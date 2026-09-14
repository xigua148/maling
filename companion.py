"""码铃陪伴域总管 —— MoodState 心情状态机 + streak 打卡 + 每日足迹 + 成就占位。

设计来源：docs/design-v12.md D1 / D2（A1/A2/A4 底座，A7 数据已积累）。

本模块刻意保持「纯 stdlib、零第三方依赖」：
  - 不 import utils.py（其顶层会拉入 core -> requests 等 CLI 依赖），因此
    本模块自实现与 utils._atomic_write_json 完全同语义的原子写（tmp + os.replace）。
  - 不 import intimacy.py / memory.py / core —— 它们通过构造函数**鸭子类型注入**
    （intimacy 实例只被读取 .level/.score；情绪检测用一个 callable），
    保证 CLI / GUI / 自测三处都能独立 import 本模块。

数据域边界（D1 裁决）：
  - intimacy.json   = 主人亲密度（本模块**只读** intimacy.level/score，绝不写）
  - user_memory.json= 主人长期画像（本模块只经 emotion_detector 读 detect_emotion 结果）
  - companion.json  = 码铃自身心情与关系成长线（本模块唯一持久化文件）
"""

from __future__ import annotations

import json
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

_logger = logging.getLogger("maid_coder.companion")


# ---------------------------------------------------------------------------
# 常量：心情态 / 活动态 / 表情态 / 成就定义
# ---------------------------------------------------------------------------
MOOD_IDS = ["normal", "happy", "concerned", "shy", "tired"]  # 心情态（持久化，唯一真源）
ACTIVITY_STATES = ["thinking", "focus", "surprised"]          # 活动态（呈现层临时覆盖，不持久化）

# v1.2: 扩展表情 id（动作/姿态/场景类，由"内容/事件触发"机制选用，不属于 mood/activity 核心集合）。
# 用户自绘 38 张表情差分映射：基础 8 + 扩 28 = 36 id（含 2 个备用）。
# 已覆盖：捂嘴笑/眨眼/嘟嘴/委屈/招手/比心/调皮/胜利/期待/大哭/鞠躬/崩溃 + 点头/摇头/鼓掌/汗颜/叹气/得意/晚安/咖啡/打字/挥手/盘腿/樱花/雪/蛋糕/疑问/警觉
EXTENDED_EXPRESSIONS = [
    "giggle",   # 捂嘴笑
    "wink",     # 眨眼
    "pout",     # 嘟嘴
    "teary",    # 委屈
    "greet",    # 招手
    "heart",    # 比心 / 飞吻
    "cheeky",   # 调皮
    "victory",  # 胜利
    "sparkle",  # 期待
    "cry",      # 大哭
    "bow",      # 鞠躬
    "meltdown", # 崩溃
    "nod",      # 点头同意
    "shake",    # 摇头否定
    "clap",     # 鼓掌庆祝
    "sweat",    # 汗颜流汗
    "sigh",     # 叹气
    "smug",     # 得意
    "sleep",    # 闭眼晚安
    "coffee",   # 喝咖啡醒神
    "typing",   # 敲键盘打字中
    "wave",     # 挥手告别
    "sit",      # 盘腿坐陪伴
    "sakura",   # 樱花彩蛋
    "snow",     # 雪彩蛋
    "cake",     # 蛋糕彩蛋
    "question", # 疑问
    "alert",    # 警觉
]

# 19 态表情清单：5 心情态 + 3 活动态覆盖 + 12 扩展动作/姿态
EXPRESSION_IDS = MOOD_IDS + ACTIVITY_STATES + EXTENDED_EXPRESSIONS

# mood/活动态 -> 表情 id 映射。当前 5 个心情态与表情 id 同名故为恒等映射，
# 保留映射常量便于未来「表情与心情解耦」时只改一处。
MOOD_TO_EXPRESSION: Dict[str, str] = {m: m for m in EXPRESSION_IDS}

# 心情态中文标签（后端语义/reason 生成用；GUI 心情只经表情与文案表达，勿挂「当前心情」标签）
MOOD_LABELS = {
    "normal": "平静",
    "happy": "开心",
    "concerned": "担忧",
    "shy": "害羞",
    "tired": "困倦",
}

# 心情态口语短句（current_mood_context 用；正向、无数值/义务感，v1.2c 口径）
MOOD_PHRASES = {
    "normal": "安安静静地陪着主人",
    "happy": "和主人在一起真开心",
    "concerned": "有点挂念主人",
    "shy": "见到主人有点不好意思",
    "tired": "困了，但还是想陪在主人身边",
}

# 关系称谓兜底名册（委托 intimacy.level_name() 失败时按 level 回落；A5 呈现用文本称谓，无数值）
RELATION_STAGE_NAMES = {0: "初识", 1: "熟悉", 2: "亲近", 3: "信赖"}

# ---------------------------------------------------------------------------
# A3 彩蛋互动台词池（氛围语境、无数值无义务感；贴合 5 心情态）
# ---------------------------------------------------------------------------
PET_CLICK_TEXTS: Dict[str, List[str]] = {
    "normal": [
        "(轻轻拽了拽主人的衣角) 主人~ 码铃在这儿呢",
        "(晃了晃铃铛) 叮铃~ 主人找码铃呀？码铃随时都在~",
    ],
    "happy": [
        "(开心地晃起铃铛) 嘿嘿，被主人戳到啦~",
        "(眉眼弯弯) 主人一过来，码铃就跟着开心起来了~",
    ],
    "concerned": [
        "(抬头看了看主人) 主人~ 有心事的话，码铃都听着呢",
        "(轻轻蹭了蹭) 累了就歇一歇吧，码铃在这儿陪着",
    ],
    "shy": [
        "(脸微微一红，低下头) 主、主人怎么突然点码铃啦…",
        "(小声) 被主人这样看着…码铃有点不好意思…",
    ],
    "tired": [
        "(揉了揉眼睛，打起精神晃铃) 唔…被主人一叫就有精神了~",
        "(困困地) 主人~ 码铃还撑得住，您也要记得早点休息呀",
    ],
}
# 冷却期专用台词（30 分钟内再次点击：只回话、不加分）
PET_CLICK_COOL_TEXTS: Dict[str, List[str]] = {
    "normal": [
        "(乖乖站好) 码铃在呢~ 主人专心忙的话，不用管我",
        "(轻轻晃铃) 叮——主人忙你们的，码铃安静陪着",
    ],
    "happy": [
        "(笑着晃铃) 今天主人心情很好呀，码铃也跟着开心~",
        "(铃铛轻响) 嘿嘿，被主人多戳几下也没关系啦",
    ],
    "concerned": [
        "(安安静静陪着) 主人别太累，码铃就在这儿",
        "(轻轻拢了拢裙摆) 主人要不要先歇口气？",
    ],
    "shy": [
        "(脸又红了) 主人…再戳下去，码铃会害羞得站不住的…",
        "(小声嘟囔) 铃铛都要被主人戳坏啦…",
    ],
    "tired": [
        "(困困地靠着) 主人…码铃先靠一会儿，还陪着您",
        "(眯着眼晃铃) 呜…今天真的有点困了…",
    ],
}
PET_CLICK_COOLDOWN_MINUTES = 30

