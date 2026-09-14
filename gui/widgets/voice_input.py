"""语音输入 —— UI 入口 + ASR 后端探测（沙箱无麦克风与依赖时如实标注）。

可用性矩阵（运行时探测，不伪造）：

- SpeechRecognition / PyAudio 不可导入 → 后端缺失，UI 入口打开说明对话框
- 导入成功但 sr.Microphone() 不可用（无麦克风设备）→ 后端存在但无设备
- 都就绪 → 启动识别对话框，按住「开始录音」→ 识别 → 文字回填到输入框

> 当前沙箱（PySide6 GUI 容器）无音频硬件、未安装 SpeechRecognition/PyAudio，
> 实际不可运行；本模块保证：代码路径完整、UI 入口存在、不可用时弹出明确说明，
> 不伪装录音可用。所有新增颜色取自 theme_color。
"""
from __future__ import annotations

import importlib
import traceback
from typing import Optional, Tuple

from gui.qt_compat import (
    Qt, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QThread, Signal, QSizePolicy,
)
from gui.utils import theme_color
from gui import icons


_SR_MODULE = None
_SR_IMPORT_ERROR: Optional[str] = None
try:
    _SR_MODULE = importlib.import_module("speech_recognition")
except Exception as exc:  # ImportError / ModuleNotFoundError
    _SR_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def stt_backend_available() -> bool:
    """SpeechRecognition 是否可导入。"""
    return _SR_MODULE is not None


def stt_backend_error() -> Optional[str]:
    """未导入时的原因（用于 UI 提示）；可用时返回 None。"""
    return _SR_IMPORT_ERROR


def microphone_available() -> bool:
    """检测麦克风设备是否可用（不可用 = 沙箱环境 / 未授权 / 驱动缺失）。"""
    if _SR_MODULE is None:
        return False
    try:
        recognizer = _SR_MODULE.Recognizer()
        with _SR_MODULE.Microphone() as _source:
            return True
    except Exception:
        return False


def diagnose_voice_input() -> Tuple[bool, bool, str]:
    """三态诊断：(后端可用, 设备可用, 描述)。"""
    backend_ok = stt_backend_available()
    if not backend_ok:
        return False, False, f"未检测到语音识别后端（{_SR_IMPORT_ERROR or 'SpeechRecognition 未安装'}）"
    device_ok = microphone_available()
    if not device_ok:
        return True, False, "语音识别后端已就绪，但当前环境无可用麦克风设备"
    return True, True, "语音识别后端与麦克风均就绪"


class _RecognitionWorker(QThread):
    """R3: 录音 + 识别在独立线程执行，避免同步阻塞 GUI 线程（此前最长 8.8s 冻结）。"""

    recognized = Signal(str)     # 识别成功（最终文本）
    failed = Signal(str)         # 识别失败（错误描述）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sr = _SR_MODULE

    def run(self) -> None:
        try:
            recognizer = self._sr.Recognizer()
            with self._sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=8)
            # 默认使用 Google Web Speech（在线、免费、需网络）
            try:
                text = recognizer.recognize_google(audio, language="zh-CN")
            except Exception:
                # 失败时回退到 Sphinx 离线（需 pocketsphinx，可选）
                try:
                    text = recognizer.recognize_sphinx(audio, language="zh-CN")
                except Exception:
                    raise
            self.recognized.emit(text)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}：{exc}")


