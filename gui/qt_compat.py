"""Qt 绑定兼容层 —— 统一入口，降低未来换绑定的成本。"""
from __future__ import annotations

# QFileSystemModel 兼容层：新旧版本 PySide6 位置不同
try:
    from PySide6.QtGui import QFileSystemModel
except ImportError:
    from PySide6.QtWidgets import QFileSystemModel

# Widgets
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QStackedWidget, QSplitter,
    QListWidget, QListWidgetItem, QTextEdit, QPlainTextEdit,
    QPushButton, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout,
    QGridLayout, QMessageBox, QFileDialog, QProgressBar,
    QStatusBar, QToolBar, QMenuBar, QMenu, QApplication,
    QDialog, QComboBox, QSlider, QCheckBox, QRadioButton,
    QTabWidget, QTabBar, QTreeWidget, QTreeWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QFrame, QSizePolicy, QLayout,
    QTreeView, QTextBrowser, QGraphicsDropShadowEffect,
    QInputDialog, QSystemTrayIcon, QToolButton,
)

# Core
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QObject, QTimer,
    QSize, QPoint, QRect, QRectF, QSettings, QStandardPaths,
    QEvent, QMetaObject, Q_ARG, QSortFilterProxyModel,
    QDir,
    # v1.4(V-1.4-0 预编): 帧压缩/内存 JPG（screen_grab 与 games 绘板需要）
    QBuffer, QByteArray,
)

# Gui
from PySide6.QtGui import (
    QFont, QFontDatabase, QIcon, QPixmap, QColor,
    QPalette, QKeySequence, QShortcut, QTextCursor,
    QTextCharFormat, QAction, QPainter, QPainterPath, QPen,
    QClipboard, QSyntaxHighlighter,
    QDragEnterEvent, QDragMoveEvent, QDropEvent,
    # v1.2.x: 头像渐进解码（超大/异常图防内存崩溃，role 头像用）
    QImageReader,
    # v1.3(P1-2): 区域截图直接问（screen_capture.py 多屏 grabWindow 合成）
    QGuiApplication, QScreen,
    # v1.4(V-1.4-0 预编): 内存帧缩放/编码 + 游戏自绘板（screen_grab / games 需要）
    QImage, QImageWriter,
)

__all__ = [
    # Widgets
    "QMainWindow", "QWidget", "QStackedWidget", "QSplitter",
    "QListWidget", "QListWidgetItem", "QTextEdit", "QPlainTextEdit",
    "QPushButton", "QLabel", "QLineEdit", "QVBoxLayout", "QHBoxLayout",
    "QGridLayout", "QMessageBox", "QFileDialog", "QProgressBar",
    "QStatusBar", "QToolBar", "QMenuBar", "QMenu", "QApplication",
    "QDialog", "QComboBox", "QSlider", "QCheckBox", "QRadioButton",
    "QTabWidget", "QTabBar", "QTreeWidget", "QTreeWidgetItem", "QTableWidget",
    "QTableWidgetItem", "QHeaderView", "QAbstractItemView",
    "QScrollArea", "QFrame", "QSizePolicy", "QLayout",
    "QTreeView", "QTextBrowser", "QGraphicsDropShadowEffect",
    "QInputDialog", "QSystemTrayIcon", "QToolButton", "QFileSystemModel",
    # Core
    "Qt", "QThread", "Signal", "Slot", "QObject", "QTimer",
    "QSize", "QPoint", "QRect", "QSettings", "QStandardPaths",
    "QEvent", "QMetaObject", "Q_ARG", "QSortFilterProxyModel",
    "QDir",
    # v1.4 预编增补（Core）
    "QBuffer", "QByteArray",
    # Gui
    "QFont", "QFontDatabase", "QIcon", "QPixmap", "QColor",
    "QPalette", "QKeySequence", "QShortcut", "QTextCursor",
    "QTextCharFormat", "QAction", "QPainter", "QPainterPath", "QPen",
    "QClipboard", "QSyntaxHighlighter", "QImageReader",
    "QDragEnterEvent", "QDragMoveEvent", "QDropEvent",
    # v1.4 预编增补（Gui）
    "QImage", "QImageWriter",
    # v1.3(P1-2)
    "QGuiApplication", "QScreen",
    # Core 增补：v1.3(P1-2) screen_capture 选区绘制用
    "QRectF",
]
