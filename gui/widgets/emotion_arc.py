"""gui/widgets/emotion_arc.py —— v1.8(F2/D-V18-03/Q-D3) 情绪弧线：8 周日格色带。

纯 Qt（QFrame 网格 + QLabel 色块），零第三方依赖；数据源 = MemoryManager
get_emotions_history()（只读，memory 层零改动）。展示约定（R-A 本期主战场）：
  - 最近 8 周 × 7 日格（列 = 周，旧 → 新；行 = 周一 → 周日）；
  - 档位色块：按情绪分类映射颜色（平稳=主题淡色 / 元气=暖黄 / 有点累=淡橙 /
    低落=淡蓝），走 theme_color 语义取色 + 固定 fallback（深浅色各宜）；
  - 当日多条取众数（同数取后见者——情绪就近呈现）；
  - **无记录 = 浅灰点，不臆造**；
  - hover 仅档位词（"那天有点累"）——**零数字**；
  - 固定说明文案："这只是帮你看见自己，不是给你打分。"
  - **全组件无 int→str 上屏路径**（无分数/百分比/计数/坐标轴/日期数字上屏，
    验收断言见 tests/test_v18_batch1.py）；
  - 今日格轻呼吸动画（**v2.x：不再自带 QTimer**，统一经 ``gui.motion.loop`` 收口 ——
    **每周期翻转一次**外圈（半周期 = 1 个 period = 1600ms，贴原实现 1400ms），accent ↔ 透明；
    ``off`` 档 / 系统关动画**不起循环**、定格静态形态，绝不残留动画），
    **R-P：按可见性启停 —— 隐藏即停，不再常驻空转**；
  - 点击有记录的日格发 dayClicked(date_iso) 信号（页面侧跳该日条目列表）。
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from gui import motion
from gui.qt_compat import QFrame, QLabel, Qt, QVBoxLayout, QHBoxLayout, QWidget, Signal
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui.emotion_arc")

__all__ = ["EmotionArcWidget", "emotion_tier_word", "TIER_WORD_OF_EMOTION"]

ARC_WEEKS = 8          # 弧线回看周数（8 周 × 7 日格）
ARC_EMPTY_DAYS = ARC_WEEKS * 7

# 情绪分类 -> 档位词（hover 文案与色块语义的唯一来源；零数字）
TIER_WORD_OF_EMOTION = {
    "happy": "元气满满",
    "tired": "那天有点累",
    "anxious": "心里装着事",
    "lonely": "安安静静",
    "normal": "平平常常",
}

# 档位 -> 主题色语义键 + 深浅色皆宜的 fallback（淡色系，不做浓色评分感）
_TIER_COLOR_KEYS = {
    "happy": ("warning", "#FFE9B8"),     # 元气 = 暖黄
    "tired": ("warning_strong", "#FFD9C2"),  # 有点累 = 淡橙
    "anxious": ("info", "#CCE4F6"),      # 心里装着事 = 淡蓝
    "lonely": ("info", "#D8E4F0"),       # 安安静静 = 更淡蓝
    "normal": ("divider", "#F1E4E6"),    # 平稳 = 主题淡色
}
_EMPTY_COLOR_FALLBACK = "#EFEDED"    # 空日浅灰点
_TODAY_RING_FALLBACK = "#FF6B9D"     # 今日格外圈（accent）

#: 呼吸「周期」（ms）——经 ``motion.loop_period_ms`` 夹取到 ``[800, 1600]``。
#: **取夹取上限 1600**：外圈**每个周期翻转一次**（半周期 = 1 个周期）→ 半周期实测
#: ≈1600ms，与原实现（QTimer 1400ms 取反 → 半周期 1400ms / 整周期 2800ms）观感最接近
#: （+14%）；优先「保真原节奏」而非字面 1400。若用 ``progress < 0.5`` 会把每周期再劈半
#: → 半周期仅 800ms，反而更快更违和。
_BREATH_PERIOD_MS = 1600


def emotion_tier_word(emotion: str) -> str:
    """情绪分类 -> 档位词；未知分类回落「平平常常」（绝不输出数字）。"""
    return TIER_WORD_OF_EMOTION.get(str(emotion or "").strip(), TIER_WORD_OF_EMOTION["normal"])


class _DayCell(QLabel):
    """单日格：色块 + hover 档位词 + 可点击（仅在有记录的日子）。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignCenter)
        self._date_iso = ""
        self._tier_word = ""

    def apply_day(self, date_iso: str, tier_word: str, color: str,
                  is_today: bool, ring: str) -> None:
        """写入一日的外观（文本恒为空——上屏只有颜色，零数字路径）。"""
        self._date_iso = date_iso
        self._tier_word = tier_word
        self.setText("")  # 色块无文字；hover 词走 tooltip
        if tier_word:
            self.setToolTip(tier_word)   # hover 仅档位词（"那天有点累"式）
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setToolTip("")          # 空日零 hover 词（不臆造）
            self.unsetCursor()
        border = f"2px solid {ring}" if is_today else "1px solid transparent"
        self.setStyleSheet(
            f"background: {color}; border: {border}; border-radius: 4px;")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.trigger_click()
        super().mousePressEvent(event)

    def trigger_click(self) -> None:
        """日格点击（有记录的日才发信号；供测试与键盘可达性复用）。"""
        if self._date_iso and self._tier_word:
            parent = self.parent()
            while parent is not None and not isinstance(parent, EmotionArcWidget):
                parent = parent.parent()
            if parent is not None:
                parent.dayClicked.emit(self._date_iso)


