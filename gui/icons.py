"""码铃矢量图标内核（v2.1 / 设计 D-V21-06 / D-V21-07）。

本模块契约见 ``docs/design-v21.md`` §4.4 —— **改动须先改设计文档**。

单一收口点：全站图标只记「图标名 + 尺寸」，需要 ``QIcon`` 的走
:func:`icon`，需要「文本流内嵌」的走 :func:`font`（控件 QSS 控色）或
:func:`text_glyph`（把字形字符拼进文案流，如按钮标签
``f"{{glyph}} 导出"``，emoji 原样作 ``fallback``）；**禁止落点自己拼
``chr()`` 或硬编码 family / 颜色**（共享知识 §6.9）。图标字体走
``gui/assets/icons/``，**不并入** ``gui/fonts.py`` 的 ``FONT_IDS``；其真实
family 名经 :data:`FONT_FAMILY_NAME` 暴露，供 ``gui/fonts.py`` 的家族链引用
（字体链回退族的唯一真值源，避免字面量散落）。

红线：
  · R-F 零新增运行时第三方依赖（PySide6 内置 + ``gui.*`` + 标准库）；
  · R-P 走 ``QPixmapCache`` 且有界；
  · R-R / I-5 图标集授权四处登记（由域3 落地）。

无 ``QApplication`` 也可安全 import：顶层不创建任何 Qt 对象、不注册字体、
不读配置。

图标集：``ICONSET = "remix_icon"``（Remix Icon 2.5.0，Apache-2.0）；资源与
manifest 由构建期脚本 ``tools/build_icons.py`` 生成（相关构建期工具**仅构建期**，
不进运行时、不进 exe）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from gui.utils import get_resource_path, theme_color

if TYPE_CHECKING:  # 仅类型提示用，运行时不导入（保证无 QApplication 可 import）
    from gui.qt_compat import QFont, QIcon

#: 模块级日志器（R-Q 静默降级统一记 ``debug``：属预期行为、非告警）
logger = logging.getLogger("maid_coder.gui.icons")

# 图标资源在 gui/ 下的相对目录（⚠-2：与 spec datas 目标目录一致）
ICON_DIR_REL = "assets/icons"

# 图标集标识（design §4.4；构建期定稿，随包登记于 docs/THIRD_PARTY.md）
ICONSET = "remix_icon"

# 图标字体真实 family 名（design §4.4；Remix Icon 2.5.0 注册后的
# ``applicationFontFamilies`` 名称）。供 ``gui/fonts.py`` 家族链引用 —— 图标族
# 的唯一真值源，禁止在别处硬编码 "remixicon" 字面量。
# 该字体**不含 ASCII / 数字 / 中文**，作为文字链回退族不会劫持正常字符。
FONT_FAMILY_NAME = "remixicon"

# 构建期产物文件名（tools/build_icons.py 生成）
_FONT_FILE = "maling_icons.ttf"
_MANIFEST_FILE = "icons_manifest.json"

# 无活动主题引擎时的中性兜底色（正常路径一律走 theme_color 取活动色板）
_FALLBACK_TEXT_COLOR = "#000000"

# QPixmapCache 键追踪上限（缓存本身按字节限额有界；此处只界追踪表大小）
_MAX_TRACKED_KEYS = 512

# --- 运行时状态（不在顶层创建 Qt 对象）--------------------------------------
_registered_family: Optional[str] = None
_manifest: Dict[str, int] = {}
_app_ctx = None
_subscribed = False
_cache_keys: List[str] = []


# ---------------------------------------------------------------------------
# 资源与 manifest（纯逻辑，无 Qt）
# ---------------------------------------------------------------------------
def _asset_path(filename: str) -> Optional[Path]:
    """解析图标资源路径（frozen 态 = _MEIPASS/assets/icons/...，源码态 = gui/assets/icons/...）。"""
    try:
        return Path(get_resource_path(f"{ICON_DIR_REL}/{filename}"))
    except Exception:
        return None


def _load_manifest() -> Dict[str, int]:
    """读取并校验 ``icons_manifest.json``（名称 → 码位）；失败返回空字典。"""
    path = _asset_path(_MANIFEST_FILE)
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for name, codepoint in raw.items():
        if isinstance(name, str) and isinstance(codepoint, int) and codepoint > 0:
            out[name] = codepoint
    return out


def _ensure_manifest() -> Dict[str, int]:
    """惰性加载 manifest（首次使用时读一次；纯文件读取，不建 Qt 对象）。"""
    global _manifest
    if _manifest:
        return _manifest
    _manifest = _load_manifest()
    return _manifest


def _current_theme_name() -> str:
    engine = getattr(_app_ctx, "theme_engine", None) if _app_ctx is not None else None
    if engine is None:
        return ""
    try:
        return str(engine.current_theme_name() or "")
    except Exception:
        return ""


def _device_pixel_ratio() -> float:
    """当前屏幕 devicePixelRatio（取不到回落 1.0 → 高 DPI 下由 setDevicePixelRatio 适配）。"""
    try:
        from gui.qt_compat import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            if screen is not None:
                return float(screen.devicePixelRatio() or 1.0)
    except Exception:
        logger.debug("读取 devicePixelRatio 失败，回落 1.0", exc_info=True)
    return 1.0


def _track_key(key: str) -> None:
    _cache_keys.append(key)
    if len(_cache_keys) > _MAX_TRACKED_KEYS:
        del _cache_keys[: len(_cache_keys) - _MAX_TRACKED_KEYS]


# ---------------------------------------------------------------------------
# 注册 / 查询
# ---------------------------------------------------------------------------
def register_icon_font() -> Optional[str]:
    """把图标字体注册进 Qt，返回**真实 family**（``applicationFontFamilies``）。

    失败（缺文件 / 无 Qt / 注册失败）返回 ``None``，不抛。
    """
    global _registered_family, _manifest
    if _registered_family is not None:
        return _registered_family
    try:
        from gui.qt_compat import QFontDatabase
    except Exception:
        return None

    path = _asset_path(_FONT_FILE)
    if path is None or not path.exists():
        return None
    try:
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id == -1:
            return None
        families = QFontDatabase.applicationFontFamilies(font_id) or []
        if not families:
            return None
    except Exception:
        return None

    _registered_family = families[0]
    _manifest = _load_manifest()
    return _registered_family


def available() -> bool:
    """图标字体已注册且 manifest 加载成功。"""
    if _registered_family is None:
        return False
    return bool(_ensure_manifest())


def has(name: str) -> bool:
    """该图标名是否在 manifest 中。"""
    return isinstance(name, str) and name in _ensure_manifest()


def glyph(name: str) -> Optional[str]:
    """名称 → 字形字符（``chr(codepoint)``）；未知名返回 ``None``。"""
    codepoint = _ensure_manifest().get(name) if isinstance(name, str) else None
    if not isinstance(codepoint, int) or codepoint <= 0:
        return None
    try:
        return chr(codepoint)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def icon(name: str, size: int = 16, color: Optional[str] = None) -> "QIcon":
    """**主 API**：渲染图标为 ``QIcon``。

    ``color=None`` 时取活动色板 ``text``（``theme_color``）；``QPainter`` 把字形
    画进 ``QPixmap``（``setDevicePixelRatio`` 适配高 DPI）；结果进 ``QPixmapCache``
    （键 = ``f"{name}|{size}|{color}|{theme}"``）。
    """
    try:
        from gui.qt_compat import QColor, QFont, QIcon, QPainter, QPixmap, QPixmapCache, Qt
    except Exception:  # 无 Qt：静默降级（调用方应已用 available() 判断）
        return None  # type: ignore[return-value]

    if not available() or not has(name):
        return QIcon()

    char = glyph(name)
    if not char:
        return QIcon()

    try:
        px_size = max(1, int(round(float(size))))
    except Exception:
        px_size = 16

    if color is None:
        color = theme_color(_app_ctx, "text", _FALLBACK_TEXT_COLOR)
    color = str(color or _FALLBACK_TEXT_COLOR)
    cache_key = f"{name}|{px_size}|{color}|{_current_theme_name()}"

    cached = QPixmapCache.find(cache_key)
    if isinstance(cached, QPixmap) and not cached.isNull():
        return QIcon(cached)

    dpr = _device_pixel_ratio()
    device = max(1, int(round(px_size * dpr)))
    pixmap = QPixmap(device, device)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    try:
        font = QFont(_registered_family or "")
        font.setPixelSize(device)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, char)
    finally:
        painter.end()
    pixmap.setDevicePixelRatio(dpr)

    QPixmapCache.insert(cache_key, pixmap)
    _track_key(cache_key)
    return QIcon(pixmap)


def font(size: int = 16) -> "QFont":
    """**次 API**：把图标当文本嵌入时返回设好 family / pixelSize 的 ``QFont``；
    颜色由控件 QSS ``color`` 控制。
    """
    try:
        from gui.qt_compat import QFont
    except Exception:  # 无 Qt
        return None  # type: ignore[return-value]
    qfont = QFont()
    if _registered_family:
        qfont.setFamily(_registered_family)
    try:
        qfont.setPixelSize(max(1, int(size)))
    except Exception:
        logger.debug("设置图标字体 pixelSize 失败，沿用默认", exc_info=True)
    return qfont


def text_glyph(name: str, fallback: str) -> str:
    """**文本内嵌便捷入口**：返回可拼进文案流的字形字符。

    语义：图标字体可用（:func:`available`）且 :func:`has` 为真时返回
    :func:`glyph`（PUA 字形字符），否则原样返回 ``fallback``。

    **fallback 约定**：调用方把原 emoji（如 ``"📄 导出"`` 里的 ``"📄"``）作为
    ``fallback`` 传入 —— 图标字体缺资源 / 未注册时文案自动退化为 emoji，
    不空白、不崩（R-K/R-Q 精神）。**不得删除 emoji 字面量**，它是唯一的
    兜底文案来源。

    颜色由承载控件的 QSS ``color`` 控制（与 :func:`font` 同源），字形随主题色
    统一、任意缩放不糊。

    顶层不建 Qt 对象、不注册字体、不读配置，无 ``QApplication`` 也可安全调用。
    """
    if available() and has(name):
        char = glyph(name)
        if char:
            return char
    return fallback


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
def _on_theme_changed(_theme_name: str = "") -> None:
    """换肤 / 深浅切换 → 清图标缓存（下次按新色重新渲染）。"""
    clear_cache()


def configure(app_ctx) -> None:
    """启动期注入 ``app_ctx`` 以便 ``icon()`` 取活动色板；订阅 ``theme_changed``
    清缓存（换肤 / 深浅切换后图标重新按新色渲染）。
    """
    global _app_ctx, _subscribed
    _app_ctx = app_ctx
    if _subscribed:
        return
    engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
    if engine is None:
        return
    try:
        signal = getattr(engine, "theme_changed", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(_on_theme_changed)
            _subscribed = True
    except Exception:
        logger.debug("订阅 theme_changed 失败，图标缓存换肤后不自动清空", exc_info=True)


def clear_cache() -> None:
    """清 ``QPixmapCache`` 中图标键（测试 / 换肤用）。"""
    try:
        from gui.qt_compat import QPixmapCache
    except Exception:
        _cache_keys.clear()
        return
    for key in _cache_keys:
        try:
            QPixmapCache.remove(key)
        except Exception:
            continue
    _cache_keys.clear()


def _reset_state() -> None:
    """仅供测试：复位注册态 / manifest / 订阅标记 / 键追踪（不触碰 ``QPixmapCache``）。"""
    global _registered_family, _manifest, _app_ctx, _subscribed
    _registered_family = None
    _manifest = {}
    _app_ctx = None
    _subscribed = False
    _cache_keys.clear()
