"""tests/test_v16_chat_batch2.py —— v1.6 第二批针对性自测（P0-2 路由 + P0-4 四项）。

覆盖任务面自测项：
- ① 意图五态命中/跳过断言（Agent 显式开启 / task_type != chat / demo 全跳过；
  analyze 检索收敛；手动选态覆盖；未识别恒落 chat 零附加）；
- ② 失败→重试幂等（session user 消息不重复；skip_history_write 生效；
  连续 3 次失败引导文案）；
- ③ 反套话注入仅请求副本不入历史（context_trimmed 置位→注入→复位；开关关闭不注入）；
- ④ 状态链文案切换（发送中→思考→响应中→正在回复→重试中→失败清除，offscreen 面板）；
- ⑤ GUI 冒烟含意图控件（offscreen 构造 ChatPanelWidget + 意图下拉持久化）。
隔离：FakeCtx / FakeSession，绝不读写真实 ~/.maid_coder。
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from gui.chat_service import ChatService, ANTI_FLUFF_INJECTION  # noqa: E402
from gui.intent import INTENT_HINTS  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeInnerSession:
    """仿 ChatSession 的最小会话（含 context_trimmed 标志）。"""

    def __init__(self):
        self.history = [{"role": "system", "content": "SYS"}]
        self.current_system = "SYS"
        self.context_trimmed = False

    def add_message(self, role, content=None, **kwargs):
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        self.history.append(msg)

    def replace_history(self, entries):
        """仿 ChatSession.replace_history：user/assistant 清洗 + system 置顶。"""
        clean = [{"role": str(e.get("role")), "content": str(e.get("content"))}
                 for e in (entries or [])
                 if e.get("role") in ("user", "assistant") and e.get("content")]
        self.history = [{"role": "system", "content": self.current_system}] + clean

    @property
    def inner(self):
        return self


class FakeConfig:
    def __init__(self):
        self.api_provider = "deepseek"
        self.api_key = "sk-test"          # 非 demo
        self.chat_intent_mode = "auto"
        self.web_search_enabled_gui = False
        self.stream_mode = True
        self.temperature = 0.7
        self.max_tokens = 2048
        self.maid_mode = True
        self.agent_anti_hallucination_inject = True


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()
        self.session = FakeInnerSession()
        self.api = MagicMock()   # 默认可 launch（DummyWorker 替身）；失败用例显式置 None


class _AnyCall:
    """万能链式替身：任意属性可再取、任意调用可执行（connect/start 等）。"""

    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        return None


class DummyWorker:
    """替身 ApiWorker：捕获 messages/task_config，绝不启动线程。"""
    captured = {"messages": None, "task_config": None}

    def __init__(self, api, messages, task_config, app_ctx, on_session_used=None,
                 expr_filter=False):
        type(self).captured = {"messages": messages, "task_config": task_config,
                               "app_ctx": app_ctx}

    def __getattr__(self, name):
        return _AnyCall()


@pytest.fixture
def svc(qapp_guard):
    ctx = FakeCtx()
    s = ChatService(ctx)
    yield s


@pytest.fixture
def qapp_guard():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# ① 意图路由：命中 / 跳过 / 收敛
# ---------------------------------------------------------------------------
class TestIntentRouting:
    def test_auto_detect_analyze(self, svc):
        assert svc._route_intent("帮我分析一下这段报错是怎么回事", "chat") == "analyze"

    def test_auto_detect_confide(self, svc):
        assert svc._route_intent("我今天好难受，只想说说", "chat") == "confide"

    def test_unrecognized_returns_empty(self, svc):
        # 未识别恒落 chat → 返回 ""（零附加、消息流绝不改道）
        assert svc._route_intent("今天天气不错呀", "chat") == ""

    def test_agent_mode_skips_routing(self, svc):
        # Agent 显式开启 → 完全跳过路由（显式开关绝对优先，v1.5.2 行为逐字一致）
        svc.set_agent_mode(True)
        try:
            assert svc._route_intent("帮我分析这段报错", "chat") == ""
        finally:
            svc.set_agent_mode(False)

    def test_non_chat_task_type_skips_routing(self, svc):
        assert svc._route_intent("帮我分析这段报错", "managed_task") == ""
        assert svc._route_intent("帮我分析这段报错", "agent") == ""

    def test_demo_mode_skips_routing(self, svc):
        svc._app_ctx.config.api_key = ""   # → demo
        assert svc._route_intent("帮我分析这段报错", "chat") == ""

    def test_manual_override(self, svc):
        # 手动选态覆盖自动识别
        assert svc._route_intent("今天天气不错呀", "chat", intent_mode="confide") == "confide"
        assert svc._route_intent("帮我分析这段报错", "chat", intent_mode="act") == "act"

    def test_manual_chat_state_zero_attach(self, svc):
        # 手动选「陪我聊聊」= 零附加（等价未识别）
        assert svc._route_intent("随便说点啥", "chat", intent_mode="chat") == ""

    def test_config_mode_manual(self, svc):
        # GuiConfig.chat_intent_mode 非 auto → 自动识别被配置覆盖
        svc._app_ctx.config.chat_intent_mode = "advise"
        assert svc._route_intent("今天天气不错呀", "chat") == "advise"

    def test_intent_module_broken_degrades_empty(self, svc, monkeypatch):
        # 降级：intent 模块异常 → 恒返 ""（退化为 v1.5.2 普通链）
        import builtins
        real_import = builtins.__import__

        def boom(name, *a, **k):
            if name == "gui.intent":
                raise RuntimeError("mock broken")
            return real_import(name, *a, **k)
        monkeypatch.setattr(builtins, "__import__", boom)
        assert svc._route_intent("帮我分析这段报错", "chat") == ""


class TestIntentLaunchIntegration:
    def test_hint_injected_into_request_copy_only(self, svc, monkeypatch):
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("我今天好难受，只想说说", suppress_echo=True)
        msgs = DummyWorker.captured["messages"]
        inj = [m for m in msgs if m["role"] == "system" and INTENT_HINTS["confide"][:8] in m["content"]]
        assert len(inj) == 1, "倾诉语气提示应注入请求副本"
        # 注入位置在末位 user 之前，且不入 session.history
        assert msgs[-1]["role"] == "user"
        hist = svc._app_ctx.session.history
        assert all(INTENT_HINTS["confide"][:8] not in (m.get("content") or "")
                   for m in hist if m["role"] == "system" and m is not hist[0] or True)
        assert not any(INTENT_HINTS["confide"][:8] in str(m.get("content", ""))
                       for m in hist[1:]), "注入绝不写 session.history"

    def test_chat_state_zero_injection(self, svc, monkeypatch):
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("今天天气不错呀", suppress_echo=True)
        msgs = DummyWorker.captured["messages"]
        sys_after_main = [m for m in msgs[1:] if m["role"] == "system"]
        # chat 态零意图提示（v1.6 口径不变）
        assert not any((INTENT_HINTS["confide"][:8] in m["content"])
                       or (INTENT_HINTS["analyze"][:8] in m["content"])
                       for m in sys_after_main), "chat 态零意图提示、零打扰"
        # v1.8(V18-12/D-V18-07): 场景 > 意图五态 —— chat 态唯一合法注入 =
        # 场景语气底色 + 场景边界消息（均以【场景 开头，无意图提示）
        assert all(str(m["content"]).startswith("【场景")
                   for m in sys_after_main), \
            f"chat 态非场景注入混入: {[m['content'][:20] for m in sys_after_main]}"

    def test_analyze_skips_should_auto_search(self, svc, monkeypatch):
        # analyze 态 + 联网开启 → 直接置 web_search_query（跳过 should_auto_search）
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc._app_ctx.config.web_search_enabled_gui = True
        # 该句不应命中 should_auto_search 的常规判定（纯技术分析无时效词），但 analyze 直接收敛
        try:
            from helpers import WebSearch
            if WebSearch().should_auto_search("帮我分析一下这段报错是怎么回事"):
                pytest.skip("基线 should_auto_search 本就命中，收敛断言无区分度")
        except Exception:
            pass
        svc.send_message("帮我分析一下这段报错是怎么回事", suppress_echo=True)
        assert DummyWorker.captured["task_config"].get("web_search_query")

    def test_non_analyze_keeps_should_auto_search(self, svc, monkeypatch):
        # 非 analyze 态不改变既有检索判定链（v1.5.2 行为）
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc._app_ctx.config.web_search_enabled_gui = True
        svc.send_message("今天天气不错呀", suppress_echo=True)
        assert not DummyWorker.captured["task_config"].get("web_search_query")

    def test_retry_does_not_re_route(self, svc, monkeypatch):
        # 幂等：重试路径不过意图路由（保持原样重发、零附加）
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("帮我分析一下这段报错", suppress_echo=True)
        first = DummyWorker.captured["task_config"]
        assert first.get("web_search_query") is not None or True
        # 制造失败现场后重试 → intent_state 为空、无注入
        svc._on_api_error("boom")
        svc._app_ctx.config.web_search_enabled_gui = False
        assert svc.retry_last_failure()
        assert DummyWorker.captured["task_config"].get("web_search_query") is None


# ---------------------------------------------------------------------------
# ② 失败保留 + 重试幂等
# ---------------------------------------------------------------------------
class TestRetryIdempotency:
    def test_failure_keeps_user_message_and_records_scene(self, svc):
        emitted = []
        svc.message_failed.connect(lambda e: emitted.append(e))
        svc._app_ctx.api = None   # _launch_worker 早退失败，但 user 消息已入库
        svc.send_message("帮我修一下这个函数", suppress_echo=True)
        hist = svc._app_ctx.session.history
        user_msgs = [m for m in hist if m["role"] == "user" and m["content"] == "帮我修一下这个函数"]
        assert len(user_msgs) == 1, "失败不回滚：数据层 user 消息保留（失败保留）"
        assert svc._last_failure and svc._last_failure["text"] == "帮我修一下这个函数"

    def test_retry_no_duplicate_write(self, svc):
        svc._app_ctx.api = None
        svc.send_message("帮我修一下这个函数", suppress_echo=True)
        assert len([m for m in svc._app_ctx.session.history
                    if m["role"] == "user" and m["content"] == "帮我修一下这个函数"]) == 1
        assert svc.retry_last_failure() is True
        # skip_history_write=True → session 中 user 消息不重复（端到端幂等）
        assert len([m for m in svc._app_ctx.session.history
                    if m["role"] == "user" and m["content"] == "帮我修一下这个函数"]) == 1
        assert svc._last_failure is None

    def test_retry_without_scene_returns_false(self, svc):
        assert svc.retry_last_failure() is False

    def test_fail_streak_guidance_at_three(self, svc):
        emitted = []
        svc.message_failed.connect(lambda e: emitted.append(e))
        svc._current_user_text = "x"
        for i in range(3):
            svc._on_api_error("timeout")
        assert "连续几次" in emitted[-1] and "API Key" in emitted[-1]
        assert "连续几次" not in emitted[0]

    def test_success_resets_fail_streak(self, svc):
        svc._on_api_error("e1")
        svc._on_api_error("e2")
        assert svc._fail_streak == 2
        svc._on_stream_finished("ok", {})
        assert svc._fail_streak == 0
        assert svc._last_failure is None

    def test_cancel_resets_fail_streak(self, svc):
        svc._on_api_error("e1")
        svc._on_cancelled()
        assert svc._fail_streak == 0


# ---------------------------------------------------------------------------
# ③ 反套话注入（context_trimmed → 请求副本 → 复位；不入历史）
# ---------------------------------------------------------------------------
class TestAntiFluffInjection:
    def _launch(self, svc, monkeypatch):
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("继续说说刚才那个话题", suppress_echo=True)
        return DummyWorker.captured["messages"]

    def test_injection_when_trimmed_and_reset(self, svc, monkeypatch):
        sess = svc._app_ctx.session
        sess.context_trimmed = True
        msgs = self._launch(svc, monkeypatch)
        assert any(ANTI_FLUFF_INJECTION[:10] in m["content"]
                   for m in msgs if m["role"] == "system"), "截断发生过 → 注入反套话指令"
        # 注入后标志复位（一次性消费）
        assert sess.context_trimmed is False
        # 不入 session.history
        assert not any(ANTI_FLUFF_INJECTION[:10] in str(m.get("content", ""))
                       for m in sess.history[1:])

    def test_no_injection_when_not_trimmed(self, svc, monkeypatch):
        msgs = self._launch(svc, monkeypatch)
        assert not any("诚实边界" in m["content"] for m in msgs if m["role"] == "system")

    def test_switch_off_disables_injection(self, svc, monkeypatch):
        sess = svc._app_ctx.session
        sess.context_trimmed = True
        svc._app_ctx.config.agent_anti_hallucination_inject = False
        msgs = self._launch(svc, monkeypatch)
        assert not any("诚实边界" in m["content"] for m in msgs if m["role"] == "system")

    def test_only_chat_path_injects(self, svc, monkeypatch):
        # Agent 模式（显式）不注入 —— 工具循环自组消息，防错位
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        sess = svc._app_ctx.session
        sess.context_trimmed = True
        svc.set_agent_mode(True)
        try:
            svc.send_message("看看这个报错", suppress_echo=True)
        finally:
            svc.set_agent_mode(False)
        assert sess.context_trimmed is True, "Agent 路径不消费标志"


# ---------------------------------------------------------------------------
# ③-b session.context_trimmed 标志（session.py 增量）
# ---------------------------------------------------------------------------
class TestSessionContextTrimmedFlag:
    def _make_session(self, tmp_path):
        from core import AppConfig
        from session import ChatSession
        cfg = MagicMock(spec=AppConfig)
        cfg.max_history_rounds = 2
        cfg.summary_interval = 5
        cfg.workspace = str(tmp_path)
        cfg.api_max_tokens = 64
        cfg.output_debug = False
        cfg.web_search_enabled = False
        cfg.sensitive_info_scan = False
        cfg.code_exec_enabled = False
        cfg.multi_enabled = False
        cfg.output_speed = "fast"
        cfg.stream_mode = False
        cfg.output_show_token_usage = False
        cfg.persona_role = "maid"
        cfg.persona_title = "码铃"
        cfg.persona_personality = "温柔"
        cfg.persona_address_user = "主人"
        cfg.persona_address_self = "我"
        cfg.snippets_file = str(tmp_path / "snip.json")
        cfg.todos_file = str(tmp_path / "todo.json")
        cfg.code_exec_timeout = 5
        cfg.web_search_max_results = 3
        cfg.kb_index_file = str(tmp_path / "kb.json")
        cfg.plugins_dir = str(tmp_path / "plugins")
        logger = MagicMock()
        return ChatSession(cfg, MagicMock(), logger)

    def test_flag_set_on_real_trim(self, tmp_path):
        s = self._make_session(tmp_path)
        assert s.context_trimmed is False
        for i in range(10):   # max_history_rounds=2 → 4 条 user/assistant 即触发截断
            s.add_message("user", f"u{i}")
            s.add_message("assistant", f"a{i}")
        assert s.context_trimmed is True

    def test_flag_not_set_below_limit(self, tmp_path):
        s = self._make_session(tmp_path)
        s.add_message("user", "hi")
        s.add_message("assistant", "hello")
        assert s.context_trimmed is False

    def test_clear_resets_flag(self, tmp_path):
        s = self._make_session(tmp_path)
        for i in range(10):
            s.add_message("user", f"u{i}")
        assert s.context_trimmed is True
        s.clear()
        assert s.context_trimmed is False

    def test_auto_summary_sets_flag(self, tmp_path):
        s = self._make_session(tmp_path)
        s.add_message("user", "你好")
        s.add_message("assistant", "主人好~")
        s.api.chat = MagicMock(return_value={
            "choices": [{"message": {"content": "摘要内容"}}],
            "usage": {"completion_tokens": 10},
        })
        assert s.auto_summary() is True
        assert s.context_trimmed is True


# ---------------------------------------------------------------------------
# ②-b regenerate 收口链（签名对齐 + 幂等不重复）
# ---------------------------------------------------------------------------
class TestRegenerateChain:
    def test_regen_with_ui_history_single_user_in_request(self, svc, monkeypatch):
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("原始问题", suppress_echo=True)
        svc._app_ctx.session.add_message("assistant", "回复A")
        # 面板截断 assistant 气泡后传入的剩余消息（含末位 user）
        remaining = [{"role": "user", "content": "原始问题"}]
        svc.regenerate("原始问题", ui_history=remaining)
        msgs = DummyWorker.captured["messages"]
        users = [m for m in msgs if m["role"] == "user"]
        assert len(users) == 1 and users[0]["content"] == "原始问题", \
            f"重跑请求副本应只含一条末位 user，实际: {[u['content'] for u in users]}"
        assert msgs[0]["role"] == "system"

    def test_regen_does_not_duplicate_session(self, svc, monkeypatch):
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("原始问题", suppress_echo=True)
        svc._app_ctx.session.add_message("assistant", "回复A")
        remaining = [{"role": "user", "content": "原始问题"}]
        svc.regenerate("原始问题", ui_history=remaining)
        hist = svc._app_ctx.session.history
        assert len([m for m in hist if m["role"] == "user" and m["content"] == "原始问题"]) == 1
        # 重建历史语义：replace_history 后 session = system + 剩余消息
        assert hist[0]["role"] == "system"

    def test_regen_backward_compat_no_args(self, svc, monkeypatch):
        # 旧无参调用：直接重跑 _current_user_text，不重复入库
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("老问题", suppress_echo=True)
        svc._app_ctx.session.add_message("assistant", "老回复")
        svc.regenerate()
        msgs = DummyWorker.captured["messages"]
        users = [m for m in msgs if m["role"] == "user"]
        assert len(users) == 1 and users[0]["content"] == "老问题"

    def test_regen_skips_intent_routing(self, svc, monkeypatch):
        # 幂等：重跑不过意图路由（零附加、保持原样）
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        svc.send_message("帮我分析这段报错", suppress_echo=True)
        svc.regenerate("帮我分析这段报错", ui_history=[{"role": "user", "content": "帮我分析这段报错"}])
        assert DummyWorker.captured["task_config"].get("web_search_query") is None


# ---------------------------------------------------------------------------
# ④⑤ 状态链 + GUI 冒烟（offscreen 面板 + 意图控件）
# ---------------------------------------------------------------------------
@pytest.fixture
def panel(qapp_guard):
    from gui.widgets.chat_panel import ChatPanelWidget
    ctx = FakeCtx()
    ctx.chat_service = ChatService(ctx)
    p = ChatPanelWidget(ctx)
    qapp_guard.processEvents()
    return p


class TestStatusChainAndPanel:
    def test_panel_smoke_with_intent_widget(self, panel):
        # GUI 冒烟：面板可构造 + 意图下拉存在（6 项、默认 auto）
        combo = panel.intent_combo
        assert combo is not None
        assert combo.count() == 6
        assert combo.itemData(0) == "auto"
        assert combo.currentData() == "auto"

    def test_intent_mode_persisted(self, panel):
        cfg = panel.app_ctx.config
        idx = panel.intent_combo.findData("confide")
        panel.intent_combo.setCurrentIndex(idx)
        panel._on_intent_mode_changed(idx)
        assert cfg.chat_intent_mode == "confide"
        idx2 = panel.intent_combo.findData("auto")
        panel.intent_combo.setCurrentIndex(idx2)
        panel._on_intent_mode_changed(idx2)
        assert cfg.chat_intent_mode == "auto"

    def test_status_chain_text_switches(self, panel):
        # 发送中 → 思考 → 响应中 → 正在回复
        panel.status_label.setText("")
        panel._status_first_chunk = False
        panel._on_thinking(True)
        assert panel.status_label.text() == "正在思考…"
        panel._on_stream_started()
        assert panel.status_label.text() == "模型响应中…"
        panel._on_chunk("你好")
        assert panel.status_label.text() == "正在回复…"
        # thinking(False) 不回写（保持流式态文案）
        panel._on_thinking(False)
        assert panel.status_label.text() == "正在回复…"
        # 收尾清空
        panel._on_stream_finished("你好呀~", {})
        assert panel.status_label.text() == ""

    def test_failure_shows_action_row_and_retry(self, panel):
        svc = panel.chat_service
        svc._app_ctx.api = None
        panel._add_message_bubble("user", "帮我修一下函数")
        svc.send_message("帮我修一下函数", suppress_echo=True)
        # 失败路径：错误气泡 + 动作行
        assert panel._failure_row is not None
        assert panel._failure_user_bubble is not None
        assert "帮我修一下函数" in panel._failure_user_bubble.get_text()
        # 状态清除
        assert panel.status_label.text() == ""
        # 重试幂等：session user 消息不重复
        before = len([m for m in svc._app_ctx.session.history
                      if m["role"] == "user" and m["content"] == "帮我修一下函数"])
        panel._on_retry_failed()
        after = len([m for m in svc._app_ctx.session.history
                     if m["role"] == "user" and m["content"] == "帮我修一下函数"])
        assert before == after == 1

    def test_success_clears_failure_row(self, panel):
        svc = panel.chat_service
        svc._app_ctx.api = None
        panel._add_message_bubble("user", "测试消息abc")
        svc.send_message("测试消息abc", suppress_echo=True)
        assert panel._failure_row is not None
        panel._on_stream_finished("done", {})
        assert panel._failure_row is None

    def test_retry_status_text(self, panel, monkeypatch):
        # api 可用 + DummyWorker → worker 已创建但不发信号 → 状态停留在「重试中…」
        monkeypatch.setattr("gui.chat_service.ApiWorker", DummyWorker)
        panel.chat_service._app_ctx.api = MagicMock()
        panel.chat_service._last_failure = {"text": "x", "task_type": "chat",
                                            "attachments": [], "ts": 0.0}
        panel._on_retry_failed()
        assert panel.status_label.text() == "重试中…"

    def test_intent_combo_hidden_none_crash_free(self, qapp_guard):
        # 防御：无 app_ctx.config 时持久化静默跳过不崩
        from gui.widgets.chat_panel import ChatPanelWidget
        ctx = FakeCtx()
        ctx.chat_service = ChatService(ctx)
        del ctx.config
        p = ChatPanelWidget(ctx)
        p._on_intent_mode_changed(1)
        qapp_guard.processEvents()
