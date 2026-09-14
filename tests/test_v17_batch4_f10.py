# -*- coding: utf-8 -*-
"""v1.7 第四批测试（F10 多角色群聊 MVP，D-V17-06）。

覆盖（team-lead 指定七类针对性）：
- ① @指定触发与角色人设正确（请求 system = 被@角色人设 + 群聊语境段，
    他人消息改写 user +【名字】：前缀，system 唯一，请求副本用后即弃）；
- ② 未@不触发（silent 策略全员沉默；rotate 默认轮转第一位；「@一下」不误命中）；
- ③ 插话调用链退役（v1.8 收尾：chatter 四道闸纯函数/配置键/字段已删除）；
- ④ speaker_id 持久化与渲染（显示会话落盘 / 重启恢复 / 气泡名字标签）；
- ⑤ 三隔离守卫（对齐历史 / 亲密度 / 记忆提取零调用断言）；
- ⑥ 切角色/切会话场景零回归（群聊只清空 LLM 历史，单聊对齐链不变）；
- ⑦ 单聊会话完全不受影响（回归：组装/入库/计分链原样）。

隔离：SessionManager/RoleManager 全部指向 tmp_path，Qt 走 offscreen，
零真实 ~/.maid_coder；F10 严禁触碰 page_role.py（只读 import）。
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from gui.chat_service import (  # noqa: E402
    ChatService,
    GROUP_DEFAULT_NO_AT_POLICY,
    GROUP_HISTORY_LIMIT,
    build_group_system_prompt,
    parse_group_mention,
    rewrite_group_history,
)
from gui.models import ChatSession  # noqa: E402
from gui.session_manager import SessionManager, is_group_session  # noqa: E402


def _qt_app():
    from gui.qt_compat import QApplication
    return QApplication.instance() or QApplication([])


def _fake_role(rid, name, prompt="", avatar=None):
    return SimpleNamespace(id=rid, name=name, system_prompt=prompt,
                           personality={"lively": 50, "rigorous": 50, "caring": 50},
                           avatar=avatar, is_default=False)


def _group_display_session(members=("r_a", "r_b", "r_c"), policy="rotate"):
    s = ChatSession(name="群聊")
    s.metadata = {
        "type": "group",
        "members": list(members),
        "turn_order": list(members),
        "no_at_policy": policy,
    }
    return s


def _mock_app_ctx(llm_session=None):
    cfg = MagicMock()
    cfg.api_key = "sk-test"
    cfg.api_provider = "deepseek"
    cfg.stream_mode = True
    cfg.temperature = 0.7
    cfg.max_tokens = 2048
    cfg.maid_mode = True
    llm = llm_session if llm_session is not None else MagicMock()
    ctx = SimpleNamespace(cfg=cfg, config=cfg, api=MagicMock(),
                          session=llm, collaborator=None, intimacy=None)
    return ctx


def _make_service(llm_session=None):
    _qt_app()
    return ChatService(_mock_app_ctx(llm_session))


# ---------------------------------------------------------------------------
# ① @指定触发与角色人设正确
# ---------------------------------------------------------------------------
class TestMentionAndAssembly:
    def test_parse_mention_exact(self):
        name_map = {"小铃": "r_a", "鲸鱼": "r_b"}
        assert parse_group_mention("你好 @小铃 来答一下", name_map) == "r_a"
        assert parse_group_mention("@鲸鱼 看看这个", name_map) == "r_b"
        assert parse_group_mention("开头 @小铃", name_map) == "r_a"

    def test_parse_mention_no_false_positive(self):
        name_map = {"小铃": "r_a"}
        # 「@一下」等非成员词不命中（精确匹配防误触发，R-J①）
        assert parse_group_mention("@一下 试试", name_map) is None
        assert parse_group_mention("没有@任何成员", name_map) is None
        assert parse_group_mention("", name_map) is None

    def test_rewrite_history_prefix_and_own_role(self):
        speaker = _fake_role("r_a", "小铃")
        # 用轻量 dict 消息构造（与 ChatMessage 字段兼容）
        msgs = [
            SimpleNamespace(role="user", content="大家好", metadata={}),
            SimpleNamespace(role="assistant", content="我是小铃", metadata={"speaker_id": "r_a"}),
            SimpleNamespace(role="assistant", content="我是鲸鱼", metadata={"speaker_id": "r_b"}),
        ]
        out = rewrite_group_history(msgs, speaker, {"r_a": "小铃", "r_b": "鲸鱼"})
        assert out[0] == {"role": "user", "content": "大家好"}
        # 自己的历史保持 assistant role（标准 multi-party 建模）
        assert out[1] == {"role": "assistant", "content": "我是小铃"}
        # 他人发言改写为 user + 【名字】：前缀（消角色错位）
        assert out[2] == {"role": "user", "content": "【鲸鱼】：我是鲸鱼"}

    def test_system_unique_with_group_segment(self):
        speaker = _fake_role("r_a", "小铃", prompt="你是贴身女仆小铃。")
        sys_prompt = build_group_system_prompt(speaker, ["鲸鱼", "三三"])
        assert "你是贴身女仆小铃" in sys_prompt          # 该角色人设
        assert "群聊模式" in sys_prompt
        assert "鲸鱼" in sys_prompt and "三三" in sys_prompt
        assert "不代替" in sys_prompt                     # R-J④ 不代替他人
        # 请求副本中 system 唯一（prepare 后仅 1 条 system）
        session = _group_display_session()
        session.messages = []
        roles = {"r_a": speaker, "r_b": _fake_role("r_b", "鲸鱼"),
                 "r_c": _fake_role("r_c", "三三")}
        svc = _make_service()
        msgs = svc.prepare_group_request(session, speaker, roles, user_text="你好")
        assert msgs[0]["role"] == "system"
        assert sum(1 for m in msgs if m["role"] == "system") == 1
        assert msgs[-1] == {"role": "user", "content": "你好"}

    def test_prepare_truncates_to_60(self):
        session = _group_display_session(members=("r_a", "r_b"))
        speaker = _fake_role("r_a", "小铃")
        roles = {"r_a": speaker, "r_b": _fake_role("r_b", "鲸鱼")}
        for i in range(80):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}", metadata={"speaker_id": "r_b"})
        svc = _make_service()
        msgs = svc.prepare_group_request(session, speaker, roles, user_text="最新消息")
        body = [m for m in msgs if m["role"] != "system"]
        assert len(body) <= GROUP_HISTORY_LIMIT
        assert msgs[-1]["content"] == "最新消息"

    def test_group_send_request_and_turn_rotation(self):
        """@指定：请求 system=被@角色，轮转记账生效，请求副本不污染任何会话。"""
        session = _group_display_session()
        session.add_message("user", "大家好")
        session.add_message("assistant", "我是鲸鱼", metadata={"speaker_id": "r_b"})
        speaker = _fake_role("r_a", "小铃", prompt="小铃人设A")
        roles = {"r_a": speaker, "r_b": _fake_role("r_b", "鲸鱼", prompt="鲸鱼人设B"),
                 "r_c": _fake_role("r_c", "三三")}
        svc = _make_service()
        captured = {}

        def _fake_launch(messages, spk, disp, task_config):
            captured.update({"messages": messages, "speaker": spk,
                             "session": disp, "task_config": task_config})
            return True

        svc._launch_group_worker = _fake_launch
        assert svc.group_send("在吗 @小铃", session, speaker, roles) is True
        msgs = captured["messages"]
        assert msgs[0]["role"] == "system" and "小铃人设A" in msgs[0]["content"]
        assert sum(1 for m in msgs if m["role"] == "system") == 1
        # 他人发言带名字前缀；本轮 user 在末位
        assert any(m["content"].startswith("【鲸鱼】：") for m in msgs)
        assert msgs[-1] == {"role": "user", "content": "在吗 @小铃"}
        assert captured["task_config"]["group"] is True
        # 轮转：小铃发言后移队尾
        assert session.metadata["turn_order"] == ["r_b", "r_c", "r_a"]
        # 请求副本用后即弃：显示会话本身未被写入发言内容
        assert all(m.metadata.get("speaker_id") != "r_a" for m in session.messages)


# ---------------------------------------------------------------------------
# ②/F10 自由发言：未@ 路由（@覆盖 / silent 沉默 / 默认调度）
# ---------------------------------------------------------------------------
class TestNoMentionPolicy:
    def _svc_with_stub_sched(self):
        svc = _make_service()
        sched_calls = []
        svc._launch_group_scheduler = lambda session, roles, text: sched_calls.append(text)
        return svc, sched_calls

    def test_mention_overrides_scheduler(self):
        """@点名 = 显式覆盖（最高优先级）：不走调度，直接发言。"""
        session = _group_display_session()
        svc, sched_calls = self._svc_with_stub_sched()
        speak_calls = []
        svc.group_send = lambda *a, **k: speak_calls.append(a) or True
        mode = svc.send_group_turn("你好 @小铃", session,
                                   {"r_a": _fake_role("r_a", "小铃"),
                                    "r_b": _fake_role("r_b", "鲸鱼")})
        assert mode == "at"
        assert sched_calls == []           # 调度请求零额外 token
        assert len(speak_calls) == 1       # 被@角色立即发言
        assert getattr(speak_calls[0][2], "id") == "r_a"

    def test_silent_policy_no_reply_no_scheduler(self):
        session = _group_display_session(policy="silent")
        svc, sched_calls = self._svc_with_stub_sched()
        speak_calls = []
        svc.group_send = lambda *a, **k: speak_calls.append(a) or True
        mode = svc.send_group_turn("随便聊聊", session,
                                   {"r_a": _fake_role("r_a", "小铃")})
        assert mode == "silent"            # 全员沉默等待 @（消息照常入会话，零回复）
        assert sched_calls == [] and speak_calls == []

    def test_no_mention_goes_to_scheduler(self):
        """未@默认：轻量 LLM 调度决定接话者（自由发言）。"""
        session = _group_display_session()
        svc, sched_calls = self._svc_with_stub_sched()
        mode = svc.send_group_turn("今天天气真好", session,
                                   {"r_a": _fake_role("r_a", "小铃"),
                                    "r_b": _fake_role("r_b", "鲸鱼")})
        assert mode == "scheduled"
        assert sched_calls == ["今天天气真好"]

    def test_at_yixia_still_schedules(self):
        """「@一下」非成员名 → 不算点名 → 走自由调度（rotate 默认）。"""
        session = _group_display_session(policy="rotate")
        svc, sched_calls = self._svc_with_stub_sched()
        mode = svc.send_group_turn("@一下", session,
                                   {"r_a": _fake_role("r_a", "小铃")})
        assert mode == "scheduled" and sched_calls == ["@一下"]

    def test_default_policy_is_rotate(self):
        assert GROUP_DEFAULT_NO_AT_POLICY == "rotate"


# ---------------------------------------------------------------------------
# ③ 插话调用链退役（v1.8 收尾：chatter 四道闸纯函数已随配置键/字段一并删除）
# ---------------------------------------------------------------------------
class TestInterjectRetired:
    def test_interject_chain_retired(self):
        """F10 自由发言定案：插话调用链退役 —— maybe_group_interject 恒拒且零发言。"""
        session = _group_display_session()
        session.metadata["chatter"] = {"enabled": True, "last_at": 0,
                                       "date": "", "count_today": 0}
        svc = _make_service()
        calls = []
        svc.group_send = lambda *a, **k: calls.append(a) or True
        assert svc.maybe_group_interject(session, "r_a", allow=True) is False
        assert calls == []               # 不再触发任何发言（接话由调度器决定）
        # 调度硬约束常量：每条用户消息最多 2 个角色发言
        from gui.chat_service import GROUP_SCHED_MAX_SPEAKERS
        assert GROUP_SCHED_MAX_SPEAKERS == 2


# ---------------------------------------------------------------------------
# ④ speaker_id 持久化与渲染
# ---------------------------------------------------------------------------
class TestSpeakerPersistenceAndRender:
    def test_group_reply_persisted_with_speaker_id(self, tmp_path):
        session = _group_display_session(members=("r_a", "r_b"))
        svc = _make_service()
        svc._group_active = True
        svc._group_speaker_id = "r_b"
        svc._group_display_session = session
        svc._drain = lambda: None
        svc._on_group_stream_finished("这是鲸鱼的回答", {"total_tokens": 42})
        msg = session.messages[-1]
        assert msg.role == "assistant" and msg.content == "这是鲸鱼的回答"
        assert msg.metadata["speaker_id"] == "r_b"

    def test_roundtrip_through_session_file(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        session = sm.create_group_session("群聊", ["r_a", "r_b"])
        session.add_message("assistant", "你好呀", metadata={"speaker_id": "r_a"})
        sm.save_session(session)
        sm2 = SessionManager(sessions_dir=tmp_path / "sessions")
        loaded = sm2.get_session(session.id)
        assert is_group_session(loaded)
        assert loaded.metadata["members"] == ["r_a", "r_b"]
        assert loaded.messages[-1].metadata["speaker_id"] == "r_a"

    def test_save_current_session_preserves_speaker(self, tmp_path):
        """面板增量落盘不得抹掉 speaker_id（气泡 attr 与存量 metadata 双来源）。"""
        from gui.qt_compat import QWidget, QVBoxLayout
        from gui.widgets.chat_panel import ChatPanelWidget
        from gui.widgets.message_bubble import MessageBubble
        _qt_app()
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        session = sm.create_group_session("群聊", ["r_a", "r_b"])
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addStretch()
        b1 = MessageBubble("user", "在吗")
        b2 = MessageBubble("assistant", "在的~")
        b2.speaker_id = "r_a"
        for b in (b1, b2):
            layout.addWidget(b)

        dummy = SimpleNamespace(
            session_manager=sm, _current_session_id=session.id,
            messages_layout=layout, _refresh_session_list=lambda: None,
        )
        ChatPanelWidget._save_current_session(dummy)
        assert session.messages[0].role == "user"
        assert session.messages[1].metadata["speaker_id"] == "r_a"

    def test_bubble_name_label_mechanism(self):
        """群聊气泡名字标签机制：nameLabel 可定位且可写（渲染链由面板调用）。"""
        from gui.qt_compat import QLabel
        from gui.widgets.message_bubble import MessageBubble
        _qt_app()
        bubble = MessageBubble("assistant", "你好")
        label = bubble.findChild(QLabel, "nameLabel")
        assert label is not None
        label.setText("小铃")
        assert label.text() == "小铃"


# ---------------------------------------------------------------------------
# ⑤ 三隔离守卫（R-J④⑤ / 共享知识 26）
# ---------------------------------------------------------------------------
class TestTripleIsolation:
    def test_no_llm_history_no_intimacy_no_memory_extract(self):
        llm = MagicMock()
        llm.history = []
        intimacy = MagicMock()
        ctx = _mock_app_ctx(llm_session=llm)
        ctx.intimacy = intimacy
        svc = ChatService(ctx)
        session = _group_display_session(members=("r_a", "r_b"))
        session.add_message("user", "大家好")
        speaker = _fake_role("r_a", "小铃")
        roles = {"r_a": speaker, "r_b": _fake_role("r_b", "鲸鱼")}
        svc._launch_group_worker = lambda *a, **k: True
        assert svc.group_send("你好 @小铃", session, speaker, roles) is True
        # 隔离①：LLM 对齐历史零触碰（add_message/replace_history 均不调用）
        llm.add_message.assert_not_called()
        llm.replace_history.assert_not_called()
        # 隔离②：亲密度零计分
        intimacy.add_interaction.assert_not_called()
        # 隔离③：记忆提取零调用
        memory_mgr = getattr(llm, "memory_mgr", None)
        if memory_mgr is not None:
            memory_mgr.extract_from_dialogue.assert_not_called()
        # 回复完成路径同样零计分/零入对齐历史
        svc._group_active = True
        svc._group_speaker_id = "r_a"
        svc._group_display_session = session
        svc._drain = lambda: None
        svc._on_group_stream_finished("小铃的回复", {"total_tokens": 10})
        llm.add_message.assert_not_called()
        intimacy.add_interaction.assert_not_called()
        assert session.messages[-1].metadata["speaker_id"] == "r_a"

    def test_group_api_error_no_failure_site_for_single_chat(self):
        """群聊失败不记单聊失败现场（retry_last_failure 走单聊链会写对齐历史）。"""
        svc = _make_service()
        session = _group_display_session(members=("r_a",))
        svc._group_active = True
        svc._group_display_session = session
        svc._drain = lambda: None
        emitted = []
        svc.message_failed.connect(lambda e: emitted.append(e))
        svc._on_api_error("网络错误")
        assert svc._group_active is False
        assert svc._last_failure is None  # 单聊重试链不被群聊失败污染
        assert emitted and "网络错误" in emitted[0]


# ---------------------------------------------------------------------------
# ⑥ 切角色/切会话场景零回归
# ---------------------------------------------------------------------------
class TestSwitchScenarios:
    def _panel_dummy(self, llm_session):
        return SimpleNamespace(app_ctx=SimpleNamespace(session=llm_session))

    def test_switch_to_group_clears_llm_history_only(self):
        llm = MagicMock()
        session = _group_display_session()
        session.add_message("user", "群消息")
        session.add_message("assistant", "群回复", metadata={"speaker_id": "r_a"})
        from gui.widgets.chat_panel import ChatPanelWidget
        ChatPanelWidget._sync_llm_context(self._panel_dummy(llm), session)
        llm.replace_history.assert_called_once_with([])  # 只清空，绝不写入群聊消息

    def test_switch_to_single_rebuilds_history(self):
        llm = MagicMock()
        session = ChatSession(name="单聊")
        session.add_message("user", "单聊消息")
        session.add_message("assistant", "单聊回复")
        from gui.widgets.chat_panel import ChatPanelWidget
        ChatPanelWidget._sync_llm_context(self._panel_dummy(llm), session)
        entries = llm.replace_history.call_args[0][0]
        assert [e["role"] for e in entries] == ["user", "assistant"]
        assert entries[0]["content"] == "单聊消息"

    def test_switch_from_group_to_single_no_leak(self):
        llm = MagicMock()
        group = _group_display_session()
        group.add_message("assistant", "群内容", metadata={"speaker_id": "r_a"})
        single = ChatSession(name="单聊")
        single.add_message("user", "单聊消息")
        from gui.widgets.chat_panel import ChatPanelWidget
        dummy = self._panel_dummy(llm)
        ChatPanelWidget._sync_llm_context(dummy, group)
        ChatPanelWidget._sync_llm_context(dummy, single)
        # 群内容从未进入 LLM 历史；切回单聊后历史 = 单聊消息
        assert llm.replace_history.call_count == 2
        entries = llm.replace_history.call_args[0][0]
        assert all("群内容" not in (e.get("content") or "") for e in entries)


# ---------------------------------------------------------------------------
# ⑦ 单聊会话完全不受影响（回归）
# ---------------------------------------------------------------------------
class TestSingleChatRegression:
    def test_single_chat_assembly_and_writeback(self):
        """单聊链回归：user 入库 / 历史组装 / assistant 写入 / 计分链原样。"""
        llm = MagicMock()
        llm.history = [{"role": "system", "content": "sys"}]
        intimacy = MagicMock()
        ctx = _mock_app_ctx(llm_session=llm)
        ctx.intimacy = intimacy
        svc = ChatService(ctx)
        fake_worker = MagicMock()
        fake_worker.isRunning.return_value = False
        svc._worker = fake_worker

        launched = {}
        def _fake_api_worker(api, messages, task_config, app_ctx, **kw):
            launched["messages"] = messages
            launched["task_config"] = task_config
            m = MagicMock()
            m.start = lambda: None
            return m

        import gui.chat_service as cs_mod
        orig_worker = cs_mod.ApiWorker
        cs_mod.ApiWorker = _fake_api_worker
        try:
            svc.send_message("帮我看看这段代码", suppress_echo=True)
        finally:
            cs_mod.ApiWorker = orig_worker
        # user 消息照常写入 LLM 对齐历史（v1.5.1 链不变）
        llm.add_message.assert_called_once()
        assert llm.add_message.call_args[0][0] == "user"
        # 请求 = system + 既有历史 + 本轮 user
        msgs = launched["messages"]
        assert msgs[0]["role"] == "system" and msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "帮我看看这段代码"
        assert launched["task_config"]["task_type"] == "chat"
        assert svc._group_active is False  # 单聊不进入群聊调度态
        # 回复完成：assistant 写入 + 计分链照常（可能带随机语气注入，做包含断言）
        svc._on_stream_finished("这是回复", {"total_tokens": 5})
        last_args = llm.add_message.call_args[0]
        assert last_args[0] == "assistant" and "这是回复" in last_args[1]
        intimacy.add_interaction.assert_called()

    def test_single_session_model_untouched(self):
        """旧单聊会话零迁移：无 type 字段 = 单聊语义（is_group_session False）。"""
        s = ChatSession(name="旧会话")
        assert s.metadata == {}
        assert is_group_session(s) is False
        # <2 成员建群被拒绝（R-J③）
        sm = SessionManager(sessions_dir=Path(os.path.expanduser("~")) / ".maid_coder_test_f10" / "sessions")
        try:
            sm.create_group_session("坏群", ["only_one"])
            assert False, "<2 成员应拒绝建群"
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# F10b：@补全（纯函数 + 补全→@解析闭环）
# ---------------------------------------------------------------------------
class TestF10bMentionCompletion:
    def test_parse_mention_partial_states(self):
        from gui.chat_service import parse_mention_partial
        assert parse_mention_partial("hello world") is None      # 非 @态
        assert parse_mention_partial("在吗 ") is None
        assert parse_mention_partial("叫一下 @") == ""           # 刚输入 @
        assert parse_mention_partial("你看看 @小") == "小"        # 输入中
        assert parse_mention_partial("@鲸鱼_1") == "鲸鱼_1"
        assert parse_mention_partial("@小铃 你好") is None       # 已空格收尾 = 关闭

    def test_mention_candidates_prefix_filter(self):
        from gui.chat_service import mention_candidates
        names = ["小铃", "鲸鱼", "三三"]
        assert mention_candidates(names, "") == names            # @ 后弹全部
        assert mention_candidates(names, "小") == ["小铃"]
        assert mention_candidates(names, "四") == []

    def test_apply_mention_completion(self):
        from gui.chat_service import apply_mention_completion
        assert apply_mention_completion("你看 @小", "小铃") == "你看 @小铃 "
        assert apply_mention_completion("@", "鲸鱼") == "@鲸鱼 "
        # 非 @态不改动
        assert apply_mention_completion("普通文本", "小铃") == "普通文本"

    def test_completion_feeds_mention_parse(self):
        """补全插入结果必须能被 @解析命中（补全→触发闭环）。"""
        from gui.chat_service import apply_mention_completion, parse_group_mention
        text = apply_mention_completion("请问 @鲸", "鲸鱼") + "这个问题怎么看"
        assert text == "请问 @鲸鱼 这个问题怎么看"
        assert parse_group_mention(text, {"鲸鱼": "r_b"}) == "r_b"


# ---------------------------------------------------------------------------
# F10b：GuiConfig.group_* 持久化 + 建群默认消费
# ---------------------------------------------------------------------------
class TestF10bGroupConfig:
    def test_config_defaults_and_roundtrip(self, tmp_path, monkeypatch):
        from gui.config import GuiConfig
        monkeypatch.setattr(
            GuiConfig, "_config_path", classmethod(
                lambda cls: tmp_path / "gui_config.json"))
        cfg = GuiConfig()
        assert cfg.group_no_at_policy == "rotate"   # Q-C1 默认轮转
        # v1.8 收尾：group_chatter_enabled 配置键已退役，不再存在
        assert not hasattr(cfg, "group_chatter_enabled")
        cfg.group_no_at_policy = "silent"
        cfg.save()
        cfg2 = GuiConfig.load()
        assert cfg2.group_no_at_policy == "silent"
        assert not hasattr(cfg2, "group_chatter_enabled")

    def test_create_group_consumes_config_defaults(self, tmp_path):
        """建群默认策略可按 GuiConfig 值落会话级 metadata（会话级可覆盖）。"""
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        s = sm.create_group_session("群聊", ["a", "b"], no_at_policy="silent")
        assert s.metadata["no_at_policy"] == "silent"
        assert "chatter" not in s.metadata   # v1.8 收尾：chatter 字段已退役
        # silent 策略在发言调度中生效（未@ → 沉默零回复）
        svc = _make_service()
        svc._launch_group_scheduler = lambda *a, **k: None
        mode = svc.send_group_turn("随便聊聊", s,
                                   {"a": _fake_role("a", "甲"), "b": _fake_role("b", "乙")})
        assert mode == "silent"


# ---------------------------------------------------------------------------
# F10b：群标签 / 群设置（改名/解散）生命周期
# ---------------------------------------------------------------------------
class TestF10bGroupLifecycle:
    def test_group_badge_and_rename_persist(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        s = sm.create_group_session("群聊", ["a", "b"])
        assert is_group_session(s)  # 列表 👥 角标的判定源
        sm.rename_session(s.id, "小客厅")
        sm2 = SessionManager(sessions_dir=tmp_path / "sessions")
        assert sm2.get_session(s.id).name == "小客厅"
        assert is_group_session(sm2.get_session(s.id))

    def test_disband_removes_session_file(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path / "sessions")
        s = sm.create_group_session("群聊", ["a", "b"])
        file_path = tmp_path / "sessions" / f"{s.id}.json"
        assert file_path.exists()
        assert sm.delete_session(s.id) is True      # 解散 = 复用删除链
        assert not file_path.exists()
        assert sm.get_session(s.id) is None

    def test_group_settings_menu_action_present(self):
        """右键菜单群聊设置分支的判定源：群会话才注入设置项（源码断言）。"""
        src = (ROOT / "gui" / "widgets" / "chat_panel.py").read_text(encoding="utf-8")
        assert "群聊设置" in src and "_on_group_settings" in src
        assert "解散群聊" in src


# ---------------------------------------------------------------------------
# F10b：proactive 主动消息群聊边界（隐藏不入面板）
# ---------------------------------------------------------------------------
class TestF10bProactiveBoundary:
    def _panel_dummy(self, session, add_bubble, save):
        return SimpleNamespace(
            chat_service=None,
            _current_ai_bubble=None,
            _current_group_session=lambda: session,
            session_manager=SimpleNamespace(
                get_session=lambda sid: session if sid == session.id else None),
            _current_session_id=session.id,
            _add_message_bubble=add_bubble,
            _save_current_session=save,
        )

    def test_proactive_hidden_in_group_session(self):
        from gui.widgets.chat_panel import ChatPanelWidget
        session = _group_display_session(members=("r_a", "r_b"))
        session.add_message("user", "群消息")
        add_bubble, save = MagicMock(), MagicMock()
        dummy = self._panel_dummy(session, add_bubble, save)
        ChatPanelWidget._on_message_added(dummy, "assistant", "码铃的主动关心")
        add_bubble.assert_not_called()   # 群聊激活 → 主动消息不入面板
        save.assert_not_called()         # 也不落群聊显示会话

    def test_normal_echo_still_renders_in_single_session(self):
        from gui.widgets.chat_panel import ChatPanelWidget
        session = ChatSession(name="单聊")
        session.add_message("user", "hi")
        add_bubble, save = MagicMock(), MagicMock()
        dummy = self._panel_dummy(session, add_bubble, save)
        ChatPanelWidget._on_message_added(dummy, "assistant", "单聊回复")
        add_bubble.assert_called_once()
        save.assert_called_once()

    def test_user_echo_path_unaffected_in_group(self):
        """守卫只拦 assistant 主动消息；user 回声抑制链不受影响。"""
        from gui.widgets.chat_panel import ChatPanelWidget
        session = _group_display_session(members=("r_a", "r_b"))
        svc = MagicMock()
        svc.echo_suppressed = True
        dummy = self._panel_dummy(session, MagicMock(), MagicMock())
        dummy.chat_service = svc
        ChatPanelWidget._on_message_added(dummy, "user", "x")
        dummy._add_message_bubble.assert_not_called()  # 既有 echo 抑制仍然生效


# ---------------------------------------------------------------------------
# F10 自由发言调度（定案）：轻量调度 → 1-2 人串行接话 → 失败兜底
# ---------------------------------------------------------------------------
class TestF10FreeTalkScheduler:
    ROLES = {"r_a": _fake_role("r_a", "小铃", prompt="小铃人设", avatar=None),
             "r_b": _fake_role("r_b", "鲸鱼", prompt="鲸鱼人设"),
             "r_c": _fake_role("r_c", "三三", prompt="三三人设")}

    # ---- ① 调度请求 payload 断言 ----
    def test_scheduler_payload_members_history_and_constraints(self):
        from gui.chat_service import (build_scheduler_messages,
                                      build_scheduler_context)
        session = _group_display_session()
        session.add_message("user", "早上好")
        session.add_message("assistant", "早呀主人", metadata={"speaker_id": "r_a"})
        recent = build_scheduler_context(session.messages, self.ROLES, "今晚吃什么")
        assert "主人：早上好" in recent
        assert "【小铃】：早呀主人" in recent        # 他人发言带名字前缀
        assert "主人（本轮新消息）：今晚吃什么" in recent
        msgs = build_scheduler_messages(self.ROLES, "今晚吃什么", recent)
        assert msgs[0]["role"] == "system"
        # 约束提示词：1-2 人 / 没人合适也选最相关的 1 人 / 自言自语例外 / 严格 JSON
        assert "1-2 人" in msgs[0]["content"]
        assert "最相关的 1 人" in msgs[0]["content"]
        assert "自言自语" in msgs[0]["content"]
        assert '"speakers"' in msgs[0]["content"] and '"reason"' in msgs[0]["content"]
        # 成员清单：id + 名字 + 一句话人设
        assert "id=r_a 名字=小铃" in msgs[1]["content"]
        assert "小铃人设" in msgs[1]["content"]
        assert "鲸鱼" in msgs[1]["content"]

    def test_scheduler_context_limits_to_6(self):
        from gui.chat_service import build_scheduler_context
        session = _group_display_session()
        for i in range(10):
            session.add_message("user", f"u{i}")
            session.add_message("assistant", f"a{i}", metadata={"speaker_id": "r_b"})
        recent = build_scheduler_context(session.messages, self.ROLES, "最新消息")
        body = [ln for ln in recent.split("\n")
                if ln.startswith(("主人：", "【"))]
        assert len(body) <= 6 + 1                     # 6 条历史 + 本轮新消息
        assert "u9" in recent and "u0" not in recent   # 保留最近

    def test_parse_scheduler_reply_by_id_and_name(self):
        from gui.chat_service import parse_scheduler_reply
        # 名字匹配 / id 匹配 / 混合
        raw = '{"speakers": ["小铃", "r_b"], "reason": "两人都适合"}'
        assert parse_scheduler_reply(raw, self.ROLES) == ["r_a", "r_b"]
        # 保序去重 + 非法过滤 + >2 截断（调度硬约束）
        raw2 = '{"speakers": ["鲸鱼", "不存在", "鲸鱼", "三三", "小铃"], "reason": "x"}'
        assert parse_scheduler_reply(raw2, self.ROLES) == ["r_b", "r_c"]
        # 垃圾输出 → 空列表（调用方回退轮转）
        assert parse_scheduler_reply("这不是JSON", self.ROLES) == []
        assert parse_scheduler_reply('{"speakers": []}', self.ROLES) == []
        # ```json 围栏容错
        raw3 = '```json\n{"speakers": ["三三"], "reason": "r"}\n```'
        assert parse_scheduler_reply(raw3, self.ROLES) == ["r_c"]

    # ---- ② 调度 2 人 → 串行两次请求且第二次含第一次发言（接话） ----
    def test_serial_two_speakers_second_sees_first(self):
        svc = _make_service()
        session = _group_display_session()
        session.add_message("user", "今天我们聊什么好")
        captured = []
        svc._launch_group_worker = lambda messages, spk, disp, cfg: \
            captured.append({"speaker": spk.id, "messages": messages}) or True
        svc._drain = lambda: None
        # 模拟调度成功返回 2 人（小铃 → 鲸鱼）
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_speaker_queue = ["r_a", "r_b"]
        svc._advance_group_queue()
        assert len(captured) == 1 and captured[0]["speaker"] == "r_a"
        # 第一位发言完成（气泡渲染完 → 显示会话已落盘）→ 推进第二位
        svc._group_speaker_id = "r_a"          # 桩未走 _launch_group_worker，手动归属
        svc._group_display_session = session   # 桩路径补显示会话（真实链由 worker 启动时设置）
        svc._on_group_stream_finished("今天聊点开心的吧", {"total_tokens": 30})
        assert len(captured) == 2
        assert captured[1]["speaker"] == "r_b"
        # 第二位请求包含第一位刚说的话，且带【名字】：前缀（接话语义）
        texts = [m.get("content", "") for m in captured[1]["messages"]]
        assert any("【小铃】：今天聊点开心的吧" in t for t in texts)
        assert svc._group_speaker_queue == []         # 队列耗尽，本轮结束

    # ---- ④ JSON 解析失败 / 超时 → 回退轮转 ----
    def test_garbage_reply_falls_back_to_rotation(self):
        svc = _make_service()
        session = _group_display_session()
        session.add_message("user", "在吗")
        captured = []
        svc._launch_group_worker = lambda messages, spk, disp, cfg: \
            captured.append(spk.id) or True
        svc._drain = lambda: None
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_sched_req_id = "gs_1"
        svc._on_group_scheduled("gs_1", "完全不是JSON", {})
        assert captured == ["r_a"]                    # turn_order 轮转第一位兜底

    def test_timeout_falls_back_to_rotation(self):
        svc = _make_service()
        session = _group_display_session()
        captured = []
        svc._launch_group_worker = lambda messages, spk, disp, cfg: \
            captured.append(spk.id) or True
        svc._drain = lambda: None
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_sched_req_id = "gs_9"
        svc._on_scheduler_timeout("gs_9")
        assert captured == ["r_a"]

    def test_scheduler_failure_falls_back(self):
        svc = _make_service()
        session = _group_display_session()
        captured = []
        svc._launch_group_worker = lambda messages, spk, disp, cfg: \
            captured.append(spk.id) or True
        svc._drain = lambda: None
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_sched_req_id = "gs_2"
        svc._on_scheduler_failed("gs_2", "网络错误")
        assert captured == ["r_a"]

    # ---- 调度计费透明 ----
    def test_scheduler_usage_billed(self):
        svc = _make_service(llm_session=MagicMock())
        session = _group_display_session()
        svc._launch_group_worker = lambda *a, **k: True
        svc._drain = lambda: None
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_sched_req_id = "gs_3"
        svc._on_group_scheduled("gs_3",
                                '{"speakers": ["小铃"], "reason": "r"}',
                                {"total_tokens": 88})
        svc._app_ctx.session.add_usage.assert_called_with({"total_tokens": 88})

    # ---- 过期调度回调拦截 ----
    def test_stale_schedule_callback_ignored(self):
        svc = _make_service(llm_session=MagicMock())
        captured = []
        svc._launch_group_worker = lambda messages, spk, disp, cfg: \
            captured.append(spk.id) or True
        svc._group_sched_req_id = "gs_new"
        svc._on_group_scheduled("gs_old", '{"speakers": ["小铃"]}', {})
        svc._on_scheduler_failed("gs_old", "err")
        svc._on_scheduler_timeout("gs_old")
        assert captured == []                          # 过期回调零影响

    # ---- ⑤ 发言失败终止本轮剩余接话 ----
    def test_speak_failure_stops_remaining_queue(self):
        svc = _make_service()
        session = _group_display_session()
        svc._group_sched_state = {"session": session, "member_roles": self.ROLES}
        svc._group_speaker_queue = ["r_a", "r_b"]
        svc._group_active = True
        svc._on_api_error("网络错误")                 # 第一位发言失败
        assert svc._group_speaker_queue == []          # 剩余接话终止
        assert svc._group_active is False

    # ---- 真实 GroupScheduleWorker 单元（api stub，不开线程） ----
    def test_group_schedule_worker_run_logic(self):
        from gui.chat_service import GroupScheduleWorker
        api = MagicMock()
        api.chat.return_value = {"choices": [{"message": {"content":
            '{"speakers": ["小铃"], "reason": "r"}'}}], "usage": {"total_tokens": 42}}
        worker = GroupScheduleWorker.__new__(GroupScheduleWorker)
        # 手动绑定（绕开 QThread 初始化依赖，仅验证 run 调用逻辑）
        import threading
        results = {}
        class _Sig:
            def __init__(self, key):
                self._key = key
            def emit(self, *args):
                results[self._key] = args
        worker.schedule_ready = _Sig("ready")
        worker.schedule_failed = _Sig("fail")
        worker._api = api
        worker._messages = [{"role": "system", "content": "s"}]
        worker._req_id = "gs_x"
        worker._max_tokens = 120
        worker.run()
        assert results["ready"][0] == "gs_x"
        assert "speakers" in results["ready"][1]
        assert results["ready"][2] == {"total_tokens": 42}
        api.chat.assert_called_once_with(worker._messages, max_tokens=120, temperature=0.2)
