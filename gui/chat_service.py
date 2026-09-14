"""ChatService —— 封装聊天逻辑，ApiWorker 异步调用，Signal 回传。

v10.15 真实性修复:
- 真流式：消费 chat_stream_chunks 生成器，按内容增量逐 emit message_chunk_received；
- 诚实报错：API 异常时不再以「女仆语气 fallback」掩盖，统一 emit message_failed；
- 演示模式显著标注：当未配置 API Key 且非 ollama 本地时，回复前缀 [模拟回复·未连接API]；
- 协作取消：取消时调用 response.close() 触发底层连接关闭；
- 关窗时正确等待：worker.stop(wait_ms=5000) 等待线程退出。
- 保留旧信号名（message_chunk_received / message_cancelled / thinking_indicator）以兼容已有面板/独立窗口连接。
"""
from __future__ import annotations

import logging
import json
import queue
import random
import re
import threading
import time
from datetime import datetime
from typing import Optional

try:
    from gui.expr_markup import MarkupStreamFilter, final_expression
except Exception:
    MarkupStreamFilter = None
    final_expression = None

from gui.qt_compat import QObject, Signal, QThread, QTimer

from core import normalize_provider

# v1.7(F10a): 群聊会话判定（gui/session_manager 纯函数，无循环依赖）
try:
    from gui.session_manager import is_group_session as _is_group_session
except Exception:
    _is_group_session = None

# v1.4.8: 用户友好错误消息
try:
    from user_messages import format_api_error, format_agent_summary
except ImportError:
    format_api_error = None
    format_agent_summary = None

# v1.6(P0-2/D-V16-04): 意图五态纯规则分类（根级 intent.py，零 Qt 依赖；
# 加载失败静默降级为恒返 "chat"，全链退化为 v1.5.2 行为）
try:
    from intent import classify_intent as _classify_intent
except Exception:
    _classify_intent = None

logger = logging.getLogger("maid_coder.gui")

# v10.15: 演示模式显著标注，避免用户误以为真的连上了 API
DEMO_LABEL = "[模拟回复·未连接API]"

# v1.6(P0-4/D-V16-08): 反套话注入文案（请求级 system 副本，不入 session.history）
ANTI_FLUFF_INJECTION = (
    "【诚实边界】较早期的对话已被精简为摘要。若主人问到已精简的内容，"
    "请如实说明'那段我们聊天的细节我记不全了，只记得大概'，并主动提议补充要点；"
    "绝不编造当时的具体原话。另外：避免重复总结、过度分点、空洞客套，"
    "回答保持自然、具体、有信息量。"
)

# v1.7(F3/D-V17-02): 深夜对话尾注（请求级 system 副本，不入 session.history）——
# 深夜时段（23:00–5:00）聊天时轻附一句休息关切提示，复用 request_injections
# 机制，零新机制、零计数语义（R-A）。
NIGHT_CARE_INJECTION = (
    "【深夜关怀】现在是深夜，如果主人的消息透着倦意，回复的结尾可以轻轻附一句"
    "休息方面的关心（一句就好，不说教、不催促）。"
)

# ---------------------------------------------------------------------------
# v1.8(V18-02/D-V18-02): F1 实体提及注入 + F2 情绪概览注入（纯函数构建器）
#
# 注入序位框架（D-V18-02/共享知识 1，全期共用）：request_injections 统一在
# intent 提示之后追加，顺序 = 实体提及 → 回应约定(F6 二批) → 场景语气(F4 三批)
# → 情绪概览(F2)（Q-D5 三层叠加：情绪激活当轮场景挂起，场景在概览前）；
# Agent / 任务 / demo 三类路径全部跳过（与 NIGHT_CARE 边界逐字一致）。注入只进请求副本，绝不写 session.history。
# 双通道拆分（⚠-2 校正）：pinned 实体走 build_memory_context（system 级常驻，
# memory.py）；**提及命中**走本文件 request_injections（每轮 ≤2 实体 × ≤120
# 字符/实体行，独立限额，与 system 级 300 字符共享预算无关）。
# ---------------------------------------------------------------------------

_ENTITY_MENTION_MAX = 2          # 每轮提及注入实体数上限
_ENTITY_LINE_MAX = 120           # 单实体注入行字符上限

# v1.8(D-V18-03/⚠-3): 情绪概览显式疑问句式词表 —— intent 五态**无 emotion 态**，
# 触发 = confide 态命中 或 本词表命中（"我最近状态怎么样"类显式发问）。
_EMOTION_OVERVIEW_QUERY_WORDS = (
    "最近怎么样", "最近状态", "状态怎么样", "状态如何", "最近好不好",
    "是不是很丧", "最近情绪", "我最近", "最近的我", "心情怎么样",
)


def build_entity_mention_injection(memory_mgr, user_text: str) -> list:
    """F1 提及命中注入行构建器（纯函数，无 Qt/服务依赖，可独立单测）。

    用户消息经 find_entities_by_name（精确子串）命中实体 → 取前 2 个，逐实体
    生成 ≤120 字符行「【关于X】关系；备注：…；最近：…」；未命中返回空表
    （零 prompt 污染，R-I payload 最小化）。
    """
    if memory_mgr is None or not user_text:
        return []
    try:
        hits = memory_mgr.find_entities_by_name(user_text)
    except Exception:
        return []
    lines: list = []
    for e in hits[:_ENTITY_MENTION_MAX]:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        line = f"【关于{e.get('name')}】{e.get('relation', '其他')}"
        notes = str(e.get("notes") or "").strip()
        if notes:
            line += f"；备注：{notes}"
        events = e.get("events") or []
        if events:
            ev_text = str(events[0].get("text", "")).strip()
            if ev_text:
                line += f"；最近：{ev_text}"
        lines.append(line[:_ENTITY_LINE_MAX])
    return lines


def build_emotion_overview_injection(memory_mgr, user_text: str,
                                     intent_state: str = "",
                                     enabled: bool = True) -> list:
    """F2 情绪概览注入构建器（纯函数；触发 = confide 态 或 显式疑问句式）。

    命中 → 附 emotion_overview(7)+emotion_overview(30) 两句纯规则模板
    （零数字零 LLM）；未问零注入（payload 最小化）。总开关
    GuiConfig.emotion_overview_enabled 关闭时恒返空表。
    """
    if memory_mgr is None or not enabled or not user_text:
        return []
    low = (user_text or "").lower()
    hit = (intent_state == "confide"
           or any(w.lower() in low for w in _EMOTION_OVERVIEW_QUERY_WORDS))
    if not hit:
        return []
    try:
        ov7 = memory_mgr.emotion_overview(7)
        ov30 = memory_mgr.emotion_overview(30)
    except Exception:
        return []
    if not ov7 and not ov30:
        return []
    parts = [s for s in (ov7, ov30) if s]
    return ["【情绪概览】" + "；".join(parts)]


def build_response_rule_injection(memory_mgr, user_text: str) -> list:
    """F6 回应约定注入构建器（V18-07/D-V18-05，纯函数，可独立单测）。

    用户消息经 match_rules（精确子串包含）命中 enabled 规则 → 逐条生成
    「【回应约定】主人说过：当他说「XX」时，请按约定回应：YY」；未命中
    零注入零成本（payload 最小化）。序位在实体提及之后（D-V18-02）。
    规则与偏好/mute 正交：规则优先于画像（约定 > 画像），mute 不抑制规则。
    """
    if memory_mgr is None or not user_text:
        return []
    try:
        hits = memory_mgr.match_rules(user_text)
    except Exception:
        return []
    lines: list = []
    for r in hits:
        if not isinstance(r, dict) or not r.get("trigger"):
            continue
        lines.append(
            f"【回应约定】主人说过：当他说「{r.get('trigger')}」时，"
            f"请按约定回应：{r.get('response') or '（按主人当时的叮嘱灵活回应）'}"
        )
    return lines


# v1.8(V18-12/D-V18-07/Q-D5): 负面情绪集合（memory.detect_emotion 输出子集）
# —— 三层叠加第①层"情绪陪伴激活"的负面信号口径（当轮 confide 命中 + 命中
# 以下之一 → 场景注入挂起；逐轮判定，无持久模式）。
_NEGATIVE_EMOTIONS = ("tired", "anxious", "lonely")


def build_scene_injection(scene_id: str, suspended: bool = False,
                          enabled: bool = True) -> list:
    """F4 场景语气注入构建器（V18-12/D-V18-07，纯函数，可独立单测）。

    enabled=False（scene_auto 关）或 suspended=True（情绪陪伴激活当轮，Q-D5
    第①层 > 第②层）→ 空表零注入；否则返回该场景一句话语气指令
    （scene.py SCENE_TONES，未收录场景回落休息档）。
    """
    if not enabled or suspended:
        return []
    try:
        import scene as scene_mod
        tone = scene_mod.scene_tone_text(scene_id)
    except Exception:
        return []
    return [tone] if tone else []


# v1.8(V18-16/D-V18-08): F7 影像记忆召回 —— 指代句式（规则）判定 + 注入构建器
#（纯函数，可独立单测）。句式口径：时间指代词 + 图像词同时在场（"上次那张图"
# "之前的截图"类）；仅规则零 token，无语义模糊匹配防误命中。
_VISION_RECALL_TIME_RE = re.compile(
    r"上次|之前|刚才|那天|昨天|前天|早前|先前|早些时候")
_VISION_RECALL_IMAGE_RE = re.compile(r"图|截图|照片|图片|相片")
# R-K 诚实边界（措辞与验收断言共用）：召回时如实说明只能记得对话内容。
_VISION_HONESTY_TEXT = (
    "（诚实边界：若主人想重新查看图片，请如实说明——"
    "我只能记得当时的对话内容，无法重新查看图片本身，也绝不编造图片内容。）")


def vision_recall_hit(user_text: str) -> bool:
    """用户消息是否命中影像召回指代句式（纯函数；发送侧再加"未带新附件"条件）。"""
    if not user_text:
        return False
    return bool(_VISION_RECALL_TIME_RE.search(user_text)
                and _VISION_RECALL_IMAGE_RE.search(user_text))


def _vision_date_label(iso_time: str) -> str:
    """ISO 时间 -> 「9-03」短标签（解析失败回空串，不阻塞注入）。"""
    try:
        dt = datetime.fromisoformat(str(iso_time))
        return f"{dt.month}-{dt.day:02d}"
    except Exception:
        return ""


def first_paragraph_digest(text: str, maxlen: int = 50) -> str:
    """回应首段摘要（影像记忆存档用）：第一个非空行截断 maxlen 字。"""
    for para in (text or "").splitlines():
        p = para.strip()
        if p:
            return p[:maxlen]
    return ""


def build_vision_recall_injection(memory_mgr, user_text: str) -> list:
    """F7 影像召回注入构建器（V18-16/D-V18-08，纯函数，可独立单测）。

    指代句式命中 → 检索影像记忆（关键词重叠 + 时间倒序 top2）→ 逐条生成
    「【之前的分享】9-03 主人发过一张图（配文：…），当时码铃回应：…」+ 尾附
    诚实边界（R-K：只能记得对话内容，无法重新查看图片本身）。零记忆时只注入
    诚实说明，绝不编造；未命中句式零注入（payload 最小化，R-I）。
    """
    if memory_mgr is None or not vision_recall_hit(user_text):
        return []
    try:
        mems = memory_mgr.query_vision_memories(keyword=user_text, limit=2)
    except Exception:
        return []
    if not mems:
        return ["【之前的分享】主人问起之前的图片，但码铃没有留下相关记录。"
                + _VISION_HONESTY_TEXT]
    lines: list = []
    for m in mems:
        if not isinstance(m, dict):
            continue
        ds = _vision_date_label(m.get("time")) or "之前"
        brief = (str(m.get("user_text") or "").strip()
                 or str(m.get("image_note") or "一张图片"))
        line = f"【之前的分享】{ds} 主人发过一张图（配文：{brief}）"
        digest = str(m.get("assistant_digest") or "").strip()
        if digest:
            line += f"，当时码铃回应：{digest}"
        lines.append(line)
    if lines:
        lines.append(_VISION_HONESTY_TEXT)
    return lines


def is_deep_night(now: Optional[datetime] = None) -> bool:
    """v1.7(F3): 深夜时段判定（23:00–次日 5:00，与 greeting 深夜段同口径）。"""
    try:
        now = now or datetime.now()
        return now.hour >= 23 or now.hour < 5
    except Exception:
        return False


# ======================================================================
# v1.7(F10a/F10b/D-V17-06): 多角色群聊 MVP —— 显示会话层功能
#
# 核心裁决：群聊完全不触碰 session.history 与 v1.5.1 人设对齐链；
# 发言 = 一次独立 LLM 调用（请求副本即时从显示会话组装、用后即弃）；
# 三隔离（共享知识 26）：不写对齐历史 / 不计亲密度 / 不做记忆提取；
# R-J 隔离：发言由调度器决定（1-2 人串行，每条用户消息 ≤2），旧 chatter
# 四道闸已退役（v1.8 收尾）。
# ======================================================================

GROUP_HISTORY_LIMIT = 60          # 群聊历史截断条数（MVP：不做 auto_summary）
GROUP_DEFAULT_NO_AT_POLICY = "rotate"  # 无@策略默认（Q-C1：轮转第一位）

# @解析（design §2.6）：@名字，对成员名精确匹配（防「@一下」误命中）
GROUP_MENTION_RE = re.compile(r"@([\u4e00-\u9fa5A-Za-z0-9_·]+)")


def parse_group_mention(text: str, name_to_id: dict) -> Optional[str]:
    """v1.7(F10a): 解析用户消息中的 @名字 → 精确匹配成员名，返回 role_id。

    未命中任何成员名（含「@一下」这类非成员词）返回 None。
    """
    for m in GROUP_MENTION_RE.finditer(text or ""):
        rid = (name_to_id or {}).get(m.group(1))
        if rid:
            return rid
    return None


# v1.7(F10b): @补全令牌（光标前缀以 @ 结尾且后续仅成员名字符 → 正在输入成员名）
GROUP_MENTION_PARTIAL_RE = re.compile(r"@([\u4e00-\u9fa5A-Za-z0-9_·]*)$")


def parse_mention_partial(text_before_cursor: str) -> Optional[str]:
    """v1.7(F10b): 解析光标前文本是否处于 @补全输入态，返回已输入的名字片段。

    返回 None = 非 @输入态（不弹补全）；返回 "" = 刚输入 @（弹全部成员）。
    """
    m = GROUP_MENTION_PARTIAL_RE.search(text_before_cursor or "")
    return m.group(1) if m else None


def mention_candidates(member_names: list, partial: str) -> list:
    """v1.7(F10b): 按已输入片段过滤成员名候选（前缀匹配，@ 后弹全部）。"""
    names = [str(n) for n in (member_names or []) if n]
    if not partial:
        return names
    return [n for n in names if n.startswith(partial)]


