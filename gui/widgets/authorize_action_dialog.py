# -*- coding: utf-8 -*-
"""v1.4(B2) 逐次授权增强弹窗（design-v14 D-V14-12 / R-G）。

与 Agent 会话级授权（agent_tools.authorize / agent_authorization_requested）语义区分：
- **仅「允许这一次 / 拒绝」**，不提供会话级/任务级放行（R-G①）；
- 展示：动作类型中文 + 目标坐标 + 坐标区域缩略截图 + type 文本**明文预览**；
- 敏感语义命中（密码/账号/卡号等关键词）额外**红字警告条** —— 诚实提示，**不做内容黑名单**
  （Q-B6 / D-V14-13），由用户自行判断；
- 拒绝即终局：不重试、不强推（沿用 Agent 授权文案口径）。
- 全部取色走 theme_color；预览图缩放安全（任意图可显示，绝不崩）。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPixmap, Qt, QFont,
    QFrame,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui.authorize_action")

ACTION_NAMES = {
    "click": "单击",
    "double_click": "双击",
    "right_click": "右键",
    "type": "输入文字",
    "hotkey": "按下快捷键",
}

#: 敏感语义关键词（仅作红字提醒，非黑名单拦截）
SENSITIVE_KEYWORDS = (
    "password", "passwd", "pwd", "secret", "token", "key", "私钥",
    "密码", "口令", "密钥", "卡号", "账号", "身份证", "ssn", "credit", "银行卡",
)


def detect_sensitive(text: str) -> Optional[str]:
    """type 文本是否命中敏感语义 → 返回提示语；无命中返回 None。"""
    t = (text or "").lower()
    if not t:
        return None
    hit = next((kw for kw in SENSITIVE_KEYWORDS if kw.lower() in t), None)
    if not hit:
        return None
    return (
        "⚠️ 这段输入看起来含敏感信息（检测到「{}」类语义）。"
        "码铃会**照原文如实输入**预览框里的内容，请先确认目标输入框与内容都正确；"
        "码铃不会记录你的输入。"
    ).format(hit)


class AuthorizeActionDialog(QDialog):
    """GUI 单步操作授权弹窗（modal）。exec_() 返回 Accepted 视为「允许这一次」。"""

    def __init__(self, action: dict, preview: Optional[QPixmap] = None, parent=None):
        super().__init__(parent)
        self._action = action or {}
        self.setWindowTitle("码铃 · 操作授权（仅这一次）")
        self.setModal(True)
        self.setMinimumWidth(440)
        self._build_ui(preview)

    # ------------------------------------------------------------------
    def _build_ui(self, preview: Optional[QPixmap]) -> None:
        accent = theme_color(self, "accent", "#FF6B9D")
        text_main = theme_color(self, "text", "#4A4A4A")
        text_sec = theme_color(self, "text_secondary", "#8A8A8A")
        warn = theme_color(self, "state_warn", "#E5A02E")
        danger = theme_color(self, "state_danger", "#D9534F")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        atype = str(self._action.get("type") or "")
        title = QLabel("码铃想执行一个电脑操作")
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color: {text_main};")
        layout.addWidget(title)

        action_label = QLabel(self._action_summary())
        action_label.setWordWrap(True)
        action_label.setStyleSheet(
            f"QLabel {{ color: {accent}; font-size: 13px; font-weight: bold; }}"
        )
        layout.addWidget(action_label)

        # 区域缩略截图（当前帧 crop，尽力显示；失败给文字占位）
        preview_label = QLabel("目标区域预览")
        preview_label.setStyleSheet(f"color: {text_sec}; font-size: 11px;")
        layout.addWidget(preview_label)
        if preview is not None and not preview.isNull():
            sc = preview.scaled(280, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            img_lbl = QLabel()
            img_lbl.setPixmap(sc)
            img_lbl.setAlignment(Qt.AlignCenter)
            img_lbl.setStyleSheet(
                f"border: 1px solid {theme_color(self, 'border', '#FFE4E1')};"
                f"border-radius: 8px; background: {theme_color(self, 'surface_muted', '#FFF9FA')};"
            )
            layout.addWidget(img_lbl)
        else:
            placeholder = QLabel("（截图预览不可用 —— 仍可基于动作与坐标判断）")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setMinimumHeight(120)
            placeholder.setStyleSheet(
                f"color: {text_sec}; font-size: 11px;"
                f"border: 1px dashed {theme_color(self, 'border', '#FFE4E1')}; border-radius: 8px;"
            )
            layout.addWidget(placeholder)

        # 坐标（逻辑虚拟桌面坐标）
        if self._action.get("x") is not None and self._action.get("y") is not None:
            pos_row = QHBoxLayout()
            pos_row.addWidget(QLabel("目标位置:"))
            pos = QLabel(f"({self._action['x']}, {self._action['y']})（屏幕逻辑坐标）")
            pos.setStyleSheet(f"color: {text_main}; font-size: 12px;")
            pos_row.addWidget(pos)
            pos_row.addStretch()
            layout.addLayout(pos_row)

        # type 明文预览（独立滚动区防长文本）
        if atype == "type":
            type_title = QLabel("将输入的文本（明文预览）:")
            type_title.setStyleSheet(f"color: {text_main}; font-size: 12px; font-weight: bold;")
            layout.addWidget(type_title)
            box = QFrame()
            box.setStyleSheet(
                f"QFrame {{ background: {theme_color(self, 'bg_light', '#FFF0F3')};"
                f" border-radius: 6px; }}"
            )
            box_l = QVBoxLayout(box)
            box_l.setContentsMargins(6, 6, 6, 6)
            txt = QLabel(self._action.get("text") or "（空）")
            txt.setWordWrap(True)
            txt.setTextInteractionFlags(Qt.TextSelectableByMouse)
            txt.setStyleSheet(
                f"color: {text_main}; font-size: 12px; font-family: Consolas, 'Microsoft YaHei';"
            )
            box_l.addWidget(txt)
            layout.addWidget(box)
            sensitive = detect_sensitive(self._action.get("text") or "")
            if sensitive:
                warn_lbl = QLabel(sensitive)
                warn_lbl.setWordWrap(True)
                warn_lbl.setStyleSheet(
                    f"color: {danger}; font-size: 11px; font-weight: bold;"
                )
                layout.addWidget(warn_lbl)
        elif atype == "hotkey":
            keys = self._action.get("keys") or []
            hk_label = QLabel("快捷键: " + " + ".join(str(k) for k in keys))
            hk_label.setStyleSheet(f"color: {text_main}; font-size: 12px;")
            layout.addWidget(hk_label)

        hint = QLabel(
            "这只是**单次**授权 —— 只执行这一下，之后每次操作都会再次询问。\n"
            "码铃不做任何键鼠记录；拒绝后码铃不会重试或强推。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {text_sec}; font-size: 10px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        allow = QPushButton("✅ 允许这一次")
        allow.setCursor(Qt.PointingHandCursor)
        allow.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: {theme_color(self, 'text_on_accent', '#FFFFFF')};"
            f" border: none; border-radius: 10px; padding: 6px 18px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {theme_color(self, 'accent_light', '#FFB6C1')}; }}"
        )
        allow.clicked.connect(self.accept)
        reject = QPushButton("拒绝")
        reject.setCursor(Qt.PointingHandCursor)
        reject.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {danger};"
            f" border: 1px solid {danger}; border-radius: 10px; padding: 6px 18px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {theme_color(self, 'bg_light', '#FFF0F3')}; }}"
        )
        reject.clicked.connect(self.reject)
        btn_row.addWidget(allow)
        btn_row.addWidget(reject)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def _action_summary(self) -> str:
        atype = str(self._action.get("type") or "unknown")
        desc = str(self._action.get("description") or "").strip()
        name = ACTION_NAMES.get(atype, atype)
        coord = ""
        if self._action.get("x") is not None and self._action.get("y") is not None:
            coord = f"，目标 (x={self._action['x']}, y={self._action['y']})"
        if desc:
            return f"【{name}】 {desc}{coord}"
        return f"【{name}】{coord}"

    # 便捷判定（供 controller 使用）
    def is_allowed(self) -> bool:
        return self.result() == QDialog.Accepted
