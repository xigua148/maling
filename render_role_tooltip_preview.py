# -*- coding: utf-8 -*-
"""把 3 个入口按钮的 tooltip 文案「改前 / 改后」并列渲染为 PNG。

修改只影响 hover tooltip（静态帧视觉差为 0）；此脚本把 tooltip 内容
直接渲染成 QLabel（用 RichText 模拟换行），便于一眼看出差异。

输出：_role_layout_frames/role_{tone}_tooltip_preview.png
"""
from __future__ import annotations

import os, sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from gui.qt_compat import (  # noqa: E402
    QApplication, QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

app = QApplication.instance() or QApplication([])

OUT_DIR = os.path.join(ROOT, "_role_layout_frames")

ORIGINAL_PROMPT_TIP = ("点击打开大编辑框，填写/修改系统提示词\n"
                       "（决定 AI 的角色背景、性格与说话方式）")
ORIGINAL_OPENING_TIP = ("配置角色的开场白（切到该角色/新建会话时说的第一句话）\n"
                        "最多 3 套，多套之间用单独一行 --- 分隔，注入时随机选一套")
ORIGINAL_DIALOGUE_TIP = ("配置「用户-角色」示例对话（few-shot），供语气与相处方式参考\n"
                         "最多 5 组，可勾选启用/停用；注入 system 尾部，不进对话历史")

LONGEST = {
    "prompt_entry_btn": "✏️ 编辑系统提示词  （当前：十六字人设标题示例一…）",
    "opening_entry_btn": "🎬 开场白（已配 3 套）",
    "dialogue_entry_btn": "💬 示例对话（已配 5 组）",
}

ORIGINALS = {
    "prompt_entry_btn": ORIGINAL_PROMPT_TIP,
    "opening_entry_btn": ORIGINAL_OPENING_TIP,
    "dialogue_entry_btn": ORIGINAL_DIALOGUE_TIP,
}


def _build_panel(tone, title):
    box = QFrame()
    box.setObjectName("tooltipPreview")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName("roleHint")
    lay.addWidget(head)
    for attr in ("prompt_entry_btn", "opening_entry_btn", "dialogue_entry_btn"):
        cur = LONGEST[attr]
        original = ORIGINALS[attr]
        before_tip = original
        after_tip = f"{original}\n\n当前：{cur}"
        card = QFrame()
        card.setObjectName("roleSection")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 12, 12, 12)
        cl.setSpacing(4)
        btn_label = QLabel(f"按钮文字：<b>{cur}</b>")
        cl.addWidget(btn_label)
        before_label = QLabel(
            f"<b style='color:#C48A9C'>改前 tooltip：</b><br/>"
            + before_tip.replace("\n", "<br/>")
        )
        before_label.setWordWrap(True)
        cl.addWidget(before_label)
        after_label = QLabel(
            f"<b style='color:#5DA47E'>改后 tooltip：</b><br/>"
            + after_tip.replace("\n", "<br/>")
        )
        after_label.setWordWrap(True)
        cl.addWidget(after_label)
        lay.addWidget(card)
    return box


def main():
    from gui.theme_engine import ThemeEngine

    os.makedirs(OUT_DIR, exist_ok=True)
    log = []
    for theme, tone in (("ui_minimal", "light"), ("ui_night", "dark")):
        eng = ThemeEngine()
        try:
            eng._font_choice = lambda: "resource_rounded"
        except Exception:
            pass
        eng.load_theme(theme)
        panel = _build_panel(tone, f"角色页入口按钮 · tooltip 对照 · {theme}")
        panel.resize(720, 720)
        panel.show()
        panel.ensurePolished()
        if panel.layout() is not None:
            panel.layout().activate()
        app.processEvents()
        path = os.path.join(OUT_DIR, f"role_{tone}_tooltip_preview.png")
        panel.grab().save(path)
        log.append(f"{os.path.basename(path):<40} {panel.width()}x{panel.height()}")
        panel.hide()
        panel.deleteLater()
        app.processEvents()

    with open(os.path.join(OUT_DIR, "_frames.txt"), "a", encoding="utf-8") as f:
        f.write("\n=== 改前/改后 tooltip 文案对照 ===\n" + "\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()