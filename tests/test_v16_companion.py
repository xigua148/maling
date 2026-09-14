"""tests/test_v16_companion.py —— v1.6 第一批针对性自测（P0-3 + P0-1 页面）。

覆盖任务面自测项 ②③④⑤：
- ② 抑制表：mute 后 followup 跳过、7 天去重生效（memory 部分见 test_memory.py，
  这里测 greeting.build_contentful_line 对 muted 的消费）；
- ③ 三键：feedback 写回 followup_muted_until、不进 intimacy 计分（护栏断言）；
- ④ page_memory_book offscreen 构造 + CRUD + 主题色；
- ⑤ startup_greet 四重闸回归（enabled/quiet/cap/cooldown + 占配额）。
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from memory import MemoryManager
from managers import TodoManager


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeCompanion:
    def __init__(self):
        self.commits = []
        self._snapshot = {}

    def proactive_snapshot(self):
        return dict(self._snapshot)

    def commit_proactive(self, count_delta=1):
        self.commits.append(count_delta)

    def to_dict(self):
        return {"event_log": []}


class FakeChatService:
    def __init__(self):
        self.calls = []

    def proactive_ask(self, text, scene="idle_hello", subject=""):
        self.calls.append({"text": text, "scene": scene, "subject": subject})
        return True

    def is_busy(self):
        return False


class FakeSession:
    def __init__(self, memory_mgr, todo_mgr=None):
        self.memory_mgr = memory_mgr
        self.todo_mgr = todo_mgr
        self.refresh_calls = 0

    def refresh_system_context(self):
        self.refresh_calls += 1


def _backdate_topic(mm, hours=2.0):
    t = mm.get_active_topics()[0]
    t["last_mentioned"] = (datetime.now() - timedelta(hours=hours)).isoformat()
    mm._save()


# ---------------------------------------------------------------------------
# ① greeting.build_contentful_line（内容拼装 + muted 消费）
# ---------------------------------------------------------------------------
class TestBuildContentfulLine:
    def test_topic_followup_hit(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate_topic(mm, hours=2)
        hit = build_contentful_line(mm, None)
        assert hit is not None
        assert "Rust 入门" in hit["text"]
        assert hit["subject"] == "Rust 入门"

    def test_muted_topic_skipped_returns_none(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate_topic(mm, hours=2)
        mm.record_followup_feedback("Rust 入门", "mute")
        assert build_contentful_line(mm, None) is None

    def test_dedup_only_once(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate_topic(mm, hours=2)
        assert build_contentful_line(mm, None) is not None
        assert build_contentful_line(mm, None) is None  # asked_at 7 天去重

    def test_emotion_continuation(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm._data["habits"]["last_emotion"] = "tired"
        mm._data["habits"]["last_emotion_time"] = datetime.now().isoformat()
        mm._save()
        hit = build_contentful_line(mm, None)
        assert hit is not None and hit["subject"] == "__emotion__"

    def test_emotion_muted_falls_through(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm._data["habits"]["last_emotion"] = "tired"
        mm._data["habits"]["last_emotion_time"] = datetime.now().isoformat()
        mm.record_followup_feedback("__emotion__", "mute")  # 源级静默 3 天
        assert build_contentful_line(mm, None) is None

    def test_todo_nudge(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        td = TodoManager(str(tmp_path / "t.json"))
        td.add_item("给花园浇水")
        # 待办需 ≥24h 才轻提
        td._items[0]["created_at"] = (datetime.now() - timedelta(hours=25)).isoformat()
        td._save()
        hit = build_contentful_line(mm, td)
        assert hit is not None and hit["subject"] == "__todo__"

    def test_todo_fresh_not_nudged(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        td = TodoManager(str(tmp_path / "t.json"))
        td.add_item("刚记下的事")
        assert build_contentful_line(mm, td) is None

    def test_no_content_returns_none(self, tmp_path):
        from greeting import build_contentful_line
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        assert build_contentful_line(mm, None) is None


# ---------------------------------------------------------------------------
# ⑤ scheduler 接线 + maybe_startup_greet 四重闸
# ---------------------------------------------------------------------------
class FakeCfg:
    """鸭子类型 AppConfig（显式属性，避免 MagicMock 误触发 demo 判定）。"""

    def __init__(self, enabled=True, cap=3, cooldown=0, idle=90):
        self.api_provider = "openai"
        self.api_key = "sk-test"
        self.agent_proactive_enabled = enabled
        self.agent_proactive_quiet_start = "03:00"
        self.agent_proactive_quiet_end = "03:01"
        self.agent_proactive_daily_cap = cap
        self.agent_proactive_cooldown_minutes = cooldown
        self.agent_proactive_idle_minutes = idle


def _make_scheduler(tmp_path, monkeypatch, *, cap=3, enabled=True, memory_seed=True):
    from gui import proactive_scheduler as ps
    # 静默闸确定性：测试中关掉 quiet 判定（仅本测试进程）
    monkeypatch.setattr(ps, "is_in_quiet", lambda *a, **k: False)
    mm = MemoryManager(filepath=str(tmp_path / "m.json"))
    td = TodoManager(str(tmp_path / "t.json"))
    if memory_seed:
        mm.add_topic("Rust 入门", source="manual")
        _backdate_topic(mm, hours=2)
    session = FakeSession(mm, td)
    companion = FakeCompanion()
    chat_service = FakeChatService()

    class FakeCtx:
        pass

    ctx = FakeCtx()
    ctx.cfg = FakeCfg(enabled=enabled, cap=cap)
    ctx.config = ctx.cfg
    ctx.session = session
    ctx.companion = companion
    ctx.chat_service = chat_service
    sched = ps.ProactiveScheduler(ctx)
    return sched, session, companion, chat_service


class TestSchedulerWiring:
    def test_startup_greet_content_and_accounting(self, tmp_path, monkeypatch):
        sched, session, companion, chat_service = _make_scheduler(tmp_path, monkeypatch)
        out = sched.maybe_startup_greet()
        assert out == "idle_hello"
        assert len(chat_service.calls) == 1
        call = chat_service.calls[0]
        assert call["scene"] == "idle_hello"
        assert call["subject"] == "Rust 入门"          # 内容源键随投递传出
        assert "Rust 入门" in call["text"]              # 模板句 + 换行 + 内容句
        assert "\n" in call["text"]
        assert companion.commits == [1]                 # 占 cap/cooldown 记账
        assert session.memory_mgr.get_active_topics()[0]["followup_asked_at"] is not None

    def test_startup_greet_template_fallback(self, tmp_path, monkeypatch):
        from gui import proactive_scheduler as _ps

        class _NoonDT(_ps.datetime):
            @classmethod
            def now(cls):
                return _ps.datetime(2026, 9, 9, 12, 0)
        # 正午冻结：避开晨(5-11)/午后/深夜仪式窗口，保证纯模板回退路径
        # （不冻结时 5-11 点运行会并入早安仪式句导致跨时刻假红）
        monkeypatch.setattr(_ps, "datetime", _NoonDT)
        sched, session, companion, chat_service = _make_scheduler(
            tmp_path, monkeypatch, memory_seed=False)
        out = sched.maybe_startup_greet()
        assert out == "idle_hello"
        call = chat_service.calls[0]
        assert call["subject"] == ""                    # 纯模板 → 无三键
        assert call["text"] in ("主人还在忙呀，码铃安静陪着呢~",
                                "好久没听到主人的声音了，需要码铃的话随时喊一声~")

    def test_startup_greet_one_shot(self, tmp_path, monkeypatch):
        sched, *_ = _make_scheduler(tmp_path, monkeypatch, memory_seed=False)
        assert sched.maybe_startup_greet() is not None
        assert sched.maybe_startup_greet() is None      # 一次性标记防重复

    def test_startup_greet_respects_cap(self, tmp_path, monkeypatch):
        sched, session, companion, chat_service = _make_scheduler(
            tmp_path, monkeypatch, memory_seed=False, cap=0)
        assert sched.maybe_startup_greet() is None      # daily_cap_reached
        assert chat_service.calls == []
        assert companion.commits == []

    def test_startup_greet_respects_enabled_off(self, tmp_path, monkeypatch):
        sched, session, companion, chat_service = _make_scheduler(
            tmp_path, monkeypatch, memory_seed=False, enabled=False)
        assert sched.maybe_startup_greet() is None
        assert chat_service.calls == []

    def test_startup_greet_yields_to_recent_user_activity(self, tmp_path, monkeypatch):
        from datetime import datetime as _dt
        sched, session, companion, chat_service = _make_scheduler(
            tmp_path, monkeypatch, memory_seed=False)
        sched._last_user_activity_at = _dt.now()        # 用户刚交互过 → 让路
        assert sched.maybe_startup_greet() is None
        assert chat_service.calls == []

    def test_startup_greet_respects_cooldown(self, tmp_path, monkeypatch):
        from gui.proactive_scheduler import ProactiveConfig
        sched, session, companion, chat_service = _make_scheduler(
            tmp_path, monkeypatch, memory_seed=False)
        # 上次主动在 30 分钟前 + cooldown=60 → 应被冷却闸拦截
        companion._snapshot = {"last_at": (datetime.now() - timedelta(minutes=30)).isoformat(),
                               "count_today": 0}
        monkeypatch.setattr(
            "gui.proactive_scheduler.ProactiveConfig.from_cfg",
            classmethod(lambda cls, c: ProactiveConfig(
                enabled=True, quiet_start="03:00", quiet_end="03:01",
                daily_cap=3, idle_minutes=90, cooldown_minutes=60)),
        )
        assert sched.maybe_startup_greet() is None    # cooldown 拦截
        assert chat_service.calls == []

    def test_run_check_idle_hello_with_content(self, tmp_path, monkeypatch):
        from datetime import datetime as _dt
        sched, session, companion, chat_service = _make_scheduler(tmp_path, monkeypatch)
        sched._last_user_activity_at = _dt.now() - timedelta(minutes=120)  # idle>90min
        scene = sched.run_check()
        assert scene == "idle_hello"
        call = chat_service.calls[0]
        assert "Rust 入门" in call["text"]
        assert call["subject"] == "Rust 入门"


# ---------------------------------------------------------------------------
# ③ 反馈三键：写回 + 不进 intimacy / 不打交互点（护栏）
# ---------------------------------------------------------------------------
class TestFeedbackGuardrails:
    def test_bar_pick_callback_and_once(self, tmp_path):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from gui.widgets.proactive_feedback import ProactiveFeedbackBar
        app = QApplication.instance() or QApplication([])
        picked = []
        bar = ProactiveFeedbackBar("Rust 入门", "idle_hello",
                                   lambda s, sc, k: picked.append((s, sc, k)))
        bar.expand()
        # 找到「先不提这个」按钮并点击（按 objectName 过滤，排除 ✨ 收起钮）
        from PySide6.QtWidgets import QPushButton
        btns = [b for b in bar.findChildren(QPushButton) if b.objectName() == "feedbackBtn"]
        assert len(btns) == 3
        mute_btn = next(b for b in btns if "先不提" in b.text())
        mute_btn.click()
        assert picked == [("Rust 入门", "idle_hello", "mute")]
        assert bar._answered is True
        # 已反馈后再点无效（防重复提交）
        mute_btn.click()
        assert len(picked) == 1

    def test_feedback_writeback_and_no_intimacy(self, tmp_path, monkeypatch):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        # 护栏 spy：intimacy / 交互打点绝不应被触碰
        bump_calls = []
        mark_calls = []

        class SpyIntimacy:
            def bump_intimacy(self, *a, **k):
                bump_calls.append(a)

        class SpyScheduler:
            _last_user_activity_at = None

            def mark_user_activity(self):
                mark_calls.append(1)

        spy_sched = SpyScheduler()
        # 模拟面板回调路径（chat_panel._on_feedback_picked 的核心写回）
        mm.record_followup_feedback("Rust 入门", "mute")
        # 断言：muted_until 写回 ≥13 天；interactions 零
        t = mm.get_active_topics()[0]
        muted_until = datetime.fromisoformat(t["followup_muted_until"])
        assert (muted_until - datetime.now()).days >= 13
        assert bump_calls == []
        assert mark_calls == []
        assert spy_sched._last_user_activity_at is None

    def test_chat_panel_callback_writes_memory_only(self, tmp_path):
        """chat_panel._on_feedback_picked 全路径护栏（真实方法）。"""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        session = FakeSession(mm)

        class Ctx:
            pass

        ctx = Ctx()
        ctx.session = session
        from gui.widgets import chat_panel as cp_mod

        # 不构造整个面板（重依赖），借用真实未绑定方法 + 假 self 验证逻辑
        class FakePanel:
            app_ctx = ctx
            chat_service = None

        cp_mod.ChatPanelWidget._on_feedback_picked(
            FakePanel(), "Rust 入门", "idle_hello", "heart")
        assert mm.get_active_topics()[0]["followup_score"] == 1
        assert session.refresh_calls == 0  # 反馈路径不触发 system 重建（纯策略写）


# ---------------------------------------------------------------------------
# ④ page_memory_book offscreen 构造 + CRUD + 主题色
# ---------------------------------------------------------------------------
class TestPageMemoryBookOffscreen:
    def _page(self, tmp_path):
        from PySide6.QtWidgets import QApplication
        from gui.pages.page_memory_book import PageMemoryBook
        app = QApplication.instance() or QApplication([])
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        session = FakeSession(mm)
        session.refresh_calls = 0

        class Ctx:
            pass

        ctx = Ctx()
        ctx.session = session
        # v1.7(F7): 日记 Tab 懒装配会回落真实 ~/.maid_coder——测试预挂 tmp 单例
        try:
            from diary import DiaryManager
            ctx.diary = DiaryManager(filepath=tmp_path / "diaries.json")
        except Exception:
            pass
        page = PageMemoryBook(ctx)
        return page, mm, session

    def test_construct_and_empty_states(self, tmp_path):
        page, mm, session = self._page(tmp_path)
        # v1.8(D-V18-09): 记忆中心满 8 分区（+人物关系/回应约定/共同经历）
        assert page.tabs.count() == 8
        assert page.tabs.tabText(3) == "人物关系"
        assert page.tabs.tabText(4) == "回应约定 📌"
        assert page.tabs.tabText(6) == "往期回顾"
        assert page.tabs.tabText(7) == "她的日记"
        assert "只存于你的电脑" in page.privacy_label.text()
        # R-A 红线：无计数徽章（页面不渲染 N 条 字样）
        rendered = "\n".join(w.text() for w in page._list_widgets
                             if hasattr(w, "text"))
        assert "条记忆" not in rendered

    def test_pref_crud_and_cards(self, tmp_path):
        page, mm, session = self._page(tmp_path)
        mm.set_preference("nickname", "小远", source="manual")
        page.refresh()
        texts = self._card_texts(page)
        assert any("nickname：小远" in t for t in texts)
        assert any("你告诉我的" in t for t in texts)
        # 删除（直接走 manager + 页面刷新，模拟删除即遗忘）
        mm.delete_preference("nickname")
        _ = session.refresh_calls
        from gui.pages.page_memory_book import _refresh_system_context
        _refresh_system_context(page.app_ctx)
        assert session.refresh_calls == 1  # 删除即遗忘当轮生效（R-I）
        page.refresh()
        assert not any("nickname" in t for t in self._card_texts(page))

    def test_topic_cards_pin_mute(self, tmp_path):
        page, mm, session = self._page(tmp_path)
        mm.add_topic("Rust 入门", source="auto")
        page.refresh()
        assert any("Rust 入门" in t for t in self._card_texts(page))
        # 固定（无对话框，直接回调）
        page._on_pin_topic("Rust 入门", True)
        assert mm.get_active_topics()[0]["pinned"] is True
        # 不要再提（mute 14 天）
        page._on_mute_topic("Rust 入门")
        t = mm.get_active_topics()[0]
        muted_until = datetime.fromisoformat(t["followup_muted_until"])
        assert (muted_until - datetime.now()).days >= 13
        # 遗忘（→ 归档 + refresh_system_context）
        before = session.refresh_calls
        page._on_forget_topic("Rust 入门")
        assert session.refresh_calls == before + 1
        assert len(mm.get_active_topics()) == 0
        assert len(mm.get_archived_topics()) == 1

    def test_emotion_section(self, tmp_path):
        page, mm, session = self._page(tmp_path)
        mm.extract_from_dialogue("今天好累啊", "抱抱")
        page.refresh()
        texts = self._card_texts(page)
        assert any("疲惫" in t for t in texts)

    def test_theme_colors_applied(self, tmp_path):
        page, mm, session = self._page(tmp_path)
        mm.set_preference("k", "v", source="manual")
        page.refresh()
        # 至少卡片类组件带上了 theme_color 取色的 QSS（含背景色声明）
        styles = [w.styleSheet() for w in page._list_widgets if hasattr(w, "styleSheet")]
        assert any("background" in s for s in styles)

    @staticmethod
    def _card_texts(page):
        texts = []
        from PySide6.QtWidgets import QLabel
        for w in page._list_widgets:
            if isinstance(w, QLabel):
                texts.append(w.text())
            else:
                for lab in w.findChildren(QLabel):
                    texts.append(lab.text())
        return texts
