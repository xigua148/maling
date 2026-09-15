"""投影层次（elevation）试点 —— 主界面「扁平 → 有层次」的唯一收口。

**为什么需要这一层**

Qt 的 QSS **不支持** ``box-shadow``（见 ``gui/themes/base.qss`` 第 10 节注释），
``THEME_DEFINITIONS`` 里定义的 14 处 ``shadow`` 变量在 QSS 中 **0 引用**。
真正的模糊投影只能由代码侧 ``QGraphicsDropShadowEffect`` 承担，而改动前
主界面（首页 / 设置页）**0 处**投影 —— 这是"整体观感廉价"的根因之一。

本模块把「读主题 ``shadow`` 变量 → 解析 CSS box-shadow → 换算成 Qt 参数 →
挂 ``QGraphicsDropShadowEffect`` → 换肤后刷新颜色」这条链路收口成一个模块，
业务侧"改一处"即可全局生效/回滚。

**设计纪律**
  · **取色一律走 ``ThemeEngine.get_color("shadow", ...)``**，禁止硬编码颜色；
  · 主题缺 ``shadow`` / 值非法 / 无 ``theme_engine`` → **静默跳过**（不装、不报错、
    界面完全正常），与项目 "R-Q 静默降级" 一致；
  · **不引入** 任何第三方依赖（R-F 红线），只用 PySide6 内置 + 标准库；
  · **不改字号**（``setPointSize`` / ``setPixelSize`` 一律不碰）；
  · 无 ``QApplication`` 也可安全 import：顶层不创建任何 Qt 对象；
  · 容器里已挂 ``QGraphicsOpacityEffect`` 的控件（动效层 ``gui.transitions``）
    本层**不接管**，反之亦然 —— 两类效果互斥，避免互相覆盖。

**挂载范围（试点，刻意收窄）**
  见报告 ``_elevation_pilot_report.md``；当前共 5 处（首页房间卡 + 3 张状态卡 +
  设置页「外观与效果」分区）。消息气泡（数量可达上百）**本轮不做**，理由见报告
  性能评估一节。

**总开关**：模块级 :data:`ENABLED` 置 ``False`` 即整体不装（快速 A/B 对比用）。
"""
from __future__ import annotations

import logging
import re
import weakref
from typing import Any, Optional, Tuple

from gui.qt_compat import QColor, QGraphicsDropShadowEffect

#: 模块级日志器（R-Q 静默降级统一记 ``debug``：属预期行为、非告警）
logger = logging.getLogger("maid_coder.gui.elevation")

__all__ = [
    "ENABLED",
    "SHADOW_KEY",
    "parse_css_shadow",
    "qt_blur_radius",
    "current_shadow",
    "apply_card_shadow",
    "remove_card_shadow",
    "refresh_all",
    "bind_theme_engine",
    "mounted_count",
]

# ---------------------------------------------------------------------------
# 总开关（置 False → 全模块退化为 no-op，便于快速对比效果 / 免打包回退）
# ---------------------------------------------------------------------------
ENABLED: bool = True

#: 主题色板里的投影键名（``THEME_DEFINITIONS[*]["colors"]["shadow"]``）
SHADOW_KEY: str = "shadow"

# ---------------------------------------------------------------------------
# CSS box-shadow → Qt 的换算常量
# ---------------------------------------------------------------------------
# ⚠ 换算依据（**不要随手改**，改动前先读完这段）：
#   CSS 规范（css-backgrounds-3）：box-shadow 的 blur-radius 指「阴影边缘过渡区
#   的**直径**的一半」难以直接对应，工程上通用结论是 **blur-radius ≈ 2 × 高斯
#   标准差 stdDev**（即 CSS 的模糊半径约为高斯核 stdDev 的两倍）。
#   Qt 侧 ``QGraphicsDropShadowEffect::setBlurRadius(r)`` 的 r 直接喂给内部高斯
#   模糊的 **stdDev**（Qt 源码 qt_blurImage 走的是指数模糊，r 即等效 stdDev）。
#   ⇒ 同一视觉效果的换算为 **qt_blur = css_blur / 2**。
#   例：CSS "0 6px 20px rgba(...)" → Qt blurRadius = 10、offset = (0, 6)。
_CSS_BLUR_TO_QT_BLUR: float = 0.5