# v1.3(P2-1): 小游戏情绪反馈 30min 冷却 —— 与 pet_click 同口径、独立计时键
# companion.json["mini_game"]["last_at"]（非 intimacy 计分键、后台零加分）。
GAME_COOLDOWN_MINUTES = 30
GAME_RESULT_OUTCOMES = ("win", "lose", "draw")

# 荷官「台词 + 结果一句」情绪反馈池（无数值/筹码语义；输=温柔安慰不贬低）
GAME_WIN_TEXTS = [
    "(眉眼弯弯，轻轻鼓掌) 主人手气真不错，这一局赢得漂亮，码铃都跟着开心~",
    "(开心地晃起铃铛) 赢啦赢啦~ 主人今天的运气好得让码铃挪不开眼~",
    "(笑盈盈收好牌) 这局主人发挥太好啦，码铃心服口服~",
]
GAME_LOSE_TEXTS = [
    "(温柔地放下手牌) 游戏嘛，开心最重要啦。在码铃心里，主人永远是最棒的~",
    "(轻声安慰) 输赢都只是一小局，主人别放在心上，码铃一直站在您这边~",
    "(暖声) 没关系哦，就当陪码铃玩了一会儿放松放松~",
]
GAME_DRAW_TEXTS = [
    "(歪了歪头) 平局呢~ 主人和码铃默契得不相上下，真有缘分~",
    "(笑着收好牌) 打平啦，看来这局连运气都在帮我们偷懒呢~",
]
# 冷却期专用台词（30 分钟内再玩：只陪玩、不再做情绪化反馈）
GAME_COOL_TEXTS = [
    "(乖乖坐在桌边) 主人玩得开心就好，码铃安静陪着~",
    "(轻声) 码铃不多嘴啦，主人继续玩~",
]

# 时段 id：早 / 午 / 晚 / 深夜（basis.period 落盘用；规则 3 直接按 hour 判深夜）
PERIOD_IDS = ["morning", "afternoon", "evening", "night"]


def period_of_hour(hour: int) -> str:
    """把小时映射到四时段。深夜跨天：hour>=23 或 hour<5。"""
    if not isinstance(hour, int):
        hour = 0
    if 5 <= hour < 11:
        return "morning"      # 早
    if 11 <= hour < 18:
        return "afternoon"    # 午
    if 18 <= hour < 23:
        return "evening"      # 晚
    return "night"            # 深夜 23:00-4:59


# ---------------------------------------------------------------------------
# MoodState 纯规则引擎（零 LLM）
# ---------------------------------------------------------------------------
@dataclass
class MoodInput:
    """MoodEngine 输入快照。"""
    owner_emotion: Optional[str] = None   # detect_emotion 输出: None/tired/happy/anxious/lonely
    intimacy_level: int = 0               # 0..3（只读 intimacy.level）
    hour: int = 12                        # 0..23
    consecutive_days: int = 1
    minutes_since_level_up: Optional[int] = None  # 升级后分钟数（<=10 走短暂 boost）
    gratitude_recent: bool = False        # 刚检测到感谢/夸奖（事件脉冲，事件当下才置 True）


def _mood_decision(inp: MoodInput) -> tuple[str, str]:
    """规则映射表（design-v12 D2，优先级从高到低，命中即返回）。"""
    lvl = inp.intimacy_level if isinstance(inp.intimacy_level, int) else 0
    lvl = max(0, min(3, lvl))

    # P1: 升级后 10 分钟内且好感等级 >= 2 —— 升级庆祝
    if inp.minutes_since_level_up is not None and inp.minutes_since_level_up <= 10:
        if lvl >= 3:
            return "shy", "刚升级到最高信赖，有点不好意思"
        if lvl >= 2:
            return "happy", "升级庆祝，心里甜甜的"

    # P2: 主人低落 / 疲劳 —— 码铃担忧
    if inp.owner_emotion in ("tired", "anxious", "lonely"):
        return "concerned", f"主人好像{ {'tired': '很累', 'anxious': '有点焦虑', 'lonely': '有点孤单'}[inp.owner_emotion] }，想陪在身边"

    # P3: 深夜 —— 犯困（体现「她还在」）
    if inp.hour >= 23 or inp.hour < 5:
        return "tired", "夜深了，有点犯困却还陪着主人"

    # P4: 主人开心 + 刚被夸奖 —— 害羞（level>=2）/ 开心
    if inp.owner_emotion == "happy":
        if inp.gratitude_recent and lvl >= 2:
            return "shy", "被主人夸奖，害羞地低下头"
        return "happy", "主人心情很好，跟着开心起来"

    # P5: 其余 —— 默认微笑
    return "normal", "安静的陪伴"


def compute_mood(
    owner_emotion: Optional[str] = None,
    intimacy_level: int = 0,
    hour: Optional[int] = None,
    consecutive_days: int = 1,
    minutes_since_level_up: Optional[int] = None,
    gratitude_recent: bool = False,
) -> str:
    """纯函数入口：给定输入直接返回心情态 id（normal/happy/concerned/shy/tired）。

    供外部/自测便捷调用；内部走 MoodInput + _mood_decision。
    """
    if hour is None:
        hour = datetime.now().hour
    return _mood_decision(MoodInput(
        owner_emotion=owner_emotion,
        intimacy_level=intimacy_level or 0,
        hour=int(hour),
        consecutive_days=max(1, int(consecutive_days) or 1),
        minutes_since_level_up=minutes_since_level_up,
        gratitude_recent=bool(gratitude_recent),
    ))[0]


