"""A9 有节制主动陪伴调度器 —— ProactiveScheduler（GUI 运行期唯一主动触发源）。

设计（docs/prd-v12.md §4.1 A9 / design-v12.md §3.10）：
  - 触发场景白名单（收窄为三类，优先级从高到低）：
      ① agent_revisit  Agent 任务完成且用户未回复（近 5 分钟）—— 回访
      ② low_emotion    检测到主人低情绪（近 5 分钟）—— 关心
      ③ idle_hello     长空闲（idle >= idle_minutes）—— 轻声问候
  - 节流四重闸（全部通过才允许开口）：
      enabled 总开关 > 免打扰时段(quiet) > 单日上限(daily_cap) > 冷却(cooldown)
  - 防自续命：主动消息**不算交互打点**（本模块从不调用 mark_user_activity），
    所以不会因「她刚开口」把空闲计时归零而连环开口；长空闲本轮只问候一次
    （_idle_hello_sent，用户真实交互 mark_user_activity 后复位）。
  - 记账：companion.json.proactive（last_date/count_today/last_at），见
    CompanionManager.proactive_snapshot()/commit_proactive()；配置只读
    cfg.agent_proactive_*；demo 模式不触发。
  - 呈现：唯一交付路径 = ChatService.proactive_ask(text, scene) 独立入口
    （不发用户发送队列、无 echo、不 bump_intimacy、不 mark 交互打点），
    会话落 assistant 气泡（meta.proactive），由 ChatService.proactive_message
    Signal 广播给主面板 / 独立浮窗渲染。

模块防御：PySide6 缺失时 QT_OK=False，本模块仍可 import；此时
ProactiveScheduler 为普通类（无 QTimer），手动调用 run_check() 即可
走同一判定/投递逻辑——无 Qt 开发机可用它做纯逻辑自测。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

_logger = logging.getLogger("maid_coder.gui.proactive")

# 场景判定窗口 / 低情绪集合
LOW_EMOTION_WINDOW_MIN = 5        # 低情绪关心窗口（近 5 分钟）
AGENT_DONE_WINDOW_MIN = 5         # agent 完成回访窗口（近 5 分钟）
NEGATIVE_EMOTIONS = ("tired", "anxious", "lonely")

# 免打扰兜底默认（与 core AppConfig 默认一致）
DEFAULT_QUIET_START = "22:30"
DEFAULT_QUIET_END = "08:00"


# ---------------------------------------------------------------------------
# 纯时间/规则工具（无 Qt、可自测）
# ---------------------------------------------------------------------------
def parse_hhmm(value: Any, default: str) -> str:
    """把 'HH:MM' 归一为 'HH:MM'；非法值回落 default（防御配置脏数据）。"""
    s = str(value or "").strip()
    try:
        hh, mm = s.split(":")
        if 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59:
            return f"{int(hh):02d}:{int(mm):02d}"
    except (ValueError, TypeError):
        pass
    return default


def hhmm_to_minutes(value: str) -> int:
    """'HH:MM' -> 当日分钟数（0..1439）。"""
    try:
        hh, mm = value.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, TypeError):
        return 0


def is_in_quiet(now: datetime, quiet_start: str, quiet_end: str) -> bool:
    """免打扰时段判定，支持跨天（如 22:30–08:00）；start==end 视为全天免打扰。"""
    start_m = hhmm_to_minutes(parse_hhmm(quiet_start, DEFAULT_QUIET_START))
    end_m = hhmm_to_minutes(parse_hhmm(quiet_end, DEFAULT_QUIET_END))
    cur_m = now.hour * 60 + now.minute
    if start_m == end_m:
        return True
    if start_m < end_m:            # 同一天内（如 13:00–17:00）
        return start_m <= cur_m < end_m
    return cur_m >= start_m or cur_m < end_m   # 跨天（如 22:30–08:00）


def parse_iso(value: Any) -> Optional[datetime]:
    """ISO 字符串 -> datetime；空/非法返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 配置视图（鸭子类型：任意 cfg 提供 agent_proactive_* 字段即可）