def apply_mention_completion(text_before_cursor: str, name: str) -> str:
    """v1.7(F10b): 计算补全后的光标前文本（@片段 → @完整名字 + 空格收尾）。"""
    m = GROUP_MENTION_PARTIAL_RE.search(text_before_cursor or "")
    if not m:
        return text_before_cursor or ""
    return text_before_cursor[:m.start()] + f"@{name} "


def build_group_system_prompt(role, other_names: list) -> str:
    """v1.7(F10a): 发言角色的 system = 该角色人设提示词 + 群聊语境段（system 唯一，R-J④）。

    只读复用 page_role.build_role_system_prompt（人设来源唯一；导入失败回退原始
    system_prompt，零写操作——F10 严禁改 page_role.py）。
    """
    name = str(getattr(role, "name", "") or "成员")
    try:
        from gui.pages.page_role import build_role_system_prompt
        base = build_role_system_prompt(
            str(getattr(role, "system_prompt", "") or ""),
            getattr(role, "personality", None),
        )
    except Exception:
        base = str(getattr(role, "system_prompt", "") or "") or f"你是{name}。"
    names = "、".join(str(n) for n in (other_names or []) if n) or "无"
    segment = (
        f"【群聊模式】你（{name}）正在与主人及其他成员的群聊中，在场成员：{names}。"
        "【名字】：前缀的消息是其他成员的发言，主人是没有前缀的消息；"
        f"只以你自己「{name}」的人设发言，绝不代替其他成员或主人发言。"
    )
    return base + "\n\n" + segment


def rewrite_group_history(messages, speaker_role, name_by_id: dict) -> list:
    """v1.7(F10a): 历史角色改写（D-V17-06 关键设计，纯函数）。

    - 发言角色自己的历史 assistant 消息保持 assistant role；
    - 其他成员的 assistant 消息改写为 user role 且前缀「【名字】：」；
    - user 消息原样 user；
    - 结果只作请求副本，用后即弃，绝不写回任何会话。
    """
    sid = getattr(speaker_role, "id", "")
    entries: list = []
    for m in messages or []:
        if isinstance(m, dict):
            role, content, meta = m.get("role"), m.get("content"), (m.get("metadata") or {})
        else:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
            meta = getattr(m, "metadata", None) or {}
        if role not in ("user", "assistant") or not content:
            continue
        if role == "user":
            entries.append({"role": "user", "content": content})
            continue
        speaker = meta.get("speaker_id")
        if speaker == sid:
            entries.append({"role": "assistant", "content": content})
        else:
            name = name_by_id.get(speaker) or "成员"
            entries.append({"role": "user", "content": f"【{name}】：{content}"})
    return entries


# ======================================================================
# v1.7(F10 自由发言调度·定案): 用户消息后轻量 LLM 调度（1-2 人串行接话）
# —— @点名保留为显式覆盖（优先级最高）；调度 JSON 解析失败/超时回退
#    turn_order 轮转 1 人（绝不让用户消息无回应）；调度 token 如实计费。
# ======================================================================

GROUP_SCHED_MAX_SPEAKERS = 2      # 每条用户消息最多 2 个角色发言（调度硬约束，R-J 适配）
GROUP_SCHED_HISTORY_LIMIT = 6     # 调度输入携带的最近群聊条数
GROUP_SCHED_MAX_TOKENS = 120      # 轻量调度请求 token 上限
GROUP_SCHED_TIMEOUT_MS = 20000    # 调度超时兜底（超时回退轮转）

_SCHEDULER_SYSTEM_PROMPT = (
    "你是群聊接话调度器。根据群聊成员和最近对话，决定用户这条消息后谁应该接话："
    "1-2 人；没人特别合适接话时也要选最相关的 1 人（用户在等回应），"
    "除非用户明显在自言自语或发文件处理中（此时输出空数组）。\n"
    f'只输出一个 JSON 对象，格式：{{"speakers": ["成员id或名字", ...], "reason": "一句话"}}，'
    "最多 2 人，不要输出任何其他内容。"
)


def build_scheduler_context(display_messages, member_roles: dict,
                            user_text: str, limit: int = GROUP_SCHED_HISTORY_LIMIT) -> str:
    """v1.7(F10): 调度输入的群聊上下文（最近 N 条，他人带【名字】：前缀）。"""
    lines: list = []
    msgs = [m for m in (display_messages or [])
            if (m.get("role") if isinstance(m, dict) else getattr(m, "role", None))
            in ("user", "assistant")]
    for m in msgs[-limit:]:
        if isinstance(m, dict):
            role, content, meta = m.get("role"), m.get("content"), (m.get("metadata") or {})
        else:
            role, content, meta = getattr(m, "role", None), getattr(m, "content", None), \
                (getattr(m, "metadata", None) or {})
        if not content:
            continue
        if role == "user":
            lines.append(f"主人：{content}")
        else:
            sid = meta.get("speaker_id")
            name = getattr((member_roles or {}).get(sid), "name", None) or "成员"
            lines.append(f"【{name}】：{content}")
    lines.append(f"主人（本轮新消息）：{user_text}")
    return "\n".join(lines)


