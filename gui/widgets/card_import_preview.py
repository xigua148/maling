"""gui/widgets/card_import_preview.py —— v1.8(F5/D-V18-06) 角色卡导入预览弹窗。

收编 v1.7 Q-C10 遗留（预览确认页列 v1.7.x）。逐项呈现角色卡字段：
名称 / 描述 / 系统提示词摘要 / 性格三值（**档位词「偏上·适中·偏低」，不显
数值**，R-A）/ 开场白套数 / 示例对话组数 / 封面缩略图。

- 封面缺失或超限等异常字段**逐项红字** +「仍要导入」显式确认（Q-D7）；
- 名称冲突提示：传入 existing_names → 展示 dedupe_import_name 收敛后的
  最终名（「XX（导入）」），确认后由调用方（page_role）照此落盘；
- 对齐链零语义变更：本弹窗只替换确认交互，导入落盘逻辑由 page_role 既有
  链完成（create_role + save_role 不动）。
"""
from __future__ import annotations

import base64 as _b64
from typing import List, Optional

from gui.qt_compat import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPalette, QPixmap,
    QPushButton, Qt, QVBoxLayout,
)
from gui.role_card import (
    COVER_MAX_B64_BYTES, MAX_CARD_BYTES, dedupe_import_name,
    personality_tier_word,
)
from gui.utils import theme_color
from gui import icons

__all__ = ["CardImportPreviewDialog", "resolve_theme_source"]

_DESC_SUMMARY_CHARS = 80     # 描述/提示词摘要截断字数


