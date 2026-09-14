"""tests/test_memory.py —— Memory 模块测试。

覆盖：
- _merge_defaults 深层合并（Fix 15）
- 默认值完整性
"""
import json
import os
import tempfile
import pytest


class TestMemoryDeepMerge:
    """深层合并测试（对应 Fix 15: _merge_defaults）。"""

    def _make_mm(self, tmp_path):
        from memory import MemoryManager
        filepath = str(tmp_path / "test_memory.json")
        return MemoryManager(filepath=filepath)

    def test_deep_merge_preserves_sub_keys(self, tmp_path):
        """深层合并应保留子键，不被浅覆盖。"""
        mm = self._make_mm(tmp_path)
        # 使用实际存在的默认结构键
        data = {
            "topics": {"active": ["coding", "testing"], "archived": ["old"]},
            "habits": {"common_commands": ["ls", "cd"]},
        }
        result = mm._merge_defaults(data)
        assert result["topics"]["active"] == ["coding", "testing"]
        assert result["topics"]["archived"] == ["old"]
        assert result["habits"]["common_commands"] == ["ls", "cd"]

    def test_deep_merge_fills_missing_defaults(self, tmp_path):
        """缺失的子键应从默认值填充。"""
        mm = self._make_mm(tmp_path)
        data = {"topics": {"active": ["coding"]}}
        result = mm._merge_defaults(data)
        # topics 下应有 archived 默认键
        assert "archived" in result["topics"]
        assert result["topics"]["archived"] == []

    def test_empty_data_returns_full_defaults(self, tmp_path):
        mm = self._make_mm(tmp_path)
        result = mm._merge_defaults({})
        assert isinstance(result, dict)
        # 检查实际存在的默认键
        assert "preferences" in result
        assert "topics" in result
        assert "habits" in result
        assert "meta" in result

    def test_no_shallow_overwrite(self, tmp_path):
        """浅 merge 会丢子键，深 merge 不应。"""
        mm = self._make_mm(tmp_path)
        data = {"topics": {"active": ["new_topic"]}}
        result = mm._merge_defaults(data)
        # 深层 merge 应保留 topics 下未覆盖的默认子键
        assert "archived" in result["topics"]
        # active 应被覆盖
        assert result["topics"]["active"] == ["new_topic"]

    def test_merge_does_not_mutate_input(self, tmp_path):
        """合并不应修改输入数据。"""
        mm = self._make_mm(tmp_path)
        original = {"topics": {"active": ["coding"]}}
        import copy
        backup = copy.deepcopy(original)
        mm._merge_defaults(original)
        assert original == backup

    def test_meta_version_default(self, tmp_path):
        """meta.version 默认值为 1。"""
        mm = self._make_mm(tmp_path)
        result = mm._merge_defaults({})
        assert result["meta"]["version"] == 1


# ===========================================================================
# v1.6(D-V16-01): schema 读时迁移 / followup 增强 / 反馈写回 / 删除即遗忘
# ===========================================================================
from datetime import datetime, timedelta  # noqa: E402


def _old_format_payload():
    """模拟 v1.5 旧格式 user_memory.json（str 偏好、旧话题条目）。"""
    return {
        "preferences": {"nickname": "小远", "language": "Rust"},
        "topics": {
            "active": [
                {"subject": "Rust 入门", "last_mentioned": datetime.now().isoformat(),
                 "status": "ongoing"},
            ],
            "archived": [
                {"subject": "旧项目", "last_mentioned": "2026-01-01T10:00:00",
                 "status": "completed"},
            ],
        },
        "habits": {"common_commands": [], "typical_session_time": ""},
        "meta": {"created_at": "2026-01-01T00:00:00", "updated_at": "2026-08-01T00:00:00",
                 "version": 1},
    }


def _backdate(mm, hours: float) -> None:
    """把全部活跃话题的 last_mentioned 拨回 N 小时前（进入续接窗口）。"""
    ts = (datetime.now() - timedelta(hours=hours)).isoformat()
    for t in mm.get_active_topics():
        t["last_mentioned"] = ts
    mm._save()


