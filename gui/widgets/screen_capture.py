"""v1.3(P1-2) 区域截图直接问 —— 无边框半透明全屏遮罩选区 QDialog。

v1.4(B3)：本文件只**加**一个委托方法 capture_active_screen_png()（整帧→临时 PNG），
对话框与 `_capture_desktop` 原样不动；持续看屏的内存帧由 gui/screen_grab.py 承接
（design-v14 D-V14-07 / §2.3，职责不重叠）。

设计（docs/design-v13.md D-V13-04 / §5 P1-2，docs/prd-v13.md §3.1 P1-2）：
- 多屏遍历 QScreen.grabWindow(0) + devicePixelRatio 校正，合成整块虚拟桌面位图；
- 全屏遮罩层上拖框选区域 → 存 `tempfile/maid_coder_shot/shot_*.png` → 返回路径；
- **选完不自动发送**：由 chat_panel 把路径进附件条 + 预填引导文案，用户确认后走既有发送链；
- 只发生在用户显式操作下，绝无后台偷拍/定时截屏（红线）；产物仅本地临时文件；
- 无视觉模型提示沿用既有链路（v1.2.2 已有，不重复造）；
- 全部新增取色走 theme_color（无裸色值）；任何一步失败返回 None，由调用方提示，绝不崩。

已知边界：多屏混合 DPR（不同缩放比例）下选区边缘可能偏差 ≤ 一屏 dpr 差，P2 内修
（design D-V13-04 降级口径：主屏/同 DPR 多屏最小可用已覆盖）。
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from typing import List, Optional, Tuple

from gui.qt_compat import (
    QApplication, QDialog, QPainter, QPixmap, QColor, QPen,
    Qt, QRect, QRectF, QPoint, QGuiApplication, QScreen,
    QMessageBox, QFont,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")


class ScreenCaptureDialog(QDialog):
    """全屏遮罩选区对话框。exec_() 返回 Accepted 时 result_path() 给出截图路径。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("区域截图发给码铃")
        # 无边框 + 置顶 + 工具窗（不抢任务栏），跨屏覆盖虚拟桌面
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setCursor(Qt.CrossCursor)
        self._captured_path: Optional[str] = None
        self._base_pixmap: Optional[QPixmap] = None
        self._virtual_rect = QRect()
        self._dpr = 1.0
        self._drag_start: Optional[QPoint] = None
        self._drag_cur: Optional[QPoint] = None

        self._capture_desktop()
        if self._base_pixmap is None:
            return  # 截取失败：_build_ui 会放兜底说明
        # 窗口覆盖整个虚拟桌面（含负坐标），保证选区坐标系与合成位图一致
        self.setGeometry(self._virtual_rect)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_DeleteOnClose)

    # -- 合成多屏截屏（devicePixelRatio 校正）--
    def _capture_desktop(self) -> None:
        try:
            screens: List[QScreen] = QGuiApplication.screens()
            if not screens:
                return
            # 虚拟桌面逻辑矩形 = 各屏 geometry 并集
            vr = QRect()
            for sc in screens:
                geo = sc.geometry()
                vr = vr.united(QRect(geo))
            self._virtual_rect = vr
            # 以主屏 DPR 为基准（同 DPR 多屏精确；混合 DPR 见模块 docstring 已知边界）
            dpr = float(QGuiApplication.primaryScreen().devicePixelRatio() or 1.0)
            self._dpr = max(1.0, dpr)
            w = int(vr.width() * self._dpr)
            h = int(vr.height() * self._dpr)
            if w <= 0 or h <= 0:
                return
            canvas = QPixmap(w, h)
            canvas.setDevicePixelRatio(self._dpr)  # 让后续 paint 以逻辑尺寸 1:1 呈现
            canvas.fill(QColor(0, 0, 0))
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            try:
                for sc in screens:
                    pm = sc.grabWindow(0)  # 已带该屏 dpr 的高分辨率位图
                    if pm is None or pm.isNull():
                        continue
                    geo = sc.geometry()
                    # 目标矩形 = 该屏在虚拟桌面内的逻辑区域
                    target = QRectF(
                        (geo.x() - vr.x()) * self._dpr,
                        (geo.y() - vr.y()) * self._dpr,
                        geo.width() * self._dpr,
                        geo.height() * self._dpr,
                    )
                    painter.drawPixmap(target, pm, QRectF(pm.rect()))
            finally:
                painter.end()
            self._base_pixmap = canvas
        except Exception as exc:
            logger.warning("截屏合成失败: %s", exc)
            self._base_pixmap = None

    # -- 绘制：背景冻结帧 + 选区蒙版 --
    def paintEvent(self, event) -> None:  # noqa: N802
        if self._base_pixmap is None:
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.drawPixmap(QPoint(0, 0), self._base_pixmap)
        if self._drag_start is not None and self._drag_cur is not None:
            sel = QRect(self._drag_start, self._drag_cur).normalized()
            # 选区外暗化（半透明黑），选区内还原清晰
            overlay = QColor(0, 0, 0, 120)
            dims = [
                QRect(self.rect().left(), self.rect().top(), self.rect().width(), sel.top() - self.rect().top()),
                QRect(self.rect().left(), sel.bottom(), self.rect().width(), self.rect().bottom() - sel.bottom()),
                QRect(self.rect().left(), sel.top(), sel.left() - self.rect().left(), sel.height()),
                QRect(sel.right(), sel.top(), self.rect().right() - sel.right(), sel.height()),
            ]
            for dim in dims:
                if dim.width() > 0 and dim.height() > 0:
                    painter.fillRect(dim, overlay)
            # 选区边框
            accent = theme_color(None, "accent", "#FF6B9D")
            painter.setPen(QPen(QColor(accent), 2))
            painter.drawRect(sel)
            # 尺寸提示
            hint = f"{sel.width()} × {sel.height()}"
            painter.setFont(QFont("Microsoft YaHei", 9))
            painter.setPen(QColor("#FFFFFF"))
            tx = sel.left()
            ty = sel.top() - 6
            if ty < 0:
                ty = sel.bottom() + 18
            painter.drawText(tx + 4, ty, hint)
        painter.end()

    # -- 拖框 --
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
            self._drag_cur = event.pos()
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start is not None:
            self._drag_cur = event.pos()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or self._drag_start is None:
            return
        self._drag_cur = event.pos()
        sel = QRect(self._drag_start, self._drag_cur).normalized()
        self._drag_start = None
        if sel.width() < 4 or sel.height() < 4:
            self._captured_path = None
            self.reject()  # 太小的框视为取消
            return
        self._save_region(sel)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._captured_path = None
            self.reject()
            return
        super().keyPressEvent(event)

    # -- 落盘 --
    def _save_region(self, sel: QRect) -> None:
        """按 DPR 放大选区到物理像素，写入临时目录。"""
        try:
            if self._base_pixmap is None:
                self._captured_path = None
                self.reject()
                return
            # 逻辑坐标 → 物理像素坐标
            dev_x = int((sel.x() - self._virtual_rect.x()) * self._dpr)
            dev_y = int((sel.y() - self._virtual_rect.y()) * self._dpr)
            dev_w = int(sel.width() * self._dpr)
            dev_h = int(sel.height() * self._dpr)
            crop = self._base_pixmap.copy(dev_x, dev_y, dev_w, dev_h)
            if crop is None or crop.isNull() or crop.width() <= 0 or crop.height() <= 0:
                self._captured_path = None
                self.reject()
                return
            folder = os.path.join(tempfile.gettempdir(), "maid_coder_shot")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"shot_{int(time.time() * 1000)}.png")
            if crop.save(path, "PNG"):
                self._captured_path = path
                self.accept()
            else:
                self._captured_path = None
                self.reject()
        except Exception as exc:
            logger.warning("截图保存失败: %s", exc)
            self._captured_path = None
            self.reject()

    def result_path(self) -> Optional[str]:
        return self._captured_path


