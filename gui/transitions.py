"""通用过渡层（质感试点）—— 一切过渡经本模块，落点不再手写动画。

**定位**：本层是 ``gui.motion``（动效内核）之上的**薄封装**，提供两类过渡：

  · **入场淡入** :func:`fade_in` —— 一次性过渡（切页 / 浮层出现等）；
  · **按压反馈** :func:`install_press_feedback` —— 按钮按下/松开的微交互。

.. warning::

   **本层当前只对外提供「按压反馈」**，生产侧唯一落点是
   ``MainWindow._connect_signals()`` 里的
   ``transitions.install_press_feedback_recursive(self.sidebar)``。

   **切页淡入不归本层管** —— 它由 ``MainWindow._on_page_switched()``
   （经 ``PageManager.page_changed`` 信号触发）直接调用 ``motion.fade()`` 实现，
   且已处理同页快速重切 / ``motion`` 缺失兜底。**切勿在** ``PageManager.navigate()``
   **里再接一次** ``fade_in`` —— 那会与既有的 ``_on_page_switched`` 形成双动画，
   抢同一个 ``opacity`` 属性导致抖动（v2.1 试点踩过的坑，已回退）。

**为什么需要这一层**：Qt 的 QSS **不支持** ``transition`` 属性，CSS 里一行
``transition: all .2s`` 就能全局平滑的事情，在 Qt 里每个过渡都得手写动画。
本层把这些手写动画收口成两个函数，业务侧"改一处"即可全局生效/回滚。

**纪律（与项目 §八 动效纪律一致）**：
  · 本层**只做过渡与反馈**，不引入任何新的"图形母题运动"
    （禁止跳动圆点 / 电平柱 / 涟漪扩散 / 旋转环等），仅调节「不透明度」；
  · **不改变** geometry / size / font —— 那会触发布局重排，正是"不丝滑"的来源；
  · 时长一律经 ``motion.duration()``、缓动一律经 ``motion.easing()``，
    本层**不硬编码**具体曲线，只在参数里给"基准毫秒"供夹取；
  · ``motion.enabled() == False``（``off`` 档 / 系统减少动画）时：
    不安装过滤器、不创建 effect、不残留半透明 —— **界面必须完全正常**；
  · R-F：零新增运行时第三方依赖（仅 PySide6 内置 + 标准库）。

**总开关**：模块级 :data:`ENABLED` 置 ``False`` 即整体失效（快速 A/B 对比用）。

无 ``QApplication`` 也可安全 import：顶层不创建任何 Qt 对象。
"""
from __future__ import annotations

from typing import Optional

from gui.qt_compat import (
    QApplication, QDialog, QEvent, QGraphicsOpacityEffect, QObject,
    QPushButton, QToolButton, Qt,
)
import logging

# v2.1(可观测性)：静默 except 收敛用 —— 本文件此前多处 `except ...: pass` 无任何
#   记录，异常被完全吞掉，问题只能靠肉眼发现。改走 logger.debug 后可在日志里定位
#   （仅记录、不重抛，行为零变化）。
logger = logging.getLogger("maid_coder.gui.transitions")

# 动效内核（只调用不改）；缺失时静默降级（R-Q⑤：模块可整体剥离）
try:
    from gui import motion
except Exception:  # pragma: no cover - 内核剥离兜底
    motion = None

__all__ = [
    "ENABLED",
    "fade_in",
    "install_press_feedback",
    "install_press_feedback_recursive",
    "install_press_feedback_for_dialogs",
    "uninstall_press_feedback",
]

# ---------------------------------------------------------------------------
# 总开关（置 False → 全部函数退化为 no-op，便于快速对比效果）
# ---------------------------------------------------------------------------
ENABLED: bool = True

# 按压反馈默认基准时长（经 motion.duration() 夹取 ≤ MAX_DURATION_MS；非硬编码终值）
_PRESS_DOWN_BASE_MS = 110
_PRESS_UP_BASE_MS = 160
_PRESS_MIN_OPACITY = 0.72

# 回调事件类型：按下（含双击的按下分支）→ 变暗；松开 → 复原
_PRESS_EVENTS = (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick)
_RELEASE_EVENTS = (QEvent.MouseButtonRelease,)
# 兜底复原：指针移出 / 控件隐藏时强制回 1.0，杜绝"半透明残留"
_RESET_EVENTS = (QEvent.Leave, QEvent.HoverLeave, QEvent.Hide, QEvent.HideToParent)

# v2.1(P1 铺开): 参与按压反馈的按钮类型 —— QPushButton（含子类）+ QToolButton。
#   不含 QCheckBox/QRadioButton（有勾选态，按下变暗会与状态语义混淆）。
_PRESS_BUTTON_TYPES = (QPushButton, QToolButton)

