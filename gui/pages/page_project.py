"""项目视图页面 —— 文件树、过滤、刷新、文件操作。"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from gui.qt_compat import (
    QWidget, QObject, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QTreeView, QFileSystemModel,
    QSortFilterProxyModel, Signal, Qt, QFont,
    QMenu, QClipboard, QApplication, QDir,
)
from gui.qt_exit_guard import ExitSafeQThread

logger = logging.getLogger("maid_coder.gui")


class RefreshThread(ExitSafeQThread):
    """异步刷新线程：统计目录文件数。

    应用退出自我收口：继承 :class:`gui.qt_exit_guard.ExitSafeQThread`（机制与
    ``gui/widgets/kb_worker.py`` 的 v2.1 #281 修法一致）。原缺陷：线程在 ``run()``
    期间用户关窗时，父页面被销毁会**连带销毁仍在运行的 ``QThread``**，触发
    ``QThread: Destroyed while thread is still running`` 并进而 **Windows fail-fast
    ``0xC0000409`` 崩溃**。基类自挂两条停机路径（``aboutToQuit`` + 父控件 ``destroyed``）
    → 幂等 ``stop()``（有界 ``wait``）→ 超时 detach + 强引用。**自包含**：不依赖
    ``gui/main.py`` 停机编排，故无需改保护文件。
    """

    finished_scan = Signal(str, int)  # (root_path, file_count)

    #: 退出时对线程的**有界**等待上界（ms）。扫描被 cap 在 10000 文件、
    #: 实测 ≈0.16s；2.0s 留约 12× 余量，硬上界保证退出**绝不无限阻塞**。
    _QUIT_WAIT_MS = 2000

    def __init__(self, root_path: str, parent: Optional[QObject] = None):
        super().__init__(parent)          # 基类内即完成退出收口挂接
        self.root_path = root_path

    def run(self):
        try:
            count = 0
            for _root, _dirs, files in os.walk(self.root_path):
                count += len(files)
                if count > 10000:  # 上限，防止过多
                    break
            self.finished_scan.emit(self.root_path, count)
        except Exception:
            self.finished_scan.emit(self.root_path, -1)


class PageProject(QWidget):
    """项目视图页面：文件树 + 工具栏 + 文件操作。"""

    file_opened = Signal(str)  # 参数：文件绝对路径

    def __init__(
        self,
        app_context,
        title: str = "项目",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self._root_path: Optional[str] = None
        self._refresh_thread: Optional[RefreshThread] = None
        self._init_ui()
        self._setup_model()
        self._set_project_root()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 页面标题
        title_row = QHBoxLayout()
        self.title_label = QLabel("项目")
        self.title_label.setObjectName("pageTitle")
        title_font = QFont()
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        title_row.addWidget(self.title_label)
        title_row.addStretch()
        layout.addLayout(title_row)

        # 工具栏
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.refresh_btn = QPushButton("刷新")
        self.refresh_btn.setObjectName("quickBtn")
        self.refresh_btn.setToolTip("重新扫描项目目录")
        self.refresh_btn.clicked.connect(self._on_refresh)
        toolbar.addWidget(self.refresh_btn)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("过滤文件名...")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self.filter_edit, 1)

        self.hidden_check = QCheckBox("显示隐藏文件")
        self.hidden_check.setChecked(False)
        self.hidden_check.stateChanged.connect(self._on_toggle_hidden)
        toolbar.addWidget(self.hidden_check)

        layout.addLayout(toolbar)

        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setObjectName("chatStatusLabel")
        layout.addWidget(self.status_label)

        # 文件树
        self.tree_view = QTreeView()
        self.tree_view.setObjectName("projectTreeView")
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.doubleClicked.connect(self._on_item_double_clicked)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(
            self._on_context_menu
        )
        layout.addWidget(self.tree_view, 1)

    def _setup_model(self) -> None:
        self.fs_model = QFileSystemModel(self)
        self.fs_model.setReadOnly(True)
        # 初始不显示隐藏文件
        self.fs_model.setFilter(
            QDir.Dirs | QDir.Files | QDir.NoDotAndDotDot
        )

        self.proxy_model = QSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.fs_model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.setRecursiveFilteringEnabled(True)

        self.tree_view.setModel(self.proxy_model)

    def _set_project_root(self) -> None:
        """从 app_context 获取项目根目录。"""
        root = None
        # 按优先级查找
        for attr in ("project_dir", "current_project_root"):
            val = getattr(self.app_ctx, attr, None)
            if val:
                root = val
                break
        if not root:
            config = getattr(self.app_ctx, "config", None)
            if config:
                root = getattr(config, "last_project_root", None)
        if not root:
            root = os.getcwd()

        root = os.path.abspath(root)
        self._root_path = root

        # 设置模型根路径
        self.fs_model.setRootPath(root)
        root_index = self.fs_model.index(root)
        proxy_index = self.proxy_model.mapFromSource(root_index)
        self.tree_view.setRootIndex(proxy_index)

        # 更新标题
        project_name = os.path.basename(root) or root
        self.title_label.setText(f"项目: {project_name}")
        self.status_label.setText(f"根目录: {root}")

        # 展开根节点
        self.tree_view.expand(proxy_index)

        # 隐藏不需要的列（只显示文件名）
        for col in range(1, self.fs_model.columnCount()):
            self.tree_view.hideColumn(col)

    def on_enter(self) -> None:
        """页面进入时刷新。"""
        self._on_refresh()

    def _on_refresh(self) -> None:
        """刷新项目目录。"""
        # 旧线程仍在跑 → 复用其句柄（**不新起、不丢句柄**），避免并发/连坐析构
        if self._refresh_thread is not None and self._refresh_thread.isRunning():
            return
        # 旧线程已自然结束 → 回收其子对象，防 on_enter 反复触发时对象堆积
        self._retire_refresh_thread()

        if not self._root_path or not os.path.isdir(self._root_path):
            self.status_label.setText("项目目录无效")
            return

        self.refresh_btn.setEnabled(False)
        self.status_label.setText("正在刷新...")

        # 启动异步线程统计（线程自挂 aboutToQuit 自我收口，见 RefreshThread docstring）
        self._refresh_thread = RefreshThread(self._root_path, self)
        self._refresh_thread.finished_scan.connect(
            self._on_refresh_finished
        )
        self._refresh_thread.start()

    def _retire_refresh_thread(self) -> None:
        """回收已结束的旧刷新线程（幂等；仍在跑则保留句柄，交给 aboutToQuit 收口）。"""
        old = self._refresh_thread
        if old is None:
            return
        try:
            if old.isRunning():
                return
            old.finished_scan.disconnect(self._on_refresh_finished)
        except (TypeError, RuntimeError):
            logger.debug("RefreshThread 旧句柄回收失败（忽略）", exc_info=True)
        self._refresh_thread = None
        try:
            old.deleteLater()
        except RuntimeError:
            logger.debug("RefreshThread 旧句柄 deleteLater 失败（忽略）", exc_info=True)

    def _on_refresh_finished(self, root_path: str, count: int) -> None:
        """刷新完成回调。"""
        self.refresh_btn.setEnabled(True)
        if count < 0:
            self.status_label.setText("刷新失败")
            return

        # 强制刷新：先清空再重设根路径
        self.fs_model.setRootPath("")
        self.fs_model.setRootPath(root_path)
        root_index = self.fs_model.index(root_path)
        proxy_index = self.proxy_model.mapFromSource(root_index)
        self.tree_view.setRootIndex(proxy_index)

        for col in range(1, self.fs_model.columnCount()):
            self.tree_view.hideColumn(col)

        self.status_label.setText(f"已扫描 {count} 个文件 | {root_path}")

    def _on_filter_changed(self, text: str) -> None:
        """过滤输入变化。"""
        self.proxy_model.setFilterFixedString(text)

    def _on_toggle_hidden(self, state: int) -> None:
        """切换隐藏文件显示。"""
        if state == Qt.Checked:
            flags = (
                QDir.Dirs
                | QDir.Files
                | QDir.Hidden
                | QDir.NoDotAndDotDot
            )
        else:
            flags = QDir.Dirs | QDir.Files | QDir.NoDotAndDotDot
        self.fs_model.setFilter(flags)

    def _on_item_double_clicked(self, index) -> None:
        """双击打开文件。"""
        if not index.isValid():
            return
        source_index = self.proxy_model.mapToSource(index)
        file_path = self.fs_model.filePath(source_index)
        if os.path.isfile(file_path):
            self.file_opened.emit(file_path)

    def _on_context_menu(self, position) -> None:
        """右键菜单。"""
        index = self.tree_view.indexAt(position)
        if not index.isValid():
            return

        source_index = self.proxy_model.mapToSource(index)
        file_path = self.fs_model.filePath(source_index)

        menu = QMenu(self)
        copy_action = menu.addAction("复制路径")
        open_action = menu.addAction("在资源管理器中打开")

        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
        if action == copy_action:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(file_path)
        elif action == open_action:
            self._open_in_explorer(file_path)

    @staticmethod
    def _open_in_explorer(path: str) -> None:
        """在系统文件管理器中打开路径。"""
        abs_path = os.path.abspath(path)
        if os.name == "nt":
            subprocess.run(
                ["explorer", "/select,", abs_path], check=False
            )
        elif os.name == "darwin":
            subprocess.run(["open", "-R", abs_path], check=False)
        else:
            # Linux：尝试打开父目录
            parent = os.path.dirname(abs_path)
            subprocess.run(["xdg-open", parent], check=False)
