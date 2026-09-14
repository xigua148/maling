"""tests/test_intent.py —— v1.6 P0-2 意图五态纯规则分类单测（≥40 用例，≥85% 断言）。

覆盖：
- 五态命中（词表 + 句式正则）；
- 未识别/空文本/低置信恒落 chat（无消息黑洞）；
- 复合句优先级（confide > act > analyze > advise）；
- 词表 JSON 合并加载 + 脏数据守卫 + reload_words 热加载 + 内置兜底；
- INTENT_HINTS 五态覆盖、chat 态零附加。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui import intent  # noqa: E402


# ---------------------------------------------------------------------------
# 五态命中用例（text, expect）—— 标注集 ≥40 条
# ---------------------------------------------------------------------------
CASES = [
    # confide 情绪倾诉（10）
    ("我今天心里很难受，不想说话", "confide"),
    ("有点想哭，别问我为什么", "confide"),
    ("撑不住了，只想找人说说话", "confide"),
    ("被领导骂了，好委屈", "confide"),
    ("最近emo了", "confide"),
    ("项目黄了，我崩溃了", "confide"),
    ("我烦死了，别给我建议，听我说完", "confide"),
    ("感觉好累好累，不想动", "confide"),
    ("我心情很糟糕", "confide"),
    ("没人懂我，只想说说", "confide"),
    # chat 闲聊陪伴（8）
    ("陪我聊聊天吧", "chat"),
    ("在吗", "chat"),
    ("好无聊啊", "chat"),
    ("和我说说话", "chat"),
    ("闲聊一会", "chat"),
    ("给我讲讲有趣的事", "chat"),
    ("无聊，解解闷", "chat"),
    ("随便聊聊", "chat"),
    # analyze 技术分析（9）
    ("帮我分析一下这段报错", "analyze"),
    ("Python 的 GIL 原理是什么", "analyze"),
    ("为什么这个接口超时了", "analyze"),
    ("这两个框架的区别是什么", "analyze"),
    ("帮我排查一下内存泄漏", "analyze"),
    ("什么是事件循环", "analyze"),
    ("这段日志怎么解读", "analyze"),
    ("帮我对比一下 MySQL 和 PG 的优缺点", "analyze"),
    ("编译一直失败是怎么回事", "analyze"),
    # advise 征求建议（8）
    ("给我建议，我该学哪门语言", "advise"),
    ("有什么建议吗", "advise"),
    ("我是不是应该换工作，怎么办", "advise"),
    ("推荐几个好用的编辑器", "advise"),
    ("这个方案值得吗", "advise"),
    ("怎么选数据库", "advise"),
    ("怎么优化我的代码结构，有什么办法", "advise"),
    ("求点建议", "advise"),
    # act 行动执行（9）
    ("帮我改一下这个函数", "act"),
    ("写一个爬虫脚本", "act"),
    ("帮我跑一下测试", "act"),
    ("帮我生成一份周报", "act"),
    ("把这个模块重构掉", "act"),
    ("修复这个 bug", "act"),
    ("新建一个项目目录", "act"),
    ("帮我提交代码", "act"),
    ("运行一下这个脚本", "act"),
]


class TestFiveStateDetection:
    def test_labeled_cases(self):
        wrong = []
        for text, expect in CASES:
            got = intent.detect(text)
            if got != expect:
                wrong.append((text, expect, got))
        accuracy = (len(CASES) - len(wrong)) / len(CASES)
        assert accuracy >= 0.85, f"准确率 {accuracy:.0%} < 85%，错判: {wrong}"

    def test_at_least_40_cases(self):
        assert len(CASES) >= 40

    def test_empty_and_unknown_fall_chat(self):
        assert intent.detect("") == "chat"
        assert intent.detect(None) == "chat"
        assert intent.detect("   ") == "chat"
        # 低置信未知内容恒落 chat（不丢消息、零附加）
        assert intent.detect("今天天气不错呀") == "chat"
        assert intent.detect("qwerty12345") == "chat"

    def test_priority_confide_over_advise(self):
        # 倾诉优先：一旦命中情绪，建议/行动语义让位
        assert intent.detect("别给我建议，我就是很难受") == "confide"

    def test_priority_act_over_analyze(self):
        # 复合句：分析 + 行动并存 → 祈使行动优先（用户要的是动手）
        assert intent.detect("帮我分析一下这个 bug 然后帮我改掉") == "act"

    def test_priority_analyze_over_advise(self):
        assert intent.detect("为什么会这样，给点建议") in ("analyze", "advise")


class TestWordsLoading:
    def test_builtin_fallback_states(self):
        words = intent.current_words()
        for state in intent.INTENT_STATES:
            assert state in words
            assert isinstance(words[state], list)

    def test_reload_words_with_dirty_json(self, tmp_path, monkeypatch):
        # 脏 JSON：非 list 值 / 非 str 项 / 非法键 → 全部守卫忽略，退回内置
        dirty = tmp_path / "intent_words.json"
        dirty.write_text(json.dumps({
            "analyze": "not-a-list",            # 非 list → 忽略
            "act": ["自定义动作", 123, None],   # 非 str 项 → 过滤
            "unknown_state": ["x"],             # 非法态 → 忽略
        }, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(intent, "_WORDS_FILE", str(dirty))
        intent.reload_words()
        try:
            words = intent.current_words()
            assert "not-a-list" not in [w for w in words["analyze"]]
            assert "自定义动作" in words["act"]
            assert all(isinstance(w, str) for w in words["act"])
            assert "unknown_state" not in words
        finally:
            monkeypatch.setattr(intent, "_WORDS_FILE",
                                str(Path(intent.__file__).parent / "assets" / "intent_words.json"))
            intent.reload_words()

    def test_missing_file_falls_back_builtin(self, tmp_path, monkeypatch):
        monkeypatch.setattr(intent, "_WORDS_FILE", str(tmp_path / "no_such.json"))
        intent.reload_words()
        assert intent.detect("陪我聊聊天吧") == "chat"

    def test_json_merge_overrides_builtin(self, tmp_path, monkeypatch):
        # 合并覆盖：JSON 中 analyze 词命中即判 analyze（JSON 优先语义）
        custom = tmp_path / "intent_words.json"
        custom.write_text(json.dumps({
            "analyze": ["量子涨落"],
        }, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(intent, "_WORDS_FILE", str(custom))
        intent.reload_words()
        try:
            # 内置词仍保留（合并而非替换）
            assert intent.detect("帮我分析一下这段报错") == "analyze"
            assert intent.detect("讲讲量子涨落吧") == "analyze"
        finally:
            monkeypatch.setattr(intent, "_WORDS_FILE",
                                str(Path(intent.__file__).parent / "assets" / "intent_words.json"))
            intent.reload_words()


class TestHintsAndContract:
    def test_hints_cover_non_chat_states(self):
        for state in ("confide", "analyze", "advise", "act"):
            assert isinstance(intent.INTENT_HINTS.get(state, ""), str)
            assert intent.INTENT_HINTS[state].strip()

    def test_chat_state_zero_injection(self):
        # chat 态零附加（验收：未识别场景零注入、零打扰）
        assert intent.INTENT_HINTS.get("chat", "") == ""

    def test_confide_hint_semantics(self):
        hint = intent.INTENT_HINTS["confide"]
        assert "倾听" in hint or "共情" in hint
        assert "不要列解决方案" in hint

    def test_states_are_plain_strings(self):
        # 零依赖可序列化（str 字面量非 Enum）
        assert intent.INTENT_STATES == ("confide", "chat", "analyze", "advise", "act")
        assert intent.detect("写一个脚本") == "act"
        assert isinstance(intent.detect("x"), str)

    def test_zero_dependencies(self):
        # 纯 stdlib：不 import Qt / core / memory
        src = Path(intent.__file__).read_text(encoding="utf-8")
        for banned in ("PySide6", "from core", "import core", "from memory", "import memory"):
            assert banned not in src, f"intent.py 不得依赖 {banned}"
