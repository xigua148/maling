# -*- coding: utf-8 -*-
"""v1.7 第二批测试（F4 贴身提醒 + F7 女仆日记）。

针对性覆盖（team-lead 任务书 ①-⑥）：
① NL 解析规则命中 / LLM 兜底失败诚实文案（零编造——失败路径零 due_at 写入）
② 到点通知触发（mock tray notify）+ quiet 降级顺延 + 启动补送恰一次
③ 次日补写触发与幂等
④ 日记 payload R-I 断言（白名单键，不含对话原文）
⑤ 365 篇滚动裁剪
⑥ 日记 Tab 构造翻阅

全部 tmp_path 隔离（R-I：绝不污染真实 ~/.maid_coder/）。
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# 共享：R-A 扫描（沿用 v1.7 词表口径）
# ---------------------------------------------------------------------------
REDLINE_WORDS = ["筹码", "胜率", "倒数", "断签", "打卡", "进度",
                 "心情曲线", "情绪报告", "记忆成就", "日记打卡"]
REDLINE_RES = [r"第\d+次", r"连续第\d+", r"第\d+周"]


def _assert_no_redline(text: str, where: str) -> None:
    import re
    for w in REDLINE_WORDS:
        assert w not in text, f"[{where}] 红线词 {w!r} 命中: {text[:60]!r}"
    for pat in REDLINE_RES:
        m = re.search(pat, text)
        assert m is None, f"[{where}] 红线表述 {m.group(0)!r} 命中: {text[:60]!r}"


@pytest.fixture
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# ① F4：parse_when 规则解析（全部显式传 now，确定性断言）
# ---------------------------------------------------------------------------
class TestParseWhen:
    NOW = datetime(2026, 9, 9, 10, 0)  # 周三

    def _parse(self, text, now=None):
        from reminders import parse_when
        return parse_when(text, now or self.NOW)

    def test_relative_minutes(self):
        p = self._parse("提醒我20分钟后休息")
        assert p["confidence"] == "high"
        assert p["due_at"] == "2026-09-09T10:20"

    def test_relative_hours_and_half(self):
        p = self._parse("2小时后叫我开会")
        assert p["due_at"] == "2026-09-09T12:00" and p["confidence"] == "high"
        p = self._parse("半小时后取快递")
        assert p["due_at"] == "2026-09-09T10:30"

    def test_relative_days_default_clock(self):
        p = self._parse("提醒我3天后回访")
        assert p["due_at"] == "2026-09-12T09:00" and p["confidence"] == "high"

    def test_tomorrow_period_pm(self):
        p = self._parse("提醒我明天下午3点开会")
        assert p["due_at"] == "2026-09-10T15:00" and p["confidence"] == "high"

    def test_weekday_future_nearest(self):
        # 今天周三：周三晚上8点已过（20:00 > 10:00 未过 → 今天）→ 今天 20:00
        p = self._parse("提醒我周三晚上8点健身")
        assert p["due_at"] == "2026-09-09T20:00"
        # 周一（已过）→ 下周一
        p = self._parse("提醒我周一上午9点例会")
        assert p["due_at"] == "2026-09-14T09:00"

    def test_month_day(self):
        p = self._parse("10月1日上午10点提醒我交报告")
        assert p["due_at"] == "2026-10-01T10:00" and p["confidence"] == "high"

    def test_bare_clock_and_half(self):
        p = self._parse("提醒我14:30开会")
        assert p["due_at"] == "2026-09-09T14:30"
        p = self._parse("记得提醒我后天9点半买票")
        assert p["due_at"] == "2026-09-11T09:30"

    def test_no_clue_default_low_qc3(self):
        p = self._parse("提醒我喝水")
        assert p["confidence"] == "low"
        assert p["due_at"] == "2026-09-10T09:00"  # 今天 09:00 已过 → 明天

    def test_past_today_clock_rolls_tomorrow(self):
        p = self._parse("提醒我8点跑步")  # 今天 08:00 已过
        assert p["due_at"] == "2026-09-10T08:00"

    def test_prefix_strip(self):
        p = self._parse("记得提醒我买牛奶")
        assert p["remind_text"] == "买牛奶"
        p = self._parse("别让我忘了交房租")
        assert p["remind_text"] == "交房租"

    def test_no_redline_in_templates(self):
        from reminders import (build_confirm_text, build_due_bubble,
                               build_overdue_bubble, build_list_text)
        _assert_no_redline(build_confirm_text("2026-09-10T15:00", "开会"), "confirm")
        _assert_no_redline(build_due_bubble("开会"), "due")
        _assert_no_redline(build_overdue_bubble("开会"), "overdue")
        _assert_no_redline(build_list_text(
            [{"due_at": "2026-09-09T15:00", "remind_text": "开会",
              "notified": False}]), "list")


class TestParseLlmWhen:
    NOW = datetime(2026, 9, 9, 10, 0)

    def _parse(self, raw):
        from reminders import parse_llm_when
        return parse_llm_when(raw, self.NOW)

    def test_valid_json(self):
        p = self._parse('{"datetime": "2026-09-10 15:00", "text": "开会"}')
        assert p == {"due_at": "2026-09-10T15:00", "remind_text": "开会"}

    def test_fail_word(self):
        assert self._parse("FAIL") is None

    def test_bad_json(self):
        assert self._parse("明天下午吧") is None
        assert self._parse('{"datetime": "明天15:00", "text": "x"}') is None

    def test_past_time_rejected(self):
        assert self._parse('{"datetime": "2026-09-09 08:00", "text": "x"}') is None

    def test_empty_text_not_crash(self):
        p = self._parse('{"datetime": "2026-09-10 15:00"}')
        assert p is not None and p["remind_text"]


# ---------------------------------------------------------------------------
# ① F4：TodoManager 提醒字段（旧 todos.json 零迁移）
# ---------------------------------------------------------------------------
class TestTodoManagerReminders:
    def _mgr(self, tmp_path):
        from managers import TodoManager
        return TodoManager(str(tmp_path / "todos.json"))

    def test_legacy_items_untouched(self, tmp_path):
        """旧 todos.json（无 due_at 字段）零迁移、不进 due_items。"""
        path = tmp_path / "todos.json"
        path.write_text(json.dumps(
            [{"text": "旧待办", "done": False,
              "created_at": "2026-01-01T08:00:00"}], ensure_ascii=False),
            encoding="utf-8")
        td = self._mgr(tmp_path)
        td.filepath = str(path)
        td._load()
        assert td.due_items() == []
        assert td.items()[0]["text"] == "旧待办"

    def test_add_and_due_flow(self, tmp_path):
        td = self._mgr(tmp_path)
        idx = td.add_reminder("开会", "2026-09-09T09:00")  # 相对 now 已过
        assert idx == 1
        due = td.due_items(datetime(2026, 9, 9, 10, 0))
        assert len(due) == 1 and due[0][0] == 1
        # 未来时刻不触发
        assert td.due_items(datetime(2026, 9, 9, 8, 0)) == []
        td.mark_notified(1)
        assert td.due_items(datetime(2026, 9, 9, 10, 0)) == []

    def test_mark_quiet_pending(self, tmp_path):
        td = self._mgr(tmp_path)
        td.add_reminder("喝水", "2026-09-09T09:00")
        td.mark_quiet_pending(1)
        assert td.items()[0]["quiet_pending"] is True
        assert not td.items()[0].get("notified")

    def test_cancel_reminder(self, tmp_path):
        td = self._mgr(tmp_path)
        td.add_reminder("开会", "2026-09-10T09:00")
        assert td.cancel_reminder(1) is True
        assert td.items() == []
        assert td.cancel_reminder(5) is False

    def test_today_items_sorted(self, tmp_path):
        td = self._mgr(tmp_path)
        td.add_reminder("晚的", "2026-09-09T20:00")
        td.add_reminder("早的", "2026-09-09T08:00")
        items = td.today_items(datetime(2026, 9, 9, 10, 0))
        assert [i["remind_text"] for i in items] == ["早的", "晚的"]


# ---------------------------------------------------------------------------
# ② F4：ReminderScheduler（mock tray notify + screen_bubble）
# ---------------------------------------------------------------------------
class FakeTray:
    def __init__(self):
        self.notifications = []

    def notify_maid(self, title, text):
        self.notifications.append((title, text))


class FakeChatBubbles:
    def __init__(self):
        self.bubbles = []

    def screen_bubble(self, text, scene="screen_notice"):
        self.bubbles.append((text, scene))
        return True


def _sched_ctx(tmp_path, quiet_start="23:00", quiet_end="07:00"):
    from managers import TodoManager
    todo = TodoManager(str(tmp_path / "todos.json"))
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(agent_proactive_quiet_start=quiet_start,
                            agent_proactive_quiet_end=quiet_end),
        session=SimpleNamespace(todo_mgr=todo),
        tray_manager=FakeTray(),
        chat_service=FakeChatBubbles(),
    )
    return ctx, todo


def _freeze_reminders_clock(monkeypatch, moment):
    """把 reminders 模块内的 datetime.now() 固定为 moment（确定性时钟）。

    ReminderScheduler._scan 内部硬读 datetime.now()（reminders.py:478），
    无可注入的 now 形参；故仅在被测模块命名空间替换 `datetime` 名，
    不含任何产品代码改动。固定后 due/quiet 判定均与运行时刻解耦。
    """
    import reminders as _rem
    real_dt = _rem.datetime

    class _FixedDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(_rem, "datetime", _FixedDT)
    return moment


# 固定时钟常量：白天 14:00（非 quiet）/ 深夜 23:30（落在 quiet 23:00–07:00）
_FIXED_DAY = datetime(2026, 9, 9, 14, 0)
_FIXED_NIGHT = datetime(2026, 9, 9, 23, 30)


class TestReminderScheduler:
    def test_due_fires_notify_and_bubble(self, qapp, tmp_path, monkeypatch):
        """到点 → 通知 + 气泡（固定白天时钟 14:00，非 quiet）。"""
        from reminders import ReminderScheduler
        _freeze_reminders_clock(monkeypatch, _FIXED_DAY)  # 固定时钟
        ctx, todo = _sched_ctx(tmp_path)
        todo.add_reminder("取快递", "2026-09-09T09:00")
        sched = ReminderScheduler(ctx)
        sched._scan(overdue=False)
        assert ctx.tray_manager.notifications == [("码铃提醒", "主人，到点的提醒来啦：取快递")]
        assert len(ctx.chat_service.bubbles) == 1
        text, scene = ctx.chat_service.bubbles[0]
        assert scene == "reminder" and "取快递" in text
        _assert_no_redline(text, "reminder_bubble")
        assert todo.items()[0]["notified"] is True

    def test_quiet_degrades_then_delivers_after(self, qapp, tmp_path, monkeypatch):
        """quiet → 只记 pending 不弹不气泡；quiet 结束首个 tick 补气泡不弹通知。

        固定白天时钟 14:00：quiet 由显式 cfg 窗口制造（00:00–23:59），
        与运行时刻无关，两条扫描结果确定。
        """
        from reminders import ReminderScheduler
        _freeze_reminders_clock(monkeypatch, _FIXED_DAY)  # 固定时钟
        ctx, todo = _sched_ctx(tmp_path, quiet_start="00:00", quiet_end="23:59")
        todo.add_reminder("喝水", "2026-09-09T09:00")
        sched = ReminderScheduler(ctx)
        sched._scan(overdue=False)
        assert ctx.tray_manager.notifications == []
        assert ctx.chat_service.bubbles == []
        assert todo.items()[0]["quiet_pending"] is True
        assert not todo.items()[0]["notified"]
        # quiet 结束（cfg 恢复常规）→ 补气泡、不弹通知、恰一次落盘
        ctx.cfg.agent_proactive_quiet_start = "23:00"
        ctx.cfg.agent_proactive_quiet_end = "07:00"
        sched._scan(overdue=False)
        assert ctx.tray_manager.notifications == []  # Q-C4：顺延补看不弹通知
        assert len(ctx.chat_service.bubbles) == 1
        assert todo.items()[0]["notified"] is True

    def test_quiet_by_clock_degrades_at_night(self, qapp, tmp_path, monkeypatch):
        """静默分支（固定深夜时钟 23:30 + 默认 quiet 23:00–07:00）：

        到点提醒走降级顺延 —— 不弹通知、不气泡，只记 quiet_pending。
        """
        from reminders import ReminderScheduler
        _freeze_reminders_clock(monkeypatch, _FIXED_NIGHT)  # 固定深夜时钟
        ctx, todo = _sched_ctx(tmp_path)  # quiet_start=23:00 / quiet_end=07:00
        todo.add_reminder("喝水", "2026-09-09T09:00")
        sched = ReminderScheduler(ctx)
        sched._scan(overdue=False)
        assert ctx.tray_manager.notifications == [], "深夜顺延不弹通知"
        assert ctx.chat_service.bubbles == [], "深夜顺延不气泡"
        assert todo.items()[0]["quiet_pending"] is True
        assert not todo.items()[0]["notified"]

    def test_catch_up_once(self, qapp, tmp_path, monkeypatch):
        """启动补送：文案带"你不在时到点的"，恰一次（固定白天时钟 14:00）。"""
        from reminders import ReminderScheduler
        _freeze_reminders_clock(monkeypatch, _FIXED_DAY)  # 固定时钟
        ctx, todo = _sched_ctx(tmp_path)
        todo.add_reminder("回邮件", "2026-09-08T18:00")
        sched = ReminderScheduler(ctx)
        sched.catch_up()
        assert len(ctx.chat_service.bubbles) == 1
        text, scene = ctx.chat_service.bubbles[0]
        assert "你不在时到点的" in text and "回邮件" in text
        assert scene == "reminder"
        assert todo.items()[0]["notified"] is True
        sched.catch_up()  # 二次 → 零重复
        assert len(ctx.chat_service.bubbles) == 1

    def test_missing_components_ok(self, qapp):
        """无 todo/tray/chat → 静默空转。"""
        from reminders import ReminderScheduler
        sched = ReminderScheduler(SimpleNamespace(cfg=None, session=None,
                                                  tray_manager=None,
                                                  chat_service=None))
        sched._scan(overdue=False)  # 不抛异常


# ---------------------------------------------------------------------------
# ① F4：ChatService 提醒分支（规则直出 / demo 降级 / LLM 兜底入队 / 诚实失败）
# ---------------------------------------------------------------------------
class FakeInnerSession:
    def __init__(self):
        self.history = [{"role": "system", "content": "SYS"}]

    def add_message(self, role, content=None, **kw):
        msg = {"role": role, "content": content}
        msg.update(kw)
        self.history.append(msg)


def _chat_ctx(tmp_path, api_key="sk-test", todo=None):
    from managers import TodoManager
    from gui.chat_service import ChatService
    cfg = SimpleNamespace(
        api_provider="deepseek", api_key=api_key, chat_intent_mode="auto",
        web_search_enabled_gui=False, stream_mode=True, temperature=0.7,
        todos_file=str(tmp_path / "todos.json"),
    )
    sess = FakeInnerSession()
    sess.todo_mgr = todo or TodoManager(str(tmp_path / "todos.json"))
    ctx = SimpleNamespace(
        config=cfg, cfg=cfg,
        session=sess,
        api=MagicMock() if api_key else None,
        intimacy=None, collaborator=None, chat_service=None,
    )
    svc = ChatService(ctx)
    launched = []
    svc._launch_worker = lambda payload: launched.append(payload)  # 遮蔽方法
    return svc, ctx, launched


class TestRemindChatChain:
    def test_high_confidence_local_confirm_zero_llm(self, tmp_path):
        """规则 high → 本地确认句直出（零 LLM、不入发送队列）。"""
        svc, ctx, launched = _chat_ctx(tmp_path)
        assert svc._handle_remind_request("提醒我明天下午3点开会", False) is True
        assert launched == [], "规则命中绝不入 LLM 队列"
        todo = ctx.session.todo_mgr
        assert len(todo.items()) == 1
        # "明天"按真实 now 解析（日期解耦，杜绝跨日假红）
        exp = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") + "T15:00"
        assert todo.items()[0]["due_at"] == exp
        # 用户消息 + 确认句均入会话
        roles = [m["role"] for m in ctx.session.history]
        assert roles == ["system", "user", "assistant"]
        confirm = ctx.session.history[-1]["content"]
        assert "我会提醒你" in confirm and "开会" in confirm
        _assert_no_redline(confirm, "confirm_bubble")

    def test_low_demo_falls_back_to_default_time(self, tmp_path):
        """low + demo（无 api）→ 按明示默认时刻 09:00 登记（Q-C3，非编造）。"""
        svc, ctx, launched = _chat_ctx(tmp_path, api_key="")
        assert svc._handle_remind_request("提醒我喝水", False) is True
        assert launched == []
        todo = ctx.session.todo_mgr
        assert len(todo.items()) == 1
        assert todo.items()[0]["due_at"].endswith("T09:00")
        assert "我会提醒你" in ctx.session.history[-1]["content"]

    def test_low_with_llm_enqueues_remind_parse(self, tmp_path):
        """low + LLM 可用 → remind_parse 专用分支入队。"""
        svc, ctx, launched = _chat_ctx(tmp_path)
        assert svc._handle_remind_request("提醒我下周三之前把报告交了", False) is True
        assert len(launched) == 1
        assert launched[0]["task_type"] == "remind_parse"
        assert launched[0]["text"].startswith("提醒我")
        assert ctx.session.todo_mgr.items() == [], "兜底分支零预写入"

    def test_todo_missing_walks_through(self, tmp_path):
        """todos 单源完全不可用 → 放行走普通聊天（降级不吞消息）。"""
        svc, ctx, launched = _chat_ctx(tmp_path)
        svc._todo_mgr = lambda: None
        assert svc._handle_remind_request("提醒我开会", False) is False

    def test_list_branch_local_template(self, tmp_path):
        svc, ctx, launched = _chat_ctx(tmp_path)
        # 今日条目用真实今天（today_items 按 due_at 日期过滤，写死日期跨日即空）
        ctx.session.todo_mgr.add_reminder(
            "开会", datetime.now().strftime("%Y-%m-%d") + "T15:00")
        assert svc._handle_remind_list("今天有什么安排？", False) is True
        assert launched == []
        bubble = ctx.session.history[-1]["content"]
        assert "开会" in bubble and "15:00" in bubble
        _assert_no_redline(bubble, "list_bubble")


class _Sig:
    """信号替身（PySide6 SignalInstance.emit 只读，实例属性遮蔽）。"""

    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class TestRemindParseWorker:
    """ApiWorker._run_remind_parse：成功登记 / 失败诚实零编造。"""

    def _worker(self, tmp_path, llm_reply, todo):
        import gui.chat_service as cs_mod
        from gui.chat_service import ApiWorker
        cfg = SimpleNamespace(stream_mode=True, temperature=0.7,
                              max_tokens=2048, todos_file=str(tmp_path / "t.json"))
        ctx = SimpleNamespace(cfg=cfg, config=cfg,
                              session=SimpleNamespace(todo_mgr=todo),
                              api=None, intimacy=None, collaborator=None)
        api = MagicMock()
        api.chat.return_value = {"choices": [{"message": {"content": llm_reply}}]}
        task_config = {"task_type": "remind_parse", "user_text": "提醒我明天三点开会"}
        worker = ApiWorker(api, [], task_config, ctx)
        for name in ("message_stream_started", "message_stream_finished",
                     "message_failed", "thinking_indicator"):
            setattr(worker, name, _Sig())
        return worker, worker.message_stream_finished.calls

    def test_llm_success_registers(self, tmp_path):
        from managers import TodoManager
        todo = TodoManager(str(tmp_path / "todos.json"))
        # v1.8 三批回归修复：原硬编码 "2026-09-10 15:00" 在当日 15:00 后运行
        # 必然落入 parse_llm_when 的过去拒绝窗（D-V17-03 零编造口径）——改为
        # 动态未来时刻，消除时间依赖。
        from datetime import datetime, timedelta
        future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        reply = json.dumps({"datetime": future, "text": "开会"},
                           ensure_ascii=False)
        worker, emits = self._worker(tmp_path, reply, todo)
        worker._run_remind_parse()
        assert len(todo.items()) == 1
        assert todo.items()[0]["due_at"] == future.replace(" ", "T")
        text, _ = emits[-1]
        assert "我会提醒你" in text

    def test_llm_fail_honest_zero_write(self, tmp_path):
        """LLM 兜底失败 → 确定性诚实话术，零 due_at 写入（零编造断言）。"""
        from managers import TodoManager
        from reminders import REMIND_FAIL_TEXT
        for reply in ("FAIL", "明天下午吧", '{"datetime": "错的", "text": "x"}'):
            todo = TodoManager(str(tmp_path / f"t{abs(hash(reply))}.json"))
            worker, emits = self._worker(tmp_path, reply, todo)
            worker._run_remind_parse()
            assert todo.items() == [], f"失败路径零写入: {reply!r}"
            text, _ = emits[-1]
            assert text == REMIND_FAIL_TEXT  # 常量一致性：无任何猜测时间被登记

    def test_llm_network_error_honest(self, tmp_path):
        from managers import TodoManager
        from reminders import REMIND_FAIL_TEXT
        todo = TodoManager(str(tmp_path / "todos.json"))
        worker, emits = self._worker(tmp_path, "ok", todo)
        worker._api.chat.side_effect = RuntimeError("network down")
        worker._run_remind_parse()
        assert todo.items() == []
        assert emits[-1][0] == REMIND_FAIL_TEXT


# ---------------------------------------------------------------------------
# ③④⑤ F7：DiaryManager / payload R-I / should_write / 365 滚动
# ---------------------------------------------------------------------------
def _diary(tmp_path):
    from diary import DiaryManager
    return DiaryManager(filepath=tmp_path / "diaries.json")


class TestDiaryManager:
    def test_add_and_idempotent(self, tmp_path):
        d = _diary(tmp_path)
        assert d.add_entry("2026-09-08", "码铃", "平静", "昨天陪主人写了代码。") is True
        assert d.add_entry("2026-09-08", "码铃", "平静", "重复写") is False  # 同 date 幂等
        assert d.has_entry("2026-09-08")
        assert d.list_entries()[0]["date"] == "2026-09-08"

    def test_empty_content_rejected(self, tmp_path):
        """绝不落占位假日记。"""
        d = _diary(tmp_path)
        assert d.add_entry("2026-09-08", "码铃", "平静", "  ") is False
        assert d.list_entries() == []

    def test_list_desc_order(self, tmp_path):
        d = _diary(tmp_path)
        for day in ("2026-09-01", "2026-09-09", "2026-09-05"):
            d.add_entry(day, "码铃", "平静", f"日记{day}")
        assert [e["date"] for e in d.list_entries()] == [
            "2026-09-09", "2026-09-05", "2026-09-01"]

    def test_prune_365_rolling(self, tmp_path):
        """⑤ 365 篇滚动裁剪：最旧淘汰、最新保留。"""
        d = _diary(tmp_path)
        base = datetime(2025, 9, 9)
        for i in range(400):
            day = (base + timedelta(days=i)).strftime("%Y-%m-%d")
            d.add_entry(day, "码铃", "平静", f"第{i}篇的内容")
        entries = d.list_entries()
        assert len(entries) == 365
        assert entries[0]["date"] == (base + timedelta(days=399)).strftime("%Y-%m-%d")
        assert entries[-1]["date"] == (base + timedelta(days=35)).strftime("%Y-%m-%d")

    def test_export_markdown(self, tmp_path):
        d = _diary(tmp_path)
        d.add_entry("2026-09-08", "码铃", "平静", "昨天陪主人写了代码。")
        out = d.export_markdown(str(tmp_path / "export" / "她的日记.md"))
        text = Path(out).read_text(encoding="utf-8")
        assert "## 2026-09-08" in text and "陪主人写了代码" in text


class _FakeMemory:
    """含对话原文的 memory 替身——断言 payload 绝不带走原文（R-I）。"""
    CONVERSATION = ("主人说：我今天的密码是 abc123456，帮我记住，别告诉别人。"
                    "这是很长很长的对话原文，包含隐私内容。")

    def get_active_topics(self):
        return [{"subject": "项目重构", "last_mentioned": "2026-09-08T10:00:00"}]

    def get_archived_topics(self):
        return [{"subject": "搬家", "completed_at": "2026-09-08T18:00:00"}]

    def get_emotions_history(self):
        return [{"emotion": "happy", "ts": "2026-09-08T12:00:00"}]

    def get_recent_messages(self, n=50):
        return [{"role": "user", "content": self.CONVERSATION}]


class _FakeHighlights:
    def query_range(self, start, end):
        if start <= "2026-09-08" <= end:
            return [{"date": "2026-09-08", "text": "解决了登录 bug"}]
        return []


class TestDiaryPayloadRI:
    DAY = "2026-09-08"

    def _payload(self, memory=None, highlights=None):
        from diary import build_diary_payload
        return build_diary_payload(memory_mgr=memory or _FakeMemory(),
                                   highlights_mgr=highlights or _FakeHighlights(),
                                   companion=None, date=self.DAY, role_name="码铃")

    def test_payload_whitelist_keys(self):
        """④ payload 键白名单（R-I 断言面）。"""
        from diary import PAYLOAD_KEYS
        payload = self._payload()
        assert set(payload.keys()) <= PAYLOAD_KEYS
        # 无任何对话/消息类键
        forbidden = {"messages", "history", "conversation", "raw", "dialog"}
        assert not (set(payload.keys()) & forbidden)

    def test_payload_no_conversation_content(self):
        """④ 对话原文绝不进 payload。"""
        payload = self._payload()
        blob = json.dumps(payload, ensure_ascii=False)
        assert "abc123456" not in blob, "对话原文（含隐私）泄漏进 payload"
        assert "别告诉别人" not in blob
        # 要点类字段正常在
        assert payload["highlights"] == ["解决了登录 bug"]
        assert payload["new_topics"] == ["项目重构"]
        assert payload["done_topics"] == ["搬家"]

    def test_mood_and_volume_words(self):
        payload = self._payload()
        assert payload["mood_word"] == "开心"
        assert payload["volume_word"] in ("安静的一天", "平常的一天", "热闹的一天")
        import re
        assert not re.search(r"\d", payload["volume_word"] + payload["mood_word"])

    def test_should_write_semantics(self, tmp_path):
        from diary import should_write
        d = _diary(tmp_path)
        payload = self._payload()
        assert should_write(d, payload) is True          # 有内容未写
        d.add_entry(self.DAY, "码铃", "平静", "写好了")
        assert should_write(d, payload) is False         # 已写 → 幂等
        empty = dict(payload, highlights=[], new_topics=[], done_topics=[])
        assert should_write(d, empty) is False           # 无内容不写

    def test_prompt_no_redline_and_tone(self):
        from diary import build_diary_prompt
        payload = self._payload()
        p1 = build_diary_prompt(payload, stage="亲近")
        assert "亲近" in p1 and "100–200 字" in p1
        _assert_no_redline(p1, "diary_prompt")
        p2 = build_diary_prompt(payload, stage="信赖", diary_tone=True)
        assert "更软更亲近" in p2  # F5 特权表消费（信赖 → 日记口吻更亲密）


# ---------------------------------------------------------------------------
# ③ F7：_diary_worker 次日补写（触发 + 幂等 + 失败静默）
# ---------------------------------------------------------------------------
class _EmptyHighlights:
    def query_range(self, start, end):
        return []


class TestDiaryWorker:
    def _ctx(self, tmp_path, llm_reply="昨天我们解决了登录 bug，主人很开心。"):
        from diary import DiaryManager
        from intimacy import IntimacyTracker
        tracker = IntimacyTracker(filepath=str(tmp_path / "intimacy.json"))
        tracker._data["score"] = 150  # 信赖 → diary_tone 特权
        ctx = SimpleNamespace(
            config=SimpleNamespace(diary_enabled=True),
            diary=DiaryManager(filepath=tmp_path / "diaries.json"),
            session=SimpleNamespace(memory_mgr=_FakeMemory()),
            companion=None,
            intimacy=tracker,
            api=MagicMock(),
        )
        ctx.api.chat.return_value = {
            "choices": [{"message": {"content": llm_reply}}]}
        return ctx

    @staticmethod
    def _stub_role(monkeypatch):
        """隔离真实 ~/.maid_coder/roles（RoleManager 只读也避免环境依赖）。"""
        import gui.pages.page_role as pr
        fake_mgr = MagicMock()
        fake_mgr.default_role = SimpleNamespace(name="码铃")
        monkeypatch.setattr(pr, "RoleManager", lambda: fake_mgr)

    @staticmethod
    def _freeze_diary_clock(monkeypatch):
        """diary 模块时钟固定 2026-09-09（昨日=09-08，与 _Fake* 桩数据对齐）。

        _diary_worker → build_diary_payload 用真实 now()-1d 算"昨日"，
        而桩数据写死 2026-09-08——跨日运行（09-10 起）必空转假红。
        """
        import diary as _diary_mod

        class _FixedDT(_diary_mod.datetime):
            @classmethod
            def now(cls):
                return _diary_mod.datetime(2026, 9, 9, 12, 0)
        monkeypatch.setattr(_diary_mod, "datetime", _FixedDT)

    def test_worker_writes_yesterday(self, tmp_path, monkeypatch):
        """③ 次日启动补写昨日：payload 组装 → api.chat → add_entry。"""
        import gui.main as gm
        self._freeze_diary_clock(monkeypatch)
        monkeypatch.setattr("gui.pages.page_memories.get_highlights_manager",
                            lambda ctx: _FakeHighlights(), raising=False)
        self._stub_role(monkeypatch)
        ctx = self._ctx(tmp_path)
        gm._diary_worker(ctx)
        entries = ctx.diary.list_entries()
        assert len(entries) == 1
        assert entries[0]["date"] == "2026-09-08"  # 冻结时钟(09-09)的昨日
        assert entries[0]["content"]  # 真实内容，非占位
        # 提示词带信赖口吻特权（F5 勾稽）
        prompt = ctx.api.chat.call_args[0][0][0]["content"]
        assert "更软更亲近" in prompt

    def test_worker_idempotent(self, tmp_path, monkeypatch):
        """③ 已写过 → 再跑不重写。"""
        import gui.main as gm
        self._freeze_diary_clock(monkeypatch)
        monkeypatch.setattr("gui.pages.page_memories.get_highlights_manager",
                            lambda ctx: _FakeHighlights(), raising=False)
        self._stub_role(monkeypatch)
        ctx = self._ctx(tmp_path)
        gm._diary_worker(ctx)
        gm._diary_worker(ctx)
        assert len(ctx.diary.list_entries()) == 1

    def test_worker_silent_on_llm_fail(self, tmp_path, monkeypatch):
        """③ 失败静默（should_write 仍 True 自然重试），绝不落占位。"""
        import gui.main as gm
        monkeypatch.setattr("gui.pages.page_memories.get_highlights_manager",
                            lambda ctx: _FakeHighlights(), raising=False)
        self._stub_role(monkeypatch)
        ctx = self._ctx(tmp_path, llm_reply="")
        gm._diary_worker(ctx)
        assert ctx.diary.list_entries() == []

    def test_worker_skips_empty_day(self, tmp_path, monkeypatch):
        """昨日无内容 → 不调 LLM 不写。"""
        import gui.main as gm
        monkeypatch.setattr("gui.pages.page_memories.get_highlights_manager",
                            lambda ctx: _EmptyHighlights(), raising=False)
        self._stub_role(monkeypatch)
        ctx = self._ctx(tmp_path)
        ctx.session.memory_mgr = SimpleNamespace(  # 全空数据源
            get_active_topics=lambda: [], get_archived_topics=lambda: [],
            get_emotions_history=lambda: [])
        gm._diary_worker(ctx)
        assert ctx.diary.list_entries() == []
        ctx.api.chat.assert_not_called()

    def test_init_diary_disabled(self, tmp_path):
        """Q-C2：diary_enabled=False → 静默跳过。"""
        import gui.main as gm
        ctx = self._ctx(tmp_path)
        ctx.config.diary_enabled = False
        assert gm._init_diary(ctx) is False
        assert getattr(ctx, "diary_thread", None) is None


# ---------------------------------------------------------------------------
# ⑥ F7：page_memory_book 日记 Tab（offscreen 构造 + 翻阅）
# ---------------------------------------------------------------------------
class TestDiaryTab:
    def _page(self, tmp_path, entries=(("2026-09-08", "平静", "日记一"),
                                       ("2026-09-01", "开心", "日记二"),
                                       ("2026-08-20", "", "日记三"))):
        from PySide6.QtWidgets import QApplication
        from gui.pages.page_memory_book import PageMemoryBook
        from diary import DiaryManager
        QApplication.instance() or QApplication([])
        d = DiaryManager(filepath=tmp_path / "diaries.json")
        for date, mood, content in entries:
            d.add_entry(date, "码铃", mood, content)
        ctx = SimpleNamespace(session=None, diary=d)
        page = PageMemoryBook(ctx)
        return page, d

    def _all_texts(self, page):
        """收集所有卡片文本（顶层 QLabel + _EntryCard 内部 QLabel）。"""
        from gui.qt_compat import QLabel
        texts = []
        for w in page._list_widgets:
            if hasattr(w, "text"):
                texts.append(w.text())
            for lab in w.findChildren(QLabel):
                texts.append(lab.text())
        return "\n".join(texts)

    def test_tab_construct_and_browse(self, tmp_path):
        """⑥ 第 5 分区「她的日记」：按月分组倒序翻阅。"""
        page, d = self._page(tmp_path)
        # v1.8(D-V18-09): 分区满 8（+人物关系/回应约定/共同经历），日记第 8 位
        assert page.tabs.count() == 8
        assert page.tabs.tabText(7) == "她的日记"
        joined = self._all_texts(page)
        assert "日记一" in joined and "日记二" in joined and "日记三" in joined
        assert "9 月" in joined and "8 月" in joined  # 按月分组
        assert "心情：平静" in joined
        # 倒序：日记一（09-08）在日记二（09-01）之前
        assert joined.index("日记一") < joined.index("日记二")

    def test_tab_refresh_idempotent(self, tmp_path):
        page, d = self._page(tmp_path)
        n = len(page._list_widgets)
        page.refresh()
        assert len(page._list_widgets) == n  # 不重复插卡

    def test_tab_empty_state(self, tmp_path):
        from PySide6.QtWidgets import QApplication
        from gui.pages.page_memory_book import PageMemoryBook
        from diary import DiaryManager
        QApplication.instance() or QApplication([])
        ctx = SimpleNamespace(session=None,
                              diary=DiaryManager(filepath=tmp_path / "e.json"))
        page = PageMemoryBook(ctx)
        texts = "\n".join(w.text() for w in page._list_widgets if hasattr(w, "text"))
        assert "还没有日记" in texts
