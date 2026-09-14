"""gui/tts.py —— v1.3 P1-1 TTS 语音输出（她开口说话）

设计（docs/design-v13.md D-V13-02，标红实现路径微调）：
  - 默认后端 = PySide6.QtTextToSpeech（Windows 底层即 SAPI5）：随 PySide6 体系、
    零新增第三方依赖、纯本地离线（R-E/R-F）；不手写 ctypes COM 绑定（约 200 行脆弱代码）。
  - 可插拔后端：TTSBackend 抽象，SapiBackend 为默认实现；edge-tts（联网、文本上云）
    仅留后端口注释（P2+ 可插拔实现，v1.3 零实现、零交付、不开默认入口）。
  - 全局单例 TTSController（QObject，挂 app_ctx.tts，main.py 装配）：
    speak(text, owner) 多气泡并发「后开口打断前开口」；owner 供 UI 恢复「🔊 朗读/⏹ 停止」按钮态。
  - 红线：只朗读 AI 回复文本（不朗读用户原文，隐私）；朗读不中断正在进行的打字/流式
    （回复已完成才触发 auto_read）；无 key 演示模式无回复不朗读（守卫在 chat_service）。
  - 降级（三态探测风格，绝不崩）：QtTextToSpeech import 失败 / 引擎不可用 /
    availableVoices() 为空 → available=False + availability_reason 可读原因，
    语音区与朗读按钮点击给一句说明。
"""
from __future__ import annotations

import logging
from typing import Optional

from gui.qt_compat import QObject, Signal, QTimer

logger = logging.getLogger("maid_coder.gui")

# 系统缺中文语音包 / 引擎缺失时的可读降级文案（语音区 / 朗读按钮共用）
TTS_MISSING_VOICE_HINT = "未检测到系统语音，请到 Windows 语音设置添加中文语音包"
TTS_BACKEND_UNAVAILABLE_HINT = "系统 TTS 组件不可用（QtTextToSpeech 未加载）"

# ---- 防御式加载 QtTextToSpeech（弱环境降级：import 失败 -> 后端不可用，不崩）----
try:
    from PySide6.QtTextToSpeech import QTextToSpeech
    _TTS_OK = True
except Exception as _e:  # 运行环境无 QtTextToSpeech 插件/DLL
    _TTS_OK = False
    logger.debug("QtTextToSpeech 不可用: %s", _e)