# ---------------------------------------------------------------------------
# 成就定义（A4 首批 6；风格同 intimacy.py 的 _INTIMACY_LEVELS 内联常量）
# ---------------------------------------------------------------------------
ACHIEVEMENT_DEFS = [
    {"id": "first_meeting", "name": "初次见面", "desc": "第一次打开码铃，故事开始。", "trigger": "首次 open"},
    {"id": "streak_3",      "name": "三日之约", "desc": "连续三天打开码铃。", "trigger": "连续天数>=3"},
    {"id": "intimacy_2",    "name": "渐渐亲近", "desc": "与主人达到「亲近」等级。", "trigger": "level_up 至 Lv.>=2"},
    {"id": "first_task",    "name": "初次效劳", "desc": "帮主人完成第一个任务。", "trigger": "agent_done（C 线接入）"},
    {"id": "first_heal",    "name": "暖心治愈", "desc": "在主人情绪低落时送上关心。", "trigger": "heal 事件（C/UI 线接入）"},
    {"id": "theme_switch",  "name": "焕然一新", "desc": "切换过一次主题皮肤。", "trigger": "theme 事件（UI 线接入）"},
]
ACHIEVEMENT_BY_ID = {d["id"]: d for d in ACHIEVEMENT_DEFS}

# 事件池（ingest_event 支持的类型；stable 契约，C 线 / UI 线会持续投递）
EVENT_TYPES = ("open", "chat", "level_up", "gratitude", "agent_done", "heal",
               "pet_click", "theme", "game", "anniversary",
               "pomodoro_done")  # v1.3(P2-1/P2-6): +game/anniversary；v1.4(A3): +pomodoro_done

_HISTORY_LIMIT = 50       # mood.history 上限
_EVENT_LOG_LIMIT = 200    # event_log 上限
_MILESTONE_LIMIT = 200    # milestones 上限
_PUNCH_LIMIT = 730        # 打卡记录上限（约两年）


# ---------------------------------------------------------------------------
def _companion_dir() -> str:
    d = os.path.expanduser("~/.maid_coder")
    os.makedirs(d, exist_ok=True)
    return d


def _companion_path() -> str:
    return os.path.join(_companion_dir(), "companion.json")


