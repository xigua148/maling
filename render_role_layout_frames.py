# -*- coding: utf-8 -*-
"""角色页「功能入口」前后对照帧（真实平台）。

浅 ui_minimal + 深 ui_night 两版 × {整页 / 三个入口按钮区域特写}。
真实平台（**不设** QT_QPA_PLATFORM）；几何需 show()（交接文档 §2.2）。

用法：
    python render_role_layout_frames.py             # 默认 1016 宽（主窗最小 1200）
    python render_role_layout_frames.py 820         # 指定页面宽度
输出：_role_layout_frames/*.png
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
DEFAULT_PAGE_W = 1016          # 主窗最小 1200 − 侧栏 180 − splitter handle 4
PAGE_H = 800

# 最长动态文案（开场白上限 3 套 / 示例对话上限 5 组 / 提示词首行截断到 16 字）
LONGEST = {
    "prompt_entry_btn": "✏️ 编辑系统提示词  （当前：十六字人设标题示例一…）",
    "opening_entry_btn": "🎬 开场白（已配 3 套）",
    "dialogue_entry_btn": "💬 示例对话（已配 5 组）",
}


def _ctx(theme_engine):
    return SimpleNamespace(cfg=None, config=None, theme_engine=theme_engine,
                           companion=None, companion_bridge=None,
                           role_bridge=None, page_manager=None, session=None,
                           session_manager=None, weekly=None, diary=None,
                           highlights=None)


def _build(theme, page_w):
    from gui.theme_engine import ThemeEngine
    from gui.pages.page_role import PageRole

    eng = ThemeEngine()
    try:
        eng._font_choice = lambda: "resource_rounded"
    except Exception:
        pass
    eng.load_theme(theme)
    page = PageRole(_ctx(eng))
    page.resize(page_w, PAGE_H)
    page.show()
    page.ensurePolished()
    page.layout().activate()
    app.processEvents()
    for attr, txt in LONGEST.items():
        getattr(page, attr).setText(txt)
    page.prompt_count_label.setText("12345 字")
    page.ensurePolished()
    page.layout().activate()
    app.processEvents()
    return page


def _crop_around(page, w):
    """把 w 在 page 坐标系里的矩形向外扩 8px 后裁出来。"""
    r = w.rect()
    tl = w.mapTo(page, r.topLeft())
    return page.grab().copy(tl.x() - 8, tl.y() - 8, r.width() + 16, r.height() + 16)


def main():
    page_w = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PAGE_W
    os.makedirs(OUT_DIR, exist_ok=True)
    log = [f"=== 角色页功能入口帧（真实平台 / show() / 最长动态文案）page_w={page_w} ==="]

    for theme, tone in (("ui_minimal", "light"), ("ui_night", "dark")):
        page = _build(theme, page_w)

        full = os.path.join(OUT_DIR, f"role_{tone}_full.png")
        page.grab().save(full)
        log.append(f"{os.path.basename(full):<26} {page.width()}x{page.height()}")

        # 三个入口按钮各自特写
        for attr, short in (("prompt_entry_btn", "prompt"),
                            ("opening_entry_btn", "opening"),
                            ("dialogue_entry_btn", "dialogue")):
            b = getattr(page, attr)
            p = os.path.join(OUT_DIR, f"role_{tone}_{short}.png")
            _crop_around(page, b).save(p)
            fm = b.fontMetrics()
            lm = b.contentsMargins()
            iw = (b.iconSize().width() + 4) if not b.icon().isNull() else 0
            need = fm.horizontalAdvance(b.text()) + iw + lm.left() + lm.right()
            log.append(
                f"{os.path.basename(p):<26} avail={b.width():<4} need={need:<4} "
                f"h={b.height():<3} 差={need - b.width():<+5} | {b.text()!r}"
            )

        # 左栏（4 个新建/导入导出入口）
        p = os.path.join(OUT_DIR, f"role_{tone}_leftbtns.png")
        _crop_around(page, page.left_sidebar).save(p)
        log.append(f"{os.path.basename(p):<26} left_sidebar "
                   f"{page.left_sidebar.width()}x{page.left_sidebar.height()}")

        page.hide()
        page.deleteLater()
        app.processEvents()

    with open(os.path.join(OUT_DIR, "_frames.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