# ---------------------------------------------------------------------------
@dataclass
class ProactiveConfig:
    enabled: bool = True
    quiet_start: str = DEFAULT_QUIET_START
    quiet_end: str = DEFAULT_QUIET_END
    daily_cap: int = 3
    idle_minutes: int = 90
    cooldown_minutes: int = 60
    llm_enhance: bool = False
    # v1.3(P1-4): Idle 问候（系统全局空闲恢复）—— 与 A9 共享四重闸 + cooldown/cap
    idle_return_enabled: bool = True
    system_idle_minutes: int = 30

    @classmethod
    def from_cfg(cls, cfg: Any) -> "ProactiveConfig":
        """从 AppConfig 鸭子类型取 proactive 参数（缺字段用默认，不抛异常）。"""
        if cfg is None:
            return cls()

        def _get(*names: str, default: Any) -> Any:
            for n in names:
                v = getattr(cfg, n, None)
                if v is not None:
                    return v
            return default

        return cls(
            enabled=bool(_get("agent_proactive_enabled", default=True)),
            quiet_start=str(_get("agent_proactive_quiet_start", default=DEFAULT_QUIET_START)),
            quiet_end=str(_get("agent_proactive_quiet_end", default=DEFAULT_QUIET_END)),
            daily_cap=max(0, int(_get("agent_proactive_daily_cap", default=3) or 0)),
            idle_minutes=max(1, int(_get("agent_proactive_idle_minutes", default=90) or 1)),
            cooldown_minutes=max(0, int(_get("agent_proactive_cooldown_minutes", default=60) or 0)),
            llm_enhance=bool(_get("agent_proactive_llm_enhance", default=False)),
            # v1.3(P1-4)
            idle_return_enabled=bool(_get("agent_proactive_idle_return_enabled", default=True)),
            system_idle_minutes=max(1, int(_get("agent_proactive_system_idle_minutes", default=30) or 1)),
        )


# ---------------------------------------------------------------------------
# ProactivePolicy —— 纯规则判定（无 Qt、可自测）
# ---------------------------------------------------------------------------
@dataclass
class PolicyState:
    """决策输入快照（由 scheduler 组装）。"""
    now: datetime
    last_user_activity_at: Optional[datetime] = None  # 用户真实交互（主动消息不算）
    last_proactive_at: Optional[datetime] = None      # 上次主动（companion.proactive.last_at）
    count_today: int = 0                              # 今日已主动条数
    last_chat_event_at: Optional[datetime] = None     # 最近一次低情绪 chat 事件时间
    last_agent_done_at: Optional[datetime] = None     # 最近一次 agent_done 事件时间
    idle_already_helloed: bool = False                # 本轮空闲是否已问候过（内存标记）
    # v1.6(P1-1/D-V16-11): 外部冷却截止（免提退出 10min 恢复缓冲）—— 计入闸的
    # 一个输入，非独立闸；None/过去时 = 不拦截
    external_cooldown_until: Optional[datetime] = None
    # v1.8(V18-13/D-V18-07/Q-D6): 工作场景主动降档 —— external_cooldown_until
    # 同款落法（外部输入覆盖，非独立闸）：None = 走既有 cfg.daily_cap；
    # 工作场景激活时调度器按场景计算注入（3→1，可配置键调 0=工作时段不打扰）。
    external_daily_cap_override: Optional[int] = None


# ---------------------------------------------------------------------------
# v1.8(V18-13/D-V18-07/Q-D6): 工作场景 cap 降档计算（纯函数，无 Qt 可单测）
# ---------------------------------------------------------------------------
def scene_cap_override(cfg: Any, now: Optional[datetime] = None) -> Optional[int]:
    """按当前场景计算 external_daily_cap_override（external_cooldown_until 同款
    外部输入落法，四重闸结构零改动）。

    - 工作场景激活 → min(scene_work_proactive_cap, 用户配置 daily_cap)：
      降档不改档（Q-D6）——**绝不高于用户既有配置**（用户配 0 = 主动消息全关，
      工作场景不得悄悄放开）；scene_work_proactive_cap 可配 0（工作时段不打扰）；
    - 其余场景 / scene_auto 关闭 / 判定异常 → None（走既有 cfg.daily_cap）。
    """
    try:
        import scene as scene_mod
        if cfg is None or not bool(getattr(cfg, "scene_auto", True)):
            return None
        mo = scene_mod.resolve_manual_override(
            str(getattr(cfg, "manual_scene", "") or ""),
            str(getattr(cfg, "manual_scene_date", "") or ""))
        if scene_mod.current_scene(now or datetime.now(), mo) == scene_mod.SCENE_WORK:
            work_cap = max(0, int(getattr(cfg, "scene_work_proactive_cap", 1)))
            configured = max(0, int(getattr(cfg, "agent_proactive_daily_cap", 3) or 0))
            return min(work_cap, configured)
    except Exception:
        return None
    return None


