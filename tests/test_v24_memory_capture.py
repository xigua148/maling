"""tests/test_v24_memory_capture.py —— v2.4 GUI 记忆捕获钩子（D-V24-01 / D-V24-04）。

背景：`extract_from_dialogue` 与 `archive_stale_topics` 此前**只有 CLI 调用**
（session.py:595 / :600），GUI 链路一次都不调 —— 实测 `~/.maid_coder/user_memory.json`
三周零写入，连带 pick_topic_followup 恒为 None。本文件钉住修复后的行为。

覆盖：
- 单聊普通轮 -> 真实写记忆（话题 / 偏好）
- 过期话题自动归档（D-V24-04）
- 零写入矩阵：暂存缺失 / 取消轮 / demo / 记忆管理器缺失
- 钩子内部异常绝不外抛（不阻塞消息链）
- 群聊三隔离（R-J④⑤ / 共享知识 26）在挂载后仍成立
- send_message 暂存置位条件（只走 chat、非 Agent、非 demo）

测试数据隔离：一律 `filepath=tmp_path`，不读写真实 ~/.maid_coder/（共享知识 23）。
"""
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from memory import MemoryManager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _AnyCall:
    """万能链式替身（connect/start 等任意调用可执行）。"""

    def __getattr__(self, name):
        return self

    def __call__(self, *a, **k):
        return None


class _DummyWorker:
    """替身 ApiWorker：捕获 messages/task_config，绝不启动线程。"""

    captured = {}

    def __init__(self, api, messages, task_config, app_ctx, on_session_used=None,
                 expr_filter=False):
        type(self).captured = {"messages": messages, "task_config": task_config}

    def __getattr__(self, name):
        return _AnyCall()


class _FakeSession:
    """最小 session 替身：只提供 _v18_memory_mgr 与请求组装所需字段。"""

    def __init__(self, memory_mgr):
        self.memory_mgr = memory_mgr
        self.history = [{"role": "system", "content": ""}]
        self.current_system = ""


def _make_service(memory_mgr, api_key="sk-test"):
    """构造真实 ChatService（守卫逻辑走真身，不做 monkeypatch）。"""
    from gui.chat_service import ChatService
    from gui.qt_compat import QApplication
    QApplication.instance() or QApplication([])
    cfg = MagicMock()
    cfg.api_key = api_key
    cfg.api_provider = "deepseek"
    cfg.stream_mode = True
    cfg.temperature = 0.7
    cfg.max_tokens = 2048
    cfg.maid_mode = True
    ctx = SimpleNamespace(cfg=cfg, config=cfg, api=MagicMock(),
                          session=_FakeSession(memory_mgr),
                          collaborator=None, intimacy=None)
    return ChatService(ctx)


def _make_mm(tmp_path):
    return MemoryManager(filepath=str(tmp_path / "v24_capture.json"))


class TestCaptureWritesMemory:
    """正向：单聊普通轮必须真正落记忆（修复前这里恒为空）。"""

    def test_topic_captured_with_auto_source(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": "我最近在学 Rust"}, "好呀",
                                        {"cancelled": False})
        topics = mm.get_active_topics()
        assert [t["subject"] for t in topics] == ["学 Rust"]
        # source=auto 是 GUI 下首次可能出现的来源（记忆中心「自动提取」角标）
        assert topics[0]["source"] == "auto"

    def test_preference_captured(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": "请叫我小远"}, "好的，小远",
                                        {"cancelled": False})
        assert mm.get_preference("nickname") == "小远"

    def test_memory_actually_persisted_to_disk(self, tmp_path):
        """落盘断言：不只是内存态（这是本次修复的核心症状）。"""
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": "我在研究向量数据库"}, "嗯",
                                        {"cancelled": False})
        reloaded = _make_mm(tmp_path)
        assert [t["subject"] for t in reloaded.get_active_topics()] == ["向量数据库"]

    def test_stale_topics_archived_on_capture(self, tmp_path):
        """D-V24-04：同处跑过期归档（此前同样只有 CLI 调）。"""
        mm = _make_mm(tmp_path)
        mm.add_topic("很久以前的事")
        for t in mm._data["topics"]["active"]:
            t["last_mentioned"] = (datetime.now() - timedelta(days=30)).isoformat()
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": "你好"}, "嗯", {})
        assert mm.get_active_topics() == []
        assert [t["subject"] for t in mm.get_archived_topics()] == ["很久以前的事"]
        assert mm.get_archived_topics()[0]["status"] == "auto_archived"


