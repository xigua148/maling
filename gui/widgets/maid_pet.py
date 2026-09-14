"""窗口角落微型常驻宠物（A-9 / PRD A8 + A8-1）—— MaidPet 组件。

产品口径（docs/design-v12.md §3.6 D6 + A-9 任务）：
  - 角落宠物是「以女仆形象为基础的小动物形态」—— 戴铃铛发饰/领结的女仆装
    小兽（猫耳方向），**不是主形象简单缩小**；
  - 当前无宠物 PNG 资产：assets/maid_pet/ 只放 manifest + 说明，PNG 到位即被
    PetAssets 自动加载（接口不变）。缺图时**不显示程序绘制的占位兽**（用户拍板
    「先去掉小兽小人，画好真图再启用」）——控件画中性 🔔 兜底，UI 永不空白；
  - A8-1 微型档 v1.2 先行 5 态：normal / happy / thinking / focus / tired，
    其余 8 态输入（concerned/shy/surprised）经 pet_expression_for() 收敛到 5 态内；
  - 尺寸 48~72px（内容区宽裕时）；窄区自动缩为 24px 或隐藏（纯函数判定，可自测）；
  - 位置：挂载到主窗口内容区（page_stack）右上角，不遮挡会话操作、不随滚动漂移
    （父控件 resize 时自动 reposition）；窄窗折叠由 pet_size_for_content_width 决定；
  - 表情联动：订阅 app_ctx.companion_bridge.mood_changed（活动态 thinking/focus
    由聊天面板经 bridge.note_activity 广播，本组件作为四接收端之一随同更新）；
  - hover：轻量 popup 心情文案（氛围语境无数值）+「回首页」动作；
  - 点击：小互动反馈（happy 脉冲 ~400ms，模拟点头/铃铛闪；不做动画引擎）。
  - v1.4 造型收敛（GuiConfig.pet_style）：角落宠物与聊天气泡头像统一为 maid，
    即复用主形象 MaidAssets（assets/maid/）在宠物尺寸渲染。原「女仆小兽」chibi
    形态已按用户要求移除 UI 入口，历史存档经 resolve_pet_style 回落 maid；
    assets/maid_pet/ 资产保留，仅不再被 UI 选用。

§3.9 红线遵守：UI 无数值/分数/进度条；tooltip 只含心情句/关系称谓/暖描述；
companion 缺失时降级为中性 🔔 兜底 + 通用文案，UI 永不空白/崩溃。

防御式设计（对齐 gui/maid_avatar.py）：
  - 模块顶层不依赖 PySide6；纯决策函数（表情收敛/尺寸判定/tooltip 拼装）无 Qt
    依赖，可在无 GUI 环境 import 并自测；
  - Qt 层（PetChibiPainter / PetAssets / MaidPet）在 PySide6 缺失时降级为 None。
"""

from __future__ import annotations

import logging
from typing import Optional

# companion（纯 stdlib）提供心情态 -> 心情短语（tooltip 文案），避免两处漂移
from companion import MOOD_PHRASES
# 复用 MaidAssets 加载器/占位回退基础设施，不重复造加载器
from gui.maid_avatar import MaidAssets, resolve_expression
from gui.utils import get_resource_path, theme_color

_logger = logging.getLogger("maid_coder.gui.maid_pet")

# ---------------------------------------------------------------------------
# 纯决策层（无 Qt 依赖，可独立自测）
# ---------------------------------------------------------------------------

# A8-1 微型档 v1.2 先行 5 态（manifest.asset_notes.micro_states_v12 同口径）
PET_MICRO_STATES = ["normal", "happy", "thinking", "focus", "tired"]

# 8 态 -> 宠物 5 态 收敛表（多余态回落最接近的微档表情；未列默认 normal）
PET_STATE_FALLBACK = {
    "normal": "normal",
    "happy": "happy",
    "thinking": "thinking",
    "focus": "focus",
    "tired": "tired",
    "concerned": "normal",   # 担忧无专属微档，回落平静（不表达负向）
    "shy": "happy",          # 被夸害羞 -> 开心（正向，避免负向反馈）
    "surprised": "normal",
}

# 宠物 tooltip 兜底心情短语（正向、无数值；心情态取 companion.MOOD_PHRASES 优先）
_PET_TOOLTIP_PHRASES = {
    "normal": "安安静静地陪着主人",
    "happy": "和主人在一起真开心",
    "concerned": "有点挂念主人",
    "shy": "见到主人有点不好意思",
    "tired": "困了，但还是想陪在主人身边",
    "thinking": "正在心里想着主人的事情",
    "focus": "正专注地帮主人做事",
    "surprised": "被主人吓了一跳呢",
}


# ---------------------------------------------------------------------------
# v1.2 宠物造型全局开关（纯决策层；v1.4 形态已收敛）
#   maid = 女仆小人主形象（assets/maid/，气泡头像与角落宠物共用，唯一形态）
#   chibi = 「女仆小兽」——v1.4 起 UI 不再提供该入口，常量与回落逻辑保留兼容，
#           历史存档/外部传入的 chibi 统一经 resolve_pet_style 回落 maid。
#           资产目录 assets/maid_pet/ 不删除，仅不再被 UI 选用。
# 首页大形象/侧栏/托盘恒为 maid 本体，不随开关变化。
# ---------------------------------------------------------------------------
PET_STYLE_CHIBI = "chibi"
PET_STYLE_MAID = "maid"
PET_STYLE_LABELS = {
    PET_STYLE_CHIBI: "女仆小兽",
    PET_STYLE_MAID: "女仆小人",
}