class ProactivePolicy:
    """四重闸 + 三类场景的纯规则。decision() 返回 (allow, scene|None, block_reason)。"""

    @staticmethod
    def gates(cfg: ProactiveConfig, st: PolicyState) -> Optional[str]:
        """四重闸按序返回第一个拦截原因；全部通过返回 None。"""
        if not cfg.enabled:
            return "disabled"
        if is_in_quiet(st.now, cfg.quiet_start, cfg.quiet_end):
            return "quiet_hours"
        # v1.6(P1-1/D-V16-11): 免提退出恢复缓冲（计入闸，位于 quiet 后、cap 前）
        if st.external_cooldown_until is not None and st.now < st.external_cooldown_until:
            return "resume_buffer"
        # v1.8(V18-13/D-V18-07/Q-D6): 工作场景 cap 降档 —— 覆盖生效值而非加闸，
        # 四重闸结构零改动（其余输入：enabled/quiet/cooldown 行为逐字不变）
        cap = cfg.daily_cap
        if st.external_daily_cap_override is not None:
            try:
                cap = max(0, int(st.external_daily_cap_override))
            except (TypeError, ValueError):
                cap = cfg.daily_cap
        if st.count_today >= cap:
            return "daily_cap_reached"
        if st.last_proactive_at is not None:
            gap = (st.now - st.last_proactive_at).total_seconds() / 60.0
            if gap < cfg.cooldown_minutes:
                return f"cooldown({int(gap)}m<{cfg.cooldown_minutes}m)"
        return None

    @staticmethod
    def scene_hits(cfg: ProactiveConfig, st: PolicyState) -> Optional[str]:
        """按优先级返回命中的场景 id；无命中返回 None。"""
        # ① agent_revisit：近 5 分钟 agent 完成且其后用户未回复
        if st.last_agent_done_at is not None:
            within = (st.now - st.last_agent_done_at).total_seconds() <= AGENT_DONE_WINDOW_MIN * 60
            user_replied = (st.last_user_activity_at is not None
                            and st.last_user_activity_at >= st.last_agent_done_at)
            if within and not user_replied:
                return "agent_revisit"
        # ② low_emotion：近 5 分钟低情绪事件
        if st.last_chat_event_at is not None:
            within = (st.now - st.last_chat_event_at).total_seconds() <= LOW_EMOTION_WINDOW_MIN * 60
            if within:
                return "low_emotion"
        # ③ idle_hello：空闲超阈值且本轮空闲未问候过（防连环，用户交互后开放）
        if st.last_user_activity_at is not None:
            idle_min = (st.now - st.last_user_activity_at).total_seconds() / 60.0
            if idle_min >= cfg.idle_minutes and not st.idle_already_helloed:
                return "idle_hello"
        return None

    @staticmethod
    def decision(cfg: ProactiveConfig, st: PolicyState
                 ) -> tuple[bool, Optional[str], Optional[str]]:
        """返回 (allow, scene, block_reason)。allow=True 时调用方可开口。"""
        reason = ProactivePolicy.gates(cfg, st)
        if reason is not None:
            return False, None, reason
        scene = ProactivePolicy.scene_hits(cfg, st)
        if scene is None:
            return False, None, "no_scene"
        return True, scene, None


# ---------------------------------------------------------------------------
# 文案（氛围语境；不显示「今日第 N 次」等数值/义务感词，§3.9 红线）
# ---------------------------------------------------------------------------
SCENE_TEXTS: Dict[str, List[str]] = {
    "idle_hello": [
        "主人还在忙呀，码铃安静陪着呢~",
        "好久没听到主人的声音了，需要码铃的话随时喊一声~",
    ],
    "low_emotion": [
        "听起来有点辛苦呢…要不要先喝口水歇一歇？码铃在这儿~",
        "先别急，我们一件一件来，码铃陪着你~",
    ],
    "agent_revisit": [
        "刚才那件事码铃处理好啦，需要继续的话随时说~",
        "任务收尾完成~ 主人看看结果，有不对的码铃马上改~",
    ],
    # v1.3(P1-4): 「等她回来」Idle 问候 —— 系统全局空闲达标后恢复输入时一句迎接
    "idle_return": [
        "主人回来啦，码铃一直等着呢~",
        "欢迎回来~ 码铃乖乖守着，一刻都没偷懒哦。",
        "主人回来啦，要喝杯水休息一下吗？",
    ],
    # v1.3(P2-6): 纪念日祝福（独立 1 次/日配额，不走 cap/cooldown；受 quiet 约束）
    "anniversary": [
        "今天是个特别的日子，码铃想第一个送上祝福~",
    ],
}

# v1.3(P2-6): 纪念日祝福文案池（生日 / 初见；称谓经 stage_name 拼装，无数值/无倒计时）
ANNIVERSARY_BIRTHDAY_TEXTS = [
    "今天是主人的生日呀~ 生日快乐！愿主人新的一岁平安喜乐，码铃会一直陪着您~",
    "叮铃~ 主人的生日到啦！码铃在心里放了小烟花：生日快乐，这一年也要开开心心~",
]
ANNIVERSARY_FIRST_MEET_TEXTS = [
    "今天是我们初次相遇的日子，码铃一直记在心里呢~",
    "不知不觉又到初遇纪念日啦，谢谢主人愿意把码铃带回家~",
]