def _truncate(text: str, limit: int = _DESC_SUMMARY_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


class _PaletteThemeEngine:
    """无 app_ctx 时的兜底主题源（接口与 ThemeEngine.get_color 同形）。

    v2.2(缺陷2/3)：``theme_color(app_ctx, key, fallback)`` 只认
    ``app_ctx.theme_engine.get_color``。弹窗若既没有 parent 链上下文、也不在带
    ``app_ctx`` 的窗口树里（独立审计探针就是这种情形），此前会逐键回落**硬编码
    浅色**，深色主题下正文色掉到 2.0。这里改为取控件 polish 后的调色板 ——
    全局 QSS 已把当前主题刷进去（实测 ``WindowText`` = 主题 text、
    ``Window`` = 主题底色），因此兜底也随主题。
    """

    #: 语义前景键 → 用调色板正文色
    _FG_KEYS = frozenset({
        "text", "text_secondary", "text_hint", "accent", "accent_text",
        "primary", "primary_dark", "info", "warning", "state_warn",
        "state_ok", "focus_accent",
    })
    #: 语义底色键（含「实底按钮上的字」）→ 用调色板窗口底色
    _BG_KEYS = frozenset({
        "bg", "bg_card", "bg_light", "surface_muted", "secondary", "chat_bg",
        "accent_light", "disabled_bg", "border", "divider", "pet_bubble_bg",
        "text_on_accent",
    })

    def __init__(self, widget=None):
        self.theme_engine = self
        self._widget = widget
        self._palette = None

    def _pal(self):
        if self._palette is None:
            pal = None
            try:
                if self._widget is not None:
                    self._widget.ensurePolished()
                    pal = self._widget.palette()
            except Exception:
                pal = None
            self._palette = pal
        return self._palette

    def get_color(self, color_key: str, fallback=None) -> str:
        pal = self._pal()
        if pal is not None:
            if color_key in self._FG_KEYS:
                return pal.color(QPalette.WindowText).name()
            if color_key in self._BG_KEYS:
                return pal.color(QPalette.Window).name()
        return fallback if fallback is not None else "#000000"


def resolve_theme_source(start=None):
    """定位可用于 ``theme_color`` 的取色源。

    顺序：显式 ``start`` 自身/祖先链上的 ``app_ctx`` → 顶层窗口上的 ``app_ctx``
    → 兜底 ``_PaletteThemeEngine``（读控件调色板里的当前主题色）。永不返回 None。
    """
    seen = set()
    node = start
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        for attr in ("app_ctx", "_app_ctx"):
            ctx = getattr(node, attr, None)
            if ctx is not None and getattr(ctx, "theme_engine", None) is not None:
                return ctx
        if getattr(node, "theme_engine", None) is not None:
            return node
        node = node.parent() if hasattr(node, "parent") else None
    try:
        app = QApplication.instance()
        if app is not None:
            candidates = list(app.topLevelWidgets())
            active = app.activeWindow()
            if active is not None:
                candidates.insert(0, active)
            for w in candidates:
                for attr in ("app_ctx", "_app_ctx"):
                    ctx = getattr(w, attr, None)
                    if ctx is not None and getattr(ctx, "theme_engine", None) is not None:
                        return ctx
                if getattr(w, "theme_engine", None) is not None:
                    return w
    except Exception:
        pass
    return _PaletteThemeEngine(start)


class CardImportPreviewDialog(QDialog):
    """角色卡导入预览（字段逐项 + 封面缩略 + 冲突改名提示 + 确认/取消）。"""

    def __init__(self, card: dict, existing_names: Optional[List[str]] = None,
                 parent=None, app_context=None):
        super().__init__(parent)
        # v2.2(缺陷2)：接上取色链路 —— 显式入参优先，其次沿 parent 链找
        #   （page_role 带 app_ctx），再退到顶层窗口，最后回落调色板兜底源。
        self._app_ctx = resolve_theme_source(app_context or self)
        self.setWindowTitle("导入角色卡预览")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.card = card
        self.final_name = dedupe_import_name(
            str(card.get("name", "")), existing_names or [])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(8)

        head = QLabel("导入前请确认这张角色卡的内容：")
        head.setObjectName("cardPreviewHead")
        lay.addWidget(head)

        rows = self._build_rows()
        for label_text, value_widget in rows:
            row = QHBoxLayout()
            key = QLabel(label_text)
            key.setObjectName("cardPreviewKey")
            key.setFixedWidth(96)
            key.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            row.addWidget(key)
            row.addWidget(value_widget, 1)
            lay.addLayout(row)

        # 名称冲突提示（dedupe_import_name 既有逻辑衔接）
        if self.final_name != card.get("name"):
            tip = QLabel(f"已有同名角色，将自动改名为「{self.final_name}」导入。")
            tip.setObjectName("cardPreviewWarn")
            tip.setWordWrap(True)
            lay.addWidget(tip)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("确认导入")
        ok_btn.setObjectName("cardPreviewOk")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("cardPreviewCancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        self._apply_style()

    # -- 字段逐项 --
    def _build_rows(self):
        card = self.card
        rows = []
        p = card.get("personality") or {}

        rows.append(("角色名称", QLabel(str(card.get("name", "")))))
        # v1.9(C/D-V19-01): 名字（空 = 无名字 → 自称"我"）
        _given = (card.get("given_name") or "").strip()
        rows.append(("角色名字", QLabel(_given if _given else "（未设置，自称「我」）")))
        rows.append(("角色描述", QLabel(_truncate(card.get("description") or "") or "（空）")))
        rows.append(("提示词摘要", QLabel(_truncate(card.get("system_prompt") or "") or "（空）")))
        rows.append((
            "性格参数",
            QLabel(
                f"活泼{personality_tier_word(p.get('lively', 50))} · "
                f"严谨{personality_tier_word(p.get('rigorous', 50))} · "
                f"贴心{personality_tier_word(p.get('caring', 50))}"
            ),
        ))
        rows.append(("开场白", QLabel(f"{len(card.get('opening_lines') or [])} 套")))
        rows.append(("示例对话", QLabel(f"{len(card.get('example_dialogues') or [])} 组")))

        # 封面缩略 / 异常红字（R-I：卡文件含 base64 属 v2 设计明确允许）
        rows.append(("封面", self._cover_widget(card.get("cover_image") or "")))
        return rows

    def _cover_widget(self, cover_uri: str) -> QLabel:
        lab = QLabel()
        lab.setWordWrap(True)
        if not cover_uri:
            lab.setText("（无封面，角色列表将回退默认头像）")
            return lab
        try:
            raw = _b64.b64decode(cover_uri.split(",", 1)[1])
            pix = QPixmap()
            if not pix.loadFromData(raw):
                raise ValueError("解码失败")
            lab.setPixmap(pix.scaled(
                96, 96,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            lab.setToolTip(f"内嵌封面 {len(cover_uri.encode('utf-8')) // 1024} KB")
        except Exception:
            # 超限/非法封面：parse_card 已降级为空或数据损坏 → 红字 + 仍可导入
            lab.setObjectName("cardPreviewError")
            lab.setText(f"{icons.text_glyph('warning', '⚠')} 封面数据异常（超过 500KB 或已损坏），"
                        "导入后将以无封面回退默认头像。\n确认后仍可继续导入。")
        return lab

    # -- 样式 --
    def _apply_style(self) -> None:
        # v2.2(缺陷2)：文字/次要文字改走主题令牌 —— 硬编码深棕 #5D4037 在深色
        #   主题（#131114）上只有 2.016，近不可见；警告/异常红同样改走令牌。
        src = self.app_ctx_color()
        text = theme_color(src, "text", "#3A3A3A")
        secondary = theme_color(src, "text_secondary", "#8A8A8A")
        warn = theme_color(src, "warning", "#A06411")
        error = theme_color(src, "state_danger", "#C0392B")
        self.setStyleSheet(
            f"QLabel#cardPreviewHead {{ color: {secondary}; font-size: 12px; }}"
            f"QLabel#cardPreviewKey {{ color: {secondary}; font-size: 12px; }}"
            f"QLabel#cardPreviewWarn {{ color: {warn}; font-size: 12px; }}"
            f"QLabel#cardPreviewError {{ color: {error}; font-size: 12px; }}"
            f"QLabel {{ color: {text}; font-size: 13px; }}"
        )

    def app_ctx_color(self):
        """``theme_color(app_ctx, ...)`` 适配入口：已解析的取色源（永不为 None）。"""
        return getattr(self, "_app_ctx", None)
