"""tests/test_v25_memory_features.py —— v2.5 记忆系统：提及注入 / 完成检测 / 词表热补 /
会话回放不再覆盖全局记忆。

对应决策：
- D-V25-05 话题提及注入通道（find_topics_by_name + build_topic_mention_injection）
- D-V25-04 话题完成自动检测（含「只说完成词不点名」的防误归档）
- D-V25-06 提取词表外挂 JSON 热补（含坏文件降级）
- D-V25-07 会话/崩溃恢复不再回放 memory / intimacy
- D-V25-01 MemoryManager 进程内锁
- D-V25-03 死代码清理与常量单一事实源

测试数据隔离：一律 filepath=tmp_path（共享知识 23）。
"""
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from memory import MemoryManager


def _make_mm(tmp_path, name="v25_memory.json"):
    return MemoryManager(filepath=str(tmp_path / name))


# ---------------------------------------------------------------------------
# D-V25-05：话题提及注入通道
# ---------------------------------------------------------------------------

class TestTopicMentionRetrieval:
    def test_finds_active_topic_by_full_subject(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        hits = mm.find_topics_by_name("考研复习好难啊")
        assert [t["subject"] for t in hits] == ["考研复习"]

    def test_finds_archived_topic(self, tmp_path):
        """归档话题也能被唤起 —— 这是本通道存在的理由。"""
        mm = _make_mm(tmp_path)
        mm.add_topic("装修计划", source="manual")
        mm.complete_topic("装修计划")
        assert mm.get_active_topics() == []
        hits = mm.find_topics_by_name("装修计划那边怎么样了")
        assert [t["subject"] for t in hits] == ["装修计划"]
        assert hits[0]["status"] == "completed"

    def test_partial_cjk_prefix_does_not_match(self, tmp_path):
        """**保守匹配**（与实体通道一致）：不做 CJK 前缀模糊匹配。

        「装修计划」不会因为用户说「装修」就被唤起 —— 宁可漏，不可误注入
        （提及注入是每轮都跑的通道，误命中等于持续 prompt 污染）。
        """
        mm = _make_mm(tmp_path)
        mm.add_topic("装修计划", source="manual")
        assert mm.find_topics_by_name("装修那边怎么样了") == []
        assert mm.find_topics_by_name("装修计划") != []      # 整串命中才算

    def test_finds_spaced_subject_by_word(self, tmp_path):
        """「学 Rust」这类含空格话题，用户只说「Rust」也能命中。"""
        mm = _make_mm(tmp_path)
        mm.add_topic("学 Rust", source="manual")
        assert [t["subject"] for t in mm.find_topics_by_name("Rust 写得怎么样了")] == ["学 Rust"]

    def test_no_hit_returns_empty(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        assert mm.find_topics_by_name("今天天气不错") == []

    def test_empty_text_returns_empty(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        assert mm.find_topics_by_name("") == []
        assert mm.find_topics_by_name(None) == []

    def test_limit_applied(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("话题甲", source="manual")
        mm.add_topic("话题乙", source="manual")
        hits = mm.find_topics_by_name("话题甲和话题乙", limit=1)
        assert len(hits) == 1

    def test_returns_copies_not_internal_objects(self, tmp_path):
        """返回副本 —— 调用方改不动内部数据（防注入链污染记忆）。"""
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        hits = mm.find_topics_by_name("考研复习")
        hits[0]["subject"] = "被改了"
        assert mm.get_active_topics()[0]["subject"] == "考研复习"


class TestTopicMentionInjectionBuilder:
    def _build(self, mm, text):
        from gui.chat_service import build_topic_mention_injection
        return build_topic_mention_injection(mm, text)

    def test_line_format(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        lines = self._build(mm, "考研复习好难")
        assert len(lines) == 1
        assert lines[0].startswith("【之前聊过】")
        assert "考研复习" in lines[0]

    def test_completed_topic_marked(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("装修计划", source="manual")
        mm.complete_topic("装修计划")
        lines = self._build(mm, "装修计划进展如何")
        assert len(lines) == 1
        assert "已经完成了" in lines[0]

    def test_no_hit_zero_injection(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("考研复习", source="manual")
        assert self._build(mm, "今天天气不错") == []

    def test_none_mgr_safe(self):
        assert self._build(None, "随便说点什么") == []

    def test_empty_text_safe(self, tmp_path):
        mm = _make_mm(tmp_path)
        assert self._build(mm, "") == []

    def test_line_length_capped(self, tmp_path):
        """两行长话题拼起来超限时被截断到 _TOPIC_MENTION_LINE_MAX。"""
        mm = _make_mm(tmp_path)
        long_a = "甲" * 80
        long_b = "乙" * 80
        mm.add_topic(long_a, source="manual")
        mm.add_topic(long_b, source="manual")
        lines = self._build(mm, f"{long_a} 和 {long_b} 都聊聊")
        assert len(lines) == 1
        assert len(lines[0]) <= 150
        # 未截断时本应超过上限（证明截断真的生效，而非碰巧没超）
        assert len(long_a) + len(long_b) + 20 > 150

    def test_broken_mgr_does_not_raise(self):
        class _Boom:
            def find_topics_by_name(self, *a, **k):
                raise RuntimeError("boom")
        assert self._build(_Boom(), "任意") == []


# ---------------------------------------------------------------------------
# D-V25-04：话题完成自动检测
# ---------------------------------------------------------------------------

class TestTopicCompletionDetection:
    def test_completion_phrase_with_topic_archives(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.extract_from_dialogue("我最近在学 Rust", "好呀")
        assert [t["subject"] for t in mm.get_active_topics()] == ["学 Rust"]
        mm.extract_from_dialogue("Rust 终于搞定了", "太棒了")
        assert mm.get_active_topics() == []
        archived = mm.get_archived_topics()
        assert [t["subject"] for t in archived] == ["学 Rust"]
        assert archived[0]["status"] == "completed"

    def test_completion_word_without_topic_does_not_guess(self, tmp_path):
        """核心守护：只说「搞定了」而不点名话题时**绝不猜测**（防误归档）。"""
        mm = _make_mm(tmp_path)
        mm.extract_from_dialogue("我在研究向量数据库", "嗯")
        mm.extract_from_dialogue("今天搞定了好多事", "辛苦啦")
        assert [t["subject"] for t in mm.get_active_topics()] == ["向量数据库"]
        assert mm.get_archived_topics() == []

    def test_no_completion_word_no_archive(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.extract_from_dialogue("我在研究向量数据库", "嗯")
        mm.extract_from_dialogue("向量数据库挺有意思的", "是呀")
        assert [t["subject"] for t in mm.get_active_topics()] == ["向量数据库"]
        assert mm.get_archived_topics() == []

    def test_completion_reports_in_extracted(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.extract_from_dialogue("我最近在学 Rust", "好")
        out = mm.extract_from_dialogue("Rust 搞定了", "厉害")
        assert any("已完成话题" in s for s in out)

    @pytest.mark.parametrize("phrase", ["搞定了", "完成了", "上线了", "考完了", "交付了"])
    def test_various_completion_phrases(self, tmp_path, phrase):
        mm = _make_mm(tmp_path, name=f"c_{phrase}.json")
        mm.add_topic("考研复习", source="manual")
        mm.extract_from_dialogue(f"考研复习{phrase}", "好")
        assert mm.get_active_topics() == []


# ---------------------------------------------------------------------------
# D-V25-06：提取词表外挂 JSON 热补
# ---------------------------------------------------------------------------

class TestExternalPatterns:
    def _write_patterns(self, tmp_path, payload):
        p = Path(tmp_path) / "memory_patterns.json"
        if isinstance(payload, str):
            p.write_text(payload, encoding="utf-8")
        else:
            p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return p

    def test_absent_file_uses_builtin(self, tmp_path):
        mm = _make_mm(tmp_path)
        assert mm.extract_from_dialogue("我最近在学 Rust", "好") == ["活跃话题: 学 Rust"]

    def test_external_topic_pattern_hot_patches(self, tmp_path):
        mm = _make_mm(tmp_path)
        assert mm.extract_from_dialogue("我在肝 Galgame", "好") == []
        self._write_patterns(tmp_path, {
            "topic": [[r"(?:我在肝)\s*(.+?)(?:[。！？\n]|$)", "ongoing"]],
        })
        assert mm.extract_from_dialogue("我在肝 Galgame", "好") == ["活跃话题: Galgame"]

    def test_external_completion_word_hot_patches(self, tmp_path):
        mm = _make_mm(tmp_path)
        mm.add_topic("装修计划", source="manual")
        mm.extract_from_dialogue("装修计划弄妥了", "好")     # 内置词表未命中
        assert len(mm.get_active_topics()) == 1
        self._write_patterns(tmp_path, {"completion": [["弄妥了", "x"]]})
        mm.extract_from_dialogue("装修计划弄妥了", "好")
        assert mm.get_active_topics() == []

    def test_external_emotion_keywords_hot_patches(self, tmp_path):
        mm = _make_mm(tmp_path)
        assert mm.detect_emotion("这波太爽了") is None
        self._write_patterns(tmp_path, {"emotion_keywords": {"excited": ["太爽了"]}})
        assert mm.detect_emotion("这波太爽了") == "excited"

    def test_builtin_takes_priority_order(self, tmp_path):
        """外挂条目**追加**在内置之后，内置优先级不受影响。"""
        mm = _make_mm(tmp_path)
        self._write_patterns(tmp_path, {
            "emotion_keywords": {"zzz_custom": ["累"]},   # 与内置 tired 的「累」同词
        })
        assert mm.detect_emotion("好累啊") == "tired"

    def test_broken_json_falls_back_silently(self, tmp_path):
        mm = _make_mm(tmp_path)
        self._write_patterns(tmp_path, "{这不是合法 JSON")
        assert mm.extract_from_dialogue("我最近在学 Rust", "好") == ["活跃话题: 学 Rust"]

    def test_wrong_types_are_ignored(self, tmp_path):
        mm = _make_mm(tmp_path)
        self._write_patterns(tmp_path, {
            "topic": "不是列表",
            "completion": [["只有一项"]],
            "emotion_keywords": {"bad": "不是列表"},
        })
        assert mm.extract_from_dialogue("我最近在学 Rust", "好") == ["活跃话题: 学 Rust"]

    def test_reload_on_mtime_change(self, tmp_path):
        """改词表不必重启 —— mtime 变更自动重载。"""
        import time
        mm = _make_mm(tmp_path)
        assert mm.extract_from_dialogue("我在肝 Galgame", "好") == []
        self._write_patterns(tmp_path, {"topic": [[r"(?:我在肝)\s*(.+?)(?:[。！？\n]|$)", "ongoing"]]})
        time.sleep(0.01)
        assert mm.extract_from_dialogue("我在肝 Galgame", "好") == ["活跃话题: Galgame"]

    def test_patterns_file_next_to_memory_file(self, tmp_path):
        """词表与记忆文件同目录（真实安装 = ~/.maid_coder/）。"""
        mm = _make_mm(tmp_path)
        assert Path(mm._patterns_path()).parent == Path(tmp_path)


# ---------------------------------------------------------------------------
# D-V25-07：会话/崩溃恢复不再回放覆盖全局记忆
# ---------------------------------------------------------------------------

class TestNoReplayOverwrite:
    def _cfg(self, tmp_path):
        cfg = MagicMock()
        cfg.max_history_rounds = 8
        cfg.summary_interval = 5
        cfg.auto_save = False
        cfg.persona_address_user = "主人"
        cfg.persona_address_self = "我"
        cfg.snippets_file = str(tmp_path / "s.json")
        cfg.todos_file = str(tmp_path / "t.json")
        cfg.code_exec_timeout = 5
        cfg.web_search_max_results = 3
        cfg.kb_index_file = str(tmp_path / "k.json")
        cfg.plugins_dir = str(tmp_path / "p")
        return cfg

    def test_load_does_not_replay_global_memory(self, tmp_path, monkeypatch):
        """加载旧会话不得用会话内快照覆盖全局记忆（原实现会整体回退）。"""
        import memory as memory_mod
        import session as session_mod
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(memory_mod, "_memory_path",
                            lambda: str(tmp_path / "auto_mem.json"))
        # v2.5(D-V25-10): 会话落点已锚定用户数据目录 —— 测试必须重定向，
        # 否则会写进真实 ~/.maid_coder/sessions/（违反共享知识 23）
        monkeypatch.setattr(session_mod, "_cli_session_dir", lambda: str(tmp_path))
        from session import ChatSession
        s = ChatSession(self._cfg(tmp_path), MagicMock(), MagicMock())
        # 接管为 tmp 隔离实例，并写入「当前」全局记忆
        mm = _make_mm(tmp_path)
        s.memory_mgr = mm
        mm.add_topic("当前话题", source="manual")
        # 造一个内嵌「三周前快照」的旧会话文件
        old = {
            "session_id": "default", "history": [], "turn_count": 1,
            "memory": {
                "topics": {"active": [{"subject": "三周前的旧话题",
                                       "last_mentioned": "2026-08-01T00:00:00",
                                       "status": "ongoing"}],
                           "archived": []},
                "preferences": {}, "meta": {"version": 1},
            },
            "intimacy": {},
        }
        (tmp_path / "cli_default.json").write_text(
            json.dumps(old, ensure_ascii=False), encoding="utf-8")
        assert s.load("default") is True
        # 全局记忆必须仍是「当前话题」，绝不能被旧快照覆盖
        assert [t["subject"] for t in mm.get_active_topics()] == ["当前话题"]

    def test_spy_from_dict_not_called_on_load(self, tmp_path, monkeypatch):
        """更硬的护栏：load() 根本不应调用 from_dict。"""
        import memory as memory_mod
        import session as session_mod
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(memory_mod, "_memory_path",
                            lambda: str(tmp_path / "auto_mem.json"))
        monkeypatch.setattr(session_mod, "_cli_session_dir", lambda: str(tmp_path))
        from session import ChatSession
        s = ChatSession(self._cfg(tmp_path), MagicMock(), MagicMock())
        mm = _make_mm(tmp_path)
        s.memory_mgr = mm
        called = []
        monkeypatch.setattr(mm, "from_dict", lambda *a, **k: called.append(1))
        (tmp_path / "cli_default.json").write_text(
            json.dumps({"session_id": "default", "history": [],
                        "memory": {"topics": {"active": [], "archived": []}}},
                       ensure_ascii=False), encoding="utf-8")
        s.load("default")
        assert called == [], "load() 不应回放记忆快照"


class TestCliSessionPath:
    """D-V25-10：CLI 会话文件锚定用户数据目录（原为 CWD 相对）。"""

    def _mm(self, tmp_path):
        return _make_mm(tmp_path, name="sess_mem.json")

    def test_session_dir_is_absolute_under_user_data(self):
        import session as session_mod
        d = session_mod._cli_session_dir()
        assert os.path.isabs(d)
        assert d.replace("\\", "/").endswith(".maid_coder/sessions")

    def test_session_file_has_cli_prefix(self):
        """加 cli_ 前缀，避免与 GUI 的 <session_id>.json 撞名（格式不同）。"""
        import session as session_mod
        p = session_mod._cli_session_file("default")
        assert os.path.basename(p) == "cli_default.json"

    def test_save_and_load_survive_cwd_change(self, tmp_path, monkeypatch):
        """核心保证：换工作目录后仍能读回同一份会话。"""
        import memory as memory_mod
        import session as session_mod
        monkeypatch.setattr(memory_mod, "_memory_path",
                            lambda: str(tmp_path / "auto_mem.json"))

        def _dir():                      # 与真实实现一致：带 makedirs
            d = tmp_path / "s"
            d.mkdir(parents=True, exist_ok=True)
            return str(d)

        monkeypatch.setattr(session_mod, "_cli_session_dir", _dir)
        from session import ChatSession
        cwd_a = tmp_path / "a"
        cwd_b = tmp_path / "b"
        cwd_a.mkdir()
        cwd_b.mkdir()
        monkeypatch.chdir(cwd_a)
        s = self._mk_session(tmp_path)
        s.add_message("user", "在 A 目录说的话")
        s.save("mysess")
        monkeypatch.chdir(cwd_b)          # 换目录
        s2 = self._mk_session(tmp_path)
        assert s2.load("mysess") is True, "换目录后仍应读回同一份会话"
        assert any("在 A 目录说的话" in str(m.get("content", "")) for m in s2.history)

    def test_legacy_cwd_file_still_readable(self, tmp_path, monkeypatch):
        """向后兼容：旧版本写在启动目录下的会话文件仍能读回。"""
        import memory as memory_mod
        import session as session_mod
        monkeypatch.setattr(memory_mod, "_memory_path",
                            lambda: str(tmp_path / "auto_mem.json"))
        # 新位置故意指向一个空目录 → 新位置无文件，只能走兼容分支
        monkeypatch.setattr(session_mod, "_cli_session_dir",
                            lambda: str(tmp_path / "empty_new"))
        monkeypatch.chdir(tmp_path)
        from session import ChatSession
        (tmp_path / "legacyone.json").write_text(
            json.dumps({"session_id": "legacyone", "history": [
                {"role": "user", "content": "旧位置的话"}]}, ensure_ascii=False),
            encoding="utf-8")
        s = ChatSession(self._cfg_stub(tmp_path), MagicMock(), MagicMock())
        assert s.load("legacyone") is True
        assert any("旧位置的话" in str(m.get("content", "")) for m in s.history)

    def _mk_session(self, tmp_path):
        """构造会话并把布尔字段归一 —— MagicMock 的 cfg 会把它们变成 MagicMock，
        导致 save() 序列化时 TypeError（与业务逻辑无关，纯测试替身问题）。"""
        from session import ChatSession
        s = ChatSession(self._cfg_stub(tmp_path), MagicMock(), MagicMock())
        s.deep_mode = s.coding_mode = s.multi_mode = False
        s.stream_mode = False
        s.speed = "normal"
        return s

    def _cfg_stub(self, tmp_path):
        cfg = MagicMock()
        cfg.max_history_rounds = 8
        cfg.summary_interval = 5
        cfg.auto_save = False
        cfg.persona_address_user = "主人"
        cfg.persona_address_self = "我"
        cfg.snippets_file = str(tmp_path / "s.json")
        cfg.todos_file = str(tmp_path / "t.json")
        cfg.code_exec_timeout = 5
        cfg.web_search_max_results = 3
        cfg.kb_index_file = str(tmp_path / "k.json")
        cfg.plugins_dir = str(tmp_path / "p")
        return cfg


# ---------------------------------------------------------------------------
# D-V25-01 / D-V25-03：线程安全与死代码清理
# ---------------------------------------------------------------------------

class TestThreadSafetyAndCleanup:
    def test_manager_has_reentrant_lock(self, tmp_path):
        mm = _make_mm(tmp_path)
        import threading
        assert isinstance(mm._lock, type(threading.RLock()))

    def test_save_is_locked_callable_from_same_thread(self, tmp_path):
        """RLock 可重入：持锁路径里再调 _save() 不得死锁。"""
        mm = _make_mm(tmp_path)
        with mm._lock:
            mm.add_topic("重入测试", source="manual")   # 内部会 _save()
        assert [t["subject"] for t in mm.get_active_topics()] == ["重入测试"]

    def test_concurrent_writes_keep_file_parseable(self, tmp_path):
        import threading
        mm = _make_mm(tmp_path)
        errors = []

        def worker(n: int) -> None:
            try:
                for i in range(20):
                    mm.add_topic(f"话题{n}-{i}", source="manual")
            except Exception as exc:                     # pragma: no cover
                errors.append(exc)

        ts = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert errors == []
        # 文件仍可被重新解析（无交错损坏）
        again = _make_mm(tmp_path)
        assert isinstance(again.get_active_topics(), list)

    def test_dead_method_removed(self, tmp_path):
        """D-V25-03：update_topic_status 是全仓死代码，本版删除。"""
        mm = _make_mm(tmp_path)
        assert not hasattr(mm, "update_topic_status")

    def test_vision_note_constants_are_wired(self, tmp_path):
        """D-V25-03：常量与实现不再漂移（原常量定义了却从未被使用）。"""
        import memory as m
        assert m._VISION_NOTE_DEFAULT == "用户分享了一张图片"
        mm = _make_mm(tmp_path)
        vid = mm.add_vision_memory("配文", "摘要")     # 不传 image_note
        item = [v for v in mm.list_vision_memories() if v["id"] == vid][0]
        assert item["image_note"] == m._VISION_NOTE_DEFAULT

    def test_relation_presets_single_source(self):
        """D-V25-03：关系预设单一事实源（页面不再复制一份）。"""
        import memory as m
        from gui.pages import page_memory_book as pmb
        assert pmb._ENTITY_RELATION_PRESETS is m._ENTITY_RELATION_PRESETS \
            or pmb._ENTITY_RELATION_PRESETS == m._ENTITY_RELATION_PRESETS
        assert pmb._FOLLOWUP_MUTE_DAYS == m._FOLLOWUP_MUTE_DAYS

    def test_vision_query_no_redundant_branch(self, tmp_path):
        """D-V25-03：query_vision_memories 的死分支已修（limit=None 返回全部）。"""
        mm = _make_mm(tmp_path)
        for i in range(5):
            mm.add_vision_memory(f"配文{i}", f"摘要{i}")
        assert len(mm.query_vision_memories("", limit=None)) == 5
        assert len(mm.query_vision_memories("", limit=2)) == 2
        assert len(mm.query_vision_memories("不存在词", limit=None)) == 5
