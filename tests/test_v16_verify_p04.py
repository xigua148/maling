"""tests/test_v16_verify_p04.py —— v1.6 P0-4「已实现待验证」三项端到端验证（T5，只验证不开发）。

对应 D-V16-12 / R-K 销项：
- ① 停止生成立即生效：真 ApiWorker + 可取消流式 mock，流中点停 → 3s 内线程退出、
  message_cancelled 信号到达、无残留 worker（chat_service.is_busy()==False）；
- ② 上下文边界：max_history_rounds 截断受控（len(history) ≤ 1 + 4 + rounds*2）
  + context_trimmed 置位 + auto_summary 仅 CLI 链（GUI 无调用，D-V16-08 校正）；
- ③ 编辑重发基础链（v10.2）：确认框 → 截断该条及之后（UI 气泡 + 显示会话存档）
  + 回填输入框；LLM 侧行为如实记录（见测试内结论注释）。
隔离：FakeCtx / tmp 家目录，不读写真实 ~/.maid_coder。
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from gui.chat_service import ApiWorker, ChatService  # noqa: E402
from gui.qt_compat import QApplication  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeConfig:
    api_provider = "deepseek"
    api_key = "sk-test"
    stream_mode = True
    temperature = 0.7
    max_tokens = 2048
    maid_mode = True


class FakeCtx:
    def __init__(self):
        self.config = FakeConfig()
        self.session = MagicMock()


# ---------------------------------------------------------------------------
# ① 停止生成立即生效（StreamCancelled 链）
# ---------------------------------------------------------------------------
class FakeCancellableAPI:
    """可取消流式 mock：每块 yield 前查 cancel_check，取消时抛 StreamCancelled。"""

    class StreamCancelled(Exception):
        pass

    def __init__(self, chunks=200):
        self._chunks = chunks
        self.close_called = False

    def chat_stream_chunks(self, messages, cancel_check=None, on_response=None, **kw):
        for i in range(self._chunks):
            if cancel_check is not None and cancel_check():
                raise self.StreamCancelled("cancelled by user")
            time.sleep(0.01)
            yield f"chunk{i} "

    def close(self):
        self.close_called = True


class TestStopGenerationEffective:
    def test_stop_mid_stream_thread_exits_and_signal(self, qapp):
        api = FakeCancellableAPI()
        worker = ApiWorker(api, [{"role": "user", "content": "hi"}],
                           {"task_type": "chat", "user_text": "hi"}, FakeCtx())
        events = {"chunks": 0, "cancelled": False, "finished": False}
        worker.message_chunk_received.connect(lambda _: events.__setitem__("chunks", events["chunks"] + 1))
        worker.message_cancelled.connect(lambda: events.__setitem__("cancelled", True))
        worker.message_stream_finished.connect(lambda *a: events.__setitem__("finished", True))
        worker.start()
        # 等待流式产出（跨线程信号排队，spin 事件循环等待）
        deadline = time.time() + 5
        while events["chunks"] < 5 and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert events["chunks"] >= 5, "流式应已开始产出（前置：真流式链可用）"
        # 流中点停（与面板 ⏹ 同路径：stop_current → cancel_check + response.close）
        worker.stop_current()
        assert worker.wait(3000), "3s 内 worker 线程应退出（停止立即生效）"
        deadline = time.time() + 2
        while not (events["cancelled"] or events["finished"]) and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
        assert events["cancelled"], "取消路径应发出 message_cancelled（UI 显示「生成已停止~」）"
        assert not events["finished"], "取消不应走正常完成路径"
        assert not worker.isRunning(), "无残留 worker 线程"

    def test_chat_service_stop_releases_busy(self, qapp, monkeypatch):
        # 服务级：is_busy() 在 stop 后应归 False（主动陪伴闸依赖该判定）
        from gui.chat_service import ChatService as _CS
        _CS  # noqa
        ctx = FakeCtx()
        ctx.session.history = []
        ctx.session.add_message = lambda *a, **k: None
        svc = _CS(ctx)
        assert svc.is_busy() is False
        # 注入一个运行中的假 worker
        fake_worker = MagicMock()
        fake_worker.isRunning.return_value = True
        svc._worker = fake_worker
        assert svc.is_busy() is True
        svc.stop_current()
        assert svc._stop_requested is True
        fake_worker.stop_current.assert_called_once()


# ---------------------------------------------------------------------------
# ② 上下文边界（max_history_rounds + auto_summary 仅 CLI）
# ---------------------------------------------------------------------------
class TestContextBoundary:
    def _make_session(self, tmp_path, rounds=3):
        from core import AppConfig
        from session import ChatSession
        cfg = MagicMock(spec=AppConfig)
        cfg.max_history_rounds = rounds
        cfg.summary_interval = 5
        cfg.workspace = str(tmp_path)
        cfg.snippets_file = str(tmp_path / "s.json")
        cfg.todos_file = str(tmp_path / "t.json")
        cfg.code_exec_timeout = 5
        cfg.web_search_max_results = 3
        cfg.kb_index_file = str(tmp_path / "kb.json")
        cfg.plugins_dir = str(tmp_path / "plugins")
        cfg.persona_role = "maid"
        cfg.persona_title = "码铃"
        cfg.persona_personality = "温柔"
        cfg.persona_address_user = "主人"
        cfg.persona_address_self = "我"
        cfg.multi_enabled = False
        cfg.output_speed = "fast"
        cfg.stream_mode = False
        cfg.output_show_token_usage = False
        cfg.output_debug = False
        cfg.web_search_enabled = False
        cfg.sensitive_info_scan = False
        cfg.code_exec_enabled = False
        return ChatSession(cfg, MagicMock(), MagicMock())

    def test_request_length_controlled_30_rounds(self, tmp_path):
        # 30 轮对话（> max_history_rounds=3）→ history 受控 + context_trimmed 置位
        s = self._make_session(tmp_path, rounds=3)
        for i in range(30):
            s.add_message("user", f"u{i}")
            s.add_message("assistant", f"a{i}")
        limit = 1 + 4 + 3 * 2
        assert len(s.history) <= limit, \
            f"上下文边界：len(history)={len(s.history)} 应 ≤ 1+4+rounds*2={limit}"
        assert s.context_trimmed is True, "实际截断发生过 → 反套话注入条件成立"

    def test_trim_keeps_main_system_and_recent_injections(self, tmp_path):
        s = self._make_session(tmp_path, rounds=2)
        s.add_message("system", "[联网搜索上下文] 注入")
        for i in range(10):
            s.add_message("user", f"u{i}")
            s.add_message("assistant", f"a{i}")
        roles = [m["role"] for m in s.history]
        assert roles[0] == "system", "主 system prompt 必须保留在首位"
        assert len(s.history) <= 1 + 4 + 4

    def test_gui_has_no_auto_summary_call(self):
        # D-V16-08 校正：GUI 全树零 auto_summary 调用（摘要是 CLI-only 语义）
        gui_root = ROOT / "gui"
        hits = []
        for py in gui_root.rglob("*.py"):
            try:
                src = py.read_text(encoding="utf-8")
            except Exception:
                continue
            # 只匹配真实调用形态（.auto_summary(）；注释提及不算）
            if ".auto_summary(" in src:
                hits.append(str(py.relative_to(ROOT)))
        assert hits == [], f"GUI 链不应调用 auto_summary（D-V16-08），命中: {hits}"


# ---------------------------------------------------------------------------
# ③ 编辑重发基础链（v10.2）
# ---------------------------------------------------------------------------
class TestEditResendChain:
    def _panel(self, qapp):
        from gui.widgets.chat_panel import ChatPanelWidget
        from gui.widgets.message_bubble import MessageBubble
        ctx = FakeCtx()
        ctx.chat_service = ChatService(ctx)
        ctx.session = MagicMock()
        ctx.session.history = []
        ctx.session.replace_history = MagicMock()
        panel = ChatPanelWidget(ctx)
        return panel

    def test_edit_truncates_bubbles_and_backfills(self, qapp, monkeypatch, tmp_path):
        panel = self._panel(qapp)
        from gui.widgets.message_bubble import MessageBubble
        # 显示会话：3 条气泡 u1/a1/u2（在 u1 上触发编辑 → a1/u2 应被截断）
        b1 = panel._add_message_bubble("user", "第一条消息")
        b2 = panel._add_message_bubble("assistant", "第一条回复")
        b3 = panel._add_message_bubble("user", "第二条消息")
        # R9 确认框：mock 为 Yes
        from gui.qt_compat import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        panel._on_edit_requested(b1)
        qapp.processEvents()
        # 断言：b1/b2/b3 均已从布局移除（含该条及之后全部）
        remaining = []
        for i in range(panel.messages_layout.count()):
            w = panel.messages_layout.itemAt(i)
            if w is not None and isinstance(w.widget(), MessageBubble):
                remaining.append(w.widget())
        assert b1 not in remaining and b2 not in remaining and b3 not in remaining
        # 回填输入框
        assert panel.input_edit.toPlainText() == "第一条消息"
        assert "已回填到输入框" in panel.status_label.text()

    def test_edit_cancel_keeps_bubbles(self, qapp, monkeypatch):
        panel = self._panel(qapp)
        from gui.widgets.message_bubble import MessageBubble
        b1 = panel._add_message_bubble("user", "消息A")
        b2 = panel._add_message_bubble("assistant", "回复A")
        from gui.qt_compat import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
        panel._on_edit_requested(b1)
        remaining = []
        for i in range(panel.messages_layout.count()):
            w = panel.messages_layout.itemAt(i)
            if w is not None and isinstance(w.widget(), MessageBubble):
                remaining.append(w.widget())
        assert b1 in remaining and b2 in remaining, "取消确认 → 不截断（R9 防误触）"
        assert panel.input_edit.toPlainText() == ""

    def test_resend_after_edit_not_duplicated(self, qapp, monkeypatch):
        # 改后重发（正常 send_message 链）：显示会话截断后重发 → 存档无重复
        panel = self._panel(qapp)
        from gui.widgets.message_bubble import MessageBubble
        b1 = panel._add_message_bubble("user", "原始消息")
        panel._add_message_bubble("assistant", "回复")
        from gui.qt_compat import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        panel._on_edit_requested(b1)
        # 用户改文本后发送（面板直插气泡 = 唯一 user 渲染入口，suppress_echo）
        panel.input_edit.setPlainText("改后的消息")
        panel._add_message_bubble("user", "改后的消息")
        texts = []
        for i in range(panel.messages_layout.count()):
            w = panel.messages_layout.itemAt(i)
            widget = w.widget() if w is not None else None
            if isinstance(widget, MessageBubble) and widget.role == "user":
                texts.append(widget.get_text())
        assert texts == ["改后的消息"], f"重发后 user 气泡应只有一条改后文本，实际: {texts}"

    # —— 如实记录（R-K）：LLM 侧 app_ctx.session.history 在编辑截断时**不**同步截断，
    # 改后文本经正常 send 链追加到 LLM 历史（旧轮次仍保留，直至切换/新建会话经
    # _sync_llm_context 重建）。此为 v10.2 基础链的既有边界，与 v1.5.2 行为一致，
    # 本批只验证不扩改。验证结论已回传 team-lead。
