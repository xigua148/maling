# -*- coding: utf-8 -*-
"""空状态 label（#roleEmptyState）截断修复前后对照帧。

「改前」= 把 wordWrap 关回 False（即修复前的既有行为）；「改后」= 当前代码。
真实平台（不设 QT_QPA_PLATFORM）+ show()；清空角色列表让空状态 label 显形。

输出：_role_layout_frames/empty_{light|dark}_{before|after}.png
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from gui.qt_compat import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

OUT_DIR = os.path.join(ROOT, "_role_layout_frames")


def _ctx(theme_engine):
    return SimpleNamespace(cfg=None, config=None, theme_engine=theme_engine,
                           companion=None, companion_bridge=None,
                           role_bridge=None, page_manager=None, session=None,
                           session_manager=None, weekly=None, diary=None,
                           highlights=None)


def _grab_sidebar(page):
    """裁左栏（220 宽）上半：含标题 + 4 个按钮 + 空状态 label。"""
    r = page.left_sidebar.rect()
    return page.grab().copy(0, 0, r.width(), r.height())


def main():
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_role import PageRole

    os.makedirs(OUT_DIR, exist_ok=True)
    log = ["=== 空状态 label（#roleEmptyState）截断修复前后对照（真实平台 / show()）==="]

    for theme, tone in (("ui_minimal", "light"), ("ui_night", "dark")):
        eng = ThemeEngine()
        try:
            eng._font_choice = lambda: "resource_rounded"
        except Exception:
            pass
        eng.load_theme(theme)

        for variant, wrap in (("before", False), ("after", True)):
            page = PageRole(_ctx(eng))
            page.resize(1016, 800)
            page.show()
            page.ensurePolished()
            page.layout().activate()
            app.processEvents()

            # 清空角色 → 空状态 label 显形（保留空的 role_list 占位，让 label 取自然高）
            page.role_list.clear()
            page.empty_label.setVisible(True)
            page.empty_label.setWordWrap(wrap)
            page.ensurePolished()
            page.layout().activate()
            app.processEvents()

            fm = page.empty_label.fontMetrics()
            lm = page.empty_label.contentsMargins()
            tw = fm.horizontalAdvance(page.empty_label.text())
            avail = page.empty_label.width()
            hint = page.empty_label.sizeHint().width()
            h = page.empty_label.height()

            path = os.path.join(OUT_DIR, f"empty_{tone}_{variant}.png")
            _grab_sidebar(page).save(path)
            log.append(
                f"{os.path.basename(path):<26} wordWrap={str(wrap):<5} "
                f"avail={avail:<4} textW={tw:<4} sizeHint={hint:<4} "
                f"hint差={hint - avail:<+5} h={h:<3} | {page.empty_label.text()!r}"
            )
            page.hide()
            page.deleteLater()
            app.processEvents()

    with open(os.path.join(OUT_DIR, "_frames.txt"), "a", encoding="utf-8") as f:
        f.write("\n" + "\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
