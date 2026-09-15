"""gui/tavern/service.py —— 酒馆功能域 · Qt 控制器（V22-06，**本域唯一含 Qt 的文件**）。

设计依据：``docs/design-v22.md``
    - §4.3  ``class TavernService(QObject)`` 冻结签名（4 个信号 + ``start_play`` /
            ``submit`` / ``reroll`` / ``edit_narration``）；
    - §4.4 / L4  坏档矩阵与「更高版本只读」的**优雅降级**（只读会话：可玩、不落盘、不崩、不弹框）；
    - §4.5  与既有业务数据隔离：**持久化只经 ``TavernStore.save``**（单写点）；
    - §5.2  状态 / 文本分离：``reroll`` **只重跑叙述**，绝不动 ``vars`` / ``node_id`` / ``chapter_id``；
    - §5.5  Q2 关系只读：可读 ``companion.relation_stage_name`` / ``intimacy.level_name``
            做称呼与语气，**绝不写回任何好感度 / 亲密数据**；
    - §5.6  LLM 不可用 / 超时 / 垃圾返回 → **完整降级**（占位叙述 + 留痕），UI **不弹错误框**；
    - §6.5  全局派生值（主题色 / 动效档位 / 时长）**读时现取、禁止在 ``__init__`` 缓存**；
    - §6.1/§6.2  给 UI 的信号 / 查询面（界面零序号、零数值）。

架构铁律（本模块）：
    * **唯一 Qt 文件**：本域其余 9 个模块（``model`` / ``errors`` / ``store`` / ``engine`` /
      ``worldbook`` / ``intent_router`` / ``prompt`` / ``summarize`` / ``__init__``）**零 Qt**，
      本文件是**唯一**允许 ``import`` Qt 的位置（design D-V22-06）。
    * **单写点**：落盘一律 ``load() -> 内存改 -> save()`` 三步；**不绕过** ``TavernStore``、
      **不新增写点**；子模块一律不写盘。
    * **LLM 在工作线程**：一次「拍（turn）」的全部编排（路由 + 叙述 + 摘要 + 落盘）跑在
      ``QThread`` 子类 :class:`_TurnWorker` 内，**不阻塞 UI**；``propose`` 另有
      :data:`PROPOSE_TIMEOUT_S` 的**有界超时**（由 ``intent_router`` 施加）。
    * **不缓存全局派生值**：``motion`` / ``theme_color`` 的取值方法**每次调用现读**。
    * **异常收口**：只走 :mod:`gui.tavern.errors` 冻结层级；日志 ``logger.debug(..., exc_info=True)``，
      **无裸 ``except: pass``**；**绝不弹错误框**（一切提示走 ``degraded`` 信号）。

===================  给「批 2 页面 / 控件」工程师的契约摘要  ===================

信号（``Signal``；命名与载荷形状即页面 / 控件的对接面）
    * :attr:`TavernService.narration_chunk` ``Signal(str)`` —— **增量**叙述文本（逐 chunk）。
      仅作预览；**权威全文以** :attr:`narration_done` **为准**（流中断时以占位叙述覆盖）。
    * :attr:`TavernService.narration_done` ``Signal(str)`` —— 本拍**完整**叙述文本（权威）。
    * :attr:`TavernService.play_changed` ``Signal(str)`` —— 当前生效 ``play_id`` 变化 /
      内容变化（载荷 = 新的 ``play_id``；空串表示当前无局）。
    * :attr:`TavernService.degraded` ``Signal(str)`` —— **中性提示**（LLM 不可用 / 只读会话 /
      自由输入关闭等）。**不弹窗**，建议落在 ``state_warn`` 语义色的提示条。
    * :attr:`TavernService.plays_changed` ``Signal()`` —— 「我的故事」列表增删改（新建 / 删除）。
    * :attr:`TavernService.turn_ready` ``Signal(dict)`` —— 一拍完成。载荷键：
      ``{play_id, turn, input_kind, resolution, narration, degraded}``。
    * :attr:`TavernService.hud_changed` ``Signal(dict)`` —— 顶部状态条。载荷：
      ``{chapter_title, scene_id, held_items, read_only, degraded}``（**零序号、零数值**）。
    * :attr:`TavernService.choices_changed` ``Signal(list)`` —— 快捷动作。载荷：
      ``[{"choice_id","label"}, ...]``（**无裸 emoji**；图标由 UI 自行按 ``choice_id`` 取）。
    * :attr:`TavernService.worldbook_changed` ``Signal(dict)`` —— 本拍世界书命中。
    * :attr:`TavernService.summary_changed` ``Signal(dict)`` —— 新摘要（结构化 4 键）。
    * :attr:`TavernService.busy_changed` ``Signal(bool)`` —— 生成中（供省略号节奏指示）。
    * :attr:`TavernService.read_only_changed` ``Signal(bool)`` —— L4 只读会话开关。

查询面（只读；页面在 ``on_enter()`` / 收到信号后调用）
    :meth:`list_plays` / :meth:`current_play_id` / :meth:`current_play` /
    :meth:`current_hud` / :meth:`current_choices` / :meth:`current_narrative` /
    :meth:`current_transcript` / :meth:`trace` / :meth:`worldbook_entries` /
    :meth:`worldbook_hits` / :meth:`current_summary` / :meth:`get_settings` /
    :meth:`chapter_title` / :meth:`is_read_only` / :meth:`is_busy` /
    :meth:`motion_enabled` / :meth:`motion_level` / :meth:`motion_duration` /
    :meth:`theme_color`。

写操作（页面只经这些方法，**绝不**直接触碰 ``store``）
    :meth:`start_play` / :meth:`load_play` / :meth:`delete_play` / :meth:`submit` /
    :meth:`reroll` / :meth:`edit_narration` / :meth:`set_settings` / :meth:`reload` /
    :meth:`refresh`。全部落盘经 :meth:`_save`（唯一 ``save`` 调用点）。

``"history"`` 段 → 真实消息映射（★，见 :func:`render_chat_messages`）
    ``prompt.build_story_prompt`` 恒定产出 5 段，末段 ``role`` 为字面量 ``"history"``
    （**不是合法 chat role**）。由本模块负责映射进真实消息序列：
    前 4 段 ``system`` → ``{"role": "system"}``；末段 ``history`` → ``{"role": "user"}``
    （历史 = 喂给说书人的上下文；末条为 ``user``，模型据此续写 ``assistant`` 叙述）。
    映射表常量 :data:`SEGMENT_MESSAGE_ROLES`。
"""
from __future__ import annotations

import copy
import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from gui.qt_compat import QApplication, QObject, QThread, Signal

from . import engine as tavern_engine
from . import intent_router as tavern_router
from . import model as tavern_model
from . import prompt as tavern_prompt
from . import summarize as tavern_summarize
from . import worldbook as tavern_worldbook
from .errors import TavernRouteError, TavernStoreError
from .store import TavernStore

logger = logging.getLogger("maling.tavern.service")

__all__ = [
    # —— 常量 ——
    "PRODUCT_NAME",
    "FALLBACK_BOOK_ID",
    "PROPOSE_TIMEOUT_S",
    "SEGMENT_MESSAGE_ROLES",
    "VALID_CHAT_ROLES",
    "READ_ONLY_HINT",
    "LLM_DOWN_HINT",
    "FREE_INPUT_OFF_HINT",
    "SAVE_FAILED_HINT",
    "ENDED_HINT",
    "NEUTRAL_CHOICE_ECHO",
    "NEUTRAL_CHOICE_LABEL",
    "PREREQ_OPERATORS",
    # —— 纯函数（可单测）——
    "read_persona",
    "local_narration",
    "render_chat_messages",
    # —— 主类 ——
    "TavernService",
]


# ===========================================================================
# 常量
# ===========================================================================

#: 项目铁律：``given_name`` 为空时界面显示的产品名（**严禁**用 ``role.name`` 当姓名）。
PRODUCT_NAME: str = "码铃"

#: 内容包缺省 id（``load_content`` / ``load_builtin_book`` 的默认包名）。
FALLBACK_BOOK_ID: str = "lantern"

#: ``propose`` 档的**有界超时**（秒；由 ``intent_router`` 在工作线程内施加）。
PROPOSE_TIMEOUT_S: float = 6.0

#: 合法 chat 角色（映射后的消息序列只允许出现这些）。
VALID_CHAT_ROLES: tuple = ("system", "user", "assistant")

#: 段名 → 真实消息 role 的映射（前 4 段 system；末段 history → user）。
#: **单一来源**：``prompt.PROMPT_SEGMENTS`` 语义（见模块 docstring ★）。
SEGMENT_MESSAGE_ROLES: Dict[str, str] = {
    "narrator_rules": "system",
    "world_rules": "system",
    "character_card": "system",
    "turn_context": "system",
    "history": "user",
}

#: L4 只读会话的中性提示（**不弹框**，走 ``degraded``）。
READ_ONLY_HINT: str = "这份存档来自更高的版本，本期只能看一看，不会改动它。"

#: LLM 不可用 / 叙述中断的中性提示。
LLM_DOWN_HINT: str = "她这会儿有点走神，我先替你把这一夜记下来。"

#: 自由输入被设置关闭时的中性提示。
FREE_INPUT_OFF_HINT: str = "自由输入已经关上了，用快捷动作接着往下走吧。"

#: 落盘被拒时的中性提示（只读会话）。
SAVE_FAILED_HINT: str = "这一晚先留在记忆里，暂时不写进存档。"

#: 终局（``status == "ended"``）后再 ``submit`` 时的中性提示（**不弹框**，走 ``degraded``）。
ENDED_HINT: str = "这一夜已经讲完了，回头看看别的故事吧。"

#: ``choice`` 档**查不到中文 label** 时的中性占位。
#: 不变量：``transcript`` / 提示词**任何路径**都不得出现 ``choice_id`` 形态的机器名 ——
#: 查不到中文名时宁可用一句中性中文，**绝不**回落原 ``text``（那正是机器名）。
NEUTRAL_CHOICE_ECHO: str = "照你说的做了。"

#: ``choices[]`` / ``quick_actions[]`` **缺 ``label``** 时选项排的中性占位。
#: 不变量（同 :data:`NEUTRAL_CHOICE_ECHO`）：玩家条与 UI 按钮**任何路径**都不得出现
#: ``choice_id`` 形态的机器名 —— 缺中文名时给一句中性中文，**绝不**回落 ``choice_id``。
NEUTRAL_CHOICE_LABEL: str = "（未命名的动作）"


# ===========================================================================
# 类型守卫小工具（本地副本，避免耦合各模块私有名）
# ===========================================================================

