"""tests/test_v24_followup_priority.py —— v2.4 续接优先级评分与话题提取质量门。

覆盖：
- D-V24-03 多因子评分 `_followup_priority`（有用信号 + 软时间衰减 + 来源可信度）
- D-V24-03 三条硬门仍生效（muted 静默 / 7 天去重 / [min,max] 时间窗）
- D-V24-03 tie-break 方向不变（idx 小者优先，既有 test_score_weighting 依赖）
- D-V24-02 话题提取质量门（正则前导锚点 + _TOPIC_SUBJECT_MAX）

测试数据隔离：一律 `filepath=tmp_path`，不读写真实 ~/.maid_coder/（共享知识 23）。
"""
from datetime import datetime, timedelta

import pytest


def _make_mm(tmp_path):
    from memory import MemoryManager
    return MemoryManager(filepath=str(tmp_path / "v24_memory.json"))


def _add(mm, subject, hours_ago, score=0, source="manual"):
    """建一条话题并把 last_mentioned 拨到 hours_ago 小时前。

    走公开方法 add_topic；仅对 last_mentioned / followup_score 做测试专用回拨
    （与 companion_scenarios 的 act_backdate_topic 同法）。
    """
    mm.add_topic(subject, source=source)
    for t in mm._data["topics"]["active"]:
        if t["subject"] == subject:
            t["last_mentioned"] = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
            t["followup_score"] = score
            break
    return mm


class TestFollowupPriorityFormula:
    """D-V24-03：多因子评分本身的行为（纯函数，直接调用）。"""

    def test_useful_clamped_no_runaway(self, tmp_path):
        """followup_score 无上限，但 useful 项 clamp 到 1.0 —— 高分不失控。"""
        mm = _make_mm(tmp_path)
        now = datetime.now()
        base = {"subject": "x", "last_mentioned": now.isoformat(), "source": "manual"}
        p5 = mm._followup_priority(dict(base, followup_score=5), now)
        p100 = mm._followup_priority(dict(base, followup_score=100), now)
        assert p5 == pytest.approx(p100)

    def test_evidence_manual_over_auto(self, tmp_path):
        """同时间同分数下 manual 优先于 auto（用户手建 > 自动提取）。"""
        mm = _make_mm(tmp_path)
        now = datetime.now()
        stamp = now.isoformat()
        p_manual = mm._followup_priority(
            {"subject": "m", "last_mentioned": stamp, "followup_score": 0,
             "source": "manual"}, now)
        p_auto = mm._followup_priority(
            {"subject": "a", "last_mentioned": stamp, "followup_score": 0,
             "source": "auto"}, now)
        assert p_manual > p_auto

    def test_recency_decays_with_age(self, tmp_path):
        """recency 软衰减：越旧分越低（同一话题不同时间戳）。"""
        mm = _make_mm(tmp_path)
        now = datetime.now()
        def p(hours):
            return mm._followup_priority(
                {"subject": "x", "followup_score": 0, "source": "auto",
                 "last_mentioned": (now - timedelta(hours=hours)).isoformat()}, now)
        assert p(1) > p(12) > p(36) > p(72)

    def test_half_life_value(self, tmp_path):
        """半衰期恰为 36h：一个半衰期后 recency 项减半（0.5 倍）。"""
        mm = _make_mm(tmp_path)
        from memory import _FOLLOWUP_HALF_LIFE_HOURS
        assert _FOLLOWUP_HALF_LIFE_HOURS == 36.0
        now = datetime.now()
        def recency(hours):
            tk = {"subject": "x", "followup_score": 0, "source": "auto",
                  "last_mentioned": (now - timedelta(hours=hours)).isoformat()}
            # 反解 recency：priority = 0.40*0 + 0.40*recency + 0.20*evidence(auto)
            return (mm._followup_priority(tk, now) - 0.20 * 0.6) / 0.40
        assert recency(0) == pytest.approx(1.0, abs=1e-6)
        assert recency(36) == pytest.approx(0.5, abs=1e-3)
        assert recency(72) == pytest.approx(0.25, abs=1e-3)

    def test_dirty_data_falls_back(self, tmp_path):
        """脏数据降级不抛错：非法 score / 非法时间戳 / 非法 source / 空 dict。"""
        mm = _make_mm(tmp_path)
        now = datetime.now()
        assert mm._followup_priority({}, now) >= 0.0
        assert mm._followup_priority({"followup_score": "不是数字"}, now) >= 0.0
        assert mm._followup_priority({"followup_score": None}, now) >= 0.0
        assert mm._followup_priority({"last_mentioned": "不是时间"}, now) >= 0.0
        assert mm._followup_priority({"source": None}, now) >= 0.0
        assert mm._followup_priority({"source": 12345}, now) >= 0.0
        # 缺时间戳 -> recency 取 0（沉底）
        assert mm._followup_priority({"source": "manual"}, now) \
            == pytest.approx(0.20 * 1.0)

    def test_is_pure_no_mutation(self, tmp_path):
        """纯函数：调用前后 topic 不被修改。"""
        mm = _make_mm(tmp_path)
        now = datetime.now()
        tk = {"subject": "x", "last_mentioned": now.isoformat(),
              "followup_score": 3, "source": "manual", "pinned": True}
        snapshot = dict(tk)
        mm._followup_priority(tk, now)
        assert tk == snapshot