#: Qt blurRadius 下限（px）。CSS "0 1px 3px" → qt=1.5，已足够小；兜底防 0。
_MIN_QT_BLUR: float = 1.0

#: 值里**只有颜色没有几何**时（如旧主题 "rgba(255,182,193,0.15)"）的缺省几何。
_DEFAULT_OFFSET_X: float = 0.0
_DEFAULT_OFFSET_Y: float = 1.0
_DEFAULT_CSS_BLUR: float = 3.0

#: alpha 下限（0~1）。CSS 里 0.05 的阴影在 Qt 8-bit 合成下量化到 13/255，
#: 视觉上几乎不可见；试点期给一个下限保证"层次看得见"。
#: **置 0.0 即 100% 忠实主题值**（想完全尊重主题作者意图时改这里，勿删本注释）。
_MIN_ALPHA: float = 0.08

#: 层级倍率：1=卡片、2=抬升（弹层/悬浮）、3=顶层（对话框）
_LEVEL_SCALE: dict = {1: 1.0, 2: 1.6, 3: 2.4}

# ---------------------------------------------------------------------------
# CSS 解析用的正则
# ---------------------------------------------------------------------------
# rgba(0,0,0,0.05) / rgb(0,0,0) —— alpha 支持 "0.5" 与 "50%" 两种写法
_RGBA_RE = re.compile(
    r"rgba?\s*\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*"
    r"(?:\s*[,/]\s*([0-9]*\.?[0-9]+%?)\s*)?\)",
    re.IGNORECASE,
)
# #RGB / #RRGGBB / #RRGGBBAA
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
# 长度数值（px/pt/em/rem 后缀可选；box-shadow 不支持百分比长度，忽略单位按 px 计）
_LENGTH_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:px|pt|em|rem)?", re.IGNORECASE)
# 关键字：inset 无法用 drop shadow 表达；none/transparent 直接跳过
_INSET_RE = re.compile(r"\binset\b", re.IGNORECASE)
_SKIP_VALUES = {"none", "transparent", "initial", "unset", "0", "0px"}


# ---------------------------------------------------------------------------
# ① CSS box-shadow 解析
# ---------------------------------------------------------------------------
def _color_from_rgba(match: "re.Match") -> Optional[QColor]:
    """由 :data:`_RGBA_RE` 的匹配结果构造 ``QColor``；越界/非法返回 ``None``。"""
    try:
        r = int(match.group(1))
        g = int(match.group(2))
        b = int(match.group(3))
    except Exception:
        return None
    if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
        return None
    color = QColor(r, g, b)
    raw_alpha = match.group(4)
    if raw_alpha:
        text = raw_alpha.strip()
        try:
            if text.endswith("%"):
                alpha = float(text[:-1]) / 100.0
            else:
                alpha = float(text)
                # CSS 传统写法里 alpha 偶尔出现 0~255（非规范），与 0~1 区分
                if alpha > 1.0:
                    alpha = alpha / 255.0
        except Exception:
            alpha = 1.0
        color.setAlphaF(min(1.0, max(0.0, alpha)))
    return color if color.isValid() else None


