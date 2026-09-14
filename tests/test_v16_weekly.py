# -*- coding: utf-8 -*-
"""v1.6 P1-3 每周共同回顾测试（D-V16-10 / Q-B4）。

覆盖：
- 周日 18:00–21:00 窗口判定（含边界：18:00 生成、17:59/21:00 不生成）；
- 错过窗口不补（窗口外恒 None、无补发队列）+ 同周幂等（week_start 键）；
- 52 周滚动淘汰；
- 规则骨架零 LLM、零数字（R-A：档位词、无计数字段、无「第 N 周」）；
- highlights.query_range 区间/倒序/limit/非法参数；
- page_home 本周回顾卡片（有记录才渲染）+ page_memory_book 往期 Tab（offscreen）。

隔离：weekly/highlights/memory 一律 filepath=tmp_path，绝不读写真实 ~/.maid_coder。
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from highlights import HighlightsManager  # noqa: E402
from memory import MemoryManager  # noqa: E402
from weekly import (  # noqa: E402
    PACE_QUIET, PACE_TIERS, WeeklyReviewManager, week_start_of,
)

# 2026-09-06 为周日（本地日期口径）
SUNDAY_1830 = datetime(2026, 9, 6, 18, 30)
SUNDAY_1759 = datetime(2026, 9, 6, 17, 59)
SUNDAY_2100 = datetime(2026, 9, 6, 21, 0)
SUNDAY_2059 = datetime(2026, 9, 6, 20, 59)
MONDAY_1900 = datetime(2026, 9, 7, 19, 0)
SATURDAY_1900 = datetime(2026, 9, 5, 19, 0)


def _mgr(tmp_path):
    return WeeklyReviewManager(filepath=tmp_path / "weekly.json")


def _stamp_highlights_to_week(hl, now):
    """把高光条目时间戳改写到 now 所在周（add() 恒用真实今天，测试需对齐）。"""
    ws = datetime.strptime(week_start_of(now), "%Y-%m-%d").date()
    d = ws + timedelta(days=2)
    for it in hl._data["items"]:
        it["date"] = d.isoformat()
        it["at"] = f"{d.isoformat()}T10:00:00"
    hl._save()


def _stamp_memory_to_week(mem, now):
    """把话题时间戳改写到 now 所在周（add_topic 恒用真实今天）。"""
    ws = datetime.strptime(week_start_of(now), "%Y-%m-%d").date()
    iso = f"{(ws + timedelta(days=2)).isoformat()}T12:00:00"
    for t in mem._data["topics"]["active"] + mem._data["topics"]["archived"]:
        if t.get("last_mentioned"):
            t["last_mentioned"] = iso
        if t.get("completed_at"):
            t["completed_at"] = iso
    mem._save()


# ---------------------------------------------------------------------------
# 窗口判定 / 错过不补 / 幂等
# ---------------------------------------------------------------------------
class TestWindowJudgment:
    def test_sunday_evening_generates(self, tmp_path):
        m = _mgr(tmp_path)
        review = m.maybe_generate(SUNDAY_1830)
        assert review is not None
        assert review["week_start"] == "2026-08-31"  # 该周周一
        assert review["polished"] is None

    def test_before_and_after_window(self, tmp_path):
        m = _mgr(tmp_path)
        assert m.maybe_generate(SUNDAY_1759) is None
        assert m.maybe_generate(SUNDAY_2100) is None
        assert m.list_reviews() == []

    def test_not_sunday(self, tmp_path):
        m = _mgr(tmp_path)
        assert m.maybe_generate(MONDAY_1900) is None
        assert m.maybe_generate(SATURDAY_1900) is None
        assert m.list_reviews() == []

    def test_missed_window_no_makeup(self, tmp_path):
        # 错过窗口（17:59 / 次日周一 / 周六）→ 不生成、无补发队列，该周永远没有记录
        m = _mgr(tmp_path)
        assert m.maybe_generate(SUNDAY_1759) is None
        assert m.maybe_generate(MONDAY_1900) is None
        assert m.maybe_generate(SATURDAY_1900) is None
        assert m.list_reviews() == []

    def test_same_week_idempotent(self, tmp_path):
        m = _mgr(tmp_path)
        assert m.maybe_generate(SUNDAY_1830) is not None
        assert m.maybe_generate(SUNDAY_2059) is None  # 同周幂等
        assert m.maybe_generate(SUNDAY_1830) is None  # 重开 app 也不重复
        assert len(m.list_reviews()) == 1

    def test_next_week_generates_again(self, tmp_path):
        m = _mgr(tmp_path)
        assert m.maybe_generate(SUNDAY_1830) is not None
        next_sunday = datetime(2026, 9, 13, 19, 0)
        review = m.maybe_generate(next_sunday)
        assert review is not None
        assert review["week_start"] == "2026-09-07"
        assert len(m.list_reviews()) == 2

    def test_week_start_of(self):
        assert week_start_of(SUNDAY_1830) == "2026-08-31"   # 周日 → 本周周一
        assert week_start_of(MONDAY_1900) == "2026-09-07"   # 周一 → 当天
        assert week_start_of(SATURDAY_1900) == "2026-08-31"


# ---------------------------------------------------------------------------
# 52 周滚动淘汰
# ---------------------------------------------------------------------------
class TestPrune:
    def test_52_week_rolling(self, tmp_path):
        from datetime import timedelta
        m = _mgr(tmp_path)
        base = datetime(2020, 1, 6, 12, 0)  # 某周一
        for i in range(60):
            m._data["reviews"].append({
                "week_start": (base + timedelta(weeks=i)).date().isoformat(),
                "generated_at": base.isoformat(),
                "skeleton": {"pace": PACE_QUIET}, "polished": None,
            })
        m._save()
        reviews = m.list_reviews()
        assert len(reviews) <= 52
        # 淘汰最旧的：保留的是最近 52 周（最新 week_start 在列）
        assert reviews[0]["week_start"] == "2021-02-22"  # base + 59 周
        # 落盘文件同样被裁剪
        data = json.loads((tmp_path / "weekly.json").read_text(encoding="utf-8"))
        assert len(data["reviews"]) <= 52


# ---------------------------------------------------------------------------
# 规则骨架（零 LLM / R-A 零数字 / 档位词）
# ---------------------------------------------------------------------------
class TestSkeleton:
    def _gen(self, tmp_path, now=SUNDAY_1830, highlights=None, memory=None,
             companion=None):
        m = _mgr(tmp_path)
        return m.maybe_generate(now, highlights=highlights, memory_mgr=memory,
                                companion=companion), m

    def test_empty_env_quiet_pace(self, tmp_path):
        review, _ = self._gen(tmp_path)
        sk = review["skeleton"]
        assert sk["pace"] == PACE_QUIET
        assert sk["new_topics"] == [] and sk["done_topics"] == []
        assert sk["highlights"] == []
        assert "平稳" in sk["mood_note"]

    def test_no_numbers_in_skeleton(self, tmp_path):
        hl = HighlightsManager(filepath=tmp_path / "hl.json")
        for i, ch in enumerate("甲乙丙丁戊"):
            hl.add("user", f"收藏的高光内容{ch}")
        _stamp_highlights_to_week(hl, SUNDAY_1830)
        mem = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mem.add_topic("考研复习")
        mem.add_topic("装修计划")
        mem.complete_topic("装修计划")
        _stamp_memory_to_week(mem, SUNDAY_1830)
        review, _ = self._gen(tmp_path, highlights=hl, memory=mem)
        sk = review["skeleton"]
        blob = json.dumps(sk, ensure_ascii=False)
        import re
        assert not re.search(r"\d", blob), f"skeleton 出现数字: {blob}"
        assert "第 N 周" not in blob and "第N周" not in blob
        # 键集合固定：无任何计数类字段
        assert set(sk.keys()) == {"pace", "new_topics", "done_topics",
                                  "highlights", "mood_note", "relation_stage"}

    def test_pace_tiers(self, tmp_path):
        mem = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mem.add_topic("考研复习")
        _stamp_memory_to_week(mem, SUNDAY_1830)
        review, _ = self._gen(tmp_path, memory=mem)
        assert review["skeleton"]["pace"] == PACE_TIERS[1]  # 清闲的一周

    def test_highlights_picked_at_most_3(self, tmp_path):
        hl = HighlightsManager(filepath=tmp_path / "hl.json")
        for i in range(5):
            hl.add("user", f"高光文本{i}")
        _stamp_highlights_to_week(hl, SUNDAY_1830)
        review, _ = self._gen(tmp_path, highlights=hl)
        assert len(review["skeleton"]["highlights"]) == 3

    def test_topics_split_new_and_done(self, tmp_path):
        mem = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mem.add_topic("装修计划")
        mem.add_topic("备考")
        mem.complete_topic("备考")
        _stamp_memory_to_week(mem, SUNDAY_1830)
        review, _ = self._gen(tmp_path, memory=mem)
        sk = review["skeleton"]
        assert "装修计划" in sk["new_topics"]
        assert "备考" in sk["done_topics"]

    def test_relation_stage_readonly(self, tmp_path):
        class _Comp:
            def relation_stage_name(self):
                return "熟悉"
        review, _ = self._gen(tmp_path, companion=_Comp())
        assert review["skeleton"]["relation_stage"] == "熟悉"

    def test_data_source_errors_degrade(self, tmp_path):
        class _BoomHL:
            def query_range(self, *a, **k):
                raise RuntimeError("boom")

        class _BoomMem:
            def get_active_topics(self):
                raise RuntimeError("boom")

            def get_archived_topics(self):
                raise RuntimeError("boom")

            def get_emotions_history(self):
                raise RuntimeError("boom")

        class _BoomComp:
            def relation_stage_name(self):
                raise RuntimeError("boom")

        review, _ = self._gen(tmp_path, highlights=_BoomHL(), memory=_BoomMem(),
                              companion=_BoomComp())
        assert review is not None  # 降级为空档，不抛错
        assert review["skeleton"]["pace"] == PACE_QUIET


# ---------------------------------------------------------------------------
# highlights.query_range（v1.6 增量）
# ---------------------------------------------------------------------------
class TestQueryRange:
    def _hl(self, tmp_path):
        hl = HighlightsManager(filepath=tmp_path / "hl.json")
        dates = ["2026-09-01", "2026-09-03", "2026-09-05", "2026-09-07",
                 "2026-09-09"]
        for i, d in enumerate(dates):
            hl.add("user", f"高光{i}")
            hl._data["items"][-1]["date"] = d
            hl._data["items"][-1]["at"] = f"{d}T10:0{i}:00"
        hl._save()
        return hl

    def test_range_inclusive_and_desc(self, tmp_path):
        hl = self._hl(tmp_path)
        got = hl.query_range("2026-09-03", "2026-09-07", limit=10)
        assert [it["date"] for it in got] == ["2026-09-07", "2026-09-05",
                                              "2026-09-03"]

    def test_limit(self, tmp_path):
        hl = self._hl(tmp_path)
        got = hl.query_range("2026-09-01", "2026-09-09", limit=2)
        assert [it["date"] for it in got] == ["2026-09-09", "2026-09-07"]

    def test_invalid_range(self, tmp_path):
        hl = self._hl(tmp_path)
        assert hl.query_range("bad", "2026-09-07") == []
        assert hl.query_range("2026-09-07", "2026-09-01") == []  # 起止颠倒
        assert hl.query_range("2026-09-07", "2026-09-01", limit=0) == []

    def test_weekly_uses_query_range(self, tmp_path):
        # 骨架中的高光必须来自 query_range（时间倒序 + ≤3 + 只含文本无日期）
        hl = self._hl(tmp_path)
        m = _mgr(tmp_path)
        review = m.maybe_generate(SUNDAY_1830, highlights=hl)
        picks = review["skeleton"]["highlights"]
        assert 0 < len(picks) <= 3
        assert all(set(p.keys()) == {"text"} and p["text"] for p in picks)


# ---------------------------------------------------------------------------
# GUI 呈现（offscreen）：page_home 卡片 + page_memory_book 往期 Tab
# ---------------------------------------------------------------------------
@pytest.fixture
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _LiteCtx:
    """极简 ctx：无 config 属性 → theme_color 走兜底；manager 全部显式注入。"""
    weekly = None
    session = None
    companion = None
    companion_bridge = None
    session_manager = None
    highlights = None


def _insert_record_for_current_week(m, pace=PACE_QUIET):
    """直接写入一条「本周」记录（窗口判定已在别处覆盖，这里只测呈现路径）。"""
    from weekly import week_start_of as _ws
    m._data["reviews"].append({
        "week_start": _ws(datetime.now()),
        "generated_at": datetime.now().isoformat(),
        "skeleton": {"pace": pace, "new_topics": ["考研复习"],
                     "done_topics": [], "highlights": [],
                     "mood_note": "这一周心情都挺平稳，平静也是好日子。",
                     "relation_stage": "熟悉"},
        "polished": None,
    })
    m._save()


class TestWeeklyGui:
    def test_page_home_card_hidden_without_record(self, qapp, tmp_path):
        from gui.pages.page_home import PageHome
        ctx = _LiteCtx()
        ctx.weekly = _mgr(tmp_path)  # 显式注入空 manager，避免懒装配触真实目录
        page = PageHome(ctx)
        page.refresh_weekly_review()
        assert page.weekly_card.isVisibleTo(page) is False

    def test_page_home_card_shown_with_record(self, qapp, tmp_path):
        from gui.pages.page_home import PageHome
        ctx = _LiteCtx()
        m = _mgr(tmp_path)
        _insert_record_for_current_week(m)
        ctx.weekly = m
        page = PageHome(ctx)
        page.refresh_weekly_review()
        assert page.weekly_card.isVisibleTo(page) is True
        text = page.weekly_body.text()
        import re
        assert not re.search(r"\d", text), f"卡片文案出现数字: {text}"
        assert "考研复习" in text and "熟悉" in text

    def test_memory_book_weekly_tab(self, qapp, tmp_path):
        from gui.qt_compat import QLabel
        from gui.pages.page_memory_book import PageMemoryBook
        ctx = _LiteCtx()
        ctx.session = SimpleNamespace(
            memory_mgr=MemoryManager(filepath=str(tmp_path / "memory.json")))
        m = _mgr(tmp_path)
        _insert_record_for_current_week(m)
        ctx.weekly = m
        page = PageMemoryBook(ctx)
        # v1.8(D-V18-09): 记忆中心分区满 8（+人物关系/回应约定/共同经历）
        assert page.tabs.tabText(6) == "往期回顾"
        # 收集：空态 QLabel + _EntryCard 的标题 QLabel
        texts = []
        for w in page._list_widgets:
            if isinstance(w, QLabel):
                texts.append(w.text())
            else:
                title = w.findChild(QLabel, "memoryBookTitle")
                if title is not None:
                    texts.append(title.text())
        assert any("本周" in t or "那一周" in t for t in texts), f"缺周标签: {texts}"
        blob = "".join(texts)
        assert "第 1 周" not in blob and "第1周" not in blob

    def test_memory_book_weekly_tab_empty(self, qapp, tmp_path):
        from gui.pages.page_memory_book import PageMemoryBook
        ctx = _LiteCtx()
        ctx.session = SimpleNamespace(
            memory_mgr=MemoryManager(filepath=str(tmp_path / "memory.json")))
        ctx.weekly = _mgr(tmp_path)
        page = PageMemoryBook(ctx)
        # v1.8(D-V18-09): 记忆中心分区满 8（+人物关系/回应约定/共同经历）
        assert page.tabs.tabText(6) == "往期回顾"
        # v1.8(F2): 情绪弧线区块无 text()，收集时按能力守卫
        blob = "".join(w.text() for w in page._list_widgets
                       if hasattr(w, "text"))
        assert "还没有回顾" in blob
