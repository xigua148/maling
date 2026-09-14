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
    QDialog, QFrame, QHBoxLayout, QLabel, QPixmap, QPushButton, Qt,
    QVBoxLayout,
)
from gui.role_card import (
    COVER_MAX_B64_BYTES, MAX_CARD_BYTES, dedupe_import_name,
    personality_tier_word,
)
from gui.utils import theme_color
from gui import icons

__all__ = ["CardImportPreviewDialog"]

_DESC_SUMMARY_CHARS = 80     # 描述/提示词摘要截断字数


def _truncate(text: str, limit: int = _DESC_SUMMARY_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


class CardImportPreviewDialog(QDialog):
    """角色卡导入预览（字段逐项 + 封面缩略 + 冲突改名提示 + 确认/取消）。"""

    def __init__(self, card: dict, existing_names: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
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
        text = theme_color(self.app_ctx_color(), "text", "#5D4037")
        secondary = theme_color(self.app_ctx_color(), "text_secondary", "#8A8A8A")
        warn = theme_color(self.app_ctx_color(), "warning", "#E6A23C")
        error = "#D9534F"
        self.setStyleSheet(
            f"QLabel#cardPreviewHead {{ color: {secondary}; font-size: 12px; }}"
            f"QLabel#cardPreviewKey {{ color: {secondary}; font-size: 12px; }}"
            f"QLabel#cardPreviewWarn {{ color: {warn}; font-size: 12px; }}"
            f"QLabel#cardPreviewError {{ color: {error}; font-size: 12px; }}"
            f"QLabel {{ color: {text}; font-size: 13px; }}"
        )

    def app_ctx_color(self):  # theme_color(app_ctx, ...) 适配：弹窗无 app_ctx
        return None