class TestV16SchemaMigration:
    """读时迁移：旧格式读入 → 新结构 → 旧调用方零破坏。"""

    def test_old_file_migrates(self, tmp_path):
        import json
        from memory import MemoryManager
        fp = str(tmp_path / "m.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(_old_format_payload(), f, ensure_ascii=False)
        mm = MemoryManager(filepath=fp)
        # ① get_preference 恒返 str（零破坏）
        assert mm.get_preference("nickname") == "小远"
        assert mm.get_preference("language") == "Rust"
        assert mm.get_preference("不存在") is None
        # ② 内部结构已对象化，source 恒 legacy（不伪造 manual）
        raw = mm._data["preferences"]["nickname"]
        assert isinstance(raw, dict)
        assert raw["value"] == "小远"
        assert raw["source"] == "legacy"
        assert raw["created_at"] == "2026-08-01T00:00:00"
        # ③ 话题补齐 v1.6 字段
        t = mm.get_active_topics()[0]
        assert t["source"] == "legacy"
        assert t["followup_asked_at"] is None
        assert t["followup_muted_until"] is None
        assert t["followup_score"] == 0
        assert t["pinned"] is False
        # ④ meta.version 保持 1（不引入升级流程）
        assert mm._data["meta"]["version"] == 1

    def test_migration_idempotent_on_reload(self, tmp_path):
        import json
        from memory import MemoryManager
        fp = str(tmp_path / "m.json")
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(_old_format_payload(), f, ensure_ascii=False)
        mm1 = MemoryManager(filepath=fp)   # 触发迁移 + _save 固化
        mm2 = MemoryManager(filepath=fp)   # 二次读取走新结构
        assert mm2.get_preference("nickname") == "小远"
        assert mm2._data["preferences"]["nickname"]["source"] == "legacy"
        assert mm2.list_preferences()["nickname"]["value"] == "小远"

    def test_set_preserves_created_at_and_source(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.set_preference("k", "v1", source="auto")
        mm.set_preference("k", "v2", source="auto")
        raw = mm._data["preferences"]["k"]
        assert raw["source"] == "auto" and raw["value"] == "v2"
        assert raw["created_at"] <= raw["updated_at"]

    def test_extract_uses_auto_source(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.extract_from_dialogue("我喜欢写简洁的代码", "好的")
        assert mm.get_preference("code_style") == "简洁"
        assert mm._data["preferences"]["code_style"]["source"] == "auto"


class TestV16EmotionsHistory:
    """情绪历史 append + 上限 200（Q-B8）。"""

    def test_extract_appends_emotion(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.extract_from_dialogue("今天好累啊", "抱抱")
        hist = mm.get_emotions_history()
        assert len(hist) == 1
        assert hist[0]["emotion"] == "tired"
        assert "累" in hist[0]["excerpt"]
        # 单条兼容路径不动
        assert mm.get_last_emotion() == "tired"
        assert mm.get_last_emotion_time() is not None

    def test_history_cap_200(self, tmp_path):
        import json
        from memory import MemoryManager
        fp = str(tmp_path / "m.json")
        now = datetime.now().isoformat()
        payload = _old_format_payload()
        payload["emotions"] = [{"time": now, "emotion": "happy", "excerpt": "x"} for _ in range(250)]
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        mm = MemoryManager(filepath=fp)
        assert len(mm.get_emotions_history()) == 200
        # 淘汰的是最旧（列表前段）——首条 excerpt 应该是被裁剪后的第 51 条附近
        # 再 append 触发上限守卫
        mm.extract_from_dialogue("好累", "嗯")
        assert len(mm.get_emotions_history()) <= 200


class TestV16DeleteTopicForever:
    """物理双删 active+archived，精确匹配。"""

    def test_delete_from_both_lists(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        mm.forget_topic("Rust 入门")  # → archived
        mm.add_topic("Rust 入门", source="manual")  # 又活跃了
        assert mm.delete_topic_forever("Rust 入门") is True
        assert mm.get_active_topics() == []
        assert all(t["subject"] != "Rust 入门" for t in mm.get_archived_topics())
        # 再次删除：无匹配返回 False
        assert mm.delete_topic_forever("Rust 入门") is False

    def test_exact_match_no_fuzzy(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("学 Rust", source="manual")
        assert mm.delete_topic_forever("Rust") is False  # 子串不误删
        assert len(mm.get_active_topics()) == 1


class TestV16TopicFollowup:
    """build_topic_followup 增强：muted 跳过 / 7 天去重 / score 加权。"""

    def test_hit_writes_asked_at(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate(mm, hours=2)
        text = mm.build_topic_followup(1, 72)
        assert text is not None and "Rust 入门" in text
        t = mm.get_active_topics()[0]
        assert t["followup_asked_at"] is not None

    def test_dedup_within_7_days(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate(mm, hours=2)
        first = mm.pick_topic_followup(1, 72)
        assert first is not None
        second = mm.pick_topic_followup(1, 72)
        assert second is None  # 7 天去重内不再续接

    def test_muted_topic_skipped(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate(mm, hours=2)
        mm.record_followup_feedback("Rust 入门", "mute")
        assert mm.pick_topic_followup(1, 72) is None

    def test_mute_expires_after_14_days(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        _backdate(mm, hours=2)
        mm.record_followup_feedback("Rust 入门", "mute")
        # 手动把 muted_until 拨回 15 天前 → 不再静默
        t = mm.get_active_topics()[0]
        t["followup_muted_until"] = (datetime.now() - timedelta(days=15)).isoformat()
        mm._save()
        assert mm.pick_topic_followup(1, 72) is not None

    def test_score_weighting(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("旧话题", source="manual")
        mm.add_topic("新话题", source="manual")
        # 旧话题分数更高 → 尽管 append 序在后，仍优先续接
        mm.record_followup_feedback("旧话题", "heart")
        mm.record_followup_feedback("旧话题", "heart")
        _backdate(mm, hours=2)  # 两个话题都拨回 2h 前进入 1–72h 窗口
        hit = mm.pick_topic_followup(1, 72)
        assert hit["subject"] == "旧话题"

    def test_out_of_window_ignored(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        assert mm.pick_topic_followup(1, 2) is None  # 提及时间≈现在，<1h


class TestV16FollowupFeedback:
    """record_followup_feedback 三键写回 + 内容源静默。"""

    def test_heart_chat_mute(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("Rust 入门", source="manual")
        assert mm.record_followup_feedback("Rust 入门", "heart") is True
        assert mm.get_active_topics()[0]["followup_score"] == 1
        before = datetime.now()
        assert mm.record_followup_feedback("Rust 入门", "chat") is True
        asked = datetime.fromisoformat(mm.get_active_topics()[0]["followup_asked_at"])
        assert asked >= before - timedelta(seconds=5)
        assert mm.record_followup_feedback("Rust 入门", "mute") is True
        muted_until = datetime.fromisoformat(mm.get_active_topics()[0]["followup_muted_until"])
        assert (muted_until - datetime.now()).days >= 13  # ≥13 天（Q-B7 14 天语义）
        # 未登记的 feedback 值拒绝
        assert mm.record_followup_feedback("Rust 入门", "unknown") is False

    def test_archived_topic_feedback(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("旧话题", source="manual")
        mm.forget_topic("旧话题")
        assert mm.record_followup_feedback("旧话题", "heart") is True
        assert mm.get_archived_topics()[0]["followup_score"] == 1

    def test_source_mute_special_keys(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        assert mm.record_followup_feedback("__emotion__", "mute") is True
        assert mm.is_source_muted("__emotion__") is True
        assert mm.is_source_muted("__todo__") is False
        # 非 mute 的特殊键不写
        assert mm.record_followup_feedback("__emotion__", "heart") is False
        # 三天静默（±1 天容差）
        until = datetime.fromisoformat(mm._data["source_muted_until"]["__emotion__"])
        days = (until - datetime.now()).total_seconds() / 86400
        assert 2 < days <= 3


class TestV16BuildContextAndPin:
    """D-V16-03 注入微调 + pinned 归档豁免。"""

    def test_context_ongoing_desc_order(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        old = (datetime.now() - timedelta(hours=5)).isoformat()
        newer = (datetime.now() - timedelta(hours=1)).isoformat()
        done = (datetime.now() - timedelta(hours=2)).isoformat()
        mm._data["topics"]["active"] = [
            {"subject": "旧话题", "last_mentioned": old, "status": "ongoing"},
            {"subject": "新话题", "last_mentioned": newer, "status": "ongoing"},
            {"subject": "已完成话题", "last_mentioned": done, "status": "completed"},
        ]
        ctx = mm.build_memory_context()
        assert "新话题" in ctx and "旧话题" in ctx
        assert "已完成话题" not in ctx            # 仅 ongoing
        assert ctx.index("新话题") < ctx.index("旧话题")  # last_mentioned 降序

    def test_context_pref_uses_value(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.set_preference("nickname", "小远", source="manual")
        ctx = mm.build_memory_context()
        assert "nickname=小远" in ctx
        assert "source" not in ctx  # 策略/元数据字段不进 prompt

    def test_pin_prevents_auto_archive(self, tmp_path):
        from memory import MemoryManager
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_topic("要固定的事", source="manual")
        mm.pin_topic("要固定的事", True)
        old = (datetime.now() - timedelta(days=30)).isoformat()
        mm.get_active_topics()[0]["last_mentioned"] = old
        mm._save()
        n = mm.archive_stale_topics(days=7)
        assert n == 0
        assert len(mm.get_active_topics()) == 1
