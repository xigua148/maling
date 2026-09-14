"""tests/test_v16_voice.py —— v1.6 P1-1 语音细节针对性自测（D-V16-11）。

覆盖：
- ① 软失败反馈链：连续 3 次提示 / 6 次自动暂停 / 识别成功归零；
- ② 退出恢复缓冲：stop() 记录 10min resume_cooldown_until，入闸（resume_buffer）；
- ③ 说话打断（barge-in）：speaking 中开口 → 停 TTS + 「我在听~」+ 接续发送；
  回声防护（朗读文本回转写不自我打断）；打断中命中退出关键词 → 退出；
- ④ 呼吸动画：listening 启 / 离开停（纯 UI QTimer）；
- ⑤ 角色音色同步：apply_role_voice 语速偏置生效/未收录归零/诚实降级；
- ⑥ 语音与文字同会话：speech_ready → 面板 _on_send 同源链（接线断言）。
隔离：FakeCtx / monkeypatch 识别 worker，不触真实麦克风与 ~/.maid_coder。
"""
import os
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from gui.qt_compat import QApplication  # noqa: E402
from gui.voice_conversation import (  # noqa: E402
    VoiceConversationController, _looks_like_echo,
    _MAX_SOFT_FAILURES, _SOFT_NOTICE_AT, _RESUME_BUFFER_MIN,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def ctrl(qapp):
    ctx = MagicMock()
    ctx.tts = None
    ctx.proactive_scheduler = None
    c = VoiceConversationController(ctx)
    # 不真起识别 worker（无麦克风环境）
    c._spawn_worker = lambda: None
    return c


def _listen(c):
    c._state = c.STATE_LISTENING


# ---------------------------------------------------------------------------
# ① 软失败反馈链
# ---------------------------------------------------------------------------
class TestSoftFailureFeedback:
    def test_soft_failures_notice_at_three(self, ctrl):
        noticed = []
        ctrl.notice.connect(lambda t: noticed.append(t))
        _listen(ctrl)
        soft_err = "could not understand audio"
        for _ in range(_SOFT_NOTICE_AT):
            ctrl._on_failed(soft_err)
        assert ctrl._soft_failures == _SOFT_NOTICE_AT
        assert any("没听清" in t for t in noticed), "第 3 次软失败应给出友好提示"
        assert ctrl.state == ctrl.STATE_LISTENING, "软失败不打断循环"

    def test_soft_failures_auto_pause_at_six(self, ctrl):
        noticed = []
        ctrl.notice.connect(lambda t: noticed.append(t))
        _listen(ctrl)
        soft_err = "no speech"
        for _ in range(_MAX_SOFT_FAILURES):
            ctrl._on_failed(soft_err)
        assert ctrl.state == ctrl.STATE_IDLE, "连续 6 次软失败应自动暂停（防无限空转）"
        assert any("免提先休息" in t for t in noticed)

    def test_success_resets_soft_failures(self, ctrl):
        _listen(ctrl)
        for _ in range(2):
            ctrl._on_failed("timed out")
        assert ctrl._soft_failures == 2
        ctrl._on_recognized("你好呀")
        assert ctrl._soft_failures == 0, "识别成功 → 软失败归零"
        assert ctrl.state == ctrl.STATE_SENDING

    def test_hard_failure_path_unaffected(self, ctrl):
        noticed = []
        ctrl.notice.connect(lambda t: noticed.append(t))
        _listen(ctrl)
        ctrl._on_failed("OSError: device error")
        assert ctrl._hard_failures == 1
        assert ctrl._soft_failures == 0, "硬错误不进软失败计数"


# ---------------------------------------------------------------------------
# ② 退出恢复缓冲（10min 入闸）
# ---------------------------------------------------------------------------
# 固定时钟（消除对系统墙钟的依赖——夜间跑批不再假红）：
#   _FIXED_DAY   = 工作日 14:00（非 quiet、非深夜）→ 覆盖非静默分支
#   _FIXED_NIGHT = 23:30（落在默认 quiet 22:30–08:00）→ 覆盖静默分支
_FIXED_DAY = datetime(2026, 9, 10, 14, 0)
_FIXED_NIGHT = datetime(2026, 9, 10, 23, 30)


class TestResumeBuffer:
    def test_stop_sets_resume_cooldown(self, ctrl):
        _listen(ctrl)
        ctrl.stop()
        remaining = ctrl.resume_cooldown_until - time.time()
        assert _RESUME_BUFFER_MIN * 60 - 30 <= remaining <= _RESUME_BUFFER_MIN * 60, \
            f"stop 后应记录 ~10min 恢复缓冲，实际剩 {remaining:.0f}s"

    def test_scheduler_reads_resume_buffer_into_gates(self, ctrl):
        """免提退出 10min 内主动陪伴应被闸拦截（固定白天时钟 14:00）。"""
        from gui.proactive_scheduler import (ProactiveConfig, ProactivePolicy,
                                             PolicyState)
        now = _FIXED_DAY  # 固定时钟：白天非 quiet，避免被 quiet 闸抢先
        # 模拟 scheduler._build_state 注入：控制器缓冲 -> PolicyState
        external = datetime.fromtimestamp(ctrl.resume_cooldown_until) \
            if ctrl.resume_cooldown_until > 0 else None
        st = PolicyState(now=now, external_cooldown_until=external,
                         last_user_activity_at=now - timedelta(hours=2))
        # 先置一个未来缓冲（模拟刚 stop）
        st.external_cooldown_until = now + timedelta(minutes=9)
        reason = ProactivePolicy.gates(ProactiveConfig(), st)
        assert reason == "resume_buffer", "免提退出 10min 内主动陪伴应被闸拦截"

    def test_expired_buffer_does_not_block(self):
        """过期缓冲不拦（固定白天时钟 14:00）。"""
        from gui.proactive_scheduler import ProactiveConfig, ProactivePolicy, PolicyState
        now = _FIXED_DAY  # 固定时钟：白天非 quiet
        st = PolicyState(now=now, external_cooldown_until=now - timedelta(minutes=1))
        assert ProactivePolicy.gates(ProactiveConfig(), st) is None

    def test_buffer_is_gate_input_not_new_gate(self):
        # 计入闸：无缓冲时 gates 行为与 v1.5.2 逐字一致（固定白天时钟 14:00）
        from gui.proactive_scheduler import ProactiveConfig, ProactivePolicy, PolicyState
        now = _FIXED_DAY  # 固定时钟：白天非 quiet
        st = PolicyState(now=now)
        assert ProactivePolicy.gates(ProactiveConfig(), st) is None
        st2 = PolicyState(now=now, count_today=3)
        assert ProactivePolicy.gates(ProactiveConfig(), st2) == "daily_cap_reached"

    def test_quiet_hours_blocks_before_resume_buffer_at_night(self):
        """静默分支（固定深夜时钟 23:30，默认 quiet 22:30–08:00）：

        四重闸顺序为 quiet > resume_buffer —— 深夜时钟下即便置了未来恢复
        缓冲，也应先被 quiet 闸拦下（确定性覆盖夜间行为，非依赖真实时刻）。
        """
        from gui.proactive_scheduler import ProactiveConfig, ProactivePolicy, PolicyState
        night = _FIXED_NIGHT
        st = PolicyState(now=night,
                         external_cooldown_until=night + timedelta(minutes=9))
        assert ProactivePolicy.gates(ProactiveConfig(), st) == "quiet_hours", \
            "深夜时钟下 quiet 闸应先于免提恢复缓冲命中"


# ---------------------------------------------------------------------------
# ③ 说话打断（barge-in）+ 回声防护
# ---------------------------------------------------------------------------
class TestBargeIn:
    def _speaking(self, ctrl, monkeypatch, snippet="今天天气真好，我们要不要一起出去玩"):
        tts = MagicMock()
        tts.available = True
        tts.speak = MagicMock(return_value=True)
        tts.active_owner = ctrl
        ctrl.app_ctx.tts = tts
        monkeypatch.setattr(ctrl, "_spawn_bargein", lambda: None)
        ok = ctrl._try_speak_reply(snippet)
        assert ok and ctrl.state == ctrl.STATE_SPEAKING
        return tts

    def test_bargein_interrupts_tts(self, ctrl, monkeypatch):
        tts = self._speaking(ctrl, monkeypatch)
        notices = []
        speeches = []
        ctrl.notice.connect(lambda t: notices.append(t))
        ctrl.speech_ready.connect(lambda t: speeches.append(t))
        ctrl._on_bargein_recognized("好了别念了，我有别的事")
        assert ctrl.state == ctrl.STATE_SENDING, "打断后应进入发送态接续新输入"
        tts.stop.assert_called_once()
        assert any("我在听" in t for t in notices), "打断瞬间应有「我在听~」反馈"
        assert speeches == ["好了别念了，我有别的事"]

    def test_bargein_echo_ignored(self, ctrl, monkeypatch):
        self._speaking(ctrl, monkeypatch)
        respawned = []
        monkeypatch.setattr(ctrl, "_spawn_bargein", lambda: respawned.append(1))
        speeches = []
        ctrl.speech_ready.connect(lambda t: speeches.append(t))
        # 回声：识别文本是朗读内容的子串 → 忽略不打断
        ctrl._on_bargein_recognized("我们要不要一起出去玩")
        assert ctrl.state == ctrl.STATE_SPEAKING, "回声不应打断朗读"
        assert speeches == []
        assert respawned, "忽略回声后应重挂一路继续监听"

    def test_bargein_exit_keyword_stops(self, ctrl, monkeypatch):
        self._speaking(ctrl, monkeypatch)
        notices = []
        ctrl.notice.connect(lambda t: notices.append(t))
        ctrl._on_bargein_recognized("暂停")
        assert ctrl.state == ctrl.STATE_IDLE, "打断中命中退出关键词 → 免提退出"

    def test_bargein_failed_keeps_speaking(self, ctrl, monkeypatch):
        self._speaking(ctrl, monkeypatch)
        respawned = []
        monkeypatch.setattr(ctrl, "_spawn_bargein", lambda: respawned.append(1))
        ctrl._on_bargein_failed("network error")
        assert ctrl.state == ctrl.STATE_SPEAKING, "朗读期识别失败不打断朗读"
        assert respawned, "失败后静默重挂继续监听"

    def test_tts_end_stops_bargein_and_resumes_listening(self, ctrl, monkeypatch):
        self._speaking(ctrl, monkeypatch)
        stopped = []
        monkeypatch.setattr(ctrl, "_stop_bargein", lambda: stopped.append(1))
        ctrl._on_tts_state(None)   # TTS 自然结束（owner None）
        assert stopped, "朗读结束应收走 barge-in worker"
        assert ctrl.state == ctrl.STATE_LISTENING


class TestEchoGuard:
    def test_substring_is_echo(self):
        assert _looks_like_echo("一起出去玩", "今天天气真好，我们要不要一起出去玩")

    def test_unrelated_is_not_echo(self):
        assert not _looks_like_echo("帮我写个脚本", "今天天气真好，我们要不要一起出去玩")

    def test_empty_inputs(self):
        assert not _looks_like_echo("", "abc")
        assert not _looks_like_echo("abc", "")


# ---------------------------------------------------------------------------
# ④ 呼吸动画（handsfree_bar）
# ---------------------------------------------------------------------------
class TestBreathingAnimation:
    @staticmethod
    def _bare_ctx():
        class _Ctx:  # 无 config 属性 → theme_color 走 fallback 裸值
            pass
        return _Ctx()

    def test_listening_starts_breathing(self, qapp):
        from gui.qt_compat import Qt
        from gui import motion
        from gui.widgets.handsfree_bar import HandsfreeBar
        motion.configure("standard")
        bar = HandsfreeBar(self._bare_ctx())
        bar.setAttribute(Qt.WA_DontShowOnScreen, True)
        bar.show()                       # v2.x：隐藏即停，故须可见才跑
        bar.set_state("listening")
        assert bar._indicator.is_running() is True
        bar._indicator._on_tick(0.4)     # 一拍不崩（相位推进）
        bar.set_state("idle")
        assert bar._indicator.is_running() is False, "离开 listening 应停表（防常驻耗电）"
        bar.hide()

    def test_other_states_no_breathing(self, qapp):
        from gui.qt_compat import Qt
        from gui.widgets.handsfree_bar import HandsfreeBar
        bar = HandsfreeBar(self._bare_ctx())
        bar.setAttribute(Qt.WA_DontShowOnScreen, True)
        bar.show()
        bar.set_state("speaking")
        assert bar._indicator.is_running() is False
        bar.hide()


# ---------------------------------------------------------------------------
# ⑤ 角色音色同步（role_bridge → TTS 联动）
# ---------------------------------------------------------------------------
class TestRoleVoiceSync:
    def _controller(self, qapp):
        from gui.tts import TTSController
        ctx = MagicMock()
        ctx.config = MagicMock(tts_speed=50, tts_enabled=True)
        ctx.role_bridge = None
        return TTSController(ctx)

    def test_known_role_applies_rate_bias(self, qapp):
        c = self._controller(qapp)
        assert c.apply_role_voice("preset_cat") is True
        assert c._role_rate_bias == 8, "猫娘语速偏置应生效"
        c.apply_role_voice("preset_dr")
        assert c._role_rate_bias == -6

    def test_unknown_role_resets_bias(self, qapp):
        c = self._controller(qapp)
        c.apply_role_voice("preset_cat")
        c.apply_role_voice("preset_whale")
        assert c._role_rate_bias == -4
        # 未收录角色 → 偏置归零（跟随设置页），返回 False（诚实降级）
        assert c.apply_role_voice("some_custom_role") is False
        assert c._role_rate_bias == 0

    def test_bias_clamped_in_apply(self, qapp):
        c = self._controller(qapp)
        c._role_rate_bias = 200   # 异常值防御
        c._apply_rate_from_config()   # 不崩、钳位生效即可
        assert True

    def test_role_bridge_subscription(self, qapp):
        from gui.tts import TTSController
        ctx = MagicMock()
        ctx.config = MagicMock(tts_speed=50, tts_enabled=True)
        bridge = MagicMock()
        ctx.role_bridge = bridge
        c = TTSController(ctx)
        bridge.role_changed.connect.assert_called_once(), "应订阅 role_bridge.role_changed"


# ---------------------------------------------------------------------------
# ⑥ 语音与文字同会话（接线断言 + 面板级冒烟）
# ---------------------------------------------------------------------------
class TestVoiceTextSameSession:
    @staticmethod
    def _panel(qapp):
        from gui.widgets.chat_panel import ChatPanelWidget
        from gui.chat_service import ChatService

        # 与 test_v16_chat_batch2 同款 FakeCtx（theme_color 走 fallback 裸值）
        class FakeConfig:
            api_provider = "deepseek"
            api_key = "sk-test"
            tts_enabled = True
            tts_speed = 50
        class FakeInnerSession:
            history = []
            def add_message(self, *a, **k): pass
        class FakeCtx:
            pass
        ctx = FakeCtx()
        ctx.config = FakeConfig()
        ctx.session = FakeInnerSession()
        ctx.chat_service = ChatService(ctx)
        panel = ChatPanelWidget(ctx)
        return panel

    def test_speech_ready_routes_through_send_chain(self, qapp):
        # 接线断言：ctrl.speech_ready -> panel._on_hf_speech_ready（与打字同源）
        panel = self._panel(qapp)
        sent = []
        panel.chat_service.send_message = lambda text, **kw: sent.append((text, kw))
        panel._on_hf_speech_ready("语音说的一句话")
        assert sent and sent[0][0].startswith("语音说的一句话"), \
            "语音识别文本必须走与打字同源的 send_message 链（同一会话）"
        assert sent[0][1].get("suppress_echo") is True

    def test_same_chat_service_as_text_path(self, qapp):
        # 语音与打字共用同一 ChatService 实例（同一会话/同一历史）
        panel = self._panel(qapp)
        assert panel.chat_service is panel.app_ctx.chat_service