class TestFollowupRankingBehaviour:
    """D-V24-03：评分接入 pick_topic_followup 后的排序行为。"""

    def test_recent_beats_stale_heart(self, tmp_path):
        """设计意图核心：3h 前提到的（0.488）胜过 60h 前 heart 过一次的（0.356）。

        v1.6 的 (score, idx) 字典序下这里是 A 胜且与时间无关 —— 本用例即旧行为
        的反例，钉住 v2.4 的改进语义。
        """
        mm = _make_mm(tmp_path)
        _add(mm, "久远被夸过", 60, score=1, source="manual")
        _add(mm, "刚刚聊起", 3, score=0, source="auto")
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        assert hit["subject"] == "刚刚聊起"

    def test_recent_strong_heart_wins(self, tmp_path):
        """12h 前 heart 过两次（0.647）胜 2h 前无 heart（0.578）—— 加权仍有效。"""
        mm = _make_mm(tmp_path)
        _add(mm, "被夸过两次", 12, score=2, source="manual")
        _add(mm, "刚提到", 2, score=0, source="manual")
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        assert hit["subject"] == "被夸过两次"

    def test_tie_break_keeps_list_order(self, tmp_path):
        """评分完全相同时按列表原序（idx 小者优先）—— 方向与 v1.6 一致。

        既有 tests/test_memory.py::test_score_weighting 实际依赖此 tie-break，
        反转方向会使其变红（见 docs/design-v24.md §1.4 落点校正）。
        """
        mm = _make_mm(tmp_path)
        same = (datetime.now() - timedelta(hours=6)).isoformat()
        mm.add_topic("先加入的", source="manual")
        mm.add_topic("后加入的", source="manual")
        for t in mm._data["topics"]["active"]:
            t["last_mentioned"] = same
            t["followup_score"] = 0
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        assert hit["subject"] == "先加入的"


class TestFollowupHardGatesPreserved:
    """D-V24-03：三条硬门在评分改造后必须原样生效（硬门管"能不能提"）。"""

    def test_muted_topic_still_skipped(self, tmp_path):
        mm = _make_mm(tmp_path)
        _add(mm, "被静默的", 3, score=5, source="manual")   # 分数最高
        _add(mm, "可提的", 30, score=0, source="auto")
        for t in mm._data["topics"]["active"]:
            if t["subject"] == "被静默的":
                t["followup_muted_until"] = (datetime.now() + timedelta(days=7)).isoformat()
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        assert hit["subject"] == "可提的"

    def test_dedup_within_7_days_still_applies(self, tmp_path):
        mm = _make_mm(tmp_path)
        _add(mm, "刚问过的", 3, score=5, source="manual")
        _add(mm, "没问过的", 30, score=0, source="auto")
        for t in mm._data["topics"]["active"]:
            if t["subject"] == "刚问过的":
                t["followup_asked_at"] = (datetime.now() - timedelta(days=1)).isoformat()
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        assert hit["subject"] == "没问过的"

    def test_out_of_window_still_ignored(self, tmp_path):
        """72h 窗外一律不入选（评分再高也不行）。"""
        mm = _make_mm(tmp_path)
        _add(mm, "太老了", 100, score=9, source="manual")
        assert mm.pick_topic_followup(1, 72) is None

    def test_too_recent_still_ignored(self, tmp_path):
        """1h 窗内（刚说过）不续接。"""
        mm = _make_mm(tmp_path)
        _add(mm, "刚说的", 0, score=9, source="manual")
        assert mm.pick_topic_followup(1, 72) is None

    def test_hit_still_writes_asked_at(self, tmp_path):
        """命中副作用保持不变：写 followup_asked_at 并落盘（v1.6 验收 1）。"""
        mm = _make_mm(tmp_path)
        _add(mm, "可提的", 5, source="manual")
        hit = mm.pick_topic_followup(1, 72)
        assert hit is not None
        for t in mm._data["topics"]["active"]:
            assert t["followup_asked_at"] is not None
        # 二次调用应被 7 天去重挡住
        assert mm.pick_topic_followup(1, 72) is None


class TestTopicExtractionQualityGate:
    """D-V24-02：话题提取质量门 —— 挡住裸名词误捕，保留正常表达。"""

    def _topics(self, tmp_path, text):
        mm = _make_mm(tmp_path)
        mm.extract_from_dialogue(text, "好的")
        return [t["subject"] for t in mm.get_active_topics()]

    @pytest.mark.parametrize("text", [
        "这个项目做完了",          # 裸名词提及 + 无分隔词 -> 原本捕获「做完了」
        "我的项目已经上线了",
        "今天工作好累",
        "我把任务交了",
        "最近项目很忙",
    ])
    def test_bare_noun_mention_not_extracted(self, tmp_path, text):
        assert self._topics(tmp_path, text) == []

    @pytest.mark.parametrize("text,expected", [
        ("项目：做个网站", "做个网站"),
        ("我的项目是做个网站", "做个网站"),
        ("任务叫重构登录页", "重构登录页"),
        ("我在研究向量数据库", "向量数据库"),
        ("我最近在学 Rust", "学 Rust"),
    ])
    def test_valid_forms_still_extracted(self, tmp_path, text, expected):
        assert self._topics(tmp_path, text) == [expected]

    def test_overlong_subject_rejected(self, tmp_path):
        """超长捕获被 _TOPIC_SUBJECT_MAX(30) 挡住（与正则锚点双保险）。"""
        long_tail = "做一个支持多租户的分布式任务调度系统并且要兼容现有的所有历史接口和协议"
        assert len(long_tail) > 30
        assert self._topics(tmp_path, f"项目是{long_tail}") == []

    def test_subject_max_constant(self, tmp_path):
        from memory import _TOPIC_SUBJECT_MAX
        assert _TOPIC_SUBJECT_MAX == 30