# ---------------------------------------------------------------------------
# 模块级登记（防 GC 双保险 + 销毁清理）
# ---------------------------------------------------------------------------
# 进行中的淡入动画：widget id → QPropertyAnimation（重入时先停旧的，杜绝叠加）
_FADE_ACTIVE: "dict[int, object]" = {}
# 按压反馈过滤器：widget id → _PressFeedback（强引用防 GC；widget 销毁时弹出）
_PRESS_FILTERS: "dict[int, QObject]" = {}
# 已安装标记（动态属性名）：避免重复安装 + fade_in 收尾时判断要不要摘 effect
_PRESS_PROP = "pressFeedbackInstalled"


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _motion_on() -> bool:
    """动效是否可用：总开关 + 内核存在 + ``motion.enabled()`` 三重判定。"""
    return bool(ENABLED) and motion is not None and bool(motion.enabled())


def _opacity_effect(widget) -> "Optional[QGraphicsOpacityEffect]":
    """取 ``widget`` 上已有的 opacity effect；没有或类型不符返回 ``None``。

    **绝不覆盖**其它图形效果（如投影 ``QGraphicsDropShadowEffect``）——
    那会破坏既有视觉，属"改出新问题"。
    """
    try:
        eff = widget.graphicsEffect()
    except Exception:
        return None
    return eff if isinstance(eff, QGraphicsOpacityEffect) else None


def _has_other_effect(widget) -> bool:
    """``widget`` 上是否挂着**非 opacity** 的图形效果（此时本层一律不接管）。"""
    try:
        eff = widget.graphicsEffect()
    except Exception:
        return True  # 读不到 → 保守视为"已有"，不动
    return eff is not None and not isinstance(eff, QGraphicsOpacityEffect)


def _is_left_button(event) -> bool:
    """事件是否由鼠标**左键**触发（鸭子类型取值，避免新增导入）。"""
    getter = getattr(event, "button", None)
    if not callable(getter):
        return False
    try:
        return getter() == Qt.LeftButton
    except Exception:
        return False


def _safe_stop(anim) -> None:
    """停掉动画；C++ 侧已销毁 / 参数为空时静默（``stop()`` 不发 finished，
    故不会误触发收尾回调 —— 与 ``MainWindow._on_page_switched`` 同策略）。"""
    if anim is None:
        return
    try:
        anim.stop()
    except Exception:
        logger.debug("静默降级：_safe_stop 中忽略异常", exc_info=True)


# ---------------------------------------------------------------------------
# ① 入场淡入
# ---------------------------------------------------------------------------
def fade_in(widget, *, duration_ms: Optional[int] = None,
            on_finished=None) -> "Optional[object]":
    """把 ``widget`` 从全透明淡入到不透明（一次性过渡）。

    实现：确保 ``widget`` 上挂一个 ``QGraphicsOpacityEffect`` 并把 opacity 归零，
    再复用 ``motion.fade(widget, to=1.0, ...)`` 完成淡入；结束后（默认）摘掉
    effect，避免长期挂 opacity 带来的合成开销与"半透明残留"风险。

    重入安全：同一 widget 上再次调用会先停掉上一段未完成的淡入，
    **绝不叠加**两个动画（否则同属性互相打架 → 抖动）。

    Args:
        widget: 目标控件（``QWidget``）。
        duration_ms: 基准时长；``None`` 走 ``motion.duration()`` 档位默认。
        on_finished: 动画结束回调（无参）。

    Returns:
        在跑的 ``QPropertyAnimation``；``off`` 档 / 总开关关闭 / 控件已有非
        opacity 效果时返回 ``None`` 且**不产生任何副作用**。
    """
    if widget is None or not _motion_on():
        return None
    # 已有投影等效果 → 不接管（避免破坏既有视觉）
    if _has_other_effect(widget):
        return None

    key = id(widget)
    _safe_stop(_FADE_ACTIVE.pop(key, None))

    eff = _opacity_effect(widget)
    if eff is None:
        try:
            eff = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(eff)
        except Exception:
            _FADE_ACTIVE.pop(key, None)
            return None
    try:
        eff.setOpacity(0.0)  # 归零：保证每次切换都是完整的 0 → 1
    except Exception:
        logger.debug("静默降级：fade_in 中忽略异常", exc_info=True)

    anim = motion.fade(
        widget, to=1.0, duration_ms=duration_ms,
        on_finished=_make_fade_finisher(widget, key, on_finished),
    )
    if anim is None:
        # 极端竞态：内核临时不可用 → 立刻置终态，绝不留 opacity=0 的空白
        _FADE_ACTIVE.pop(key, None)
        try:
            eff.setOpacity(1.0)
        except Exception:
            logger.debug("静默降级：fade_in 中忽略异常", exc_info=True)
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                logger.debug("静默降级：fade_in 中忽略异常", exc_info=True)
        return None

    _FADE_ACTIVE[key] = anim
    return anim


