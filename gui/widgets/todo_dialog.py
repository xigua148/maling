"""todo_dialog.py —— 待办管理最小可用对话框（v1.5.0）

审计结论（docs/audit-功能真实性清单-2026-09-07.md #C2）：TodoManager 能力本体
（extract_from_text / list_items / mark_done）实测可用，但 GUI 全树零引用 —— 空壳。
本对话框补上 GUI 入口：输入添加 + 勾选完成 + 删除。

后端：managers.TodoManager（v1.5.0 增补 add_item / delete_item / items），
存档文件沿用 AppConfig.todos_file（默认 cwd/todos.json，与 CLI /todo 同一份）。
"""

from __future__ import annotations

import logging

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, Qt,
)

try:
    from gui.utils import theme_color
except Exception:  # 主题工具缺失时对话框仍可用（内置兜底色）
    theme_color = None

logger = logging.getLogger("maid_coder.gui")


class TodoDialog(QDialog):
    """待办：输入框添加 + 列表勾选完成 + 删除（最小可用）。"""

    def __init__(self, app_ctx, parent=None):
        super().__init__(parent or None)
        self.app_ctx = app_ctx
        self.setWindowTitle("码铃 · 待办事项")
        self.resize(480, 420)
        self._todo = None
        # 勾选/取消勾选由程序发起时置 True，避免回环触发
        self._syncing = False

        self._accent = self._tc("accent", "#FF6B9D")
        self._bg = self._tc("bg_card", "#FFFFFF")
        self._border = self._tc("border", "#FFE4E1")
        self._text = self._tc("text", "#5D4037")
        self._text2 = self._tc("text_secondary", "#888888")

        self.setStyleSheet(
            f"QDialog {{ background: {self._tc('bg', '#FFF5F5')}; }}"
            f"QLabel {{ color: {self._text}; }}"
            f"QLineEdit {{"
            f"  background: {self._bg}; color: {self._text};"
            f"  border: 1px solid {self._border}; border-radius: 8px; padding: 6px;"
            f"}}"
            f"QListWidget {{"
            f"  background: {self._bg}; color: {self._text};"
            f"  border: 1px solid {self._border}; border-radius: 8px;"
            f"}}"
            f"QPushButton {{"
            f"  background: {self._bg}; color: {self._accent};"
            f"  border: 1px solid {self._accent}; border-radius: 8px; padding: 6px 14px;"
            f"}}"
            f"QPushButton:hover {{ background: {self._tc('bg_light', '#FFF0F3')}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("📝 待办事项")
        f = title.font()
        f.setBold(True)
        f.setPointSize(12)
        title.setFont(f)
        layout.addWidget(title)

        # -- 添加行 --
        add_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("输入新待办，回车或点「添加」…")
        self.input_edit.returnPressed.connect(self._on_add)
        add_row.addWidget(self.input_edit, 1)
        self.add_btn = QPushButton("➕ 添加")
        self.add_btn.clicked.connect(self._on_add)
        add_row.addWidget(self.add_btn)
        layout.addLayout(add_row)

        # -- 列表（带勾选） --
        self.list_widget = QListWidget()
        self.list_widget.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.list_widget, 1)

        # -- 操作行 --
        op_row = QHBoxLayout()
        del_btn = QPushButton("🗑 删除选中")
        del_btn.clicked.connect(self._on_delete)
        op_row.addWidget(del_btn)
        op_row.addStretch()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet(f"color: {self._text2}; font-size: 12px;")
        op_row.addWidget(self.count_label)
        layout.addLayout(op_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        self._init_todo()
        self._reload_items()

    # ------------------------------------------------------------------
    def _tc(self, key: str, fallback: str) -> str:
        if theme_color is None:
            return fallback
        try:
            return str(theme_color(self.app_ctx, key, fallback))
        except Exception:
            return fallback

    def _init_todo(self) -> None:
        """按 AppConfig.todos_file（缺省 cwd/todos.json）实例化 TodoManager。"""
        try:
            from managers import TodoManager
            cfg = getattr(self.app_ctx, "cfg", None)
            filepath = str(getattr(cfg, "todos_file", "") or "todos.json")
            self._todo = TodoManager(filepath)
        except Exception as exc:
            self._todo = None
            logger.warning("TodoManager 初始化失败: %s", exc)

    def _reload_items(self) -> None:
        """从后端重拉列表渲染（勾选态随 done）。"""
        self._syncing = True
        try:
            self.list_widget.clear()
            if self._todo is None:
                return
            for idx, item in enumerate(self._todo.items(), start=1):
                text = str(item.get("text", ""))
                done = bool(item.get("done", False))
                widget_item = QListWidgetItem(text)
                widget_item.setFlags(widget_item.flags() | Qt.ItemIsUserCheckable)
                widget_item.setCheckState(Qt.Checked if done else Qt.Unchecked)
                if done:
                    from gui.qt_compat import QFont
                    strike = QFont()
                    strike.setStrikeOut(True)
                    widget_item.setFont(strike)
                widget_item.setData(Qt.UserRole, idx)  # 1-based 序号，删除/勾选定位用
                self.list_widget.addItem(widget_item)
        finally:
            self._syncing = False
        self._refresh_count()

    def _refresh_count(self) -> None:
        total = self.list_widget.count()
        done = sum(
            1 for i in range(total)
            if self.list_widget.item(i).checkState() == Qt.Checked
        )
        self.count_label.setText(f"共 {total} 项 · 已完成 {done} 项")

    # ------------------------------------------------------------------
    def _on_add(self) -> None:
        text = self.input_edit.text().strip()
        if not text or self._todo is None:
            return
        try:
            self._todo.add_item(text)
        except Exception as exc:
            logger.warning("添加待办失败: %s", exc)
        self.input_edit.clear()
        self._reload_items()

    def _on_delete(self) -> None:
        if self._todo is None:
            return
        selected = self.list_widget.currentItem()
        if selected is None:
            return
        idx = int(selected.data(Qt.UserRole) or 0)
        if idx <= 0:
            return
        try:
            self._todo.delete_item(idx)
        except Exception as exc:
            logger.warning("删除待办失败: %s", exc)
        self._reload_items()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """勾选/取消勾选 → mark_done（1-based 序号按未过滤列表对位）。"""
        if self._syncing or self._todo is None or item is None:
            return
        idx = int(item.data(Qt.UserRole) or 0)
        if idx <= 0:
            return
        try:
            if item.checkState() == Qt.Checked:
                self._todo.mark_done(idx)
            else:
                self._todo.undo_done(idx)
        except Exception as exc:
            logger.debug("更新待办状态失败: %s", exc)
        self._reload_items()