def parse_css_shadow(value: Any) -> Optional[Tuple[float, float, float, QColor]]:
    """解析 CSS ``box-shadow`` 字符串（**只取第一段外阴影**）。

    支持形态：
      · ``"0 1px 3px rgba(0,0,0,0.05)"``  → ``(0.0, 1.0, 3.0, QColor)``
      · ``"0 6px 20px rgba(255,143,163,0.13)"`` → ``(0.0, 6.0, 20.0, QColor)``
      · ``"rgba(255,182,193,0.15)"``（**只有颜色没有几何**，旧主题）
        → 用缺省几何 ``(0.0, 1.0, 3.0, QColor)``
      · ``"#00000033"`` / ``"rgb(0,0,0)"`` 亦可

    Args:
        value: 主题 ``shadow`` 变量的原始值；非字符串 / 空串 / ``"none"`` 一律跳过。

    Returns:
        ``(offset_x, offset_y, blur_radius, color)``；**blur_radius 是 CSS 语义**
        （≈2×stdDev），**不能直接喂给** ``setBlurRadius`` —— 请先经
        :func:`qt_blur_radius` 换算。无法解析（没有合法颜色 / inset 内阴影 /
        ``none``）时返回 ``None``，**不抛异常**。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in _SKIP_VALUES:
        return None
    if _INSET_RE.search(text):
        # inset 是内阴影，QGraphicsDropShadowEffect 表达不了 → 静默跳过
        return None

    # ① 取颜色（必须成功，否则整条跳过 —— 无颜色就没法画阴影）
    color: Optional[QColor] = None
    rest = text
    m_rgba = _RGBA_RE.search(text)
    if m_rgba is not None:
        color = _color_from_rgba(m_rgba)
        rest = text[: m_rgba.start()] + " " + text[m_rgba.end():]
    if color is None:
        m_hex = _HEX_RE.search(text)
        if m_hex is not None:
            candidate = QColor(m_hex.group(0))
            if candidate.isValid():
                color = candidate
                rest = text[: m_hex.start()] + " " + text[m_hex.end():]
    if color is None or not color.isValid():
        return None

    # ② 取几何（把颜色片段剔除后再扫数字，避免把 rgba() 里的通道值当成长度）
    nums = [float(n) for n in _LENGTH_RE.findall(rest)]
    if len(nums) >= 3:
        off_x, off_y, css_blur = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        off_x, off_y, css_blur = nums[0], nums[1], _DEFAULT_CSS_BLUR
    elif len(nums) == 1:
        off_x, off_y = _DEFAULT_OFFSET_X, _DEFAULT_OFFSET_Y
        css_blur = nums[0]
    else:
        # 只有颜色没有几何（旧主题 "rgba(255,182,193,0.15)"）→ 缺省几何
        off_x, off_y = _DEFAULT_OFFSET_X, _DEFAULT_OFFSET_Y
        css_blur = _DEFAULT_CSS_BLUR

    # blur 不允许为负（CSS 规范：负值非法，等同 0）
    if css_blur < 0:
        css_blur = 0.0
    return (off_x, off_y, css_blur, color)


def qt_blur_radius(css_blur: float) -> float:
    """CSS ``blur-radius`` → Qt ``QGraphicsDropShadowEffect.setBlurRadius()``。

    换算：**qt = css / 2**（依据见 :data:`_CSS_BLUR_TO_QT_BLUR` 的注释），
    并夹到下限 :data:`_MIN_QT_BLUR`（0 会让 Qt 退化成硬边矩形，比没有还难看）。
    """
    try:
        value = float(css_blur) * _CSS_BLUR_TO_QT_BLUR
    except Exception:
        value = _DEFAULT_CSS_BLUR * _CSS_BLUR_TO_QT_BLUR
    if value < _MIN_QT_BLUR:
        value = _MIN_QT_BLUR
    return value


# ---------------------------------------------------------------------------
# ② 当前主题的 shadow 取值
# ---------------------------------------------------------------------------
def current_shadow(engine: Any = None) -> Optional[Tuple[float, float, float, QColor]]:
    """读当前活动主题的 ``shadow`` 变量并解析；缺失/非法返回 ``None``（静默）。

    Args:
        engine: ``ThemeEngine`` 实例；``None`` 时用模块级已绑定的引擎。

    .. note::
        ``ThemeEngine.get_color(key, fallback)`` 在 fallback 为 ``None`` 时会回落到
        ``"#000000"``，故这里传 **空串** 作为"缺失"哨兵值（见主题引擎实现）。
    """
    eng = engine if engine is not None else _ENGINE
    if eng is None:
        return None
    getter = getattr(eng, "get_color", None)
    if not callable(getter):
        return None
    try:
        raw = getter(SHADOW_KEY, "")
    except Exception:
        return None
    if not raw or not isinstance(raw, str):
        return None
    try:
        return parse_css_shadow(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ③ 模块级登记（弱引用，随控件销毁自动回收）
# ---------------------------------------------------------------------------
class _Entry:
    """一条挂载记录：控件弱引用 + effect 强引用 + 层级。"""

    __slots__ = ("widget", "effect", "level")

    def __init__(self, widget, level: int, key: int):
        # 控件销毁即回调 finalizer，杜绝 id 复用导致的登记错配
        self.widget = weakref.ref(widget, self._make_finalizer(key))
        self.effect: Optional[QGraphicsDropShadowEffect] = None
        self.level: int = level

    @staticmethod
    def _make_finalizer(key: int):
        def _finalize(_ref=None):
            _REGISTRY.pop(key, None)

        return _finalize


#: id(widget) -> _Entry
_REGISTRY: "dict[int, _Entry]" = {}

#: 已绑定的主题引擎（``theme_changed`` 信号源）
_ENGINE: Any = None
_BOUND_ENGINE_ID: Optional[int] = None


def _configure_effect(effect: QGraphicsDropShadowEffect,
                      parsed: Tuple[float, float, float, QColor],
                      level: int) -> None:
    """把解析结果按层级写进 effect（不创建/不挂载，只写参数）。"""
    off_x, off_y, css_blur, color = parsed
    scale = _LEVEL_SCALE.get(level, 1.0)

    effect.setBlurRadius(qt_blur_radius(css_blur) * scale)
    effect.setOffset(off_x * scale, off_y * scale)

    # alpha 下限：见 _MIN_ALPHA 注释（置 0 即完全忠实主题值）
    alpha = color.alphaF()
    if _MIN_ALPHA > 0.0 and 0.0 < alpha < _MIN_ALPHA:
        color = QColor(color)
        color.setAlphaF(_MIN_ALPHA)
    effect.setColor(color)


def _apply_entry(entry: _Entry,
                 parsed: Optional[Tuple[float, float, float, QColor]]) -> bool:
    """把（可能为空的）解析结果落到 entry 所指控件上；失败一律静默返回 ``False``。"""
    widget = entry.widget()
    if widget is None:
        return False
    try:
        if parsed is None:
            # 主题无 shadow（或新主题非法）→ 摘掉，绝不残留旧色
            widget.setGraphicsEffect(None)
            entry.effect = None
            return False
        if entry.effect is None:
            entry.effect = QGraphicsDropShadowEffect(widget)
            widget.setGraphicsEffect(entry.effect)
        _configure_effect(entry.effect, parsed, entry.level)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# ④ 对外 API
# ---------------------------------------------------------------------------
def bind_theme_engine(engine: Any) -> bool:
    """绑定主题引擎并订阅 ``theme_changed``（幂等；换肤后自动刷新阴影颜色）。

    不绑定也能装阴影，只是**换肤后颜色不会更新**（会残留旧主题的阴影色）。

    Args:
        engine: ``ThemeEngine`` 实例（有 ``theme_changed`` 信号）。

    Returns:
        绑定成功返回 ``True``；``engine`` 为空 / 无信号 / 连接失败返回 ``False``。
    """
    global _ENGINE, _BOUND_ENGINE_ID
    if engine is None:
        return False
    signal = getattr(engine, "theme_changed", None)
    if signal is None or not hasattr(signal, "connect"):
        return False
    _ENGINE = engine
    if _BOUND_ENGINE_ID == id(engine):
        return True
    try:
        signal.connect(_on_theme_changed)
        _BOUND_ENGINE_ID = id(engine)
        return True
    except Exception:
        return False


def _on_theme_changed(theme_name: str = "") -> None:
    """``theme_changed`` 槽：换肤后把已挂阴影的颜色/几何整体刷新一遍。"""
    try:
        refresh_all(theme_name)
    except Exception:
        logger.debug("换肤后刷新投影失败，已静默忽略", exc_info=True)


def apply_card_shadow(widget, *, level: int = 1,
                      engine: Any = None, app_ctx: Any = None) -> bool:
    """给 ``widget`` 装一层投影，参数取自**当前活动主题**的 ``shadow`` 变量。

    典型用法（页面里 ``app_ctx`` 已注入）::

        from gui import elevation
        elevation.apply_card_shadow(self.room_card, level=1, app_ctx=self.app_ctx)

    Args:
        widget: 目标控件（``QWidget``）。
        level: 层级档位 —— 1=卡片（基准）、2=抬升（弹层/悬浮）、3=顶层（对话框）；
               非法值回落 1。
        engine: 显式指定 ``ThemeEngine``；缺省按 ``app_ctx.theme_engine`` 取。
        app_ctx: 应用上下文（``engine`` 为空时从它身上取 ``theme_engine``）。

    Returns:
        装上返回 ``True``；总开关关闭 / 无引擎 / 主题无 ``shadow`` / 解析失败 /
        控件已有其它图形效果 → 返回 ``False`` 且 **无任何副作用**（静默跳过）。
    """
    if widget is None or not ENABLED:
        return False
    try:
        level = int(level)
    except Exception:
        level = 1
    if level not in _LEVEL_SCALE:
        level = 1

    if engine is None and app_ctx is not None:
        engine = getattr(app_ctx, "theme_engine", None)
    if engine is not None:
        bind_theme_engine(engine)
    eng = engine if engine is not None else _ENGINE

    parsed = current_shadow(eng)
    if parsed is None:
        return False

    try:
        # 已有动效层 opacity effect（或其它效果）→ 不接管，避免互相覆盖
        existing = widget.graphicsEffect()
    except Exception:
        return False
    if existing is not None and not isinstance(existing, QGraphicsDropShadowEffect):
        return False

    key = id(widget)
    entry = _REGISTRY.get(key)
    if entry is None or entry.widget() is not widget:
        entry = _Entry(widget, level, key)
        _REGISTRY[key] = entry
    else:
        entry.level = level
    return _apply_entry(entry, parsed)


def remove_card_shadow(widget) -> bool:
    """摘掉 ``widget`` 上的投影并注销登记（幂等；用于页面重建 / 手动回退）。"""
    if widget is None:
        return False
    key = id(widget)
    entry = _REGISTRY.pop(key, None)
    if entry is None:
        return False
    try:
        widget.setGraphicsEffect(None)
    except Exception:
        return False
    entry.effect = None
    return True


def refresh_all(theme_name: str = "") -> int:
    """换肤后刷新**全部**已挂阴影（颜色 + 几何），防止残留旧主题色。

    Args:
        theme_name: 主题名（``theme_changed`` 信号参数）；本实现不需要区分主题，
                    仅保留参数以对齐信号签名并便于日志排查。

    Returns:
        成功刷新的数量（主题无 ``shadow`` 时为 0 —— 此时所有已挂阴影会被摘掉）。
    """
    parsed = current_shadow()
    count = 0
    for key in list(_REGISTRY.keys()):
        entry = _REGISTRY.get(key)
        if entry is None:
            continue
        if entry.widget() is None:
            _REGISTRY.pop(key, None)
            continue
        if _apply_entry(entry, parsed):
            count += 1
    return count


def mounted_count() -> int:
    """当前登记（且控件仍存活）的投影数量 —— 自测 / A-B 对比用。"""
    alive = 0
    for key in list(_REGISTRY.keys()):
        entry = _REGISTRY.get(key)
        if entry is None or entry.widget() is None:
            _REGISTRY.pop(key, None)
            continue
        alive += 1
    return alive
