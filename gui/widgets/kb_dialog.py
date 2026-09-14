"""kb_dialog.py —— 知识库最小可用对话框（v1.5.0）

审计结论（docs/audit-功能真实性清单-2026-09-07.md #C1）：KnowledgeBase 能力本体
（index_directory / search / status）实测可用，但 GUI 全树零引用 —— 空壳。
本对话框补上 GUI 入口：选目录建索引 + 关键词检索（top3：路径 + 摘要）。

后端：helpers.KnowledgeBase（helpers.py:363 search），索引文件沿用
AppConfig.kb_index_file（默认 cwd/kb_index.json，与 CLI /kb 同一份）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QPlainTextEdit, QFileDialog, Qt,
)

try:
    from gui.utils import theme_color
except Exception:  # 主题工具缺失时对话框仍可用（内置兜底色）
    theme_color = None

logger = logging.getLogger("maid_coder.gui")


class KnowledgeBaseDialog(QDialog):
    """知识库：选目录 → 建立索引 → 检索（最小可用，不做大页面）。"""

    def __init__(self, app_ctx, parent=None):
        super().__init__(parent or None)
        self.app_ctx = app_ctx
        self.setWindowTitle("码铃 · 知识库")
        self.resize(560, 420)
        self._kb = None

        self._accent = self._tc("accent", "#FF6B9D")
        self._bg = self._tc("bg_card", "#FFFFFF")
        self._border = self._tc("border", "#FFE4E1")
        self._text = self._tc("text", "#5D4037")
        self._text2 = self._tc("text_secondary", "#888888")

        self.setStyleSheet(
            f"QDialog {{ background: {self._tc('bg', '#FFF5F5')}; }}"
            f"QLabel {{ color: {self._text}; }}"
            f"QLineEdit, QPlainTextEdit {{"
            f"  background: {self._bg}; color: {self._text};"
            f"  border: 1px solid {self._border}; border-radius: 8px; padding: 6px;"
            f"}}"
            f"QPushButton {{"
            f"  background: {self._bg}; color: {self._accent};"
            f"  border: 1px solid {self._accent}; border-radius: 8px; padding: 6px 14px;"
            f"}}"
            f"QPushButton:hover {{ background: {self._tc('bg_light', '#FFF0F3')}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("📚 本地知识库")
        f = title.font()
        f.setBold(True)
        f.setPointSize(12)
        title.setFont(f)
        layout.addWidget(title)

        # -- 第一行：目录选择 + 建立索引 --
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("选择要索引的文件夹（.md/.txt/.py 等）")
        dir_row.addWidget(self.dir_edit, 1)
        pick_btn = QPushButton("📁 选目录")
        pick_btn.clicked.connect(self._on_pick_dir)
        dir_row.addWidget(pick_btn)
        index_btn = QPushButton("🔍 建立索引")
        index_btn.clicked.connect(self._on_index)
        dir_row.addWidget(index_btn)
        layout.addLayout(dir_row)

        # -- 第二行：搜索框 --
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入关键词检索知识库…")
        self.search_edit.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_edit, 1)
        self.search_btn = QPushButton("搜索")
        self.search_btn.clicked.connect(self._on_search)
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)

        # -- 结果区 --
        self.result_view = QPlainTextEdit()
        self.result_view.setReadOnly(True)
        self.result_view.setMinimumHeight(180)
        layout.addWidget(self.result_view, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {self._text2}; font-size: 12px;")
        layout.addWidget(self.status_label)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        # 初始化后端（失败不崩，状态栏提示）
        self._init_kb()
        self._refresh_status()

    # ------------------------------------------------------------------
    def _tc(self, key: str, fallback: str) -> str:
        if theme_color is None:
            return fallback
        try:
            return str(theme_color(self.app_ctx, key, fallback))
        except Exception:
            return fallback

    def _init_kb(self) -> None:
        """按 AppConfig.kb_index_file（缺省 cwd/kb_index.json）实例化 KnowledgeBase。"""
        try:
            from helpers import KnowledgeBase
            cfg = getattr(self.app_ctx, "cfg", None)
            index_file = str(getattr(cfg, "kb_index_file", "") or "kb_index.json")
            self._kb = KnowledgeBase(index_file)
        except Exception as exc:
            self._kb = None
            logger.warning("KnowledgeBase 初始化失败: %s", exc)
            self.status_label.setText(f"知识库初始化失败：{exc}")

    def _refresh_status(self) -> None:
        if self._kb is not None:
            try:
                self.status_label.setText(self._kb.status())
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _on_pick_dir(self) -> None:
        start = self.dir_edit.text().strip() or str(Path.cwd())
        chosen = QFileDialog.getExistingDirectory(self, "选择要索引的目录", start)
        if chosen:
            self.dir_edit.setText(chosen)

    def _on_index(self) -> None:
        directory = self.dir_edit.text().strip()
        if not directory:
            self.status_label.setText("请先选择要索引的目录。")
            return
        if self._kb is None:
            self._init_kb()
            if self._kb is None:
                return
        try:
            msg = self._kb.index_directory(directory)
            # index_directory 返回带 ANSI 色码的字符串，给 GUI 用先粗略去色
            clean = msg.replace("\033[92m", "").replace("\033[93m", "").replace("\033[0m", "")
            self.result_view.setPlainText(clean)
        except Exception as exc:
            self.result_view.setPlainText(f"建立索引失败：{exc}")
        self._refresh_status()

    def _on_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            self.status_label.setText("请输入检索关键词。")
            return
        if self._kb is None:
            self._init_kb()
            if self._kb is None:
                return
        try:
            results = self._kb.search(query, top_k=3)
        except Exception as exc:
            self.result_view.setPlainText(f"检索失败：{exc}")
            return
        if not results:
            self.result_view.setPlainText(f"未找到与「{query}」相关的内容。\n（可先对文档目录「建立索引」）")
            return
        lines = ["📚 检索结果（Top %d）：" % len(results)]
        for path, chunk, score in results:
            lines.append("")
            lines.append(f"[{path}]（相关度 {score:.3f}）")
            lines.append(f"  {chunk[:300]}")
        self.result_view.setPlainText("\n".join(lines))