def _as_str(value: Any, default: str = "") -> str:
    """``str`` 守卫。"""
    return value if isinstance(value, str) else default


def _as_int(value: Any, default: int = 0) -> int:
    """``int`` 守卫：``bool`` 不算 ``int``；非法回默认。"""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> List[str]:
    """把疑似列表收敛为 ``list[str]``（非 list/tuple 或含非 str 项时丢该项）。"""
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if isinstance(x, str) and x]


def _choice_snapshot(raw: Any, id_key: str) -> Optional[dict]:
    """把内容包的一条 ``choices[]`` / ``quick_actions[]`` 映射为 ``pending[]`` 快照。

    ``id_key`` —— ``choices[]`` 用 ``"choice_id"``，``quick_actions[]`` 用 ``"action_id"``。

    缺少 id 或 ``transform`` 的项**直接丢弃**：没有 ``transform`` 就执行不了
    （:func:`gui.tavern.intent_router.resolve_choice` 靠它路由），留在列表里只会变成
    点了没反应的死按钮。
    """
    if not isinstance(raw, dict):
        return None
    cid = _as_str(raw.get(id_key))
    transform = _as_str(raw.get("transform"))
    if not cid or not transform:
        return None
    args = raw.get("args")
    return {
        "choice_id": cid,
        # ★ P2：缺 ``label`` 时**中性化** —— 绝不回落 ``choice_id``（那正是机器名，
        # 会同时出现在玩家条与 UI 按钮上，是「任何路径不出现机器名」的旁路）。
        "label": _as_str(raw.get("label")).strip() or NEUTRAL_CHOICE_LABEL,
        "transform": transform,
        "args": dict(args) if isinstance(args, dict) else {},
    }


def _choice_label(pending: Any, choice_id: str) -> str:
    """在 ``pending[]`` 快照里按 ``choice_id`` 查**中文 label**（查不到 → 空串）。

    用途：``input_kind == "choice"`` 时玩家条对外只应出现中文文案；``choice_id``
    是给 router ``resolve_choice`` 用的机器名，**不得**进 ``transcript`` / 提示词。
    """
    if not isinstance(pending, list):
        return ""
    for item in pending:
        if isinstance(item, dict) and _as_str(item.get("choice_id")) == choice_id:
            return _as_str(item.get("label")).strip()
    return ""


