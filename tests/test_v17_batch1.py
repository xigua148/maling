# -*- coding: utf-8 -*-
"""v1.7 第一批测试（F5 关系阶段叙事 D-V17-04 + F3 时段仪式感 D-V17-02）。

覆盖（team-lead 指定四类针对性）：
- ① 阶段表映射与升级恰一次播报（notified_stage 持久化 + 重启不重播 +
    非升级不播 + 计分死路径回退修复）；
- ② 早安/午后/晚安三通道触发与 quiet 降级（ritual.json 按日限次、错过不补）；
- ③ 语录库加载（≥200 条 4+1 池）与每日一句（md5 稳定哈希当日确定 + 阶段加权）；
- ④ R-A 扫描词表新 4 词（心情曲线/情绪报告/记忆成就/日记打卡）+ 旧词全量零命中。

隔离：intimacy/ritual 全部 filepath=tmp_path；Qt 走 offscreen；零真实 ~/.maid_coder。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import intimacy as intimacy_mod  # noqa: E402
import quotations as quotations_mod  # noqa: E402
import greeting as greeting_mod  # noqa: E402
from intimacy import IntimacyTracker  # noqa: E402
from quotations import (  # noqa: E402
    RitualStore, goodnight_due, pick_quote,
)

# R-A 扫描词表：旧 6 词 + v1.7 新 4 词（design §9 / prd §10.10）
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


def _tracker(tmp_path, score=0, level=0):
    t = IntimacyTracker(filepath=str(tmp_path / "intimacy.json"))
    t._data["score"] = score
    t._data["level"] = t._get_level_info(score)["level"]
    return t


# ---------------------------------------------------------------------------
# ① F5：阶段表映射
# ---------------------------------------------------------------------------
class TestStageMapping:
    @pytest.mark.parametrize("score,name,level", [
        (0, "初识", 0), (9, "初识", 0),
        (10, "熟悉", 1), (49, "熟悉", 1),
        (50, "亲近", 2), (149, "亲近", 2),
        (150, "信赖", 3),
    ])
    def test_level_mapping(self, tmp_path, score, name, level):
        t = _tracker(tmp_path, score=score)
        assert t.level_name() == name
        assert t.level == level

    def test_privilege_table_keys(self, tmp_path):
        # Q-C9：全表无「闲聊话术变体」键
        for lvl, priv in intimacy_mod._STAGE_PRIVILEGES.items():
            assert set(priv.keys()) == {"address_style", "goodnight_variant",
                                        "diary_tone", "quote_pool_weight"}, \
                f"level {lvl} 特权键异常（不得出现闲聊话术变体）"

    @pytest.mark.parametrize("lvl,address,gn,diary,weight", [
        (0, "您", False, False, "plain"),
        (1, "你", False, False, "warm"),
        (2, "你", True, False, "warm"),
        (3, "你", True, True, "intimate"),
    ])
    def test_privilege_values(self, tmp_path, lvl, address, gn, diary, weight):
        t = _tracker(tmp_path)
        priv = t.stage_privileges(lvl)
        assert priv["address_style"] == address
        assert priv["goodnight_variant"] is gn
        assert priv["diary_tone"] is diary
        assert priv["quote_pool_weight"] == weight

    def test_stage_prompt_staged(self, tmp_path):
        t = _tracker(tmp_path, score=0)
        p0 = t.build_intimacy_prompt()
        assert "【关系阶段】初识" in p0 and "您" in p0
        assert "Lv" not in p0, "system 侧也不暴露 Lv 数值语义"
        t2 = _tracker(tmp_path, score=150)
        p3 = t2.build_intimacy_prompt()
        assert "【关系阶段】信赖" in p3 and "你" in p3
        assert "生动" in p3 and "软" in p3  # 信赖阶段特权说明
        _assert_no_redline(p0, "stage_prompt_0")
        _assert_no_redline(p3, "stage_prompt_3")

    def test_stage_announcement_no_numbers(self, tmp_path):
        t = _tracker(tmp_path, score=150)
        text = t.stage_announcement(3)
        assert "信赖" in text
        import re
        assert not re.search(r"\d", text), "播报句模板不得含数值位"


# ---------------------------------------------------------------------------
# ① F5：notified_stage 持久化 + 升级播报恰一次
# ---------------------------------------------------------------------------
class FakeInnerSession:
    def __init__(self):
        self.history = [{"role": "system", "content": "SYS"}]

    def add_message(self, role, content=None, **kw):
        msg = {"role": role, "content": content}
        msg.update(kw)
        self.history.append(msg)


class FakeConfig:
    api_provider = "deepseek"
    api_key = "sk-test"          # 非 demo
    chat_intent_mode = "auto"
    web_search_enabled_gui = False
    stream_mode = True
    temperature = 0.7
    scene_auto = False   # v1.8(V18-12/D-V18-07): 本文件为 v1.7 语义基线——场景关，
                         # 睡前/NIGHT_CARE 合并判定不生效，深夜关怀按 v1.7 原样验证


class FakeCtx:
    def __init__(self, tracker, tmp_path):
        self.config = FakeConfig()
        self.session = FakeInnerSession()
        self.api = MagicMock()
        self.intimacy = tracker
        self.collaborator = None    # 实测 MultiModelCollaborator 无 bump_intimacy
        self.chat_service = None


def _service(tmp_path, tracker):
    from gui.chat_service import ChatService
    return ChatService(FakeCtx(tracker, tmp_path))


class TestStageUpAnnounce:
    def test_upgrade_announces_exactly_once(self, tmp_path):
        t = _tracker(tmp_path, score=149, level=2)   # 亲近，再 +1 即升级信赖
        svc = _service(tmp_path, t)
        svc._current_user_text = "谢谢主人"
        svc._bump_intimacy_after_reply()
        # 升级播报进了会话（proactive assistant 气泡）
        announced = [m for m in svc._app_ctx.session.history
                     if m.get("role") == "assistant"]
        assert any("信赖" in str(m.get("content")) for m in announced), \
            f"升级后应播报一次: {[m.get('content') for m in announced]}"
        assert t.notified_stage == 3, "投递成功后 notified_stage 落盘"
        # 恰一次：继续对话同阶段不重播
        n_before = len(announced)
        svc._bump_intimacy_after_reply()
        announced2 = [m for m in svc._app_ctx.session.history
                      if m.get("role") == "assistant"]
        assert len(announced2) == n_before, "同阶段继续对话不得重复播报"

    def test_notified_stage_persists_no_replay_on_restart(self, tmp_path):
        t = _tracker(tmp_path, score=149, level=2)
        svc = _service(tmp_path, t)
        svc._current_user_text = "嗯"
        svc._bump_intimacy_after_reply()
        assert t.notified_stage == 3
        # 重启：新 tracker（同文件）+ 新 service，分数再涨但阶段不升级
        t2 = IntimacyTracker(filepath=str(tmp_path / "intimacy.json"))
        assert t2.notified_stage == 3, "notified_stage 应持久化"
        svc2 = _service(tmp_path, t2)
        svc2._current_user_text = "嗯"
        svc2._bump_intimacy_after_reply()
        texts = [str(m.get("content")) for m in svc2._app_ctx.session.history
                 if m.get("role") == "assistant"]
        assert not any("更亲近了" in x for x in texts), "重启后不得重播"

    def test_no_announce_without_real_upgrade(self, tmp_path):
        # 初识态首聊（level 0 → 0）：不是升级事件，不播（防「初识」噪音播报）
        t = _tracker(tmp_path, score=0, level=0)
        svc = _service(tmp_path, t)
        svc._current_user_text = "在吗"
        svc._bump_intimacy_after_reply()
        assert t.notified_stage == -1, "未升级不记账"
        texts = [str(m.get("content")) for m in svc._app_ctx.session.history
                 if m.get("role") == "assistant"]
        assert not any("更亲近了" in x for x in texts)

    def test_dead_scoring_path_fallback(self, tmp_path):
        # 计分链死路径修复：collaborator 无 bump_intimacy → 回落 _bump_intimacy
        t = _tracker(tmp_path, score=0, level=0)
        svc = _service(tmp_path, t)
        assert svc._app_ctx.collaborator is None
        before = t.score
        svc._current_user_text = "你好"
        svc._bump_intimacy_after_reply()
        assert t.score > before, "collab 缺失时应回落到 v10.15 计分路径"


# ---------------------------------------------------------------------------
# ③ F3：语录库加载 + 每日一句
# ---------------------------------------------------------------------------
class TestQuotationLibrary:
    def test_library_loaded_200_plus(self):
        pools = quotations_mod._load_pools()
        total = sum(len(v) for v in pools.values())
        assert total >= 200, f"语录库应 ≥200 条，实得 {total}"
        for key in ("morning", "afternoon", "night", "all", "intimate"):
            assert pools.get(key), f"缺池 {key}"
            for q in pools[key]:
                assert isinstance(q, str) and q.strip()

    def test_asset_json_no_redline(self):
        path = ROOT / "gui" / "assets" / "quotations.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for pool, items in data.items():
            for q in items:
                _assert_no_redline(q, f"quotations[{pool}]")

    def test_pick_quote_deterministic(self):
        a = pick_quote("2026-09-09", "morning", "plain")
        b = pick_quote("2026-09-09", "morning", "plain")
        assert a == b, "同日同槽必须稳定（当日确定）"
        assert pick_quote("2026-09-10", "morning", "plain") == \
            pick_quote("2026-09-10", "morning", "plain")

    def test_pick_quote_weighting(self):
        pools = {
            "morning": [f"普通晨{i}" for i in range(20)],
            "afternoon": [f"普通午{i}" for i in range(20)],
            "night": [f"普通夜{i}" for i in range(20)],
            "all": [f"通用{i}" for i in range(20)],
            "intimate": [f"亲昵{i}" for i in range(20)],
        }
        base = set(pools["morning"]) | set(pools["all"])
        intimate = set(pools["intimate"])
        # plain：永不进亲昵池
        for d in range(60):
            q = pick_quote(f"2027-01-{(d % 28) + 1:02d}", "morning", "plain", pools)
            assert q in base, f"plain 档命中亲昵池: {q}"
        # intimate：约 2/3 命中亲昵池（确定性比例，容差断言）
        hit = sum(1 for d in range(60)
                  if pick_quote(f"2027-02-{(d % 28) + 1:02d}", "morning",
                                "intimate", pools) in intimate)
        assert 30 <= hit <= 55, f"intimate 加权比例异常: {hit}/60"
        # warm：约 1/2
        hit_w = sum(1 for d in range(60)
                    if pick_quote(f"2027-03-{(d % 28) + 1:02d}", "morning",
                                  "warm", pools) in intimate)
        assert 20 <= hit_w <= 40, f"warm 加权比例异常: {hit_w}/60"


class TestRitualStore:
    def test_given_mark_and_daily_reset(self, tmp_path):
        store = RitualStore(filepath=tmp_path / "ritual.json")
        day1 = datetime(2026, 9, 9, 8, 0)
        day2 = datetime(2026, 9, 10, 9, 0)
        assert not store.given("morning", day1)
        store.mark_given("morning", "晨光语录", day1)
        assert store.given("morning", day1)
        assert store.quote_of("morning") == "晨光语录"
        # 跨日重置：date != today 即清（按日限次的天然保证）
        assert not store.given("morning", day2), "跨日必须重置"
        assert store.quote_of("morning") is None

    def test_persistence(self, tmp_path):
        p = tmp_path / "ritual.json"
        s1 = RitualStore(filepath=p)
        s1.mark_given("afternoon", "午后语录", datetime(2026, 9, 9, 15, 0))
        s2 = RitualStore(filepath=p)
        assert s2.given("afternoon", datetime(2026, 9, 9, 16, 0))
        assert s2.quote_of("afternoon") == "午后语录"

    def test_goodnight_due(self, tmp_path):
        store = RitualStore(filepath=tmp_path / "ritual.json")
        night = datetime(2026, 9, 9, 23, 30)
        day = datetime(2026, 9, 9, 15, 0)
        assert not goodnight_due(day, store, True), "非深夜不触发"
        assert not goodnight_due(night, store, False), "开关关不触发"
        assert goodnight_due(night, store, True)
        store.mark_given("goodnight", None, night)
        assert not goodnight_due(night, store, True), "当日已发不再触发"


# ---------------------------------------------------------------------------
# ② F3：三个纯函数（greeting 增量，_TIME_PERIODS 零改动）
# ---------------------------------------------------------------------------
class TestGreetingBuilders:
    def test_morning_ritual(self):
        line = greeting_mod.build_morning_ritual("今日语录甲", "小远", "熟悉")
        assert "早安" in line and "小远" in line and "今日语录甲" in line
        assert "你" in line
        line0 = greeting_mod.build_morning_ritual("今日语录乙", "主人", "初识")
        assert "您" in line0
        _assert_no_redline(line, "morning_ritual")

    def test_afternoon_line(self):
        line = greeting_mod.build_afternoon_line("午后语录")
        assert "午后语录" in line
        _assert_no_redline(line, "afternoon_line")

    def test_goodnight_variants_by_stage(self):
        clingy = set(greeting_mod._GOODNIGHT_CLINGY)
        gentle = set(greeting_mod._GOODNIGHT_GENTLE)
        for stage in ("亲近", "信赖"):
            for _ in range(10):
                assert greeting_mod.build_goodnight_line(stage) in clingy
        for stage in ("初识", "熟悉"):
            for _ in range(10):
                assert greeting_mod.build_goodnight_line(stage) in gentle
        for line in clingy | gentle:
            _assert_no_redline(line, "goodnight")
        # 撒娇式必须带 💕（可感知差异）
        assert all("💕" in x for x in clingy)


# ---------------------------------------------------------------------------
# ② F3：午后检查点 + 早安编排（scheduler 接线，窗口/quiet/按日限次）
# ---------------------------------------------------------------------------
class FakeCompanion:
    def relation_stage_name(self):
        return "熟悉"


class FakeChatService:
    def __init__(self):
        self.delivered = []
        self.busy = False

    def is_busy(self):
        return self.busy

    def proactive_ask(self, text, scene="idle_hello", subject=""):
        self.delivered.append((text, scene, subject))
        return True


class FakeSchedulerCfg:
    agent_proactive_enabled = True
    agent_proactive_quiet_start = "23:00"
    agent_proactive_quiet_end = "07:00"
    agent_proactive_daily_cap = 3
    api_key = "sk-test"
    api_provider = "deepseek"


def _sched_ctx(tmp_path, tracker=None):
    ctx = SimpleNamespace()
    ctx.cfg = FakeSchedulerCfg()
    ctx.config = FakeSchedulerCfg()
    ctx.companion = FakeCompanion()
    ctx.chat_service = FakeChatService()
    ctx.session = SimpleNamespace(
        memory_mgr=SimpleNamespace(get_preference=lambda k: "小远"),
        todo_mgr=None)
    ctx.intimacy = tracker or _tracker(tmp_path)
    ctx.ritual_store = RitualStore(filepath=tmp_path / "ritual.json")
    return ctx


@pytest.fixture
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeDT:
    """datetime 替身：固定 now()，其余透传真实 datetime。"""
    target = datetime(2026, 9, 9, 15, 0)

    @classmethod
    def now(cls):
        return cls.target

    def __getattr__(self, name):
        return getattr(datetime, name)


@pytest.fixture
def fake_clock(monkeypatch):
    import gui.proactive_scheduler as ps
    monkeypatch.setattr(ps, "datetime", _FakeDT)
    return _FakeDT


def _today_at(h, m=0):
    """假时钟同日化：date 取真实今天。

    fake_clock 只替换 scheduler 模块的 datetime，而 RitualStore（quotations）
    内部用真实 datetime.now() 做跨日重置——若假时钟日期 ≠ 真实日期，
    mark/given 两次 ensure_today 互相清账导致断言漂移（2026-09-10 起暴露）。
    统一取真实日期 + 指定时刻即可两侧一致。
    """
    return datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)


class TestAfternoonRitual:
    def test_in_window_delivers_and_marks(self, qapp, tmp_path, fake_clock, monkeypatch):
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        sched = ProactiveScheduler(ctx)
        fake_clock.target = _today_at(15)
        assert sched.maybe_afternoon_ritual() == "afternoon_ritual"
        text, scene, subject = ctx.chat_service.delivered[-1]
        assert scene == "afternoon_ritual" and "：" in text
        assert ctx.ritual_store.given("afternoon", _today_at(15))
        _assert_no_redline(text, "afternoon_ritual")
        # 按日限次：当日第二次 → None
        assert sched.maybe_afternoon_ritual() is None
        assert len(ctx.chat_service.delivered) == 1

    def test_out_of_window_missed_no_makeup(self, qapp, tmp_path, fake_clock):
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        sched = ProactiveScheduler(ctx)
        fake_clock.target = datetime(2026, 9, 9, 13, 59)
        assert sched.maybe_afternoon_ritual() is None
        fake_clock.target = datetime(2026, 9, 9, 17, 0)
        assert sched.maybe_afternoon_ritual() is None
        assert not ctx.ritual_store.given("afternoon", datetime(2026, 9, 9, 18, 0))

    def test_quiet_hours_degrades(self, qapp, tmp_path, fake_clock):
        # quiet 降级：窗口内但 quiet 覆盖（quiet_start=14:00, end=16:00）
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        ctx.cfg.agent_proactive_quiet_start = "14:00"
        ctx.cfg.agent_proactive_quiet_end = "16:00"
        sched = ProactiveScheduler(ctx)
        fake_clock.target = datetime(2026, 9, 9, 15, 0)
        assert sched.maybe_afternoon_ritual() is None
        assert not ctx.ritual_store.given("afternoon", datetime(2026, 9, 9, 15, 0))

    def test_busy_degrades(self, qapp, tmp_path, fake_clock):
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        ctx.chat_service.busy = True
        sched = ProactiveScheduler(ctx)
        fake_clock.target = datetime(2026, 9, 9, 15, 0)
        assert sched.maybe_afternoon_ritual() is None


class TestMorningRitualLine:
    def test_in_window_builds(self, qapp, tmp_path, fake_clock):
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        sched = ProactiveScheduler(ctx)
        fake_clock.target = _today_at(9)
        line = sched._morning_ritual_line()
        assert line is not None
        assert "早安" in line and "小远" in line and "：" in line
        _assert_no_redline(line, "morning_ritual_line")
        # 投递成功后记账 → 当日不再给
        sched._mark_morning_ritual()
        assert ctx.ritual_store.given("morning", _today_at(9, 30))
        assert sched._morning_ritual_line() is None

    def test_out_of_window_none(self, qapp, tmp_path, fake_clock):
        from gui.proactive_scheduler import ProactiveScheduler
        sched = ProactiveScheduler(_sched_ctx(tmp_path))
        fake_clock.target = datetime(2026, 9, 9, 12, 0)
        assert sched._morning_ritual_line() is None

    def test_stage_weight_consumed(self, qapp, tmp_path, fake_clock):
        # F5→F3 联动：信赖阶段 quote_pool_weight=intimate → 亲昵子池优先
        from gui.proactive_scheduler import ProactiveScheduler
        ctx = _sched_ctx(tmp_path)
        tracker = ctx.intimacy
        tracker._data["score"] = 150
        ctx.companion = SimpleNamespace(relation_stage_name=lambda: "信赖")
        sched = ProactiveScheduler(ctx)
        fake_clock.target = datetime(2026, 9, 9, 8, 0)
        line = sched._morning_ritual_line()
        assert line is not None  # 加权不改变可用性


# ---------------------------------------------------------------------------
# ② F3：深夜对话尾注（request_injections 机制复用，零新机制）
# ---------------------------------------------------------------------------
class TestNightCareInjection:
    def _launch(self, monkeypatch, tmp_path, hour):
        import gui.chat_service as cs_mod
        from gui.chat_service import ChatService, NIGHT_CARE_INJECTION

        class _AnyCall:
            def __getattr__(self, name):
                return self

            def __call__(self, *a, **k):
                return None

        class _Worker:
            captured = {}

            def __init__(self, api, messages, task_config, app_ctx,
                         on_session_used=None, expr_filter=False):
                type(self).captured = {"messages": messages}

            def __getattr__(self, name):
                return _AnyCall()

        class _FakeDT:
            target = datetime(2026, 9, 9, hour, 0)

            @classmethod
            def now(cls):
                return cls.target

            @staticmethod
            def fromisoformat(s):
                return datetime.fromisoformat(s)

            @staticmethod
            def fromtimestamp(ts):
                return datetime.fromtimestamp(ts)

            @staticmethod
            def strptime(s, f):
                return datetime.strptime(s, f)

        monkeypatch.setattr(cs_mod, "ApiWorker", _Worker)
        monkeypatch.setattr(cs_mod, "datetime", _FakeDT)
        tracker = IntimacyTracker(filepath=str(tmp_path / "i.json"))
        ctx = FakeCtx(tracker, tmp_path)
        svc = ChatService(ctx)
        svc.send_message("继续写这段代码", suppress_echo=True)
        msgs = _Worker.captured["messages"] or []
        system_texts = [str(m.get("content", "")) for m in msgs
                        if m.get("role") == "system"]
        return any(NIGHT_CARE_INJECTION in t for t in system_texts)

    def test_deep_night_injects(self, monkeypatch, tmp_path):
        assert self._launch(monkeypatch, tmp_path, 23) is True

    def test_daytime_no_injection(self, monkeypatch, tmp_path):
        assert self._launch(monkeypatch, tmp_path, 10) is False
