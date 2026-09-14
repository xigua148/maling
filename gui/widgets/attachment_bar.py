"""附件芯片栏 —— 输入框上方的多附件展示条，支持逐个移除、主题色同步。

新增功能：第四阶段「文件拖拽上传」UI 入口。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from gui.qt_compat import (
    Qt, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QSizePolicy, Signal,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# 单文件大小上限（10MB）
MAX_FILE_SIZE = 10 * 1024 * 1024


@dataclass
class AttachmentData:
    """单个附件的元信息。"""

    name: str       # 展示用文件名
    path: str       # 本地绝对路径
    size: int       # 字节
    ext: str        # 后缀（带 .，小写）

    def to_dict(self) -> dict:
        return {"name": self.name, "path": self.path, "size": self.size, "ext": self.ext}

    @classmethod
    def from_dict(cls, d: dict) -> Optional["AttachmentData"]:
        """从 dict 反序列化；R7: 落库/回放时的第二道闸。

        size 超过 10MB 上限或字段非法时返回 None（调用方跳过），与 UI 层
        add_file_path 的校验形成双保险。
        """
        try:
            data = cls(
                name=str(d.get("name", "")),
                path=str(d.get("path", "")),
                size=int(d.get("size", 0) or 0),
                ext=str(d.get("ext", "")),
            )
        except (TypeError, ValueError) as exc:
            logger.warning("附件元数据非法，回放时剔除: %r (%s)", d, exc)
            return None
        if data.size > MAX_FILE_SIZE:
            logger.warning(
                "附件超过 10MB 上限，回放时剔除: %s (%d bytes)",
                data.name, data.size,
            )
            return None
        return data


def attachment_icon(name: str, ext: str) -> str:
    """根据扩展名返回类型图标。"""
    code_ext = {".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".go", ".rs", ".rb", ".php", ".sh", ".kt", ".swift"}
    image_ext = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico"}
    audio_ext = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}
    video_ext = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv"}
    archive_ext = {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz"}
    doc_ext = {".md", ".txt", ".pdf", ".doc", ".docx", ".rtf"}
    if ext in code_ext:
        return "💻"
    if ext in image_ext:
        return "🖼"
    if ext in audio_ext:
        return "🎵"
    if ext in video_ext:
        return "🎬"
    if ext in archive_ext:
        return "📦"
    if ext in doc_ext:
        return "📝"
    return "📄"


def human_size(size: int) -> str:
    """可读的文件大小。"""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


class _Chip(QFrame):
    """单个附件芯片（图标 + 文件名 + 大小 + 移除按钮）。"""

    remove_requested = Signal(object)  # 发出自身

    def __init__(self, data: AttachmentData, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.data = data
        self.setObjectName("attachmentChip")
        self.setStyleSheet(self._build_style(app_ctx))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 4, 4)
        layout.setSpacing(6)

        self._icon_label = QLabel(attachment_icon(data.name, data.ext))
        self._icon_label.setObjectName("attachmentChipIcon")
        self._icon_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self._icon_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name_label = QLabel(data.name)
        name_label.setObjectName("attachmentChipName")
        name_label.setToolTip(data.path)
        name_label.setStyleSheet("font-size: 12px;")
        text_col.addWidget(name_label)
        size_label = QLabel(human_size(data.size))
        size_label.setObjectName("attachmentChipSize")
        size_label.setStyleSheet("font-size: 10px; opacity: 0.7;")
        text_col.addWidget(size_label)
        layout.addLayout(text_col, 1)

        self._remove_btn = QPushButton("×")
        self._remove_btn.setObjectName("attachmentChipRemove")
        self._remove_btn.setFixedSize(20, 20)
        self._remove_btn.setCursor(Qt.PointingHandCursor)
        self._remove_btn.setToolTip("移除附件")
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        self._apply_remove_btn_style(app_ctx)
        layout.addWidget(self._remove_btn)

        # 内部颜色（后续主题切换时统一刷新）
        self._name_label = name_label
        self._size_label = size_label
        self._app_ctx = app_ctx

    def _build_style(self, app_ctx) -> str:
        bg = theme_color(app_ctx, "bg_card", "#FFFFFF")
        border = theme_color(app_ctx, "accent_light", "#FFB6C1")
        text = theme_color(app_ctx, "text", "#4A4A4A")
        return (
            f"QFrame#attachmentChip {{"
            f"  background: {bg};"
            f"  border: 1px solid {border};"
            f"  border-radius: 12px;"
            f"  color: {text};"
            f"}}"
        )

    def _apply_remove_btn_style(self, app_ctx) -> None:
        accent = theme_color(app_ctx, "accent", "#FF6B9D")
        text_secondary = theme_color(app_ctx, "text_secondary", "#8A8A8A")
        text_on_accent = theme_color(app_ctx, "text_on_accent", "#FFFFFF")
        self._remove_btn.setStyleSheet(
            f"QPushButton#attachmentChipRemove {{"
            f"  background: transparent; border: none; border-radius: 10px;"
            f"  color: {text_secondary}; font-size: 14px; font-weight: bold;"
            f"}}"
            f"QPushButton#attachmentChipRemove:hover {{"
            f"  background: {accent}; color: {text_on_accent};"
            f"}}"
        )

    def refresh_theme(self) -> None:
        self.setStyleSheet(self._build_style(self._app_ctx))
        text = theme_color(self._app_ctx, "text", "#4A4A4A")
        secondary = theme_color(self._app_ctx, "text_secondary", "#8A8A8A")
        self._name_label.setStyleSheet(f"font-size: 12px; color: {text};")
        self._size_label.setStyleSheet(f"font-size: 10px; color: {secondary}; opacity: 0.7;")
        self._apply_remove_btn_style(self._app_ctx)


class AttachmentBar(QWidget):
    """输入框上方的多附件芯片栏。"""

    changed = Signal()

    def __init__(self, app_ctx, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        self._items: List[_Chip] = []
        self.setObjectName("attachmentBar")
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 0)
        outer.setSpacing(4)

        self._header = QLabel("附件")
        self._header.setObjectName("attachmentBarHeader")
        self._header.setStyleSheet(self._build_header_style())
        outer.addWidget(self._header)

        self._chips_layout = QVBoxLayout()
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(4)
        outer.addLayout(self._chips_layout)

    def _build_header_style(self) -> str:
        color = theme_color(self._app_ctx, "text_secondary", "#8A8A8A")
        return f"QLabel#attachmentBarHeader {{ font-size: 11px; color: {color}; padding: 0 2px; }}"

    def refresh_theme(self) -> None:
        self._header.setStyleSheet(self._build_header_style())
        for chip in self._items:
            chip.refresh_theme()

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def add_file_path(self, path: str) -> Tuple[bool, str]:
        """从文件路径添加附件。

        返回 (是否成功, 原因/文件名)。
        失败原因: "missing" 文件不存在；"too_large" 超过 10MB；"duplicate" 已存在同名。
        """
        if not path or not os.path.isfile(path):
            return False, "missing"
        try:
            size = os.path.getsize(path)
        except OSError:
            return False, "missing"
        if size > MAX_FILE_SIZE:
            return False, "too_large"
        data = AttachmentData(
            name=os.path.basename(path),
            path=os.path.abspath(path),
            size=size,
            ext=os.path.splitext(path)[1].lower(),
        )
        if any(c.data.path == data.path for c in self._items):
            return False, "duplicate"
        self._add_chip(data)
        return True, data.name

    def add_attachment(self, data: AttachmentData) -> None:
        """直接添加附件（用于历史消息回放、编辑回填）。"""
        # 避免重复
        if any(c.data.path == data.path for c in self._items):
            return
        self._add_chip(data)

    def add_from_dicts(self, dicts: List[dict]) -> None:
        """从 dict 列表批量添加（编辑消息回填 / 历史回放）。

        R7: from_dict 返回 None（超限/非法）的条目跳过。
        """
        for d in dicts or []:
            data = AttachmentData.from_dict(d)
            if data is not None:
                self.add_attachment(data)

    def attachments(self) -> List[dict]:
        return [c.data.to_dict() for c in self._items]

    def clear(self) -> None:
        for chip in self._items:
            chip.setParent(None)
            chip.deleteLater()
        self._items.clear()
        self.setVisible(False)
        self.changed.emit()

    def count(self) -> int:
        return len(self._items)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _add_chip(self, data: AttachmentData) -> None:
        chip = _Chip(data, self._app_ctx, self)
        chip.remove_requested.connect(self._on_chip_removed)
        self._chips_layout.addWidget(chip)
        self._items.append(chip)
        self.setVisible(True)
        self.changed.emit()

    def _on_chip_removed(self, chip: _Chip) -> None:
        if chip not in self._items:
            return
        self._items.remove(chip)
        self._chips_layout.removeWidget(chip)
        chip.setParent(None)
        chip.deleteLater()
        if not self._items:
            self.setVisible(False)
        self.changed.emit()
