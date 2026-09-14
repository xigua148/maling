"""贴身提醒（v1.7 F4 / D-V17-03）。

分层契约（R-D 增量，纯 stdlib 解析 + 薄 Qt 调度器）：
  - parse_when：正则规则族（离线可用），无任何时间线索 → 默认 09:00（Q-C3）
    + confidence="low"；有线索 → confidence="high"。**永不编造时间**。
  - parse_llm_when：LLM 兜底输出的严格 JSON 解析（单次、失败返回 None →
    上层走诚实文案，绝不猜时间）。
  - ReminderScheduler：60s QTimer 扫描 todos.json（D-V17-10 单源，不新增
    reminders.json）；到点 notify_maid（Windows 通知中心，Q-C4）+ 对话气泡；
    quiet 时段降级顺延（气泡补看、不弹通知）；启动补送恰一次。
  - 存储：TodoManager 条目可选字段 due_at/remind_text/notified/quiet_pending，
    旧条目零迁移。

红线：R-A（无打卡/倒数语义——提醒是"到点说一声"，非任务系统）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量与词表
# ---------------------------------------------------------------------------
_DEFAULT_REMIND_TIME = "09:00"  # Q-C3：无明确时间句的默认时刻（可调不入 UI）

# 提醒意图词（独立词表；reminders.py 内置，可经 JSON 扩展——本期不入 UI）
REMIND_INTENT_WORDS = ["提醒我", "记得提醒", "别让我忘", "叫我记得"]
# 列览意图词（"今天有什么安排/提醒" → 本地模板列今日提醒，零 LLM）
REMIND_LIST_WORDS = ["有什么安排", "有什么提醒", "今天的安排", "今天的提醒",
                     "今天有什么安排", "今天安排"]
# LLM 兜底失败诚实文案（零编造——绝不出现猜测的时间）
REMIND_FAIL_TEXT = ("码铃没听懂时间呢，主人可以直接说「明天9点提醒我xxx」这样，"
                    "码铃就能记下啦~")

_WEEKDAY_NAMES = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5,
                  "日": 6, "天": 6}
_PERIOD_OFFSETS = {"凌晨": 0, "早上": 0, "上午": 0, "中午": 0,
                   "下午": 12, "傍晚": 12, "晚上": 12, "夜里": 12, "今晚": 12}


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------
def is_remind_request(text: str) -> bool:
    """提醒意图词命中（对话录入入口用）。"""
    t = str(text or "")
    return any(w in t for w in REMIND_INTENT_WORDS)


def is_remind_list_request(text: str) -> bool:
    """列览意图命中（"今天有什么安排/提醒"）。"""
    t = str(text or "")
    return any(w in t for w in REMIND_LIST_WORDS)


def strip_remind_prefix(text: str) -> str:
    """剥离提醒前缀词，得到提醒主体（remind_text）。"""
    t = str(text or "").strip()
    # 多轮剥离：记得提醒我 / 帮我记着 / 提醒我 / 叫我 / 别让我忘了…
    patterns = [
        r"^麻烦你?帮我?记着[一下下]*[:：,，，]?",
        r"^记得?(提醒|告诉|叫)我[:：,，，]?",
        r"^(提醒|告诉|叫)我[:：,，，]?",
        r"^帮我?记着[:：,，，]?",
        r"^别让我忘(记)?(了)?[:：,，，]?",
        r"^提醒[:：,，，]?",
    ]
    changed = True
    while changed:
        changed = False
        for pat in patterns:
            new = re.sub(pat, "", t)
            if new != t:
                t = new.strip()
                changed = True
    return t.strip(" ，,。：:！!？?~")


# ---------------------------------------------------------------------------
# 规则解析器（离线可用；全部返回 dict，无线索 → 默认时刻 low）
# ---------------------------------------------------------------------------
def _apply_period(hour: int, period: str) -> int:
    """12h → 24h 换算（下午/晚上 N<12 → +12；上午 12 → 0；夜里 12 → 0）。"""
    if period in ("下午", "傍晚", "晚上", "夜里", "今晚"):
        return hour + 12 if hour < 12 else hour
    if period in ("凌晨",):
        return hour % 12
    if period == "中午":
        return 12 if hour == 12 else hour
    return hour % 12 if hour == 12 else hour  # 上午 12 点 → 0 点


def _day_target(now: datetime, base: datetime) -> datetime:
    """时刻落到具体日期；该时刻已过 → 顺延一天（提醒绝不在过去）。"""
    target = base
    if target <= now:
        target += timedelta(days=1)
    return target


def _parse_clock(text: str) -> Optional[Tuple[int, int, str]]:
    """从文本中提取第一处"钟点"表达 → (hour, minute, period)。

    支持 HH:MM / HH：MM / N点半 / N点N分 / N点；period 为紧邻前缀时段词。
    """
    m = re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里|今晚)?\s*"
                  r"(\d{1,2})\s*[：:](\d{2})", text)
    if m:
        h, mi = int(m.group(2)), int(m.group(3))
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi, m.group(1) or ""
    m = re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里|今晚)?\s*"
                  r"(\d{1,2})\s*点半", text)
    if m:
        h = int(m.group(2))
        if 1 <= h <= 12:
            return h, 30, m.group(1) or ""
    m = re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里|今晚)?\s*"
                  r"(\d{1,2})\s*点(\d{1,2})分?", text)
    if m:
        h, mi = int(m.group(2)), int(m.group(3))
        if 1 <= h <= 12 and 0 <= mi <= 59:
            return h, mi, m.group(1) or ""
    m = re.search(r"(凌晨|早上|上午|中午|下午|傍晚|晚上|夜里|今晚)?\s*"
                  r"(\d{1,2})\s*点", text)
    if m:
        h = int(m.group(2))
        if 1 <= h <= 12:
            return h, 0, m.group(1) or ""
    return None


def _parse_relative(text: str) -> Optional[Tuple[timedelta, bool]]:
    """相对时间 → (delta, has_explicit_clock)。

    分钟/小时后 = 精确时刻（has_explicit_clock=True）；N天后 = 日期确定但
    时刻取默认（has_explicit_clock=False，仍算 high——有明确时间线索）。
    """
    m = re.search(r"半\s*个?\s*小时后", text)
    if m:
        return timedelta(minutes=30), True
    m = re.search(r"(\d+)\s*个?\s*分钟(?:以后|之后|后)", text)
    if m:
        return timedelta(minutes=int(m.group(1))), True
    m = re.search(r"(\d+)\s*个?\s*(小时|钟头)(?:以后|之后|后)", text)
    if m:
        return timedelta(hours=int(m.group(1))), True
    m = re.search(r"(\d+)\s*天(?:以后|之后|后)", text)
    if m:
        return timedelta(days=int(m.group(1))), False
    return None


def _parse_weekday(text: str) -> Optional[int]:
    # "下周X"为长尾（差一周语义），规则层不命中 → 交 LLM 兜底
    m = re.search(r"(?<!下)(?:周|礼拜|星期)\s*([一二三四五六日天])", text)
    if m:
        return _WEEKDAY_NAMES.get(m.group(1))
    return None


def _parse_month_day(text: str) -> Optional[Tuple[int, int]]:
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]", text)
    if m:
        mo, dy = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= dy <= 31:
            return mo, dy
    return None


def _parse_day_offset_word(text: str) -> Optional[int]:
    """今天=0 / 明天=1 / 后天=2（"大后天"长尾交 LLM 兜底）。"""
    if re.search(r"(今|本)天|今晚(?!.*(点|:))", text):
        return 0
    if "明天" in text or "明日" in text:
        return 1
    if "后天" in text:
        return 2
    return None


def parse_when(text: str, now: Optional[datetime] = None) -> dict:
    """规则解析提醒时间（D-V17-03 六类 + Q-C3 默认）。

    返回 ``{"due_at": ISO, "remind_text": str, "confidence": "high"|"low"}``。
    无任何时间线索 → due_at=默认时刻（Q-C3）+ confidence="low"（上层走
    LLM 兜底；LLM 也不可用时按明示默认值登记，非编造）。
    """
    now = now or datetime.now()
    remind_text = strip_remind_prefix(text)
    default_dt = now.replace(hour=int(_DEFAULT_REMIND_TIME[:2]),
                             minute=int(_DEFAULT_REMIND_TIME[3:]),
                             second=0, microsecond=0)

    def _iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M")

    # ① 相对时间（N分钟后 / N小时后 / 半小时后 / N天后）
    rel = _parse_relative(text)
    if rel is not None:
        delta, has_clock = rel
        if has_clock:
            return {"due_at": _iso(now + delta), "remind_text": remind_text,
                    "confidence": "high"}
        due = (now + delta).replace(hour=default_dt.hour,
                                    minute=default_dt.minute, second=0,
                                    microsecond=0)
        if due <= now:  # N天后默认时刻已过（N=0 不可能）→ 顺延一天
            due += timedelta(days=1)
        return {"due_at": _iso(due), "remind_text": remind_text,
                "confidence": "high"}

    clock = _parse_clock(text)
    clock_dt: Optional[datetime] = None
    if clock is not None:
        h = _apply_period(clock[0], clock[2])
        mi = clock[1]
        if 0 <= h <= 23:
            clock_dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)

    day_dt: Optional[datetime] = None
    # ② 绝对日期：N月N日（已过 → 明年）
    md = _parse_month_day(text)
    if md is not None:
        try:
            day_dt = now.replace(year=now.year, month=md[0], day=md[1])
        except ValueError:
            day_dt = None
        if day_dt is not None and day_dt.date() < now.date():
            try:
                day_dt = day_dt.replace(year=now.year + 1)
            except ValueError:
                day_dt = None
    # ③ 周X（未来最近一个，含今天；时刻已过 → 下周同日）
    if day_dt is None:
        wd = _parse_weekday(text)
        if wd is not None:
            delta_days = (wd - now.weekday()) % 7
            day_dt = (now + timedelta(days=delta_days)).replace(
                hour=0, minute=0, second=0, microsecond=0)
    # ④ 今天/明天/后天
    if day_dt is None:
        off = _parse_day_offset_word(text)
        if off is not None:
            day_dt = (now + timedelta(days=off)).replace(
                hour=0, minute=0, second=0, microsecond=0)

    # 日期 + 时刻组合（或仅其一）
    if day_dt is not None and clock_dt is not None:
        due = day_dt.replace(hour=clock_dt.hour, minute=clock_dt.minute)
        if due <= now:  # 周X/时刻组合已过 → 顺延（周X +7 天；日期词 +1 天）
            due += timedelta(days=7 if _parse_weekday(text) is not None else 1)
        return {"due_at": _iso(due), "remind_text": remind_text,
                "confidence": "high"}
    if day_dt is not None:
        due = day_dt.replace(hour=default_dt.hour, minute=default_dt.minute)
        if due <= now:
            due += timedelta(days=1)
        return {"due_at": _iso(due), "remind_text": remind_text,
                "confidence": "high"}
    if clock_dt is not None:
        return {"due_at": _iso(_day_target(now, clock_dt)),
                "remind_text": remind_text, "confidence": "high"}

    # ⑤ 无任何时间线索 → 默认时刻（Q-C3）+ low
    return {"due_at": _iso(_day_target(now, default_dt)),
            "remind_text": remind_text, "confidence": "low"}


def parse_llm_when(raw: str, now: Optional[datetime] = None) -> Optional[dict]:
    """LLM 兜底输出的严格解析（D-V17-03 零编造口径）。

    只接受 ``{"datetime": "YYYY-MM-DD HH:MM", "text": "..."}`` 形态；
    JSON 不合法 / 时间格式不合法 / 时间在过去超过容忍窗 → None（上层诚实
    回复，零 due_at 写入）。容忍 now 之前 60 秒内的时刻（LLM 秒级截断）。
    """
    now = now or datetime.now()
    try:
        data = json.loads(str(raw or ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    dt_raw = str(data.get("datetime", "")).strip()
    text = str(data.get("text", "")).strip()
    try:
        due = datetime.strptime(dt_raw, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None
    if due < now - timedelta(seconds=60):
        return None
    if not text:
        text = "（主人没说提醒的内容）"
    return {"due_at": due.strftime("%Y-%m-%dT%H:%M"), "remind_text": text}


# ---------------------------------------------------------------------------
# 文案模板（本地直出，零 LLM 零幻觉）
# ---------------------------------------------------------------------------
def format_due(due_at: str, now: Optional[datetime] = None) -> str:
    """ISO 时刻 → 人话（"今天 14:30" / "明天 09:00" / "周三 14:30" / "9月10日 14:30"）。"""
    now = now or datetime.now()
    try:
        due = datetime.strptime(str(due_at), "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return str(due_at)
    hm = f"{due.hour:02d}:{due.minute:02d}"
    days = (due.date() - now.date()).days
    if days == 0:
        return f"今天 {hm}"
    if days == 1:
        return f"明天 {hm}"
    if days == 2:
        return f"后天 {hm}"
    if 0 < days <= 7:
        names = "一二三四五六日"
        return f"周{names[due.weekday()]} {hm}"
    return f"{due.month}月{due.day}日 {hm}"


def build_confirm_text(due_at: str, remind_text: str) -> str:
    """确认句本地模板（design §2.3-3：确定性回复，零成本零幻觉）。"""
    return f"好的，{format_due(due_at)} 我会提醒你「{remind_text}」📝"


def build_due_bubble(remind_text: str) -> str:
    """到点气泡（scene="reminder"，确定性模板）。"""
    return f"主人，到点的提醒来啦：{remind_text}"


def build_overdue_bubble(remind_text: str) -> str:
    """启动补送气泡（你不在时到点的；恰一次）。"""
    return f"主人，有一条你不在时到点的提醒：{remind_text}"


def build_list_text(items: List[dict]) -> str:
    """今日提醒列览（本地模板，时间排序，零 LLM）。"""
    live = [d for d in items if str(d.get("due_at", ""))]
    if not live:
        return "今天没有记下的提醒，主人想安排什么随时说「提醒我…」就好~"
    lines = ["今天记下的提醒："]
    for d in sorted(live, key=lambda x: str(x.get("due_at", ""))):
        state = "" if not d.get("notified") else "（已提醒过）"
        lines.append(f"  ⏰ {format_due(str(d['due_at']))} 「{d.get('remind_text') or d.get('text', '')}」{state}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 调度器（薄 Qt；无 PySide6 降级为不可用）
# ---------------------------------------------------------------------------
try:  # pragma: no cover - 环境分叉
    from PySide6.QtCore import QObject, QTimer
except Exception:  # pragma: no cover
    QObject = object  # type: ignore[assignment,misc]
    QTimer = None  # type: ignore[assignment]

# quiet 判定复用 proactive_scheduler 既有工具（同一配置源，口径一致）
try:
    from gui.proactive_scheduler import is_in_quiet, DEFAULT_QUIET_START, DEFAULT_QUIET_END
except Exception:  # pragma: no cover
    def is_in_quiet(now, quiet_start, quiet_end):  # type: ignore[misc]
        return False
    DEFAULT_QUIET_START, DEFAULT_QUIET_END = "23:00", "08:00"  # type: ignore


class ReminderScheduler(QObject):
    """贴身提醒调度器：60s QTimer 扫描 todos.json 的 due 条目。

    - 到点：非 quiet → notify_maid("码铃提醒", text)（Windows 通知中心，Q-C4）
      + ChatService 确定性气泡（scene="reminder"）；quiet → 降级顺延
      （只记 quiet_pending，不弹通知，quiet 结束后首个 tick 补气泡不弹通知）；
    - 触发后 mark_notified（恰一次）；独立通道不占 A9 cap（番茄钟先例）；
    - catch_up：启动补送 due_at < now ∧ not notified 恰一次（文案带
      "你不在时到点的"）。
    """

    TICK_MS = 60 * 1000

    def __init__(self, app_ctx):
        super().__init__()
        self.app_ctx = app_ctx
        self._timer = None
        if QTimer is not None:
            self._timer = QTimer(self)
            self._timer.setInterval(self.TICK_MS)
            self._timer.timeout.connect(self._on_tick)

    # -- 生命周期 --
    def start(self) -> bool:
        if self._timer is None:
            return False
        self.catch_up()
        self._timer.start()
        return True

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    # -- 数据源 --
    def _todo_mgr(self):
        """todos.json 单源：session.todo_mgr 优先，回落按 cfg.todos_file 新建。"""
        session = getattr(self.app_ctx, "session", None)
        mgr = getattr(session, "todo_mgr", None)
        if mgr is not None:
            return mgr
        try:
            from managers import TodoManager
            cfg = getattr(self.app_ctx, "cfg", None)
            filepath = str(getattr(cfg, "todos_file", "") or "todos.json")
            return TodoManager(filepath)
        except Exception:
            return None

    def _tray(self):
        tray = getattr(self.app_ctx, "tray_manager", None)
        if tray is not None and callable(getattr(tray, "notify_maid", None)):
            return tray
        return None

    def _chat(self):
        cs = getattr(self.app_ctx, "chat_service", None)
        if cs is not None and callable(getattr(cs, "screen_bubble", None)):
            return cs
        return None

    def _is_quiet(self, now: datetime) -> bool:
        try:
            cfg = getattr(self.app_ctx, "cfg", None)
            start = str(getattr(cfg, "agent_proactive_quiet_start",
                                DEFAULT_QUIET_START))
            end = str(getattr(cfg, "agent_proactive_quiet_end",
                              DEFAULT_QUIET_END))
            return is_in_quiet(now, start, end)
        except Exception:
            return False

    # -- 交付 --
    def _deliver(self, item: dict, overdue: bool = False,
                 quiet_pending: bool = False) -> None:
        """到点交付：通知（可降级）+ 对话气泡（确定性模板）。"""
        text = str(item.get("remind_text") or item.get("text", "")).strip()
        if not text:
            return
        if overdue:
            bubble = build_overdue_bubble(text)
        else:
            bubble = build_due_bubble(text)
        chat = self._chat()
        if chat is not None:
            try:
                chat.screen_bubble(bubble, scene="reminder")
            except Exception:
                pass
        # Q-C4：quiet 顺延补看不弹通知；托盘不可用 notify_maid 内部静默跳过
        if not quiet_pending:
            tray = self._tray()
            if tray is not None:
                try:
                    tray.notify_maid("码铃提醒", bubble)
                except Exception:
                    pass

    # -- 扫描 --
    def _on_tick(self) -> None:
        self._scan(overdue=False)

    def catch_up(self) -> None:
        """启动补送：due_at < now ∧ not notified 恰一次（文案带"不在时到点的"）。"""
        self._scan(overdue=True)

    def _scan(self, overdue: bool) -> None:
        todo = self._todo_mgr()
        if todo is None:
            return
        now = datetime.now()
        quiet = self._is_quiet(now)
        try:
            due = todo.due_items(now)
        except Exception:
            return
        for idx, item in due:
            try:
                if quiet:
                    # quiet 时段：不弹不气泡，只记 pending，等 quiet 结束的 tick
                    if not item.get("quiet_pending"):
                        todo.mark_quiet_pending(idx)
                    continue
                quiet_pending = bool(item.get("quiet_pending"))
                self._deliver(item, overdue=overdue,
                              quiet_pending=quiet_pending)
                todo.mark_notified(idx)
            except Exception:
                continue