def resolve_pet_style(cfg) -> str:  # noqa: ARG001 —— 保留旧签名以兼容既有调用方
    """解析宠物造型：恒为「女仆小人」maid。

    v1.4：「女仆小兽」（chibi）形态已按用户要求从设置页移除（资产目录
    assets/maid_pet/ 保留，仅不再提供 UI 入口）。历史存档里的 chibi 值与任何
    非法/缺失值统一回落 maid。

    签名与返回值兼容旧调用方（MaidPet / MessageBubble / 设置页），入参不再
    影响结果，保留仅为不破坏既有调用点。
    """
    return PET_STYLE_MAID


def pet_expression_for(state: Optional[str]) -> str:
    """任意心情态/活动态/表情 id -> 宠物 5 态表情 id；未知一律 normal。"""
    if not isinstance(state, str):
        return "normal"
    key = state.strip().lower()
    if key in PET_MICRO_STATES:
        return key
    return PET_STATE_FALLBACK.get(key, "normal")


def pet_size_for_content_width(content_width: int) -> int:
    """按内容区宽度决定宠物像素尺寸（0 = 隐藏）。

    区间设计（对齐 A-9「48~72px 常态，窄区缩 24px / 自动隐藏」）：
      - >= 900px   : 64px（常态上限）
      - 640~899    : 48px（常态下限）
      - 420~639    : 24px（mini 档，窄窗可折叠形态）
      - < 420      : 0（内容区过窄 -> 隐藏，避免遮挡会话操作）
    负数/异常输入一律按 0 处理（隐藏），纯函数便于自测。
    """
    try:
        w = int(content_width)
    except (TypeError, ValueError):
        return 0
    if w <= 0:
        return 0
    if w >= 900:
        return 64
    if w >= 640:
        return 48
    if w >= 420:
        return 24
    return 0


def pet_display_mode(content_width: int) -> str:
    """尺寸判定 -> 语义标签（hidden/mini/full），供日志与自测断言。"""
    size = pet_size_for_content_width(content_width)
    if size <= 0:
        return "hidden"
    if size <= 24:
        return "mini"
    return "full"


