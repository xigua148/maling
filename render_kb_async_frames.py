# -*- coding: utf-8 -*-
"""render_kb_async_frames.py —— 批 1（KB 异步化）交付对照帧。

真实平台（**不设 QT_QPA_PLATFORM**）；按 MEMORY §五：测"文字/字形是否渲染"必须真实
平台且**不要 show()** —— `resize()` + `ensurePolished()` + `layout().activate()` +
`processEvents()` + `grab()`。

浅（ui_minimal）× 深（ui_night）× 4 态：
  ① 空闲态  ② 建索引进行中  ③ 检索进行中  ④ off 档静态文案

输出：_kb_async_frames/kb_{light|dark}_{idle|indexing|searching|off}.png
用法：python render_kb_async_frames.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from gui.qt_compat import QApplication  # noqa: E402

OUT_DIR = os.path.join(ROOT, "_kb_async_frames")
WIDTH, HEIGHT = 560, 420

app = QApplication.instance() or QApplication([])


def _build_index() -> str:
    """造一个小索引文件，让空闲态状态栏有真实内容。"""
    from helpers import KnowledgeBase

    tmp = Path(tempfile.mkdtemp(prefix="render_kb_async_"))
    corpus = tmp / "corpus"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "a.md").write_text(
        "码铃知识库语料：异步加载、线程、进度反馈。Hello async loading.\n" * 20,
        encoding="utf-8",
    )
    (corpus / "b.md").write_text(
        "另一篇文档：检索中、文字节奏、融入度。Ripple is an alien motif.\n" * 20,
        encoding="utf-8",
    )
    index_file = str(tmp / "kb_index.json")
    KnowledgeBase(index_file).index_directory(str(corpus))
    return index_file


def _prepare(dlg):
    dlg.resize(WIDTH, HEIGHT)
    dlg.ensurePolished()
    if dlg.layout() is not None:
        dlg.layout().activate()
    app.processEvents()


def main():
    from gui.theme_engine import ThemeEngine
    from gui.widgets.kb_dialog import KnowledgeBaseDialog
    import gui.motion as motion

    os.makedirs(OUT_DIR, exist_ok=True)
    index_file = _build_index()
    log = []

    for theme, tone in (("ui_minimal", "light"), ("ui_night", "dark")):
        eng = ThemeEngine()
        eng._font_choice = lambda: "resource_rounded"
        eng.load_theme(theme)
        ctx = SimpleNamespace(
            cfg=SimpleNamespace(kb_index_file=index_file),
            config=None, theme_engine=eng,
        )

        for state in ("idle", "indexing", "searching", "off"):
            motion.configure("off" if state == "off" else "standard")
            dlg = KnowledgeBaseDialog(ctx)
            _prepare(dlg)

            if state == "indexing":
                dlg.dir_edit.setText("D:/示例/知识库目录")
                dlg._start_busy("正在建立索引")
            elif state == "searching":
                dlg.search_edit.setText("异步加载")
                dlg._start_busy("检索中")
            elif state == "off":
                dlg.dir_edit.setText("D:/示例/知识库目录")
                dlg._start_busy("正在建立索引")     # off → 静态文案
            _prepare(dlg)

            path = os.path.join(OUT_DIR, f"kb_{tone}_{state}.png")
            dlg.grab().save(path)
            log.append(
                f"{os.path.basename(path):<26} theme={theme:<10} state={state:<9} "
                f"motion={motion.level():<8} loop={motion.running_loop_count()} "
                f"status=\"{dlg.status_label.text()}\""
            )
            # 收尾：停循环（不 show() → 直接 dispose）
            dlg._stop_busy()
            dlg.deleteLater()
            app.processEvents()
        motion.configure("standard")

    with open(os.path.join(OUT_DIR, "_frames.txt"), "w", encoding="utf-8") as f:
        f.write("=== 批 1 · KB 异步化对照帧清单 ===\n" + "\n".join(log) + "\n")
    print("\n".join(log))


if __name__ == "__main__":
    main()
