"""用户偏好记忆系统 — 结构化 JSON 记忆存储与自动提取。"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from utils import _atomic_write_json


# ---------------------------------------------------------------------------
# 默认记忆结构
# ---------------------------------------------------------------------------
_DEFAULT_MEMORY = {
    "preferences": {},
    "topics": {
        "active": [],
        "archived": [],
    },
    "habits": {
        "common_commands": [],
        "typical_session_time": "",
    },
    # v1.6(D-V16-01): 情绪历史（上限 _EMOTIONS_HISTORY_MAX，append 淘汰最旧）
    "emotions": [],
    # v1.6(D-V16-01 #7): 内容源级静默（"__emotion__" / "__todo__" -> ISO 截止时间）
    "source_muted_until": {},
    # v1.8(D-V18-01/Q-D1): 记忆图谱实体（人物关系），读时迁移补键
    "entities": [],
    # v1.8(D-V18-05/Q-D9): 回应规则（"以后我说 XX 你要 YY"），读时迁移补键
    "response_rules": [],
    # v1.8(D-V18-08/Q-D8): 影像记忆（F7 多模态记忆）——只存"对话事实"（文字摘要
    # + 中性图片描述），绝不存图像二进制 / data URI / base64（R-I 硬线）；
    # 读时迁移补键 + 50 条滚动淘汰（超出删最旧）。
    "vision_memories": [],
    "meta": {
        "created_at": "",
        "updated_at": "",
        "version": 1,
    },
}

# v1.6(D-V16-01): followup / 情绪历史常量（Q-B7 静默 14 天、Q-B8 情绪上限 200，可调）
_FOLLOWUP_MUTE_DAYS = 14        # 「先不提」话题静默天数
_SOURCE_MUTE_DAYS = 3           # 情绪延续/待办轻提内容源静默天数
_EMOTIONS_HISTORY_MAX = 200     # 情绪历史上限
_FOLLOWUP_DEDUP_DAYS = 7        # 续接提问去重窗口
_SOURCE_MUTE_KEYS = ("__emotion__", "__todo__")
_PREFERENCE_SOURCES = ("auto", "manual", "legacy")

# v2.4(D-V24-03): 续接优先级多因子评分常量（可调）。吸收 ALTM governor 的三条
# 设计——「多因子加权」「软时间衰减」「有用信号优先」——按本模块语义裁剪。
# 与既有硬门正交：硬门（muted 静默 / 7 天去重 / [min,max] 时间窗）决定"能不能
# 提"，本评分只决定"先提哪个"。评分为**纯内部计算量**：不落任何字段、不入 UI、
# 不入注入串、不进日志文案（R-A 无数值化）。
_FOLLOWUP_HALF_LIFE_HOURS = 36.0   # 时间衰减**半衰期**（72h 时间窗 = 两个半衰期，窗边缘权重 0.25）
_FOLLOWUP_W_USEFUL = 0.40          # 有用信号权重（heart；对应 ALTM 的 useful_access）
_FOLLOWUP_W_RECENCY = 0.40         # 时间近因权重
_FOLLOWUP_W_EVIDENCE = 0.20        # 来源可信度权重
_FOLLOWUP_USE_PER_HEART = 0.20     # 单次 heart 的 useful 增量（clamp 到 1.0）
_FOLLOWUP_EVIDENCE = {"manual": 1.0, "auto": 0.6, "legacy": 0.7}

# v1.8(D-V18-01/Q-D1): 记忆图谱实体常量 —— 上限拒写、绝不自动淘汰（人物记忆
# 不悄悄消失，R-I）；relation 开放枚举（列表值 + 自定义文本均可）。
_ENTITY_MAX = 100              # 实体上限
_ENTITY_EVENT_MAX = 20         # 每实体事件上限（按时间倒序）
_ENTITY_SOURCES = ("manual", "assistant_proposed")
_ENTITY_RELATION_PRESETS = ("同事", "朋友", "家人", "恋人", "同学", "其他")

# v1.8(D-V18-03): 情绪概览纯规则模板（档位词、零数字、零 LLM，≤80 字符）。
# 键 = detect_emotion 既有情绪分类；同分时按 _EMOTION_OVERVIEW_PRIORITY 顺序
# 取先者（确定性输出，无随机）。
_EMOTION_OVERVIEW_TEMPLATES = {
    "tired": "多数时候有点累，记得让自己歇一歇。",
    "happy": "元气的时候多一些，真替你开心。",
    "anxious": "心里装着事的时候多一些，别急，慢慢来。",
    "lonely": "安静独处的日子多了一些，码铃一直都在。",
}
_EMOTION_OVERVIEW_PRIORITY = ("tired", "anxious", "lonely", "happy")

# v1.8(D-V18-05/Q-D9): 回应规则常量 —— 上限 20 条拒写不淘汰；trigger/response
# 超长清洗截断（录入友好）；last_hit_at 仅作"上次生效"呈现原料（R-A 不计次数）。
_RULES_MAX = 20
_RULE_TRIGGER_MAX = 20         # 触发词字数上限
_RULE_RESPONSE_MAX = 100       # 回应风格描述字数上限
_RULE_MATCH_LIMIT = 3          # 单轮注入规则数上限
_RULE_SOURCES = ("manual", "assistant_proposed")

# v1.8(D-V18-08/Q-D8): 影像记忆常量 —— 50 条**滚动淘汰**（超出删最旧，与实体/
# 规则的"拒写不淘汰"不同：影像记忆是对话的自然余烬，滚动淘汰是设计裁决 Q-D8）。
# R-I 硬线：任何字段绝不落图像二进制 / data URI / base64（写入前清洗 + 迁移
# 清洗 + 文件内容断言三重防线）；image_note 恒为中性描述（存的是"对话事实"，
# 不是"识别结果"——增强档失败也绝不编造，R-K 诚实边界）。
_VISION_MEMORY_MAX = 50              # 上限（滚动淘汰删最旧）
_VISION_USER_TEXT_MAX = 50           # 配文摘要字数上限
_VISION_DIGEST_MAX = 200             # assistant 回复摘要字数上限
_VISION_NOTE_MAX = 60                # 图片中性描述字数上限
_VISION_SOURCES = ("default", "enhanced")
# v2.5(D-V25-03): 值对齐实际行为后接线（原值「主人发过一张截图」从未被使用，
# 实际代码走的是硬编码字符串——常量与实现漂移，本版收口为单一事实源）。
_VISION_NOTE_DEFAULT = "用户分享了一张图片"     # 默认档中性描述
_VISION_NOTE_UNSEEN = "当时无法识别内容"        # 诚实边界①：看图失败仍存档时的描述

# 偏好提取关键词规则
_PREFERENCE_PATTERNS = [
    (r"(?:我喜欢|我爱|我偏好|我习惯|我常|我通常|我主要)\s*[:：]?\s*(.+?)(?:[。！？\n]|$)", "preference"),
    (r"(?:叫我|称呼我|请叫我|你可以叫我)\s*[:：]?\s*(.+?)(?:[。！？\n]|$)", "nickname"),
    (r"(?:我用|我用的是|我使用|我主要用)\s*([A-Za-z+#]+)\s*(?:写|开发|编程|做)", "language"),
    (r"(?:我的风格是|我喜欢写|我倾向|我偏好)\s*(简洁|详细|注释多|类型安全|面向对象|函数式)", "code_style"),
]

# 话题提取关键词规则
# v2.4(D-V24-02): 第三条分隔词由**可选改必选**并加前导锚点。原写法
# `(?:项目|任务|工作)\s*(?:叫|是|关于)?\s*[:：]?\s*(.+?)` 在分隔词全部缺省时，
# 会捕获裸名词提及之后的整句剩余部分——「这个项目做完了」→ 话题「做完了」。
# 前导锚点（句首/标点/空白）+ 必选分隔符（叫/是/关于/冒号）挡住该类误捕；
# 「项目：做个网站」「我的项目是做个网站」仍正常提取（精度优先于召回）。
_TOPIC_PATTERNS = [
    (r"(?:我在学|我在学习|我在看|我在研究|我在做|我在搞|我在尝试)\s*(.+?)(?:[。！？\n]|$)", "ongoing"),
    (r"(?:最近在|最近我在|最近在搞|最近在忙)\s*(.+?)(?:[。！？\n]|$)", "ongoing"),
    (r"(?:^|[。！？；;，,\s])(?:我的|这个|那个)?(?:项目|任务|工作)\s*(?:叫|是|关于|[:：])\s*[:：]?\s*(.+?)(?:[。！？\n]|$)", "ongoing"),
]
_TOPIC_SUBJECT_MAX = 30        # v2.4(D-V24-02): 话题字数上限（原硬编码 100 过宽，长句必是误捕）

# v2.5(D-V25-04): 话题完成句式 —— 命中完成句式**且**本轮同时提及该话题
#（subject 整串或其 ≥2 字空格分词出现在消息里）才自动 complete_topic；
# 只说「搞定了」不点名话题时**绝不猜测**（防误归档，R-K 诚实边界）。
_TOPIC_COMPLETION_PATTERNS = (
    "搞定了", "完成了", "做完了", "上线了", "考完了", "验收了",
    "交付了", "收尾了", "收官了", "通关了", "拿到了offer",
)

# v2.5(D-V25-06): 外挂词表文件名（位于记忆文件同目录，即 ~/.maid_coder/）。
# 存在且可解析时与内置词表**合并**（追加式热补，不必复制全部内置条目）；
# 不存在 / 损坏 / 字段类型不对 → 静默回落内置词表，绝不抛错（R-K）。
_PATTERNS_FILE = "memory_patterns.json"

# 情绪关键词检测
_EMOTION_KEYWORDS = {
    "tired": ["累", "疲惫", "困", "忙", "压力大", "加班", "熬", "筋疲力尽", "好累"],
    "happy": ["开心", "高兴", "搞定", "成功", "上线", "庆祝", "棒", "太好了", "顺利"],
    "anxious": ["焦虑", "担心", "不会", "难", "卡住了", "困惑", "迷茫", "不知所措"],
    "lonely": ["无聊", "没事做", "孤单", "寂寞", "没人", "空虚"],
}


# ---------------------------------------------------------------------------
# v2.4(P0-1): 落盘安全网常量 —— 对齐 gui/tavern/store.py 既有约定（L5 快照恢复 /
# L6 损坏档改名保留）。记忆文件在 GUI 下改为每轮对话都写，损坏后被默认结构静默
# 覆盖的风险随之放大，故补齐同款防护。单槽即可：目标是"始终有一份上次完好状态"，
# 不做历史版本回溯。
_MEMORY_BACKUPS = 1
_BACKUP_SUFFIX = ".bak"
_CORRUPT_SUFFIX = ".corrupt"


def _memory_dir() -> str:
    """返回记忆文件存储目录。"""
    d = os.path.expanduser("~/.maid_coder")
    os.makedirs(d, exist_ok=True)
    return d


def _memory_path() -> str:
    """返回用户记忆文件路径。"""
    return os.path.join(_memory_dir(), "user_memory.json")


def parse_iso_dt(value) -> Optional[datetime]:
    """ISO 字符串 -> datetime；空/非法返回 None（v1.6 followup 字段解析用）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
