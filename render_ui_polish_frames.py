# -*- coding: utf-8 -*-
"""render_ui_polish_frames.py —— UI 打磨（粉色软化 + 气泡姓名改人名）交付对照帧。

真实平台（**不设 QT_QPA_PLATFORM**）；按 MEMORY §五：测"文字/字形是否渲染"必须真实
平台且**不要 show()** —— `resize()` + `ensurePolished()` + `layout().activate()` +
`processEvents()` + `grab()`。

两主题 × 两版 × 两屏：
  主题：ui_minimal（默认，本次改色）/ ui_night（对照，本次不改主题色）
  版本：before（改前：深粉 #E0457B + 裸色姓名 + 姓名显示「女仆」）
        after （改后：软化粉 #C3557C + 主题色姓名 + 姓名显示人名「小铃」）
  屏  ：chat（气泡姓名 + 主色按钮）/ sidebar（侧栏导航）

「改前」由脚本**临时补丁**还原（不动磁盘源）：
  · ThemeEngine.THEME_DEFINITIONS["ui_minimal"]["colors"] 回写旧粉值；
  · 气泡 nameLabel 回写旧裸色 + 旧文案「女仆」。

输出：_ui_polish_frames/ui_{minimal|night}_{before|after}_{chat|sidebar}.png
      _ui_polish_frames/_frames.txt
用法：python render_ui_polish_frames.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from gui.qt_compat import (  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

app = QApplication.instance() or QApplication([])

OUT_DIR = os.path.join(ROOT, "_ui_polish_frames")

# 说明：after 帧走**真实** resolve_default_speaker_name 全链路（given_name →
# ROLE_PRESETS 预设表 → 「码铃」）。用户本机的 role_maid.json 无 given_name 字段，
# 第 2 级预设兜底命中「温柔女仆→小铃」，故无需任何 monkeypatch 即可显示「小铃」。

# 改前 ui_minimal 的旧粉值（只用于 before 帧的临时补丁；磁盘源已是新值）
_OLD_MINIMAL_COLORS = {
    "primary": "#E0457B", "primary_dark": "#C0335F", "secondary": "#FCEEF4",
    "accent": "#E0457B", "accent_light": "#FCEEF4",
    "bg_light": "#FCEEF4", "focus_accent": "#E0457B",
    "pet_bubble_bg": "#FCEEF4",
}
# 改前 message_bubble.py:501-503 的旧裸色（用户侧 / AI 侧）
_OLD_NAME_COLOR_USER = "#FF9EB5"
_OLD_NAME_COLOR_AI = "#FF6B9D"
_OLD_AI_NAME_TEXT = "女仆"


def _ctx(eng):
    return SimpleNamespace(
        cfg=None, config=None, theme_engine=eng,
        companion=None, companion_bridge=None, role_bridge=None,
        page_manager=None, session=None, session_manager=None,
        weekly=None, diary=None, highlights=None, tts=None,
        gui_session=None, chat_service=None, tray_manager=None,
    )


def _prepare(w, width, height):
    w.resize(width, height)
    w.ensurePolished()
    if w.layout() is not None:
        w.layout().activate()
    app.processEvents()


def _bubble(ctx, role, text, is_consecutive=False, speaker_name=None):
    import gui.widgets.message_bubble as mb
    b = mb.MessageBubble(
        role, text,
        is_consecutive=is_consecutive,
        max_bubble_width=520,
        app_context=ctx,
        speaker_name=speaker_name,
    )
    _prepare(b, 720, 120)
    return b


def _revert_name_label(bubble, is_user):
    """把气泡姓名区还原成改前观感（裸色 + 人设标签「女仆」）。"""
    from PySide6.QtWidgets import QLabel
    lab = bubble.findChild(QLabel, "nameLabel")
    if lab is None:
        return
    color = _OLD_NAME_COLOR_USER if is_user else _OLD_NAME_COLOR_AI
    text = "主人" if is_user else _OLD_AI_NAME_TEXT
    lab.setText(text)
    lab.setStyleSheet(
        f"QLabel {{ font-size: 12px; font-weight: 500; color: {color}; padding: 0 4px; }}"
    )


def _patch_speaker_name(enable: bool):
    """after 模式：清一次人名缓存，走真实解析链路（无 monkeypatch）。"""
    import gui.widgets.message_bubble as mb
    mb.invalidate_default_speaker_name()


def _build_chat(ctx, before: bool):
    """聊天主界面：主色按钮 + 用户/AI 气泡（AI 姓名区可见）。"""
    w = QWidget()
    root = QVBoxLayout(w)
    root.setContentsMargins(16, 16, 16, 16)
    root.setSpacing(10)

    head = QHBoxLayout()
    for label, obj in (("＋ 新建会话", ""), ("⚙ 设置", "")):
        btn = QPushButton(label)
        if obj:
            btn.setObjectName(obj)
        head.addWidget(btn)
    head.addStretch()
    send = QPushButton("发送")
    send.setObjectName("primaryBtn")
    head.addWidget(send)
    root.addLayout(head)

    u = _bubble(ctx, "user", "帮我把默认主题的粉色调柔和一点，不要太扎眼。", True and False)
    a1 = _bubble(ctx, "assistant", "好的主人，我把主色的饱和度降下来了，白字对比度还提高了呢 (◕‿◕)")
    a2 = _bubble(ctx, "assistant", "另外，我的名字现在会正确显示成「小铃」啦～", True)
    if before:
        _revert_name_label(u, True)
        _revert_name_label(a1, False)
    for b in (u, a1, a2):
        root.addWidget(b)
    root.addStretch()
    _prepare(w, 780, 420)
    return w


def _build_sidebar(ctx, before: bool):
    from gui.widgets.sidebar import SidebarWidget
    s = SidebarWidget(ctx)
    _prepare(s, 180, 600)
    return s


def _engine(theme: str, before: bool):
    from gui.theme_engine import ThemeEngine

    eng = ThemeEngine()
    try:
        eng._font_choice = lambda: "resource_rounded"
    except Exception:
        pass
    restore = None
    if before and theme == "ui_minimal":
        colors = ThemeEngine.THEME_DEFINITIONS["ui_minimal"]["colors"]
        restore = {k: colors.get(k) for k in _OLD_MINIMAL_COLORS}
        colors.update(_OLD_MINIMAL_COLORS)
    eng.load_theme(theme)
    return eng, restore


def _restore(eng, restore):
    if restore is None:
        return
    from gui.theme_engine import ThemeEngine
    ThemeEngine.THEME_DEFINITIONS["ui_minimal"]["colors"].update(restore)


def main():
    from gui.theme_engine import ThemeEngine

    os.makedirs(OUT_DIR, exist_ok=True)
    log = ["=== UI 打磨对照帧（真实平台 / 不 show()）==="]

    for theme, tone in (("ui_minimal", "minimal"), ("ui_night", "night")):
        for variant in ("before", "after"):
            before = variant == "before"
            _patch_speaker_name(not before)
            eng, restore = _engine(theme, before)
            ctx = _ctx(eng)
            try:
                c = ThemeEngine.THEME_DEFINITIONS[theme]["colors"]
                log.append(
                    f"[{tone}/{variant}] primary={eng.get_color('primary')} "
                    f"primary_dark={eng.get_color('primary_dark')} "
                    f"accent_light={eng.get_color('accent_light')} "
                    f"(def: {c.get('primary')})"
                )
                for screen, builder in (("chat", _build_chat), ("sidebar", _build_sidebar)):
                    w = builder(ctx, before)
                    _prepare(w, w.width(), w.height())
                    name = f"ui_{tone}_{variant}_{screen}.png"
                    path = os.path.join(OUT_DIR, name)
                    w.grab().save(path)
                    size = f"{w.width()}x{w.height()}"
                    if screen == "chat":
                        from PySide6.QtWidgets import QLabel
                        labs = [l.text() for l in w.findChildren(QLabel, "nameLabel")]
                        size += f"  nameLabel={labs}"
                    log.append(f"  {name:<32} {size}")
                    w.deleteLater()
                    app.processEvents()
            finally:
                _restore(eng, restore)

    log.append(f"generated_at={datetime.now().isoformat(timespec='seconds')}")
    with open(os.path.join(OUT_DIR, "_frames.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
