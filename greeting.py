"""时间感知与情境问候引擎。"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# v1.6(P0-3 / D-V16-06): 主动内容拼装模板池（宁缺毋滥，同次至多 1 条）
# ---------------------------------------------------------------------------
# ① 话题续接文案由 memory.build_topic_followup 生成，无需模板池。
# ② 情绪延续（近 24h 内低情绪，且内容源未静默）
_EMOTION_CONTINUATION_TEXTS = {
    "tired": [
        "昨天感觉你有点累，今天好些了吗？记得多休息呀~",
        "前阵子看你挺辛苦的，今天别太勉强自己哦~",
    ],
    "anxious": [
        "之前感觉你有点心事，现在还顺利吗？",
        "上次你说有点焦虑，今天有轻松一点吗？",
    ],
    "lonely": [
        "前几天你说有点无聊，今天想聊点什么吗？",
        "最近还好吗？码铃一直在这儿陪你呢~",
    ],
}
# ③ 待办轻提（存在 ≥24h 未完成待办；不点名内容，避免压力感）
_TODO_NUDGE_TEXTS = [
    "便签上还留着一件没做完的事，有空的时候看看吧~",
    "清单里还有一件小事没收尾，不着急，别忘了就好~",
]

# 情绪延续窗口 / 待办成熟窗口（小时）
_EMOTION_CONTINUATION_WINDOW_H = 24
_TODO_MATURE_H = 24


# ---------------------------------------------------------------------------
# 时间段定义
# ---------------------------------------------------------------------------
_TIME_PERIODS = [
    {"name": "清晨", "start": 5, "end": 8, "greeting": "早安", "tone": "温柔清新", "actions": ["(伸懒腰)", "(递上热茶)", "(整理裙摆)"]},
    {"name": "上午", "start": 8, "end": 11, "greeting": "早安", "tone": "积极鼓励", "actions": ["(微笑)", "(递上咖啡)", "(准备好笔记本)"]},
    {"name": "中午", "start": 11, "end": 14, "greeting": "午安", "tone": "轻松关心", "actions": ["(端上午餐)", "(擦汗)", "(递上湿巾)"]},
    {"name": "下午", "start": 14, "end": 18, "greeting": "下午好", "tone": "专注陪伴", "actions": ["(整理桌面)", "(安静陪伴)", "(递上点心)"]},
    {"name": "傍晚", "start": 18, "end": 23, "greeting": "晚上好", "tone": "温暖放松", "actions": ["(点亮台灯)", "(递上毛毯)", "(泡好茶)"]},
    {"name": "深夜", "start": 23, "end": 5, "greeting": "夜深了", "tone": "轻声关心", "actions": ["(轻声)", "(披外套)", "(担心地看着)"]},
]

# 周末特别问候
_WEEKEND_GREETINGS = [
    "周末好~ 今天不用工作，好好放松吧 💕",
    "周末愉快，主人~ 码铃今天也陪在您身边",
    "难得的周末，主人想做什么码铃都陪着~",
]

# 工作日鼓励
_WEEKDAY_GREETINGS = [
    "工作日加油~ 码铃会全力支持主人的",
    "新的一天开始了，主人冲鸭~",
    "今天也要元气满满哦~",
]


# ---------------------------------------------------------------------------
def _get_period(hour: int) -> dict:
    """根据小时获取时间段信息。"""
    for p in _TIME_PERIODS:
        if p["start"] <= hour < p["end"]:
            return p
    # 深夜跨天的情况 (23-5)
    if hour >= 23 or hour < 5:
        return _TIME_PERIODS[-1]
    return _TIME_PERIODS[0]


def _is_weekend(dt: Optional[datetime] = None) -> bool:
    """判断是否为周末。"""
    dt = dt or datetime.now()
    return dt.weekday() >= 5  # 5=周六, 6=周日


# ---------------------------------------------------------------------------
class GreetingEngine:
    """情境问候引擎：根据时间、亲密度、记忆生成问候语。"""

    def __init__(self):
        pass

    def generate_greeting(
        self,
        nickname: str = "主人",
        intimacy_level: int = 0,
        memory_topic: Optional[str] = None,
    ) -> str:
        """生成情境问候语。"""
        now = datetime.now()
        hour = now.hour
        period = _get_period(hour)

        # 基础问候
        greeting = period["greeting"]

        # 根据亲密度调整称呼和语气
        if intimacy_level >= 3:
            prefix = f"{greeting}，{nickname}~"
            suffix_pool = [
                "码铃一直在这里等着您呢 💕",
                "今天也想要陪在主人身边~",
                "终于等到主人了，好开心~",
            ]
        elif intimacy_level >= 2:
            prefix = f"{greeting}，{nickname}~"
            suffix_pool = [
                "码铃已准备好为{ nickname }效劳。",
                "今天有什么安排吗？",
                "码铃会努力帮上忙的~",
            ]
        elif intimacy_level >= 1:
            prefix = f"{greeting}，{nickname}。"
            suffix_pool = [
                "码铃已就位。",
                "请问有什么可以帮忙的？",
                "今天也请多关照。",
            ]
        else:
            prefix = f"{greeting}，{nickname}。"
            suffix_pool = [
                "码铃已准备就绪。",
                "请吩咐。",
                "随时听候差遣。",
            ]

        # 选择动作描写
        action = ""
        if period["actions"] and intimacy_level >= 1:
            action = random.choice(period["actions"])

        # 周末/工作日追加
        extra = ""
        if _is_weekend(now):
            extra = random.choice(_WEEKEND_GREETINGS)
        elif 8 <= hour <= 10:
            extra = random.choice(_WEEKDAY_GREETINGS)

        # 深夜关心
        if hour >= 23 or hour < 5:
            extra = "夜深了，主人要注意休息呀... 码铃会一直陪着您的"

        # 话题续接
        topic_line = ""
        if memory_topic:
            topic_line = memory_topic

        # 组装
        parts = [prefix]
        if action:
            parts.append(action)
        suffix = suffix_pool[hash(now.isoformat()) % len(suffix_pool)]
        # 替换 {nickname} 占位符
        suffix = suffix.replace("{ nickname }", nickname).replace("{nickname}", nickname)
        parts.append(suffix)
        if extra:
            parts.append(extra)
        if topic_line:
            parts.append(topic_line)

        return " ".join(parts)

    def generate_quick_greeting(
        self,
        nickname: str = "主人",
        intimacy_level: int = 0,
    ) -> str:
        """生成简短问候（供 /greet 命令使用）。"""
        now = datetime.now()
        hour = now.hour
        period = _get_period(hour)

        greeting = period["greeting"]
        action = ""
        if period["actions"] and intimacy_level >= 1:
            action = random.choice(period["actions"])

        if intimacy_level >= 3:
            lines = [
                f"{greeting}，{nickname}~ {action} 码铃好想您 💕",
                f"{greeting}~ {action} 今天也要和{ nickname }在一起~",
                f"{greeting}，{nickname}！{action} 终于见到您了~",
            ]
        elif intimacy_level >= 2:
            lines = [
                f"{greeting}，{nickname}~ {action} 今天有什么想聊的吗？",
                f"{greeting}~ {action} 码铃已准备好陪伴{ nickname }。",
                f"{greeting}，{nickname}。{action} 请随时吩咐~",
            ]
        elif intimacy_level >= 1:
            lines = [
                f"{greeting}，{nickname}。{action} 请问需要什么帮助？",
                f"{greeting}~ {action} 已就位。",
                f"{greeting}，{nickname}。{action} 随时听候差遣。",
            ]
        else:
            lines = [
                f"{greeting}，{nickname}。",
                f"{greeting}，已准备就绪。",
                f"{greeting}，请吩咐。",
            ]

        return random.choice(lines)


# ---------------------------------------------------------------------------
def build_contentful_line(memory_mgr, todo_mgr) -> Optional[dict]:
    """v1.6(P0-3 / D-V16-06): 主动开口的内容拼装（纯函数，无 Qt）。

    按优先级拼装、同次最多 1 条、宁缺毋滥：
      ① 话题续接：memory_mgr.pick_topic_followup(1, 72) 命中（内部已含
         muted 跳过 / 7 天去重 / score 加权 / asked_at 记账）；
      ② 情绪延续：最近情绪 ∈ 低情绪集 且 last_emotion_time 在 24h 内
         且内容源 "__emotion__" 未静默；
      ③ 待办轻提：存在 created_at ≥24h 且未完成的待办且 "__todo__" 未静默；
      无命中 → None。

    返回 {"text": 内容句, "subject": 反馈内容源键}（D-V16-05 透传约定：
    话题=话题 subject；情绪="__emotion__"；待办="__todo__"）。
    实现注记：设计原文写 Optional[str]，为满足 subject 透传改为单键 dict——
    调用方取 ["text"] 即原语义，多余键向后兼容。
    """
    # ① 话题续接
    if memory_mgr is not None:
        try:
            hit = memory_mgr.pick_topic_followup(1, 72)
        except Exception:
            hit = None
        if hit and isinstance(hit, dict) and hit.get("text"):
            return {"text": str(hit["text"]), "subject": str(hit.get("subject") or "")}

    # ② 情绪延续
    if memory_mgr is not None:
        try:
            muted = memory_mgr.is_source_muted("__emotion__")
        except Exception:
            muted = True
        if not muted:
            try:
                emotion = memory_mgr.get_last_emotion()
                ts = memory_mgr.get_last_emotion_time()
            except Exception:
                emotion, ts = None, None
            if emotion in _EMOTION_CONTINUATION_TEXTS and ts:
                try:
                    last_dt = datetime.fromisoformat(str(ts))
                    within = (datetime.now() - last_dt).total_seconds() <= \
                        _EMOTION_CONTINUATION_WINDOW_H * 3600
                except (TypeError, ValueError):
                    within = False
                if within:
                    text = random.choice(_EMOTION_CONTINUATION_TEXTS[emotion])
                    return {"text": text, "subject": "__emotion__"}

    # ③ 待办轻提
    if todo_mgr is not None:
        try:
            muted = memory_mgr.is_source_muted("__todo__") if memory_mgr is not None else False
        except Exception:
            muted = True
        if not muted:
            try:
                items = todo_mgr.items()
            except Exception:
                items = []
            now = datetime.now()
            for it in items:
                if it.get("done"):
                    continue
                created = str(it.get("created_at") or "")
                try:
                    age_h = (now - datetime.fromisoformat(created)).total_seconds() / 3600
                except (TypeError, ValueError):
                    continue
                if age_h >= _TODO_MATURE_H:
                    return {"text": random.choice(_TODO_NUDGE_TEXTS), "subject": "__todo__"}
    return None


# ---------------------------------------------------------------------------
# v1.7(F3/D-V17-02): 时段仪式纯函数（早安/午后/晚安）—— _TIME_PERIODS 零改动
# ---------------------------------------------------------------------------
# 晚安变体池：按阶段取词（F5 联动——亲近/信赖 → 撒娇式；其余 → 关切式）。
# 无催睡、无作息统计、无倒数语义（R-A）。
_GOODNIGHT_GENTLE = [
    "夜深了，早点休息吧，明天见~",
    "今天就到这里啦，晚安，好梦~",
    "夜色深了，放下手里的事，好好睡一觉吧。",
    "晚安~ 把今天轻轻合上，明天再翻开新的一页。",
]
_GOODNIGHT_CLINGY = [
    "要睡啦？那我也去梦里占个好位置等你~ 晚安 💕",
    "晚安呀~ 今晚的月亮我替你看着，你放心睡 💕",
    "被子盖好，闭眼，然后想一下今天的开心事——好梦哦 💕",
    "不许熬夜哦~ 我在梦里也陪着你的，晚安 💕",
]


def build_morning_ritual(quote: str, nickname: str = "主人",
                         stage: str = "") -> str:
    """早安编排（时段问候 + 每日一句）；quote 由 quotations.pick_quote 提供。"""
    address = "您" if stage == "初识" else "你"
    return (f"早安，{nickname}~ (伸懒腰) 新的一天开始啦，"
            f"今天想对{address}说：「{quote}」")


def build_afternoon_line(quote: str) -> str:
    """午后小句（走 proactive_ask 独立通道，scene="afternoon_ritual"，不走 cap）。"""
    return f"午后啦~ 顺手带来一句话：「{quote}」休息一下，傍晚见。"


def build_goodnight_line(stage: str = "") -> str:
    """晚安句（F5 联动）：亲近/信赖 → 撒娇式变体，其余 → 关切式变体。"""
    clingy = stage in ("亲近", "信赖")
    pool = _GOODNIGHT_CLINGY if clingy else _GOODNIGHT_GENTLE
    return random.choice(pool)