def _make_fade_finisher(widget, key: int, on_finished):
    """构造淡入收尾回调：摘 effect（按压反馈控件除外）+ 透传用户回调。"""
    def _finish() -> None:
        _FADE_ACTIVE.pop(key, None)
        try:
            # 按压反馈控件需长期保留 effect，此处不摘（否则按压缩放失效）
            if not bool(widget.property(_PRESS_PROP)):
                if isinstance(widget.graphicsEffect(), QGraphicsOpacityEffect):
                    widget.setGraphicsEffect(None)
        except Exception:
            logger.debug("静默降级：_finish 中忽略异常", exc_info=True)
        if on_finished is not None:
            try:
                on_finished()
            except Exception:
                logger.debug("静默降级：_finish 中忽略异常", exc_info=True)
    return _finish


# ---------------------------------------------------------------------------
# ② 按压反馈
# ---------------------------------------------------------------------------
class _PressFeedback(QObject):
    """按压反馈事件过滤器 —— **只改 opacity**，不动 geometry / size / font。

    以 ``widget`` 为父对象（C++ 侧随控件销毁）+ 模块级字典强引用（防 Python GC），
    双保险；``widget.destroyed`` 时由 :func:`install_press_feedback` 弹出字典。
    """

    def __init__(self, widget, min_opacity: float, down_ms: int, up_ms: int):
        super().__init__(widget)
        self._widget = widget
        self._min_opacity = float(min_opacity)
        self._down_ms = int(down_ms)
        self._up_ms = int(up_ms)
        self._anim: "Optional[object]" = None

    # -- effect 存取 --------------------------------------------------------
    def _effect(self) -> "Optional[QGraphicsOpacityEffect]":
        try:
            eff = self._widget.graphicsEffect()
        except Exception:
            return None
        return eff if isinstance(eff, QGraphicsOpacityEffect) else None

    def _ensure_effect(self) -> "Optional[QGraphicsOpacityEffect]":
        eff = self._effect()
        if eff is None:
            try:
                eff = QGraphicsOpacityEffect(self._widget)
                self._widget.setGraphicsEffect(eff)
                eff.setOpacity(1.0)
            except Exception:
                return None
        return eff

    # -- 过渡 --------------------------------------------------------------
    def _animate_to(self, target: float, base_ms: int) -> "Optional[object]":
        """把 opacity 过渡到 ``target``；时长/缓动经 motion 收口。"""
        eff = self._ensure_effect()
        if eff is None:
            return None
        _safe_stop(self._anim)
        try:
            start = float(eff.opacity())
        except Exception:
            start = 1.0
        self._anim = motion.animate(
            eff, b"opacity", start, float(target),
            duration_ms=base_ms, easing=motion.easing(),
        )
        if self._anim is None:
            # off 档（运行中切换设置）→ 立即落到终值，绝不停在半透明
            try:
                eff.setOpacity(float(target))
            except Exception:
                logger.debug("静默降级：_animate_to 中忽略异常", exc_info=True)
        return self._anim

    def reset(self) -> None:
        """强制回到不透明终态（off 档 / 指针移出 / 隐藏时兜底调用）。"""
        _safe_stop(self._anim)
        self._anim = None
        eff = self._effect()
        if eff is None:
            return
        try:
            eff.setOpacity(1.0)
        except Exception:
            logger.debug("静默降级：reset 中忽略异常", exc_info=True)

    # -- 事件过滤 ----------------------------------------------------------
    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 回调命名
        try:
            if not _motion_on():
                # 运行中切到 off / 系统关闭动画 → 立即复原，杜绝半透明残留
                self.reset()
                return False
            etype = event.type()
            if etype in _PRESS_EVENTS:
                if _is_left_button(event):
                    self._animate_to(self._min_opacity, self._down_ms)
            elif etype in _RELEASE_EVENTS:
                if _is_left_button(event):
                    self._animate_to(1.0, self._up_ms)
                else:
                    self.reset()
            elif etype in _RESET_EVENTS:
                # 按下后拖出控件再松开 → 收不到 Release，靠 Leave 兜底复原
                self.reset()
        except Exception:
            logger.debug("静默降级：eventFilter 中忽略异常", exc_info=True)
        return False  # 永不吞事件，原有点击逻辑零影响