def capture_region(parent=None) -> Optional[str]:
    """便捷入口：弹全屏选区对话框，成功返回截图路径；取消/不可用返回 None。

    v1.3(P1-2) 契约名：chat_panel / 热键 / 托盘共用（design §5 P1-2）。
    """
    if QGuiApplication.screens is None or not QGuiApplication.screens():
        if parent is not None:
            try:
                QMessageBox.information(parent, "截图不可用", "当前环境未检测到可用屏幕，无法区域截图。")
            except Exception:
                pass
        return None
    dlg = ScreenCaptureDialog(parent)
    # 给用户一个 Esc/说明提示：遮罩左上角画提示（标题栏被隐藏，用 tooltip 即可）
    dlg.setToolTip("拖动鼠标框选要发送的区域，Esc 取消")
    if dlg.exec_() == QDialog.Accepted:
        return dlg.result_path()
    return None


def capture_active_screen_png(parent=None) -> Optional[str]:
    """v1.4(B3) 委托方法：抓当前虚拟桌面整帧 → 临时 PNG（**无选区**）。

    与 capture_region 的区别：不弹遮罩选区框，直接抓全虚拟桌面保存为临时 PNG；
    供需要「截一张当前屏」的入口使用（如用户主动把当前屏发给码铃/临时用图），
    走 R-E「用户主动截一张」既有临时 PNG 例外。持续看屏的**内存帧**不经此方法
    （走 screen_grab / screen_watch 内存链，不落盘）。

    失败返回 None（由调用方提示），绝不崩。
    """
    try:
        from gui.screen_grab import grab_virtual_desktop
        result = grab_virtual_desktop()
        if not result.ok or result.pixmap is None or result.pixmap.isNull():
            if parent is not None:
                try:
                    QMessageBox.information(parent, "截图不可用", "当前环境未检测到可用屏幕，无法截图。")
                except Exception:
                    pass
            return None
        folder = os.path.join(tempfile.gettempdir(), "maid_coder_shot")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"screen_{int(time.time() * 1000)}.png")
        if result.pixmap.save(path, "PNG"):
            return path
        return None
    except Exception as exc:
        logger.warning("当前屏整帧截图失败: %s", exc)
        return None


# 向后兼容别名（v1.3 前早期命名，保留以免外部调用点误伤）
capture_screenshot = capture_region