def _content_choice_label(content: Any, choice_id: str) -> str:
    """在内容包里按 ``choice_id`` 反查中文 ``label``（节点 ``choices[]`` + ``quick_actions[]``）。

    用途（A2-4）：``submit(..., input_kind="choice")`` 时若 ``pending`` 快照里查不到该选项
    （旧档 / 直接调公开 API），仍能从**内容包**取到中文文案，**避免机器名写进存档 / 提示词**。
    查不到 → 空串（调用方回落中性中文占位，**绝不**回落 ``choice_id``）。
    """
    if not isinstance(content, dict) or not choice_id:
        return ""
    chapters = content.get("chapters")
    if isinstance(chapters, list):
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            nodes = chapter.get("nodes")
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                choices = node.get("choices")
                if not isinstance(choices, list):
                    continue
                for choice in choices:
                    if isinstance(choice, dict) and _as_str(choice.get("choice_id")) == choice_id:
                        label = _as_str(choice.get("label")).strip()
                        if label:
                            return label
    actions = content.get("quick_actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and _as_str(action.get("action_id")) == choice_id:
                label = _as_str(action.get("label")).strip()
                if label:
                    return label
    return ""


#: ``prerequisites`` 值支持的**条件算子名**（一个 dict 只允许出现其中一个）。
#: 契约扩展（经用户批准）：见 ``docs/design-v22.md`` §4.2。
PREREQ_OPERATORS: tuple = ("has", "has_all", "has_not", "not")


def _prereq_operator_met(want: dict, actual: Any) -> bool:
    """判定单个**算子形态**的 ``prerequisites`` 值是否满足（**fail-closed、绝不抛异常**）。

    为什么需要它：``opened`` / ``known`` / ``held_items`` / ``scene_items`` / ``given``
    这 5 个基底变量是**列表型**（由 ``open`` / ``ask_about`` / ``take`` / ``give`` 的
    ``post`` 自动 append 维护），而旧判定是严格等值 —— 列表永不等于字符串，于是这 5 个
    变量**永远无法用于分支**。本函数补上「列表包含 / 不包含 / 标量不等于」的查询能力。

    算子语义（``actual`` = ``state[key]``）：
        * ``{"has": v}``      —— ``actual`` 是 list 且含 ``v``；
        * ``{"has_all": [v…]}`` —— ``actual`` 是 list 且含 ``v`` 的**全部**（取值必须是 list）；
        * ``{"has_not": v}``  —— ``actual`` 是 list 且**不含** ``v``；
        * ``{"not": v}``      —— ``actual`` **不是** list 且 ``!= v``（列表请用 ``has_not``）。

    安全规则（全部 fail-closed）：
        * ``want`` 里出现 **>1 个算子** / **未知算子名** → 不通过；
        * ``has`` / ``has_all`` / ``has_not`` 用于**非列表** ``actual`` → 不通过；
        * ``not`` 用于**列表** ``actual`` → 不通过；
        * ``has_all`` 的取值不是 list → 不通过；
        * ``has_all`` 的取值是**空 list** → 不通过（空表在集合语义下恒真 = vacuous truth，
          与「写错一律不通过」同口径，故显式拒绝）。
    """
    if len(want) != 1:
        return False  # 一个 dict 只能有一个算子（>1 即无法判定意图 → 拒绝）
    op, operand = next(iter(want.items()))
    if op not in PREREQ_OPERATORS:
        return False  # 未知算子名 → 拒绝
    if op in ("has", "has_all", "has_not"):
        if not isinstance(actual, list):
            return False  # 包含类算子只对列表型变量有意义
        if op == "has":
            return operand in actual
        if op == "has_all":
            if not isinstance(operand, list):
                return False
            if not operand:
                return False  # 空表恒真 → fail-closed（写错一律不通过）
            return all(item in actual for item in operand)
        return operand not in actual  # has_not
    # op == "not"：标量不等于；列表必须用 has_not
    if isinstance(actual, list):
        return False
    return actual != operand


def _prerequisites_met(prerequisites: Any, state: Dict[str, Any]) -> bool:
    """storylet 准入判定：``prerequisites`` 的每个键都要满足（**向后兼容 + 条件算子**）。

    值形态（**新增**算子形态不改变原有形态的语义）：
        ① ``{"scene_id": "counter"}`` —— 原样：与 ``state`` **严格等值**（现有内容包全走这条）；
        ② ``{"opened": {"has": "drawer"}}`` —— 列表包含单项；
        ③ ``{"known": {"has_all": ["photo", "name"]}}`` —— 列表包含全部；
        ④ ``{"opened": {"has_not": "latch"}}`` —— 列表不包含（做「你还没做过 X」）；
        ⑤ ``{"poured": {"not": "long_night"}}`` —— 标量不等于。

    - 空 / 非 dict → **无条件通过**（作者没写条件即视为通用块）。
    - 键不在 ``state`` 里 → **不通过**（fail-closed：宁可少放行，也不误导进未满足的块）。
    - 值不是 dict → 严格等值（保持现状）；值是 dict → 走 :func:`_prereq_operator_met`。
    - **不支持**：值域为 ``dict`` 的 var 无法用等值分支 —— 值形态 ``dict`` 已被算子占用。
    - **绝不抛异常**（本函数被 ``_advance_node`` 与 ``_sync_pending`` 调用，抛异常会炸整拍）。
    """
    if not isinstance(prerequisites, dict) or not prerequisites:
        return True
    if not isinstance(state, dict):
        return False
    for key, want in prerequisites.items():
        if not isinstance(key, str) or key not in state:
            return False
        actual = state[key]
        if isinstance(want, dict):
            if not _prereq_operator_met(want, actual):
                return False
        elif actual != want:
            return False
    return True


def _type_matches(value: Any, default: Any) -> bool:
    """按默认值类型判定 ``value`` 是否类型相符（``bool`` / ``int`` 严格区分）。"""
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        return isinstance(value, int) and not isinstance(value, bool)
    if isinstance(default, str):
        return isinstance(value, str)
    if isinstance(default, list):
        return isinstance(value, list)
    if isinstance(default, dict):
        return isinstance(value, dict)
    return True


# ===========================================================================
# 应用侧只读读取（persona / 关系）—— 纯函数，便于单测注入
# ===========================================================================

def _default_role() -> Any:
    """取应用当前生效角色（懒 import；**只用于读 given_name / 人设**）。

    单测可 monkeypatch 本函数注入假角色对象。异常时返回 ``None``。
    """
    from gui.pages.page_role import RoleManager

    return RoleManager().default_role


def read_persona(app_ctx: Any) -> dict:
    """从应用侧读取**当前生效角色**的 ``given_name`` 与人设（**只读**）。

    **姓名单一规则（项目铁律）**：``given_name`` 非空 → 用它；为空 → 用产品名
    :data:`PRODUCT_NAME`。**绝不**使用 ``role.name``（人设标签≠人名）。

    Args:
        app_ctx: 应用上下文（用于取笔记本角色；缺省时回落产品名）。

    Returns:
        ``{"given_name": str, "persona": str, "display_name": str}``：
        ``persona`` = ``description`` + ``system_prompt``（去空行拼接，缺省空串）。
    """
    given = ""
    persona = ""
    role: Any = None
    try:
        role = _default_role()
    except Exception:
        logger.debug("酒馆读取当前角色失败（回落产品名）", exc_info=True)
        role = None
    if role is not None:
        given = _as_str(getattr(role, "given_name", "")).strip()
        desc = _as_str(getattr(role, "description", "")).strip()
        sysp = _as_str(getattr(role, "system_prompt", "")).strip()
        persona = "\n".join(part for part in (desc, sysp) if part)
    return {
        "given_name": given,
        "persona": persona,
        "display_name": given or PRODUCT_NAME,
    }


# ===========================================================================
# 本地（确定性、无网络）叙述兜底 —— LLM 不可用 / 中断时使用
# ===========================================================================

#: 各受控变换成功后的**本地占位叙述**（第二人称、无任何数值 / 序号 / R-A 词）。
_LOCAL_OK_LINES: Dict[str, str] = {
    "move_to": "你挪了个位置。屋里安静下来，只有那盏灯笼轻轻晃了晃。",
    "take": "你把那样东西拿在手里，指尖先碰到了它的一点凉意。",
    "give": "你把它递了过去。她停了一下，才伸手收下。",
    "open": "它开了，里面那点光浮出来，落在你脸上。",
    "ask_about": "你把话头递过去。她没有立刻答，目光飘开又收了回来。",
    "wait": "你们都没作声，灯芯轻轻响了一下，时间自己走过去了。",
    "order": "你要的那样东西被推到面前，杯沿还留着一圈温。",
}

#: 变换未成功（命中但前置不满足 / 校验拒绝）时的占位叙述。
_LOCAL_FAIL_LINE: str = "她偏了偏头，像是没太听清你的意思，这一下就轻轻过去了。"

#: 兜底 ``narrate`` 档的占位叙述（状态未变）。
_LOCAL_NARRATE_LINE: str = "你留了个话头在那儿。她没接，也没驳，屋子继续安安静静地亮着。"


def local_narration(play: Any, resolution: Any, *, player_text: str = "") -> str:
    """本地占位叙述（**确定性、零网络、无墙钟**），按 ``resolution`` 择句。

    Args:
        play: 局状态（当前实现不读取，保留参数以稳定签名 / 未来可扩展）。
        resolution: 本拍 ``resolution``（读 ``mode`` / ``transform`` / ``ok``）。
        player_text: 玩家本拍输入（保留；当前不拼接，避免复述与出戏）。

    Returns:
        非空中文叙述；保证不含数值 / 序号（对齐 §7「说书人规则」与 R-A 红线）。
    """
    _ = (play, player_text)
    res = resolution if isinstance(resolution, dict) else {}
    mode = _as_str(res.get("mode"))
    transform = _as_str(res.get("transform"))
    if mode == "narrate":
        return _LOCAL_NARRATE_LINE
    if res.get("ok") is True and transform in _LOCAL_OK_LINES:
        return _LOCAL_OK_LINES[transform]
    return _LOCAL_FAIL_LINE


# ===========================================================================
# ★ "history" 段 → 真实消息映射（本模块职责；prompt 末段 role = "history" 非法）
# ===========================================================================

def render_chat_messages(segments: Any) -> List[dict]:
    """把五段式 prompt（``[{segment, role, content}]``）映射为**真实 chat 消息序列**。

    规则（见模块 docstring ★ 与 :data:`SEGMENT_MESSAGE_ROLES`）：
      * 段 ``role == "history"`` → ``{"role": "user"}``；
      * 其余段（``"system"``）→ ``{"role": "system"}``；
      * 忽略空 ``system`` 段（避免无谓的消息），但**保证至少一条 system**；
      * **保证末条为 ``user``**（生成面：模型据末条 user 续写 ``assistant`` 叙述）。

    Args:
        segments: ``prompt.build_story_prompt`` 的返回（任意类型；非 list → 兜底单条）。

    Returns:
        ``list[dict]``，每项 ``{"role", "content"}``，``role ∈`` :data:`VALID_CHAT_ROLES`。
    """
    items = segments if isinstance(segments, (list, tuple)) else []
    messages: List[dict] = []
    system_seen = False
    history_content = ""
    for seg in items:
        if not isinstance(seg, dict):
            continue
        name = _as_str(seg.get("segment"))
        raw_role = _as_str(seg.get("role"))
        mapped = SEGMENT_MESSAGE_ROLES.get(name, "user" if raw_role == "history" else "system")
        content = _as_str(seg.get("content"))
        if mapped == "user":
            history_content = content
            continue
        if not content:
            continue  # 跳过空 system 段
        messages.append({"role": "system", "content": content})
        system_seen = True
    if not system_seen:
        messages.insert(0, {"role": "system", "content": ""})
    messages.append({"role": "user", "content": history_content})
    # 契约自检：映射后不得出现非法 role（末段 history 必须已被消化）
    for m in messages:
        assert m["role"] in VALID_CHAT_ROLES, f"非法 chat role: {m['role']!r}"
    return messages


# ===========================================================================
# 回合工作线程（LLM 不阻塞 UI）
# ===========================================================================

class _TurnWorker(QThread):
    """一次「拍」编排的工作线程（跑路由 + 叙述 + 摘要 + 落盘；**绝不阻塞 UI**）。

    只接受一个**无参 callable**（``job``）；``run()`` 整体 ``try/except``，
    异常**绝不跨线程抛出**（对齐 ``gui/widgets/kb_worker.py`` 既有惯用法）。
    job 内部经服务对象发信号（跨线程自动排队）。
    """

    def __init__(self, job: Callable[[], None], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._job = job

    def run(self) -> None:  # noqa: D401 - Qt 钩子
        try:
            self._job()
        except Exception:
            logger.debug("酒馆回合工作线程异常（已吞，绝不跨线程抛）", exc_info=True)


# ===========================================================================
# 主类：TavernService
# ===========================================================================

class TavernService(QObject):
    """酒馆功能域**唯一 Qt 控制器**（design §4.3 冻结签名的实现 + 只读查询面）。

    典型用法（页面）::

        svc = TavernService(app_ctx)
        svc.narration_chunk.connect(self._on_chunk)
        svc.narration_done.connect(self._on_done)
        svc.plays_changed.connect(self._reload_play_list)
        svc.degraded.connect(self._show_hint)
        pid = svc.start_play("lantern")
        svc.submit("我推门进去", input_kind="free")

    Attributes:
        （无公开可写属性；一切经方法 / 信号。）
    """

    # —— 冻结信号（design §4.3）——
    narration_chunk = Signal(str)
    narration_done = Signal(str)
    play_changed = Signal(str)
    degraded = Signal(str)
    # —— 扩展信号（本模块定义的 UI 契约，见模块 docstring）——
    plays_changed = Signal()
    turn_ready = Signal(dict)
    hud_changed = Signal(dict)
    choices_changed = Signal(list)
    worldbook_changed = Signal(dict)
    summary_changed = Signal(dict)
    busy_changed = Signal(bool)
    read_only_changed = Signal(bool)

    def __init__(
        self,
        app_ctx: Any,
        *,
        base_dir: Any = None,
        synchronous: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        """构造酒馆控制器。

        Args:
            app_ctx: 应用上下文（``api`` / ``cfg`` / ``companion`` / ``intimacy`` / ``theme_engine``）。
            base_dir: 存档目录（单测传 ``tmp_path``；``None`` → ``~/.maid_coder/tavern``）。
            synchronous: ``True`` 时一拍**内联执行**（供无事件循环的确定性单测）；
                ``False``（生产）时跑在 :class:`_TurnWorker` 工作线程，**不阻塞 UI**。
            parent: Qt 父对象。
        """
        super().__init__(parent)
        self._app_ctx = app_ctx
        self._store = TavernStore(base_dir=base_dir)
        self._synchronous = bool(synchronous)
        self._busy = False
        self._worker: Optional[_TurnWorker] = None
        self._read_only = False
        self._content_cache: Dict[str, dict] = {}
        self._last_selection: Any = None
        # 世界书 sticky / cooldown 的**激活账本**（``{play_id: {uid: 最后激活拍}}``）。
        # 会话内内存态：``PLAY_KEYS`` / ``TOP_LEVEL_KEYS`` 均已冻结，落盘新键会破坏契约，
        # 故本账本**不落盘**（跨重启不保留；同档同会话内确定性可复现）。
        self._lore_ledgers: Dict[str, Dict[int, int]] = {}
        # 构造期**只**读一次存档（内存态），**不**缓存任何全局派生值（§6.5）
        self._data: dict = self._store.load()
        if self._store.read_only:
            self._read_only = True

    # ==================================================================
    # 生命周期
    # ==================================================================

    def _ensure_loaded(self) -> dict:
        """返回内存态存档（构造期已加载；此处只做防御性兜底）。"""
        if not isinstance(self._data, dict):
            self._data = self._store.load()
            if self._store.read_only:
                self._read_only = True
        return self._data

    def reload(self) -> None:
        """重新从磁盘读档（覆盖内存态；用于外部改动后刷新）。会重新判定只读。"""
        self._data = self._store.load()
        self._read_only = bool(self._store.read_only)
        self._content_cache.clear()
        self._last_selection = None
        self._lore_ledgers.clear()
        self.read_only_changed.emit(self._read_only)

    def refresh(self) -> None:
        """把当前状态整体广播给 UI（页面 ``on_enter()`` 时调用）。"""
        data = self._ensure_loaded()
        pid = _as_str(data.get("active_play_id"))
        self.play_changed.emit(pid)
        self.plays_changed.emit()
        self.hud_changed.emit(self.current_hud())
        self.choices_changed.emit(self.current_choices())

    def list_plays(self) -> List[dict]:
        """「我的故事」列表元信息（**无序号**；时间由 UI 自行渲染为相对时间）。

        Returns:
            每项 ``{play_id, title, book_id, status, updated_at, chapter_title, is_active}``。
        """
        data = self._ensure_loaded()
        active = _as_str(data.get("active_play_id"))
        plays = data.get("plays")
        out: List[dict] = []
        if isinstance(plays, list):
            for play in plays:
                if not isinstance(play, dict):
                    continue
                pid = _as_str(play.get("play_id"))
                out.append({
                    "play_id": pid,
                    "title": _as_str(play.get("title")),
                    "book_id": _as_str(play.get("book_id")),
                    "status": _as_str(play.get("status"), "active"),
                    "updated_at": _as_str(play.get("updated_at")),
                    "chapter_title": self._chapter_title(play),
                    "is_active": pid == active,
                })
        return out

    def current_play_id(self) -> str:
        """当前生效 ``play_id``（无局 → 空串）。"""
        return _as_str(self._ensure_loaded().get("active_play_id"))

    def current_play(self) -> Optional[dict]:
        """当前生效局对象（``data`` 内实时引用；无 → ``None``）。"""
        data = self._ensure_loaded()
        pid = _as_str(data.get("active_play_id"))
        if not pid:
            return None
        play = TavernStore.get_play(data, pid)
        return play if isinstance(play, dict) else None

    def start_play(
        self,
        book_id: str,
        *,
        title: Optional[str] = None,
        play_id: Optional[str] = None,
        seed: Optional[int] = None,
        now: Optional[str] = None,
    ) -> str:
        """新开一局（写入内存 + ``save``）并置为当前局。

        Args:
            book_id: 绑定世界书 id。
            title: 局标题（UI 显示，**无序号**）；``None`` → 按内容包推默认标题。
            play_id: 指定局 id（单测用）；``None`` → 生成。
            seed: 显式随机 seed；``None`` → 生成（并持久化，满足"显式 seed"约束）。
            now: 可注入时间戳（确定性单测）。

        Returns:
            新局的 ``play_id``。
        """
        data = self._ensure_loaded()
        bid = _as_str(book_id) or FALLBACK_BOOK_ID
        pid = _as_str(play_id) or self._new_play_id()
        resolved_title = _as_str(title) or self._default_title(bid)
        resolved_seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else self._new_seed()
        play = tavern_model.new_play(bid, resolved_title, resolved_seed, play_id=pid, now=now)
        self._seed_seen_nodes(play)   # 开局节点记为已访问，避免被 storylet 再挑一次
        self._sync_pending(play)  # 开局即给出初始节点的选项（否则整排按钮永空）
        TavernStore.upsert_play(data, play)
        data["active_play_id"] = pid
        # 首帧世界书快照：不跑这一步，「世界书」Tab 在第一拍之前恒为空
        self._worldbook_for(play, self._settings())
        self._save()
        self.play_changed.emit(pid)
        self.plays_changed.emit()
        self.hud_changed.emit(self.current_hud())
        self.choices_changed.emit(self.current_choices())
        self.worldbook_changed.emit(self.worldbook_hits())
        return pid

    def load_play(self, play_id: str) -> bool:
        """把已有局置为当前局（写 ``active_play_id`` + ``save``）。

        Returns:
            ``True`` 表示成功（局存在）。
        """
        data = self._ensure_loaded()
        pid = _as_str(play_id)
        target = TavernStore.get_play(data, pid)
        if target is None:
            return False
        data["active_play_id"] = pid
        self._seed_seen_nodes(target)   # 旧档可能没有 seen_nodes
        self._sync_pending(target)  # 载入即刷新选项（旧档可能没有 pending 字段）
        # 首帧世界书快照（同 start_play：不跑则 turn=0 时「世界书」Tab 恒空）
        self._worldbook_for(target, self._settings())
        self._save()
        self.play_changed.emit(pid)
        self.hud_changed.emit(self.current_hud())
        self.choices_changed.emit(self.current_choices())
        self.worldbook_changed.emit(self.worldbook_hits())
        return True

    def delete_play(self, play_id: str) -> bool:
        """删除一局（内存 + ``save``）；若删的是当前局，一并清空当前指针。

        Returns:
            ``True`` 表示确有删除。
        """
        data = self._ensure_loaded()
        pid = _as_str(play_id)
        was_active = _as_str(data.get("active_play_id")) == pid
        removed = TavernStore.delete_play(data, pid)
        if not removed:
            return False
        self._lore_ledgers.pop(pid, None)
        # ★ P2：删的若是**当前局**，`_last_selection`（「世界书」Tab 快照）会残留旧局命中 ——
        # 必须一并清空；否则删局后 Tab 仍显示已删局的条目（实测残留 6 条）。
        # 删非当前局时不动快照（它属仍生效的当前局，清了反而误空 Tab）。
        if was_active:
            self._last_selection = None
        self._save()
        self.plays_changed.emit()
        self.play_changed.emit(self.current_play_id())
        self.hud_changed.emit(self.current_hud())
        self.choices_changed.emit(self.current_choices())
        # 广播世界书快照（删局后 Tab 必须刷新；载荷即最新命中，无局时为空）
        self.worldbook_changed.emit(self.worldbook_hits())
        return True

    def save(self) -> bool:
        """显式落盘（当前内存态）；只读会话下会被拒并**优雅降级**。"""
        return self._save()

    # ==================================================================
    # 一拍（turn）编排 —— submit / reroll
    # ==================================================================

    def submit(self, text: str, input_kind: str = "free") -> bool:
        """玩家输入（自由文本或选项）→ 起一拍（设计 §4.3 冻结签名）。

        编排在工作线程（生产）或内联（``synchronous=True``）执行：
        ``route`` → 落 ``transcript``（**每拍带 resolution 留痕**）→ 按需摘要 → ``save``。

        Args:
            text: 自由输入文本，或选项 id（``input_kind="choice"``）。
            input_kind: ``"free"`` | ``"choice"``（其余一律回落 ``"free"``）。

        Returns:
            ``True`` 表示已起一拍；``False`` 表示被拒（生成中 / 无局 / 自由输入关闭 / 已终局）。
        """
        if self._busy:
            return False
        kind = input_kind if input_kind in tavern_model.INPUT_KINDS else "free"
        raw_text = text if isinstance(text, str) else ""
        data = self._ensure_loaded()
        if not _as_str(data.get("active_play_id")):
            self.degraded.emit("还没有开局，先新开一局吧。")
            return False
        # A2-3（P1）：终局（``status == "ended"``）后**拒绝**新的一拍 —— 不写状态、不追加
        # journal、不推进 ``node_id``。否则再点一下就会推进到**另一个**结局节点，
        # 两局混成一局（``journal.seen_endings`` 记下两个结局）。
        # 只读操作（``reroll`` / ``edit_narration``）走各自入口，**不受此闸影响**。
        play = self.current_play()
        if isinstance(play, dict) and _as_str(play.get("status")) == "ended":
            self.degraded.emit(ENDED_HINT)
            return False
        if kind == "free" and not self._allow_free_input():
            self.degraded.emit(FREE_INPUT_OFF_HINT)
            return False
        self._start(lambda: self._pipeline_turn(raw_text, kind))
        return True

    def reroll(self, turn: int) -> bool:
        """重掷**本拍叙述**（只重跑叙述生成，**绝不动** ``vars`` / ``node_id`` / ``chapter_id``）。

        Args:
            turn: 目标拍的 ``turn``。

        Returns:
            ``True`` 表示已起重掷；``False`` 表示被拒（生成中 / 找不到该拍的叙述条目）。
        """
        if self._busy:
            return False
        target = _as_int(turn, -1)
        play = self.current_play()
        if play is None or self._narrator_index(play, target) < 0:
            return False
        self._start(lambda: self._reroll_pipeline(target))
        return True

    def edit_narration(self, turn: int, text: str) -> bool:
        """就地编辑某拍的**叙述文本**（只允许改 ``text``；**禁止**改状态字段）。

        Args:
            turn: 目标拍的 ``turn``。
            text: 新叙述文本。

        Returns:
            ``True`` 表示已改（并尝试落盘）。
        """
        if not isinstance(text, str):
            return False
        play = self.current_play()
        if play is None:
            return False
        idx = self._narrator_index(play, _as_int(turn, -1))
        if idx < 0:
            return False
        transcript = play.get("transcript")
        if not isinstance(transcript, list):
            return False
        transcript[idx]["text"] = text
        self._save()
        self.narration_done.emit(text)
        self.turn_ready.emit({
            "play_id": self.current_play_id(),
            "turn": _as_int(turn, -1),
            "input_kind": _as_str(transcript[idx].get("input_kind"), "free"),
            "resolution": dict(transcript[idx].get("resolution") or {}),
            "narration": text,
            "degraded": False,
        })
        return True

    # ==================================================================
    # 工作线程调度
    # ==================================================================

    def _start(self, job: Callable[[], None]) -> None:
        """起一拍：置忙 → 内联执行或投递工作线程。"""
        self._busy = True
        self.busy_changed.emit(True)
        if self._synchronous:
            try:
                job()
            except Exception:
                logger.debug("酒馆内联回合异常（已吞）", exc_info=True)
            finally:
                self._busy = False
                self.busy_changed.emit(False)
            return
        worker = _TurnWorker(job, self)
        self._worker = worker
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_worker_finished(self, worker: "_TurnWorker") -> None:
        """工作线程收尾（主线程回调）：清忙 + 回收线程对象。"""
        self._busy = False
        if self._worker is worker:
            self._worker = None
        self.busy_changed.emit(False)
        try:
            worker.deleteLater()
        except Exception:  # pragma: no cover - 对象生命周期边界
            logger.debug("酒馆工作线程回收失败（忽略）", exc_info=True)

    def wait_for_idle(self, timeout_s: float = 10.0) -> bool:
        """等待当前工作线程结束（**测试 / 收尾用**）；随后冲刷排队信号。

        Returns:
            ``True`` 表示线程已结束（或本就空闲）。
        """
        worker = self._worker
        if worker is None:
            return True
        try:
            ok = bool(worker.wait(int(max(0.0, timeout_s) * 1000)))
        except (RuntimeError, TypeError):
            logger.debug("等待酒馆工作线程失败（对象可能已销毁）", exc_info=True)
            ok = False
        app = QApplication.instance()
        if app is not None:
            for _ in range(3):
                app.processEvents()
        return ok

    def stop(self, wait_ms: int = 2000) -> bool:
        """有界停机：等待工作线程自然结束（**从不**无限阻塞、**从不** terminate）。"""
        worker = self._worker
        if worker is None or not worker.isRunning():
            return True
        try:
            return bool(worker.wait(int(wait_ms)))
        except (RuntimeError, TypeError):
            logger.debug("停止酒馆工作线程失败（忽略）", exc_info=True)
            return False

    # ==================================================================
    # 一拍编排实现（工作线程体）
    # ==================================================================

    def _pipeline_turn(self, text: str, input_kind: str) -> None:
        """一拍完整编排（**工作线程内**）：路由 → 叙述 → 摘要 → 落盘 → 广播。"""
        data = self._ensure_loaded()
        pid = _as_str(data.get("active_play_id"))
        play = TavernStore.get_play(data, pid)
        if not isinstance(play, dict):
            self.degraded.emit("还没有开局，先新开一局吧。")
            return

        settings = self._settings()
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        content = self._content_for(book_id)

        pre_turn = _as_int(play.get("turn"), 0)
        resolution, new_state = self._route(text, play, content, settings, input_kind)

        # 候选态：深拷贝，**绝不就地改入参**（对齐 engine「不可变式」纪律）
        working = copy.deepcopy(new_state if isinstance(new_state, dict) else play)

        # 拍数推进：**本服务**为拍计数器推进 +1（engine 仅对 wait 自增，避免双计）
        post_turn = _as_int(working.get("turn"), pre_turn)
        beat_turn = max(post_turn, pre_turn + 1)
        working["turn"] = beat_turn

        transcript = working.get("transcript")
        if not isinstance(transcript, list):
            transcript = []
            working["transcript"] = transcript

        # 对外文本：选项只回中文 label（``choice_id`` 是 router 的机器名，不进存档 / 提示词）
        echo_text = self._echo_text(play, text, input_kind, content)

        at = tavern_model.iso_now()
        player_entry = {
            "turn": beat_turn,
            "role": "player",
            "input_kind": input_kind,
            "text": echo_text,
            "resolution": dict(resolution),
            "narrated": True,
            "at": at,
        }
        # 先落玩家条：让叙述 prompt 的 turn_context 能看到"本拍发生了什么"
        transcript.append(player_entry)

        # 世界书取值（每拍一次；即便本地叙述也要给「世界书」Tab 留快照）
        book = self._worldbook_for(working, settings)

        # 叙述（LLM 流式或本地占位）
        narration_text, degraded = self._narrate(
            working, content, settings, book=book,
            mode="normal", resolution=resolution, player_text=echo_text,
        )
        narrator_entry = {
            "turn": beat_turn,
            "role": "narrator",
            "input_kind": input_kind,
            "text": narration_text,
            "resolution": dict(resolution),
            "narrated": True,
            "at": tavern_model.iso_now(),
        }
        transcript.append(narrator_entry)

        # seen_nodes 记账（仅内部；不与 I2 冲突）
        node_id = _as_str(working.get("node_id"))
        seen = working.get("seen_nodes")
        if not isinstance(seen, list):
            seen = []
            working["seen_nodes"] = seen
        if node_id and node_id not in seen:
            seen.append(node_id)

        # 摘要（到点才生成；验证不过 → 保留旧摘要）
        # 注意：本块**必须在** ``_advance_node`` 之后 —— ``new_chapter`` 只能由「换章」判定，
        # 而换章正是 ``_advance_node`` 造成的（放到前面就恒为 False，章末摘要永远不触发）。
        chapter_before = self._chapter_key(content, _as_str(working.get("node_id")))

        working["updated_at"] = at
        self._advance_node(working)  # storylet：按新状态挑下一个满足 prerequisites 的节点
        self._sync_pending(working)  # 再按（可能已变的）当前节点刷新选项

        chapter_after = self._chapter_key(content, _as_str(working.get("node_id")))
        new_chapter = bool(chapter_before) and bool(chapter_after) and chapter_before != chapter_after

        if tavern_summarize.should_summarize(
            working, content, settings=settings, new_chapter=new_chapter,
        ):
            new_summary = tavern_summarize.make_summary(
                working,
                llm_summarize=(self._llm_summarize if self._llm_available() else None),
                settings=settings,
                content=content,
            )
            working["summary"] = tavern_summarize.normalize_summary(new_summary)
            self.summary_changed.emit(dict(working["summary"]))

        # 终局：当前节点不再提供任何选项 → 状态收束 + 跨局日志留痕
        if self._is_terminal_node(content, working):
            working["status"] = "ended"
            self._record_ending(data, content, working)

        # LLM 降级留痕（结构化 llm 字段，读写均在内存）
        llm_state = working.get("llm")
        if not isinstance(llm_state, dict):
            llm_state = tavern_model.default_llm_state()
            working["llm"] = llm_state
        llm_state["degraded"] = bool(degraded)
        llm_state["last_error"] = "" if not degraded else "llm_unavailable_or_interrupted"

        TavernStore.upsert_play(data, working)
        data["active_play_id"] = pid
        self._save()

        # 广播（emit 从工作线程发出 → Qt 自动排队到 UI 线程）
        self.narration_done.emit(narration_text)
        self.play_changed.emit(pid)
        self.hud_changed.emit(self.current_hud())
        self.choices_changed.emit(self.current_choices())
        self.worldbook_changed.emit(self.worldbook_hits())
        self.turn_ready.emit({
            "play_id": pid,
            "turn": beat_turn,
            "input_kind": input_kind,
            "resolution": dict(resolution),
            "narration": narration_text,
            "degraded": bool(degraded),
        })

    def _reroll_pipeline(self, turn: int) -> None:
        """重掷实现（**只改 ``transcript`` 该拍的叙述文本**；状态逐字节不变）。"""
        data = self._ensure_loaded()
        pid = _as_str(data.get("active_play_id"))
        play = TavernStore.get_play(data, pid)
        if not isinstance(play, dict):
            return

        settings = self._settings()
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        content = self._content_for(book_id)

        idx = self._narrator_index(play, turn)
        if idx < 0:
            return

        # 快照状态字段（重掷后必须逐字节不变）
        before_vars = copy.deepcopy(play.get("vars"))
        before_node = play.get("node_id")
        before_scene = play.get("scene_id")
        before_chapter = play.get("chapter_id")
        before_len = len(play.get("transcript") or [])

        working = copy.deepcopy(play)
        transcript = working.get("transcript")
        resolution = dict((transcript[idx].get("resolution") or {}))
        player_text = self._player_text_for_turn(working, turn)

        book = self._worldbook_for(working, settings)

        # 重掷：prompt 走 mode="reroll"（本回合必不携带上一版文本）
        new_text, degraded = self._narrate(
            working, content, settings, book=book,
            mode="reroll", resolution=resolution, player_text=player_text,
        )
        transcript[idx]["text"] = new_text

        assert len(transcript) == before_len, "reroll 不得改变 transcript 长度"
        assert working.get("vars") == before_vars, "reroll 不得改 vars"
        assert working.get("node_id") == before_node, "reroll 不得改 node_id"
        assert working.get("scene_id") == before_scene, "reroll 不得改 scene_id"
        assert working.get("chapter_id") == before_chapter, "reroll 不得改 chapter_id"

        working["updated_at"] = tavern_model.iso_now()
        TavernStore.upsert_play(data, working)
        data["active_play_id"] = pid
        self._save()

        self.narration_done.emit(new_text)
        self.turn_ready.emit({
            "play_id": pid,
            "turn": _as_int(turn, -1),
            "input_kind": _as_str(transcript[idx].get("input_kind"), "free"),
            "resolution": resolution,
            "narration": new_text,
            "degraded": bool(degraded),
        })

    def _route(
        self,
        text: str,
        play: dict,
        content: dict,
        settings: dict,
        input_kind: str,
    ):
        """调 :func:`intent_router.route`（**降级绝不抛**；写权恒在本地）。"""
        allow_propose = bool(settings.get("allow_propose", True))
        llm_propose = self._llm_propose if allow_propose else None
        try:
            return tavern_router.route(
                text,
                play,
                content,
                allow_propose=allow_propose,
                llm_propose=llm_propose,
                timeout_s=PROPOSE_TIMEOUT_S,
                input_kind=input_kind,
                seed=play.get("seed"),
            )
        except TavernRouteError:
            logger.debug("酒馆路由入参不可用，回落 narrate", exc_info=True)
            placeholder = tavern_engine.ApplyResult(False, play, "llm_disabled", "")
            return tavern_engine.build_resolution(placeholder, mode="narrate", llm_used=False), play

    def _narrate(
        self,
        working: dict,
        content: dict,
        settings: dict,
        *,
        book: Any,
        mode: str,
        resolution: dict,
        player_text: str,
    ):
        """生成叙述文本：LLM 流式（失败即降级）或本地占位。返回 ``(text, degraded)``。"""
        want_llm = bool(settings.get("llm_narration", True)) and self._llm_available()
        if not want_llm:
            self.degraded.emit(LLM_DOWN_HINT)
            return local_narration(working, resolution, player_text=player_text), True

        messages = self._render_messages(working, content, settings, mode=mode, book=book)
        api = getattr(self._app_ctx, "api", None)
        stream_fn = getattr(api, "chat_stream_chunks", None)
        if not callable(stream_fn):
            self.degraded.emit(LLM_DOWN_HINT)
            return local_narration(working, resolution, player_text=player_text), True

        parts: List[str] = []
        try:
            for chunk in stream_fn(messages):
                if isinstance(chunk, str) and chunk:
                    parts.append(chunk)
                    self.narration_chunk.emit(chunk)
        except Exception:
            logger.debug("酒馆叙述流中断，使用占位叙述（进度不丢）", exc_info=True)
            self.degraded.emit(LLM_DOWN_HINT)
            return local_narration(working, resolution, player_text=player_text), True

        text = "".join(parts).strip()
        if not text:
            self.degraded.emit(LLM_DOWN_HINT)
            return local_narration(working, resolution, player_text=player_text), True
        return text, False

    def _render_messages(
        self,
        working: dict,
        content: dict,
        settings: dict,
        *,
        mode: str,
        book: Any,
    ) -> List[dict]:
        """五段式 prompt 组装 + **persona 注入** + ★ ``history`` 段真实消息映射。

        ★ A2-1（P0）：把 :meth:`_worldbook_for` **本拍刚算好的** ``_last_selection`` 传给
        prompt —— 提示词与「世界书」Tab 快照因此**共用同一份**世界书结果，
        ``probability`` / ``sticky`` / ``cooldown`` 才会真的改变 LLM 看到的内容。
        """
        persona = read_persona(self._app_ctx)
        injected = dict(content) if isinstance(content, dict) else {}
        if persona["persona"]:
            # 真正的 persona 由应用侧注入（覆盖内容包的同名字段）
            injected["character_card"] = persona["persona"]
        relation_ctx = self._relation_ctx(persona)
        segments = tavern_prompt.build_story_prompt(
            working, book, working, injected,
            relation_ctx=relation_ctx, mode=mode, settings=settings,
            selection=self._last_selection,
        )
        return render_chat_messages(segments)

    # ==================================================================
    # LLM 客户端包装（注入给 router / prompt）
    # ==================================================================

    def _llm_available(self) -> bool:
        """LLM 是否可用（对齐 ``_is_demo_mode`` 语义：有 key 或本地 provider，且有 client）。"""
        api = getattr(self._app_ctx, "api", None)
        if api is None or not callable(getattr(api, "chat", None)):
            return False
        cfg = getattr(self._app_ctx, "cfg", None) or getattr(self._app_ctx, "config", None)
        if cfg is None:
            return False
        provider = (_as_str(getattr(cfg, "api_provider", None)) or _as_str(getattr(cfg, "provider", ""))).strip().lower()
        if provider == "ollama":
            return True
        return bool((_as_str(getattr(cfg, "api_key", ""))).strip())

    def _llm_propose(self, prompt: str) -> Any:
        """``llm_propose`` 注入实现：``(strict_json_prompt) -> dict|str|None``。

        返回**原始**返回体（``dict`` 或 ``str``）而非预先解析 —— 让
        ``intent_router`` 的规范化器区分"畸形 JSON"（``llm_bad_json``）/ "超时"
        （``llm_timeout``）/ "不可用"（``llm_disabled``）。异常**不在此吞掉**：
        ``intent_router._invoke_propose`` 已对 ``llm_propose`` 的**一切**异常做
        统一分类（``TimeoutError`` → ``llm_timeout``；其余 → ``llm_disabled``）且**绝不外抛**
        （design D-V22-12 降级铁律），故此处透传最利于留痕归因。
        """
        if not self._llm_available():
            return None
        api = getattr(self._app_ctx, "api", None)
        resp = api.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=80, temperature=0.0,
        )
        return _extract_chat_content(resp)

    def _llm_summarize(self, source_text: str) -> Optional[str]:
        """``llm_summarize`` 注入实现：``(source_text) -> str|None``（失败 → ``None``）。"""
        if not self._llm_available():
            return None
        api = getattr(self._app_ctx, "api", None)
        try:
            resp = api.chat(
                [
                    {"role": "system", "content":
                     "把下面的酒馆片段压成一小段前情提要：第二人称、不用任何数值或序号，"
                     "不要替玩家做决定。只输出提要正文。"},
                    {"role": "user", "content": source_text},
                ],
                max_tokens=200, temperature=0.3,
            )
        except Exception:
            logger.debug("酒馆摘要请求失败（回落本地摘要）", exc_info=True)
            return None
        content = _extract_chat_content(resp)
        return content if isinstance(content, str) else None

    # ==================================================================
    # 只读查询面（UI 契约）
    # ==================================================================

    def current_hud(self) -> dict:
        """顶部状态条载荷（**零序号、零数值**）。

        Returns:
            ``{chapter_title, scene_id, held_items, read_only, degraded}``。
        """
        play = self.current_play() or {}
        return {
            "chapter_title": self._chapter_title(play),
            "scene_id": _as_str(play.get("scene_id")),
            "held_items": _as_str_list((play.get("vars") or {}).get("held_items")),
            "read_only": bool(self._read_only),
            "degraded": bool((play.get("llm") or {}).get("degraded")) if isinstance(play.get("llm"), dict) else False,
        }

    def current_choices(self) -> List[dict]:
        """快捷动作 / 选项列表（**无裸 emoji**；图标由 UI 按 ``choice_id`` 取）。

        Returns:
            ``[{"choice_id", "label"}, ...]``（来源 = ``play.pending`` 快照）。
        """
        play = self.current_play()
        if not isinstance(play, dict):
            return []
        pending = play.get("pending")
        out: List[dict] = []
        if isinstance(pending, list):
            for item in pending:
                if not isinstance(item, dict):
                    continue
                cid = _as_str(item.get("choice_id"))
                if not cid:
                    continue
                # ★ P2：缺 label 时中性化，**绝不**回落 ``cid``（机器名不得上按钮 / 上屏）。
                label = (_as_str(item.get("label")).strip()
                         or _as_str(item.get("text")).strip()
                         or NEUTRAL_CHOICE_LABEL)
                out.append({"choice_id": cid, "label": label})
        return out

    def current_narrative(self) -> List[dict]:
        """叙述流（玩家 / 说书人两条，供「今夜」Tab 渲染）。

        Returns:
            ``[{"turn", "role", "text", "input_kind", "at"}, ...]``（保持时序）。
        """
        play = self.current_play()
        if not isinstance(play, dict):
            return []
        transcript = play.get("transcript")
        out: List[dict] = []
        if isinstance(transcript, list):
            for entry in transcript:
                if not isinstance(entry, dict):
                    continue
                out.append({
                    "turn": _as_int(entry.get("turn"), 0),
                    "role": _as_str(entry.get("role")),
                    "text": _as_str(entry.get("text")),
                    "input_kind": _as_str(entry.get("input_kind")),
                    "at": _as_str(entry.get("at")),
                })
        return out

    def current_transcript(self) -> List[dict]:
        """完整 ``transcript``（含 ``resolution`` 留痕）的**浅拷贝**列表。"""
        play = self.current_play()
        if not isinstance(play, dict):
            return []
        transcript = play.get("transcript")
        if not isinstance(transcript, list):
            return []
        return [dict(e) for e in transcript if isinstance(e, dict)]

    def trace(self) -> List[dict]:
        """「记录」Tab 的留痕行（只读；**不呈现成功率 / 进度 / 胜率**）。

        Returns:
            ``[{"turn", "role", "mode", "transform", "ok", "reason", "llm_used"}, ...]``。
        """
        out: List[dict] = []
        for entry in self.current_transcript():
            res = entry.get("resolution") if isinstance(entry.get("resolution"), dict) else {}
            out.append({
                "turn": _as_int(entry.get("turn"), 0),
                "role": _as_str(entry.get("role")),
                "mode": _as_str(res.get("mode")),
                "transform": _as_str(res.get("transform")),
                "ok": bool(res.get("ok")),
                "reason": _as_str(res.get("reason")),
                "llm_used": bool(res.get("llm_used")),
            })
        return out

    def current_summary(self) -> dict:
        """当前局的 ``summary``（结构化 4 键副本）。"""
        play = self.current_play()
        if not isinstance(play, dict):
            return tavern_model.default_summary()
        return tavern_summarize.normalize_summary(play.get("summary"))

    def journal_endings(self) -> List[str]:
        """跨局累积的**已抵达结局名**（只读；自然语言，**无数量 / 序号 / 进度**）。

        ``journal`` 是 ``tavern.json`` 顶层**跨局**字段（与 ``plays[]`` 物理分离）；
        其中 ``seen_endings`` 由 :meth:`_record_ending` 在终局那一拍写入（结局节点
        ``title``，如「灯该灭了」）。**本方法只读不写**：既不新增落盘键，也不改
        ``journal`` 形状（``TOP_LEVEL_KEYS`` / ``PLAY_KEYS`` 均未动）。

        为什么要有它：此前 ``journal.seen_endings`` 是**只写不读**的旁路 —— 全仓无任何
        展示面，玩家抵达过的结局**看不到**。本方法即那个展示面的唯一数据源。

        Returns:
            结局名列表（保持写入顺序、去重、丢弃空项）；无 journal / 非法形状 → 空表。
        """
        data = self._ensure_loaded()
        journal = data.get("journal")
        raw = journal.get("seen_endings") if isinstance(journal, dict) else None
        if not isinstance(raw, list):
            return []
        out: List[str] = []
        for name in raw:
            if isinstance(name, str) and name.strip() and name.strip() not in out:
                out.append(name.strip())
        return out

    def chapter_title(self) -> str:
        """当前章的标题（**无序号**，Q4）。"""
        return self._chapter_title(self.current_play() or {})

    def worldbook_entries(self) -> dict:
        """「世界书」Tab 快照。

        绑定书（``tavern.json`` 的 ``library.books``）为空时**回退内置只读内容包**：
        内置包始终随包分发、且每拍真实参与 prompt 命中，若不回退，本 Tab 会恒显示空态
        —— 「入口在、内容也在，却什么都看不到」。回退**只读**：不写 ``library.books``
        （那属用户数据，是否播种是另一个设计决定）。

        Returns:
            ``{"book_id", "title", "entries", "budget_chars"}``；内置包也读不到 → 空 entries。
        """
        play = self.current_play() or {}
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        slot = self._book_slot(book_id)
        settings = self._settings()
        entries: List[dict] = []
        title = ""
        if isinstance(slot, dict):
            entries = slot.get("entries") if isinstance(slot.get("entries"), list) else []
            title = _as_str(slot.get("title"))
        if not entries:
            entries, builtin_title = self._builtin_worldbook(book_id)
            title = title or builtin_title or _as_str(play.get("title"))
        return {
            "book_id": book_id,
            "title": title,
            "entries": entries,
            "budget_chars": _as_int(settings.get("worldbook_budget_chars"), 0),
        }

    def _builtin_worldbook(self, book_id: str) -> tuple:
        """内置内容包的（条目, 书标题）—— 只读；异常一律吞掉并回落空表（**绝不抛**）。"""
        try:
            result = tavern_worldbook.load_builtin_book(book_id)
        except Exception:
            logger.debug("内置世界书加载失败，回落空表: %s", book_id, exc_info=True)
            return [], ""
        raw_entries = getattr(result, "entries", None)
        entries = [dict(e) for e in raw_entries if isinstance(e, dict)] if isinstance(raw_entries, list) else []
        content = self._content_for(book_id)
        worldbook = content.get("worldbook") if isinstance(content, dict) else None
        worldbook = worldbook if isinstance(worldbook, dict) else {}
        return entries, _as_str(worldbook.get("title"))

    def worldbook_hits(self) -> dict:
        """本拍世界书命中快照（最近一次的 ``WorldbookSelection``；无 → 空）。

        Returns:
            ``{"entries", "by_position", "used_chars", "trimmed"}``（条目为只读快照）。
        """
        selection = self._last_selection
        if selection is None:
            return {"entries": [], "by_position": {p: [] for p in tavern_model.LORE_POSITIONS},
                    "used_chars": 0, "trimmed": 0}
        by_position: Dict[str, List[dict]] = {}
        raw = getattr(selection, "by_position", {}) or {}
        for pos in tavern_model.LORE_POSITIONS:
            entries = raw.get(pos) if isinstance(raw, dict) else None
            by_position[pos] = [dict(e) for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
        return {
            "entries": [dict(e) for e in (getattr(selection, "entries", []) or []) if isinstance(e, dict)],
            "by_position": by_position,
            "used_chars": _as_int(getattr(selection, "used_chars", 0), 0),
            "trimmed": _as_int(getattr(selection, "trimmed", 0), 0),
        }

    def get_settings(self) -> dict:
        """当前酒馆设置副本（``tavern.json.settings``；只读）。"""
        return dict(self._settings())

    def set_settings(self, **kwargs: Any) -> bool:
        """写入酒馆设置（**仅接受已知键 + 类型相符者**）；落盘点仍为 ``save``。

        Returns:
            ``True`` 表示确有改动并已尝试落盘。
        """
        data = self._ensure_loaded()
        settings = data.get("settings")
        if not isinstance(settings, dict):
            settings = tavern_model.default_settings()
            data["settings"] = settings
        changed = False
        for key, value in kwargs.items():
            if key not in tavern_model.SETTING_KEYS:
                continue
            default = tavern_model.SETTING_DEFAULTS[key]
            if _type_matches(value, default):
                if settings.get(key) != value:
                    settings[key] = value
                    changed = True
        if changed:
            self._save()
        return changed

    def is_read_only(self) -> bool:
        """是否处于 L4 只读会话（可玩、不落盘、不崩）。"""
        return bool(self._read_only)

    def is_busy(self) -> bool:
        """是否正在生成一拍（供输入禁用 / 省略号节奏指示）。"""
        return bool(self._busy)

    # —— 全局派生值：**读时现取，禁止缓存**（§6.5） ——

    def motion_enabled(self) -> bool:
        """当前是否应播放动效（**每次现取** ``motion.enabled()``；换档位即时生效）。"""
        from gui import motion
        return bool(motion.enabled())

    def motion_level(self) -> str:
        """当前动效档位（**每次现取** ``motion.level()``）。"""
        from gui import motion
        return str(motion.level())

    def motion_duration(self, base_ms: int = 0) -> int:
        """动效时长单一收口（**每次现取** ``motion.duration``；禁硬编码 ms）。"""
        from gui import motion
        return int(motion.duration(base_ms))

    def theme_color(self, key: str, fallback: str) -> str:
        """主题色（**每次现取** ``gui.utils.theme_color``；**不缓存 QColor / 色值**）。"""
        from gui.utils import theme_color as _theme_color
        return _theme_color(self._app_ctx, key, fallback)

    # ==================================================================
    # 内部辅助
    # ==================================================================

    def _settings(self) -> dict:
        """当前设置（缺省回合类默认；**不缓存**）。"""
        data = self._ensure_loaded()
        raw = data.get("settings")
        merged = dict(tavern_model.SETTING_DEFAULTS)
        if isinstance(raw, dict):
            for key, value in raw.items():
                merged[key] = value
        return merged

    def _allow_free_input(self) -> bool:
        return bool(self._settings().get("allow_free_input", True))

    def _seed_seen_nodes(self, play: dict) -> None:
        """把当前节点记入 ``seen_nodes`` —— 否则 storylet 选择会在下一步把它再挑一次。"""
        if not isinstance(play, dict):
            return
        nid = _as_str(play.get("node_id"))
        seen = _as_str_list(play.get("seen_nodes"))
        if nid and nid not in seen:
            play["seen_nodes"] = seen + [nid]

    def _advance_node(self, play: dict) -> bool:
        """按 storylet 条件推进 ``node_id`` —— 补上 design-v22 §4.2 第 678 行留下的缺口。

        设计原文写明 ``prerequisites`` 是**节点字段、engine 不读**，消费方须"另约定键名"；
        本方法就是那个消费方，落在服务层（**不动冻结的** ``engine.py``）。

        规则（确定性；**内容包书写顺序即优先级**）：
            1. 候选 = 同时满足「``prerequisites`` 全键匹配当前状态」且
               「``id`` 未出现在 ``seen_nodes``」且「≠ 当前 ``node_id``」的节点；
            2. 取候选中的**第一个**，写 ``node_id`` 并追加进 ``seen_nodes``；
            3. 无候选 → **保持当前节点**（选项不消失，绝不把玩家卡进死路）。

        只写 ``node_id`` / ``seen_nodes``；不碰 ``vars`` / ``scene_id`` / ``turn``；
        **绝不触碰 ``chapter_id``**（硬禁区字段）。

        Returns:
            是否发生了推进。
        """
        if not isinstance(play, dict):
            return False
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        content = self._content_for(book_id)
        chapters = content.get("chapters") if isinstance(content, dict) else None
        if not isinstance(chapters, list):
            return False

        current = _as_str(play.get("node_id"))
        seen = _as_str_list(play.get("seen_nodes"))
        state = self._storylet_state(play)

        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            nodes = chapter.get("nodes")
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                nid = _as_str(node.get("id"))
                if not nid or nid == current or nid in seen:
                    continue
                if not _prerequisites_met(node.get("prerequisites"), state):
                    continue
                play["node_id"] = nid
                play["seen_nodes"] = seen + [nid]
                return True
        return False

    def _sync_pending(self, play: dict) -> None:
        """按当前节点刷新 ``play["pending"]``（快捷动作 / 选项排的**唯一数据源**）。

        为什么必须有这一步：``current_choices()`` 只读 ``play["pending"]``，而 ``pending``
        在 :func:`gui.tavern.model.new_play` 里默认空表、**没有任何别处写它** —— 不刷新就
        恒为空，于是 UI 把整排按钮隐藏（"入口在、数据在、就是不通"）。

        数据源优先级：
            1. 当前节点（``play["node_id"]`` 所在 ``nodes[]`` 项）的 ``choices`` ——
               **空列表同样采信**：那是终局节点，选项排本就该隐藏；
            2. 按 ``node_id`` 找不到节点时回落内容包 ``quick_actions``，保证这一排
               不会莫名空死（终局节点**不**走这条回落）。

        选项级前置条件：``choices[].prerequisites`` 不满足者**不进选项排**（点了也只会
        被 ``pre`` 拒绝，是纯死按钮）。未写 ``prerequisites`` 的选项照旧放行（向后兼容）。

        只写 ``pending`` 一个字段；**不动**任何推进状态
        （``vars`` / ``node_id`` / ``chapter_id`` / ``turn``）。
        """
        if not isinstance(play, dict):
            return
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        content = self._content_for(book_id)
        if not isinstance(content, dict):
            play["pending"] = []
            return

        node = self._find_content_node(content, _as_str(play.get("node_id")))
        snaps: List[dict] = []
        if node is not None:
            raw_choices = node.get("choices")
            if isinstance(raw_choices, list):
                state = self._storylet_state(play)
                for choice in raw_choices:
                    # 前置条件不过 → 不进选项排（点了也只会拿到 pre 拒绝，纯死按钮）。
                    # 未写 ``prerequisites`` 的选项照旧放行（向后兼容）。
                    if not _prerequisites_met(
                        choice.get("prerequisites") if isinstance(choice, dict) else None,
                        state,
                    ):
                        continue
                    snap = _choice_snapshot(choice, "choice_id")
                    if snap is not None:
                        snaps.append(snap)
        else:
            raw_actions = content.get("quick_actions")
            if isinstance(raw_actions, list):
                for action in raw_actions:
                    snap = _choice_snapshot(action, "action_id")
                    if snap is not None:
                        snaps.append(snap)
        play["pending"] = snaps

    @staticmethod
    def _storylet_state(play: dict) -> Dict[str, Any]:
        """storylet / 选项准入判定的状态面 = ``vars`` ∪ ``{scene_id}``。

        **单一来源**：``_advance_node``（节点准入）与 ``_sync_pending``（选项准入）共用本方法，
        保证「节点能被选中」与「选项能被点」用的是同一把尺子。
        """
        vars_map = play.get("vars") if isinstance(play, dict) else None
        state: Dict[str, Any] = dict(vars_map) if isinstance(vars_map, dict) else {}
        state["scene_id"] = _as_str(play.get("scene_id")) if isinstance(play, dict) else ""
        return state

    def _echo_text(self, play: dict, text: str, input_kind: str, content: Any = None) -> str:
        """玩家条**对外**文本：``input_kind == "choice"`` 时换成该选项的中文 label。

        为什么：``submit(text, input_kind)`` 的 ``text`` 在 ``choice`` 档是 **choice_id**
        （router ``resolve_choice`` 靠它路由，签名冻结不可改），但它同时被写进
        ``transcript`` → 存档与 ``turn_context`` 里就出现了 ``sit_down`` 这类英文机器名，
        界面上玩家看到的是自己的输入变成 ``sit_down``。机器名只保留在 ``resolution`` 留痕里。

        ★ A2-4（P1）：**查不到 label 时绝不回落原 ``text``** —— 那正是机器名，会 fail-open
        写回存档。三级取值：``pending`` 快照 → 内容包反查 → 中性中文占位
        :data:`NEUTRAL_CHOICE_ECHO`。不变量：``choice`` 档下 ``transcript`` 与提示词
        **任何路径**都不出现 ``choice_id`` 形态的机器名。
        """
        if input_kind != "choice":
            return text
        label = _choice_label(play.get("pending") if isinstance(play, dict) else None, text)
        if not label:
            label = _content_choice_label(content, text)
        return label or NEUTRAL_CHOICE_ECHO

    @staticmethod
    def _chapter_key(content: dict, node_id: str) -> str:
        """节点所属章的**稳定标识**（仅用于比较「是否换章」；**只读**，绝不写 ``chapter_id``）。

        找不到归属章 → 空串（比较时视为「不可判定」，不产生换章信号）。
        """
        if not node_id or not isinstance(content, dict):
            return ""
        chapters = content.get("chapters")
        if not isinstance(chapters, list):
            return ""
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            nodes = chapter.get("nodes")
            if not isinstance(nodes, list):
                continue
            if any(isinstance(node, dict) and node.get("id") == node_id for node in nodes):
                return (_as_str(chapter.get("chapter_id")) or _as_str(chapter.get("id"))
                        or _as_str(chapter.get("title")))
        return ""

    def _is_terminal_node(self, content: dict, play: dict) -> bool:
        """当前节点是否为**终局节点**（``choices`` 显式为空表）。

        口径从严：节点不存在 / 无 ``choices`` 键 / ``choices`` 非列表 → **不算终局**
        （宁可少判，也不把中途节点误标为已结束）。
        """
        node = self._find_content_node(content, _as_str(play.get("node_id")))
        if node is None:
            return False
        choices = node.get("choices")
        return isinstance(choices, list) and not choices

    def _record_ending(self, data: dict, content: dict, play: dict) -> None:
        """终局时写一条跨局 journal 记录（**自然语言、无数值、无序号**；幂等）。

        ``seen_endings`` 记的是**结局的名字**（终局节点 ``title``，如「灯该灭了」），
        不是节点 id / uid —— 那是机器名，也是 R-A 红线的数值/序号面。
        """
        node = self._find_content_node(content, _as_str(play.get("node_id")))
        name = _as_str((node or {}).get("title")).strip() or self._chapter_title(play)
        if not name:
            name = "这一夜到此为止"
        try:
            TavernStore.append_journal(data, "seen_endings", name)
        except Exception:
            logger.debug("酒馆结局留痕失败（不影响这一拍）", exc_info=True)

    @staticmethod
    def _find_content_node(content: dict, node_id: str) -> Optional[dict]:
        """在 ``content["chapters"][*]["nodes"][*]`` 里按 id 找节点（找不到 → ``None``）。"""
        if not node_id:
            return None
        chapters = content.get("chapters")
        if not isinstance(chapters, list):
            return None
        for chapter in chapters:
            if not isinstance(chapter, dict):
                continue
            nodes = chapter.get("nodes")
            if not isinstance(nodes, list):
                continue
            for item in nodes:
                if isinstance(item, dict) and _as_str(item.get("id")) == node_id:
                    return item
        return None

    def _content_for(self, book_id: str) -> dict:
        """内容包解析（**唯一入口** = ``worldbook.load_content``；按 book 缓存，静态内容）。"""
        bid = _as_str(book_id) or FALLBACK_BOOK_ID
        cached = self._content_cache.get(bid)
        if isinstance(cached, dict):
            return cached
        try:
            content = tavern_worldbook.load_content(bid)
        except Exception:
            logger.debug("酒馆内容包加载失败，回落空内容包: %s", bid, exc_info=True)
            content = {}
        if not isinstance(content, dict):
            content = {}
        self._content_cache[bid] = content
        return content

    def _book_slot(self, book_id: str) -> Optional[dict]:
        """在 ``library.books`` 中按 ``book_id`` 找书槽。"""
        data = self._ensure_loaded()
        library = data.get("library")
        books = library.get("books") if isinstance(library, dict) else None
        if not isinstance(books, list):
            return None
        for slot in books:
            if isinstance(slot, dict) and slot.get("book_id") == book_id:
                return slot
        return None

    def _worldbook_for(self, play: dict, settings: dict) -> Any:
        """构造本拍 ``WorldBook``（优先 ``library`` 绑定书；否则随包内容包）。失败 → ``None``。

        ★ 接线（此前三处「假机制」的根因）：
            * **补传 ``rng``**：``WorldBook.collect`` 的 ``probability`` 只在显式注入 ``rng``
              时才参与判定（``rng=None`` → 恒真）。不传 = 条目 ``probability`` 形同虚设。
              rng 由 ``play["seed"]`` + 当前拍确定性派生（同档同拍 ⇒ 同结果，可复现）。
            * **补传 ``ledger``**：``sticky`` / ``cooldown`` 需要「上一次激活是第几拍」的账本；
              ``WorldBook`` 每拍重建，账本必须由本服务持有并跨拍传递（会话内内存态，见 ``__init__``）。
            * **A2-1/A2-2**：无论走**绑定书**还是**内置包**，都**必须**跑 ``collect`` 并刷新
              :attr:`_last_selection` —— 它既是「世界书」Tab 快照，也是**本拍提示词**的世界书
              来源（``_render_messages`` 把同一份 selection 传给 prompt）。绑定书分支
              **不得**提前 ``return``（那会让 Tab 恒空 / 陈旧，且 rng/ledger 不被消费）。
        """
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        # 先清空本拍快照：任何失败路径都不得让上一拍的陈旧 selection 冒名顶替
        self._last_selection = None
        try:
            slot = self._book_slot(book_id)
            if isinstance(slot, dict) and isinstance(slot.get("entries"), list):
                book = tavern_worldbook.WorldBook.from_result(slot["entries"], settings)
            else:
                result = tavern_worldbook.load_builtin_book(book_id)
                book = tavern_worldbook.WorldBook.from_result(result, settings)
        except Exception:
            logger.debug("酒馆世界书构造失败，按空世界规则继续", exc_info=True)
            return None
        # 记录本拍选中文档（「世界书」Tab 快照 + 本拍提示词共用**同一份**）
        try:
            self._last_selection = book.collect(
                self._recent_texts(play),
                rng=self._lore_rng(play),
                turn=_as_int(play.get("turn"), 0),
                ledger=self._lore_ledger(play),
            )
        except Exception:
            logger.debug("酒馆世界书 collect 失败（不影响 prompt）", exc_info=True)
            self._last_selection = None
        return book

    def _lore_rng(self, play: dict) -> Any:
        """世界书 ``probability`` 用的**确定性**随机源（``seed`` + 当前拍，绝不用全局 random）。"""
        seed = _as_int(play.get("seed"), 0) if isinstance(play, dict) else 0
        turn = _as_int(play.get("turn"), 0) if isinstance(play, dict) else 0
        return tavern_engine.derive_rng(seed, turn)

    def _lore_ledger(self, play: dict) -> Dict[int, int]:
        """取（必要时新建）该局的 sticky / cooldown 激活账本 ``{uid: 最后激活拍}``。"""
        pid = _as_str(play.get("play_id")) if isinstance(play, dict) else ""
        ledger = self._lore_ledgers.get(pid)
        if not isinstance(ledger, dict):
            ledger = {}
            self._lore_ledgers[pid] = ledger
        return ledger

    @staticmethod
    def _recent_texts(play: dict) -> List[str]:
        """取 ``transcript`` 的可读文本（升序），供世界书关键词扫描。"""
        transcript = play.get("transcript") if isinstance(play, dict) else None
        if not isinstance(transcript, list):
            return []
        out: List[str] = []
        for entry in transcript:
            if isinstance(entry, dict):
                text = _as_str(entry.get("text"))
                if text:
                    out.append(text)
        return out

    def _relation_ctx(self, persona: dict) -> dict:
        """只读关系上下文（**Q2：只读，绝不写回**）。

        读 ``companion.relation_stage_name()``（缺则回退 ``intimacy.level_name()``）
        作称呼 / 语气提示；``name`` 取 persona 的 ``display_name``（given_name 或产品名）。
        """
        ctx: Dict[str, Any] = {"name": _as_str(persona.get("display_name")) or PRODUCT_NAME}
        stage = self._read_relation_stage()
        if stage:
            ctx["stage_name"] = stage
        return ctx

    def _read_relation_stage(self) -> str:
        """读取关系阶段名（**只读**；任何失败 → 空串）。"""
        companion = getattr(self._app_ctx, "companion", None)
        if companion is not None:
            fn = getattr(companion, "relation_stage_name", None)
            if callable(fn):
                try:
                    stage = _as_str(fn()).strip()
                    if stage:
                        return stage
                except Exception:
                    logger.debug("读取关系阶段失败（只读，忽略）", exc_info=True)
        tracker = getattr(self._app_ctx, "intimacy", None)
        if tracker is not None:
            fn2 = getattr(tracker, "level_name", None)
            if callable(fn2):
                try:
                    return _as_str(fn2()).strip()
                except Exception:
                    logger.debug("读取亲密度档名失败（只读，忽略）", exc_info=True)
        return ""

    def _chapter_title(self, play: dict) -> str:
        """章标题（**无序号**）：按**当前节点归属的章**取，逐级回落。

        真值来源是 ``play["node_id"]``（受控 ``effects`` 可写、实际在推进），**不是**
        ``chapter_id`` —— 后者是硬禁区字段（``engine._CROSS_CHAPTER_FIELDS``），
        **全仓无写入点、恒为 ``ch1``**；只按它取会永远停在开头那一章，反而更误导。
        三级回落（**只读，不写任何 state**）：

            1. 当前 ``node_id`` 所属的章标题（语义正确的那一级：「玩家现在在哪一章」）；
            2. ``chapter_id`` 查找（**两个键都认**：``chapter_id`` / ``id``，兼容旧写法）；
            3. 局标题 ``play["title"]``。

        纯读：``vars`` / ``node_id`` / ``chapter_id`` / ``turn`` 一律**不动**；
        也**绝不写** ``chapter_id``（它是硬禁区字段）。
        """
        if not isinstance(play, dict):
            return ""
        book_id = _as_str(play.get("book_id")) or FALLBACK_BOOK_ID
        content = self._content_for(book_id)
        chapters = content.get("chapters") if isinstance(content, dict) else None
        if isinstance(chapters, list):
            # 1) 按当前 node_id 归属的章（真值来源：玩家的实际位置）
            node_id = _as_str(play.get("node_id"))
            if node_id:
                for chapter in chapters:
                    if not isinstance(chapter, dict):
                        continue
                    nodes = chapter.get("nodes")
                    if not isinstance(nodes, list):
                        continue
                    if any(isinstance(node, dict) and node.get("id") == node_id for node in nodes):
                        title = _as_str(chapter.get("title")).strip()
                        if title:
                            return title
            # 2) 回落 chapter_id（两个键都认：chapter_id / id）
            cid = _as_str(play.get("chapter_id"))
            if cid:
                for chapter in chapters:
                    if not isinstance(chapter, dict):
                        continue
                    if chapter.get("chapter_id") == cid or chapter.get("id") == cid:
                        title = _as_str(chapter.get("title")).strip()
                        if title:
                            return title
        # 3) 回落局标题
        return _as_str(play.get("title"))

    def _default_title(self, book_id: str) -> str:
        """新局默认标题：优先内容包书标题，回落中性标题（**无序号**）。"""
        content = self._content_for(book_id)
        worldbook = content.get("worldbook") if isinstance(content, dict) else None
        if isinstance(worldbook, dict):
            title = _as_str(worldbook.get("title")).strip()
            if title:
                return title
        return "灯笼酒馆"

    @staticmethod
    def _narrator_index(play: dict, turn: int) -> int:
        """返回某拍**叙述条目**在 ``transcript`` 中的下标（找不到 → ``-1``）。"""
        transcript = play.get("transcript") if isinstance(play, dict) else None
        if not isinstance(transcript, list):
            return -1
        for index in range(len(transcript) - 1, -1, -1):
            entry = transcript[index]
            if (isinstance(entry, dict) and entry.get("role") == "narrator"
                    and _as_int(entry.get("turn"), -2) == turn):
                return index
        return -1

    @staticmethod
    def _player_text_for_turn(play: dict, turn: int) -> str:
        """取某拍玩家条文本（供重掷 prompt 的 turn_context）。"""
        transcript = play.get("transcript") if isinstance(play, dict) else None
        if not isinstance(transcript, list):
            return ""
        for entry in transcript:
            if (isinstance(entry, dict) and entry.get("role") == "player"
                    and _as_int(entry.get("turn"), -2) == turn):
                return _as_str(entry.get("text"))
        return ""

    @staticmethod
    def _new_play_id() -> str:
        """生成局 id（不依赖墙钟；随机源仅用于唯一性）。"""
        return "p_" + uuid.uuid4().hex[:10]

    @staticmethod
    def _new_seed() -> int:
        """生成显式 seed（持久化；不依赖全局 ``random``）。"""
        return (uuid.uuid4().int % 9_000_000) + 1_000_000

    # ==================================================================
    # 唯一落盘点
    # ==================================================================

    def _save(self) -> bool:
        """**唯一**落盘调用点（``TavernStore.save``）；被拒（L4 只读）即优雅降级。

        Returns:
            ``True`` 表示已写盘；``False`` 表示只读会话（不崩、不弹框，仅中性提示）。
        """
        if self._read_only:
            self.degraded.emit(READ_ONLY_HINT)
            return False
        try:
            self._store.save(self._data)
            return True
        except TavernStoreError:
            logger.debug("酒馆落盘被拒 / 失败，转入只读会话（优雅降级）", exc_info=True)
            self._enter_read_only()
            return False

    def _enter_read_only(self) -> None:
        """进入只读会话（幂等）：置标 + 广播中性提示（**不弹错误框**）。"""
        if not self._read_only:
            self._read_only = True
            self.read_only_changed.emit(True)
        self.degraded.emit(READ_ONLY_HINT)


# ===========================================================================
# LLM 响应小工具
# ===========================================================================

def _extract_chat_content(resp: Any) -> Optional[str]:
    """从 OpenAI 兼容返回体里抽出 ``content`` 文本（容忍多种形状；失败 → ``None``）。"""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        choices = resp.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
                if isinstance(first.get("text"), str):
                    return first["text"]
        if isinstance(resp.get("content"), str):
            return resp["content"]
    return None
