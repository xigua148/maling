# -*- coding: utf-8 -*-
"""阶段 C-1 交付帧：侧栏滚动条 hover 门控 —— 浅/深 × {空闲 / 悬停 / 滚动中} 共 6 张。

真实平台（不设 QT_QPA_PLATFORM）；为拿到正确 viewport 几何必须 show()（否则
viewport 为常量，滚动条几何失真，见交接文档 §2.2）。grab() 落盘后 hide()。

输出：_phaseC1_frames/c1_{light|dark}_{idle|hover|scrolling}.png
用法：python render_phaseC1_frames.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from gui.qt_compat import QApplication  # noqa: E402

OUT_DIR = os.path.join(ROOT, "_phaseC1_frames")
WIDTH, HEIGHT = 180, 560

app = QApplication.instance() or QApplication([])


def _bare_ctx():
    return SimpleNamespace(cfg=None, config=None, theme_engine=None, companion=None,
                           companion_bridge=None, role_bridge=None, page_manager=None)


def main():
    from gui.theme_engine import ThemeEngine
    from gui.widgets.sidebar import SidebarWidget

    os.makedirs(OUT_DIR, exist_ok=True)
    log = []
    for theme, tone in (("ui_minimal", "light"), ("ui_night", "dark")):
        eng = ThemeEngine()
        eng._font_choice = lambda: "resource_rounded"
        eng.load_theme(theme)

        for state in ("idle", "hover", "scrolling"):
            side = SidebarWidget(_bare_ctx())
            side.resize(WIDTH, HEIGHT)
            side.show()
            side.ensurePolished()
            if side.layout() is not None:
                side.layout().activate()
            app.processEvents()

            lw = side.list_widget
            sb = lw.verticalScrollBar()

            # 复位门控态
            side._scrollbar_hover = False
            side._scrollbar_scrolling = False
            if state == "scrolling":
                # 滚到中段，handle 落在轨道中部（可见）
                sb.setValue(max(1, sb.maximum() // 2))
                side._on_scrollbar_scrolled(sb.value())
            elif state == "hover":
                side._scrollbar_hover = True
            side._apply_scrollbar_visibility()
            app.processEvents()

            path = os.path.join(OUT_DIR, f"c1_{tone}_{state}.png")
            side.grab().save(path)
            log.append(
                f"{os.path.basename(path):<26} theme={theme:<10} state={state:<9} "
                f"viewport={lw.viewport().width()}x{lw.viewport().height()} "
                f"sb.width={sb.width()} sb.value={sb.value()}/{sb.maximum()} "
                f"prop={sb.property('sidebarHover')}"
            )
            side.hide()
            side.deleteLater()
            app.processEvents()

    with open(os.path.join(OUT_DIR, "_frames.txt"), "w", encoding="utf-8") as f:
        f.write("=== 阶段 C-1 侧栏滚动条帧清单 ===\n" + "\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