class TestCaptureZeroWriteMatrix:
    """零写入矩阵：除"单聊普通轮"外的所有组合都必须零调用、零落盘。"""

    def test_missing_pending_skipped(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply(None, "回复", {})
        svc._extract_memory_after_reply({}, "回复", {})
        assert mm.get_active_topics() == []

    def test_cancelled_turn_skipped(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": "我在研究向量数据库"}, "回复",
                                        {"cancelled": True})
        assert mm.get_active_topics() == []

    def test_demo_mode_skipped(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm, api_key="")   # 无 key = demo 模式
        svc._extract_memory_after_reply({"user_text": "我在研究向量数据库"}, "回复", {})
        assert mm.get_active_topics() == []

    def test_missing_memory_mgr_skipped(self, tmp_path):
        svc = _make_service(None)   # session.memory_mgr 为 None
        # 不抛错即通过（全链静默降级）
        svc._extract_memory_after_reply({"user_text": "我在研究向量数据库"}, "回复", {})


class TestCaptureNeverBlocks:
    """钩子异常绝不外抛 —— 与 _stash_vision_memory 同款纪律。"""

    def test_extract_exception_swallowed(self, tmp_path):
        class _BoomMM:
            def extract_from_dialogue(self, *a, **k):
                raise RuntimeError("boom")

            def archive_stale_topics(self, *a, **k):
                raise RuntimeError("boom")

        svc = _make_service(_BoomMM())
        svc._extract_memory_after_reply({"user_text": "任意"}, "回复", {})   # 不应抛出

    def test_archive_exception_swallowed_after_successful_extract(self, tmp_path):
        mm = _make_mm(tmp_path)

        class _ArchiveBoom:
            def __init__(self, inner):
                self._inner = inner

            def extract_from_dialogue(self, *a, **k):
                return self._inner.extract_from_dialogue(*a, **k)

            def archive_stale_topics(self, *a, **k):
                raise RuntimeError("archive boom")

        svc = _make_service(_ArchiveBoom(mm))
        svc._extract_memory_after_reply({"user_text": "我在研究向量数据库"}, "回复", {})
        # 提取已成功落盘，归档失败不影响它
        assert [t["subject"] for t in mm.get_active_topics()] == ["向量数据库"]

    def test_bad_user_text_type_does_not_crash(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._extract_memory_after_reply({"user_text": None}, "回复", {})
        svc._extract_memory_after_reply({"user_text": 12345}, "回复", {})


class TestGroupIsolationPreserved:
    """R-J④⑤ / 共享知识 26：群聊三隔离在挂载后必须仍然成立。"""

    def test_group_path_never_reaches_capture_hook(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._group_active = True
        svc._on_group_stream_finished = lambda *a, **k: None
        called = []
        svc._extract_memory_after_reply = lambda *a, **k: called.append(1)
        svc._pending_memory_turn = {"user_text": "我最近在学 Rust"}
        svc._on_stream_finished("回复", {"cancelled": False})
        assert called == [], "群聊路径不得触发记忆捕获"
        assert mm.get_active_topics() == []

    def test_group_path_clears_stash(self, tmp_path):
        """一次性消费语义：群聊轮也把暂存取走（不留残留串档下一轮）。"""
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._group_active = True
        svc._on_group_stream_finished = lambda *a, **k: None
        svc._pending_memory_turn = {"user_text": "大家好"}
        svc._on_stream_finished("回复", {"cancelled": False})
        assert svc._pending_memory_turn is None


class TestStashSetting:
    """send_message 的暂存置位条件。"""

    def test_stash_set_for_plain_chat(self, tmp_path, monkeypatch):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        svc.send_message("我最近在学 Rust", suppress_echo=True)
        assert svc._pending_memory_turn == {"user_text": "我最近在学 Rust"}

    def test_stash_cleared_at_turn_start(self, tmp_path, monkeypatch):
        """每轮发送先清暂存（防陈旧串档，与 _pending_vision 同款）。"""
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        svc._pending_memory_turn = {"user_text": "上一轮的残留"}
        svc.send_message("今天天气不错", suppress_echo=True)
        # 被本轮覆盖为新文本，而非沿用残留
        assert svc._pending_memory_turn == {"user_text": "今天天气不错"}

    def test_cancel_clears_stash(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._pending_memory_turn = {"user_text": "我在研究向量数据库"}
        svc._on_cancelled()
        assert svc._pending_memory_turn is None

    def test_failure_clears_stash(self, tmp_path):
        mm = _make_mm(tmp_path)
        svc = _make_service(mm)
        svc._pending_memory_turn = {"user_text": "我在研究向量数据库"}
        svc._on_api_error("boom")
        assert svc._pending_memory_turn is None


class TestEndToEndCaptureCycle:
    """端到端验收：send_message -> _on_stream_finished 全链路 -> **重新读盘**验证。

    这是本次修复的核心判据 —— 修复前该链路终点为空（实测 user_memory.json 自
    2026-08-29 首启后三周零写入）。断言一律走"新开 MemoryManager 重读文件"，
    不依赖进程内数据，确保验的是真正落盘。
    """

    def test_full_cycle_writes_topic_to_disk(self, tmp_path, monkeypatch):
        fp = str(tmp_path / "e2e.json")
        mm = MemoryManager(filepath=fp)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        # ① 用户发话（暂存置位）
        svc.send_message("我最近在学 Rust", suppress_echo=True)
        assert svc._pending_memory_turn is not None
        # ② 流式回复完成（一次性消费 + 提取 + 落盘）
        svc._on_stream_finished("好呀，那你要加油～", {"cancelled": False})
        assert svc._pending_memory_turn is None
        # ③ 重新读盘验证
        reloaded = MemoryManager(filepath=fp)
        assert [t["subject"] for t in reloaded.get_active_topics()] == ["学 Rust"]
        assert reloaded.get_active_topics()[0]["source"] == "auto"

    def test_full_cycle_writes_preference_to_disk(self, tmp_path, monkeypatch):
        fp = str(tmp_path / "e2e_pref.json")
        mm = MemoryManager(filepath=fp)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        svc.send_message("请叫我小远", suppress_echo=True)
        svc._on_stream_finished("好的，小远～", {"cancelled": False})
        reloaded = MemoryManager(filepath=fp)
        assert reloaded.get_preference("nickname") == "小远"

    def test_group_cycle_writes_nothing_to_disk(self, tmp_path, monkeypatch):
        """群聊端到端：即使暂存已置位，全链路终点仍零落盘（R-J④⑤）。"""
        fp = str(tmp_path / "e2e_group.json")
        mm = MemoryManager(filepath=fp)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        svc.send_message("我最近在学 Rust", suppress_echo=True)
        assert svc._pending_memory_turn is not None
        svc._group_active = True
        svc._on_group_stream_finished = lambda *a, **k: None
        svc._on_stream_finished("回复", {"cancelled": False})
        reloaded = MemoryManager(filepath=fp)
        assert reloaded.get_active_topics() == []

    def test_cancelled_cycle_writes_nothing_to_disk(self, tmp_path, monkeypatch):
        fp = str(tmp_path / "e2e_cancel.json")
        mm = MemoryManager(filepath=fp)
        svc = _make_service(mm)
        monkeypatch.setattr("gui.chat_service.ApiWorker", _DummyWorker)
        svc.send_message("我最近在学 Rust", suppress_echo=True)
        svc._on_stream_finished("半截回复", {"cancelled": True})
        reloaded = MemoryManager(filepath=fp)
        assert reloaded.get_active_topics() == []