class VoiceInputDialog(QDialog):
    """语音输入对话框：按「开始录音」→ 后台线程识别 → 文字显示并允许编辑。"""

    def __init__(self, app_ctx, parent=None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        self.setWindowTitle("语音输入")
        self.setMinimumSize(420, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("voiceStatusLabel")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("voiceTranscriptEdit")
        self.text_edit.setPlaceholderText("识别结果将显示在此，可手动编辑后确认...")
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.text_edit, 1)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton(f"{icons.text_glyph('voice', '🎙')} 开始录音")
        self.start_btn.setObjectName("voiceStartBtn")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setFixedHeight(36)
        self.start_btn.clicked.connect(self._on_start_clicked)
        btn_row.addWidget(self.start_btn)

        btn_row.addStretch()

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setObjectName("voiceCancelBtn")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.confirm_btn = QPushButton("使用此文字")
        self.confirm_btn.setObjectName("voiceConfirmBtn")
        self.confirm_btn.setFixedHeight(36)
        self.confirm_btn.setDefault(True)
        self.confirm_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.confirm_btn)

        layout.addLayout(btn_row)

        # R3: 录音 worker 引用（识别期间持有，结束/失败/关闭时清理）
        self._worker: Optional[_RecognitionWorker] = None

        self._apply_theme()

        # 启动时探测
        backend_ok, device_ok, desc = diagnose_voice_input()
        if not backend_ok or not device_ok:
            self.start_btn.setEnabled(False)
            self.status_label.setText(
                f"{icons.text_glyph('warning', '⚠')} {desc}\n请安装 SpeechRecognition / PyAudio 并连接麦克风后重试。"
            )
        else:
            self.status_label.setText(
                f"{icons.text_glyph('check', '✓')} {desc}，点击「开始录音」开始（最长 8 秒）。"
            )

    # ------------------------------------------------------------------
    def _apply_theme(self) -> None:
        bg = theme_color(self._app_ctx, "bg_card", "#FFFFFF")
        text = theme_color(self._app_ctx, "text", "#4A4A4A")
        secondary = theme_color(self._app_ctx, "text_secondary", "#8A8A8A")
        primary = theme_color(self._app_ctx, "primary", "#FFB6C1")
        primary_dark = theme_color(self._app_ctx, "primary_dark", "#FF69B4")
        accent = theme_color(self._app_ctx, "accent", "#FF6B9D")
        border = theme_color(self._app_ctx, "border", "#E0E0E0")
        text_on_accent = theme_color(self._app_ctx, "text_on_accent", "#FFFFFF")
        disabled_bg = theme_color(self._app_ctx, "disabled_bg", "#E0E0E0")
        disabled_text = theme_color(self._app_ctx, "disabled_text", "#9E9E9E")

        self.setStyleSheet(
            f"QDialog {{ background: {bg}; color: {text}; }}"
        )
        self.status_label.setStyleSheet(f"color: {secondary}; font-size: 12px;")
        self.text_edit.setStyleSheet(
            f"QTextEdit#voiceTranscriptEdit {{"
            f"  background: {bg}; color: {text};"
            f"  border: 1px solid {border}; border-radius: 8px;"
            f"  padding: 8px; font-size: 14px;"
            f"}}"
        )
        for btn, fill, hover in [
            (self.start_btn, primary, primary_dark),
            (self.confirm_btn, accent, primary_dark),
        ]:
            btn.setStyleSheet(
                f"QPushButton {{ background: {fill}; color: {text_on_accent}; border: none;"
                f"  border-radius: 8px; padding: 4px 16px; font-size: 13px; }}"
                f"QPushButton:hover {{ background: {hover}; }}"
                f"QPushButton:disabled {{ background: {disabled_bg}; color: {disabled_text}; }}"
            )
        self.cancel_btn.setStyleSheet(
            f"QPushButton#voiceCancelBtn {{"
            f"  background: transparent; color: {secondary};"
            f"  border: 1px solid {border}; border-radius: 8px;"
            f"  padding: 4px 16px; font-size: 13px;"
            f"}}"
            f"QPushButton#voiceCancelBtn:hover {{ background: {border}; color: {text}; }}"
        )

    # ------------------------------------------------------------------
    @property
    def transcript(self) -> str:
        return self.text_edit.toPlainText().strip()

    # ----- R3: 录音/识别移入 QThread，信号回传，按钮状态随信号切换 -----
    def _on_start_clicked(self) -> None:
        if _SR_MODULE is None:
            self.status_label.setText(
                f"{icons.text_glyph('warning', '⚠')} SpeechRecognition 未安装，无法录音。"
            )
            return
        if self._worker is not None and self._worker.isRunning():
            return
        worker = _RecognitionWorker(self)
        worker.recognized.connect(self._on_recognized)
        worker.failed.connect(self._on_recognition_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self.start_btn.setEnabled(False)
        self.cancel_btn.setText("后台录音中")
        self.status_label.setText("录音中... 请说话（最长 8 秒，窗口可自由操作）")
        worker.start()

    def _on_recognized(self, text: str) -> None:
        self._worker = None
        self.start_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self.text_edit.setPlainText(text)
        self.status_label.setText(
            f"{icons.text_glyph('check', '✓')} 识别完成，可编辑后点击「使用此文字」"
        )

    def _on_recognition_failed(self, err: str) -> None:
        self._worker = None
        self.start_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self.status_label.setText(
            f"{icons.text_glyph('warning', '⚠')} 识别失败：{err}\n"
            f"可手动在下方编辑文字后确认。"
        )

    def _shutdown_worker(self) -> None:
        """对话框关闭时断开 worker 信号（listen 无法安全中断，任其后台结束并自回收）。"""
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        for sig, slot in [
            (worker.recognized, self._on_recognized),
            (worker.failed, self._on_recognition_failed),
        ]:
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass

    def closeEvent(self, event) -> None:
        self._shutdown_worker()
        super().closeEvent(event)

    def reject(self) -> None:
        self._shutdown_worker()
        super().reject()


def build_unavailable_message() -> str:
    """给 chat_panel 在没有后端时弹给用户看的完整说明。"""
    backend_ok, device_ok, desc = diagnose_voice_input()
    return (
        f"语音输入暂不可用：{desc}。\n\n"
        f"如需启用，请按以下步骤之一：\n"
        f"  1) 安装本地后端：pip install SpeechRecognition pyaudio（需真实麦克风与可访问 Google 语音 API 的网络）。\n"
        f"  2) 接入公司/自建的 ASR 模型 API（修改 gui/widgets/voice_input.py 中 recognize_* 调用）。\n\n"
        f"当前沙箱/无头环境无法测试，但代码路径已实现并接入；一旦依赖就绪、麦克风可用即可使用。"
    )