def install_press_feedback(widget, *, min_opacity: float = _PRESS_MIN_OPACITY,
                           down_ms: int = _PRESS_DOWN_BASE_MS,
                           up_ms: int = _PRESS_UP_BASE_MS):
    """给单个控件安装按压反馈（按下变暗 → 松开复原）。

    Args:
        widget: 目标控件（一般为 ``QPushButton``）。
        min_opacity: 按下时的最低不透明度（``0.72`` = 轻微变暗，克制）。
        down_ms: 按下过渡基准时长（经 ``motion.duration()`` 夹取）。
        up_ms: 松开过渡基准时长（略长于按下，回弹更自然）。

    Returns:
        已安装的过滤器；``off`` 档 / 已安装过 / 控件已有非 opacity 效果时
        返回 ``None``（**不产生任何副作用**）。
    """
    if widget is None or not _motion_on():
        return None
    key = id(widget)
    existing = _PRESS_FILTERS.get(key)
    if existing is not None:
        return existing
    if _has_other_effect(widget):
        return None

    try:
        filt = _PressFeedback(widget, min_opacity, down_ms, up_ms)
        widget.installEventFilter(filt)
        widget.setProperty(_PRESS_PROP, True)
    except Exception:
        return None

    _PRESS_FILTERS[key] = filt
    try:
        widget.destroyed.connect(lambda *_args, k=key: _PRESS_FILTERS.pop(k, None))
    except Exception:
        logger.debug("静默降级：install_press_feedback 中忽略异常", exc_info=True)
    return filt


def uninstall_press_feedback(widget) -> None:
    """卸载 ``widget`` 上的按压反馈并复原不透明度（回退 / 换肤用）。"""
    if widget is None:
        return
    key = id(widget)
    filt = _PRESS_FILTERS.pop(key, None)
    if filt is None:
        return
    try:
        widget.removeEventFilter(filt)
    except Exception:
        logger.debug("静默降级：uninstall_press_feedback 中忽略异常", exc_info=True)
    try:
        filt.reset()
        filt.deleteLater()
    except Exception:
        logger.debug("静默降级：uninstall_press_feedback 中忽略异常", exc_info=True)
    try:
        widget.setProperty(_PRESS_PROP, False)
    except Exception:
        logger.debug("静默降级：uninstall_press_feedback 中忽略异常", exc_info=True)


def install_press_feedback_recursive(root, *, min_opacity: float = _PRESS_MIN_OPACITY,
                                     down_ms: int = _PRESS_DOWN_BASE_MS,
                                     up_ms: int = _PRESS_UP_BASE_MS) -> int:
    """对 ``root`` 下所有按钮（``QPushButton`` 含子类 + ``QToolButton``）批量安装按压反馈。

    Returns:
        实际安装的控件数量（``off`` 档 / 总开关关闭时为 ``0``）。
    """
    if root is None or not _motion_on():
        return 0
    try:
        buttons = [w for t in _PRESS_BUTTON_TYPES for w in root.findChildren(t)]
    except Exception:
        return 0
    if isinstance(root, _PRESS_BUTTON_TYPES) and root not in buttons:
        buttons = buttons + [root]
    count = 0
    for btn in buttons:
        if id(btn) in _PRESS_FILTERS:
            continue  # 已安装 → 幂等跳过，不计入"新增安装数"
        if install_press_feedback(btn, min_opacity=min_opacity,
                                  down_ms=down_ms, up_ms=up_ms) is not None:
            count += 1
    return count


# ---------------------------------------------------------------------------
# ③ 对话框按压反馈（v2.1 P1 铺开）
# ---------------------------------------------------------------------------
class _DialogPressFeedbackFilter(QObject):
    """应用级事件过滤器：任何 ``QDialog`` 显示时自动为其按钮装按压反馈。

    仅**读**事件类型，恒返回 ``False``（绝不吞事件）；已装过的按钮由
    :func:`install_press_feedback` 自身幂等跳过。
    """

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 回调命名
        try:
            if event.type() == QEvent.Show and isinstance(obj, QDialog):
                install_press_feedback_recursive(obj)
        except Exception:
            logger.debug("静默降级：对话框按压反馈中忽略异常", exc_info=True)
        return False


#: 应用级对话框过滤器（强引用防 GC；同一 app 只装一次）
_DIALOG_FILTER: "Optional[_DialogPressFeedbackFilter]" = None


def install_press_feedback_for_dialogs(app=None) -> bool:
    """为「应用级对话框」装按压反馈：任何 ``QDialog`` 显示时自动铺开。

    对话框数量多且多为按需创建，逐个挂载点成本高；改用一个应用级过滤器统一收口。
    幂等：同一 ``app`` 只装一次。``off`` 档 / 无 ``QApplication`` → 不做任何事。

    Returns:
        是否已处于「已安装」状态（已装过 / 本次装上均返回 ``True``）。
    """
    global _DIALOG_FILTER
    if not _motion_on():
        return False
    if _DIALOG_FILTER is not None:
        return True
    if app is None:
        app = QApplication.instance()
    if app is None:
        return False
    try:
        filt = _DialogPressFeedbackFilter(app)
        app.installEventFilter(filt)
    except Exception:
        return False
    _DIALOG_FILTER = filt
    return True