def build_scheduler_messages(member_roles: dict, user_text: str,
                             recent_text: str) -> list:
    """v1.7(F10): 调度请求 messages（system 约束 + 成员清单 + 上下文）。"""
    roster = "\n".join(
        f'- id={rid} 名字={getattr(r, "name", "")} 人设一句话='
        f'{(getattr(r, "description", "") or getattr(r, "system_prompt", "") or "")[:40]}'
        for rid, r in (member_roles or {}).items()
    )
    user_content = (
        f"群聊成员：\n{roster or '（无）'}\n\n最近群聊：\n{recent_text}"
    )
    return [
        {"role": "system", "content": _SCHEDULER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_scheduler_reply(raw: str, member_roles: dict) -> list:
    """v1.7(F10): 解析调度回复 → 有序发言者 role_id 列表（≤2，保序去重）。

    speakers 元素按 role_id 或成员名字精确匹配；非法/未匹配项忽略；
    全部无效返回 []（调用方回退轮转，绝不丢回应）。
    """
    raw = (raw or "").strip()
    # 容错：剥掉可能的 ```json 围栏
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except Exception:
        return []
    speakers = data.get("speakers") if isinstance(data, dict) else None
    if not isinstance(speakers, list):
        return []
    id_by_name = {getattr(r, "name", ""): rid
                  for rid, r in (member_roles or {}).items() if getattr(r, "name", "")}
    out: list = []
    for item in speakers:
        key = str(item or "").strip()
        rid = key if key in (member_roles or {}) else id_by_name.get(key)
        if rid and rid not in out:
            out.append(rid)
        if len(out) >= GROUP_SCHED_MAX_SPEAKERS:
            break
    return out


def fallback_speaker(display_session, member_roles: dict):
    """v1.7(F10): 调度失败兜底 —— turn_order 轮转第一位（1 人，绝不让消息无回应）。"""
    order = [rid for rid in ((getattr(display_session, "metadata", None) or {})
                             .get("turn_order") or [])
             if rid in (member_roles or {})]
    if not order:
        order = list((member_roles or {}).keys())
    return (member_roles or {}).get(order[0]) if order else None


class GroupScheduleWorker(QThread):
    """v1.7(F10): 群聊接话调度 worker —— api.chat 单次轻量调用（严格 JSON）。

    独立于发言 ApiWorker（单槽互斥），调度完成后经 Signal 回主线程解析入队。
    """

    schedule_ready = Signal(str, str, dict)   # (req_id, content, usage)
    schedule_failed = Signal(str, str)        # (req_id, error)

    def __init__(self, api, messages: list, req_id: str,
                 max_tokens: int = GROUP_SCHED_MAX_TOKENS):
        super().__init__()
        self._api = api
        self._messages = messages
        self._req_id = req_id
        self._max_tokens = max_tokens

    def run(self):
        try:
            resp = self._api.chat(self._messages,
                                  max_tokens=self._max_tokens, temperature=0.2)
            content = ""
            try:
                content = str(resp["choices"][0]["message"]["content"] or "")
            except Exception:
                content = ""
            usage = resp.get("usage") if isinstance(resp, dict) else None
            self.schedule_ready.emit(self._req_id, content,
                                     usage if isinstance(usage, dict) else {})
        except Exception as exc:
            self.schedule_failed.emit(self._req_id, str(exc))


def _is_demo_mode(app_ctx) -> bool:
    """v10.15: 演示模式判定 —— 无 API Key 且 provider 不是 ollama 本地。

    返回 True 时调用方应使用 DEMO_LABEL 显著标注回复内容，并跳过女仆语气注入、
    会话历史写入、亲密度累加，避免误导用户。
    """
    cfg = getattr(app_ctx, "cfg", None) or getattr(app_ctx, "config", None)
    if cfg is None:
        return True
    # AppConfig 字段名为 api_provider；GuiConfig 无此字段时兜底 "openai"
    provider = getattr(cfg, "api_provider", None) or getattr(cfg, "provider", "openai") or "openai"
    if normalize_provider(provider) == "ollama":
        return False
    api_key = (getattr(cfg, "api_key", "") or "").strip()
    return not api_key


def _format_demo_payload(text: str) -> str:
    """v10.15: 演示模式显著标注的载荷格式。"""
    return f"{DEMO_LABEL}\n{text}"


def _is_technical_reply(text: str) -> bool:
    """判断回复是否技术/代码类内容（这类回复不注入女仆语气，避免违和）。"""
    t = text.lstrip()
    if not t:
        return True
    # 含代码块
    if "```" in text or "~~~" in text:
        return True
    # 以代码/命令/结构化内容开头
    code_starts = ("def ", "class ", "import ", "from ", "return ", "SELECT ", "git ",
                   "pip ", "npm ", "docker ", "```", "#!/", "<", "{\n", "[\n", "#include ")
    if t.startswith(code_starts):
        return True
    # 大段技术文本（长回复且几乎不含中文语气词）按技术处理
    if len(text) > 300 and text.count("\n") > 4:
        return True
    return False


def inject_maid_tone(text: str, app_ctx) -> str:
    """为 AI 回复注入女仆语气。v1.1 合理化：

    - 演示模式、女仆模式关闭 → 不注入（v10.15 行为保留）；
    - 技术/代码类回复 → 不注入（避免「主人~ ```python」违和）；
    - 自然对话 → 低频注入：约 15% 加轻前缀，10% 加轻后缀，不叠加颜文字堆砌。
    """
    if _is_demo_mode(app_ctx):
        return text
    config = getattr(app_ctx, "config", None)
    if config is None or not getattr(config, "maid_mode", True):
        return text
    if _is_technical_reply(text):
        return text
    # 轻量前缀池（只取自然口语化的前缀，去掉高频「主人~」）
    light_prefixes = ["主人，", "主人~ ", "码铃来啦：", ""]
    # 后缀只在语气自然时低频加，且不叠加过多符号
    light_suffixes = ["", "", " ~", " 需要我帮您改哪里吗？", " 有需要随时喊我"]
    if random.random() < 0.15:
        prefix = random.choice(light_prefixes)
        if prefix and not text.startswith(("主人", "码铃")):
            text = prefix + text
    if random.random() < 0.10:
        suffix = random.choice(light_suffixes)
        if suffix and not text.endswith(("~", "吗？", "。", "！", "?")):
            text = text + suffix
    return text


class ApiWorker(QThread):
    """后台调用 API，v10.15: 真流式 + 协作取消 + 关窗时正确等待。

    通过 chat_stream_chunks 生成器逐块产出 content delta，
    每块通过 message_chunk_received Signal 推回主线程做真实流式渲染。
    """

    message_stream_started = Signal()
    message_chunk_received = Signal(str)
    message_stream_finished = Signal(str, dict)
    message_cancelled = Signal()
    thinking_indicator = Signal(bool)
    message_failed = Signal(str)  # v10.15: 新增 —— API 错误冒泡
    expression_picked = Signal(str)  # v1.4.2: AI 自选表情（流中捕获，正文前切换）
    # v1.1(agent): 工具轨迹事件 —— (event_type, json_str)；event_type ∈ llm_start/tool_call/tool_done/tool_denied/final/max_steps
    agent_tool_event = Signal(str, str)
    # v1.5.0: GUI 联网检索完成 —— (result_count)；UI 在流式气泡前插小字提示
    web_search_done = Signal(int)

    def __init__(self, api, messages, task_config: dict, app_ctx, on_session_used=None,
                 expr_filter: bool = False):
        super().__init__()
        self._api = api
        self._messages = messages
        self._task_config = task_config or {}
        self._app_ctx = app_ctx
        # v1.4.2: AI 自选表情协议 —— 流式过滤 [[表情:xxx]] 标记（零穿帮）+ 完成时提取
        self._expr_filter = None
        if expr_filter and MarkupStreamFilter is not None:
            # 捕获到标记立即经信号广播（跨线程安全）→ 表情先于正文切换
            self._expr_filter = MarkupStreamFilter(on_expression=self.expression_picked.emit)
        self.captured_expression = None
        self._on_session_used = on_session_used
        self._stop_current = False
        self._current_user_text = (task_config or {}).get("user_text", "")
        # v10.15: 保存当前 response 对象用于取消时关闭底层连接
        self._active_response = None
        self._demo_mode = _is_demo_mode(app_ctx)
        # 演示模式的固定回复模板（让用户在没有 API 时也能感受到界面响应）
        self._demo_templates = [
            "这是一个模拟回复。当前未配置 API Key，请在「设置 → API」中填写后再启用真实对话。",
            "（演示模式）我可以陪主人聊天，但需要先在设置里配置 API Key 才能真正作答。",
            "主人~ 这是码铃的演示回复。请打开 设置 → API 填入 Key 即可解锁真实回答。",
        ]

    def stop_current(self):
        """请求停止当前流式任务；会调用 _active_response.close() 触发底层连接关闭。"""
        self._stop_current = True
        if self._active_response is not None:
            try:
                close = getattr(self._active_response, "close", None)
                if callable(close):
                    close()
            except Exception as e:
                logger.debug("关闭底层 response 异常（可忽略）: %s", e)

    def run(self):
        self.thinking_indicator.emit(True)
        try:
            task_type = self._task_config.get("task_type")
            # v1.4.7: 任务模式（managed_task）走步骤化执行引擎
            if task_type == "managed_task" and not self._demo_mode:
                self._run_managed_task()
                return
            # v1.1(agent): AgentEngine 模式（task_type == "agent"）走工具循环
            if task_type == "agent" and not self._demo_mode:
                # v1.7.2(T3): 编程引擎分流（GuiConfig.coding_engine，默认内置）。
                # managed_task 不分流——任务模式/自愈/断点恢复本期仍走内置引擎。
                gui_cfg = getattr(self._app_ctx, "config", None)
                engine = str(getattr(gui_cfg, "coding_engine", "agent") or "agent")
                if engine == "pi":
                    self._run_pi_agent()
                    return
                self._run_agent()
                return
            # v1.7(F4/D-V17-03): 提醒 LLM 兜底解析（单次 JSON，失败诚实零编造）
            if task_type == "remind_parse" and not self._demo_mode:
                self._run_remind_parse()
                return
            self.message_stream_started.emit()
            if self._demo_mode:
                # 演示模式：不调 API，按字符级流式推送一段模板回复
                self._run_demo()
                return
            # 真实流式：消费 chat_stream_chunks 生成器
            self._run_stream()
        except Exception as e:
            logger.exception("ApiWorker 运行异常: %s", e)
            if format_api_error is not None:
                err = format_api_error(e)
            else:
                err = f"⚠️ 请求失败：{e}\n请检查 API Key / 网络 / 厂商 URL"
            self.message_failed.emit(err)
            self.thinking_indicator.emit(False)

    def _run_remind_parse(self):
        """v1.7(F4/D-V17-03): 提醒 LLM 兜底解析（单次调用，规则层 low 时进入）。

        成功 → 登记 todos + 确认句（正常链落 assistant 气泡）；
        失败/JSON 不合法/时间在过去 → 诚实文案（**零 due_at 写入，绝不编造**）。
        """
        try:
            from reminders import (REMIND_FAIL_TEXT, build_confirm_text,
                                   parse_llm_when)
        except Exception:
            self.message_failed.emit("⚠️ 提醒模块加载失败，请重启应用")
            self.thinking_indicator.emit(False)
            return
        self.message_stream_started.emit()
        try:
            prompt = (
                "从下面这句话里解析出提醒时间和提醒内容，只输出一个 JSON 对象："
                '{"datetime": "YYYY-MM-DD HH:MM", "text": "提醒内容"}。'
                "如果无法确定具体日期或时刻，不要输出 JSON，只输出 FAIL 两个字。"
                f"\n当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"
                f"\n句子：{self._current_user_text}"
            )
            resp = self._api.chat(
                [{"role": "user", "content": prompt}],
                max_tokens=100, temperature=0)
            content = ""
            try:
                content = str(resp["choices"][0]["message"]["content"] or "")
            except Exception:
                content = ""
            parsed = parse_llm_when(content)
            if parsed is None:
                # 诚实回退：确定性文案，绝不编造时间，零写入
                self.message_stream_finished.emit(REMIND_FAIL_TEXT, {})
                self.thinking_indicator.emit(False)
                return
            todo = None
            session = getattr(self._app_ctx, "session", None)
            todo = getattr(session, "todo_mgr", None)
            if todo is None:
                from managers import TodoManager
                cfg = getattr(self._app_ctx, "cfg", None)
                todo = TodoManager(str(getattr(cfg, "todos_file", "") or "todos.json"))
            todo.add_reminder(parsed["remind_text"], parsed["due_at"])
            self.message_stream_finished.emit(
                build_confirm_text(parsed["due_at"], parsed["remind_text"]), {})
        except Exception as e:
            # LLM 兜底链路异常（网络/超时等）→ 同样诚实回退，零写入
            logger.warning("remind_parse 兜底失败（诚实回退）: %s", e)
            self.message_stream_finished.emit(REMIND_FAIL_TEXT, {})
        finally:
            self.thinking_indicator.emit(False)

    def _run_agent(self):
        """AgentEngine 模式：后台线程里跑工具循环。
        v1.4.7: 最终回答阶段走流式 —— content delta 通过 message_chunk_received
        实时推送给 GUI（打字机效果），工具执行阶段仍为阻塞态（thinking indicator）。
        事件通过 agent_tool_event 信号推回主线程（工具轨迹 UI）。
        """
        from agent_engine import AgentEngine
        from agent_tools import AgentTools
        from core import AppConfig as _AppConfig  # noqa
    
        app_ctx = self._app_ctx
        cfg = getattr(app_ctx, "cfg", None)
        if cfg is None or not hasattr(cfg, "api_url"):
            err = "⚠️ Agent 模式需要 AppConfig（请通过 CLI 侧配置启动），当前不可用。"
            self.message_failed.emit(err)
            self.thinking_indicator.emit(False)
            return
    
        # 复用 app_ctx 缓存的 AgentTools；首次创建时注入 GUI 授权确认回调
        tools = getattr(app_ctx, "agent_tools", None)
        if tools is None:
            tools = AgentTools(cfg, logger, confirm_fn=self._make_gui_confirm_fn())
            app_ctx.agent_tools = tools
    
        def on_event(ev: str, data: dict):
            try:
                import json as _json
                self.agent_tool_event.emit(ev, _json.dumps(data, ensure_ascii=False))
            except Exception:
                pass
    
        # v1.4.7: 流式 content delta 回调 —— 最终回答阶段逐块推送给 GUI
        _stream_started = [False]
    
        def on_content_chunk(chunk: str):
            try:
                if not _stream_started[0]:
                    self.message_stream_started.emit()
                    _stream_started[0] = True
                self.message_chunk_received.emit(chunk)
            except Exception:
                pass
    
        # system prompt：优先取 task_config 传入的 agent_system（主线程快照），
        # 避免后台线程直接读 session 对象造成跨线程访问。
        # v1.1(B1): 找不到 current_system 时的兗底说明当前可用工具与授权规则，
        # 让没有自定义 system prompt 的会话也能正确约束 Agent 行为。
        system_prompt = self._task_config.get("agent_system", "") or ""
        if not system_prompt:
            system_prompt = (
                "你是主人的专属贴身女仆码铃，技术问题专业且自信。"
                "你可以调用以下工具帮助主人完成任务：\n"
                "- 只读类：read_file（读取文件）、list_dir（列出目录）、git_status（查看 Git 状态）、git_diff（查看 Git 改动）、web_search（联网搜索）；\n"
                "- 修改类：write_file（写入/覆写文件）、git_commit（Git 提交）、run_python（沙箱执行 Python）。\n"
                "注意：修改类操作必须先征得主人授权；若授权被拒绝，请尊重主人意愿改用建议方案，不要强行重试或绕过授权。"
                "任务完成后用中文总结结果。"
            )
    
        engine = AgentEngine(
            self._api, cfg, logger, tools=tools,
            on_event=on_event,
            cancel_check=lambda: self._stop_current,
            max_steps=getattr(cfg, "agent_max_steps", 8),
            on_content_chunk=on_content_chunk,
        )
    
        user_text = self._current_user_text
        # 历史 = _messages 去掉尾部本轮的 user（engine.run 会把 user_text 单独追加）
        history = [dict(m) for m in self._messages]
        # 找到最后一个 user 的下标并截断（该条即本轮输入，交给 engine 追加）
        cut = len(history)
        for i in range(len(history) - 1, -1, -1):
            if history[i].get("role") == "user":
                cut = i
                break
        history = history[:cut]
        history = [m for m in history if m.get("role") in ("user", "assistant") and m.get("content")]
    
        full = engine.run(system_prompt, history, user_text)
        if self._stop_current:
            self.message_stream_finished.emit(full or "（已取消）", {"cancelled": True})
        else:
            self.message_stream_finished.emit(full, {"agent": True})
        self.thinking_indicator.emit(False)

    def _run_pi_agent(self):
        """v1.7.2(T3): Pi 编程引擎路径 —— Agent 模式且 coding_engine=="pi" 时，
        经 pi_backend.PiRpcSession（RPC 子进程）执行同一任务。

        与 _run_agent 同一套 GUI 信号协议：流式 chunk / 工具轨迹事件 /
        授权弹窗桥（_make_gui_confirm_fn）全部复用；停止按钮 → RPC abort。
        managed 任务不走本路径（试点范围排除，见 pi_backend.py 模块注释）。
        """
        try:
            from pi_backend import PiRpcSession
        except Exception as e:
            self.message_failed.emit(f"⚠️ Pi 编程引擎模块加载失败：{e}")
            self.thinking_indicator.emit(False)
            return

        app_ctx = self._app_ctx
        cfg = getattr(app_ctx, "cfg", None)
        if cfg is None or not hasattr(cfg, "api_url"):
            err = "⚠️ Pi 引擎需要 AppConfig（请通过 CLI 侧配置启动），当前不可用。"
            self.message_failed.emit(err)
            self.thinking_indicator.emit(False)
            return

        def on_event(ev: str, data: dict):
            try:
                import json as _json
                self.agent_tool_event.emit(ev, _json.dumps(data, ensure_ascii=False))
            except Exception:
                pass

        _stream_started = [False]

        def on_chunk(chunk: str):
            try:
                if not _stream_started[0]:
                    self.message_stream_started.emit()
                    _stream_started[0] = True
                self.message_chunk_received.emit(chunk)
            except Exception:
                pass

        session = None
        self._stop_current = False
        try:
            session = PiRpcSession(
                cfg,
                workspace=str(getattr(cfg, "workspace", ".") or "."),
                confirm_fn=self._make_gui_confirm_fn(),
                on_chunk=on_chunk,
                on_tool_call=lambda name, data: on_event("tool_call", data),
                on_tool_done=lambda name, data: on_event("tool_done", data),
            )
            session.start()
            result = session.prompt(
                self._current_user_text,
                cancel_check=lambda: self._stop_current,
            )
            full = result.get("text", "")
            payload = {"agent": True, "engine": "pi",
                       "usage": result.get("usage", {})}
            if result.get("aborted") or self._stop_current:
                payload["cancelled"] = True
            if not _stream_started[0]:
                self.message_stream_started.emit()
            self.message_stream_finished.emit(full or "（无输出）", payload)
        except Exception as e:
            logger.exception("Pi 引擎任务异常: %s", e)
            if self._stop_current:
                self.message_stream_finished.emit("（已取消）", {"cancelled": True})
            else:
                self.message_failed.emit(f"⚠️ Pi 引擎执行失败：{e}\n"
                                         "可在 设置 → Agent 设置 把编程引擎切回「内置 Agent」。")
        finally:
            self.thinking_indicator.emit(False)
            if session is not None:
                session.stop()

    def _run_managed_task(self):
        """v1.4.7: 任务模式 —— 调用 AgentEngine.run_managed_task() 步骤化执行。

        流程：LLM 拆解步骤 → 逐步执行（工具子循环）→ 失败自愈 → 断点恢复。
        事件通过 agent_tool_event 推回主线程（工具轨迹卡片已支持 task_plan/step_start 等事件）。
        最终结果汇总为一段文本通过 message_stream_finished 返回。
        """
        from agent_engine import AgentEngine
        from agent_tools import AgentTools

        app_ctx = self._app_ctx
        cfg = getattr(app_ctx, "cfg", None)
        if cfg is None or not hasattr(cfg, "api_url"):
            err = "⚠️ 任务模式需要 AppConfig，当前不可用。"
            self.message_failed.emit(err)
            self.thinking_indicator.emit(False)
            return

        # 复用/创建 AgentTools（注入 GUI 授权确认回调）
        tools = getattr(app_ctx, "agent_tools", None)
        if tools is None:
            tools = AgentTools(cfg, logger, confirm_fn=self._make_gui_confirm_fn())
            app_ctx.agent_tools = tools

        def on_event(ev, data):
            try:
                import json as _json
                self.agent_tool_event.emit(ev, _json.dumps(data, ensure_ascii=False))
            except Exception:
                pass

        def on_content_chunk(chunk):
            try:
                self.message_chunk_received.emit(chunk)
            except Exception:
                pass

        engine = AgentEngine(
            self._api, cfg, logger, tools=tools,
            on_event=on_event,
            cancel_check=lambda: self._stop_current,
            max_steps=getattr(cfg, "agent_max_steps", 8),
            on_content_chunk=on_content_chunk,
        )

        goal = self._current_user_text
        self.message_stream_started.emit()

        try:
            task_run = engine.run_managed_task(goal)
        except Exception as e:
            logger.exception("managed task 异常: %s", e)
            if format_api_error is not None:
                err = format_api_error(e, context="任务执行失败")
            else:
                err = f"⚠️ 任务执行失败：{e}"
            self.message_failed.emit(err)
            self.thinking_indicator.emit(False)
            return

        # 汇总结果为文本
        status = getattr(task_run, "status", "failed")
        summary = getattr(task_run, "summary", {})
        steps = getattr(task_run, "steps", [])
        goal_text = getattr(task_run, "goal", goal)

        if format_agent_summary is not None:
            result_text = format_agent_summary(status, goal_text, steps, summary)
        else:
            # fallback: 旧版硬编码格式
            if status == "done":
                result_text = f"✅ 任务完成！\n\n目标：{goal_text}\n共 {len(steps)} 个步骤，全部通过。"
                if summary.get("current_blocker"):
                    result_text += f"\n备注：{summary['current_blocker']}"
            elif status == "paused":
                result_text = f"⏸️ 任务已暂停（断点恢复）\n\n目标：{goal_text}\n可随时继续执行。"
            else:
                blocker = summary.get("current_blocker", "未知原因")
                result_text = f"⚠️ 任务未完成\n\n目标：{goal_text}\n卡点：{blocker}"
                passed = sum(1 for s in steps if getattr(s, "status", "") == "passed")
                result_text += f"\n已完成 {passed}/{len(steps)} 步。"

        if self._stop_current:
            self.message_stream_finished.emit(result_text, {"cancelled": True})
        else:
            self.message_stream_finished.emit(result_text, {"agent": True, "managed_task": True})
        self.thinking_indicator.emit(False)

    def _run_demo(self):
        """演示模式：以字符级流式推送一段固定模板，带显著标注前缀。"""
        body = random.choice(self._demo_templates)
        full = _format_demo_payload(body)
        chunks = [full[i:i + 3] for i in range(0, len(full), 3)]
        for ch in chunks:
            if self._stop_current:
                self.message_stream_finished.emit(full, {"cancelled": True})
                self.thinking_indicator.emit(False)
                return
            time.sleep(0.04)
            self.message_chunk_received.emit(ch)
        self.message_stream_finished.emit(full, {"demo": True})
        self.thinking_indicator.emit(False)

    def _run_stream(self):
        """真实流式：消费 chat_stream_chunks 增量并按真实节奏 emit。"""
        # v1.5.0: GUI「🌐 联网」检索 —— 在 worker 线程执行（不阻塞 UI，6s 超时），
        # 命中结果则向 messages 尾部注入一条 system 上下文（与 CLI single_turn 注入模式一致），
        # 并广播 web_search_done 供 UI 插提示。失败静默降级为直答（绝不阻塞回复）。
        ws_query = str(self._task_config.get("web_search_query") or "").strip()
        if ws_query:
            try:
                from helpers import WebSearch as _WebSearch
                results = _WebSearch().search(ws_query)
                good = [r for r in results if r.get("href")]
                if good:
                    self._messages = list(self._messages) + [{
                        "role": "system",
                        "content": "[联网搜索上下文]\n" + _WebSearch().format_results(good),
                    }]
                    try:
                        self.web_search_done.emit(len(good))
                    except Exception:
                        pass
            except Exception:
                logger.debug("GUI 联网检索失败（忽略，继续直答）", exc_info=True)
        try:
            chunks_iter = self._api.chat_stream_chunks(
                self._messages,
                cancel_check=lambda: self._stop_current,
                on_response=lambda r: setattr(self, "_active_response", r),
            )
        except TypeError:
            # 旧版 API 不支持 cancel_check / on_response（向后兼容）
            chunks_iter = self._api.chat_stream_chunks(self._messages)

        accumulated: list[str] = []
        cancelled = False
        try:
            for delta in chunks_iter:
                if not delta:
                    continue
                accumulated.append(delta)
                # v1.4.2: 表情标记流式过滤（跨 chunk 状态机，零穿帮）
                if self._expr_filter is not None:
                    visible = self._expr_filter.feed(delta)
                    if visible:
                        self.message_chunk_received.emit(visible)
                else:
                    self.message_chunk_received.emit(delta)
            if self._expr_filter is not None:
                _tail = self._expr_filter.flush()
                if _tail:
                    self.message_chunk_received.emit(_tail)
        except Exception as e:
            type_name = type(e).__name__
            if "StreamCancelled" in type_name or self._stop_current:
                cancelled = True
            else:
                logger.exception("流式响应异常: %s", e)
                if format_api_error is not None:
                    err = format_api_error(e, context="流式响应中断")
                else:
                    err = f"⚠️ 流式响应中断：{e}\n请检查 API Key / 网络 / 厂商 URL"
                # v1.2.x(看图): 本轮回传了图片却报错 → 大概率模型不支持视觉
                if self._task_config.get("vision"):
                    err += ("\n\n💡 本次消息附带了图片，但当前模型/接口可能不支持图片输入。"
                            "看图需要支持视觉的多模态模型（OpenAI 兼容端点），例如智谱 GLM-4V、"
                            "通义 qwen-vl、OpenAI GPT-4o 系列等；DeepSeek 官方接口为纯文本模型，"
                            "不支持发图。可在「设置 → 模型与接口」切换支持视觉的厂商后重发。")
                self.message_failed.emit(err)
                self.thinking_indicator.emit(False)
                return

        full_raw = "".join(accumulated)
        # v1.4.2: 剥离表情标记 + 提取 AI 自选表情（双保险，流式过滤已吞绝大多数）
        if final_expression is not None:
            try:
                full, _ids, ai_expr = final_expression(full_raw)
            except Exception:
                full, ai_expr = full_raw, None
        else:
            full, ai_expr = full_raw, None
        self.captured_expression = ai_expr
        usage: dict = {}
        # v1.2.x(token): 把 API 流式末帧携带的 token 用量带出（此前恒为空 {}）
        try:
            _api_usage = getattr(self._api, "_last_stream_usage", None) or {}
            for _k in ("total_tokens", "prompt_tokens", "completion_tokens"):
                if isinstance(_api_usage, dict) and _api_usage.get(_k):
                    usage[_k] = _api_usage[_k]
        except Exception:
            logger.debug("读取流式 token usage 失败（可忽略）", exc_info=True)
        if cancelled:
            self.message_cancelled.emit()
        else:
            _meta = dict(usage)
            if ai_expr:
                _meta["ai_expression"] = ai_expr
            self.message_stream_finished.emit(full, _meta)
        self.thinking_indicator.emit(False)


class ChatService(QObject):
    """聊天服务 —— 在主线程持有会话状态、调用 ApiWorker、转发信号。

    v10.15:
- 新增 message_failed 信号（API 错误时 emit，区别于流式结束）；
- 演示模式回复跳过女仆语气注入 / 会话写入 / 亲密度累加；
- 关窗时调用 worker.stop(wait_ms=5000) 真正等待线程退出。
    """

    message_stream_started = Signal()
    message_chunk_received = Signal(str)
    message_stream_finished = Signal(str, dict)
    message_cancelled = Signal()
    thinking_indicator = Signal(bool)
    message_failed = Signal(str)  # v10.15: 新增
    user_message_added = Signal(str)
    session_changed = Signal()
    # v1.1(agent): 工具轨迹事件转发（ChatPanel 订阅后渲染工具卡片）
    agent_tool_event = Signal(str, str)
    # v1.1(agent): 修改类工具授权请求 —— (action_desc, tool_name)，主线程弹窗确认
    agent_authorization_requested = Signal(str, str)
    # v10.14: 好感度变化信号（保留以兼容 v10.14 回归断言与 main_window 连线）
    intimacy_changed = Signal(str)
    # v1.2(A9): 主动陪伴消息就绪 —— (text, scene)；scene ∈ idle_hello/low_emotion/agent_revisit。
    # 主面板 / 独立浮窗订阅后渲染 assistant 气泡；托盘静默气泡由订阅方另发。
    proactive_message = Signal(str, str)
    # v1.4(B1b): 屏幕类消息就绪 —— (text, scene)；scene ∈ screen_peek/screen_notice/screen_action。
    # 渲染仍走 gui_session.message_added 单入口；本信号只供 UI 额外消费（托盘不订阅 → 不 toast，R-C）。
    screen_bubble_ready = Signal(str, str)
    # v1.5.0: 联网检索提示就绪 —— (notice_text)；面板在流式气泡前插一条小字提示
    web_search_notice = Signal(str)
    # v1.6(P0-3/D-V16-05): 反馈三键内容源就绪 —— (subject, scene)；subject 为空串
    # 表示纯模板问候（订阅方不渲染三键）。proactive_message 之后紧接着发出。
    proactive_feedback_ready = Signal(str, str)

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._worker: Optional[ApiWorker] = None
        self._current_msg_id: Optional[str] = None
        self._current_user_text: str = ""
        self._current_task_type: str = "chat"
        # v1.8(V18-15/D-V18-08): F7 影像记忆暂存 —— _on_stream_finished 无 payload
        # 入参，发送时把"本轮带图"事实暂存服务层（_current_user_text 同款模式），
        # 流式成功时读用；只存对话事实（user_text/中性描述），绝不存图像数据（R-I）。
        self._pending_vision: Optional[dict] = None
        self._stop_requested = False
        self._agent_mode = False
        # v1.6(P0-4/D-V16-07): 失败保留链 —— 上次失败现场 + 连续失败计数
        self._last_failure: Optional[dict] = None   # {"text","task_type","attachments","ts"}
        self._fail_streak: int = 0
        # R1（Bug1 修复）：user 回声抑制开关 —— UI 端（chat_panel/chat_window）在
        # gui_session.message_added 回声里读本属性决定是否跳过重复渲染；
        # 置位窗口见 _launch_worker 中同步写 session 的前后括号。
        self.echo_suppressed = False
        # v1.1(agent): 授权确认跨线程桥 —— worker 线程等待主线程弹窗结果
        self._auth_lock = threading.Lock()
        self._auth_pending: Optional[dict] = None  # {"event": threading.Event, "result": bool}
        # v1.7(F10a/D-V17-06): 群聊发言调度状态（串行单 worker；显示会话层隔离）
        self._group_active = False
        self._group_speaker_id: Optional[str] = None
        self._group_display_session = None
        self._group_was_interject = False
        # v1.7(F10 自由发言调度): 本轮待发言队列 + 轻量调度状态
        self._group_speaker_queue: list = []       # 本轮剩余发言者 role_id（串行接话）
        self._group_sched_seq = 0                  # 调度请求序号（防过期回调）
        self._group_sched_req_id = ""
        self._group_sched_state: Optional[dict] = None  # {"session","member_roles"}
        self._group_sched_worker = None
        self._group_sched_timer: Optional[QTimer] = None

    # ----- v1.1(agent): 授权确认桥 -----
    def _make_gui_confirm_fn(self):
        """构造 AgentTools 的 confirm_fn（在 ApiWorker 后台线程被调用）。

        工作方式：
        - 发 agent_authorization_requested 信号（Qt 自动排队到主线程），
          ChatPanel 订阅后弹 QMessageBox，并调用 resolve_agent_authorization() 回答；
        - 本线程阻塞等待；用户点"停止"或等待超时（180s）一律按拒绝处理（fail-safe）。
        """
        def _confirm(action_desc: str, tool_name: str) -> bool:
            ev = threading.Event()
            with self._auth_lock:
                self._auth_pending = {"event": ev, "result": False}
            try:
                self.agent_authorization_requested.emit(action_desc, tool_name)
            except Exception:
                pass
            # 等待主线程回答；每 200ms 轮询一次停止请求
            waited = 0.0
            while not ev.wait(0.2):
                waited += 0.2
                if self._stop_requested or waited >= 180.0:
                    with self._auth_lock:
                        self._auth_pending = None
                    return False
            with self._auth_lock:
                result = bool(self._auth_pending["result"]) if self._auth_pending else False
                self._auth_pending = None
            return result

        return _confirm

    def resolve_agent_authorization(self, approved: bool) -> None:
        """主线程（ChatPanel 弹窗后）调用：把用户选择回传给等待中的 worker。"""
        with self._auth_lock:
            pending = self._auth_pending
            if pending is not None:
                pending["result"] = bool(approved)
                pending["event"].set()

    # ----- public -----

    def _mark_user_activity(self) -> None:
        """v1.2(A9): 用户真实交互打点 -> ProactiveScheduler（缺省空转）。

        只在用户发送路径调用；主动消息走 proactive_ask，绝不触发本方法（防自续命）。
        """
        scheduler = getattr(self._app_ctx, "proactive_scheduler", None)
        if scheduler is None:
            return
        try:
            if hasattr(scheduler, "mark_user_activity"):
                scheduler.mark_user_activity()
        except Exception as exc:
            logger.debug("proactive mark_user_activity 失败（可忽略）: %s", exc)

    def send_message(self, user_text: str, task_type: str = "chat", suppress_echo: bool = False,
                     attachments: Optional[list] = None,
                     intent_mode: Optional[str] = None):
        """主线程入口：把请求入队，由 _drain 调度 ApiWorker。

        task_type="agent" 时走 AgentEngine 工具循环（Agent 模式）。
        suppress_echo: 与现有面板调用约定一致 —— 面板/独立窗口自己渲染 user 气泡，
        避免服务层再 emit 一次造成双气泡（保留旧信号以避免破坏现有调用点）。
        attachments: v1.2.x(看图) 附件原始列表 {name,path,size,ext}；其中图片在
        模型支持视觉时以 data URI 原图直传（OpenAI 多模态 content），非图片仍走文本摘要。
        intent_mode: v1.6(P0-2) 手动意图选态（面板下拉覆盖自动识别）；None/"auto"
        走 GuiConfig.chat_intent_mode，仍为 "auto" 时纯规则自动识别。**只附加不接管**：
        命中非 chat 态仅在请求副本附加语气提示（消息流绝不改道）。
        """
        if not user_text or not user_text.strip():
            return
        self._mark_user_activity()  # v1.2(A9): 用户真实交互 -> 重置主动陪伴空闲计时
        self._note_owner_emotion(user_text)  # v1.2(A1/A9): 主人情绪采集（detect_emotion -> companion）
        # v1.7(F4/D-V17-03): 贴身提醒录入拦截（intent 路由之前；仅普通聊天路径，
        # Agent/任务/demo 显式路径不受影响——demo 在分支内降级为默认时刻登记）
        if task_type == "chat" and not self._agent_mode:
            try:
                from reminders import is_remind_list_request, is_remind_request
                if is_remind_list_request(user_text):
                    if self._handle_remind_list(user_text, suppress_echo):
                        return
                elif is_remind_request(user_text):
                    if self._handle_remind_request(user_text, suppress_echo):
                        return
            except Exception:
                logger.debug("提醒分支判定失败（按普通聊天处理）", exc_info=True)
        self._stop_requested = False
        self._pending_vision = None  # v1.8(V18-15): 每轮发送先清暂存（防陈旧串档）
        self._current_user_text = user_text
        self._current_task_type = task_type
        # v1.8(V18-15/D-V18-08): 单聊带图 → 暂存影像记忆事实（仅 chat 且非
        # Agent 模式；Agent/任务模式图片被忽略不存；demo 不存；群聊走独立入口）。
        if task_type == "chat" and not self._agent_mode \
                and self._has_image_attachment(attachments) \
                and not _is_demo_mode(self._app_ctx):
            self._pending_vision = {"user_text": user_text,
                                    "image_note": "用户分享了一张图片"}
        # v1.6(P0-2/D-V16-04): 前置意图路由 —— Agent 显式开启 / task_type != "chat"
        #（任务模式、单步操作等显式路径）/ demo 三类路径完全跳过路由（Q-B2，
        # 显式开关绝对优先，与 v1.5.2 行为逐字一致）。
        intent_state = self._route_intent(user_text, task_type, intent_mode)
        request_injections: list = []
        if intent_state:
            try:
                from gui.intent import INTENT_HINTS
                hint = INTENT_HINTS.get(intent_state) or ""
                if hint:
                    request_injections.append(hint)
            except Exception:
                request_injections = []
        # v1.8(V18-02/D-V18-02): 注入序位框架 —— intent 提示之后依序追加：
        # 实体提及(F1) → 回应约定(F6，第二批挂点) → 场景语气(F4/V18-12) →
        # 情绪概览(F2)（Q-D5 三层叠加：情绪激活当轮场景挂起，故场景在概览前）。
        # 仅普通聊天路径；Agent / 任务 / demo 三类路径全部跳过
        #（与 NIGHT_CARE 边界逐字一致，R-J 隔离）。
        if task_type == "chat" and not self._agent_mode:
            try:
                if not _is_demo_mode(self._app_ctx):
                    mmgr = self._v18_memory_mgr()
                    cfg18 = getattr(self._app_ctx, "config", None)
                    for line in build_entity_mention_injection(mmgr, user_text):
                        request_injections.append(line)
                    # ② 回应约定注入（F6/V18-07）：命中触发词当轮注入（规则>偏好）
                    for line in build_response_rule_injection(mmgr, user_text):
                        request_injections.append(line)
                    # ③ 场景语气注入（F4/V18-12/D-V18-07）：scene_auto 总开关
                    # （默认 True）；Q-D5 三层叠加 —— 情绪陪伴激活当轮
                    #（confide 命中 + 负面信号）场景挂起，退出即恢复（逐轮判定）；
                    # 切换当轮双动作②：幂等边界消息写入 LLM 历史（⚠-5）。
                    scene_enabled = bool(getattr(cfg18, "scene_auto", True))
                    if scene_enabled:
                        import scene as scene_mod
                        mo = scene_mod.resolve_manual_override(
                            str(getattr(cfg18, "manual_scene", "") or ""),
                            str(getattr(cfg18, "manual_scene_date", "") or ""))
                        scene_now = scene_mod.current_scene(
                            datetime.now(), mo)
                        negative = False
                        if mmgr is not None and intent_state == "confide":
                            try:
                                negative = (mmgr.detect_emotion(user_text)
                                            in _NEGATIVE_EMOTIONS)
                            except Exception:
                                negative = False
                        for line in build_scene_injection(
                                scene_now, suspended=negative, enabled=True):
                            request_injections.append(line)
                        self._apply_scene_boundary(scene_now)
                    # ④ 情绪概览注入（F2/V18-03）：confide/疑问句式命中当轮注入
                    for line in build_emotion_overview_injection(
                            mmgr, user_text, intent_state,
                            enabled=bool(getattr(cfg18, "emotion_overview_enabled", True))):
                        request_injections.append(line)
                    # ⑤ 影像召回注入（F7/V18-16/D-V18-08）：指代句式命中且本轮
                    # 未带新附件时注入（带新图当轮是新分享，不召回）；
                    # 尾附 R-K 诚实边界，零记忆时只注入诚实说明不编造。
                    if not attachments:
                        for line in build_vision_recall_injection(mmgr, user_text):
                            request_injections.append(line)
                    self._v18_entity_propose_hook(user_text)  # V18-04 提议-确认挂点（默认关）
            except Exception:
                logger.debug("v1.8 实体/概览注入判定失败（按无注入处理）", exc_info=True)
        # v1.7(F3/D-V17-02): 深夜时段对话尾注（请求级副本，独立于意图路由；
        # 只在聊天路径附加，Agent/任务/demo 路径零改动）
        # v1.8(V18-12/D-V18-07 标红项): 睡前场景与 NIGHT_CARE 合并判定防双注入
        # —— 当前场景 = 睡前（scene_auto 开启时）→ 跳过 NIGHT_CARE append
        #（睡前语气已含"温柔安静"底色；22:30 交叉点两者同时在场必双注入）。
        if task_type == "chat" and request_injections is not None and not self._agent_mode:
            try:
                if (not _is_demo_mode(self._app_ctx)) and is_deep_night() \
                        and not self._scene_is_sleep():
                    request_injections.append(NIGHT_CARE_INJECTION)
            except Exception:
                pass
        if not suppress_echo:
            self.user_message_added.emit(user_text)
        self._enqueue_request({"kind": "send", "text": user_text, "task_type": task_type,
                               "suppress_echo": suppress_echo, "attachments": attachments or [],
                               "intent_state": intent_state,
                               "request_injections": request_injections})

    # ----- v1.7(F4/D-V17-03): 贴身提醒录入 -----

    def _todo_mgr(self):
        """todos.json 单源（session.todo_mgr 优先，回落 cfg.todos_file 新建）。"""
        session = getattr(self._app_ctx, "session", None)
        mgr = getattr(session, "todo_mgr", None)
        if mgr is not None:
            return mgr
        try:
            from managers import TodoManager
            cfg = getattr(self._app_ctx, "cfg", None)
            return TodoManager(str(getattr(cfg, "todos_file", "") or "todos.json"))
        except Exception:
            return None

    def _echo_user_message(self, user_text: str, suppress_echo: bool) -> None:
        """提醒分支的用户消息入会话（与 _launch_worker 相同的回声抑制窗口）。"""
        if not suppress_echo:
            self.user_message_added.emit(user_text)
        session = getattr(self._app_ctx, "session", None)
        if session is not None and hasattr(session, "add_message"):
            self.echo_suppressed = bool(suppress_echo)
            try:
                session.add_message("user", user_text)
            except Exception:
                logger.debug("提醒分支 user 入会话失败（可忽略）", exc_info=True)
            finally:
                self.echo_suppressed = False

    def _handle_remind_list(self, user_text: str, suppress_echo: bool) -> bool:
        """列览分支（"今天有什么安排"）：本地模板直出，零 LLM。"""
        todo = self._todo_mgr()
        if todo is None:
            return False
        from reminders import build_list_text
        self._echo_user_message(user_text, suppress_echo)
        try:
            items = todo.today_items()
        except Exception:
            items = []
        self.screen_bubble(build_list_text(items), scene="reminder")
        return True

    def _handle_remind_request(self, user_text: str, suppress_echo: bool) -> bool:
        """录入分支：规则 high → 本地确认句直出（零 LLM）；low → LLM 兜底，
        LLM 不可用（demo/无 api）时按明示默认时刻登记（Q-C3，非编造）。"""
        todo = self._todo_mgr()
        if todo is None:
            return False
        from reminders import build_confirm_text, parse_when
        parsed = parse_when(user_text)
        if parsed.get("confidence") == "high":
            self._echo_user_message(user_text, suppress_echo)
            todo.add_reminder(parsed["remind_text"], parsed["due_at"])
            self.screen_bubble(
                build_confirm_text(parsed["due_at"], parsed["remind_text"]),
                scene="reminder")
            return True
        # low：demo / api 缺失 → LLM 兜底不可用，按默认时刻登记（明示语义）
        demo = False
        try:
            demo = _is_demo_mode(self._app_ctx)
        except Exception:
            pass
        api = getattr(self._app_ctx, "api", None)
        if demo or api is None:
            self._echo_user_message(user_text, suppress_echo)
            todo.add_reminder(parsed["remind_text"], parsed["due_at"])
            self.screen_bubble(
                build_confirm_text(parsed["due_at"], parsed["remind_text"]),
                scene="reminder")
            return True
        # low + LLM 可用 → remind_parse 专用分支（用户消息照常入会话，上下文完整）
        self._enqueue_request({"kind": "send", "text": user_text,
                               "task_type": "remind_parse",
                               "suppress_echo": suppress_echo,
                               "attachments": [], "intent_state": "",
                               "request_injections": []})
        return True

    def _route_intent(self, user_text: str, task_type: str,
                      intent_mode: Optional[str] = None) -> str:
        """v1.6(P0-2/D-V16-04): send_message 前置意图路由（只附加不接管）。

        返回命中状态字符串（confide/analyze/advise/act）；chat/未识别/跳过路径
        一律返回 ""（零附加、零改道 —— 无消息黑洞）。

        - 跳过条件：task_type != "chat"（任务模式/单步操作等显式路径）、
          Agent 模式显式开启、demo 模式（演示链无附加行为意义）；
        - 手动选态（intent_mode）覆盖自动识别；"auto" 读 GuiConfig.chat_intent_mode，
          仍为 "auto" 时走 gui.intent.classify_intent 纯规则识别；
        - 幂等：本路由只作用于用户发送路径（proactive_ask / screen_bubble /
          retry 均不过此处）。
        """
        try:
            if task_type != "chat" or self._agent_mode or _is_demo_mode(self._app_ctx):
                return ""
        except Exception:
            return ""
        try:
            from gui.intent import INTENT_STATES, classify_intent
            mode = (intent_mode or "").strip() or "auto"
            if mode == "auto":
                mode = str(getattr(getattr(self._app_ctx, "config", None),
                                   "chat_intent_mode", "auto") or "auto").strip() or "auto"
            if mode in INTENT_STATES and mode != "auto" and mode != "chat":
                return mode  # 手动选态覆盖自动识别（chat 态选中也等于零附加）
            state = classify_intent(user_text)
        except Exception:
            return ""  # 降级：intent 模块加载失败 → 全链退化为 v1.5.2 行为
        return state if state in ("confide", "analyze", "advise", "act") else ""

    # ----- v1.6(P0-4/D-V16-07): 失败保留 + 一键重试 -----
    def retry_last_failure(self, skip_history_write: bool = True) -> bool:
        """重试上次失败的消息（幂等 —— **切勿改走 send_message，会重复入库**）。

        现状（D-V16-07 架构师标红确认）：GUI 链失败时数据层已保留 user 消息
        （_launch_worker 先写 session 后调 API，失败不回滚），缺的只是 UI 入口。
        本方法按失败现场原样重发（task_type 原样保留、suppress_echo 强制、
        skip_history_write=True 跳过 session.add_message —— session 中 user
        消息不重复）。重试路径**不再过意图路由**（D-V16-04 幂等约定）。
        返回是否有可重试现场。
        """
        f = self._last_failure
        if not f or not (f.get("text") or "").strip():
            return False
        self._stop_requested = False
        self._current_user_text = f["text"]
        self._current_task_type = f.get("task_type") or "chat"
        self._enqueue_request({
            "kind": "send", "text": f["text"],
            "task_type": f.get("task_type") or "chat",
            "suppress_echo": True,                      # 失败 user 气泡仍在 UI，禁回声
            "skip_history_write": bool(skip_history_write),  # session 已有该消息，防重复入库
            "attachments": list(f.get("attachments") or []),
            "intent_state": "",                         # 重试不过路由（保持原样重发）
            "request_injections": [],
        })
        self._last_failure = None
        return True

    # ----- v1.8(V18-02/V18-04): F1 实体注入与提议-确认挂点 -----

    def _v18_memory_mgr(self):
        """取 MemoryManager（session 缺失/方法缺失时返回 None，全链静默降级）。"""
        session = getattr(self._app_ctx, "session", None)
        return getattr(session, "memory_mgr", None) if session is not None else None

    # ----- v1.8(V18-12/D-V18-07): F4 场景化陪伴 -----

    def _current_scene_now(self) -> Optional[str]:
        """当前场景判定（scene_auto 关闭返回 None = 场景功能整体关闭）。"""
        try:
            cfg = getattr(self._app_ctx, "config", None)
            if cfg is None or not bool(getattr(cfg, "scene_auto", True)):
                return None
            import scene as scene_mod
            mo = scene_mod.resolve_manual_override(
                str(getattr(cfg, "manual_scene", "") or ""),
                str(getattr(cfg, "manual_scene_date", "") or ""))
            return scene_mod.current_scene(datetime.now(), mo)
        except Exception:
            return None

    def _scene_is_sleep(self) -> bool:
        """睡前场景判定（仅 scene_auto 开启时为真；NIGHT_CARE 防双注入用）。"""
        return self._current_scene_now() == "sleep"

    # ----- v1.8(V18-15/D-V18-08): F7 影像记忆存档链 -----

    def _has_image_attachment(self, attachments: Optional[list]) -> bool:
        """本轮附件是否含图片（按扩展名白名单；仅作"带图事实"判定，不读内容）。"""
        if not attachments:
            return False
        return any(isinstance(a, dict)
                   and str(a.get("ext") or "").lower() in self._IMAGE_MIME
                   for a in attachments)

    def _mark_vision_viewed(self, image_uris: list) -> None:
        """图片直传组装结果补记（_launch_worker 主线程调用）。

        组装结果为空（超限/读盘失败/Agent 忽略）→ 影像记忆仍存但记
        「当时无法识别内容」（诚实边界①）；有 URI（模型至少收到了图）→
        保持中性描述。只改 note 文案，绝不触碰图像数据（R-I）。
        """
        if self._pending_vision is not None and not image_uris:
            self._pending_vision["image_note"] = "当时无法识别内容"

    def _stash_vision_memory(self, stash: Optional[dict], full_text: str,
                             usage: dict) -> None:
        """流式成功钩子：带图消息落一条影像记忆（对话事实，非识别结果）。

        边界（R-I/R-K）：群聊路径在 _on_stream_finished 顶部分流前已取走暂存
        （群聊零写入）；demo / 取消 / 记忆管理器缺失一律跳过；增强档
        （vision_memory_enhance，Q-D8 默认关）未接入视觉识别通道 → 静默回落
        默认档，绝不编造。任何异常只 debug 日志，绝不阻塞消息链。
        """
        if not stash:
            return
        if isinstance(usage, dict) and usage.get("cancelled"):
            return
        if _is_demo_mode(self._app_ctx):
            return
        cfg = getattr(self._app_ctx, "config", None)
        if bool(getattr(cfg, "vision_memory_enhance", False)):
            # 增强档（Q-D8 默认关）：视觉模型轻量识别（max_tokens=120）替代
            # image_note；当前构建未接入识别通道 → 静默回落默认档（绝不编造）。
            logger.debug("vision_memory_enhance 开启但识别通道未接入，回落默认档")
        mmgr = self._v18_memory_mgr()
        if mmgr is None or not callable(getattr(mmgr, "add_vision_memory", None)):
            return
        try:
            mmgr.add_vision_memory(
                user_text=str(stash.get("user_text") or ""),
                assistant_digest=first_paragraph_digest(full_text),
                image_note=str(stash.get("image_note") or "用户分享了一张图片"),
                source_mode="default",
            )
        except Exception:
            logger.debug("影像记忆存档失败（静默，不阻塞消息链）", exc_info=True)

    def _apply_scene_boundary(self, scene_now: str) -> None:
        """场景切换幂等边界消息（⚠-5 双动作②；仿 notify_role_switch 范式）。

        request_injections 只活一轮、留不住"持续性"底色 → 场景切换（含启动后
        首次应用）往 LLM 会话历史追加一条 system 边界消息（语气底色随历史
        留存），按 SCENE_BOUNDARY_MARKER 识别并移除上一条，历史中至多一条；
        服务层记 _last_applied_scene 防逐轮重复写。直接操作 history（不走
        add_message），不触发 GUI 信号 —— 边界消息不渲染气泡。
        """
        try:
            if scene_now == getattr(self, "_last_applied_scene", None):
                return
        except Exception:
            return
        self._last_applied_scene = scene_now
        session = getattr(self._app_ctx, "session", None)
        if session is None or not hasattr(session, "history"):
            return
        try:
            import scene as scene_mod
            marker = scene_mod.SCENE_BOUNDARY_MARKER
            session.history = [
                m for m in session.history
                if not (isinstance(m, dict) and m.get("role") == "system"
                        and str(m.get("content", "")).startswith(marker))
            ]
            session.history.append({
                "role": "system",
                "content": scene_mod.scene_boundary_text(scene_now),
            })
        except Exception:
            logger.debug("场景边界消息写入失败（可忽略）", exc_info=True)

    def _v18_entity_propose_hook(self, user_text: str) -> None:
        """V18-04 提议-确认链挂点（D-V18-01/Q-D1：`entity_auto_propose` 默认 False）。

        开关关闭（默认）时零行为空转；开启后的对话命中关系句式 → 回复尾部
        轻问 + [记下来][不用了] 两键（复用 v1.6 反馈三键组件样式）→ 确认才
        add_entity(source="assistant_proposed")，无确认绝不写入——完整链路
        按设计可后置 v1.8.x（PRD §8），本批只立开关与挂点。
        """
        cfg = getattr(self._app_ctx, "config", None)
        if not bool(getattr(cfg, "entity_auto_propose", False)):
            return
        # v1.8.x 完整链路落点：关系句式词表判定（E-1 首版 8-10 条高频句式，
        # 词表外挂 JSON 可热补）→ 尾部轻问 → 两键确认 → add_entity(
        # source="assistant_proposed")。本批不实现，保持零行为。

    def _note_owner_emotion(self, user_text: str) -> None:
        """v1.2(A1): 主人文本 -> companion.note_owner_text（情绪检测 + 心情重算）。

        守卫式接入：无 companion / 方法缺失时静默空转；主动消息不经本方法
        （proactive_ask 独立路径，不算用户输入，防自续命）。
        """
        companion = getattr(self._app_ctx, "companion", None)
        if companion is None:
            return
        try:
            note = getattr(companion, "note_owner_text", None)
            if callable(note):
                note(user_text)
        except Exception as exc:
            logger.debug("companion.note_owner_text 失败（可忽略）: %s", exc)

    # ----- v1.2(A9): 主动陪伴独立入口 -----
    def proactive_ask(self, text: str, scene: str = "idle_hello", subject: str = "") -> bool:
        """码铃主动开口：独立路径，**不复用用户发送队列**（避免与用户消息冲突）。

        语义（PRD A9 / design §3.10）：
          - 主线程同步执行，无 echo（不发 user_message_added / user 消息）；
          - 不入 ApiWorker 队列（无 API 调用，文案即成品）——不影响正在进行的用户消息；
          - 会话落 assistant 气泡并带 meta.proactive=True；
          - **不 bump_intimacy、不算交互打点**（防自续命：不得让「她开口」重置空闲计时）；
          - demo 模式 / 会话缺失：返回 False（scheduler 不会记账）。
        返回 True 表示已投递；渲染订阅 proactive_message 信号。
        v1.6(P0-3): subject = 反馈内容源键（话题 subject / "__emotion__" /
        "__todo__"；""=纯模板问候）。投递成功且 subject 非空时，紧接着
        proactive_message 发出 proactive_feedback_ready(subject, scene)——
        订阅方据其在主动气泡后挂反馈三键动作行（不入会话存档）。
        """
        text = (text or "").strip()
        if not text:
            return False
        # demo 模式不触发（PRD A9：无 API 时不做主动陪伴）
        try:
            if _is_demo_mode(self._app_ctx):
                return False
        except Exception:
            pass
        session = getattr(self._app_ctx, "session", None)
        if session is None or not hasattr(session, "add_message"):
            return False
        try:
            session.add_message("assistant", text, proactive=True, scene=scene)
        except Exception as exc:
            logger.warning("proactive 会话写入失败: %s", exc)
            return False
        try:
            self.proactive_message.emit(text, scene)
        except Exception:
            pass
        # v1.6(P0-3): 反馈三键内容源透传（在 proactive_message 之后，保证
        # 订阅方先渲染气泡再挂动作行；subject 为空不发，纯模板无需反馈）
        if subject:
            try:
                self.proactive_feedback_ready.emit(subject, scene)
            except Exception:
                pass
        return True

    # ----- v1.4(B1b): 屏幕类消息（看屏提示 / 操作反馈 / peek 结论）独立入口 -----
    def screen_bubble(self, text: str, scene: str = "screen_notice") -> bool:
        """码铃屏幕类开口：写一条 assistant 会话气泡（meta.screen=True）+ 专用信号。

        语义（design-v14 §3.1 / D-V14-10 / 共享知识 26，与 proactive_ask 同构但独立）：
          - 主线程同步执行，无 echo；不入 ApiWorker 队列（文案即成品，不调模型）；
          - 会话落 assistant 气泡 → 经 gui_session.message_added 单入口渲染（无双气泡）；
          - **不发 proactive_message / 不 toast** —— 只发新信号 screen_bubble_ready
            （托盘不订阅该信号，天然满足 R-C「屏幕提示仅对话气泡」）；
          - 不 bump_intimacy / 不算交互打点 / 不受 proactive 四重闸约束。
        返回 True 表示已投递。
        """
        text = (text or "").strip()
        if not text:
            return False
        session = getattr(self._app_ctx, "session", None)
        if session is None or not hasattr(session, "add_message"):
            return False
        try:
            session.add_message("assistant", text, screen=True, scene=scene)
        except Exception as exc:
            logger.warning("screen_bubble 会话写入失败: %s", exc)
            return False
        try:
            self.screen_bubble_ready.emit(text, scene)
        except Exception:
            pass
        return True

    def is_busy(self) -> bool:
        """是否有正在进行的回复/agent —— 主动陪伴在忙碌期间不应开口。"""
        return self._worker is not None and self._worker.isRunning()

    # ==================================================================
    # v1.7(F10a/F10b/D-V17-06): 多角色群聊发言调度（显示会话层，三隔离）
    # ==================================================================

    @property
    def current_group_speaker(self) -> Optional[str]:
        """v1.7(F10): 当前群聊发言者 role_id（面板流式气泡渲染用）。"""
        return self._group_speaker_id

    def prepare_group_request(self, display_session, speaker_role,
                              member_roles: Optional[dict] = None,
                              user_text: str = "", interject: bool = False) -> list:
        """v1.7(F10a): 从显示会话即时组装群聊请求副本（用后即弃，不入任何会话）。

        - system = 发言角色人设 + 群聊语境段（唯一 system，R-J④）；
        - 历史角色改写（rewrite_group_history）：他人发言 → user + 【名字】：前缀；
        - 非插话路径确保本轮 user 消息在请求中（显示会话未及时落盘时只补请求副本）；
        - 历史 >60 条截断保留最近（群聊 MVP 不做 auto_summary）。
        """
        session = display_session
        if session is None or speaker_role is None:
            return []
        name_by_id = {}
        members = []
        try:
            members = list((session.metadata or {}).get("members") or [])
        except Exception:
            members = []
        for rid in members:
            r = (member_roles or {}).get(rid)
            name_by_id[rid] = str(getattr(r, "name", "") or "") if r is not None else "成员"
        entries = rewrite_group_history(getattr(session, "messages", []) or [],
                                        speaker_role, name_by_id)
        if user_text and not interject:
            text = str(user_text)
            if not entries or entries[-1].get("role") != "user" \
                    or entries[-1].get("content") != text:
                entries.append({"role": "user", "content": text})
        entries = entries[-GROUP_HISTORY_LIMIT:]
        others = [name_by_id[rid] for rid in members
                  if rid != getattr(speaker_role, "id", "") and rid in name_by_id]
        system = build_group_system_prompt(speaker_role, others)
        return [{"role": "system", "content": system}] + entries

    def group_send(self, user_text: str, display_session, speaker_role,
                   member_roles: Optional[dict] = None,
                   interject: bool = False) -> bool:
        """v1.7(F10a): 群聊发言调度 —— 独立 LLM 调用，串行单 worker。

        三隔离守卫（共享知识 26）：本路径**不写 session.history、不触发
        notify_role_switch/replace_history、不计亲密度、不做记忆提取**；
        回复完成写显示会话（speaker_id 元数据）+ 气泡渲染由面板承接。
        """
        session = display_session
        if session is None or speaker_role is None:
            return False
        if self._group_active:
            return False  # 串行：上一发言未结束不接受新发言（防并发错乱）
        messages = self.prepare_group_request(session, speaker_role,
                                              member_roles or {},
                                              user_text=user_text, interject=interject)
        if not messages:
            return False
        cfg = getattr(self._app_ctx, "config", None) or getattr(self._app_ctx, "cfg", None)
        task_config = {
            "task_type": "chat",
            "stream_mode": getattr(cfg, "stream_mode", True),
            "temperature": getattr(cfg, "temperature", 0.7),
            "max_tokens": getattr(cfg, "max_tokens", 2048),
            "user_text": user_text or "",
            "group": True,
            "group_interject": bool(interject),
            "agent_system": "",
        }
        # 轮转记账：发言后该角色移到队尾（含 @指定发言；R-J① Q-C1 rotate 语义）
        try:
            order = list((session.metadata or {}).get("turn_order") or [])
            sid = getattr(speaker_role, "id", "")
            if sid in order:
                order.remove(sid)
                order.append(sid)
                (session.metadata or {}).__setitem__("turn_order", order)
        except Exception:
            logger.debug("群聊轮转记账失败（可忽略）", exc_info=True)
        return self._launch_group_worker(messages, speaker_role, session, task_config)

    def maybe_group_interject(self, display_session, last_speaker_id: str,
                              allow: bool = True) -> bool:
        """【已退役·向后兼容】v1.7(F10b) 主动插话调度已被自由发言调度替代。

        F10 定案：用户消息后的接话由轻量 LLM 调度决定（1-2 人串行），
        "插话四道闸"机制移除（见 send_group_turn）。本方法保留空实现防止
        外部残留调用崩溃，发言路径不再调用。
        """
        return False

    # ------------------------------------------------------------------
    # v1.7(F10 自由发言调度·定案): 未@时轻量 LLM 调度（1-2 人）+ 串行接话
    # ------------------------------------------------------------------
    def send_group_turn(self, user_text: str, display_session,
                        member_roles: Optional[dict] = None) -> str:
        """v1.7(F10): 群聊一轮发言调度入口（面板发送路径调用）。

        优先级：
        1. @点名（显式覆盖，最高）：被 @ 角色必回（1 人，跳过调度零额外 token）；
        2. silent 策略：全员沉默等待 @（消息照常入会话，零回复）；
        3. 默认：轻量 LLM 调度决定本轮接话者（1-2 人）→ 串行发言，
           失败/超时回退 turn_order 轮转 1 人（绝不让用户消息无回应）。

        返回调度方式："at" | "silent" | "scheduled"（面板据此提示）。
        """
        session = display_session
        if session is None or not self._ensure_group_dispatch_idle():
            return "silent"
        roles = member_roles if member_roles is not None else self._group_member_roles(session)
        if not roles:
            return "silent"
        # 1) @点名显式覆盖
        name_to_id = {getattr(r, "name", ""): rid
                      for rid, r in roles.items() if getattr(r, "name", "")}
        mentioned = parse_group_mention(user_text or "", name_to_id)
        if mentioned and roles.get(mentioned):
            self._group_speaker_queue = [mentioned]
            self._group_sched_state = {"session": session, "member_roles": roles}
            self._advance_group_queue()
            return "at"
        # 2) silent 策略沿用（免打扰：等待 @ 点名）
        policy = str((session.metadata or {}).get("no_at_policy")
                     or GROUP_DEFAULT_NO_AT_POLICY)
        if policy == "silent":
            return "silent"
        # 3) 自由发言调度
        self._launch_group_scheduler(session, roles, user_text or "")
        return "scheduled"

    def _ensure_group_dispatch_idle(self) -> bool:
        """v1.7(F10): 串行守卫 —— 上一发言/调度未结束不接受新一轮。"""
        if self._group_active or self._group_speaker_queue:
            return False
        if self._group_sched_worker is not None and self._group_sched_worker.isRunning():
            return False
        return True

    def _launch_group_scheduler(self, session, member_roles: dict, user_text: str) -> None:
        """v1.7(F10): 启动轻量调度请求（api.chat 单次，严格 JSON，≤120 tokens）。"""
        api = getattr(self._app_ctx, "api", None)
        if api is None:
            self._fallback_rotate(session, member_roles)
            return
        self._group_sched_seq += 1
        req_id = f"gs_{self._group_sched_seq}"
        self._group_sched_req_id = req_id
        self._group_sched_state = {"session": session, "member_roles": member_roles}
        recent = build_scheduler_context(getattr(session, "messages", []) or [],
                                         member_roles, user_text)
        messages = build_scheduler_messages(member_roles, user_text, recent)
        worker = GroupScheduleWorker(api, messages, req_id)
        worker.schedule_ready.connect(self._on_group_scheduled)
        worker.schedule_failed.connect(self._on_scheduler_failed)
        self._group_sched_worker = worker
        worker.start()
        # 超时兜底：调度未按时返回 → 回退轮转（request_id 对比防误伤新轮）
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._on_scheduler_timeout(req_id))
        timer.start(GROUP_SCHED_TIMEOUT_MS)
        if self._group_sched_timer is not None:
            try:
                self._group_sched_timer.stop()
            except RuntimeError:
                pass
        self._group_sched_timer = timer

    def _on_group_scheduled(self, req_id: str, content: str, usage: dict) -> None:
        """v1.7(F10): 调度返回 → 解析发言者入队（失败回退轮转）。

        调度请求 token 经 session.add_usage 如实累计（计费透明）。
        """
        if req_id != self._group_sched_req_id:
            return  # 过期回调（超时兜底已接管 / 已切新轮）
        self._stop_sched_timer()
        state = self._group_sched_state or {}
        session, roles = state.get("session"), state.get("member_roles") or {}
        # 计费透明：调度 token 计入本轮 usage
        try:
            if isinstance(usage, dict) and usage.get("total_tokens"):
                llm_session = getattr(self._app_ctx, "session", None)
                if llm_session is not None and callable(getattr(llm_session, "add_usage", None)):
                    llm_session.add_usage(usage)
        except Exception:
            logger.debug("调度 token 计费失败（可忽略）", exc_info=True)
        speakers = parse_scheduler_reply(content, roles)
        if not speakers:
            logger.info("群聊调度无可发言者，回退轮转")
            self._fallback_rotate(session, roles)
            return
        self._group_speaker_queue = speakers[:GROUP_SCHED_MAX_SPEAKERS]
        self._advance_group_queue()

    def _on_scheduler_failed(self, req_id: str, error: str) -> None:
        """v1.7(F10): 调度请求失败 → 回退轮转（绝不让用户消息无回应）。"""
        if req_id != self._group_sched_req_id:
            return
        self._stop_sched_timer()
        logger.warning("群聊调度失败，回退轮转: %s", error)
        state = self._group_sched_state or {}
        self._fallback_rotate(state.get("session"), state.get("member_roles") or {})

    def _on_scheduler_timeout(self, req_id: str) -> None:
        """v1.7(F10): 调度超时 → 回退轮转（过期回调由 req_id 对比拦截）。"""
        if req_id != self._group_sched_req_id:
            return
        logger.warning("群聊调度超时（%dms），回退轮转", GROUP_SCHED_TIMEOUT_MS)
        state = self._group_sched_state or {}
        self._fallback_rotate(state.get("session"), state.get("member_roles") or {})

    def _stop_sched_timer(self) -> None:
        timer = self._group_sched_timer
        if timer is not None:
            try:
                timer.stop()
            except RuntimeError:
                pass
            self._group_sched_timer = None

    def _fallback_rotate(self, session, member_roles: dict) -> None:
        """v1.7(F10): 兜底 —— turn_order 轮转取 1 人发言。"""
        if session is None:
            return
        roles = member_roles or self._group_member_roles(session)
        speaker = fallback_speaker(session, roles)
        if speaker is None:
            return
        self._group_speaker_queue = [getattr(speaker, "id", "")]
        self._advance_group_queue()

    def _advance_group_queue(self) -> None:
        """v1.7(F10): 串行接话推进 —— 弹出下一位发言者（上一发言已完成）。

        第二发言者的请求由 prepare_group_request 从显示会话即时组装——
        第一位刚说的话（speaker_id 元数据）已写入，自然被改写为
        【名字】：前缀，实现"看到先说的再接话"。
        """
        if self._group_active:
            return
        state = self._group_sched_state or {}
        session, roles = state.get("session"), state.get("member_roles") or {}
        while self._group_speaker_queue:
            rid = self._group_speaker_queue.pop(0)
            role = roles.get(rid)
            if role is None:
                continue  # 角色已删除 → 跳过取下一位
            if self.group_send("", session, role, roles, interject=True):
                return
        # 队列耗尽 / 发言启动失败：本轮结束
        self._group_sched_state = None

    def _group_member_roles(self, display_session) -> dict:
        """v1.7(F10a): 从 RoleManager 只读获取群成员角色数据（严禁写 page_role.py）。"""
        try:
            from gui.pages.page_role import RoleManager
            ids = set((display_session.metadata or {}).get("members") or [])
            return {r.id: r for r in RoleManager().all_roles() if r.id in ids}
        except Exception:
            return {}

    def _launch_group_worker(self, messages: list, speaker_role, display_session,
                             task_config: dict) -> bool:
        """v1.7(F10a): 群聊 worker 启动（复用 ApiWorker 普通流式分支）。

        与 _launch_worker 的关键差异：不组装 session.history（messages 即请求
        副本）、不写 session.add_message、无意图路由/附件/联网注入——零触碰
        v1.5.1 对齐链。
        """
        api = getattr(self._app_ctx, "api", None)
        if api is None:
            self._on_api_error("⚠️ 请求失败：API 客户端未初始化\n请检查 API Key / 网络 / 厂商 URL")
            return False
        self._stop_requested = False
        self._current_user_text = task_config.get("user_text") or ""
        self._current_task_type = "chat"
        self._group_active = True
        self._group_speaker_id = getattr(speaker_role, "id", None)
        self._group_display_session = display_session
        self._group_was_interject = bool(task_config.get("group_interject"))
        self._worker = ApiWorker(api, messages, task_config, self._app_ctx, expr_filter=False)
        self._worker.message_stream_started.connect(self._on_stream_started)
        self._worker.message_chunk_received.connect(self._on_chunk_received)
        self._worker.message_stream_finished.connect(self._on_stream_finished)
        self._worker.message_cancelled.connect(self._on_cancelled)
        self._worker.thinking_indicator.connect(self._on_thinking)
        self._worker.message_failed.connect(self._on_api_error)
        self._worker.start()
        return True

    def _on_group_stream_finished(self, full_text: str, usage: dict) -> None:
        """v1.7(F10a): 群聊回复完成 —— 写显示会话（speaker_id），三隔离收口。

        - 不写 session.history、不注入女仆语气（成员以自己人设发言）、
          不 bump_intimacy、不做记忆提取、不做 TTS 朗读（MVP 无多声线）；
        - token 用量经既有 session.add_usage 如实累计（首页 Token 卡，PRD 验收 5）；
        - 发出 message_stream_finished 由面板收尾流式气泡并落盘显示会话。
        """
        self._group_active = False
        session = self._group_display_session
        self._group_display_session = None
        usage = usage or {}
        # token 成本如实累计（只记账，不写历史——首页 Token 卡读数）
        try:
            if isinstance(usage, dict) and usage.get("total_tokens"):
                llm_session = getattr(self._app_ctx, "session", None)
                if llm_session is not None and callable(getattr(llm_session, "add_usage", None)):
                    llm_session.add_usage(usage)
        except Exception:
            logger.debug("群聊 token 用量累计失败（可忽略）", exc_info=True)
        try:
            if session is not None and hasattr(session, "add_message"):
                session.add_message("assistant", full_text,
                                    metadata={"speaker_id": self._group_speaker_id})
        except Exception:
            logger.debug("群聊回复写显示会话失败（可忽略）", exc_info=True)
        self.message_stream_finished.emit(full_text, usage)
        # v1.7(F10): 串行接话 —— 本位发言完成（气泡渲染完/显示会话已落盘），
        # 推进队列让下一位接话（其请求将包含本位刚说的内容）
        self._advance_group_queue()
        self._drain()

    # ----- v1.1(agent): Agent 模式开关 -----
    def set_agent_mode(self, enabled: bool) -> None:
        """开启后发送消息以 task_type="agent" 进入工具循环；关闭回退纯聊天。"""
        self._agent_mode = bool(enabled)
        session = getattr(self._app_ctx, "session", None)
        if session is not None and hasattr(session, "agent_mode"):
            session.agent_mode = self._agent_mode

    def is_agent_mode(self) -> bool:
        return self._agent_mode

    def regenerate(self, user_text: str = "", ui_history: Optional[list] = None):
        """重新生成 AI 回复（v1.6 收口：签名对齐 chat_panel._on_regenerate_requested）。

        语义（R2）：面板已截断该轮 assistant 气泡并传入剩余消息 ui_history
        （含末位 user）——服务层先以 ui_history 重建 LLM 历史（人设 system
        置顶、消息源唯一），再原样重跑末位 user。重跑经 skip_history_write +
        skip_user_append **不入库不重复附加**（user 消息已在重建历史中），
        且不再过意图路由（幂等：保持原样重发）。

        旧无参调用兼容：不传 ui_history 时不清历史，直接重跑 _current_user_text
        （该 user 消息是原 send 已写入 session 的，同样 skip，防重复入库）。
        """
        text = (user_text or "").strip() or self._current_user_text
        if not text:
            return
        self._stop_requested = False
        self._current_user_text = text
        # task_type 原样保留（面板截断链语义：同一轮重跑不换道）
        task_type = self._current_task_type or "chat"
        if ui_history:
            session = getattr(self._app_ctx, "session", None)
            if session is not None and callable(getattr(session, "replace_history", None)):
                try:
                    session.replace_history(ui_history)
                except Exception as exc:
                    logger.debug("regenerate 重建 LLM 历史失败（按原历史重跑）: %s", exc)
        self._enqueue_request({"kind": "regen", "text": text, "task_type": task_type,
                               "suppress_echo": True, "skip_history_write": True,
                               "skip_user_append": True, "intent_state": "",
                               "request_injections": []})

    def stop_current(self):
        self._stop_requested = True
        if self._worker is not None:
            self._worker.stop_current()

    # v1.1(agent): 兼容既有 UI 调用名（面板/独立窗口均调 stop_generation）
    def stop_generation(self):
        self.stop_current()

    def shutdown(self):
        """主窗口关闭时调用：先停 worker，再等待最多 5s 让线程退出。"""
        if self._worker is not None:
            try:
                self._worker.stop_current()
            except Exception:
                pass
            try:
                # v10.15: 用 5s 替代原 hardcoded 1000ms，避免大请求被截断
                # （QThread 无 stop(wait_ms=) 方法，先请求取消再 wait(5000) 等待退出）
                self._worker.wait(5000)
            except Exception as e:
                logger.warning("等待 ApiWorker 退出超时: %s", e)
            self._worker = None

    # ----- internal -----

    # v1.2.x(看图): 允许原图直传的类型/上限（OpenAI 兼容多模态 image_url）
    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    _IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp", ".bmp": "image/bmp"}
    _MAX_IMAGE_BYTES = 8 * 1024 * 1024   # 单张 ≤8MB（超限跳过，仍走文本摘要）
    _MAX_IMAGES = 3                      # 单轮最多 3 张（控制 token/体积）

    def _image_attachments_to_data_uris(self, attachments: Optional[list]) -> list:
        """把本轮附件里的图片读为 data URI（多模态直传）。非图片/越限/读取失败静默跳过。

        v1.4(B1b) 增补：附件条目支持内存 `uri` 键 —— {name, ext, uri} 直传已组好的
        data URI（屏幕帧等内存图，**不进文件**）；path 旧通道（本地文件读盘）保留兼容。
        """
        if not attachments:
            return []
        import os as _os
        import base64 as _b64
        uris = []
        for a in attachments:
            if len(uris) >= self._MAX_IMAGES:
                break
            ext = (str(a.get("ext") or "")).lower()
            if ext not in self._IMAGE_MIME:
                continue
            # v1.4(B1b): 内存 data URI 直传（跳过文件读盘/尺寸校验——帧已在生成时控体积）
            mem_uri = a.get("uri")
            if mem_uri and str(mem_uri).startswith("data:"):
                uris.append(str(mem_uri))
                continue
            path = str(a.get("path") or "")
            size = a.get("size")
            try:
                size = int(size) if size is not None else 0
            except Exception:
                size = 0
            if size <= 0 or size > self._MAX_IMAGE_BYTES:
                logger.info("图片 %s 超限跳过直传（≤8MB 才会原图发送）", a.get("name"))
                continue
            if not path or not _os.path.exists(path):
                continue
            try:
                with open(path, "rb") as f:
                    raw = f.read()
                if not raw:
                    continue
                uri = "data:%s;base64," % self._IMAGE_MIME[ext] + _b64.b64encode(raw).decode("ascii")
                uris.append(uri)
            except Exception as e:
                logger.debug("图片 data URI 组装失败: %s", e)
        return uris

    def _enqueue_request(self, payload: dict):
        self._queue.put(payload)
        self._drain()

    def _drain(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._queue.empty():
            return
        payload = self._queue.get()
        self._launch_worker(payload)

    def _launch_worker(self, payload: dict):
        app_ctx = self._app_ctx
        cfg = app_ctx.config
        session = getattr(app_ctx, "session", None)
        collab = getattr(app_ctx, "collaborator", None)

        # 组装 messages
        history = session.history if session else []
        user_text = payload["text"]

        # v1.1(agent): Agent 模式开启时，所有消息改走工具循环（除非调用方显式指定）
        task_type = payload["task_type"]
        if task_type == "chat" and self._agent_mode:
            task_type = "agent"

        # v1.2.x(看图): 附件里的图片 -> data URI（多模态直传；仅当前轮、不回溯历史）
        image_uris = self._image_attachments_to_data_uris(payload.get("attachments") or [])
        if image_uris and task_type in ("agent", "managed_task"):
            # Agent/任务模式是纯文本推理，暂不支持图像 content；忽略图片并提示
            image_uris = []
            user_text = user_text + "\n[附带的图片已忽略：Agent/任务模式暂不支持看图，请切回普通聊天后发送图片]"
            logger.info("Agent/任务模式忽略图片附件（不支持多模态工具循环）")
        # v1.8(V18-15/D-V18-08): 组装结果补记 —— 图片组装失败/越限/被忽略 →
        # 影像记忆仍存，但记"当时无法识别内容"（诚实边界①，绝不编造识别结果）。
        self._mark_vision_viewed(image_uris)

        # v1.6(P0-4 收口): regenerate 重跑路径（skip_user_append）—— user 消息已在
        # session.history 末位（原 send 写入 / ui_history 重建），请求副本不再附加
        # 同一条 user，防请求与存档双重复。注入插入位（末位 user 之前）语义不变。
        if not payload.get("skip_user_append"):
            if collab is not None and hasattr(collab, "wrap_user_message") and task_type not in ("agent", "managed_task"):
                wrapped = collab.wrap_user_message(user_text, role=task_type)
                history = history + [{"role": "user", "content": wrapped}]
            else:
                history = history + [{"role": "user", "content": user_text}]

        # 图片注入：最后一条 user 消息 content 升级为多模态数组
        if image_uris:
            try:
                last = history[-1]
                text_part = last.get("content") or ""
                content_parts = [{"type": "text", "text": text_part}]
                for uri in image_uris:
                    content_parts.append({"type": "image_url", "image_url": {"url": uri}})
                last["content"] = content_parts
            except Exception:
                image_uris = []  # 组装失败则放弃直传，退回纯文本

        # v1.6(V16-0/共享知识 21): 请求级 system 注入基建 —— P0-2 情绪语气提示 /
        # P0-4 反套话指令共用机制。注入只进**请求副本**（history[-1] 末位 user
        # 之前），绝不写 session.history（当轮生效、不入存档）。
        _injections = [i for i in (payload.get("request_injections") or [])
                       if isinstance(i, str) and i.strip()]
        # v1.6(P0-4/T3/D-V16-08): 反套话注入 —— 仅普通聊天链；条件 = session 上
        # context_trimmed 标志（_trim_history 实际截断或 auto_summary 摘要发生过）。
        # 注入后标志复位（一次性消费）；cfg.agent_anti_hallucination_inject=False
        # 可一键关（config.yaml agent 段，不进 UI）。注意 GuiChatSession 包装器
        # setattr 会落在包装层 —— 经 inner 写回真实 ChatSession。
        try:
            if task_type == "chat" and session is not None \
                    and getattr(session, "context_trimmed", False):
                if bool(getattr(cfg, "agent_anti_hallucination_inject", True)):
                    _injections.append(ANTI_FLUFF_INJECTION)
                    sess_inner = getattr(session, "inner", session)
                    try:
                        sess_inner.context_trimmed = False
                    except Exception:
                        pass
        except Exception:
            logger.debug("反套话注入判定失败（按无注入处理）", exc_info=True)
        if _injections:
            try:
                msgs = list(history)
                insert_at = max(0, len(msgs) - 1)
                for inj in reversed(_injections):
                    msgs.insert(insert_at, {"role": "system", "content": inj})
                history = msgs
            except Exception:
                logger.debug("请求级注入组装失败（按无注入处理）", exc_info=True)

        task_config = {
            "task_type": task_type,
            "stream_mode": getattr(cfg, "stream_mode", True),
            "temperature": getattr(cfg, "temperature", 0.7),
            "max_tokens": getattr(cfg, "max_tokens", 2048),
            "user_text": user_text,
            # v1.1(agent): system prompt 主线程快照，供后台 Agent 线程使用
            "agent_system": getattr(session, "current_system", "") if session else "",
            # v1.2.x(看图): 本轮回传图片标记（供错误提示判断是否需要视觉模型）
            "vision": bool(image_uris),
        }

        # v1.5.0: GUI「🌐 联网」开关 —— 仅普通聊天生效（Agent 模式已自带 web_search 工具）；
        # 命中 should_auto_search（技术词+时间/查询意图）才交给 worker 线程真实检索，
        # 避免每轮都搜、也避免在主线程做网络请求。检索在 ApiWorker._run_stream 内执行。
        # v1.6(P0-2/D-V16-04): analyze 态命中后**跳过 should_auto_search 二次判定**
        # 直接检索（analyze 本身即技术判定，"收敛"语义）。
        if task_type == "chat" and getattr(cfg, "web_search_enabled_gui", False):
            if str(payload.get("intent_state") or "") == "analyze":
                task_config["web_search_query"] = user_text
            else:
                try:
                    from helpers import WebSearch as _WebSearch
                    if _WebSearch().should_auto_search(user_text):
                        task_config["web_search_query"] = user_text
                except Exception:
                    logger.debug("联网开关判定失败（忽略，按未开启处理）", exc_info=True)

        # v10.15: 演示模式不进入会话历史，避免污染后续真实回复
        # v1.6(P0-4/T2/D-V16-07): skip_history_write —— 重试路径 session 已有该
        # user 消息，跳过 add_message 防重复入库（幂等），其余组装不变。
        if not _is_demo_mode(app_ctx) and not payload.get("skip_history_write"):
            # R1（Bug1 根因修复）：echo_suppressed 原先只被 UI 端 getattr 读取，
            # 服务层从未定义也从未置位 → 恒为 False，session.add_message("user")
            # 触发的 gui_session.message_added 回声未被抑制，面板/独立窗口在
            # 自己已直插气泡之后又渲染一次相同 user 气泡（用户可见双气泡），
            # 且 chat_panel._save_current_session 把重复气泡一并落盘（会话记录重复）。
            # 修复：抑制标记随 payload 走，在同步写 session（即回声发射窗口，
            # 信号为同线程直连、handler 同步执行）前置位、写完立即复位。
            self.echo_suppressed = bool(payload.get("suppress_echo"))
            try:
                session.add_message("user", user_text)
            except Exception:
                logger.debug("会话写入 user 消息失败（可忽略）", exc_info=True)
            finally:
                self.echo_suppressed = False

        api = getattr(app_ctx, "api", None)
        if api is None:
            err = "⚠️ 请求失败：API 客户端未初始化\n请检查 API Key / 网络 / 厂商 URL"
            # v1.6(P0-4): 统一走 _on_api_error 汇聚点（记录失败现场 + 计数），不再直接 emit
            self._on_api_error(err)
            return

        # v1.4.2: 女仆模式开启时启用表情协议（过滤 + 指南已随角色 system 注入）
        _maid_on = bool(getattr(getattr(app_ctx, "config", None), "maid_mode", True))
        self._worker = ApiWorker(api, history, task_config, app_ctx, expr_filter=_maid_on)
        self._worker.message_stream_started.connect(self._on_stream_started)
        self._worker.message_chunk_received.connect(self._on_chunk_received)
        # v1.4.2: AI 自选表情（流中捕获）→ 广播形象系统（先于正文）
        self._worker.expression_picked.connect(self._on_expression_picked)
        self._worker.message_stream_finished.connect(self._on_stream_finished)
        self._worker.message_cancelled.connect(self._on_cancelled)
        self._worker.thinking_indicator.connect(self._on_thinking)
        self._worker.message_failed.connect(self._on_api_error)
        self._worker.agent_tool_event.connect(self._on_agent_tool_event)
        # v1.5.0: 联网检索完成 → 转发为 UI 提示信号（面板在流式气泡前插小字）
        self._worker.web_search_done.connect(self._on_web_search_done)
        self._worker.start()

    def _on_web_search_done(self, count: int) -> None:
        """v1.5.0: worker 线程检索完成（跨线程信号，Qt 自动排队回主线程）。"""
        try:
            self.web_search_notice.emit(f"🌐 已检索网络（{int(count)} 条结果）")
        except Exception:
            pass

    # ----- signal handlers -----

    def _on_stream_started(self):
        self.message_stream_started.emit()

    def _on_chunk_received(self, chunk: str):
        self.message_chunk_received.emit(chunk)

    def _on_expression_picked(self, expr: str) -> None:
        """v1.4.2: AI 自选表情（流中捕获）→ 广播形象系统。"""
        try:
            bridge = getattr(self._app_ctx, "companion_bridge", None)
            if bridge is not None and hasattr(bridge, "mood_changed"):
                bridge.mood_changed.emit(str(expr), "ai-markup")
        except Exception:
            pass

    def _on_stream_finished(self, full_text: str, usage: dict):
        # v10.15: 演示模式跳过语气 / 亲密度；否则注入女仆语气并写会话
        app_ctx = self._app_ctx
        # v1.8(V18-15): 先取走影像暂存（一次性消费）—— 群聊路径随之天然隔离
        #（暂存被丢弃不落盘，群聊带图零写入）；单聊在成功分支消费。
        pending_vision = self._pending_vision
        self._pending_vision = None
        # v1.7(F10a/D-V17-06): 群聊路径优先分流 —— 三隔离（不写对齐历史 /
        # 不计亲密度 / 不做记忆提取），不落入下方单聊任何分支
        if self._group_active:
            self._on_group_stream_finished(full_text, usage)
            return
        # v1.6(P0-4/D-V16-07): 成功 → 连续失败计数归零、清残留失败现场
        self._fail_streak = 0
        self._last_failure = None
        # v1.4.2: AI 自选表情标记 → 广播形象系统（大形象/气泡按当前角色资产集显示）
        try:
            _ai_expr = (usage or {}).get("ai_expression")
            if _ai_expr:
                _bridge = getattr(app_ctx, "companion_bridge", None)
                if _bridge is not None and hasattr(_bridge, "mood_changed"):
                    _bridge.mood_changed.emit(str(_ai_expr), "ai-markup")
        except Exception:
            pass
        if _is_demo_mode(app_ctx):
            final = full_text
            try:
                session = getattr(app_ctx, "session", None)
                if session is not None:
                    session.add_message("assistant", full_text, tag="demo")
            except Exception:
                logger.debug("会话写入 demo assistant 消息失败（可忽略）", exc_info=True)
        else:
            final = inject_maid_tone(full_text, app_ctx)
            try:
                session = getattr(app_ctx, "session", None)
                if session is not None:
                    session.add_message("assistant", full_text)
            except Exception:
                logger.debug("会话写入 assistant 消息失败（可忽略）", exc_info=True)
            # v1.2.x(token): 把本次用量累计进 session.token_used（首页 Token 卡读数）
            try:
                if isinstance(usage, dict) and usage.get("total_tokens"):
                    _add_usage = getattr(app_ctx, "session", None)
                    if _add_usage is not None and callable(getattr(_add_usage, "add_usage", None)):
                        _add_usage.add_usage(usage)
            except Exception:
                logger.debug("token usage 累计失败（可忽略）", exc_info=True)
            try:
                self._bump_intimacy_after_reply()
            except Exception:
                logger.debug("亲密度累加失败（可忽略）", exc_info=True)
            # v1.8(V18-15/D-V18-08): F7 影像记忆存档钩子 —— 带图消息流式成功
            # 且非取消时落一条（demo 已在外层分流；群聊/失败/取消零写入）。
            self._stash_vision_memory(pending_vision, full_text, usage)
            # v1.2(A9): Agent 任务完成事件 -> companion（agent_revisit 场景 + 未来 first_task 成就共用）
            if usage.get("agent") and not usage.get("cancelled"):
                companion = getattr(app_ctx, "companion", None)
                if companion is not None:
                    try:
                        ingest = getattr(companion, "ingest_event", None)
                        if callable(ingest):
                            ingest("agent_done", {"ok": True, "source": "chat_service"})
                    except Exception:
                        logger.debug("companion.ingest_event(agent_done) 失败（可忽略）", exc_info=True)
        # v1.3(P1-1): auto_read 守卫钩子 —— 回复已完成才触发，天然不中断流式。
        # getattr(app_ctx,'tts') 缺省（未装配/降级）静默空转；只朗读 AI 回复文本。
        self._maybe_auto_read(final)
        # 发出真实 final 文本（旧面板需要两个参数）
        self.message_stream_finished.emit(final, usage)
        self._drain()

    def _maybe_auto_read(self, final: str) -> None:
        """v1.3(P1-1): 自动朗读 AI 回复（默认关，设置页 tts_auto_read 打开才走）。

        守卫链（全过才朗读，任一缺省静默空转不崩）：
          tts 控制器存在 ∧ tts_enabled ∧ tts_auto_read ∧ 非 demo ∧ 文本非空。
        朗读不中断正在进行的打字/流式 —— 本钩子在回复流结束后调用，天然满足；
        无 key 演示模式（无真实回复）不朗读；多气泡并发经 tts 全局单例后开口打断前开口。
        """
        app_ctx = self._app_ctx
        if _is_demo_mode(app_ctx):
            return
        tts = getattr(app_ctx, "tts", None)
        if tts is None or not callable(getattr(tts, "speak", None)):
            return
        config = getattr(app_ctx, "config", None)
        if config is None:
            return
        if not bool(getattr(config, "tts_enabled", True)):
            return
        if not bool(getattr(config, "tts_auto_read", False)):
            return
        text = (final or "").strip()
        if not text:
            return
        try:
            if not tts.available:
                logger.debug("auto_read 跳过：TTS 不可用（%s）", tts.availability_reason or "未知")
                return
            tts.speak(text)  # owner=None：非气泡级（无「⏹ 停止」锚定）
        except Exception as exc:
            logger.debug("auto_read 朗读失败（静默空转）: %s", exc)

    def _on_cancelled(self):
        # v1.6(P0-4): 用户主动停止 ≠ 失败 → 连续失败计数归零
        self._fail_streak = 0
        self._pending_vision = None  # v1.8(V18-15): 取消轮不存影像记忆
        # v1.7(F10a): 群聊请求被取消 → 复位群聊调度态（防卡串行）
        if self._group_active:
            self._group_active = False
            self._group_display_session = None
        # v1.7(F10): 取消即终止本轮剩余接话
        self._group_speaker_queue.clear()
        self._group_sched_state = None
        self._stop_sched_timer()
        self.message_cancelled.emit()
        self._drain()

    def _on_thinking(self, active: bool):
        self.thinking_indicator.emit(active)

    def _on_api_error(self, error: str):
        """v10.15: 真实错误冒泡，不再用「女仆 fallback」掩盖。

        v1.6(P0-4/D-V16-07): 本方法是所有 message_failed 的汇聚点 —— 在这里
        统一记录失败现场（供 retry_last_failure 幂等重试）与连续失败计数
        （≥3 追加引导文案，无数值语义、纯引导）。
        """
        logger.warning("API 错误: %s", error)
        self._pending_vision = None  # v1.8(V18-15): 失败轮不存影像记忆
        # v1.7(F10a): 群聊请求失败 → 复位群聊调度态，且不记单聊失败现场
        #（retry_last_failure 走单聊链会写 session.history，群聊禁入，R-J 隔离）
        if self._group_active:
            self._group_active = False
            self._group_display_session = None
            # v1.7(F10): 发言失败即终止本轮剩余接话（防连环失败）
            self._group_speaker_queue.clear()
            self._group_sched_state = None
            self.message_failed.emit(error)
            self._drain()
            return
        try:
            self._last_failure = {
                "text": self._current_user_text,
                "task_type": self._current_task_type,
                "attachments": [],
                "ts": time.time(),
            }
        except Exception:
            pass
        try:
            self._fail_streak += 1
        except Exception:
            self._fail_streak = 1
        msg = error
        if self._fail_streak >= 3:
            msg = (error + "\n\n💡 连续几次都没能连上，建议检查网络或 API Key——"
                           "设置里可以测一下连接。")
        self.message_failed.emit(msg)
        self._drain()

    # ----- v1.1(agent): 工具事件转发 -----
    def _on_agent_tool_event(self, event_type: str, data_json: str):
        self.agent_tool_event.emit(event_type, data_json)

    # ----- v10.14 好感度兼容（保留 API 以满足 v10.14 回归断言）-----

    def _bump_intimacy(self, user_msg: str = "") -> None:
        """v10.14 兼容：每次对话结束调用，dialogue +1；带感谢词额外 gratitude +1。
        v10.15 保持 API 形态，内部把得分同步给 app_ctx.intimacy 并通过
        intimacy_changed 通知 main_window。
        """
        tracker = getattr(self._app_ctx, "intimacy", None)
        if tracker is None:
            return
        # dialogue +1
        msg = None
        try:
            msg = tracker.add_interaction("dialogue")
        except Exception:
            logger.debug("intimacy.add_interaction 失败", exc_info=True)
        # gratitude +1（如有）
        try:
            if user_msg and hasattr(tracker, "detect_gratitude") and tracker.detect_gratitude(user_msg):
                tracker.add_gratitude()
        except Exception:
            logger.debug("intimacy.gratitude 失败", exc_info=True)
        if msg:
            self.intimacy_changed.emit(msg)

    # ----- v1.7(F5/D-V17-04): 计分回退修复 + 关系阶段升级播报（恰一次） -----

    def _bump_intimacy_after_reply(self) -> None:
        """回复完成后的亲密度累加权威入口（v1.7 收口）。

        - 既有 collab.bump_intimacy 通道保留（鸭子兼容）；**实测 MultiModelCollaborator
          无该方法（hasattr 恒 False，GUI 计分链死路径）** → 回落到 v10.15 的
          _bump_intimacy（intimacy_changed 正常广播）；
        - 随后做阶段升级播报判定（恰一次，D-V17-04）。
        """
        tracker = getattr(self._app_ctx, "intimacy", None)
        old_level = None
        if tracker is not None:
            try:
                old_level = int(getattr(tracker, "level", 0) or 0)
            except Exception:
                old_level = None
        collab = getattr(self._app_ctx, "collaborator", None)
        if collab is not None and hasattr(collab, "bump_intimacy"):
            try:
                collab.bump_intimacy()
            except Exception as exc:
                logger.debug("collab.bump_intimacy 失败: %s", exc)
        else:
            self._bump_intimacy(self._current_user_text)
        self._maybe_announce_stage_up(old_level)

    def _maybe_announce_stage_up(self, old_level: Optional[int] = None) -> None:
        """阶段升级播报：本回合计分导致真实升级 ∧ 尚未播报过该阶段 → 播一次。

        - 恰一次双保险：①本轮 level > old_level（只播"升级"事件，初识不播）；
          ②level > tracker.notified_stage（持久化记账，重启/重开不重播）；
        - 播报走 proactive_ask（无 echo、不计分、不触发自续命，A9 机制零回归；
          用户交互的即时反馈，不走四重闸）；
        - 投递成功才 mark_stage_notified 落盘；写盘失败降级为进程内恰一次
         （下次重启可能重播一次，日志记录——D-V17-04 诚实降级）。
        """
        tracker = getattr(self._app_ctx, "intimacy", None)
        if tracker is None:
            return
        try:
            level = int(getattr(tracker, "level", 0) or 0)
        except Exception:
            return
        if old_level is not None and level <= int(old_level):
            return  # 本回合未升级：不是播报事件
        notified = -1
        try:
            notified = int(getattr(tracker, "notified_stage", -1))
        except Exception:
            notified = -1
        if level <= notified:
            return  # 已播报过（恰一次）
        try:
            text = tracker.stage_announcement(level)
        except Exception as exc:
            logger.debug("stage_announcement 失败: %s", exc)
            return
        delivered = False
        try:
            delivered = self.proactive_ask(text, scene="stage_up", subject="")
        except Exception as exc:
            logger.warning("阶段升级播报投递失败: %s", exc)
        if delivered:
            try:
                tracker.mark_stage_notified(level)
            except Exception as exc:
                logger.warning("notified_stage 落盘失败（降级为进程内恰一次）: %s", exc)
