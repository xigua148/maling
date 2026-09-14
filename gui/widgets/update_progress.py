"""gui/widgets/update_progress.py —— v2.0 下载态进度对话框（V20-07 / L2-1）。

docs/design-v20.md D-V20-05 + §5.2：**自包含、非模态、可后台继续、可取消**的下载进度卡。

- 非阻断（R-A）：`setModal(False)`；「后台继续」= 隐藏对话框、下载照常继续；
  「取消」= 调 `DownloadWorker.request_cancel()`（`.part` 保留供续传，Q-U4）。
- 不触碰下载逻辑：只消费 `DownloadWorker` 的信号，线程安全（Qt 自动跨线程投递）。
- 文案禁「失败 N 次 / 落后 N 版」等数值化催促语义（R-A 硬口径）。

main.py 接线（供域4 直接调用，**本模块不改 main.py**）::

    from gui.widgets.update_progress import UpdateProgressDialog

    dlg = UpdateProgressDialog(app_ctx, parent=window)   # 非模态
    dlg.download_verified.connect(on_update_downloaded)   # 校验通过 → 提示「重启安装」
    dlg.download_failed.connect(on_update_download_failed)
    dlg.begin(worker)      # 连接 worker 信号 + show()；worker 需随后 start()
    worker.start()

`dlg.begin()` 内部只做「连线 + 显示」，**不启动线程**，线程由调用方 `start()`，
便于调用方在 show 之后才真正开跑（避免下载快于 UI 就绪）。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import (
    QDialog, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QProgressBar, QFrame, Qt, QFont, Signal,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# R-A：失败态文案不出现次数 / 落后版本数 / 催促语义
_TEXT_DOWNLOADING = "正在下载更新…"
_TEXT_VERIFIED = "已下载并校验通过，重启后启用"
_TEXT_VERIFIED_NO_SHA = "已下载完成（未能校验），建议手动确认"
_TEXT_FAILED = "下载未完成，可稍后在设置页重试"
_TEXT_CANCELLED = "已取消，下次可继续下载"
_TEXT_DISK = "磁盘空间不足，请清理后重试"
_TEXT_BLOCKED = "下载受限（更新源不可用），可稍后在设置页重试"


def _friendly_failure(reason: str) -> str:
    """把 worker 错误码转成 R-A 无焦虑文案（不暴露堆栈 / 次数）。"""
    r = (reason or "").lower()
    if "disk_space_low" in r or "staging_unwritable" in r:
        return _TEXT_DISK
    if "all_links_failed" in r or "no_urls" in r or "exception" in r:
        return _TEXT_BLOCKED
    if "sha256_mismatch" in r:
        return "下载文件校验未通过，已作废，可稍后重试"
    return _TEXT_FAILED


class UpdateProgressDialog(QDialog):
    """非模态下载进度对话框（R-A）。对外信号见类文档。"""

    # 透传给上层（main.py）的语义事件
    download_verified = Signal(str)   # 校验通过的成品路径
    download_finished = Signal(str)   # 落盘完成（未经校验时也会发）
    download_failed = Signal(str)     # 原始错误码
    download_cancelled = Signal()
    backgrounded = Signal()           # 用户点了「后台继续」
    cancel_requested = Signal()       # 用户点了「取消」

    def __init__(self, app_ctx=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._worker = None
        self._terminal = False
        self.setWindowTitle("码铃 · 更新下载")
        self.setModal(False)                 # R-A 非阻断
        self.setMinimumWidth(380)
        self._build_ui()
        self._apply_theme()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        self.title_label = QLabel(_TEXT_DOWNLOADING)
        self.title_label.setObjectName("updTitle")
        tf = self.title_label.font()
        tf.setPointSize(12)
        tf.setBold(True)
        self.title_label.setFont(tf)
        outer.addWidget(self.title_label)

        self.bar = QProgressBar()
        self.bar.setObjectName("updBar")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        outer.addWidget(self.bar)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("updDetail")
        self.detail_label.setWordWrap(True)
        outer.addWidget(self.detail_label)

        line = QFrame()
        line.setObjectName("updLine")
        line.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(line)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch()
        self.background_btn = QPushButton("后台继续")
        self.background_btn.setObjectName("updBtn")
        self.background_btn.setCursor(Qt.PointingHandCursor)
        self.background_btn.clicked.connect(self._on_background)
        btns.addWidget(self.background_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("updBtnPrimary")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btns.addWidget(self.cancel_btn)
        outer.addLayout(btns)

    def _apply_theme(self) -> None:
        bg = theme_color(self.app_ctx, "bg_card", "#FFFFFF")
        accent = theme_color(self.app_ctx, "accent", "#FF6B9D")
        primary = theme_color(self.app_ctx, "primary", "#FFB6C1")
        text = theme_color(self.app_ctx, "text", "#5D4037")
        secondary = theme_color(self.app_ctx, "text_secondary", "#8A8A8A")
        divider = theme_color(self.app_ctx, "divider", "#EFE0E2")
        self.setStyleSheet(
            f"QDialog {{ background: {bg}; color: {text}; }}"
            f"QLabel#updTitle {{ color: {text}; background: transparent; }}"
            f"QLabel#updDetail {{ color: {secondary}; font-size: 11px;"
            f" background: transparent; }}"
            f"QFrame#updLine {{ color: {divider}; }}"
            f"QProgressBar#updBar {{ border: 1px solid {divider}; border-radius: 7px;"
            f" background: #F5F5F5; height: 14px; text-align: center; }}"
            f"QProgressBar#updBar::chunk {{ background: {accent}; border-radius: 6px; }}"
            f"QPushButton#updBtn {{ background: transparent; color: {accent};"
            f" border: 1px solid {primary}; border-radius: 8px; padding: 6px 14px; }}"
            f"QPushButton#updBtn:hover {{ background: {primary}; color: #FFFFFF; }}"
            f"QPushButton#updBtnPrimary {{ background: {accent}; color: #FFFFFF;"
            f" border: none; border-radius: 8px; padding: 6px 14px; }}"
        )

    # ------------------------------------------------------------------
    # 对外接线
    # ------------------------------------------------------------------
    def begin(self, worker) -> None:
        """连接 worker 信号并显示；**不启动线程**（由调用方 `worker.start()`）。"""
        self._worker = worker
        self._terminal = False
        self.title_label.setText(_TEXT_DOWNLOADING)
        self.detail_label.setText("")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.background_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        try:
            worker.progress.connect(self._on_progress)
            worker.verified.connect(self._on_verified)
            worker.finished.connect(self._on_finished)
            worker.failed.connect(self._on_failed)
            worker.cancelled.connect(self._on_cancelled)
        except Exception as exc:  # 信号连接失败不阻断（R-N）
            logger.info("下载进度对话框信号连接失败（忽略）: %s", exc)
        self.show()
        try:
            self.raise_()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # worker 信号槽（均在 GUI 线程执行）
    # ------------------------------------------------------------------
    def _on_progress(self, received: int, total: int, speed: float, eta_text: str) -> None:
        if self._terminal:
            return
        if total and total > 0:
            if self.bar.maximum() != 100:
                self.bar.setRange(0, 100)
            pct = int(received * 100 // total) if total else 0
            self.bar.setValue(min(max(pct, 0), 100))
        else:
            # 未知长度：不确定态进度条
            self.bar.setRange(0, 0)
        self.detail_label.setText(eta_text or "")

    def _on_verified(self, path: str) -> None:
        self._terminal = True
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.title_label.setText(_TEXT_VERIFIED)
        self.detail_label.setText("")
        self._to_terminal_buttons()
        self.download_verified.emit(path)

    def _on_finished(self, path: str) -> None:
        # 未经校验（无 sha256）路径：如实提示
        if not self._terminal:
            self.title_label.setText(_TEXT_VERIFIED_NO_SHA)
        self.download_finished.emit(path)

    def _on_failed(self, reason: str) -> None:
        self._terminal = True
        self.title_label.setText(_friendly_failure(reason))
        self.detail_label.setText("")
        self._to_terminal_buttons()
        self.download_failed.emit(reason)

    def _on_cancelled(self) -> None:
        self._terminal = True
        self.title_label.setText(_TEXT_CANCELLED)
        self.detail_label.setText("")
        self._to_terminal_buttons()
        self.download_cancelled.emit()

    def _to_terminal_buttons(self) -> None:
        self.background_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("关闭")

    # ------------------------------------------------------------------
    # 按钮
    # ------------------------------------------------------------------
    def _on_background(self) -> None:
        """后台继续：隐藏但不取消（下载继续；关闭对话框不中断）。"""
        self.backgrounded.emit()
        self.hide()

    def _on_cancel(self) -> None:
        if self._terminal:
            self.close()
            return
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消…")
        try:
            if self._worker is not None:
                self._worker.request_cancel()
        except Exception as exc:
            logger.info("请求取消下载失败（忽略）: %s", exc)
        self.cancel_requested.emit()

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """点 X 关闭 = 后台继续（不取消），与「后台继续」一致（R-A 非阻断）。"""
        if not self._terminal and self._worker is not None:
            self.backgrounded.emit()
        event.accept()