def build_text(scene: str, companion: Any = None) -> str:
    """按场景取一句文案；传入 companion 时拼一句当前心情语境（可裁剪）。"""
    text = random.choice(SCENE_TEXTS.get(scene, SCENE_TEXTS["idle_hello"]))
    if companion is not None:
        try:
            ctx = companion.current_mood_context()
            if ctx:
                return f"{text}\n{ctx}"
        except Exception:
            pass
    return text


# ---------------------------------------------------------------------------
# Qt 层：ProactiveScheduler（低频 QTimer；无 PySide6 时降级为普通类，可手动 run_check）
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QObject, QTimer, Signal
    QT_OK = True
except Exception:
    QT_OK = False
    QObject, QTimer, Signal = object, None, None

_Base = QObject if QT_OK else object


class ProactiveScheduler(_Base):
    """GUI 运行期唯一主动触发源：低频 QTimer + ProactivePolicy + 交付 ChatService。"""

    if QT_OK:
        # (text, scene) —— UI 订阅（主面板气泡/浮窗/托盘增强）可选用；渲染主通道仍走
        # ChatService.proactive_message
        proactive_ready = Signal(str, str)
    else:
        proactive_ready = None  # type: ignore[assignment]

    def __init__(self, app_ctx: Any, parent: Any = None, tick_ms: int = 60_000):
        if QT_OK:
            super().__init__(parent)
        else:
            super().__init__()  # type: ignore[arg-type]
        self.app_ctx = app_ctx
        self.tick_ms = max(10_000, int(tick_ms or 60_000))
        self._running = False
        # 运行态（防自续命相关的内存标记；应用退出即丢，符合 A9「仅 GUI 运行期」）
        self._idle_hello_sent = False
        self._last_user_activity_at: Optional[datetime] = None
        self._startup_greet_done = False  # v1.6(P0-3): startup_greet 一次性内存标记
        self._busy_flags: set = set()   # 占用锁：agent 工具循环 / 流式回复中不开口
        self._timer = None
        if QT_OK:
            self._timer = QTimer(self)
            self._timer.setInterval(self.tick_ms)
            self._timer.timeout.connect(self._on_tick)

    # -- 生命周期 --
    def start(self) -> bool:
        """低频轮询启动（间隔 tick_ms，默认 60s）。无 Qt 时返回 False（不真实定时）。"""
        if self._timer is None:
            return False
        self._timer.start()
        self._running = True
        return True

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._running = False

    def _on_tick(self) -> None:
        try:
            self.run_check()
        except Exception as exc:  # 主动陪伴失败绝不影响主流程
            _logger.warning("proactive tick 异常: %s", exc)
        # v1.3(P2-6): 纪念日祝福独立通道（同一 tick 顺带判定，不新起定时器）
        try:
            self.maybe_anniversary_blessing()
        except Exception as exc:
            _logger.warning("anniversary tick 异常: %s", exc)
        # v1.6(P0-3/D-V16-06): 启动问候一次性场景（复用同一 tick，不新起定时器；
        # 内部一次性内存标记防重复）
        try:
            self.maybe_startup_greet()
        except Exception as exc:
            _logger.warning("startup_greet tick 异常: %s", exc)
        # v1.7(F3/D-V17-02): 午后仪式检查点（仿纪念日独立通道，不走 cap/cooldown）
        try:
            self.maybe_afternoon_ritual()
        except Exception as exc:
            _logger.warning("afternoon_ritual tick 异常: %s", exc)

    # -- 交互打点 --
    def mark_user_activity(self) -> None:
        """用户真实交互打点：重置空闲计时 + 开放新一轮空闲问候资格。

        **主动消息绝不允许调用本方法（防自续命）**——由 ChatService 仅在
        send_message（用户发送）路径调用。
        """
        self._last_user_activity_at = datetime.now()
        self._idle_hello_sent = False

    def set_busy(self, tag: str, busy: bool) -> None:
        if busy:
            self._busy_flags.add(tag)
        else:
            self._busy_flags.discard(tag)

    def is_busy(self) -> bool:
        return bool(self._busy_flags)

    # -- 数据组装 --
    def _companion(self):
        return getattr(self.app_ctx, "companion", None)

    def _memory_mgr(self):
        """v1.6(P0-3): session.memory_mgr（GuiChatSession __getattr__ 透传；缺失→None）。"""
        session = getattr(self.app_ctx, "session", None)
        return getattr(session, "memory_mgr", None)

    def _todo_mgr(self):
        """v1.6(P0-3): session.todo_mgr（缺失→None）。"""
        session = getattr(self.app_ctx, "session", None)
        return getattr(session, "todo_mgr", None)

    def _build_content(self) -> tuple[Optional[str], str]:
        """v1.6(P0-3/D-V16-06): 内容拼装 —— 命中返回 (内容句, 内容源键)，未命中 (None, "")。

        greeting.build_contentful_line 失败一律静默降级为模板（逐字回退保障）。
        """
        try:
            from greeting import build_contentful_line
            hit = build_contentful_line(self._memory_mgr(), self._todo_mgr())
        except Exception as exc:
            _logger.debug("build_contentful_line 失败（回退模板）: %s", exc)
            return None, ""
        if hit and isinstance(hit, dict) and (hit.get("text") or "").strip():
            return str(hit["text"]), str(hit.get("subject") or "")
        return None, ""

    def _recent_event_time(self, etype: str,
                           data_filter: Optional[Callable[[dict], bool]] = None
                           ) -> Optional[datetime]:
        """companion.event_log 里最近一条满足类型的 at；data_filter 可选过滤 data。"""
        companion = self._companion()
        if companion is None:
            return None
        try:
            log = companion.to_dict().get("event_log") or []
        except Exception:
            return None
        for entry in reversed(log):
            if entry.get("type") != etype:
                continue
            if data_filter is not None:
                try:
                    if not data_filter(entry.get("data") or {}):
                        continue
                except Exception:
                    continue
            return parse_iso(entry.get("at"))
        return None

    def _build_state(self) -> Optional[PolicyState]:
        companion = self._companion()
        if companion is None:
            return None
        try:
            pstate = companion.proactive_snapshot()
        except Exception as exc:
            _logger.warning("proactive_snapshot 失败: %s", exc)
            pstate = {}
        low_event = self._recent_event_time("chat",
                                            lambda d: d.get("emotion") in NEGATIVE_EMOTIONS)
        agent_done = self._recent_event_time("agent_done")
        # v1.6(P1-1/D-V16-11): 免提退出恢复缓冲 —— 读控制器 resume_cooldown_until
        #（epoch 秒），未来时刻 → 注入 PolicyState.external_cooldown_until 入闸
        resume_until = None
        try:
            ctrl = getattr(self.app_ctx, "voice_conversation", None)
            until_ts = float(getattr(ctrl, "resume_cooldown_until", 0.0) or 0.0)
            if until_ts > 0:
                resume_until = datetime.fromtimestamp(until_ts)
                if resume_until <= datetime.now():
                    resume_until = None
        except Exception:
            resume_until = None
        # v1.8(V18-13/D-V18-07/Q-D6): 工作场景主动降档 —— 调度器每轮按
        # current_scene() 计算（纯函数 scene_cap_override，可独立单测）
        cap_override = scene_cap_override(
            getattr(self.app_ctx, "cfg", None) or getattr(self.app_ctx, "config", None))
        return PolicyState(
            now=datetime.now(),
            last_user_activity_at=self._last_user_activity_at,
            last_proactive_at=parse_iso(pstate.get("last_at")),
            count_today=int(pstate.get("count_today", 0) or 0),
            last_chat_event_at=low_event,
            last_agent_done_at=agent_done,
            idle_already_helloed=self._idle_hello_sent,
            external_cooldown_until=resume_until,
            external_daily_cap_override=cap_override,
        )

    # -- 核心单次检查（timer 回调 + 手动测试共用） --
    def run_check(self) -> Optional[str]:
        """执行一次主动判定：允许则投递并记账，返回场景 id；未允许返回 None。"""
        cfg = ProactiveConfig.from_cfg(getattr(self.app_ctx, "cfg", None))
        if not cfg.enabled:
            return None
        # demo 模式不触发（PRD A9）
        try:
            from gui.chat_service import _is_demo_mode
            if _is_demo_mode(self.app_ctx):
                return None
        except Exception:
            pass
        # 忙碌中不开口（防打断用户正在进行的流式/agent）
        if self.is_busy():
            return None
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None and getattr(chat_service, "is_busy", None) is not None:
            try:
                if chat_service.is_busy():
                    return None
            except Exception:
                pass

        st = self._build_state()
        if st is None:
            return None
        allow, scene, _block = ProactivePolicy.decision(cfg, st)
        if not allow or scene is None:
            return None

        # 长空闲：进入空闲本轮只问候一次（用户交互后经 mark_user_activity 复位）
        if scene == "idle_hello":
            self._idle_hello_sent = True

        # v1.6(P0-3/D-V16-06): 内容拼装（命中 → 场景句 + 换行 + 内容句；
        # 未命中 → build_text 逐字回退，与 v1.5.2 逐字一致）
        text = build_text(scene, self._companion())
        line, subject = self._build_content()
        if line:
            text = f"{text}\n{line}"
        delivered = self._deliver(text, scene, subject=subject)
        if delivered:
            companion = self._companion()
            try:
                companion.commit_proactive(count_delta=1)
            except Exception as exc:
                _logger.warning("commit_proactive 失败: %s", exc)
            return scene
        return None

    # -- v1.3(P1-4): Idle 问候入口（由 SystemIdleMonitor 上升沿回调，不新起定时器）--
    def on_system_idle_return(self) -> Optional[str]:
        """系统全局空闲 >= 阈值后用户恢复输入：判定是否放行一句 Idle 问候。

        与 A9 既有场景共享四重闸（enabled/quiet/cap/cooldown）与
        companion.proactive.{last_at,count_today} 计数器 —— 同一冷却窗内
        与 A9 app 内长空闲问候天然互斥不双发（design D-V13-03 / 共享知识 13）。
        离开过短（< 阈值）的判定在 SystemIdleMonitor 内完成；demo/忙挡在外。
        """
        cfg = ProactiveConfig.from_cfg(getattr(self.app_ctx, "cfg", None))
        if not cfg.enabled:
            return None
        if not cfg.idle_return_enabled:
            return None
        # demo 模式不触发（PRD A9/P1-4）
        try:
            from gui.chat_service import _is_demo_mode
            if _is_demo_mode(self.app_ctx):
                return None
        except Exception:
            pass
        # 忙碌中不开口（防打断用户正在进行的流式/agent）
        if self.is_busy():
            return None
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None and getattr(chat_service, "is_busy", None) is not None:
            try:
                if chat_service.is_busy():
                    return None
            except Exception:
                pass
        # 共享四重闸（仅查闸，不做 A9 场景命中——本场景由 Idle 监视器 crossing 直接给出）
        st = self._build_state()
        if st is None:
            return None
        block_reason = ProactivePolicy.gates(cfg, st)
        if block_reason is not None:
            _logger.debug("idle_return 被闸拦截: %s", block_reason)
            return None
        text = build_text("idle_return", self._companion())
        delivered = self._deliver(text, "idle_return")
        if delivered:
            companion = self._companion()
            try:
                companion.commit_proactive(count_delta=1)
            except Exception as exc:
                _logger.warning("commit_proactive 失败: %s", exc)
            return "idle_return"
        return None

    # -- v1.3(P2-6): 纪念日独立祝福通道（1 次/日；不走 cap/cooldown，受 quiet/demo/忙约束）--
    def maybe_anniversary_blessing(self) -> Optional[str]:
        """当日命中纪念日且未祝福 -> 一句主动祝福（生日/初见同日合并一条）。

        - **独立配额语义**：不走 daily_cap/cooldown 两道闸（温暖仪式不被日常问候挤掉），
          仍受 enabled / quiet / demo / busy 约束；不写 proactive 计数器（不占 A9 配额）。
        - **绝无补发**：blessed==today 即跳过；当天 app 没运行/无 key 即错过，不补记。
        - 生日与首次相见日同日撞车 -> kinds 两枚合并为一条文本投递（防双气泡）。
        """
        cfg = ProactiveConfig.from_cfg(getattr(self.app_ctx, "cfg", None))
        if not cfg.enabled:
            return None
        # 免打扰时段内不发声（复用 A9 quiet 口径）
        if is_in_quiet(datetime.now(), cfg.quiet_start, cfg.quiet_end):
            return None
        # demo 模式不触发（PRD A9/P2-6）
        try:
            from gui.chat_service import _is_demo_mode
            if _is_demo_mode(self.app_ctx):
                return None
        except Exception:
            pass
        # 忙碌中不开口（防打断用户正在进行的流式/agent）
        if self.is_busy():
            return None
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None and getattr(chat_service, "is_busy", None) is not None:
            try:
                if chat_service.is_busy():
                    return None
            except Exception:
                pass
        companion = self._companion()
        if companion is None or not hasattr(companion, "anniversary_due_today"):
            return None
        try:
            due = companion.anniversary_due_today()
        except Exception as exc:
            _logger.warning("anniversary_due_today 失败: %s", exc)
            return None
        if not due or not due.get("kinds"):
            return None
        kinds = list(due["kinds"])
        # 组装祝福文本（含关系称谓；合并为一条，杜绝双气泡）
        stage = ""
        if companion is not None:
            try:
                stage = companion.relation_stage_name()
            except Exception:
                stage = ""
        speaker = f"{stage}的码铃" if stage else "码铃"
        lines = []
        if "birthday" in kinds:
            lines.append(f"（{speaker}）{random.choice(ANNIVERSARY_BIRTHDAY_TEXTS)}")
        if "first_meet" in kinds:
            lines.append(f"（{speaker}）{random.choice(ANNIVERSARY_FIRST_MEET_TEXTS)}")
        text = "\n".join(lines) if lines else "（码铃）今天是个值得记在心里的日子~"
        delivered = self._deliver(text, "anniversary")
        if delivered:
            try:
                companion.mark_anniversary_blessed(detail=",".join(kinds))
            except Exception as exc:
                _logger.warning("mark_anniversary_blessed 失败（下个 tick 将重试）: %s", exc)
                return None
            return "anniversary"
        return None

    # -- v1.6(P0-3/D-V16-06): 启动问候一次性场景（走完整四重闸并占 cap/cooldown）--
    def maybe_startup_greet(self) -> Optional[str]:
        """启动后首个 tick 的一次性问候（仿 maybe_anniversary_blessing 独立通道模式）。

        语义（D-V16-06）：
          - **走完整四重闸并占 cap/cooldown**（与随后的 idle_hello 天然互斥不双发）；
          - 一次性内存标记防重复：首个 tick 判定后无论放行与否均不再触发
            （错过不补，与纪念日「绝无补发」同精神）；
          - 用户已交互（last_user_activity 非空且空闲未达阈值）时让路不开口；
          - 内容 = build_contentful_line 命中 → 场景句 + 内容句（scene 不变
            "idle_hello"、subject 随内容源传出）；未命中 → 纯模板逐字回退。
        gui/main.py 装配完成后由首个 tick 自动触发；异常由 _on_tick 守卫。
        """
        cfg = ProactiveConfig.from_cfg(getattr(self.app_ctx, "cfg", None))
        if not cfg.enabled:
            self._startup_greet_done = True
            return None
        if self._startup_greet_done:
            return None
        self._startup_greet_done = True  # 一次性：本进程只判定这一次
        # demo 模式不触发（PRD A9）
        try:
            from gui.chat_service import _is_demo_mode
            if _is_demo_mode(self.app_ctx):
                return None
        except Exception:
            pass
        # 忙碌中不开口
        if self.is_busy():
            return None
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None and getattr(chat_service, "is_busy", None) is not None:
            try:
                if chat_service.is_busy():
                    return None
            except Exception:
                pass
        st = self._build_state()
        if st is None:
            return None
        # 用户已交互且空闲未达阈值 → 让路（避免开机即打字时的打扰）
        if st.last_user_activity_at is not None:
            idle_min = (st.now - st.last_user_activity_at).total_seconds() / 60.0
            if idle_min < cfg.idle_minutes:
                _logger.debug("startup_greet 让路：用户已交互（%.0fmin < %dmin）",
                              idle_min, cfg.idle_minutes)
                return None
        # 完整四重闸（enabled/quiet/cap/cooldown）——占配额语义
        block_reason = ProactivePolicy.gates(cfg, st)
        if block_reason is not None:
            _logger.debug("startup_greet 被闸拦截: %s", block_reason)
            return None
        text = build_text("idle_hello", self._companion())
        line, subject = self._build_content()
        ritual_line = None
        if line:
            # v1.7(F3 裁决): 内容句优先于仪式句（早安编排与内容句二选一，防问候过长）
            text = f"{text}\n{line}"
        else:
            ritual_line = self._morning_ritual_line()
            if ritual_line:
                text = f"{text}\n{ritual_line}"
        delivered = self._deliver(text, "idle_hello", subject=subject)
        if delivered:
            if ritual_line:
                self._mark_morning_ritual()
            companion = self._companion()
            try:
                companion.commit_proactive(count_delta=1)
            except Exception as exc:
                _logger.warning("commit_proactive 失败: %s", exc)
            return "idle_hello"
        return None

    # -- v1.7(F3/D-V17-02): 时段仪式三通道 --

    def _ritual_store(self):
        """ritual.json 记账本（app 级单例，懒建；失败→None 静默降级）。"""
        store = getattr(self, "_ritual_store_obj", None)
        if store is not None:
            return store
        try:
            # 优先复用 app_ctx 注入的 store（测试注入点 / app 级共享单例）
            injected = getattr(self.app_ctx, "ritual_store", None)
            if injected is not None:
                self._ritual_store_obj = injected
                return injected
            from quotations import RitualStore
            store = RitualStore()
            self._ritual_store_obj = store
        except Exception as exc:
            _logger.debug("RitualStore 初始化失败（仪式通道降级）: %s", exc)
            return None
        return store

    def _stage_and_weight(self) -> tuple[str, str]:
        """（阶段名, 语录池加权档）——F5 特权表消费（信赖/亲近 → 亲昵子池优先）。"""
        stage = ""
        companion = self._companion()
        if companion is not None:
            try:
                stage = str(companion.relation_stage_name() or "")
            except Exception:
                stage = ""
        weight = "plain"
        try:
            tracker = getattr(self.app_ctx, "intimacy", None)
            if tracker is not None and hasattr(tracker, "stage_privileges"):
                weight = str(tracker.stage_privileges().get("quote_pool_weight", "plain"))
        except Exception:
            weight = "plain"
        return stage, weight

    def _morning_ritual_line(self) -> Optional[str]:
        """早安编排句：时段 ∈ 清晨/上午（5–11 点）∧ 当日未给 morning。

        二选一裁决的落点：仅在 build_contentful_line 未命中时消费（仪式句
        优先级低于话题续接）；命中 None 时由调用方并入 startup 问候。
        """
        now = datetime.now()
        if not (5 <= now.hour < 11):
            return None
        store = self._ritual_store()
        if store is None or store.given("morning"):
            return None
        stage, weight = self._stage_and_weight()
        nickname = "主人"
        try:
            memory = self._memory_mgr()
            if memory is not None and hasattr(memory, "get_preference"):
                nickname = str(memory.get_preference("nickname") or "主人") or "主人"
        except Exception:
            nickname = "主人"
        try:
            from quotations import pick_quote
            quote = pick_quote(now.strftime("%Y-%m-%d"), "morning", weight)
        except Exception as exc:
            _logger.debug("pick_quote(morning) 失败（仪式跳过）: %s", exc)
            return None
        try:
            from greeting import build_morning_ritual
            line = build_morning_ritual(quote, nickname=nickname, stage=stage)
        except Exception as exc:
            _logger.debug("build_morning_ritual 失败（仪式跳过）: %s", exc)
            return None
        self._pending_morning_quote = quote  # 交付成功后由 _mark_morning_ritual 记账
        return line

    def _mark_morning_ritual(self) -> None:
        """早安仪式记账（仅投递成功后调用；失败不影响本条已交付的问候）。"""
        store = self._ritual_store()
        if store is None:
            return
        try:
            store.mark_given("morning", getattr(self, "_pending_morning_quote", None))
        except Exception as exc:
            _logger.warning("morning 仪式记账失败（下个启动日不再重试当日）: %s", exc)

    def maybe_afternoon_ritual(self) -> Optional[str]:
        """午后检查点（仿 maybe_anniversary_blessing 独立通道模式）。

        - **不走 cap/cooldown**（温暖仪式不被日常问候挤掉——纪念日先例），
          仍受 enabled / quiet / demo / busy 约束；不写 proactive 计数器；
        - 窗口 14:00–17:00 ∧ 当日未给 afternoon → 一句轻量午后小句；
        - **错过不补**（窗口外/当日错过即无，无补发队列）；
        - 一日两条仪式句上限由 ritual.json 天然保证（morning + afternoon 各一）。
        """
        cfg = ProactiveConfig.from_cfg(getattr(self.app_ctx, "cfg", None))
        if not cfg.enabled:
            return None
        now = datetime.now()
        if not (14 <= now.hour < 17):
            return None
        if is_in_quiet(now, cfg.quiet_start, cfg.quiet_end):
            return None
        try:
            from gui.chat_service import _is_demo_mode
            if _is_demo_mode(self.app_ctx):
                return None
        except Exception:
            pass
        if self.is_busy():
            return None
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is not None and getattr(chat_service, "is_busy", None) is not None:
            try:
                if chat_service.is_busy():
                    return None
            except Exception:
                pass
        store = self._ritual_store()
        if store is None or store.given("afternoon"):
            return None
        _, weight = self._stage_and_weight()
        try:
            from quotations import pick_quote
            quote = pick_quote(now.strftime("%Y-%m-%d"), "afternoon", weight)
        except Exception as exc:
            _logger.debug("pick_quote(afternoon) 失败（仪式跳过）: %s", exc)
            return None
        try:
            from greeting import build_afternoon_line
            text = build_afternoon_line(quote)
        except Exception as exc:
            _logger.debug("build_afternoon_line 失败（仪式跳过）: %s", exc)
            return None
        delivered = self._deliver(text, "afternoon_ritual", subject="")
        if delivered:
            try:
                store.mark_given("afternoon", quote)
            except Exception as exc:
                _logger.warning("afternoon 仪式记账失败: %s", exc)
            return "afternoon_ritual"
        return None

    # -- 呈现入口 --
    def _deliver(self, text: str, scene: str, subject: str = "") -> bool:
        """唯一交付路径：ChatService.proactive_ask（独立入口，防自续命）。

        v1.6(P0-3): subject = 反馈内容源键（话题 subject / "__emotion__" /
        "__todo__"；模板问候为 ""，不渲染反馈三键）。返回是否成功投递；
        渲染由 ChatService.proactive_message 广播。
        """
        chat_service = getattr(self.app_ctx, "chat_service", None)
        if chat_service is None or not hasattr(chat_service, "proactive_ask"):
            return False
        try:
            return bool(chat_service.proactive_ask(text, scene, subject=subject))
        except Exception as exc:
            _logger.warning("proactive_ask 失败: %s", exc)
            return False
