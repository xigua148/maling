"""camera_capture.py —— 拍照发图（v1.2.2，配合多模态看图）

在聊天里「📷 拍照」：调起本机摄像头实时预览 → 拍摄一张 JPEG 到系统临时目录
→ 返回给附件栏（复用 add_file_path，随消息以图片直传，需模型支持视觉）。

设计：
- 全部 QtMultimedia 访问走防御式（try import + 运行时 isAvailable 检查）；
  无摄像头 / 驱动不可用 / 平台无多媒体后端 → 返回 None，由调用方弹提示，绝不崩。
- 不做录制/持续监控 —— 仅"拍一张照发给 AI"，符合产品红线（不做监督式陪伴）。
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import Optional

from gui.qt_compat import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    Qt, QMessageBox,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# ---- 防御式加载 QtMultimedia（弱环境降级）----
try:
    from PySide6.QtMultimedia import QCamera, QImageCapture
    from PySide6.QtMultimediaWidgets import QCameraViewfinder
    _CAM_OK = True
except Exception as _e:  # 无 QtMultimedia 插件/依赖
    _CAM_OK = False
    logger.debug("QtMultimedia 不可用: %s", _e)


class CameraCaptureDialog(QDialog):
    """摄像头取景拍摄对话框。exec_() 返回 Accepted 时 result_path() 给出照片。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📷 拍照发给码铃")
        self.setModal(True)
        self._captured_path: Optional[str] = None
        self._camera = None
        self._capture = None
        self._build_ui()
        self._start_camera()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        if not _CAM_OK:
            layout.addWidget(QLabel("当前环境不支持摄像头（QtMultimedia 不可用）。"))
            self._ok_btn = QPushButton("知道了")
            self._ok_btn.clicked.connect(self.reject)
            layout.addWidget(self._ok_btn)
            self.resize(360, 140)
            return

        self.viewfinder = QCameraViewfinder(self)
        layout.addWidget(self.viewfinder, 1)

        btn_row = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color: {theme_color(None, 'text_hint', '#999999')};")
        btn_row.addWidget(self.hint, 1)
        self.shoot_btn = QPushButton("📷 拍摄")
        self.shoot_btn.setCursor(Qt.PointingHandCursor)
        self.shoot_btn.setEnabled(False)
        self.shoot_btn.clicked.connect(self._on_shoot)
        btn_row.addWidget(self.shoot_btn)
        cancel = QPushButton("取消")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(cancel)
        layout.addLayout(btn_row)
        self.resize(760, 540)

    def _start_camera(self) -> None:
        if not _CAM_OK:
            return
        try:
            self._camera = QCamera(self)
            self._capture = QImageCapture(self._camera)
            self._capture.imageCaptured.connect(self._on_image_captured)
            self._capture.imageSaved.connect(self._on_image_saved)
            self._capture.errorOccurred.connect(self._on_capture_error)
            self._camera.setViewfinder(self.viewfinder)
            self._camera.start()
            self._camera_error_timer = 0
            self.shoot_btn.setEnabled(True)
            self.hint.setText("预览中…对准后点拍摄")
        except Exception as e:
            logger.warning("摄像头启动失败: %s", e)
            self.hint.setText("摄像头不可用或已被占用。")
            self.shoot_btn.setEnabled(False)

    def _on_shoot(self) -> None:
        if self._capture is None:
            return
        try:
            folder = os.path.join(tempfile.gettempdir(), "maid_coder_cam")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"cam_{int(time.time() * 1000)}.jpg")
            self._pending_path = path
            self.shoot_btn.setEnabled(False)
            self.hint.setText("拍摄中…")
            self._capture.captureToFile(path)
        except Exception as e:
            logger.warning("拍照失败: %s", e)
            self.hint.setText("拍照失败，请重试。")
            self.shoot_btn.setEnabled(True)

    # ---- QImageCapture 信号回调 ----
    def _on_image_captured(self, _rid: int, preview) -> None:
        try:
            if preview is not None and not preview.isNull():
                self.viewfinder._last_preview = preview  # noqa: SLF001 暂存预览避免被回收
        except Exception:
            pass

    def _on_image_saved(self, _rid: int, path: str) -> None:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            self._captured_path = path
            self.accept()
        else:
            self.hint.setText("保存失败，请重试。")
            self.shoot_btn.setEnabled(True)

    def _on_capture_error(self, _rid: int, _err, err_str: str) -> None:
        logger.warning("图像采集错误: %s", err_str)
        self.hint.setText(f"拍摄出错：{err_str}")
        self.shoot_btn.setEnabled(True)

    def result_path(self) -> Optional[str]:
        return self._captured_path

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._camera is not None:
                self._camera.stop()
        except Exception:
            pass
        super().closeEvent(event)


def capture_photo(parent=None) -> Optional[str]:
    """便捷入口：弹取景框拍一张，成功返回照片路径；取消/不可用返回 None。"""
    if not _CAM_OK:
        if parent is not None:
            try:
                QMessageBox.information(
                    parent, "拍照不可用",
                    "当前环境缺少摄像头组件（QtMultimedia 未随应用加载）。\n"
                    "可改用「📎 附件」直接选一张已有图片发送。",
                )
            except Exception:
                pass
        return None
    dlg = CameraCaptureDialog(parent)
    if dlg.exec_() == QDialog.Accepted:
        return dlg.result_path()
    return None