class MemoryManager:
    """用户偏好记忆管理器：结构化存储、自动提取、持久化。"""

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath or _memory_path()
        # v2.5(D-V25-01): 进程内锁 —— GUI 主线程写 + 日记 daemon 线程读并存，
        # _save 的「快照轮转 + 原子写」两步必须串行化（跨进程仍靠 .bak.1 快照兜底）。
        self._lock = threading.RLock()
        # v2.5(D-V25-06): 外挂词表缓存（(mtime_ns, size) 变更自动重载）
        self._patterns_cache: Optional[dict] = None
        self._patterns_stamp: Optional[tuple] = None
        self._data = self._load()

    def _patterns_path(self) -> str:
        """外挂词表路径：记忆文件同目录（真实安装 = ~/.maid_coder/；测试 = tmp_path）。"""
        return os.path.join(os.path.dirname(os.path.abspath(self.filepath)),
                            _PATTERNS_FILE)

    def _effective_patterns(self) -> dict:
        """内置词表 + 外挂 memory_patterns.json 合并（v2.5/D-V25-06，mtime 热补）。

        返回 {"preference": [...], "topic": [...], "completion": [...],
        "emotion_keywords": {...}}；外挂条目**追加**在内置之后（正则按序首命中，
        内置优先级不受影响）。外挂文件损坏/类型不对 → 静默只用内置（绝不抛错）。
        """
        built = {
            "preference": list(_PREFERENCE_PATTERNS),
            "topic": list(_TOPIC_PATTERNS),
            "completion": list(_TOPIC_COMPLETION_PATTERNS),
            "emotion_keywords": {k: list(v) for k, v in _EMOTION_KEYWORDS.items()},
        }
        path = self._patterns_path()
        try:
            stat = os.stat(path)
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._patterns_cache = None
            self._patterns_stamp = None
            return built
        if self._patterns_cache is not None and stamp == self._patterns_stamp:
            return self._patterns_cache
        merged = json.loads(json.dumps(built))   # 深拷贝，防外挂污染内置
        try:
            with open(path, "r", encoding="utf-8") as f:
                extra = json.load(f)
            if isinstance(extra, dict):
                # preference / topic 是 (正则, 标签) 二元组
                for key in ("preference", "topic"):
                    items = extra.get(key)
                    if isinstance(items, list):
                        for it in items:
                            if isinstance(it, (list, tuple)) and len(it) >= 2 \
                                    and isinstance(it[0], str) and isinstance(it[1], str):
                                merged[key].append((it[0], it[1]))
                # completion 是**纯字符串列表**（无正则、无标签），单独处理；
                # 同时容忍写成 ["词"] 的嵌套形式（取首元素）
                for it in extra.get("completion") or []:
                    if isinstance(it, str):
                        merged["completion"].append(it)
                    elif isinstance(it, (list, tuple)) and it and isinstance(it[0], str):
                        merged["completion"].append(it[0])
                emo = extra.get("emotion_keywords")
                if isinstance(emo, dict):
                    for name, words in emo.items():
                        if isinstance(name, str) and isinstance(words, list):
                            slot = merged["emotion_keywords"].setdefault(name, [])
                            slot.extend(w for w in words if isinstance(w, str))
        except (json.JSONDecodeError, IOError, OSError):
            pass   # 坏文件 = 没有外挂，回落内置（R-K 绝不因词表炸掉提取链）
        self._patterns_cache = merged
        self._patterns_stamp = stamp
        return merged

    def _load(self) -> dict:
        """读盘：主档不可解析时走「快照 -> 隔离坏档 -> 默认」阶梯，绝不静默丢数据。

        v2.4(P0-1): 原实现遇 `json.JSONDecodeError` 直接 pass、随即用默认结构
        **覆盖写盘** —— 这是本模块唯一会静默销毁用户记忆的路径（无备份、无日志）。
        GUI 改为每轮对话都落盘后该风险被放大，故对齐 `gui/tavern/store.py` 的既有
        L5/L6 约定：解析失败先尝试最新快照，仍失败则把坏档**改名保留**再回落默认。
        """
        with self._lock:
            if os.path.exists(self.filepath):
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # 补全缺失字段
                    return self._merge_defaults(data)
                except (json.JSONDecodeError, IOError):
                    recovered = self._load_latest_backup()
                    if recovered is not None:
                        return recovered
                    self._quarantine_corrupt()
            # 首次使用，创建默认结构
            default = self._merge_defaults({})
            default["meta"]["created_at"] = datetime.now().isoformat()
            self._data = default
            self._save()
            return default

    # -- v2.4(P0-1): 落盘安全网（对齐 gui/tavern/store.py L5/L6 既有约定）--

    def _backup_path(self, index: int) -> str:
        return f"{self.filepath}{_BACKUP_SUFFIX}.{index}"

    def _load_latest_backup(self) -> Optional[dict]:
        """L5：取第一份可解析快照并做读时迁移；无可用快照返回 None。"""
        for index in range(1, _MEMORY_BACKUPS + 1):
            bak = self._backup_path(index)
            if not os.path.exists(bak):
                continue
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return self._merge_defaults(json.load(f))
            except (json.JSONDecodeError, IOError):
                continue
        return None

    def _quarantine_corrupt(self) -> None:
        """L6：损坏主档改名保留为 `*.corrupt[.n]`，**绝不静默删除**。

        命名不加时间戳（保证确定性单测不受墙钟影响），同名占用时追加序号 ——
        与 `gui/tavern/store.py::_quarantine_corrupt` 同款。
        """
        target = f"{self.filepath}{_CORRUPT_SUFFIX}"
        n = 1
        while os.path.exists(target):
            target = f"{self.filepath}{_CORRUPT_SUFFIX}.{n}"
            n += 1
        try:
            os.replace(self.filepath, target)
        except OSError:
            pass   # 隔离失败也要能返回默认结构（不阻断 load）

    def _rotate_backup(self) -> None:
        """写前快照：当前档**复制**为 `.bak.1`。

        用复制而非移动 —— 移动会让「写失败」时原档消失，违背「写失败原档不被
        破坏」。轮转本身失败不阻断写入（best-effort，同 tavern store 口径）。
        """
        try:
            if os.path.exists(self.filepath):
                shutil.copy2(self.filepath, self._backup_path(1))
        except OSError:
            pass

    def _merge_defaults(self, data: dict) -> dict:
        """将现有数据与默认结构合并，确保字段完整（深层合并一层嵌套 dict）。

        v1.6(D-V16-01): 合并后做**读时迁移**（幂等，逐条 try 守卫）——
        旧格式偏好 str 包装为 {value, source: legacy, ...}；话题条目补
        source/followup 三字段/pinned；emotions 超限裁剪。脏数据降级为
        legacy 字符串，绝不抛错（_load 外层 try/except 兜底仍在）。
        """
        result = json.loads(json.dumps(_DEFAULT_MEMORY))
        for key in result:
            if key in data:
                if isinstance(result[key], dict) and isinstance(data[key], dict):
                    # 深层合并：遍历子键，不覆盖未提供的子键
                    for sub_key in result[key]:
                        if sub_key in data[key]:
                            result[key][sub_key] = data[key][sub_key]
                    # v1.6 修复：保留 default 未登记的数据子键（并集合并）——
                    # 旧实现只遍历 default 的子键，默认值为空 dict 的键
                    # （如 preferences）会把存量数据整段丢掉（隐性数据丢失，
                    # 读时迁移的前置条件：旧偏好必须先读得进来）
                    for sub_key, sub_val in data[key].items():
                        if sub_key not in result[key]:
                            result[key][sub_key] = sub_val
                else:
                    result[key] = data[key]

        # ---- v1.6 读时迁移（共享知识 18：不写升级脚本、不升 meta.version）----
        meta = result.get("meta") or {}
        fallback_ts = str(meta.get("updated_at") or meta.get("created_at") or "")
        prefs = result.get("preferences")
        if isinstance(prefs, dict):
            migrated = {}
            for k, v in prefs.items():
                try:
                    migrated[str(k)] = self._normalize_preference(v, fallback_ts)
                except Exception:
                    migrated[str(k)] = {
                        "value": "" if v is None else str(v),
                        "source": "legacy",
                        "created_at": fallback_ts,
                        "updated_at": fallback_ts,
                    }
            result["preferences"] = migrated
        topics = result.get("topics")
        if isinstance(topics, dict):
            for lst_key in ("active", "archived"):
                lst = topics.get(lst_key)
                if isinstance(lst, list):
                    topics[lst_key] = [
                        self._normalize_topic(t) if isinstance(t, dict) else t for t in lst
                    ]
        emotions = result.get("emotions")
        if isinstance(emotions, list) and len(emotions) > _EMOTIONS_HISTORY_MAX:
            del emotions[: len(emotions) - _EMOTIONS_HISTORY_MAX]
        if not isinstance(result.get("source_muted_until"), dict):
            result["source_muted_until"] = {}
        # ---- v1.8(D-V18-01) entities 读时迁移 ----
        # 旧文件无此键 -> 自动补 []（D-V16-01 同款，meta.version 不升）；
        # 存量条目逐条归一化补键（幂等）；**超限不裁剪**（人物记忆不悄悄消失）。
        entities = result.get("entities")
        if not isinstance(entities, list):
            result["entities"] = []
        else:
            result["entities"] = [
                self._normalize_entity(e) for e in entities if isinstance(e, dict)
            ]
        # ---- v1.8(D-V18-05) response_rules 读时迁移（同 entities 先例）----
        rules = result.get("response_rules")
        if not isinstance(rules, list):
            result["response_rules"] = []
        else:
            result["response_rules"] = [
                self._normalize_rule(r) for r in rules if isinstance(r, dict)
            ]
        # ---- v1.8(D-V18-08) vision_memories 读时迁移（同 entities 先例，
        #      meta.version 不升）；存量逐条归一化（R-I 消毒）+ 滚动裁剪最旧 ----
        visions = result.get("vision_memories")
        if not isinstance(visions, list):
            result["vision_memories"] = []
        else:
            result["vision_memories"] = [
                self._normalize_vision(v) for v in visions if isinstance(v, dict)
            ][-_VISION_MEMORY_MAX:]
        return result

    @staticmethod
    def _normalize_vision(raw: dict) -> dict:
        """影像记忆条目归一化（白名单字段 + R-I 消毒，幂等）。

        R-I 硬线：任何字段若携带图像数据痕迹（data URI / base64 头）一律清空，
        image_note 缺失回落中性描述——存的是「对话事实」不是「识别结果」。
        """
        def _clean(value, maxlen: int) -> str:
            s = str(value or "").strip()
            if "data:image" in s or "base64," in s:
                s = ""
            return s[:maxlen]

        mode = raw.get("source_mode")
        return {
            "id": _clean(raw.get("id"), 32) or "vis_" + uuid.uuid4().hex[:8],
            "time": _clean(raw.get("time"), 40),
            "user_text": _clean(raw.get("user_text"), _VISION_USER_TEXT_MAX),
            "assistant_digest": _clean(raw.get("assistant_digest"), _VISION_DIGEST_MAX),
            "image_note": (_clean(raw.get("image_note"), _VISION_NOTE_MAX)
                           or _VISION_NOTE_DEFAULT),
            "source_mode": mode if mode in _VISION_SOURCES else "default",
        }

    @staticmethod
    def _normalize_rule(raw: dict) -> dict:
        """回应规则条目补 v1.8 增量字段（幂等 setdefault，不动既有数据）。"""
        r = dict(raw)
        r.setdefault("id", "rule_" + uuid.uuid4().hex[:8])
        r["trigger"] = str(r.get("trigger") or "").strip()[:_RULE_TRIGGER_MAX]
        r["response"] = str(r.get("response") or "").strip()[:_RULE_RESPONSE_MAX]
        r.setdefault("enabled", True)
        r.setdefault("created_at", "")
        r.setdefault("last_hit_at", None)
        source = r.get("source")
        if source not in _RULE_SOURCES:
            r["source"] = "manual"
        return r

    @staticmethod
    def _normalize_entity(raw: dict) -> dict:
        """实体条目补 v1.8 增量字段（幂等 setdefault，不动既有数据）。"""
        e = dict(raw)
        e.setdefault("id", "ent_" + uuid.uuid4().hex[:8])
        e["name"] = str(e.get("name") or "").strip() or "未命名"
        relation = str(e.get("relation") or "").strip() or "其他"
        e["relation"] = relation
        e.setdefault("notes", "")
        events = e.get("events")
        if not isinstance(events, list):
            events = []
        else:
            events = [
                {"date": str(ev.get("date", "")), "text": str(ev.get("text", ""))}
                for ev in events if isinstance(ev, dict)
            ]
        e["events"] = events
        e.setdefault("pinned", False)
        e.setdefault("created_at", "")
        e.setdefault("updated_at", "")
        source = e.get("source")
        if source not in _ENTITY_SOURCES:
            e["source"] = "manual"
        return e

    @staticmethod
    def _normalize_preference(raw, fallback_ts: str = "") -> dict:
        """旧 str 偏好 -> 对象化结构；已是 dict 的补全缺省键（幂等）。

        旧数据 source 恒标 "legacy"（显示为「早期记忆」）——绝不用 "manual"
        伪造「你告诉我的」（D-V16-01 迁移诚实性要求）。
        """
        if isinstance(raw, dict):
            source = raw.get("source") if raw.get("source") in _PREFERENCE_SOURCES else "legacy"
            created = str(raw.get("created_at") or fallback_ts)
            return {
                "value": "" if raw.get("value") is None else str(raw.get("value")),
                "source": source,
                "created_at": created,
                "updated_at": str(raw.get("updated_at") or created or fallback_ts),
            }
        return {
            "value": "" if raw is None else str(raw),
            "source": "legacy",
            "created_at": fallback_ts,
            "updated_at": fallback_ts,
        }

    @staticmethod
    def _normalize_topic(t: dict) -> dict:
        """话题条目补 v1.6 增量字段（幂等 setdefault，不动既有数据）。"""
        source = t.get("source")
        if source not in ("auto", "manual", "legacy"):
            t["source"] = "legacy"
        t.setdefault("followup_asked_at", None)
        t.setdefault("followup_muted_until", None)
        score = t.get("followup_score", 0)
        try:
            t["followup_score"] = int(score or 0)
        except (TypeError, ValueError):
            t["followup_score"] = 0
        t.setdefault("pinned", False)
        return t

    def _save(self) -> None:
        """写盘：写前快照轮转 + 原子写（v2.4/P0-1 补快照，其余不变）。

        v2.5(D-V25-01): 全程持锁 —— 快照轮转与原子写必须串行，否则并发下
        可能出现「快照复制的是一份半写状态」。跨进程仍靠 .bak.1 兜底。
        """
        with self._lock:
            self._data["meta"]["updated_at"] = datetime.now().isoformat()
            self._rotate_backup()
            _atomic_write_json(self.filepath, self._data)

    # -- 偏好读写 --

    def get_preference(self, key: str) -> Optional[str]:
        """取偏好值。v1.6 对象化后**恒返回 str**（value 字段）——既有调用方零破坏。"""
        raw = self._data["preferences"].get(key)
        if raw is None:
            return None
        if isinstance(raw, dict):
            value = raw.get("value")
            return None if value is None else str(value)
        return str(raw)  # 防御：极端脏数据未迁移时仍按旧语义取值

    def _set_preference_nosave(self, key: str, value: str, source: str) -> None:
        """写偏好（不落盘）。保留既有 created_at；source ∈ auto/manual。"""
        if source not in ("auto", "manual"):
            source = "manual"
        now = datetime.now().isoformat()
        existing = self._data["preferences"].get(key)
        if isinstance(existing, dict):
            created = str(existing.get("created_at") or now)
        else:
            created = now
        self._data["preferences"][key] = {
            "value": str(value),
            "source": source,
            "created_at": created,
            "updated_at": now,
        }

    def set_preference(self, key: str, value: str, source: str = "manual") -> None:
        """写偏好并落盘。

        v1.6: source 语义——"auto"=对话自动提取；"manual"=用户在记忆中心页/
        /pref 命令显式告知（默认 manual 保持既有调用方语义不变）。
        """
        self._set_preference_nosave(key, value, source)
        self._save()

    def list_preferences(self) -> Dict[str, dict]:
        """v1.6: 返回结构化副本 {key: {value, source, created_at, updated_at}}。

        仅记忆中心页（page_memory_book）消费；调用方取值请用 get_preference()
        或条目的 value 字段。
        """
        out: Dict[str, dict] = {}
        for k, v in self._data["preferences"].items():
            if isinstance(v, dict):
                out[k] = dict(v)
            else:  # 防御：未迁移脏数据包装为 legacy
                out[k] = self._normalize_preference(v)
        return out

    def delete_preference(self, key: str) -> bool:
        if key in self._data["preferences"]:
            del self._data["preferences"][key]
            self._save()
            return True
        return False

    # -- 话题管理 --

    def add_topic(self, subject: str, status: str = "ongoing", source: str = "manual") -> None:
        """添加或更新活跃话题。

        v1.6: 增可选 source（"auto"=对话提取 / "manual"=用户显式添加，
        默认 manual 保持既有调用方语义）。
        """
        active = self._data["topics"]["active"]
        # 去重：如果已有相似话题，更新它
        for t in active:
            if t["subject"] == subject:
                t["last_mentioned"] = datetime.now().isoformat()
                t["status"] = status
                self._save()
                return
        entry = {
            "subject": subject,
            "last_mentioned": datetime.now().isoformat(),
            "status": status,
            "source": source if source in ("auto", "manual") else "manual",
        }
        active.append(self._normalize_topic(entry))
        self._save()

    def complete_topic(self, subject: str) -> bool:
        """将话题标记为已完成并归档。"""
        active = self._data["topics"]["active"]
        for i, t in enumerate(active):
            if t["subject"] == subject or subject in t["subject"]:
                t["status"] = "completed"
                t["completed_at"] = datetime.now().isoformat()
                self._data["topics"]["archived"].append(t)
                active.pop(i)
                self._save()
                return True
        return False

    def forget_topic(self, subject: str) -> bool:
        """手动遗忘某个话题。"""
        active = self._data["topics"]["active"]
        for i, t in enumerate(active):
            if t["subject"] == subject or subject in t["subject"]:
                t["status"] = "forgotten"
                t["forgotten_at"] = datetime.now().isoformat()
                self._data["topics"]["archived"].append(t)
                active.pop(i)
                self._save()
                return True
        return False

    def get_active_topics(self) -> List[dict]:
        return list(self._data["topics"]["active"])

    def get_archived_topics(self) -> List[dict]:
        """v1.6(P0-1): 已归档话题只读列表（记忆中心"已归档"折叠区消费）。"""
        return list(self._data["topics"]["archived"])

    def pin_topic(self, subject: str, pinned: bool = True) -> bool:
        """v1.6(P0-1): 固定/取消固定话题 —— 固定后不被 archive_stale_topics 自动归档。"""
        for t in self._data["topics"]["active"]:
            if t.get("subject") == subject:
                t["pinned"] = bool(pinned)
                self._save()
                return True
        return False

    def delete_topic_forever(self, subject: str) -> bool:
        """v1.6(P0-1/R-I): 彻底遗忘 —— active 与 archived 两列表**精确 subject 匹配**
        （不用 in 模糊匹配防误删）物理移除并落盘。返回是否有删除。"""
        removed = False
        for lst_key in ("active", "archived"):
            lst = self._data["topics"][lst_key]
            kept = [t for t in lst if t.get("subject") != subject]
            if len(kept) != len(lst):
                self._data["topics"][lst_key] = kept
                removed = True
        if removed:
            self._save()
        return removed

    def archive_stale_topics(self, days: int = 7) -> int:
        """归档超过指定天数未提及的话题。返回归档数量。

        v1.6(P0-1): pinned（用户固定）的话题跳过自动归档。
        """
        cutoff = datetime.now() - timedelta(days=days)
        active = self._data["topics"]["active"]
        archived = []
        remaining = []
        for t in active:
            if t.get("pinned"):
                remaining.append(t)
                continue
            last = t.get("last_mentioned", "")
            try:
                last_dt = datetime.fromisoformat(last) if last else datetime.now()
            except ValueError:
                last_dt = datetime.now()
            if last_dt < cutoff:
                t["status"] = "auto_archived"
                archived.append(t)
            else:
                remaining.append(t)
        self._data["topics"]["active"] = remaining
        self._data["topics"]["archived"].extend(archived)
        if archived:
            self._save()
        return len(archived)

    # -- 自动提取 --

    def extract_from_dialogue(self, user_msg: str, assistant_msg: str) -> List[str]:
        """从对话中自动提取偏好和话题。返回提取项描述列表。"""
        extracted: List[str] = []
        text = user_msg
        modified = False

        # 提取偏好（直接修改内存，不触发保存）
        # v2.5(D-V25-06): 词表走 _effective_patterns（内置 + 外挂 memory_patterns.json）
        for pattern, ptype in self._effective_patterns()["preference"]:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                if ptype == "nickname":
                    self._set_preference_nosave("nickname", value, "auto")
                    extracted.append(f"称呼偏好: {value}")
                elif ptype == "language":
                    self._set_preference_nosave("language", value, "auto")
                    extracted.append(f"编程语言偏好: {value}")
                elif ptype == "code_style":
                    self._set_preference_nosave("code_style", value, "auto")
                    extracted.append(f"代码风格偏好: {value}")
                else:
                    self._set_preference_nosave(value[:30], value[:100], "auto")
                    extracted.append(f"偏好: {value[:50]}")
                modified = True

        # 提取话题（直接修改内存，不触发保存）
        # v2.5(D-V25-06): 词表走 _effective_patterns（内置 + 外挂 memory_patterns.json）
        for pattern, status in self._effective_patterns()["topic"]:
            match = re.search(pattern, text)
            if match:
                subject = match.group(1).strip()
                # v2.4(D-V24-02): 上限由硬编码 100 收到 _TOPIC_SUBJECT_MAX(30)——
                # 话题应当短，长句必是误捕（与正则前导锚点构成双保险）。
                if 3 <= len(subject) <= _TOPIC_SUBJECT_MAX:
                    active = self._data["topics"]["active"]
                    found = False
                    for t in active:
                        if t["subject"] == subject:
                            t["last_mentioned"] = datetime.now().isoformat()
                            t["status"] = status
                            found = True
                            break
                    if not found:
                        active.append(self._normalize_topic({
                            "subject": subject,
                            "last_mentioned": datetime.now().isoformat(),
                            "status": status,
                            "source": "auto",
                        }))
                    extracted.append(f"活跃话题: {subject}")
                    modified = True

        # v2.5(D-V25-04): 话题完成检测 —— 命中完成句式**且**本轮同时提及该话题
        # 才自动归档。只说「搞定了」而不点名话题时**绝不猜测**（防误归档，R-K）。
        # 命中后走既有 complete_topic(subject)（带 completed_at + 移入 archived）。
        if any(p in text for p in self._effective_patterns()["completion"]):
            for t in list(self._data["topics"]["active"]):
                if not isinstance(t, dict):
                    continue
                subject = str(t.get("subject") or "").strip()
                if len(subject) < 2:
                    continue
                words = [w for w in re.split(r"[\s、,，/]+", subject) if len(w) >= 2]
                if subject in text or any(w in text for w in words):
                    if self.complete_topic(subject):
                        extracted.append(f"已完成话题: {subject}")
                        modified = True

        # 检测情绪并记录
        emotion = self.detect_emotion(text)
        if emotion:
            now_iso = datetime.now().isoformat()
            self._data["habits"]["last_emotion"] = emotion
            self._data["habits"]["last_emotion_time"] = now_iso
            # v1.6(D-V16-01 #4/Q-B8): 情绪历史 append（上限 200，淘汰最旧）；
            # habits.last_emotion 单条兼容读取路径（main.py 情绪检测）保持不变
            emotions = self._data.setdefault("emotions", [])
            emotions.append({
                "time": now_iso,
                "emotion": emotion,
                "excerpt": (user_msg or "")[:30],
            })
            if len(emotions) > _EMOTIONS_HISTORY_MAX:
                del emotions[: len(emotions) - _EMOTIONS_HISTORY_MAX]
            modified = True

        if modified:
            self._save()

        return extracted

    def detect_emotion(self, text: str) -> Optional[str]:
        """检测用户消息中的情绪关键词。

        v2.5(D-V25-06): 词表走 _effective_patterns —— 外挂 memory_patterns.json
        的 emotion_keywords 会**追加**到内置分类之后（新增分类也能生效）。
        """
        for emotion, keywords in self._effective_patterns()["emotion_keywords"].items():
            for kw in keywords:
                if kw in text:
                    return emotion
        return None

    def get_last_emotion(self) -> Optional[str]:
        return self._data["habits"].get("last_emotion")

    def get_emotions_history(self) -> List[dict]:
        """v1.6(P0-1): 情绪历史只读列表（时间正序，供记忆中心情绪分区渲染）。"""
        return [dict(e) for e in self._data.get("emotions", []) if isinstance(e, dict)]

    def get_last_emotion_time(self) -> Optional[str]:
        """v1.6(P0-3): 最近一次情绪记录时间（greeting 情绪延续判定用）。"""
        return self._data["habits"].get("last_emotion_time")

    # -- v1.8(D-V18-01/Q-D1): 记忆图谱实体 CRUD --
    # 约定：所有写操作立即 _save()；上限超出**拒写并抛 ValueError（友好提示）**，
    # 绝不自动淘汰；删除后由 UI 链调 session.refresh_system_context() 当轮生效。

    def list_entities(self) -> List[dict]:
        """实体只读列表（最近更新倒序，记忆中心「人物关系」分区渲染用）。"""
        entities = [dict(e) for e in self._data.get("entities", []) if isinstance(e, dict)]
        entities.sort(key=lambda e: str(e.get("updated_at") or e.get("created_at") or ""),
                      reverse=True)
        return entities

    def get_entity(self, entity_id: str) -> Optional[dict]:
        """按 id 取单条实体副本；不存在返回 None。"""
        for e in self._data.get("entities", []):
            if isinstance(e, dict) and e.get("id") == entity_id:
                return dict(e)
        return None

    def add_entity(self, name: str, relation: str = "其他", notes: str = "",
                   source: str = "manual") -> str:
        """新增实体，返回新 id。

        - 同名实体已存在 -> ValueError（引导走补充/修改，防双份注入）；
        - 实体数达 _ENTITY_MAX -> ValueError 拒写（不淘汰）；
        - source ∈ manual / assistant_proposed（D-V18-01 提议-确认确认后才写）。
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("先告诉码铃这位的名字吧。")
        entities = self._data.setdefault("entities", [])
        for e in entities:
            if isinstance(e, dict) and e.get("name") == name:
                raise ValueError(f"已经记着「{name}」啦，可以直接补充或修改。")
        if len(entities) >= _ENTITY_MAX:
            raise ValueError(
                f"记忆图谱的位置满啦（最多 {_ENTITY_MAX} 位）。"
                "可以先删掉几位不再联系的人，再试试。")
        now = datetime.now().isoformat()
        entity = self._normalize_entity({
            "id": "ent_" + uuid.uuid4().hex[:8],
            "name": name,
            "relation": (relation or "").strip() or "其他",
            "notes": str(notes or ""),
            "events": [],
            "pinned": False,
            "created_at": now,
            "updated_at": now,
            "source": source if source in _ENTITY_SOURCES else "manual",
        })
        entities.append(entity)
        self._save()
        return entity["id"]

    def update_entity(self, entity_id: str, name: Optional[str] = None,
                      relation: Optional[str] = None,
                      notes: Optional[str] = None) -> bool:
        """更新实体的名字/关系/备注（None = 不动该字段）。"""
        for e in self._data.get("entities", []):
            if not isinstance(e, dict) or e.get("id") != entity_id:
                continue
            if name is not None and name.strip():
                new_name = name.strip()
                if new_name != e.get("name"):
                    for other in self._data["entities"]:
                        if isinstance(other, dict) and other.get("id") != entity_id \
                                and other.get("name") == new_name:
                            raise ValueError(f"已经记着「{new_name}」啦，换个别名试试。")
                    e["name"] = new_name
            if relation is not None and relation.strip():
                e["relation"] = relation.strip()
            if notes is not None:
                e["notes"] = str(notes)
            e["updated_at"] = datetime.now().isoformat()
            self._save()
            return True
        return False

    def delete_entity(self, entity_id: str) -> bool:
        """删除实体（删除即遗忘——连同全部事件物理移除并落盘）。"""
        entities = self._data.get("entities", [])
        kept = [e for e in entities
                if not (isinstance(e, dict) and e.get("id") == entity_id)]
        if len(kept) != len(entities):
            self._data["entities"] = kept
            self._save()
            return True
        return False

    def pin_entity(self, entity_id: str, pinned: bool = True) -> bool:
        """固定/取消固定实体。固定实体（≤1 个生效，先到先得）走 system 级常驻注入。"""
        for e in self._data.get("entities", []):
            if not isinstance(e, dict):
                continue
            if e.get("id") == entity_id:
                e["pinned"] = bool(pinned)
                if pinned:
                    # 单 pinned 槽：固定后者则取消前者（防多实体挤占常驻预算）
                    for other in self._data["entities"]:
                        if isinstance(other, dict) and other.get("id") != entity_id \
                                and other.get("pinned"):
                            other["pinned"] = False
                e["updated_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def add_entity_event(self, entity_id: str, text: str,
                         date: Optional[str] = None) -> bool:
        """为实体追加一件共同经历的事（按时间倒序，≤_ENTITY_EVENT_MAX 拒写）。

        date 缺省取今天（YYYY-MM-DD）；超出上限抛 ValueError（不自动淘汰）。
        """
        text = (text or "").strip()
        if not text:
            return False
        for e in self._data.get("entities", []):
            if not isinstance(e, dict) or e.get("id") != entity_id:
                continue
            events = e.setdefault("events", [])
            if len(events) >= _ENTITY_EVENT_MAX:
                raise ValueError(
                    f"「{e.get('name')}」的事记不下了（每人最多 {_ENTITY_EVENT_MAX} 件）。"
                    "可以先删掉一两件久远的，再试试。")
            event_date = (date or datetime.now().strftime("%Y-%m-%d")).strip()
            events.insert(0, {"date": event_date, "text": text})
            events.sort(key=lambda ev: str(ev.get("date", "")), reverse=True)
            e["updated_at"] = datetime.now().isoformat()
            self._save()
            return True
        return False

    def delete_entity_event(self, entity_id: str, index: int) -> bool:
        """按展示序号删除实体的一件往事（index 为 events 列表下标）。"""
        for e in self._data.get("entities", []):
            if not isinstance(e, dict) or e.get("id") != entity_id:
                continue
            events = e.get("events", [])
            if 0 <= int(index) < len(events):
                events.pop(int(index))
                e["updated_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def find_entities_by_name(self, text: str) -> List[dict]:
        """用户消息中按**精确子串**命中实体名（供注入与提议链用）。

        按最近更新倒序返回命中实体（调用方截取前 2 个作提及注入，D-V18-02）。
        """
        t = text or ""
        if not t:
            return []
        hits = [dict(e) for e in self._data.get("entities", [])
                if isinstance(e, dict) and e.get("name") and str(e["name"]) in t]
        hits.sort(key=lambda e: str(e.get("updated_at") or ""), reverse=True)
        return hits

    def find_topics_by_name(self, text: str, limit: int = 2) -> List[dict]:
        """用户消息中按**精确子串**命中话题（v2.5/D-V25-05 提及注入通道用）。

        与 find_entities_by_name 对称，但有两点不同：
          ① 含空格话题（如「学 Rust」）按 ≥2 字分词补充命中——否则用户说
             「Rust」永远唤不醒它；
          ② `active` 与 `archived` **都搜** —— 归档话题被自然唤起正是本通道存在
             的理由（通道①的静态注入位只有 top3 ongoing，归档后即失联）。

        返回按 last_mentioned 倒序的命中**副本**（调用方截取前 N 条注入）。
        """
        t = text or ""
        if not t:
            return []
        hits: List[dict] = []
        for bucket in ("active", "archived"):
            for topic in self._data["topics"].get(bucket, []):
                if not isinstance(topic, dict):
                    continue
                subject = str(topic.get("subject") or "").strip()
                if len(subject) < 2:
                    continue
                words = [w for w in re.split(r"[\s、,，/]+", subject) if len(w) >= 2]
                if subject in t or any(w in t for w in words):
                    hits.append(dict(topic))
        hits.sort(key=lambda x: str(x.get("last_mentioned") or ""), reverse=True)
        return hits[:limit] if limit and limit > 0 else hits

    def _pinned_entity_segment(self) -> str:
        """system 级 pinned 实体段（D-V18-02 通道①；无 pinned 返回空串）。

        格式示例：「【关于小李】同事；备注：同组后端；最近：上周离职了（9-03）」
        日期仅取 M-DD 周语义；多 pinned 只取最近更新的一个（单槽）。
        """
        pinned = [e for e in self._data.get("entities", [])
                  if isinstance(e, dict) and e.get("pinned")]
        if not pinned:
            return ""
        pinned.sort(key=lambda e: str(e.get("updated_at") or ""), reverse=True)
        e = pinned[0]
        seg = f"【关于{e.get('name')}】{e.get('relation', '其他')}"
        notes = str(e.get("notes") or "").strip()
        if notes:
            seg += f"；备注：{notes}"
        events = e.get("events") or []
        if events:
            ev = events[0]
            ev_date = str(ev.get("date", ""))
            md = ""
            try:
                d = datetime.strptime(ev_date, "%Y-%m-%d")
                md = f"（{d.month}-{d.day:02d}）"
            except (TypeError, ValueError):
                md = ""
            ev_text = str(ev.get("text", "")).strip()
            if ev_text:
                seg += f"；最近：{ev_text}{md}"
        return seg

    def emotion_overview(self, days: int = 7) -> str:
        """v1.8(D-V18-03): 近 N 天情绪档位概览（纯规则模板，零数字零 LLM，≤80 字符）。

        只输出档位词句，不输出分数/计数/百分比（R-A 本期主战场）；无记录时
        给出平稳句，绝不臆造。confide 态/显式疑问句式命中时由 chat_service
        经 request_injections 注入（⚠-3 校正：无 emotion 态，锚定 confide）。
        """
        try:
            days = max(1, int(days))
        except (TypeError, ValueError):
            days = 7
        cutoff = datetime.now() - timedelta(days=days)
        counts: Dict[str, int] = {}
        for e in self._data.get("emotions", []):
            if not isinstance(e, dict):
                continue
            dt = parse_iso_dt(e.get("time"))
            if dt is None or dt < cutoff:
                continue
            emo = str(e.get("emotion") or "").strip()
            if emo:
                counts[emo] = counts.get(emo, 0) + 1
        period = "一周" if days <= 7 else "一个月"
        if not counts:
            return f"最近{period}风平浪静，安安静静的。"
        total = sum(counts.values())

        def _rank(item) -> int:
            emo, cnt = item
            pri = _EMOTION_OVERVIEW_PRIORITY.index(emo) if emo in _EMOTION_OVERVIEW_PRIORITY else 99
            return (cnt, -pri)

        dominant, dom_cnt = max(counts.items(), key=_rank)
        if dom_cnt * 2 >= total and dominant in _EMOTION_OVERVIEW_TEMPLATES:
            text = f"最近{period}" + _EMOTION_OVERVIEW_TEMPLATES[dominant]
        else:
            text = f"最近{period}整体平稳，有起有伏都是正常的。"
        return text[:80]

    # -- v1.8(D-V18-05/Q-D9): 回应规则 CRUD 与匹配 --
    # 约定：所有写操作立即 _save()；上限 20 条超出**拒写并抛 ValueError**；
    # 规则与偏好/mute **正交**（mute 不清规则、规则不受 mute 抑制）；
    # match 为精确子串包含（不做模糊语义，防误命中）。

    def list_rules(self) -> List[dict]:
        """规则只读列表（最近创建倒序，记忆中心「回应约定」分区渲染用）。"""
        rules = [dict(r) for r in self._data.get("response_rules", [])
                 if isinstance(r, dict)]
        rules.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return rules

    def get_rule(self, rule_id: str) -> Optional[dict]:
        for r in self._data.get("response_rules", []):
            if isinstance(r, dict) and r.get("id") == rule_id:
                return dict(r)
        return None

    def add_rule(self, trigger: str, response: str,
                 source: str = "manual") -> str:
        """新增回应规则，返回新 id。

        - trigger 空 / 同触发词已存在 -> ValueError（防重复注入）；
        - 上限 _RULES_MAX 拒写（友好提示，不自动淘汰）；
        - trigger/response 超长截断（录入友好，见 _RULE_*_MAX）。
        """
        trigger = (trigger or "").strip()[:_RULE_TRIGGER_MAX]
        response = (response or "").strip()[:_RULE_RESPONSE_MAX]
        if not trigger:
            raise ValueError("先写下约定的话语（例如：上线了）。")
        rules = self._data.setdefault("response_rules", [])
        for r in rules:
            if isinstance(r, dict) and r.get("trigger") == trigger:
                raise ValueError(f"已经有「{trigger}」的约定啦，可以直接修改它。")
        if len(rules) >= _RULES_MAX:
            raise ValueError(
                f"约定记不下了（最多 {_RULES_MAX} 条）。"
                "可以先删掉几条不再需要的，再试试。")
        rule = self._normalize_rule({
            "id": "rule_" + uuid.uuid4().hex[:8],
            "trigger": trigger,
            "response": response,
            "enabled": True,
            "created_at": datetime.now().isoformat(),
            "last_hit_at": None,
            "source": source if source in _RULE_SOURCES else "manual",
        })
        rules.append(rule)
        self._save()
        return rule["id"]

    def update_rule(self, rule_id: str, trigger: Optional[str] = None,
                    response: Optional[str] = None,
                    enabled: Optional[bool] = None) -> bool:
        """更新规则（None = 不动该字段）。"""
        for r in self._data.get("response_rules", []):
            if not isinstance(r, dict) or r.get("id") != rule_id:
                continue
            if trigger is not None:
                new_trigger = trigger.strip()[:_RULE_TRIGGER_MAX]
                if not new_trigger:
                    return False
                if new_trigger != r.get("trigger"):
                    for other in self._data["response_rules"]:
                        if isinstance(other, dict) and other.get("id") != rule_id \
                                and other.get("trigger") == new_trigger:
                            raise ValueError(f"已经有「{new_trigger}」的约定啦。")
                    r["trigger"] = new_trigger
            if response is not None:
                r["response"] = str(response).strip()[:_RULE_RESPONSE_MAX]
            if enabled is not None:
                r["enabled"] = bool(enabled)
            self._save()
            return True
        return False

    def delete_rule(self, rule_id: str) -> bool:
        """删除规则（删除即遗忘——物理移除并落盘）。"""
        rules = self._data.get("response_rules", [])
        kept = [r for r in rules
                if not (isinstance(r, dict) and r.get("id") == rule_id)]
        if len(kept) != len(rules):
            self._data["response_rules"] = kept
            self._save()
            return True
        return False

    def match_rules(self, text: str) -> List[dict]:
        """用户消息命中 enabled 规则（精确子串包含），返回 ≤3 条副本。

        命中时写 last_hit_at（"上次生效"呈现原料，R-A **不计次数**）。
        未命中零写入零成本（payload 最小化，R-I）。
        """
        t = text or ""
        if not t:
            return []
        hits: List[dict] = []
        now_iso = datetime.now().isoformat()
        for r in self._data.get("response_rules", []):
            if not isinstance(r, dict) or not r.get("enabled"):
                continue
            trigger = str(r.get("trigger") or "")
            if trigger and trigger in t:
                hits.append(dict(r))
                r["last_hit_at"] = now_iso
            if len(hits) >= _RULE_MATCH_LIMIT:
                break
        if hits:
            self._save()
        return hits

    # -- v1.8(D-V18-08/Q-D8): F7 影像记忆 CRUD 与检索 --
    # 约定：写操作立即 _save()；上限 50 条**滚动淘汰最旧**（设计如此，与
    # entities/rules 拒写不同——影像记忆是轻量对话事实，静默滚动可接受）；
    # 所有字段经 _normalize_vision 白名单消毒（R-I 硬线：绝不落图像数据）。

    def list_vision_memories(self, limit: Optional[int] = None) -> List[dict]:
        """影像记忆只读列表（时间倒序；limit=None 返回全部）。"""
        items = [dict(v) for v in self._data.get("vision_memories", [])
                 if isinstance(v, dict)]
        # v2.4(P0-0): 用 sort() 升序 + reverse() 而非 sort(reverse=True)。后者对
        # 相等元素**保持插入序**，而 datetime.now() 在 Windows 计时器分辨率下会撞
        # 时间戳（批跑实测 55 条仅 34 个不同值），撞车时"最新一条在前"失效、首条
        # 错位（test_rolling_eviction_keeps_newest_50 批跑必挂 / 单跑必过的根因）。
        # sort() 是稳定排序（相等保插入序），再整体 reverse -> 相等时间戳下后插入
        # 者在前，与"时间倒序、最新在前"语义一致。
        items.sort(key=lambda v: str(v.get("time") or ""))
        items.reverse()
        if limit is not None and limit >= 0:
            items = items[:limit]
        return items

    def add_vision_memory(self, user_text: str, assistant_digest: str = "",
                          image_note: str = "",
                          source_mode: str = "default") -> str:
        """新增一条影像记忆（带图消息发送成功钩子调用），返回新 id。

        - 只存对话事实：user_text / 回应首段摘要 / 中性 image_note，
          绝不接收图像二进制 / data URI（入参即文本，R-I 硬线）；
        - 超过 _VISION_MEMORY_MAX(50) 条滚动淘汰最旧；
        - 字段超长截断（_VISION_*_MAX）。
        """
        entry = self._normalize_vision({
            "id": "vis_" + uuid.uuid4().hex[:8],
            "time": datetime.now().isoformat(),
            "user_text": user_text,
            "assistant_digest": assistant_digest,
            "image_note": image_note or _VISION_NOTE_DEFAULT,
            "source_mode": source_mode,
        })
        visions = self._data.setdefault("vision_memories", [])
        visions.append(entry)
        if len(visions) > _VISION_MEMORY_MAX:
            self._data["vision_memories"] = visions[-_VISION_MEMORY_MAX:]
        self._save()
        return entry["id"]

    def delete_vision_memory(self, vision_id: str) -> bool:
        """删除影像记忆（删除即遗忘——物理移除并落盘）。"""
        visions = self._data.get("vision_memories", [])
        kept = [v for v in visions
                if not (isinstance(v, dict) and v.get("id") == vision_id)]
        if len(kept) != len(visions):
            self._data["vision_memories"] = kept
            self._save()
            return True
        return False

    def query_vision_memories(self, keyword: str = "",
                              limit: int = 2) -> List[dict]:
        """召回检索：关键词重叠（整词 > 2-gram）优先，零命中回落时间倒序 top N。

        设计口径（D-V18-08）：「关键词重叠 + 时间倒序 top2」。指代句式召回时
        keyword 传用户原话；回落的「最近 top2」仍是真实存过的对话事实，不编造。
        """
        items = self.list_vision_memories()
        k = (keyword or "").strip()
        if not k:
            return items[:limit] if limit and limit > 0 else items

        def _score(e: dict) -> int:
            hay = " ".join([str(e.get("user_text") or ""),
                            str(e.get("assistant_digest") or ""),
                            str(e.get("image_note") or "")])
            if k in hay:
                return len(k) * 2          # 整词命中权重最高
            grams = {k[i:i + 2] for i in range(len(k) - 1)} if len(k) >= 2 else {k}
            return sum(1 for g in grams if g and g in hay)

        scored = [(_score(e), e) for e in items]
        hits = [e for s, e in scored if s > 0]
        if hits:
            hits.sort(key=lambda e: -_score(e))   # 重叠分优先（并列保持时间倒序）
            return hits[:limit] if limit and limit > 0 else hits
        # v2.5(D-V25-03): 原为 `items[:limit] if ... else items[:limit]`（两分支等价
        # 的死代码，else 分支写错）。修正为「无 limit 时返回全部候选」。
        return items[:limit] if limit and limit > 0 else items

    # -- 记忆上下文生成 --

    def build_memory_context(self, max_chars: int = 300) -> str:
        """生成注入系统提示词的记忆上下文段落。

        v1.6(D-V16-03 微调，接口签名不变)：活跃话题改为按 last_mentioned
        **降序**取 3 个、仅 status=="ongoing"（归档再活跃的话题不再占注入位）；
        偏好全量注入不变；followup_muted_until / followup_score 等策略字段
        **不注入**（只服务主动续接，防 prompt 污染）。

        v1.8(D-V18-02 通道①)：pinned 实体走本 system 级常驻段，置于段首
        （共享 300 字符预算内 pinned 优先存活）；未提及且无 pinned 时实体
        零注入（零 prompt 污染）。提及命中走 request_injections（chat_service），
        不在本段——两通道职责分开。
        """
        parts: List[str] = []
        pinned_seg = self._pinned_entity_segment()
        if pinned_seg:
            parts.append(pinned_seg)
        prefs = self._data["preferences"]
        if prefs:
            pref_items = []
            for k, v in prefs.items():
                value = v.get("value") if isinstance(v, dict) else v
                pref_items.append(f"{k}={value}")
            parts.append("【主人偏好】" + "；".join(pref_items))

        active = [t for t in self._data["topics"]["active"]
                  if t.get("status") == "ongoing"]

        def _last_dt(t: dict) -> datetime:
            try:
                return datetime.fromisoformat(t.get("last_mentioned", ""))
            except (TypeError, ValueError):
                return datetime.min

        if active:
            recent = sorted(active, key=_last_dt, reverse=True)[:3]
            topics_str = "；".join([t["subject"] for t in recent])
            parts.append("【正在关心的事】" + topics_str)

        ctx = "\n".join(parts)
        if len(ctx) > max_chars:
            ctx = ctx[:max_chars - 3] + "..."
        return ctx

    @staticmethod
    def _followup_priority(topic: dict, now: datetime) -> float:
        """续接优先级评分（v2.4/D-V24-03；纯函数、无副作用、不落任何字段）。

            priority = 0.40*useful + 0.40*recency + 0.20*evidence

          useful   = min(followup_score * 0.20, 1.0)      「说到心坎」的加权信号
          recency  = 2 ** (-age_hours / 36)               真半衰期（36h 处恰为 0.5）
          evidence = manual 1.0 / legacy 0.7 / auto 0.6   来源可信度

        设计意图：v1.6 的排序键 (followup_score, idx) 是"计数字典序"——一个被
        heart 过的话题在 72h 窗内**永远**压过其他所有话题、与时间无关，且 score
        无上限会长期霸榜。多因子评分让"最近刚聊的"与"早先被夸过的"按真实轻重
        竞争（实测：3h 前提到 0.498 > 60h 前 heart 过一次 0.406）。

        时间戳缺失/非法时 recency 取 0（该条沉底，不影响其它候选）。本函数只读
        既有字段、**不新增持久化字段**：无 schema 变更、不经 _merge_defaults、
        不涉及 meta.version（共享知识 18 不适用）。
        """
        try:
            useful = min(int(topic.get("followup_score") or 0) * _FOLLOWUP_USE_PER_HEART,
                         1.0)
        except (TypeError, ValueError):
            useful = 0.0

        last = parse_iso_dt(topic.get("last_mentioned"))
        if last is None:
            recency = 0.0
        else:
            age_hours = max(0.0, (now - last).total_seconds() / 3600.0)
            # 真半衰期语义：底数取 2，recency(HALF_LIFE) == 0.5。
            # （若写成 exp(-age/τ) 那是时间常数语义，36h 处得 0.368 而非 0.5，
            # 衰减比设计意图更陡——窗边缘 0.135 vs 目标 0.25。）
            recency = 2.0 ** (-age_hours / _FOLLOWUP_HALF_LIFE_HOURS)

        source = topic.get("source")
        evidence = _FOLLOWUP_EVIDENCE.get(source if isinstance(source, str) else "", 0.6)

        return (_FOLLOWUP_W_USEFUL * useful
                + _FOLLOWUP_W_RECENCY * recency
                + _FOLLOWUP_W_EVIDENCE * evidence)

    def pick_topic_followup(self, min_hours: int = 1, max_hours: int = 72) -> Optional[dict]:
        """v1.6(D-V16-01 #6): 选出一条可续接话题，返回 {"text", "subject"} 或 None。

        增量收紧（相对 v1.5 旧逻辑纯增量）：
          ① 跳过 followup_muted_until > now 的话题（「先不提」14 天静默）；
          ② 跳过 followup_asked_at 距今 < 7 天的话题（去重，防连环续接）；
          ③ 排序改用多因子评分 _followup_priority（v2.4/D-V24-03：有用信号 +
             软时间衰减 + 来源可信度），同分保持列表原序（idx 小者优先）；
             命中后写 followup_asked_at 并落盘（记账，验收 1 依据）。
        接口更细的 pick_* 供 scheduler 透传 subject（反馈三键内容源键）。
        """
        now = datetime.now()
        best_t = None
        best_key = None
        for idx, t in enumerate(self._data["topics"]["active"]):
            muted_until = parse_iso_dt(t.get("followup_muted_until"))
            if muted_until is not None and muted_until > now:
                continue
            asked_at = parse_iso_dt(t.get("followup_asked_at"))
            if asked_at is not None and \
                    (now - asked_at).total_seconds() < _FOLLOWUP_DEDUP_DAYS * 86400:
                continue
            last_str = t.get("last_mentioned", "")
            if not last_str:
                continue
            try:
                last = datetime.fromisoformat(last_str)
            except ValueError:
                continue
            hours_ago = (now - last).total_seconds() / 3600
            if min_hours <= hours_ago <= max_hours:
                # v2.4(D-V24-03): 多因子评分降序；同分保持列表原序（idx 小者优先，
                # 与 v1.6 同向——既有 test_score_weighting 依赖此 tie-break 方向）
                key = (self._followup_priority(t, now), -idx)
                if best_key is None or key > best_key:
                    best_key = key
                    best_t = t
        if best_t is None:
            return None
        subject = best_t["subject"]
        best_t["followup_asked_at"] = now.isoformat()
        self._save()
        return {"text": f"上次主人提到的「{subject}」，现在有进展了吗？", "subject": subject}

    def build_topic_followup(self, min_hours: int = 1, max_hours: int = 72) -> Optional[str]:
        """生成话题续接问候语。如果在指定时间范围内有活跃话题，返回关心语句。

        v1.6: 委托 pick_topic_followup（muted 跳过 + 7 天去重 + score 加权），
        接口签名与返回类型不变（旧调用语义纯增量收紧）。
        """
        hit = self.pick_topic_followup(min_hours, max_hours)
        return hit["text"] if hit else None

    def record_followup_feedback(self, subject: str, feedback: str) -> bool:
        """v1.6(D-V16-01 #7/D-V16-05): 反馈三键写回（纯 memory 策略写入）。

        feedback ∈ {"heart", "mute", "chat"}：
          - heart：followup_score += 1（后续续接经加权自然更优先）；
          - mute：followup_muted_until = now + 14 天（Q-B7，_FOLLOWUP_MUTE_DAYS）；
          - chat：仅记 followup_asked_at（策略不变）。
        特殊键 "__emotion__" / "__todo__"：内容源级静默 3 天
        （_SOURCE_MUTE_DAYS，存 source_muted_until），greeting 拼装时经
        is_source_muted 跳过。
        **绝不触碰 intimacy / 交互打点**（R-A + 防自续命，调用方护栏）。
        """
        feedback = (feedback or "").strip().lower()
        now = datetime.now()
        if subject in _SOURCE_MUTE_KEYS:
            if feedback == "mute":
                self._data.setdefault("source_muted_until", {})[subject] = (
                    now + timedelta(days=_SOURCE_MUTE_DAYS)
                ).isoformat()
                self._save()
                return True
            return False
        for t in list(self._data["topics"]["active"]) + list(self._data["topics"]["archived"]):
            if t.get("subject") != subject:
                continue
            if feedback == "heart":
                t["followup_score"] = int(t.get("followup_score") or 0) + 1
            elif feedback == "mute":
                t["followup_muted_until"] = (
                    now + timedelta(days=_FOLLOWUP_MUTE_DAYS)
                ).isoformat()
            elif feedback == "chat":
                t["followup_asked_at"] = now.isoformat()
            else:
                return False
            self._save()
            return True
        return False

    def is_source_muted(self, key: str) -> bool:
        """内容源级静默判定（__emotion__ / __todo__ 3 天静默期内返回 True）。"""
        until = self._data.get("source_muted_until", {}).get(key)
        dt = parse_iso_dt(until)
        return dt is not None and dt > datetime.now()

    # -- 汇总视图 --

    def summary(self) -> str:
        """返回记忆摘要（供 /memory 命令使用）。"""
        lines = ["📔 主人记忆摘要"]
        prefs = self._data["preferences"]
        if prefs:
            lines.append("  【偏好】")
            for k, v in prefs.items():
                value = v.get("value") if isinstance(v, dict) else v
                lines.append(f"    {k}: {value}")
        else:
            lines.append("  【偏好】暂无")

        active = self._data["topics"]["active"]
        if active:
            lines.append("  【活跃话题】")
            for t in active:
                status = t.get("status", "ongoing")
                last = t.get("last_mentioned", "")[:10]
                lines.append(f"    • {t['subject']} ({status}) — 提及: {last}")
        else:
            lines.append("  【活跃话题】暂无")

        archived = self._data["topics"]["archived"]
        if archived:
            lines.append(f"  【已归档话题】{len(archived)} 个")

        return "\n".join(lines)

    # -- 序列化（用于 session save/load）--

    def to_dict(self) -> dict:
        return dict(self._data)

    def from_dict(self, data: dict) -> None:
        self._data = self._merge_defaults(data)
        self._save()