class EmotionArcWidget(QFrame):
    """情绪弧线区块：8 周 × 7 日格色带 + 固定说明文案（R-A 零数字）。"""

    dayClicked = Signal(str)   # 该日（YYYY-MM-DD）条目跳转（页面侧接）

    def __init__(self, app_ctx: Any, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self.setObjectName("emotionArc")
        self._cells: List[List[_DayCell]] = []
        self._breath_on = False
        self._today_cell: Optional[_DayCell] = None
        #: 循环句柄（``gui.motion.loop``）；None ⇒ 未启动 / 已停
        self._breath_handle = None
        #: 相位回绕计数（每过一个周期 +1，**单调递增**；奇偶决定外圈高亮 —— 自校正、
        #: 不"读当前值取反"，丢帧不会错位）
        self._breath_period_n = 0
        self._last_progress = None
        self._build_ui()
        # v2.x（修复 D-V21-01 违例）：呼吸**不再自带 QTimer**，统一经 ``gui.motion.loop``
        # 收口 —— 读 ``enabled()``（``off`` 档不起循环）、走模块级共享驱动器、周期经
        # ``loop_period_ms`` 夹取。**不在此启动**：由 showEvent 按可见性启、hideEvent 停
        # （R-P 隐藏即停，防组件不可见时后台空转）。首帧今日格高亮由 refresh_arc →
        # _breathe(force=True) 保证，无需依赖循环。
        # 另订阅既有「页面切换」广播（PageManager.page_changed）：切回本页时若已可见
        # 且档位可动则确保循环在跑（幂等自愈；见 _on_page_changed）。
        self._connect_pager()

    # -- UI 骨架 --
    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        caption = QLabel("这只是帮你看见自己，不是给你打分。")
        caption.setObjectName("emotionArcCaption")
        caption.setWordWrap(True)
        lay.addWidget(caption)
        grid_host = QWidget()
        grid = QVBoxLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(3)
        today = date.today()
        # 列 = 周（旧 → 新），行 = 周一 → 周日
        this_monday = today.toordinal() - today.weekday()
        for row in range(7):
            hrow = QHBoxLayout()
            hrow.setSpacing(3)
            cells_row: List[_DayCell] = []
            for col in range(ARC_WEEKS):
                # 该格日期 = 本周一起回退 (ARC_WEEKS-1-col) 周 + row 天
                ordinal = this_monday - (ARC_WEEKS - 1 - col) * 7 + row
                cell = _DayCell(grid_host)
                cell.setToolTip("")
                hrow.addWidget(cell)
                cells_row.append(cell)
            grid.addLayout(hrow)
            self._cells.append(cells_row)
        lay.addWidget(grid_host)
        self._apply_style()

    # -- 数据渲染 --
    def refresh_arc(self, emotions: Optional[List[dict]] = None) -> None:
        """重绘色带（emotions = get_emotions_history() 只读副本；无数据空灰）。"""
        by_date: Dict[str, List[str]] = {}
        for e in emotions or []:
            if not isinstance(e, dict):
                continue
            try:
                d = datetime.fromisoformat(str(e.get("time", ""))).date()
            except (TypeError, ValueError):
                continue
            emo = str(e.get("emotion", "")).strip()
            if emo:
                by_date.setdefault(d.isoformat(), []).append(emo)
        today = date.today()
        self._today_cell = None
        for row in range(7):
            for col in range(ARC_WEEKS):
                cell = self._cells[row][col]
                ordinal = (today.toordinal() - today.weekday()
                           - (ARC_WEEKS - 1 - col) * 7 + row)
                d = date.fromordinal(ordinal)
                iso = d.isoformat()
                emos = by_date.get(iso) or []
                if not emos:
                    # 无记录 = 浅灰点，不臆造（R-A）
                    cell.apply_day("", "", self._color("_empty", _EMPTY_COLOR_FALLBACK),
                                   d == today, self._ring_color())
                    continue
                # 当日多条取众数（同数取后见者——情绪就近呈现）
                counts: Dict[str, int] = {}
                for emo in emos:
                    counts[emo] = counts.get(emo, 0) + 1
                dominant = max(counts.items(), key=lambda kv: (kv[1], emos.index(kv[0])))[0]
                tier = emotion_tier_word(dominant)
                color = self._color(_TIER_COLOR_KEYS.get(dominant, ("divider", "#F1E4E6")))
                cell.apply_day(iso, tier, color, d == today, self._ring_color())
                if d == today:
                    self._today_cell = cell
        self._breathe(force=True)

    # -- 语义取色（theme_color 缺键回落固定淡色，深浅色皆宜）--
    def _color(self, key_pair, fallback: str = "") -> str:
        if isinstance(key_pair, tuple):
            key, fb = key_pair
        else:
            key, fb = key_pair, fallback
        return theme_color(self.app_ctx, key, fb)

    def _ring_color(self) -> str:
        return theme_color(self.app_ctx, "accent", _TODAY_RING_FALLBACK)

    def _apply_style(self) -> None:
        text = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        border = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QFrame#emotionArc {{ background: transparent;"
            f" border: 1px solid {border}; border-radius: 10px; }}"
            f"QLabel#emotionArcCaption {{ color: {text}; font-size: 11px;"
            f" background: transparent; border: none; }}"
        )

    # -- 今日格轻呼吸（两种淡色交替，无文字无数字）--
    def _apply_breath(self, on: bool) -> None:
        """把今日格外圈按 ``on`` 应用（``on`` = accent 高亮 / 否则透明）。

        呼吸与静态形态共用本方法；样式与旧 ``_breathe`` **逐字一致**（零视觉差异）：
        背景恒为主题淡色 ``divider``，外圈在 accent 与透明间切换。
        """
        cell = self._today_cell
        if cell is None or not cell._tier_word:
            return
        # 呼吸 = 外圈色在 accent 与透明间交替（零文字变更，零数字上屏）
        ring = self._ring_color() if on else "transparent"
        cell.setStyleSheet(
            f"background: {self._color(('divider', '#F1E4E6'))};"
            f" border: 2px solid {ring}; border-radius: 4px;")

    def _breathe(self, force: bool = False) -> None:
        """首帧静态高亮（``refresh_arc`` 依赖；保留其能力）。

        ``force=True`` → 今日格定格 accent 高亮（数据刷新后的初始强调）。
        真正的时间驱动已改由 ``motion.loop`` 的 :meth:`_on_tick` 承担
        （``_breath_on`` 由**单调周期计数**的奇偶推导，不再"取反翻转"）。
        """
        if force:
            self._breath_on = True
        self._apply_breath(self._breath_on)

    def _static_breath(self) -> None:
        """静态形态（R-Q）：外圈透明、``_breath_on=False``，并立即应用样式。"""
        self._breath_on = False
        self._apply_breath(False)

    # -- 循环收口：gui.motion.loop / stop_loop（不自带 QTimer，签名即内核契约）--
    def _on_tick(self, progress: float) -> None:
        """循环每个 tick：**每过一个周期翻转一次**外圈高亮（半周期 = 1 个 period）。

        周期边界由相位**回绕**推导（``progress`` 较上一帧变小 = 进入新周期）→ 驱动
        单调递增的周期计数 ``_breath_period_n``，其奇偶决定高亮。这样半周期恰为一个
        ``period_ms``（1600ms），贴近原实现的 1400ms；且不"读当前值取反"、不因丢帧错位
        （一次回绕 = 一个周期）。注：共享驱动器 ~16ms/帧，若按帧取反则半周期只剩 ~16ms，
        故必须按**周期回绕**而非按帧推导。
        """
        prev = self._last_progress
        if prev is not None and progress < prev:
            self._breath_period_n += 1     # 相位回绕 = 进入下一个周期
        self._last_progress = progress
        self._breath_on = (self._breath_period_n % 2 == 0)
        self._apply_breath(self._breath_on)

    def _on_disabled(self) -> None:
        """因禁用而停（档位切 ``off`` / 系统关动画 / ``stop_all()``）→ 切静态形态。

        R-Q 硬要求：``off`` 档不得留动画残留。置句柄为空，便于再次可见时重建。
        """
        self._breath_handle = None
        self._static_breath()

    def _resume_breath(self) -> None:
        """可见时启动呼吸循环；已有句柄 / 当前不可见则不启动（**幂等**）。"""
        if self._breath_handle is not None:
            return
        if not self.isVisible():
            return
        try:
            handle = motion.loop(
                self, self._on_tick, period_ms=_BREATH_PERIOD_MS,
                on_disabled=self._on_disabled,
            )
        except Exception:
            logger.debug("情绪弧线呼吸循环启动失败（保持静态）", exc_info=True)
            return
        if handle is None:
            # off 档 / 系统关动画 / 无 QApplication：不启动、不报错 → 定格静态形态
            self._static_breath()
            return
        self._breath_handle = handle
        self._last_progress = None      # 新循环：相位 / 周期计数归零
        self._breath_period_n = 0
        self._on_tick(0.0)    # 首帧高亮（与 refresh_arc 的静态高亮一致）

    def _kill_breath(self) -> None:
        """显式停循环（隐藏即停）；**幂等**，显式停**不**触发 ``on_disabled``。"""
        handle = self._breath_handle
        self._breath_handle = None
        if handle is None:
            return
        try:
            motion.stop_loop(handle)
        except Exception:
            logger.debug("情绪弧线呼吸循环停止异常", exc_info=True)

    # -- 自愈：订阅既有「页面切换」广播（不改 PageManager / motion / 设置页）--
    def _connect_pager(self) -> None:
        """订阅 ``app_ctx.page_manager.page_changed``（既有信号）；取不到则静默跳过。

        仅为「切档位后回到本页」这类场景提供一次幂等自愈机会（``page_changed`` 与
        ``hideEvent``/``showEvent`` 时序相容：切走时先 hide 再广播 → 不可见不启动）。
        """
        pm = getattr(self.app_ctx, "page_manager", None) if self.app_ctx is not None else None
        if pm is None:
            return
        sig = getattr(pm, "page_changed", None)
        if sig is None or not hasattr(sig, "connect"):
            return
        try:
            sig.connect(self._on_page_changed)
        except Exception:
            logger.debug("情绪弧线订阅 page_changed 失败（不影响显示）", exc_info=True)

    def _on_page_changed(self, _page_key: str = "") -> None:
        """页面切换广播：若本控件此刻可见且档位可动，则确保呼吸循环在跑（幂等）。"""
        self._resume_breath()

    # -- R-P：可见性启停（隐藏即停，防后台空转）--
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._resume_breath()

    def hideEvent(self, event) -> None:
        self._kill_breath()
        super().hideEvent(event)

    # -- R-A 守卫：组件上屏文本恒为零数字（供验收断言复用）--
    def screen_texts(self) -> List[str]:
        """收集所有可能上屏的文本（caption + 全部 tooltip + cell 文本）。"""
        texts = [self.findChild(QLabel, "emotionArcCaption").text()]
        for row in self._cells:
            for cell in row:
                texts.append(cell.text())
                tip = cell.toolTip()
                if tip:
                    texts.append(tip)
        return texts