def pet_tooltip_context(companion=None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """从 companion 取出 tooltip 三要素 (心情句, 关系称谓, 最近事件暖描述)。

    全部为自然语言、无数值；companion 缺失 / 异常时逐项回退 None，
    由调用方拼接兜底文案（getattr 守卫，不崩）。
    """
    phrase: Optional[str] = None
    stage: Optional[str] = None
    event_desc: Optional[str] = None
    if companion is not None:
        try:
            mood = getattr(companion, "mood", None) or "normal"
            phrase = MOOD_PHRASES.get(mood) or _PET_TOOLTIP_PHRASES.get(mood)
        except Exception:
            phrase = None
        try:
            stage = companion.relation_stage_name()
        except Exception:
            stage = None
        try:
            event_desc = companion.describe_recent_event()
        except Exception:
            event_desc = None
    if not phrase:
        # companion 缺失时按情绪态本地兜底（含活动态）
        phrase = _PET_TOOLTIP_PHRASES.get("normal")
    return phrase, stage, event_desc


def build_pet_tooltip(
    mood_phrase: Optional[str],
    stage: Optional[str],
    event_desc: Optional[str] = None,
) -> str:
    """拼装宠物 tooltip 正文（多行）。

    红线：只允许自然语言（心情句 / 「和主人的关系已到『称谓』」 / 暖事件句），
    不含任何数字/分数/进度；空段自动跳过。
    """
    lines: list[str] = []
    mood_phrase = (mood_phrase or "").strip()
    if mood_phrase:
        lines.append(mood_phrase)
    stage = (stage or "").strip()
    if stage:
        lines.append(f"和主人的关系已到「{stage}」")
    event_desc = (event_desc or "").strip()
    if event_desc:
        lines.append(event_desc)
    return "\n".join(lines)


def mood_tooltip_text(companion=None, display_state: Optional[str] = None) -> str:
    """心情 tooltip 文本（A-11 托盘/侧栏与宠物悬停共用；无数值红线）。

    display_state 优先（活动态 thinking/focus 也能出文案），否则取 companion.mood；
    companion 缺失时按 normal 兜底，永不空串、永不崩。全部自然语言。
    """
    state = display_state
    if not state:
        state = getattr(companion, "mood", None) if companion is not None else None
    key = str(state).strip().lower() if isinstance(state, str) else "normal"
    phrase = MOOD_PHRASES.get(key) or _PET_TOOLTIP_PHRASES.get(key)
    if not phrase:
        phrase = _PET_TOOLTIP_PHRASES["normal"]
    stage: Optional[str] = None
    event_desc: Optional[str] = None
    if companion is not None:
        try:
            stage = companion.relation_stage_name()
        except Exception:
            stage = None
        try:
            event_desc = companion.describe_recent_event()
        except Exception:
            event_desc = None
    return build_pet_tooltip(phrase, stage, event_desc)


# A-8(A3): 点击彩蛋台词池（氛围语境、无数值；与 5 态收敛一致，缺失回落 normal）
PET_CLICK_LINES = {
    "normal": "叮铃~ 主人，我在这里呢",
    "happy": "嘿嘿，被主人戳到啦~",
    "thinking": "嗯？主人是不是在想我呀",
    "focus": "叮——主人稍等，我忙完就来陪您",
    "tired": "呜哇… 打个铃铛打起精神！",
}


def pet_click_line(state: Optional[str] = None) -> str:
    """按当前展示态取一句点击台词（无数值；未知回落 normal 台词）。"""
    key = pet_expression_for(state)
    return PET_CLICK_LINES.get(key, PET_CLICK_LINES["normal"])


def interpret_pet_click_result(result, current_state: Optional[str] = None) -> dict:
    """解析 companion.react_to_pet_click() 返回 -> 统一反馈结构。

    companion 返回 {text, expression, cooling}（可为 None/缺字段/stub 空值）：
      - text 缺失/空 -> 用本池按 current_state 兜底台词；
      - expression 缺失/空 -> happy（正向反馈脉冲）；
      - cooling 仅透传（加分与否是 companion 内部语义，GUI 只展示）。
    返回 dict{text, expression, cooling}，全部无数值。
    """
    cooling = bool(result and result.get("cooling"))
    text = ""
    expr = ""
    if isinstance(result, dict):
        text = str(result.get("text") or "").strip()
        expr = result.get("expression") or ""
    # text 有值 = companion 真返回（含 stub 默认 mood）→ 按其 expression 走收敛；
    # text 为空（stub/None）→ 本池兜底台词 + happy 脉冲（点击反馈不失活、有生气）
    if text:
        expr = pet_expression_for(expr) if expr else "happy"
    else:
        text = pet_click_line(current_state)
        expr = pet_expression_for(expr) if expr and expr not in ("", "normal") else "happy"
    return {"text": text, "expression": expr, "cooling": cooling}


# ---------------------------------------------------------------------------
# Qt 层：猫耳小女仆占位绘制 + PetAssets（复用 MaidAssets）+ MaidPet 控件
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
    QT_OK = True
except Exception:  # PySide6 未安装：本模块仍可 import（纯决策层可用）
    QT_OK = False
    QPixmap = None  # type: ignore
    QPainter = None  # type: ignore
    QWidget = None  # type: ignore
    # 让 Qt 类体在无 PySide6 时也能被解释执行（仅定义，不会被实例化）
    Signal = lambda *a, **k: None  # noqa: E731


_MaidPetBase = QWidget if QT_OK else object
# 宠物资产池基类：PySide6 缺失时 MaidAssets 被 maid_avatar 置 None，动态回落 object
_PetAssetsBase = MaidAssets if QT_OK else object


def _color(v: str, alpha: int = 255) -> "QColor":
    col = QColor(v)
    if col.isValid():
        if alpha != 255:
            col.setAlpha(alpha)
        return col
    return QColor(180, 180, 180)


# 占位小兽的固定绘画调色板（与 maid_avatar._PLACEHOLDER_COLORS 同性质：占位
# 美术资源色，不随主题变；真正的 UI 皮肤/浮层色一律 theme_color）
_PET_PALETTE = {
    "halo": (255, 255, 255, 110),      # 柔和光环（轻微提亮，避免与深色页底粘连）
    "ear": "#FFD6E8",                   # 耳朵
    "ear_inner": "#FFE9F1",             # 内耳
    "face": "#FFE3DA",                  # 脸
    "face_stroke": "#E8B4B8",
    "line": "#8A5A5A",                  # 眉眼嘴
    "bell": "#F4C430",                  # 铃铛金
    "bell_dark": "#B8860B",
    "dress": "#FFD0DC",                 # 女仆裙
    "dress_stroke": "#E9AAB8",
    "apron": "#FFFFFF",                 # 白围裙
    "bow": "#E85D75",                   # 领结红
    "blush": (255, 150, 150, 130),
}


class PetChibiPainter:
    """QPainter 程序绘制的「猫耳小女仆」半身小兽占位图。

    输入为边长 side 的正方形画布，坐标用「64 网格」虚拟坐标 + painter.scale 缩放，
    因此任意目标尺寸下保持等比例。五官随 5 态变化（同 PlaceholderFacePainter 思路，
    复用 dot/arc/line 等基础几何，表情一眼可辨）。
    """

    @classmethod
    def draw(cls, painter: "QPainter", side: int, expression: str) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            scale = side / 64.0
            painter.scale(scale, scale)
            cls._paint(painter, pet_expression_for(expression))
        finally:
            painter.restore()

    # -- 几何辅助（64 网格内）--
    @staticmethod
    def _path(painter: "QPainter", pts) -> None:
        painter.save()
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()

    @staticmethod
    def _dot(painter: "QPainter", x: float, y: float, r: float) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(_PET_PALETTE["line"]))
        painter.drawEllipse(QRectF(x - r, y - r, r * 2, r * 2))
        painter.restore()

    @staticmethod
    def _arc(painter: "QPainter", x: float, y: float, w: float, h: float,
             start: float, span: float) -> None:
        painter.drawArc(QRectF(x, y, w, h), int(start * 16), int(span * 16))

    @staticmethod
    def _line(painter: "QPainter", x1: float, y1: float, x2: float, y2: float) -> None:
        painter.drawLine(x1, y1, x2, y2)

    # -- 主体绘制 --
    @classmethod
    def _paint(cls, painter: "QPainter", exp: str) -> None:
        # 1) 柔和光环（画在最后层之上、所有主体之下）
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(*_PET_PALETTE["halo"]))
        painter.drawEllipse(QRectF(5, 3, 54, 58))
        painter.restore()

        # 2) 女仆裙（半身小兽：先画身体，再被头/围裙覆盖局部，视觉连贯）
        cls._draw_dress(painter)

        # 3) 耳朵（猫耳方向，画在头后）
        cls._draw_ears(painter)

        # 4) 头（肤色圆）
        painter.setPen(QPen(_color(_PET_PALETTE["face_stroke"]), 1.0))
        painter.setBrush(_color(_PET_PALETTE["face"]))
        painter.drawEllipse(QRectF(17, 18, 30, 30))

        # 5) 铃铛发饰（顶中）
        cls._draw_bell_ornament(painter)

        # 6) 五官
        painter.setPen(QPen(_color(_PET_PALETTE["line"]), 1.4,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cls._draw_face(painter, exp)

        # 7) 领结（颈部，覆盖在脸下缘与裙之间）
        cls._draw_bow(painter)

    # ---- 裙子 + 白围裙 ----
    @staticmethod
    def _draw_dress(painter: "QPainter") -> None:
        painter.save()
        painter.setPen(QPen(_color(_PET_PALETTE["dress_stroke"]), 1.0))
        painter.setBrush(_color(_PET_PALETTE["dress"]))
        # 上窄下宽的小裙摆
        pts = [(23.5, 47.0), (40.5, 47.0), (49.5, 62.0), (14.5, 62.0)]
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.moveTo(*pts[0])
        for x, y in pts[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(_PET_PALETTE["apron"]))
        painter.drawRoundedRect(QRectF(27.5, 52.0, 9.0, 10.0), 2.0, 2.0)
        painter.restore()

    # ---- 猫耳 ----
    @staticmethod
    def _draw_ears(painter: "QPainter") -> None:
        painter.save()
        painter.setPen(QPen(_color(_PET_PALETTE["face_stroke"]), 0.9))
        painter.setBrush(_color(_PET_PALETTE["ear"]))
        # 外耳（左/右三角）
        for pts in ([(18.5, 21.5), (13.5, 4.0), (29.0, 10.5)],
                    [(45.5, 21.5), (50.5, 4.0), (35.0, 10.5)]):
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)
        # 内耳（浅色小三角）
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color(_PET_PALETTE["ear_inner"]))
        for pts in ([(19.5, 19.5), (16.0, 9.0), (26.0, 13.0)],
                    [(44.5, 19.5), (48.0, 9.0), (38.0, 13.0)]):
            from PySide6.QtGui import QPainterPath
            path = QPainterPath()
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
            path.closeSubpath()
            painter.drawPath(path)
        painter.restore()

    # ---- 铃铛发饰 ----
    @staticmethod
    def _draw_bell_ornament(painter: "QPainter") -> None:
        painter.save()
        # 小铃铛：圆身 + 中缝线 + 顶部小圈
        br = 3.2
        cx, cy = 32.0, 11.5
        painter.setPen(QPen(_color(_PET_PALETTE["bell_dark"]), 0.9))
        painter.setBrush(_color(_PET_PALETTE["bell"]))
        painter.drawEllipse(QRectF(cx - br, cy - br * 0.7, br * 2, br * 2))
        painter.setPen(QPen(_color(_PET_PALETTE["bell_dark"]), 0.5))
        painter.drawLine(cx, cy - br * 0.2, cx, cy + br * 0.8)
        painter.setBrush(_color(_PET_PALETTE["bell_dark"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(cx - 1.2, cy + br * 0.9, 2.4, 2.4))
        painter.restore()

    # ---- 领结（女仆装）----
    @staticmethod
    def _draw_bow(painter: "QPainter") -> None:
        painter.save()
        painter.setBrush(_color(_PET_PALETTE["bow"]))
        painter.setPen(QPen(QColor("#C24A60"), 0.7))
        cx, cy = 32.0, 47.0
        # 左/右翼 + 中心小结
        painter.drawEllipse(QRectF(cx - 5.6, cy - 1.6, 4.6, 3.6))
        painter.drawEllipse(QRectF(cx + 1.0, cy - 1.6, 4.6, 3.6))
        painter.drawEllipse(QRectF(cx - 1.2, cy - 1.5, 2.4, 3.0))
        painter.restore()

    # ---- 五官（5 态）----
    @classmethod
    def _draw_face(cls, painter: "QPainter", exp: str) -> None:
        dx = 6.2
        eye_y = 30.5

        # 眉/眼（按态）
        if exp == "happy":                       # ^ ^ 弯月眯眼
            painter.setPen(QPen(_color(_PET_PALETTE["line"]), 1.3,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cls._arc(painter, 32 - dx - 2.0, eye_y - 2.0, 4.0, 4.0, 180, 180)
            cls._arc(painter, 32 + dx - 2.0, eye_y - 2.0, 4.0, 4.0, 180, 180)
        elif exp == "thinking":                  # 视线飘向斜上（思考）
            cls._dot(painter, 32 - dx - 0.6, eye_y - 1.0, 1.0)
            cls._dot(painter, 32 + dx + 1.2, eye_y - 2.6, 0.9)
        elif exp == "focus":                     # 专注正视 + 平眉
            painter.setPen(QPen(_color(_PET_PALETTE["line"]), 1.3,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cls._line(painter, 32 - dx - 2.4, eye_y - 4.6, 32 - dx + 2.4, eye_y - 4.6)
            cls._line(painter, 32 + dx - 2.4, eye_y - 4.6, 32 + dx + 2.4, eye_y - 4.6)
            cls._dot(painter, 32 - dx, eye_y, 1.0)
            cls._dot(painter, 32 + dx, eye_y, 1.0)
        elif exp == "tired":                     # 半闭眼（困倦）
            painter.setPen(QPen(_color(_PET_PALETTE["line"]), 1.3,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            cls._arc(painter, 32 - dx - 1.8, eye_y - 1.2, 3.6, 2.6, 0, 180)
            cls._arc(painter, 32 + dx - 1.8, eye_y - 1.2, 3.6, 2.6, 0, 180)
        else:                                    # normal：常规圆点
            cls._dot(painter, 32 - dx, eye_y, 1.0)
            cls._dot(painter, 32 + dx, eye_y, 1.0)

        # 腮红（happy 态 -> 粉嫩加分；与 shy->happy 收敛共用）
        if exp == "happy":
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*_PET_PALETTE["blush"]))
            painter.drawEllipse(QRectF(32 - dx - 3.0, eye_y + 4.0, 3.0, 1.8))
            painter.drawEllipse(QRectF(32 + dx + 0.2, eye_y + 4.0, 3.0, 1.8))
            painter.restore()

        # 嘴（按态）
        my = 39.2
        mw = 2.6
        painter.setPen(QPen(_color(_PET_PALETTE["line"]), 1.3,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if exp == "happy":                       # 张嘴笑（填色小弧形）
            painter.setBrush(_color(_PET_PALETTE["line"]))
            painter.drawChord(QRectF(32 - mw, my - 1.6, mw * 2, mw * 1.7), 200 * 16, 140 * 16)
            painter.setBrush(Qt.BrushStyle.NoBrush)
        elif exp == "focus":                     # 抿嘴直线
            cls._line(painter, 32 - 1.8, my, 32 + 1.8, my)
        elif exp == "tired":                     # 困倦小 o
            painter.drawEllipse(QRectF(32 - 1.1, my - 0.8, 2.2, 2.2))
        else:                                    # normal / thinking：小微笑
            cls._arc(painter, 32 - mw, my - 1.4, mw * 2, mw * 1.4, 200, 140)


class PetAssets(_PetAssetsBase):
    """微型宠物资产池（assets/maid_pet/）：复用 MaidAssets 加载/回退管线。

    与主形象的区别只在占位图：缺 PNG 时画「猫耳小女仆」半身小兽而非圆脸占位；
    PNG 到位（文件名 = 5 态 id）即自动被 MaidAssets 逻辑加载，调用接口不变。
    """

    def __init__(self, assets_dir=None, theme: str = "default"):
        super().__init__(
            assets_dir=assets_dir or get_resource_path("assets/maid_pet"),
            theme=theme,
        )

    def _make_placeholder(self, exp: str):
        if not QT_OK:
            return None
        key = resolve_expression(exp)
        base = 256
        pix = QPixmap(base, base)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        try:
            PetChibiPainter.draw(painter, base, pet_expression_for(key))
        finally:
            painter.end()
        self._states[key] = "placeholder"
        return pix


if QT_OK:
    _maid_assets_cache: Optional[MaidAssets] = None

    def _shared_maid_assets() -> "Optional[MaidAssets]":
        """模块级共享主形象(MaidAssets)实例（style=maid 时角落宠物复用小人管线）。"""
        global _maid_assets_cache
        if _maid_assets_cache is None:
            try:
                _maid_assets_cache = MaidAssets()
            except Exception as exc:
                _logger.warning("MaidAssets 初始化失败（maid 造型走降级）: %s", exc)
                _maid_assets_cache = None
        return _maid_assets_cache

    _pet_assets_cache: Optional[PetAssets] = None

    def _shared_pet_assets() -> PetAssets:
        """模块级共享宠物资产实例（避免每控件重复解析 manifest/占位图）。"""
        global _pet_assets_cache
        if _pet_assets_cache is None:
            try:
                _pet_assets_cache = PetAssets()
            except Exception as exc:
                _logger.warning("PetAssets 初始化失败（pet 走降级）: %s", exc)
                _pet_assets_cache = None
        return _pet_assets_cache  # type: ignore[return-value]


class MaidPet(_MaidPetBase):
    """角落常驻微型宠物控件。

    挂载方式（防「页面切换时被 QStackedWidget 盖住」）：作为内容区所在的父容器
    （如 central_splitter）的**同级子控件**，parent=父容器、track_widget=内容区
    （page_stack）；绘制时宠物永远在父容器子树之上，不随页面滚动漂移，
    只在 track_widget 的右上角小区域内存在。

    行为：
      - 表达式：5 态占位小兽；订阅 companion_bridge.mood_changed（活动态随同）
        或静态使用 pet_expression_for 输入；
      - 尺寸/显隐：relayout() 依 track_widget 宽度自动 64/48/24/隐藏；
      - hover：轻量 popup（心情文案 + 关系称谓 + 最近事件 + 「回首页」）；
      - 点击：clicked 信号 + happy 脉冲反馈（点头/铃铛闪，~400ms 回落）；
      - 「回首页」：go_home_requested 信号；默认处理 = page_manager.navigate("home")
        （可被外部接管，外部 connect 后自行处理）；
      - 造型（v1.2）：chibi = 默认小兽；maid = 复用主形象 MaidAssets（assets/maid/）
        在宠物尺寸渲染；hover/点击/彩蛋/表情脉冲/tooltip 与造型无关，全部共用。
    """

    clicked = Signal()            # A-3 彩蛋接线点（后续 A-8 可连 companion 互动）
    go_home_requested = Signal()  # 回首页请求

    def __init__(self, app_context, parent: Optional[QWidget] = None,
                 track_widget: Optional[QWidget] = None):
        if not QT_OK:
            raise RuntimeError("PySide6 未安装，MaidPet 不可用")
        super().__init__(parent)
        self.app_ctx = app_context
        # 内容区参考 widget（决定宽度/右上角锚点）：缺省退回父容器自身
        self._track = track_widget or parent
        self._expr = "normal"
        self._size = 48
        self._popup: Optional[QFrame] = None
        self._pulse = False
        self._connected = False
        self._hover_hide_armed = False
        self._assets = _shared_pet_assets()
        # v1.2 宠物造型全局开关（构造时读一次；运行中由设置页保存后 set_pet_style 切换）
        self._style = resolve_pet_style(getattr(app_context, "config", None))

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("")  # 自绘 popup，屏蔽原生 tooltip 双显示

        # 表情脉冲定时器（单击反馈；随对象销毁自动停）
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setSingleShot(True)
        self._pulse_timer.timeout.connect(self._flash_end)

        # 悬停离开延迟隐藏定时器（随对象销毁自动停，避免 static singleShot 悬挂）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._on_hover_hide)

        # A-8(A3) 彩蛋台词浮层（瞬时显示后自动收起）
        self._line_pop: Optional[QFrame] = None
        self._line_label: Optional[QLabel] = None
        self._line_timer = QTimer(self)
        self._line_timer.setSingleShot(True)
        self._line_timer.timeout.connect(self._hide_line_pop)

        # track_widget resize -> 自动 reposition（内容区右上角，不随滚动漂移）
        if self._track is not None:
            self._track.installEventFilter(self)

        self._apply_initial_expression()
        self._connect_mood_bridge()
        self._reposition()

    # ------------------------------------------------------------------
    # 表情 / mood 广播
    # ------------------------------------------------------------------
    def _current_display_state(self) -> str:
        """读 bridge 当前应展示态（活动态优先），无 bridge 回落 companion.mood/normal。"""
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        try:
            if bridge is not None and hasattr(bridge, "current_display"):
                return bridge.current_display() or "normal"
        except Exception:
            pass
        companion = getattr(self.app_ctx, "companion", None)
        if companion is not None:
            try:
                return companion.mood or "normal"
            except Exception:
                pass
        return "normal"

    def _apply_initial_expression(self) -> None:
        self._expr = pet_expression_for(self._current_display_state())

    def _connect_mood_bridge(self) -> None:
        if self._connected:
            return
        bridge = getattr(self.app_ctx, "companion_bridge", None)
        if bridge is None:
            return
        try:
            if hasattr(bridge, "mood_changed") and hasattr(bridge.mood_changed, "connect"):
                bridge.mood_changed.connect(self._on_mood_changed)
                self._connected = True
        except Exception as exc:
            _logger.debug("MaidPet 订阅 mood_changed 失败（可忽略）: %s", exc)

    def _on_mood_changed(self, state: str, reason: str) -> None:
        # 脉冲期间只缓存不打断（脉冲结束回落最新态）
        if self._pulse:
            self._pending_state = pet_expression_for(state)
            return
        new = pet_expression_for(state)
        if new != self._expr:
            self._expr = new
            self.update()

    def set_pet_expression(self, state: Optional[str]) -> None:
        """外部直设表达式（供无 bridge 场景/测试），内部仍走 5 态收敛。"""
        new = pet_expression_for(state)
        if new != self._expr:
            self._expr = new
            self.update()

    def pet_expression(self) -> str:
        return self._expr

    # v1.2 宠物造型全局开关
    def set_pet_style(self, style: Optional[str]) -> None:
        """切换造型并即时重绘：v1.4 起恒为 maid（女仆小人主形象）。

        传入 chibi / 非法值 / None 一律经 resolve_pet_style 回落 maid；
        交互/表情状态全部保留（只换渲染源，不改情绪口径），供设置页保存后调用。
        """
        new = resolve_pet_style(style)
        if new != self._style:
            self._style = new
            self.update()

    def pet_style(self) -> str:
        """当前造型（v1.4 起恒为 maid），供日志与外部查询。"""
        return self._style

    # ------------------------------------------------------------------
    # 尺寸 / 定位（窄窗折叠判定纯函数 pet_size_for_content_width）
    # ------------------------------------------------------------------
    def _track_rect_in_parent(self):
        """track_widget（内容区）在自身父坐标系下的矩形，用于右上角锚定。"""
        from PySide6.QtCore import QRect
        track = self._track
        parent = self.parentWidget()
        if parent is None:
            if track is not None:
                return QRect(0, 0, track.width(), track.height())
            return QRect(0, 0, 0, 0)
        if track is None or track is parent:
            return QRect(0, 0, parent.width(), parent.height())
        try:
            if track.parent() is parent:  # 同级兄弟：直接用其几何
                return QRect(track.pos(), track.size())
            g = track.mapToGlobal(track.rect().topLeft())
            pg = parent.mapToGlobal(parent.rect().topLeft())
            return QRect(g.x() - pg.x(), g.y() - pg.y(), track.width(), track.height())
        except Exception:
            return QRect(0, 0, parent.width(), parent.height())

    def relayout(self) -> int:
        """按内容区(track_widget)宽度更新尺寸/显隐/右上角位置，返回像素尺寸(0=隐藏)。"""
        rect = self._track_rect_in_parent()
        size = pet_size_for_content_width(rect.width())
        self._size = size
        visible = size > 0
        self.setVisible(visible)
        if not visible:
            self._hide_popup()
            self._hide_line_pop()
            return 0
        self.setFixedSize(size, size)
        margin = max(6, size // 8)
        x = max(0, rect.right() - size - margin)
        y = max(0, rect.top() + margin)
        self.move(x, y)
        self.raise_()
        return size

    def _reposition(self) -> None:
        try:
            self.relayout()
        except Exception as exc:
            _logger.debug("MaidPet 定位失败（可忽略）: %s", exc)

    def eventFilter(self, obj, event) -> bool:
        # 内容区 resize -> 重定位；popup 鼠标进出 -> 控制悬停显隐
        from PySide6.QtCore import QEvent
        if obj is self._track and event.type() == QEvent.Type.Resize:
            self._reposition()
        elif obj is self._popup and event.type() == QEvent.Type.Enter:
            self._hover_hide_armed = False
        elif obj is self._popup and event.type() == QEvent.Type.Leave:
            self._hide_popup()
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        pix = None
        # v1.2 造型分支：maid = 主形象 MaidAssets（assets/maid/）在宠物尺寸渲染；
        # chibi = 小兽管线（PetAssets）。两源缺真图均返回 None -> 中性 🔔 兜底。
        assets = self._assets
        if self._style == PET_STYLE_MAID and QT_OK:
            assets = _shared_maid_assets() or self._assets
        if assets is not None and QT_OK:
            try:
                pix = assets.pixmap_for(self._expr, self._size)
            except Exception:
                pix = None
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            if pix is not None:
                painter.drawPixmap(self.rect(), pix)
            else:
                # 兜底：形象完全不可用也不空白（画铃铛字符）
                painter.setPen(QColor("#F4C430"))
                font = painter.font()
                font.setPixelSize(max(12, self._size // 2))
                painter.setFont(font)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "🔔")
        finally:
            painter.end()

    # ------------------------------------------------------------------
    # 交互：点击脉冲 / hover popup / 回首页
    # ------------------------------------------------------------------
    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            # A-8(A3) 彩蛋闭环：companion.react_to_pet_click() -> (text, expression, cooling)
            result = None
            companion = getattr(self.app_ctx, "companion", None)
            if companion is not None and hasattr(companion, "react_to_pet_click"):
                try:
                    result = companion.react_to_pet_click()
                except Exception:
                    result = None
            feedback = interpret_pet_click_result(result, self._current_display_state())
            # 表情脉冲 + 台词浮层展示（stub/空回退走本池台词，点击永不失活）
            self._flash(expression=feedback["expression"])
            self._show_click_line(feedback["text"])
        super().mouseReleaseEvent(event)

    def _flash(self, duration_ms: int = 420, expression: str = "happy") -> None:
        """表情脉冲（点头/铃铛闪的轻量表现）；脉冲结束回落最新 mood/活动态。"""
        self._pulse = True
        self._pending_state = None
        self._expr = pet_expression_for(expression)
        self.update()
        self._pulse_timer.start(duration_ms)

    def _flash_end(self) -> None:
        self._pulse = False
        fallback = self._pending_state if self._pending_state else None
        self._expr = pet_expression_for(fallback or self._current_display_state())
        self._pending_state = None
        self.update()

    def enterEvent(self, event) -> None:
        self._hover_hide_armed = False
        self._show_popup()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        # 移到 popup 上则保持打开；否则延迟关闭
        if self._popup is not None and self._popup.isVisible() and self._popup.rect().contains(
            self._popup.mapFromGlobal(self.cursor().pos())
        ):
            self._hover_hide_armed = False
            self._hide_timer.stop()
            return
        self._hover_hide_armed = True
        self._hide_timer.start(160)
        super().leaveEvent(event)

    def _on_hover_hide(self) -> None:
        if self._hover_hide_armed:
            self._hide_popup()

    # ---- A-8(A3): 彩蛋台词浮层（瞬时台词气泡，非 hover 弹层）----
    def _ensure_line_pop(self) -> None:
        if self._line_pop is not None:
            return
        from PySide6.QtCore import Qt as _Qt
        pop = QFrame(None, _Qt.WindowType.Popup | _Qt.WindowType.FramelessWindowHint)
        pop.setObjectName("maidPetLinePop")
        pop.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground)
        body = QFrame(pop)
        body.setObjectName("petLineBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(0)
        self._line_label = QLabel()
        self._line_label.setObjectName("petLineText")
        self._line_label.setWordWrap(True)
        self._line_label.setMaximumWidth(190)
        lay.addWidget(self._line_label)
        pop_lay = QVBoxLayout(pop)
        pop_lay.setContentsMargins(0, 0, 0, 0)
        pop_lay.addWidget(body)
        self._line_pop = pop
        self._style_line_pop()

    def _style_line_pop(self) -> None:
        if self._line_pop is None:
            return
        body = self._line_pop.findChild(QFrame, "petLineBody")
        if body is not None:
            bg = self._tc("pet_bubble_bg", "#FFF5F7")
            border = self._tc("accent_light", "#FFB6C1")
            text = self._tc("text", "#5D4037")
            body.setStyleSheet(
                f"QFrame#petLineBody {{"
                f"  background: {bg}; border: 1px solid {border};"
                f"  border-radius: {self._tc('radius_md', '12px')};"
                f"}}"
                f"QLabel#petLineText {{ color: {text}; font-size: 12px;"
                f"  line-height: 1.5; background: transparent; }}"
            )

    def _show_click_line(self, text: str) -> None:
        """点击后在上方瞬时展示一句台词（无数值），约 2.4s 自动收起。"""
        text = (text or "").strip()
        if not text:
            return
        self._hide_popup()  # 避免与悬停弹层同时出现
        self._ensure_line_pop()
        if self._line_pop is None or self._line_label is None:
            return
        self._style_line_pop()
        self._line_label.setText(text)
        self._line_pop.adjustSize()
        top_left = self.mapToGlobal(self.rect().topLeft())
        pw = self._line_pop.width()
        ph = self._line_pop.height()
        px = max(4, top_left.x() + self._size // 2 - pw // 2)
        py = top_left.y() - ph - 6
        py = max(4, py)
        self._line_pop.move(px, py)
        self._line_pop.show()
        self._line_pop.raise_()
        self._line_timer.start(2400)

    def _hide_line_pop(self) -> None:
        if self._line_pop is not None:
            self._line_pop.hide()

    # ---- hover popup（心情文案 + 回首页）----
    def _tc(self, key: str, fallback: str) -> str:
        return theme_color(self.app_ctx, key, fallback)

    def _ensure_popup(self) -> None:
        if self._popup is not None:
            return
        from PySide6.QtCore import Qt as _Qt
        # Qt.Popup：显示后捕获鼠标并投递到子控件（「回首页」按钮可点），
        # 点击弹出区外自动关闭 —— 轻量 hover 弹层最稳妥形态（不做动画引擎）
        popup = QFrame(None, _Qt.WindowType.Popup | _Qt.WindowType.FramelessWindowHint)
        popup.setObjectName("maidPetTooltip")
        popup.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground)
        popup.installEventFilter(self)

        body = QFrame(popup)
        body.setObjectName("petTooltipBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        self._popup_text = QLabel()
        self._popup_text.setObjectName("petTooltipText")
        self._popup_text.setWordWrap(True)
        lay.addWidget(self._popup_text)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addStretch()
        home_btn = QPushButton("🏠 回首页")
        home_btn.setObjectName("petHomeBtn")
        home_btn.setCursor(_Qt.CursorShape.PointingHandCursor)
        home_btn.clicked.connect(self._on_go_home)
        row.addWidget(home_btn)
        lay.addLayout(row)

        popup_lay = QVBoxLayout(popup)
        popup_lay.setContentsMargins(0, 0, 0, 0)
        popup_lay.addWidget(body)
        self._popup = popup
        self._style_popup()

    def _style_popup(self) -> None:
        if self._popup is None:
            return
        body = self._popup.findChild(QFrame, "petTooltipBody")
        if body is not None:
            bg = self._tc("pet_bubble_bg", "#FFF5F7")
            border = self._tc("divider", "#F0DAE0")
            text = self._tc("text", "#5D4037")
            accent = self._tc("accent", "#FF6B9D")
            radius = self._tc("radius_md", "12px")
            body.setStyleSheet(
                f"QFrame#petTooltipBody {{"
                f"  background: {bg}; border: 1px solid {border};"
                f"  border-radius: {radius};"
                f"}}"
                f"QLabel#petTooltipText {{ color: {text}; font-size: 12px;"
                f"  line-height: 1.5; background: transparent; }}"
                f"QPushButton#petHomeBtn {{"
                f"  background: {accent}; color: #FFFFFF; border: none;"
                f"  border-radius: 10px; font-size: 11px; padding: 4px 10px;"
                f"}}"
                f"QPushButton#petHomeBtn:hover {{ background: {self._tc('accent_light', '#FF9EB5')}; }}"
            )

    def _show_popup(self) -> None:
        self._ensure_popup()
        if self._popup is None:
            return
        self._style_popup()  # 每次打开按当前主题重上色
        companion = getattr(self.app_ctx, "companion", None)
        phrase, stage, event_desc = pet_tooltip_context(companion)
        text = build_pet_tooltip(phrase, stage, event_desc)
        self._popup_text.setText(text if text else "码铃在这里陪着主人~")
        self._popup.adjustSize()
        # 定位：宠物的左上方（内容区右上角，popup 向左展开不越窗）
        top_left = self.mapToGlobal(self.rect().topLeft())
        pw = self._popup.width()
        ph = self._popup.height()
        px = top_left.x() - pw - 6
        # 防止 popup 越过屏幕左侧（贴屏幕左缘）
        px = max(4, px)
        py = top_left.y() + self._size // 2 - ph // 2
        py = max(4, py)
        self._popup.move(px, py)
        self._popup.show()
        self._popup.raise_()

    def _hide_popup(self) -> None:
        self._hover_hide_armed = False
        if self._popup is not None:
            self._popup.hide()

    def _on_go_home(self) -> None:
        self._hide_popup()
        self.go_home_requested.emit()
        # 默认处理（外部若已 connect 接管，仍可额外执行，行为幂等）
        page_manager = getattr(self.app_ctx, "page_manager", None)
        if page_manager is not None and hasattr(page_manager, "navigate"):
            try:
                page_manager.navigate("home")
            except Exception as exc:
                _logger.debug("MaidPet 回首页失败（可忽略）: %s", exc)

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------
    def hideEvent(self, event) -> None:
        self._hide_popup()
        self._hide_line_pop()
        super().hideEvent(event)


# Qt 不可用时的模块级占位（GUI 层 getattr 守卫；纯决策函数始终可用）
if not QT_OK:
    PetAssets = None  # type: ignore
    PetChibiPainter = None  # type: ignore
    MaidPet = None  # type: ignore