# ---------------------------------------------------------------------------
# 后端抽象（可插拔；edge-tts 后端口注释见模块 docstring，v1.3 不交付）
# ---------------------------------------------------------------------------
class TTSBackend:
    """朗读后端抽象接口。v1.3 仅实现 SapiBackend（QtTextToSpeech/SAPI5）。"""

    def available(self) -> bool:  # pragma: no cover - 抽象接口
        raise NotImplementedError

    def availability_reason(self) -> str:  # pragma: no cover
        raise NotImplementedError

    def speak(self, text: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def stop(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def is_speaking(self) -> bool:  # pragma: no cover
        raise NotImplementedError

    def set_rate(self, speed_0_100: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def set_state_callback(self, cb) -> None:  # pragma: no cover
        raise NotImplementedError


class SapiBackend(TTSBackend):
    """默认后端：PySide6.QtTextToSpeech（Windows SAPI5 引擎）。"""

    def __init__(self) -> None:
        self._engine = None
        self._reason = TTS_BACKEND_UNAVAILABLE_HINT
        if _TTS_OK:
            try:
                self._engine = QTextToSpeech()  # 默认引擎 = SAPI5
                self._reason = ""
            except Exception as exc:
                logger.warning("QTextToSpeech 初始化失败: %s", exc)
                self._engine = None
                self._reason = TTS_BACKEND_UNAVAILABLE_HINT
        self._state_cb = None

    def available(self) -> bool:
        return self._engine is not None

    def availability_reason(self) -> str:
        return self._reason

    def has_voices(self) -> bool:
        """探测 availableVoices：为空 = 系统没有可用语音（如缺中文语音包）。"""
        if self._engine is None:
            return False
        try:
            return bool(self._engine.availableVoices())
        except Exception:
            return False

    def set_state_callback(self, cb) -> None:
        self._state_cb = cb
        if self._engine is None:
            return
        try:
            self._engine.stateChanged.connect(cb)
        except Exception as exc:
            logger.debug("QTextToSpeech stateChanged 连接失败: %s", exc)

    def set_rate(self, speed_0_100: int) -> None:
        """UI 语速 0..100 -> 引擎 rate（QtTextToSpeech 语义约 -1.0..1.0，0=常速）。"""
        if self._engine is None:
            return
        try:
            val = speed_0_100 if speed_0_100 is not None else 50
            val = max(0, min(100, int(val)))
            rate = (val - 50) / 50.0
            self._engine.setRate(rate)
        except Exception as exc:
            logger.debug("设置语速失败（可忽略）: %s", exc)

    def set_voice_hint(self, hint: str) -> bool:
        """v1.6(P1-1): 按名称关键词切音色（角色音色同步用）。

        在 availableVoices 里找 name/locale 含 hint 的第一个语音并应用；
        找不到/引擎不可用 → 保持现状返回 False（诚实降级，不伪装切换）。
        """
        if self._engine is None or not (hint or "").strip():
            return False
        try:
            voices = self._engine.availableVoices() or []
            key = str(hint).strip().lower()
            for v in voices:
                name = ""
                try:
                    name = f"{v.name()} {v.locale().name()}".lower()
                except Exception:
                    name = str(v).lower()
                if key in name:
                    self._engine.setVoice(v)
                    return True
        except Exception as exc:
            logger.debug("按提示切换音色失败（保持现状）: %s", exc)
        return False

    def speak(self, text: str) -> None:
        if self._engine is None or not text:
            return
        try:
            self._engine.say(text)
        except Exception as exc:
            logger.warning("TTS 朗读失败: %s", exc)

    def stop(self) -> None:
        if self._engine is None:
            return
        try:
            self._engine.stop()
        except Exception:
            pass

    def is_speaking(self) -> bool:
        if self._engine is None:
            return False
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            return self._engine.state() == QTextToSpeech.State.Speaking
        except Exception:
            return False


# ---------------------------------------------------------------------------
# TTSController —— app 级全局单例（多气泡并发「后开口打断前开口」）
# ---------------------------------------------------------------------------
class TTSController(QObject):
    """朗读控制器：全局单例（app_ctx.tts）。

    - speak(text, owner=None)：打断上一段朗读；owner 供 UI 把对应气泡切成「⏹ 停止」。
    - stop()：停止当前朗读。
    - state_changed(owner)：朗读归属变化（owner = 正在朗读的气泡或 None）。
    - availability_changed(bool)：后端/语音可用性探测完成后发出（设置页语音区刷新）。
    """

    state_changed = Signal(object)        # owner: QWidget 气泡 or None
    availability_changed = Signal(bool)   # 探测完成后的可用性

    def __init__(self, app_ctx, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.app_ctx = app_ctx
        self._backend = SapiBackend()  # 内部防御：引擎建不出 => available False + reason
        self._reading = False
        self._active_owner = None
        self._probed_voices = False
        self._voices_empty = False
        self._rate_value: int = 50
        # v1.6(P1-1): 角色音色联动 —— 当前角色语速偏置（0 = 跟随设置页）
        self._role_rate_bias: int = 0
        if self._backend is not None and self._backend.available():
            self._backend.set_state_callback(self._on_backend_state)
        # v1.6(P1-1/D-V16-11): 切换角色 → 音色参数同步（role_bridge 单向订阅；
        # 无 bridge / 查不到角色 → 保持现状，诚实降级）
        try:
            bridge = getattr(app_ctx, "role_bridge", None)
            if bridge is not None and hasattr(bridge, "role_changed"):
                bridge.role_changed.connect(self._on_role_changed)
        except Exception:
            pass

    # -- 生命周期/探测 --
    def start(self) -> bool:
        """后台非阻塞探测可用语音（availableVoices 可能需引擎就绪，错峰探测两次）。

        第一轮（200ms）能确认有语音 -> 立即可用；仍为空则等第二轮（900ms）定判。
        两轮都空 -> _voices_empty=True（degraded），语音区/朗读按钮显示降级提示。
        """
        if self._backend is None or not self._backend.available():
            self._probed_voices = True
            self._voices_empty = False  # 组件缺失走 availability_reason（组件不可用）
            self.availability_changed.emit(False)
            return False
        try:
            QTimer.singleShot(200, self._probe_voices_first)
            QTimer.singleShot(900, self._probe_voices_final)
        except Exception:
            pass
        return True

    def _probe_voices_first(self) -> None:
        if self._probed_voices or self._backend is None:
            return
        try:
            has = self._backend.has_voices()
        except Exception:
            has = False
        if has:
            self._voices_empty = False
            self._probed_voices = True
            self.availability_changed.emit(True)

    def _probe_voices_final(self) -> None:
        if self._probed_voices:
            return
        self._probed_voices = True
        ok = False
        if self._backend is not None and self._backend.available():
            try:
                ok = self._backend.has_voices()
            except Exception:
                ok = False
        self._voices_empty = not ok
        self.availability_changed.emit(ok)

    @property
    def available(self) -> bool:
        """总开关之外的真实可用性：后端在 + 探测到语音。未探测完成前按后端可用乐观放行。"""
        if self._backend is None:
            return False
        if not self._backend.available():
            return False
        if self._probed_voices and self._voices_empty:
            return False
        return True

    @property
    def availability_reason(self) -> str:
        if self._backend is None or not self._backend.available():
            return TTS_BACKEND_UNAVAILABLE_HINT
        if self._probed_voices and self._voices_empty:
            return TTS_MISSING_VOICE_HINT
        return ""

    @property
    def degraded(self) -> bool:
        return not self.available

    # -- 对外朗读 API --
    def speak(self, text: str, owner=None) -> bool:
        """朗读一段文本。后开口打断前开口；返回是否已受理（True=正在/将朗读）。"""
        if not self.available or not (text or "").strip():
            return False
        if self._backend is None:
            return False
        # 总开关（GuiConfig.tts_enabled）守卫放消费侧，控制器不重复读配置
        try:
            self._backend.stop()  # 打断前一段
        except Exception:
            pass
        self._apply_rate_from_config()
        self._reading = True
        self._active_owner = owner
        self.state_changed.emit(owner)
        try:
            self._backend.speak(text.strip())
        except Exception as exc:
            logger.warning("TTS speak 异常: %s", exc)
            self._reading = False
            self._active_owner = None
            self.state_changed.emit(None)
            return False
        return True

    def stop(self) -> None:
        if self._backend is not None:
            try:
                self._backend.stop()
            except Exception:
                pass
        self._finish_reading()

    def shutdown(self) -> None:
        try:
            self.stop()
        except Exception:
            pass

    @property
    def is_speaking(self) -> bool:
        if self._reading:
            return True
        if self._backend is not None and self._backend.available():
            try:
                return self._backend.is_speaking()
            except Exception:
                return False
        return False

    @property
    def active_owner(self):
        return self._active_owner

    # -- 语速 --
    def _apply_rate_from_config(self) -> None:
        config = getattr(self.app_ctx, "config", None)
        val = int(getattr(config, "tts_speed", 50) or 50) if config is not None else 50
        # v1.6(P1-1): 叠加角色语速偏置（角色音色联动），钳位 0..100
        try:
            val = max(0, min(100, val + int(self._role_rate_bias or 0)))
        except Exception:
            pass
        if val != self._rate_value and self._backend is not None:
            self._backend.set_rate(val)
            self._rate_value = val

    def set_speed(self, value: int) -> None:
        """设置页语速滑条即时调用。"""
        try:
            self._rate_value = max(0, min(100, int(value or 50)))
        except Exception:
            self._rate_value = 50
        if self._backend is not None:
            self._backend.set_rate(self._rate_value)

    # -- v1.6(P1-1/D-V16-11): 角色音色同步（role_bridge → voice 配置联动）--
    #: 预置角色音色参数（可选 "voice"=引擎语音名关键词 / "rate_bias"=语速偏置
    #: -20..20，叠加在设置页语速上；未收录角色 = 跟随全局设置，不伪装定制）
    ROLE_VOICE_HINTS = {
        "preset_cat": {"rate_bias": 8},      # 猫娘：语速略快显活泼
        "preset_dr": {"rate_bias": -6},      # 毒舌博士：语速略慢显沉稳
        "preset_whale": {"rate_bias": -4},   # 鲸鱼娘：语速略慢显温柔
    }

    def _on_role_changed(self, role_id: str, _avatar_path: str = "",
                         _base_expr: str = "") -> None:
        try:
            self.apply_role_voice(str(role_id or ""))
        except Exception:
            pass

    def apply_role_voice(self, role_id: str) -> bool:
        """按当前角色应用音色参数（语速偏置 + 可选音色关键词）。

        角色 id 解析出名称/预设参数：RoleManager 查角色；音色关键词优先取
        ROLE_VOICE_HINTS[role_id]["voice"]，无则只做语速偏置。未收录角色 →
        偏置归零（回到跟随设置页），返回 False（诚实降级）。
        """
        hint = self.ROLE_VOICE_HINTS.get(str(role_id or ""))
        # 名称反查兜底（role_bridge 只广播 id）
        name = ""
        try:
            from gui.pages.page_role import RoleManager
            role = RoleManager().get_role(str(role_id or ""))
            if role is not None:
                name = str(getattr(role, "name", "") or "")
        except Exception:
            name = ""
        if hint is None:
            hint = self.ROLE_VOICE_HINTS.get(name)
        applied = False
        bias = int((hint or {}).get("rate_bias", 0) or 0)
        if bias != self._role_rate_bias:
            self._role_rate_bias = bias
            applied = True
        self._apply_rate_from_config()
        voice_kw = (hint or {}).get("voice")
        if voice_kw and self._backend is not None:
            try:
                applied = self._backend.set_voice_hint(str(voice_kw)) or applied
            except Exception:
                pass
        if hint is None:
            return False
        return applied

    # -- 内部 --
    def _on_backend_state(self, state) -> None:
        """QTextToSpeech 状态变化：Speaking -> Ready（自然结束 / 被停止）。"""
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
            if state != QTextToSpeech.State.Speaking and self._reading:
                self._finish_reading()
        except Exception:
            pass

    def _finish_reading(self) -> None:
        self._reading = False
        self._active_owner = None
        self.state_changed.emit(None)