def _atomic_write_json(path: str, data: dict) -> None:
    """原子写 JSON（先写 .tmp 再 os.replace）——与 utils._atomic_write_json 同语义。

    不复用 utils 的原因：utils.py 顶层会拉入 core/requests（CLI 层），本模块需保持
    纯 stdlib 以便 CLI/GUI/自测都能独立 import。
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _default_data() -> dict:
    """companion.json 默认结构（schema 见 docs/design-v12.md §3.1）。"""
    now = datetime.now().isoformat()
    return {
        "schema_version": 1,
        "meta": {"created_at": now, "updated_at": now},
        "mood": {
            "current": "normal",
            "since": now,
            "basis": {
                "owner_emotion": None,
                "intimacy_level": 0,
                "period": "evening",
                "consecutive_days": 1,
                "level_up_at": None,
            },
            "history": [],
        },
        "streak": {
            "first_seen_date": "",
            "last_seen_date": "",
            "consecutive_days": 0,
            "total_days": 0,
            "punch": [],
        },
        "moments": [],
        "achievements": {"unlocked": []},
        "milestones": [],
        "event_log": [],
        # v1.2c A9（主动陪伴，P1）运行状态子块：由 A9 调度器读写；
        # 本批只定义 schema + load 兜底，不进心情/成就判定
        "proactive": {
            "last_date": "",               # 最近一次主动陪伴日期 YYYY-MM-DD（防同日多发）
            "count_today": 0,              # 今日已主动次数（按 last_date 每日清零）
            "last_at": None,               # 最近一次主动陪伴 ISO 时间
            "next_idle_eligible_at": None, # 下次空闲可发起主动陪伴的时间点
        },
        # v1.2(A3) 彩蛋互动运行状态：最近一次「加分」点击时间（30 分钟冷却语义）
        "pet_click": {
            "last_at": None,               # 最近一次冷却外加分点击的 ISO 时间
        },
        # v1.3(P2-1): 小游戏运行状态：最近一次冷却外情绪反馈时间（30min 冷却，非计分键）
        "mini_game": {
            "last_at": None,
        },
        # v1.3(P2-6): 纪念日（周年语义，MM-DD；blessed 天标防跨天重发，绝无补发）
        "anniversaries": {
            "birthday": None,              # MM-DD | None
            "first_meet": None,            # MM-DD | None
            "blessed": None,               # YYYY-MM-DD 最近一次已祝福日期
        },
    }


# ---------------------------------------------------------------------------
class MoodEngine:
    """心情引擎：对 companion 数据中 mood 分节做 recompute，变化才由上层落盘/广播。

    本类不直接落盘、不直接广播——只产出结果并维护 data["mood"]，
    落盘由 CompanionManager 统一做（单一写点）。
    """

    def __init__(self, data: dict):
        self._d = data
        self._ensure_mood_section()

    def _ensure_mood_section(self) -> None:
        if not isinstance(self._d.get("mood"), dict):
            self._d["mood"] = _default_data()["mood"]
        mood = self._d["mood"]
        mood.setdefault("current", "normal")
        mood.setdefault("since", datetime.now().isoformat())
        basis = mood.setdefault("basis", {})
        for k, v in {
            "owner_emotion": None, "intimacy_level": 0, "period": "evening",
            "consecutive_days": 1, "level_up_at": None,
        }.items():
            basis.setdefault(k, v)
        mood.setdefault("history", [])
        if mood["current"] not in MOOD_IDS:
            mood["current"] = "normal"

    # -- 查询 --
    def current(self) -> str:
        return self._d["mood"]["current"]

    def since(self) -> str:
        return self._d["mood"]["since"]

    def to_dict(self) -> dict:
        return self._d["mood"]

    # -- 计算 --
    def _minutes_since_level_up(self, now: datetime) -> Optional[int]:
        raw = self._d["mood"]["basis"].get("level_up_at")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None
        minutes = int((now - dt).total_seconds() // 60)
        return max(0, minutes)

    def recompute(self, inp: MoodInput) -> tuple[str, str, bool]:
        """按输入重算心情。返回 (mood, reason, changed)。

        changed=True 表示心情态相对上次发生变化 —— 由 CompanionManager
        负责「变化才落盘 + 广播」。
        """
        mood, reason = _mood_decision(inp)
        old = self.current()
        basis = self._d["mood"]["basis"]
        basis["owner_emotion"] = inp.owner_emotion
        basis["intimacy_level"] = inp.intimacy_level
        basis["period"] = period_of_hour(inp.hour)
        basis["consecutive_days"] = inp.consecutive_days

        if mood == old:
            return mood, reason, False

        now = datetime.now().isoformat()
        self._d["mood"]["current"] = mood
        self._d["mood"]["since"] = now
        hist = self._d["mood"].setdefault("history", [])
        hist.append({"mood": mood, "at": now, "reason": reason})
        if len(hist) > _HISTORY_LIMIT:
            del hist[:-_HISTORY_LIMIT]
        return mood, reason, True


# ---------------------------------------------------------------------------
class CompanionManager:
    """陪伴域总管：心情引擎 + streak 打卡 + 事件池 + 成就占位，读写 companion.json。

    构造参数均为鸭子类型注入：
      - intimacy:       可选，需提供 .level / .score（只读，绝不写 intimacy.json）
      - emotion_detector: 可选 callable(text) -> Optional[str]，通常传
                         memory_mgr.detect_emotion（detect_emotion 是本模块输入源）
      - listeners:      心情变化监听（纯回调，Qt 桥接由 GUI 层做）
    """

    def __init__(
        self,
        filepath: Optional[str] = None,
        intimacy: Any = None,
        emotion_detector: Optional[Callable[[str], Optional[str]]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.filepath = filepath or _companion_path()
        self._intimacy = intimacy
        self._emotion_detector = emotion_detector
        self._log = logger or _logger
        self._data = self._load()
        self.engine = MoodEngine(self._data)
        self._listeners: List[Callable[[str, str], None]] = []

    # -- 读写 --
    def _load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge_defaults(data)
            except (json.JSONDecodeError, IOError):
                self._log.warning("companion.json 损坏，重建默认结构: %s", self.filepath)
        # 首次创建：streak 留空，由首次 on_app_open() 打卡并落盘
        return _default_data()

    def _merge_defaults(self, data: dict) -> dict:
        d = _default_data()
        if not isinstance(data, dict):
            return d
        d["schema_version"] = int(data.get("schema_version", 1))
        if isinstance(data.get("meta"), dict):
            d["meta"].update(data["meta"])
        if isinstance(data.get("mood"), dict):
            d["mood"].update(data["mood"])
        if isinstance(data.get("streak"), dict):
            d["streak"].update(data["streak"])
        for key in ("moments", "event_log", "milestones"):
            if isinstance(data.get(key), list):
                d[key] = data[key]
        if isinstance(data.get("achievements"), dict):
            d["achievements"].update(data["achievements"])
        # v1.2c A9：proactive 运行状态子块；旧文件（v1.2 无此键）或半新半旧文件
        # 均以默认结构兜底合并，保证 A9 调度器读到的键永远齐全
        if isinstance(data.get("proactive"), dict):
            d["proactive"].update(data["proactive"])
        # v1.2 A3：pet_click 运行状态子块（同款兜底，兼容旧文件）
        if isinstance(data.get("pet_click"), dict):
            d["pet_click"].update(data["pet_click"])
        # v1.3(P2-1/P2-6): mini_game / anniversaries 新块兜底（旧文件无此键 -> 走默认）
        if isinstance(data.get("mini_game"), dict):
            d["mini_game"].update(data["mini_game"])
        if isinstance(data.get("anniversaries"), dict):
            d["anniversaries"].update(data["anniversaries"])
        # 畸形字段清理
        if not isinstance(d["mood"].get("history"), list):
            d["mood"]["history"] = []
        if not isinstance(d["streak"].get("punch"), list):
            d["streak"]["punch"] = []
        if not isinstance(d["achievements"].get("unlocked"), list):
            d["achievements"]["unlocked"] = []
        _p = d["proactive"]
        if not isinstance(_p.get("last_date"), str):
            _p["last_date"] = ""
        if not isinstance(_p.get("count_today"), int) or isinstance(_p.get("count_today"), bool):
            _p["count_today"] = 0
        if not isinstance(d["pet_click"].get("last_at"), (str, type(None))):
            d["pet_click"]["last_at"] = None
        # v1.3(P2-1/P2-6): 新块字段类型守卫
        if not isinstance(d["mini_game"].get("last_at"), (str, type(None))):
            d["mini_game"]["last_at"] = None
        _ann = d["anniversaries"]
        if not isinstance(_ann.get("birthday"), (str, type(None))):
            _ann["birthday"] = None
        if not isinstance(_ann.get("first_meet"), (str, type(None))):
            _ann["first_meet"] = None
        if not isinstance(_ann.get("blessed"), (str, type(None))):
            _ann["blessed"] = None
        return d

    def _save(self) -> None:
        self._data["meta"]["updated_at"] = datetime.now().isoformat()
        _atomic_write_json(self.filepath, self._data)

    # -- 查询 API --
    @property
    def mood(self) -> str:
        return self.engine.current()

    def intimacy_level(self) -> int:
        it = self._intimacy
        if it is not None:
            try:
                return int(getattr(it, "level", 0) or 0)
            except (TypeError, ValueError):
                return 0
        return 0

    def streak_info(self) -> dict:
        return dict(self._data["streak"])

    def relation_stage_name(self) -> str:
        """关系称谓（A5 呈现入口，只读、无数值）：委托 intimacy.level_name()。

        未注入 intimacy / 方法缺失时按 intimacy_level 兜底返回
        初识/熟悉/亲近/信赖；不新增 companion.json 字段、不落盘。
        """
        it = self._intimacy
        if it is not None:
            try:
                fn = getattr(it, "level_name", None)
                if callable(fn):
                    name = fn()
                    if isinstance(name, str) and name.strip():
                        return name.strip()
            except Exception as exc:
                self._log.warning("relation_stage_name 委托失败，走本地兜底: %s", exc)
        return RELATION_STAGE_NAMES.get(self.intimacy_level(), "初识")

    # -- 最近事件 -> 一句暖描述（正向措辞，无数值/义务感，v1.2c 红线） --
    _EVENT_PHRASES = {
        "level_up": "和主人的关系更亲近了一些",
        "gratitude": "主人刚夸了我，心里暖暖的",
        "agent_done": "刚刚陪主人做完了一件事",
        "heal": "陪着主人渡过了一段低落的时光",
        "pet_click": "和主人玩闹了一会儿",
        "theme": "陪主人换了个新模样",
        "chat": "刚和主人聊了几句",
        "open": "今天也见到主人啦",
        # v1.3(P2-1/P2-6)
        "game": "刚陪主人玩了一小局游戏",
        "anniversary": "今天是值得记在心里的日子",
    }

    def describe_recent_event(self) -> Optional[str]:
        """最近一条有陪伴语义的事件描述；event_log 为空返回 None。

        优先取 meaningful 事件（level_up/gratitude/agent_done/heal/pet_click/theme），
        避免高频 chat/open 反复盖住重要足迹；无 meaningful 事件时回退最近一条。
        """
        log = self._data.get("event_log") or []
        if not log:
            return None
        meaningful = ("level_up", "gratitude", "agent_done", "heal", "pet_click", "theme")
        for entry in reversed(log):
            et = entry.get("type")
            if et in meaningful:
                return self._EVENT_PHRASES.get(et)
        last = log[-1]
        return self._EVENT_PHRASES.get(last.get("type"))

    def current_mood_context(self) -> str:
        """一句短文本（心情/关系称谓/最近事件）供 A9 调度拼模板（GUI 展示用）。

        注意：这是给陪伴文案/模板用的自然语言素材，**不是注入 LLM 的上下文**；
        不含任何数值/进度/打卡字段。心情经文案表达、关系经称谓表达（v1.2c 口径）。
        """
        mood_txt = MOOD_PHRASES.get(self.mood, MOOD_LABELS.get(self.mood, "陪着主人"))
        stage = self.relation_stage_name()
        ev = self.describe_recent_event()
        if ev:
            return f"{mood_txt}。{ev}。和主人已是{stage}。"
        return f"{mood_txt}。和主人已是{stage}。"

    # -- A9 主动陪伴运行状态（v1.2c；owner = ProactiveScheduler，见 gui/proactive_scheduler.py） --
    def proactive_snapshot(self) -> dict:
        """读取 proactive 运行状态副本；按天自动归一（跨日 count_today 清零）。

        A9 频控决策的唯一持久化读数源（键见 _default_data().proactive）。
        """
        p = dict(self._data.get("proactive") or {})
        today = datetime.now().strftime("%Y-%m-%d")
        if p.get("last_date") != today:
            p["last_date"] = today
            p["count_today"] = 0
        return p

    def commit_proactive(self, *, count_delta: int = 0,
                         last_at: Optional[str] = None, **extra) -> None:
        """A9 发出一次主动后记账：今日计数 +count_delta、last_at=now、extra 透传。

        last_at 驱动 cooldown（相邻主动最小间隔）；count_today 驱动 daily_cap。
        **主动消息不更新任何「用户交互」字段** —— 防自续命（见 scheduler）。
        """
        p = self._data.setdefault("proactive", {})
        today = datetime.now().strftime("%Y-%m-%d")
        if p.get("last_date") != today:
            p["last_date"] = today
            p["count_today"] = 0
        try:
            p["count_today"] = max(0, int(p.get("count_today", 0) or 0) + int(count_delta or 0))
        except (TypeError, ValueError):
            p["count_today"] = max(0, int(count_delta or 0))
        p["last_at"] = last_at or datetime.now().isoformat()
        for k, v in extra.items():
            if v is None:
                p.pop(k, None)
            else:
                p[k] = v
        self._save()

    def to_dict(self) -> dict:
        return self._data

    def summary_dict(self) -> dict:
        """轻量快照（含数值），仅供 CLI/调试/后端文本态（P2）读取。

        v1.2c 红线：**GUI 呈现层不得用本方法渲染任何数值条/经验条/分数/天数**；
        GUI 心情走 bridge.mood_changed -> MaidAvatar.set_maid_expression，
        关系成长走 relation_stage_name() 文本称谓。
        """
        return {
            "mood": self.mood,
            "mood_label": MOOD_LABELS.get(self.mood, self.mood),
            "intimacy_level": self.intimacy_level(),
            "streak": self._data["streak"].get("consecutive_days", 0),
            "total_days": self._data["streak"].get("total_days", 0),
            "achievements": [a.get("id") for a in self._data["achievements"].get("unlocked", [])],
        }

    # -- 监听器（纯回调；GUI 桥接通过它拿 mood 变化）--
    def add_mood_listener(self, cb: Callable[[str, str], None]) -> None:
        if callable(cb) and cb not in self._listeners:
            self._listeners.append(cb)

    def remove_mood_listener(self, cb: Callable[[str, str], None]) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _notify(self, mood: str, reason: str) -> None:
        for cb in list(self._listeners):
            try:
                cb(mood, reason)
            except Exception as exc:  # 监听器异常绝不影响主流程
                self._log.warning("mood 监听器执行异常: %s", exc)

    # -- 内部辅助 --
    def _append(self, key: str, item: dict, limit: int) -> None:
        lst = self._data.setdefault(key, [])
        lst.append(item)
        if len(lst) > limit:
            del lst[:-limit]

    def _record_event(self, event_type: str, data: dict) -> None:
        self._append("event_log", {
            "type": event_type,
            "at": datetime.now().isoformat(),
            "data": data,
        }, _EVENT_LOG_LIMIT)

    @staticmethod
    def _sanitize_ctx(ctx: dict) -> dict:
        """过滤掉无法 JSON 序列化的 ctx 值，保证 event_log 永远可落盘。"""
        out: Dict[str, Any] = {}
        for k, v in ctx.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                out[k] = v
            else:
                try:
                    json.dumps(v)
                    out[k] = v
                except (TypeError, ValueError):
                    out[k] = str(v)
        return out

    def _achievement_unlocked(self, ach_id: str) -> bool:
        unlocked = self._data["achievements"].setdefault("unlocked", [])
        return any(u.get("id") == ach_id for u in unlocked)

    def _unlock_achievement(self, ach_id: str, reason: str) -> bool:
        """解锁成就并写 milestones。返回是否新解锁。"""
        if ach_id not in ACHIEVEMENT_BY_ID:
            return False
        unlocked = self._data["achievements"].setdefault("unlocked", [])
        if any(u.get("id") == ach_id for u in unlocked):
            return False
        now = datetime.now().isoformat()
        unlocked.append({"id": ach_id, "at": now})
        self._append("milestones", {"type": f"achievement:{ach_id}", "at": now, "detail": reason},
                     _MILESTONE_LIMIT)
        return True

    def _match_achievements(self, event_type: str, data: dict) -> List[str]:
        """事件驱动成就判定。当前实现最小触发集，其余待 C/UI 线事件接入。"""
        got: List[str] = []
        if event_type == "level_up" and int(data.get("level", 0) or 0) >= 2:
            if self._unlock_achievement("intimacy_2", "好感度提升至 Lv.>=2"):
                got.append("intimacy_2")
        # first_meeting / streak_3 在 on_app_open 里判定（open 事件）
        return got

    # -- 对外业务入口 --
    def on_app_open(self) -> tuple[str, Optional[dict]]:
        """应用启动打卡：连/断天判定 + 今日足迹刷新 + open 事件 + 心情重算。

        返回 (mood, moment|None)。A2 每日动态 moment 后续批次接入，本批恒 None。
        """
        today = datetime.now().strftime("%Y-%m-%d")
        streak = self._data["streak"]
        if not streak.get("first_seen_date"):
            streak["first_seen_date"] = today

        last = streak.get("last_seen_date", "")
        first_open_of_day = last != today
        if first_open_of_day:
            if last:
                try:
                    last_dt = datetime.strptime(last, "%Y-%m-%d")
                    gap = (datetime.now() - last_dt).days
                    if gap == 1:
                        streak["consecutive_days"] = streak.get("consecutive_days", 0) + 1
                    else:
                        streak["consecutive_days"] = 1
                except ValueError:
                    streak["consecutive_days"] = 1
            else:
                streak["consecutive_days"] = 1
            streak["total_days"] = streak.get("total_days", 0) + 1
            streak["last_seen_date"] = today
            punch = streak.setdefault("punch", [])
            punch.append({"date": today})
            if len(punch) > _PUNCH_LIMIT:
                del punch[:-_PUNCH_LIMIT]

            # 首次见面 / 连续三日成就（以 achievements.unlocked 判定，避免重复解锁）
            if streak["total_days"] == 1 and not self._achievement_unlocked("first_meeting"):
                self._unlock_achievement("first_meeting", "首次打开码铃")
            if streak["consecutive_days"] >= 3 and not self._achievement_unlocked("streak_3"):
                self._unlock_achievement("streak_3", "连续打开第 3 天")

            self._record_event("open", {"first_of_day": True, "total_days": streak["total_days"]})

        # 心情重算（深夜 -> tired；否则按主人情绪/时段/连续天数）
        mood, reason, changed = self.engine.recompute(MoodInput(
            owner_emotion=self._data["mood"]["basis"].get("owner_emotion"),
            intimacy_level=self.intimacy_level(),
            hour=datetime.now().hour,
            consecutive_days=max(1, streak.get("consecutive_days", 1)),
            minutes_since_level_up=self.engine._minutes_since_level_up(datetime.now()),
        ))
        if first_open_of_day or changed:
            self._save()
        if changed:
            self._notify(mood, reason)
        return mood, None

    def note_owner_text(self, text: str) -> Optional[tuple[str, str]]:
        """主人发消息钩子：经 emotion_detector 检测情绪，命中才重算心情。

        返回 (mood, reason)；无情绪命中/心情未变化返回 None。主线程调用。
        """
        detector = self._emotion_detector
        emotion = None
        if detector is not None:
            try:
                emotion = detector(text or "")
            except Exception as exc:
                self._log.warning("detect_emotion 异常: %s", exc)
        if emotion is None:
            return None
        self._record_event("chat", {"emotion": emotion})
        mood, reason, changed = self.engine.recompute(MoodInput(
            owner_emotion=emotion,
            intimacy_level=self.intimacy_level(),
            hour=datetime.now().hour,
            consecutive_days=max(1, self._data["streak"].get("consecutive_days", 1)),
            minutes_since_level_up=self.engine._minutes_since_level_up(datetime.now()),
        ))
        # 情绪命中即落盘（足迹连续性；情绪消息并非高频，写盘开销可忽略）
        self._save()
        if changed:
            self._notify(mood, reason)
        return (mood, reason) if changed else None

    def ingest_event(self, event_type: str, data: Optional[dict] = None, **ctx) -> dict:
        """事件池入口（stable 契约，C 线 / UI 线均会投递）。

        事件类型见 EVENT_TYPES；本批最小实现 level_up（升级 -> 心情 boost +
        成就 intimacy_2 + 里程碑）；其余事件一律记入 event_log 待对应批次接入。

        调用形态（两种都兼容，防 C 线踩坑）：
          ingest_event("level_up", level=2)
          ingest_event("level_up", {"level": 2})          # design-v12 的 (type, data) 风格
          ingest_event("level_up", {"level": 2}, source="gui")

        返回: {"ok": bool, "mood": str|None, "reason": str|None,
               "changed": bool, "achievements": [id...]}
        """
        if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
            return {"ok": False, "mood": None, "reason": None, "changed": False, "achievements": []}

        merged = dict(ctx)
        if isinstance(data, dict):
            merged.update(data)
        safe_ctx = self._sanitize_ctx(merged)
        self._record_event(event_type, safe_ctx)
        result: Dict[str, Any] = {"ok": True, "mood": None, "reason": None,
                                   "changed": False, "achievements": []}

        if event_type == "level_up":
            # 升级是最重要的情绪源：写 level_up_at 做 10 分钟 boost；
            # ctx 未显式带 level 时回填当前 intimacy.level（升级后调用方已更新）
            self._data["mood"]["basis"]["level_up_at"] = datetime.now().isoformat()
            safe_ctx.setdefault("level", self.intimacy_level())
            result["achievements"].extend(self._match_achievements(event_type, safe_ctx))

        mood, reason, changed = self.engine.recompute(MoodInput(
            owner_emotion=self._data["mood"]["basis"].get("owner_emotion"),
            intimacy_level=self.intimacy_level(),
            hour=datetime.now().hour,
            consecutive_days=max(1, self._data["streak"].get("consecutive_days", 1)),
            minutes_since_level_up=self.engine._minutes_since_level_up(datetime.now()),
        ))
        # 有效系统事件一律落盘（event_log 是足迹/成就判定依据，需持久化；
        # 系统事件低频，不会造成频繁写盘）
        self._save()
        if changed:
            self._notify(mood, reason)
            result.update({"mood": mood, "reason": reason, "changed": True})
        else:
            result["mood"] = mood
        return result

    # ------------------------------------------------------------------
    # A3 彩蛋互动：点她一下（30 分钟冷却 + 低频加分 + 心情匹配台词）
    # ------------------------------------------------------------------
    def react_to_pet_click(self) -> dict:
        """点击码铃形象的小反馈（PRD A3 / design §4.3）。

        语义：
          - 冷却判定：距上次「加分点击」< 30 分钟 → cooling=True，只回冷却台词、**不加分**
            （冷却内不刷新 last_at，避免狂点无限延长；到点自然恢复可加分）。
          - 冷却外：按当前心情态从台词池取一句互动台词；加分语义按 intimacy——
            调 intimacy.add_interaction("pet_click")（intimacy 计分默认 1 分；
            design 的 pet_click:1 键若未显式加入 _SCORE_RULES，默认规则同样 +1）。
            加分触发升级时，内部同步 ingest level_up（心情 boost + 成就），GUI 无需重复投递。
          - 返回结构稳定 dict {text, expression, cooling}（text 恒非空）；附加分透传
            字段 scored / level_up_message 供调用方可选消费（GUI 现有解析只取前三键，安全）。
        """
        now = datetime.now()
        mood = self.mood or "normal"
        mood_key = mood if mood in PET_CLICK_TEXTS else "normal"
        last = self._pet_click_last_at()
        cooling = last is not None and (now - last).total_seconds() < PET_CLICK_COOLDOWN_MINUTES * 60

        if cooling:
            # 冷却内：只回文案，不加分、不刷新冷却计时
            self._record_event("pet_click", {"cooling": True})
            return {
                "text": random.choice(PET_CLICK_COOL_TEXTS.get(mood_key, PET_CLICK_COOL_TEXTS["normal"])),
                "expression": mood if mood in MOOD_IDS else "normal",
                "cooling": True,
            }

        # 冷却外：按心情台词 + 愉悦脉冲表情
        text = random.choice(PET_CLICK_TEXTS.get(mood_key, PET_CLICK_TEXTS["normal"]))
        level_msg = None
        scored = False
        it = self._intimacy
        if it is not None and callable(getattr(it, "add_interaction", None)):
            try:
                level_msg = it.add_interaction("pet_click")  # intimacy 加分（默认 1 分/次）
                scored = True
            except Exception as exc:
                self._log.warning("intimacy.add_interaction(pet_click) 失败: %s", exc)

        # 只有加分点击才写 last_at，打开下一次 30 分钟冷却窗口
        self._data.setdefault("pet_click", {})["last_at"] = now.isoformat()
        self._record_event("pet_click", {"cooling": False, "scored": scored})

        if scored and level_msg:
            # 加分恰好触发升级 → 同步心情事件（P1 boost + intimacy_2 成就），含落盘/广播
            self.ingest_event("level_up", level=self.intimacy_level())
        else:
            self._save()

        return {
            "text": text,
            "expression": "happy",
            "cooling": False,
            "scored": scored,
            "level_up_message": level_msg,
        }

    def _pet_click_last_at(self) -> Optional[datetime]:
        """读取最近一次加分点击时间；数据缺失/损坏返回 None（视为可加分）。"""
        st = self._data.get("pet_click") or {}
        raw = st.get("last_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # v1.3(P2-1): 小游戏情绪反馈 —— 只做"台词+结果一句"，零计分零后台加分
    # ------------------------------------------------------------------
    def react_to_game_result(self, outcome: str) -> dict:
        """小游戏结果 -> 女仆一句情绪反馈（PRD P2-1 / design D-V13-05）。

        语义：
          - 冷却判定：距上次「冷却外情绪反馈」< 30 分钟 -> cooling=True，只回普通台词
            （冷却内不刷新计时、不做情绪化文案花活；游戏本身随时可玩）。
          - 冷却外：赢 -> happy 台词；输 -> 温柔安慰（不贬低不惩罚）；平局 -> 俏皮一句。
            短暂 happy/surprised 表情由调用方经 bridge.note_activity 呈现，本方法
            **不持久化 mood、不调 intimacy.add_interaction**（彻底去养成化，R-A/R-E）。
          - 台词带 relation_stage_name() 称谓。
          - 返回 {text, expression, cooling}（text 恒非空）；冷却外经 ingest_event("game")
            记足迹语料（非计分）。
        """
        now = datetime.now()
        outcome = outcome if outcome in GAME_RESULT_OUTCOMES else "draw"
        last = self._game_last_at()
        cooling = last is not None and (now - last).total_seconds() < GAME_COOLDOWN_MINUTES * 60
        stage = self.relation_stage_name()

        if cooling:
            self._record_event("game", {"cooling": True})
            text = random.choice(GAME_COOL_TEXTS)
            return {"text": text, "expression": "normal", "cooling": True, "stage": stage}

        if outcome == "win":
            pool, expression = GAME_WIN_TEXTS, "happy"
        elif outcome == "lose":
            pool, expression = GAME_LOSE_TEXTS, "normal"
        else:
            pool, expression = GAME_DRAW_TEXTS, "surprised"
        text = random.choice(pool)

        # 冷却外：刷新独立冷却计时键 + 事件记账（非计分；ingest_event 只记足迹/落盘）
        self._data.setdefault("mini_game", {})["last_at"] = now.isoformat()
        self.ingest_event("game", {"outcome": outcome, "cooling": False})
        return {"text": text, "expression": expression, "cooling": False, "stage": stage}

    def _game_last_at(self) -> Optional[datetime]:
        """读取最近一次小游戏情绪反馈时间；缺失/损坏返回 None（视为可反馈）。"""
        st = self._data.get("mini_game") or {}
        raw = st.get("last_at")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # v1.3(P2-6): 纪念日 —— anniversaries 块（birthday/first_meet = MM-DD）
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_mmdd(value: Any) -> Optional[str]:
        """把各种录入形态归一为 'MM-DD'；非法/空返回 None。

        兼容：'MM-DD'、'YYYY-MM-DD'（周年语义只取 MM-DD）、日期对象字符串等。
        """
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        tail = s[-5:] if len(s) > 5 else s
        try:
            dt = datetime.strptime(tail, "%m-%d")
        except (TypeError, ValueError):
            return None
        return f"{dt.month:02d}-{dt.day:02d}"

    def get_anniversaries(self) -> dict:
        """读取纪念日块副本（birthday/first_meet 可能为 None）。"""
        ann = self._data.setdefault("anniversaries", {})
        return {
            "birthday": ann.get("birthday"),
            "first_meet": ann.get("first_meet"),
            "blessed": ann.get("blessed"),
        }

    def set_anniversary(self, kind: str, value: Optional[str]) -> None:
        """设置/清除某个纪念日（kind in birthday/first_meet），存归一化 MM-DD。"""
        if kind not in ("birthday", "first_meet"):
            return
        ann = self._data.setdefault("anniversaries", {})
        normalized = self._normalize_mmdd(value)
        if normalized is None:
            ann.pop(kind, None)
        else:
            ann[kind] = normalized
        self._save()

    def anniversary_due_today(self) -> Optional[dict]:
        """今日是否有待祝福的纪念日（且 blessed != 今天）。

        返回 None = 不触发；否则 {kinds: [...], mmdd: 'MM-DD', date_label: str}。
        生日与首次相见日同日撞车 -> kinds 两枚，由调度层合并一条祝福（防双气泡）。
        绝无补发：当天已祝福（blessed==today）即返回 None。
        """
        ann = self._data.setdefault("anniversaries", {})
        today = datetime.now()
        mmdd = today.strftime("%m-%d")
        blessed = ann.get("blessed")
        if blessed == today.strftime("%Y-%m-%d"):
            return None
        kinds = [k for k in ("birthday", "first_meet") if ann.get(k) == mmdd]
        if not kinds:
            return None
        return {"kinds": kinds, "mmdd": mmdd,
                "date_label": today.strftime("%m 月 %d 日")}

    def mark_anniversary_blessed(self, detail: Optional[str] = None) -> None:
        """标记今天已祝福（blessed=today）并记一条 anniversary 事件（足迹，非计数）。"""
        ann = self._data.setdefault("anniversaries", {})
        today = datetime.now().strftime("%Y-%m-%d")
        ann["blessed"] = today
        self._record_event("anniversary", {"date": today, "detail": detail or "blessed"})
        self._save()


# ---------------------------------------------------------------------------
# Qt Signal 广播桥（单源，供首页/宠物/气泡/侧栏订阅）
#
# 说明：design-v12 中 CompanionBridge 规划为独立 gui/companion_bridge.py（任务 A-5）；
# 本批受「仅新增 companion.py / gui/maid_avatar.py」文件约束，先将桥内置本文件，
# PySide6 延迟导入、顶层零 Qt 依赖，后续可无痛抽离为 gui/companion_bridge.py。
# 桥只做「纯回调 -> Qt Signal」翻译 + 活动态覆盖广播，不碰 companion 持久化。
# ---------------------------------------------------------------------------
def _make_bridge_class():
    """动态构造 Qt 桥；无 PySide6 时降级为纯回调类（API 兼容，不 emit 真实 signal）。"""
    try:
        from PySide6.QtCore import QObject, Signal
    except Exception:  # PySide6 未安装：降级
        QObject, Signal = object, None

    if Signal is not None:
        class CompanionBridge(QObject):
            # (mood_or_state, reason) —— 与 design-v12 §6 广播约定 mood_changed(str,str) 一致
            mood_changed = Signal(str, str)

            def __init__(self, manager: Optional[CompanionManager] = None, parent=None):
                super().__init__(parent)
                self._manager = manager
                self._activity: Optional[str] = None
                self._last_mood: Optional[str] = None
                if manager is not None:
                    self._last_mood = manager.mood
                    manager.add_mood_listener(self._on_manager_mood)

            # -- 供 CompanionManager 回调 --
            def _on_manager_mood(self, mood: str, reason: str) -> None:
                self._last_mood = mood
                if self._activity is None:  # 有活动态覆盖时不打断，结束后回落最新 mood
                    self.mood_changed.emit(mood, reason)

            # -- 供呈现层（chat_service/agent 事件）调用 --
            def note_activity(self, state: Optional[str]) -> None:
                """活动态临时覆盖：state in thinking/focus/surprised；None 回落心情态。"""
                if state is not None and state not in ACTIVITY_STATES:
                    state = None
                self._activity = state
                if state is not None:
                    self.mood_changed.emit(state, "activity")
                else:
                    self.mood_changed.emit(self._last_mood or "normal", "activity_restore")

            def activity(self) -> Optional[str]:
                return self._activity

            def current_display(self) -> str:
                """当前应展示的态：活动态优先，否则心情态。"""
                return self._activity or self._last_mood or "normal"
        return CompanionBridge

    # ---- 降级类：无 PySide6，纯回调模拟（GUI 不可用但 import 不崩）----
    class _FakeSignal:
        """降级版 signal 替身：API 与 Qt Signal 对齐（connect / emit）。"""

        def __init__(self, owner: "CompanionBridge"):
            self._owner = owner

        def connect(self, fn: Callable[[str, str], None]) -> None:
            if fn not in self._owner._callbacks:
                self._owner._callbacks.append(fn)

        def emit(self, state: str, reason: str) -> None:
            self._owner._emit(state, reason)

    class CompanionBridge:
        def __init__(self, manager: Optional[CompanionManager] = None, parent=None):
            self._manager = manager
            self._activity: Optional[str] = None
            self._last_mood: Optional[str] = None
            self._callbacks: List[Callable[[str, str], None]] = []
            self.mood_changed = _FakeSignal(self)  # 与 Qt 版同名同 API
            if manager is not None:
                self._last_mood = manager.mood
                manager.add_mood_listener(self._on_manager_mood)

        def _emit(self, state: str, reason: str) -> None:
            for cb in list(self._callbacks):
                try:
                    cb(state, reason)
                except Exception:
                    pass

        def _on_manager_mood(self, mood: str, reason: str) -> None:
            self._last_mood = mood
            if self._activity is None:
                self._emit(mood, reason)

        def note_activity(self, state: Optional[str]) -> None:
            if state is not None and state not in ACTIVITY_STATES:
                state = None
            self._activity = state
            if state is not None:
                self._emit(state, "activity")
            else:
                self._emit(self._last_mood or "normal", "activity_restore")

        def activity(self) -> Optional[str]:
            return self._activity

        def current_display(self) -> str:
            return self._activity or self._last_mood or "normal"
    return CompanionBridge


CompanionBridge = _make_bridge_class()
