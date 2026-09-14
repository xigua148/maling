"""码铃形象资产管线（B1）—— MaidAssets 加载器 + QPainter 占位脸回退 + MaidAvatar 控件。

约定（docs/design-v12.md D6）：
  - 资产目录 `gui/assets/maid/`，清单 `manifest.json`，8 表情 PNG 文件名 = 表情 id；
  - PNG 缺失 / 损坏（QImage 解码失败 / 空图）时的形象策略（v1.2x 用户拍板：
    「先去掉小兽小人的程序占位画，等美术插画到位再启用」）：
      * 默认 `PLACEHOLDER_ENABLED = False` —— **不渲染程序绘制的占位脸**，
        `pixmap_for()/rounded()` 返回 None，由消费端（聊天气泡 🌸、角落宠物 🔔、
        侧栏 🔔 文本、首页形象卡中性铃铛）提供中性兜底；UI 永不空白、
        永不出现程序画的假脸/假兽；
      * `PLACEHOLDER_ENABLED = True` 可临时预览占位绘制（仅调试用）；
  - 美术 PNG 到位后自动启用真形象，无需改代码（加载器按文件名即取即用）；
  - 统一 API：`MaidAvatar.set_maid_expression(name)` / `expression()`；
    主形象缩略 / 圆形裁剪供气泡 / 微型档复用（QPainter clip）。

防御式设计：PySide6 未安装时本模块仍可 import（纯决策函数可用，
`QT_OK=False`），MaidAvatar 相关类降级为 None / 占位，GUI 层用 getattr 守卫跳过。

本模块刻意把「缺图判定 / 表情回退决策」做成不依赖 Qt 的纯函数，
便于在无 PySide6 的开发机上自测缺图回退分支。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

# companion（纯 stdlib）提供心情态 -> 表情的权威集合，避免两处漂移
from companion import ACTIVITY_STATES, EXPRESSION_IDS, MOOD_IDS, MOOD_TO_EXPRESSION
from gui.utils import get_resource_path

_logger = logging.getLogger("maid_coder.gui.maid_avatar")

# 常量集合兜底：即使 manifest 缺失 / 损坏，8 态表情仍可用
FALLBACK_EXPRESSIONS = ["normal", "happy", "thinking", "focus",
                        "concerned", "shy", "tired", "surprised"]
EXPRESSIONS = EXPRESSION_IDS  # 与 companion 单一来源一致（8 态）

# 占位脸默认主题色（未来可扩；占位画只用它，UI 主色走 theme_color）
_PLACEHOLDER_COLORS = {
    "bg": "#FFE9EF",        # 底色块（软粉）
    "face": "#FFE0D6",      # 肤色
    "face_stroke": "#E8B4B8",
    "line": "#8A5A5A",      # 眉眼嘴线
    "bell": "#F4C430",      # 铃铛金
    "blush": "rgba(255,150,150,0.55)",
    "ring": "#FFFFFF",      # 内圈
}

MANIFEST_NAME = "manifest.json"

# v1.2x：真插画就绪前的形象策略 —— 默认不显示程序绘制的占位脸/兽（用户拍板
# 「先去掉小兽小人，画好真图再启用」）。置 True 仅用于调试/预览占位绘制。
PLACEHOLDER_ENABLED = False


def asset_dir() -> Path:
    """返回 maid 资产目录路径（frozen 与源码两种模式下均正确）。"""
    return get_resource_path("assets/maid")


# ---------------------------------------------------------------------------
# 纯决策层（无 Qt 依赖，可独立自测）
# ---------------------------------------------------------------------------
def load_manifest(assets_dir: Optional[Path] = None) -> dict:
    """读取并校验 manifest；缺失/损坏时返回含兜底 8 态的默认结构，绝不抛异常。"""
    directory = Path(assets_dir) if assets_dir else asset_dir()
    default = {
        "schema_version": 1,
        "version": 1,
        "expressions": list(FALLBACK_EXPRESSIONS),
        "moods": list(MOOD_IDS),
        "activity_states": list(ACTIVITY_STATES),
        "themes": ["default"],
    }
    try:
        mf = directory / MANIFEST_NAME
        if not mf.exists():
            return default
        with open(mf, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return default
        exprs = data.get("expressions")
        if not isinstance(exprs, list) or not exprs:
            data["expressions"] = default["expressions"]
        return data
    except Exception as exc:
        _logger.warning("maid manifest 读取失败，使用兜底清单: %s", exc)
        return default


def missing_asset_ids(assets_dir: Optional[Path] = None) -> List[str]:
    """返回「缺失或 0 字节」的表情 id 列表（不依赖 Qt 的存在性判定）。

    损坏判定（文件存在但 QImage 解码失败）需 Qt，见 MaidAssets.expression_missing。
    """
    directory = Path(assets_dir) if assets_dir else asset_dir()
    manifest = load_manifest(directory)
    missing: List[str] = []
    for exp in manifest.get("expressions", FALLBACK_EXPRESSIONS):
        png = directory / f"{exp}.png"
        if not png.exists() or png.stat().st_size <= 0:
            missing.append(exp)
    return missing


def resolve_expression(name: str, known: Optional[list] = None) -> str:
    """把任意输入规范化为合法表情 id；未知一律回落 normal（含 None/空/大小写容错）。"""
    if not isinstance(name, str):
        return "normal"
    cand = name.strip().lower()
    pool = list(known) if known else EXPRESSIONS
    if cand in pool:
        return cand
    return "normal"


def expression_known(name: str) -> bool:
    return isinstance(name, str) and name.strip().lower() in EXPRESSIONS


def mood_to_expression(state: Optional[str]) -> str:
    """mood/活动态 -> 表情 id。心情态 + 活动态全在 8 态集合内，恒等映射。"""
    if state is None:
        return "normal"
    key = str(state).strip().lower()
    return MOOD_TO_EXPRESSION.get(key, "normal")


# ---------------------------------------------------------------------------
# Qt 层：占位脸绘制 + MaidAssets 加载器 + MaidAvatar 控件（防御式 import）
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import Qt, QRectF, QSize
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
    from PySide6.QtWidgets import QWidget
    QT_OK = True
except Exception:  # PySide6 未安装：控件降级，模块仍可 import
    QT_OK = False
    QPixmap = None  # type: ignore
    QPainter = None  # type: ignore
    QWidget = None  # type: ignore

# 动态基类：QT_OK=False 时 MaidAvatar 降级为普通类（仅防误实例化时抛错，
# 类定义本身不再因 None 基类崩溃）
_MaidAvatarBase = QWidget if QT_OK else object


def _color(v: str, alpha: int = 255) -> QColor:
    """解析 '#RRGGBB' 或 'rgba(r,g,b,a)' 颜色；失败回落灰。仅在 Qt 可用时调用。"""
    col = QColor(v)
    if col.isValid():
        if alpha != 255:
            col.setAlpha(alpha)
        return col
    return QColor(180, 180, 180)


class PlaceholderFacePainter:
    """QPainter 程序绘制的 Q 版占位脸：底色块 + 铃铛符号 + 按表情 ID 画眉眼/嘴型。

    使用相对坐标（cx, cy, r），可被任意尺寸复用。表情必须能一眼区分。
    """

    # 表情 -> 眉 / 眼 / 嘴 的画法 key（几何绘制集中在 _paint_face 内）
    EYE_STYLES = {"normal": "dot", "happy": "arc_up", "concerned": "dot_tilt",
                  "shy": "dot_side", "tired": "line", "thinking": "dot_up",
                  "focus": "dot_focus", "surprised": "round"}
    BROW_STYLES = {"concerned": "worried", "focus": "flat", "tired": "gentle",
                   "thinking": "raised", "surprised": "raised"}
    MOUTH_STYLES = {"normal": "smile", "happy": "open_smile", "concerned": "flat",
                    "shy": "small", "tired": "small_o", "thinking": "smile",
                    "focus": "flat", "surprised": "oh"}

    @classmethod
    def draw(cls, painter: "QPainter", cx: float, cy: float, r: float,
             expression_id: str) -> None:
        """以 (cx, cy) 为脸中心、r 为半径绘制一个 Q 版占位脸。"""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        exp = resolve_expression(expression_id)

        # 底色块：圆角方块（比脸略大一圈的软粉底，模拟头像底板）
        box = QRectF(cx - r * 1.25, cy - r * 1.25, r * 2.5, r * 2.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("#FFC9D8"))
        painter.drawRoundedRect(box, r * 0.5, r * 0.5)

        # 脸：肤色圆
        painter.setBrush(_color(_PLACEHOLDER_COLORS["face"]))
        painter.setPen(QPen(_color(_PLACEHOLDER_COLORS["face_stroke"]), max(1.0, r * 0.03)))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 铃铛符号（发饰）：头顶小金铃 + 一条铃绳
        cls._draw_bell(painter, cx, cy - r * 0.95, r)

        # 表情细节（眉眼嘴）
        painter.setPen(QPen(_color(_PLACEHOLDER_COLORS["line"]), max(1.2, r * 0.045),
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cls._paint_face(painter, cx, cy, r, exp)
        painter.restore()

    # -- 内部几何 --
    @staticmethod
    def _draw_bell(painter: "QPainter", x: float, y: float, r: float) -> None:
        br = r * 0.18
        painter.save()
        painter.setPen(QPen(_color(_PLACEHOLDER_COLORS["bell"]), max(1.0, r * 0.03)))
        painter.setBrush(_color(_PLACEHOLDER_COLORS["bell"]))
        # 铃身（半圆下接小圆）与中缝线
        painter.drawEllipse(QRectF(x - br, y - br, br * 2, br * 2))
        painter.setPen(QPen(_color("#B8860B"), max(0.8, r * 0.025)))
        painter.drawArc(QRectF(x - br, y - br * 0.4, br * 2, br * 2), 180 * 16, 180 * 16)
        painter.restore()

    @classmethod
    def _paint_face(cls, painter: "QPainter", cx: float, cy: float, r: float, exp: str) -> None:
        eye_dx = r * 0.32
        eye_y = cy - r * 0.15
        eye_r = r * 0.10

        # ---- 眉 ----
        brow = cls.BROW_STYLES.get(exp, "normal")
        if brow == "worried":      # 担忧：眉梢上扬的八字眉（靠外侧下压）
            cls._line(painter, cx - eye_dx - eye_r * 1.2, eye_y - r * 0.42,
                      cx - eye_dx + eye_r * 0.6, eye_y - r * 0.22)
            cls._line(painter, cx + eye_dx - eye_r * 0.6, eye_y - r * 0.22,
                      cx + eye_dx + eye_r * 1.2, eye_y - r * 0.42)
        elif brow == "raised":     # 惊讶/思考：抬高的挑眉
            cls._arc(painter, cx - eye_dx - eye_r, eye_y - r * 0.55, eye_r * 2, eye_r * 2, 200, 140)
            cls._arc(painter, cx + eye_dx - eye_r, eye_y - r * 0.55, eye_r * 2, eye_r * 2, 200, 140)
        elif brow == "flat":       # 专注：平直眉
            cls._line(painter, cx - eye_dx - eye_r * 1.0, eye_y - r * 0.42,
                      cx - eye_dx + eye_r * 1.0, eye_y - r * 0.42)
            cls._line(painter, cx + eye_dx - eye_r * 1.0, eye_y - r * 0.42,
                      cx + eye_dx + eye_r * 1.0, eye_y - r * 0.42)
        else:                      # gentle / normal：温和微弧眉
            cls._arc(painter, cx - eye_dx - eye_r * 1.1, eye_y - r * 0.5, eye_r * 2.4, eye_r * 1.4, 210, 120)
            cls._arc(painter, cx + eye_dx - eye_r * 1.3, eye_y - r * 0.5, eye_r * 2.4, eye_r * 1.4, 210, 120)

        # ---- 眼 ----
        eye = cls.EYE_STYLES.get(exp, "dot")
        if eye == "arc_up":        # happy：弯月眯眼（^_^）
            painter.setPen(QPen(_color(_PLACEHOLDER_COLORS["line"]), max(1.4, r * 0.05),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - eye_dx - eye_r, eye_y - eye_r, eye_r * 2, eye_r * 2), 180 * 16, 180 * 16)
            painter.drawArc(QRectF(cx + eye_dx - eye_r, eye_y - eye_r, eye_r * 2, eye_r * 2), 180 * 16, 180 * 16)
        elif eye == "line":        # tired：半闭眼（下弧线）
            painter.setPen(QPen(_color(_PLACEHOLDER_COLORS["line"]), max(1.4, r * 0.05),
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r), 180 * 16, 180 * 16)
            painter.drawArc(QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r), 180 * 16, 180 * 16)
        elif eye == "round":       # surprised：大圆眼（填色）
            painter.setBrush(_color(_PLACEHOLDER_COLORS["line"]))
            painter.drawEllipse(QRectF(cx - eye_dx - eye_r * 0.7, eye_y - eye_r * 0.7, eye_r * 1.4, eye_r * 1.4))
            painter.drawEllipse(QRectF(cx + eye_dx - eye_r * 0.7, eye_y - eye_r * 0.7, eye_r * 1.4, eye_r * 1.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif eye == "dot_up":      # thinking：视线飘向斜上
            cls._dot(painter, cx - eye_dx - eye_r * 0.1, eye_y - eye_r * 0.15, eye_r * 0.45)
            cls._dot(painter, cx + eye_dx + eye_r * 0.2, eye_y - eye_r * 0.4, eye_r * 0.42)
        elif eye == "dot_side":    # shy：视线略偏下（不好意思直视）
            cls._dot(painter, cx - eye_dx - eye_r * 0.15, eye_y + eye_r * 0.1, eye_r * 0.4)
            cls._dot(painter, cx + eye_dx - eye_r * 0.3, eye_y + eye_r * 0.15, eye_r * 0.4)
        elif eye == "dot_focus":   # focus：聚焦正视小圆点
            cls._dot(painter, cx - eye_dx, eye_y, eye_r * 0.45)
            cls._dot(painter, cx + eye_dx, eye_y, eye_r * 0.45)
        else:                      # normal / dot / dot_tilt：常规圆点
            cls._dot(painter, cx - eye_dx, eye_y + (eye_r * 0.1 if eye == "dot_tilt" else 0), eye_r * 0.45)
            cls._dot(painter, cx + eye_dx, eye_y + (eye_r * 0.1 if eye == "dot_tilt" else 0), eye_r * 0.45)

        # 害羞腮红
        if exp == "shy":
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_color("#FFA0A0", alpha=110))
            painter.drawEllipse(QRectF(cx - eye_dx - eye_r * 1.5, cy + r * 0.05, eye_r * 1.0, eye_r * 0.6))
            painter.drawEllipse(QRectF(cx + eye_dx + eye_r * 0.5, cy + r * 0.05, eye_r * 1.0, eye_r * 0.6))
            painter.restore()

        # ---- 嘴 ----
        mouth = cls.MOUTH_STYLES.get(exp, "smile")
        my = cy + r * 0.35
        mw = eye_r * 1.5
        if mouth == "open_smile":  # happy：张开的笑（填色小圆角矩形）
            painter.setBrush(_color(_PLACEHOLDER_COLORS["line"]))
            painter.drawChord(QRectF(cx - mw, my - mw * 0.4, mw * 2, mw * 1.8), 200 * 16, 140 * 16)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif mouth == "oh":        # surprised：O 型小嘴
            painter.setBrush(_color(_PLACEHOLDER_COLORS["line"]))
            painter.drawEllipse(QRectF(cx - mw * 0.45, my - mw * 0.35, mw * 0.9, mw * 0.9))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif mouth == "small_o":   # tired：困倦小 o
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(cx - mw * 0.35, my - mw * 0.25, mw * 0.7, mw * 0.7))
        elif mouth == "flat":      # concerned / focus：抿嘴直线
            cls._line(painter, cx - mw, my, cx + mw, my)
        elif mouth == "small":     # shy：小小微笑
            painter.drawArc(QRectF(cx - mw * 0.8, my - mw * 0.3, mw * 1.6, mw * 1.0), 200 * 16, 140 * 16)
        else:                      # smile：常规微笑
            painter.drawArc(QRectF(cx - mw, my - mw * 0.6, mw * 2, mw * 1.6), 200 * 16, 140 * 16)

    @staticmethod
    def _dot(painter: "QPainter", x: float, y: float, r: float) -> None:
        painter.setBrush(_color(_PLACEHOLDER_COLORS["line"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(x - r, y - r, r * 2, r * 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _line(painter: "QPainter", x1: float, y1: float, x2: float, y2: float) -> None:
        painter.drawLine(x1, y1, x2, y2)

    @staticmethod
    def _arc(painter: "QPainter", x: float, y: float, w: float, h: float,
             start: int, span: int) -> None:
        painter.drawArc(QRectF(x, y, w, h), start * 16, span * 16)


class MaidAssets:
    """形象资产加载器：校验 manifest + 逐表情加载 PNG；缺失/损坏按
    PLACEHOLDER_ENABLED 策略处理（默认关：返回 None，由消费端中性兜底；
    置 True 才生成程序占位脸，仅调试预览）。

    加载结果缓存：pixmap_for() 幂等；加载失败永不抛异常。
    """

    def __init__(self, assets_dir: Optional[Path] = None, theme: str = "default",
                 fallback: Optional["MaidAssets"] = None):
        self.dir = Path(assets_dir) if assets_dir else asset_dir()
        self.theme = theme or "default"
        self.manifest = load_manifest(self.dir)
        self.expressions: List[str] = list(self.manifest.get("expressions") or FALLBACK_EXPRESSIONS)
        # expression_id -> ("png" | "placeholder")，描述该表情当前回退状态
        self._states: Dict[str, str] = {}
        self._cache: Dict[str, QPixmap] = {}
        # v1.4.2: 角色专属资产集的回落链——本目录缺某表情时用码铃本体同表情顶替，
        # 保证任何角色在任何心情下都有图可显示（不会空白/不会切铃铛）。
        self.fallback = fallback
        # 缺真图时是否渲染程序绘制的占位形象（默认关闭，见模块常量 PLACEHOLDER_ENABLED）
        self.placeholder_enabled = PLACEHOLDER_ENABLED
        if QT_OK:
            self._load_all()

    # -- 加载 --
    def _load_all(self) -> None:
        # 合并 manifest 声明 + 目录内所有 .png（扩展表情 id 由用户自绘差分自动发现）
        discovered: List[str] = []
        if self.dir.is_dir():
            for p in self.dir.iterdir():
                if p.is_file() and p.suffix.lower() == ".png" and p.stem != "manifest":
                    discovered.append(p.stem)
        if discovered:
            merged = sorted(set(self.expressions) | set(discovered))
            self.expressions = merged
        for exp in self.expressions:
            pix = self._load_png(exp)
            if pix is not None:
                self._states[exp] = "png"
                self._cache[exp] = pix
            else:
                self._states[exp] = "placeholder"

    def _png_path(self, exp: str) -> Path:
        # A6 换装预留：若存在 {exp}_{theme}.png 则优先（当前默认只有 {exp}.png）
        themed = self.dir / f"{exp}_{self.theme}.png"
        if themed.exists():
            return themed
        return self.dir / f"{exp}.png"

    def _load_png(self, exp: str) -> Optional[QPixmap]:
        """Qt 加载单张 PNG；文件缺失/解码失败/空图均返回 None（回退占位）。"""
        path = self._png_path(exp)
        try:
            if not path.exists() or path.stat().st_size <= 0:
                return None
            img = QImage(str(path))
            if img.isNull() or img.width() <= 0 or img.height() <= 0:
                _logger.warning("maid 表情图损坏，回退占位: %s", path)
                return None
            return QPixmap.fromImage(img)
        except Exception as exc:
            _logger.warning("maid 表情图加载失败，回退占位: %s (%s)", path, exc)
            return None

    # -- 查询 --
    def expression_missing(self, exp: str) -> bool:
        """是否正在使用占位脸（缺图/坏图）。Qt 不可用时按文件存在性判定。

        v1.4.2: 带 fallback（角色资产集）时，本目录缺图但码铃本体有图 → 视为不缺
        （回落链保证有图显示，不触发消费端中性兜底）。
        """
        key = resolve_expression(exp)
        if self._states:
            own_missing = self._states.get(key, "placeholder") == "placeholder"
        else:
            own_missing = key in missing_asset_ids(self.dir)
        if own_missing and self.fallback is not None:
            return self.fallback.expression_missing(exp)
        return own_missing

    def missing_ids(self) -> List[str]:
        return [e for e in self.expressions if self.expression_missing(e)]

    def has_png(self, exp: str) -> bool:
        return not self.expression_missing(exp)

    # -- 取图 --
    def pixmap_for(self, exp: str, size_hint: Optional[int] = None) -> Optional[QPixmap]:
        """返回表情图（真实 PNG 或占位脸），并按 size_hint 缩放；Qt 不可用时返回 None。

        v1.4.2: 本目录缺图且有 fallback（码铃本体资产集）→ 用本体同表情图顶替
        （角色专属形象的表情差分回落链）。
        """
        if not QT_OK:
            return None
        key = resolve_expression(exp)
        pix = self._cache.get(key)
        if pix is None:
            if self.fallback is not None:
                # 本目录没有该表情的真图：回落码铃本体同表情（不渲染占位）
                fb = self.fallback.pixmap_for(exp, size_hint)
                if fb is not None:
                    self._cache[key if not size_hint else f"{key}@{size_hint}"] = fb
                    return fb
            if not self.placeholder_enabled:
                # 真插画未就绪（默认）：不渲染程序占位脸，返回 None 由消费端中性兜底
                return None
            # 仅调试预览占位绘制时（PLACEHOLDER_ENABLED=True）才生成程序脸
            pix = self._make_placeholder(key)
        if size_hint and pix is not None and pix.width() != size_hint:
            pix = pix.scaled(size_hint, size_hint,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
            self._cache[f"{key}@{size_hint}"] = pix
        return pix

    def _make_placeholder(self, exp: str) -> Optional[QPixmap]:
        """程序绘制占位脸（底色块 + 铃铛 + 眉眼嘴）。"""
        if not QT_OK:
            return None
        base = 256
        pix = QPixmap(base, base)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        try:
            PlaceholderFacePainter.draw(painter, base / 2, base / 2, base * 0.36, exp)
        finally:
            painter.end()
        self._states[exp] = "placeholder"
        return pix

    # -- 圆形裁剪（气泡/微型档复用）--
    def rounded(self, exp: str, size: int = 64) -> Optional[QPixmap]:
        """把主形象缩略并圆形裁剪（QPainter clip）为 size×size 头像。"""
        if not QT_OK:
            return None
        src = self.pixmap_for(exp, size)
        if src is None:
            return None
        out = QPixmap(size, size)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, src)
        painter.end()
        return out


class MaidAvatar(_MaidAvatarBase):
    """主形象控件：显示指定表情（png 或占位），供首页/宠物/气泡复用。

    统一 API：set_maid_expression(name) / expression()；
    Design 别名：set_expression()（同 set_maid_expression）。
    """

    def __init__(self, parent=None, assets: Optional[MaidAssets] = None,
                 expression: str = "normal", size: int = 160):
        if not QT_OK:
            raise RuntimeError("PySide6 未安装，MaidAvatar 不可用")
        super().__init__(parent)
        self._assets = assets or MaidAssets()
        self._expression = resolve_expression(expression)
        self._size = size
        self.setMinimumSize(1, 1)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    # -- 状态 --
    def set_maid_expression(self, name: str) -> bool:
        """设置表情；非法 id 回落 normal。返回是否发生变化。"""
        new = resolve_expression(name)
        if new == self._expression:
            return False
        self._expression = new
        self.update()
        return True

    def set_expression(self, name: str) -> bool:
        """design-v12 别名，行为与 set_maid_expression 一致。"""
        return self.set_maid_expression(name)

    def set_assets(self, assets: Optional["MaidAssets"]) -> None:
        """v1.4.2: 切换资产集（角色专属形象）——表情 id 保持不变，仅换图源。

        传 None 或角色无资产集时回落码铃本体 MaidAssets。切换后立即重绘。
        """
        new_assets = assets if assets is not None else _get_default_assets()
        if new_assets is self._assets:
            return
        self._assets = new_assets
        self.update()

    def expression(self) -> str:
        return self._expression

    def using_placeholder(self) -> bool:
        return self._assets.expression_missing(self._expression)

    # -- 呈现 --
    def pixmap(self, size_hint: Optional[int] = None) -> Optional[QPixmap]:
        return self._assets.pixmap_for(self._expression, size_hint)

    def rounded_avatar(self, size: int = 64) -> Optional[QPixmap]:
        """当前表情的圆形裁剪头像（供聊天气泡/微型档/侧栏复用）。"""
        return self._assets.rounded(self._expression, size)

    def sizeHint(self) -> QSize:  # noqa: N802（Qt 命名）
        return QSize(self._size, self._size)

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        pix = self.pixmap_for_current()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if pix is not None:
                painter.drawPixmap(self.rect(), pix)
            else:
                # 形象未就绪（资产无真图且占位绘制默认关）：中性几何铃铛兜底，
                # 不画程序假脸；美术 PNG 就位后自动显示真形象。
                self._paint_neutral_bell(painter)
        finally:
            painter.end()

    def _paint_neutral_bell(self, painter: "QPainter") -> None:
        """极简中性占位：浅粉圆底 + 几何小铃铛（不依赖 emoji 字体，也不画脸）。"""
        rect = self.rect()
        side = min(rect.width(), rect.height())
        if side <= 0:
            return
        cx = rect.x() + rect.width() / 2.0
        cy = rect.y() + rect.height() / 2.0
        r = side * 0.42
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("#FFE4EC"))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        # 铃身（金色圆）
        bell_r = r * 0.30
        painter.setBrush(_color("#F4C430"))
        painter.setPen(QPen(_color("#C89B2C"), max(1.0, r * 0.035)))
        painter.drawEllipse(QRectF(cx - bell_r, cy - bell_r * 0.55, bell_r * 2, bell_r * 2))
        # 顶部铃钮
        knob = r * 0.08
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("#E8A93C"))
        painter.drawEllipse(QRectF(cx - knob, cy - bell_r * 0.55 - knob * 1.8, knob * 2, knob * 2))
        # 底部铃口弧线
        painter.setPen(QPen(_color("#C89B2C"), max(1.0, r * 0.03)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(cx - bell_r * 0.6, cy + bell_r * 0.25, bell_r * 1.2, bell_r * 0.8), 0, 180 * 16)

    def pixmap_for_current(self) -> Optional[QPixmap]:
        """按控件当前尺寸缩放的表情图（控件内直接绘制用）。"""
        w = max(1, self.width())
        pix = self._assets.pixmap_for(self._expression, w)
        if pix is not None:
            return pix.scaled(w, w, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        return None


# ----------------------------------------------------------------------
# v1.4.2: 角色专属形象资产集（每角色一套表情差分，缺图回落码铃本体）
# ----------------------------------------------------------------------
_ROLE_ASSETS_CACHE: Dict[str, Optional["MaidAssets"]] = {}
_default_assets_inst: Optional["MaidAssets"] = None


def _get_default_assets() -> "MaidAssets":
    """码铃本体默认资产集（模块级单例，懒建）。"""
    global _default_assets_inst
    if _default_assets_inst is None:
        _default_assets_inst = MaidAssets()
    return _default_assets_inst


def role_assets_root_dirs(role_id: str) -> List[Path]:
    """角色形象目录查找顺序：~/.maid_coder 优先（与角色目录同根，升级不丢），
    GUI 数据目录次之，随包内置最后。"""
    dirs: List[Path] = []
    try:
        dirs.append(Path.home() / ".maid_coder" / "role_assets" / str(role_id))
    except Exception:
        pass
    try:
        from gui.utils import get_user_data_dir
        dirs.append(Path(get_user_data_dir()) / "role_assets" / str(role_id))
    except Exception:
        pass
    try:
        dirs.append(asset_dir().parent / "roles" / str(role_id))
    except Exception:
        pass
    return dirs


def _dir_has_png(d: Path) -> bool:
    try:
        return d.is_dir() and any(
            p.suffix.lower() == ".png" and p.stem != "manifest" for p in d.iterdir()
        )
    except Exception:
        return False


def role_assets(role_id: str) -> Optional["MaidAssets"]:
    """取角色专属资产集（带回落链）；角色没有任何自定义图 → None（调用方用码铃本体）。"""
    key = str(role_id or "")
    if not key:
        return None
    if key in _ROLE_ASSETS_CACHE:
        return _ROLE_ASSETS_CACHE[key]
    result: Optional[MaidAssets] = None
    if QT_OK:
        for d in role_assets_root_dirs(key):
            if _dir_has_png(d):
                try:
                    result = MaidAssets(assets_dir=d, fallback=_get_default_assets())
                except Exception:
                    result = None
                break
    _ROLE_ASSETS_CACHE[key] = result
    return result


def reset_role_assets(role_id: str = "") -> None:
    """用户放入/更新表情图后调用：清缓存让新图立即生效（role_id 空则全清）。"""
    if not role_id:
        _ROLE_ASSETS_CACHE.clear()
    else:
        _ROLE_ASSETS_CACHE.pop(str(role_id), None)


# Qt 不可用时的模块级占位（GUI 层用 getattr 守卫，勿直接实例化）
if not QT_OK:
    MaidAssets = None  # type: ignore
    PlaceholderFacePainter = None  # type: ignore  （保留纯决策函数可用）
