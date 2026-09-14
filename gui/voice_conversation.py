# -*- coding: utf-8 -*-
"""免提对话控制器 —— v1.3 P2-2（design-v13 D-V13-07）

状态机（QObject 信号驱动，非阻塞）：
    idle → listening → (recognized) → sending → (回复完成)
                                                ↓
                                          speaking → listening …（循环）

- **STT 链路复用**：识别 worker 直接复用 `voice_input._RecognitionWorker`
  （SpeechRecognition + pyaudio + recognize_google zh-CN，单源不另起识别链）。
- **发送不直连 ChatService**：识别文本只经 `speech_ready(str)` 信号交由
  chat_panel 复用其 `_on_send` 路径渲染/发送（保住「UI 直插气泡唯一入口」约定，
  防双气泡）。回复朗读完成后由面板调 `notify_reply_done()` 放行回到 listening。
- **免提期暂停 A9**：start 时对 ProactiveScheduler `set_busy("handsfree", True)`，
  stop 时释放（防她在你说话时插嘴）。
- **三通道退出**：
    ① 界面 ⏹/🎙 开关（stop()）；
    ② 识别文本命中关键词（暂停 / 结束对话 / 不说了…）→ 自动回 idle；
    ③ listening 期检测到系统新输入（GetLastInputInfo 毫秒数，R-B 只取数值）
      → 视为想打字，自动停听回 idle（灵敏度常量可调，见 _poll_input_interrupt）。
- 识别失败 / 静默超时**不打断循环**：静默/听不懂自动重听；连续硬件级错误 3 次
  才自动暂停并给出说明（避免后台空转）。

顶层零 PySide6 依赖之外全部延迟/防御：无后端 / 无麦克风时 start() 返回 False，
绝不伪装可用。免提控制器为 app 级单例（挂 app_ctx.voice_conversation），
chat_window 如需入口复用同一实例，避免第二套识别链。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from gui.qt_compat import QObject, QTimer, Signal
from gui import icons
from gui.system_idle import last_input_age_ms
from gui.widgets import voice_input as _voice_input_mod

logger = logging.getLogger("maid_coder.gui.voice_conversation")

# 单例在 app_ctx 上的挂载键名（chat_panel / chat_window 共用同一控制器）
APP_CTX_KEY = "voice_conversation"

# 识别文本退出关键词（命中即视为「不想说了」，自动回 idle）
EXIT_KEYWORDS = ("暂停", "结束对话", "不说了", "先不说了", "停一下")

# 连续硬错误（设备/网络等）达到该次数 -> 自动暂停并说明
_MAX_HARD_FAILURES = 3
# 关键词命中后的「结束语」由 notice 携带，不重复打断状态
_SILENT_SOFT_MARKERS = ("timed out", "could not understand", "no speech",
                        "unknownvalue", "听不懂", "静默")
# v1.6(P1-1/D-V16-11): 软失败（听不懂/静默）反馈与上限 —— 连续 3 次给出提示、
# 6 次自动暂停（防无限空转）；识别成功即归零
_SOFT_NOTICE_AT = 3
_MAX_SOFT_FAILURES = 6
# v1.6(P1-1/D-V16-11): 免提退出恢复缓冲 —— stop() 后 10 分钟内主动陪伴不开口
# （计入四重闸而非独立闸：scheduler 读 resume_cooldown_until 注入 PolicyState）
_RESUME_BUFFER_MIN = 10

# 打断通道（③）灵敏度：进入 listening 后跳过前 N 次轮询（给用户松手/开口时间）
_INTERRUPT_SKIP_POLLS = 3
_INTERRUPT_POLL_MS = 800
# 触发阈值：检测到最近 ~450ms 内有系统输入即视为「想打字」（真机可标定微调）
_INTERRUPT_AGE_MS = 450


def _normalize_spoken(text: str) -> str:
    """去空白与标点后用于关键词判定。"""
    s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text or "")
    return s.lower()


def _looks_like_echo(text: str, spoken_snippet: str) -> bool:
    """v1.6(P1-1): 免提打断回声防护 —— 免提期 TTS 经扬声器外放，识别器可能
    把码铃自己的话转写回来造成「自己打断自己」。

    判定（保守，宁可放过不可误断）：识别文本（归一化后）是朗读文本的子串、
    或与其高度重叠（>60% 字符共用），视为回声 → 忽略本次打断。
    """
    t = _normalize_spoken(text)
    s = _normalize_spoken(spoken_snippet)
    if not t or not s:
        return False
    if t in s:
        return True
    overlap = sum(1 for ch in set(t) if ch in s)
    return len(set(t)) > 0 and overlap / len(set(t)) > 0.6


def _hit_exit_keyword(text: str) -> bool:
    n = _normalize_spoken(text)
    return any(kw in n for kw in EXIT_KEYWORDS)


def _is_soft_failure(err: str) -> bool:
    e = (err or "").lower()
    return any(m in e for m in _SILENT_SOFT_MARKERS)


class VoiceConversationController(QObject):
    """免提对话控制器（app 级单例；见模块 docstring）。"""

    #: 状态变化 idle / listening / recognizing / sending / speaking
    state_changed = Signal(str)
    #: 识别到一段话（非关键词）——由 UI 复用其发送路径（绝不直连 ChatService）
    speech_ready = Signal(str)
    #: 一次性说明文本（识别失败/自动暂停/退出提示等），UI 可闪显
    notice = Signal(str)

    STATE_IDLE = "idle"
    STATE_LISTENING = "listening"
    STATE_RECOGNIZING = "recognizing"
    STATE_SENDING = "sending"
    STATE_SPEAKING = "speaking"

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._state: str = self.STATE_IDLE
        self._worker = None  # 当前识别 worker（QThread，见 _spawn_worker）
        self._hard_failures: int = 0
        self._soft_failures: int = 0  # v1.6(P1-1): 软失败连续计数（识别成功归零）
        self._interrupt_polls: int = 0
        self._interrupt_timer: Optional[QTimer] = None
        self._busy_tag = "handsfree"
        # v1.6(P1-1/D-V16-11): 免提退出恢复缓冲（epoch 秒；scheduler 读此字段入闸）
        self.resume_cooldown_until: float = 0.0
        # v1.6(P1-1): 说话打断（barge-in）识别 worker —— speaking 期间监听用户开口
        self._bargein_worker = None
        self._spoken_snippet: str = ""  # 当前朗读文本（回声防护比对用）
        self._scheduler = getattr(app_ctx, "proactive_scheduler", None) \
            if app_ctx is not None else None
        # speaking 结束后回到 listening 的钩子（TTS state_changed(None)）
        tts = getattr(app_ctx, "tts", None) if app_ctx is not None else None
        if tts is not None and hasattr(tts, "state_changed"):
            try:
                tts.state_changed.connect(self._on_tts_state)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    def is_active(self) -> bool:
        return self._state != self.STATE_IDLE

    def start(self) -> bool:
        """开启免提：探测后端/麦克风；OK 则暂停 A9 并进入 listening。"""
        if self._state != self.STATE_IDLE:
            return True  # 已在免提中
        backend_ok, device_ok, desc = _voice_input_mod.diagnose_voice_input()
        if not backend_ok or not device_ok:
            self.notice.emit(f"免提暂不可用：{desc}")
            logger.warning("免提无法开启：%s", desc)
            return False
        self._set_busy(True)
        self._hard_failures = 0
        self._begin_listening()
        return True

    def stop(self, notice: str = "") -> None:
        """停止免提（三通道汇聚点）：释放 A9、断开 worker、停朗读，回 idle。

        v1.6(P1-1/D-V16-11): 曾激活过的停止 → 记录 10 分钟恢复缓冲
        （resume_cooldown_until），期间主动陪伴四重闸不开口。
        """
        was_active = self._state != self.STATE_IDLE
        if not was_active and not notice:
            return
        self._set_busy(False)
        worker = self._worker
        self._worker = None
        if worker is not None:
            self._disconnect_worker(worker)
        self._stop_bargein()
        self._stop_interrupt_timer()
        # 若正在朗读本控制器归属的回复 -> 停读
        if self._state == self.STATE_SPEAKING:
            self._stop_own_speech()
        if was_active:
            self.resume_cooldown_until = time.time() + _RESUME_BUFFER_MIN * 60
        self._state = self.STATE_IDLE
        self.state_changed.emit(self.STATE_IDLE)
        if notice:
            self.notice.emit(notice)

    # 由 chat_panel 在「本条语音消息的 AI 回复流结束」后回调
    def notify_reply_done(self, reply_text: str = "") -> None:
        """回复（或错误/取消）已结束：朗读回复（若可用），否则直接回 listening。

        - 不在免提中（用户已停）→ 空转；
        - speaking 前先朗读 assistant 完整回复；TTS 结束事件触发回 listening。
        """
        if self._state != self.STATE_SENDING:
            return
        text = (reply_text or "").strip()
        if self._try_speak_reply(text):
            return
        # TTS 不可用 / 没内容 -> 直接继续听
        self._begin_listening()

    def shutdown(self) -> None:
        """应用退出/面板销毁时兜底（幂等）。"""
        try:
            self.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部：listening 循环
    # ------------------------------------------------------------------
    def _begin_listening(self) -> None:
        if self._state == self.STATE_IDLE:
            return  # 已被用户停止
        if self._state == self.STATE_LISTENING:
            return
        self._state = self.STATE_LISTENING
        self.state_changed.emit(self.STATE_LISTENING)
        self._interrupt_polls = 0
        self._ensure_interrupt_timer()
        self._spawn_worker()

    def _spawn_worker(self) -> None:
        if self._worker is not None:
            return
        try:
            worker = _voice_input_mod._RecognitionWorker(self)
        except Exception as exc:
            logger.warning("免提识别 worker 创建失败: %s", exc)
            self.stop(notice="免提意外中断（识别组件异常），请重试~")
            return
        worker.recognized.connect(self._on_recognized)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_recognized(self, text: str) -> None:
        self._disconnect_worker(self._worker)
        self._worker = None
        self._stop_interrupt_timer()
        if self._state != self.STATE_LISTENING:
            return  # 期间已被停止
        raw = (text or "").strip()
        self._state = self.STATE_RECOGNIZING
        self.state_changed.emit(self.STATE_RECOGNIZING)
        if not raw:
            self._begin_listening()
            return
        if _hit_exit_keyword(raw):
            self.stop(notice=f"好～免提先暂停啦。想继续就再点一下「{icons.text_glyph('voice', '🎙')} 免提」~")
            return
        # 硬错误计数清零（成功听懂一句）
        self._hard_failures = 0
        self._soft_failures = 0  # v1.6(P1-1): 识别成功 → 软失败计数归零
        self._state = self.STATE_SENDING
        self.state_changed.emit(self.STATE_SENDING)
        self.speech_ready.emit(raw)

    def _on_failed(self, err: str) -> None:
        if self._worker is not None:
            self._disconnect_worker(self._worker)
            self._worker = None
        if self._state != self.STATE_LISTENING:
            return
        if _is_soft_failure(err):
            # v1.6(P1-1/D-V16-11): 软失败（听不懂/静默）连续计数 —— 3 次给提示、
            # 6 次自动暂停（防无限空转）；不打断退出通道
            self._soft_failures += 1
            if self._soft_failures >= _MAX_SOFT_FAILURES:
                self.stop(notice="总是听不清，免提先休息一下。建议换个安静环境，或改用打字和我聊~")
                return
            if self._soft_failures >= _SOFT_NOTICE_AT:
                self.notice.emit("没听清，建议换个安静环境，或改用打字和我聊~")
            self._begin_listening()
            return
        self._hard_failures += 1
        logger.info("免提识别硬错误(%d/%d): %s",
                    self._hard_failures, _MAX_HARD_FAILURES, err)
        if self._hard_failures >= _MAX_HARD_FAILURES:
            self.stop(notice=f"连续几次都没听清（{err}），免提已自动暂停，点「{icons.text_glyph('voice', '🎙')} 免提」可重新开始~")
            return
        self._begin_listening()

    # ------------------------------------------------------------------
    # 内部：通道 ③ 任意输入打断
    # ------------------------------------------------------------------
    def _ensure_interrupt_timer(self) -> None:
        if self._interrupt_timer is not None:
            return
        try:
            timer = QTimer(self)
            timer.setInterval(_INTERRUPT_POLL_MS)
            timer.timeout.connect(self._poll_input_interrupt)
            timer.start()
            self._interrupt_timer = timer
        except Exception:
            self._interrupt_timer = None

    def _stop_interrupt_timer(self) -> None:
        timer, self._interrupt_timer = self._interrupt_timer, None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _poll_input_interrupt(self) -> None:
        if self._state != self.STATE_LISTENING:
            return
        age = last_input_age_ms()
        if age is None:
            return  # 非 Windows / API 不可用：通道③静默关闭
        if self._interrupt_polls < _INTERRUPT_SKIP_POLLS:
            self._interrupt_polls += 1
            return
        # 检测到最近 ~450ms 内存在新输入 -> 视为想打字，自动停听
        if age < _INTERRUPT_AGE_MS:
            self.stop(notice=f"检测到你在敲键盘/动鼠标，码铃先不抢麦啦～想继续免提随时点「{icons.text_glyph('voice', '🎙')} 免提」~")

    # ------------------------------------------------------------------
    # 内部：回复朗读（speaking）
    # ------------------------------------------------------------------
    def _try_speak_reply(self, reply_text: str) -> bool:
        """尝试朗读回复；失败/不可用返回 False（由调用方直接回 listening）。

        v1.6(P1-1/D-V16-11): 朗读开始的同时挂 barge-in 识别 worker —— 用户开口
        即打断 TTS（回声防护见 _looks_like_echo；打断后话头截断 = TTS stop，
        正文气泡内容不受影响）。
        """
        config = getattr(self.app_ctx, "config", None)
        if config is not None and not bool(getattr(config, "tts_enabled", True)):
            return False
        tts = getattr(self.app_ctx, "tts", None)
        if tts is None or not getattr(tts, "available", False):
            return False
        if not reply_text:
            return False
        # 长回复截断朗读，避免长时间占麦（展示内容不受影响，只读前段）
        snippet = reply_text[:600].rstrip()
        if len(reply_text) > 600:
            snippet += "……"
        self._state = self.STATE_SPEAKING
        self.state_changed.emit(self.STATE_SPEAKING)
        try:
            ok = tts.speak(snippet, owner=self)
        except Exception:
            ok = False
        if not ok:
            self._state = self.STATE_SENDING
            return False
        self._spoken_snippet = snippet
        self._spawn_bargein()
        return True

    def _on_tts_state(self, owner) -> None:
        """TTS 归属变化：本控制器归属的朗读自然结束/被停 -> 回到 listening。"""
        if self._state != self.STATE_SPEAKING:
            return
        if owner is not None:
            return  # 新的朗读（打断）被别的 owner 接管：不重启听
        # owner 为 None：上一段朗读结束（可能被别的 owner speak() 打断也先落 None）
        self._stop_bargein()
        if self._state == self.STATE_SPEAKING:
            self._begin_listening()

    # ------------------------------------------------------------------
    # 内部：说话打断（barge-in）—— speaking 期间监听用户开口（D-V16-11 ③）
    # ------------------------------------------------------------------
    def _spawn_bargein(self) -> None:
        """朗读期间挂一路识别：用户开口 → 停 TTS + 「我在听」反馈 + 接续发送。"""
        if self._bargein_worker is not None:
            return
        try:
            worker = _voice_input_mod._RecognitionWorker(self)
        except Exception as exc:
            logger.debug("barge-in worker 创建失败（不打断朗读）: %s", exc)
            return
        worker.recognized.connect(self._on_bargein_recognized)
        worker.failed.connect(self._on_bargein_failed)
        worker.finished.connect(worker.deleteLater)
        self._bargein_worker = worker
        worker.start()

    def _stop_bargein(self) -> None:
        worker, self._bargein_worker = self._bargein_worker, None
        self._spoken_snippet = ""
        if worker is not None:
            self._disconnect_worker(worker)
            try:
                worker.quit()
            except Exception:
                pass

    def _on_bargein_recognized(self, text: str) -> None:
        """用户开口打断：停 TTS →「我在听~」→ 识别文本接续走发送链。"""
        worker, self._bargein_worker = self._bargein_worker, None
        if worker is not None:
            self._disconnect_worker(worker)
        if self._state != self.STATE_SPEAKING:
            return
        raw = (text or "").strip()
        # 回声防护：识别结果像码铃自己的朗读 → 忽略，继续挂一路听
        if not raw or _looks_like_echo(raw, self._spoken_snippet):
            if self._state == self.STATE_SPEAKING:
                self._spawn_bargein()
            return
        # 真打断：截断朗读（stop 触发 state_changed(None)，但本方法先改状态防重入）
        self._stop_bargein()
        self._state = self.STATE_SENDING
        self.state_changed.emit(self.STATE_SENDING)
        try:
            tts = getattr(self.app_ctx, "tts", None)
            if tts is not None and getattr(tts, "active_owner", None) is self:
                tts.stop()
        except Exception:
            pass
        # 打断瞬间反馈（D-V16-11：「我在听~」）
        self.notice.emit("我在听~")
        if _hit_exit_keyword(raw):
            self.stop(notice=f"好～免提先暂停啦。想继续就再点一下「{icons.text_glyph('voice', '🎙')} 免提」~")
            return
        self._hard_failures = 0
        self._soft_failures = 0
        self.speech_ready.emit(raw)

    def _on_bargein_failed(self, err: str) -> None:
        """朗读期间识别失败：静默重挂（不打断朗读、不累计听写失败）。"""
        worker, self._bargein_worker = self._bargein_worker, None
        if worker is not None:
            self._disconnect_worker(worker)
        if self._state == self.STATE_SPEAKING:
            self._spawn_bargein()

    def _stop_own_speech(self) -> None:
        tts = getattr(self.app_ctx, "tts", None)
        if tts is not None and getattr(tts, "active_owner", None) is self:
            try:
                tts.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 内部：worker / busy 清理
    # ------------------------------------------------------------------
    @staticmethod
    def _disconnect_worker(worker) -> None:
        if worker is None:
            return
        for sig in ("recognized", "failed"):
            try:
                s = getattr(worker, sig, None)
                if s is not None:
                    s.disconnect()
            except (TypeError, RuntimeError):
                pass

    def _set_busy(self, busy: bool) -> None:
        sched = getattr(self.app_ctx, "proactive_scheduler", None) \
            if self.app_ctx is not None else self._scheduler
        if sched is None or not hasattr(sched, "set_busy"):
            return
        try:
            sched.set_busy(self._busy_tag, busy)
        except Exception:
            pass
