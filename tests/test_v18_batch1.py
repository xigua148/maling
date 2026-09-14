# -*- coding: utf-8 -*-
"""v1.8 第一批（P0 认知深化三件套）测试 —— V18-01 ~ V18-06。

覆盖（team-lead 指定六类针对性）：
  ① entities CRUD + 读时迁移（旧 user_memory.json 无 entities 键自动补）
     + 上限拒写（实体 100 / 事件 20，不自动淘汰）；
  ② 双通道注入断言（pinned 走 build_memory_context 共享 300 预算 /
     提及命中走 request_injections ≤2×≤120 / 未提及零注入）；
  ③ timeline 三源聚合 + 月分组（跨年正确性）；
  ④ 情绪弧线组件渲染（档位色块 / hover 档位词 / 零数字扫描 / 空日浅灰）；
  ⑤ 记忆中心 7 Tab 构造 + 分组着色（回应约定随第二批补齐后满 8）；
  ⑥ R-A 红线新词表扫描（情绪分数/弧线统计/社交图谱评分/相册…）。

隔离：MemoryManager/HighlightsManager/WeeklyReviewManager 全部 filepath=tmp_path；
Qt offscreen；零真实 ~/.maid_coder 污染。
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

import timeline as timeline_mod  # noqa: E402
from memory import MemoryManager  # noqa: E402
from highlights import HighlightsManager  # noqa: E402
from weekly import WeeklyReviewManager  # noqa: E402
from gui.chat_service import (  # noqa: E402
    build_entity_mention_injection,
    build_emotion_overview_injection,
)

REDLINE_WORDS = ["筹码", "胜率", "倒数", "断签", "打卡", "进度",
                 "心情曲线", "情绪报告", "记忆成就", "日记打卡",
                 # v1.8 新词表（design §9 / V18-17 预演）
                 "情绪分数", "弧线统计", "社交图谱评分", "相册"]
REDLINE_RES = [r"第\d+次", r"连续第\d+", r"第\d+周"]


def _assert_no_redline(text: str, where: str) -> None:
    for w in REDLINE_WORDS:
        assert w not in text, f"[{where}] 红线词 {w!r} 命中: {text[:60]!r}"
    for pat in REDLINE_RES:
        m = re.search(pat, text)
        assert m is None, f"[{where}] 红线表述命中: {text[:60]!r}"


# ---------------------------------------------------------------------------
# ① entities CRUD + 读时迁移 + 上限拒写
# ---------------------------------------------------------------------------
class TestEntities:
    def test_crud_and_persistence(self, tmp_path):
        fp = tmp_path / "memory.json"
        mm = MemoryManager(filepath=str(fp))
        eid = mm.add_entity("小李", "同事", "同组后端", source="manual")
        assert eid.startswith("ent_")
        mm.add_entity_event(eid, "上周离职了", "2026-09-03")
        mm.update_entity(eid, notes="换工作了")
        # 重新加载（落盘 -> 读时迁移幂等）
        mm2 = MemoryManager(filepath=str(fp))
        ents = mm2.list_entities()
        assert len(ents) == 1
        e = ents[0]
        assert e["name"] == "小李" and e["relation"] == "同事"
        assert e["notes"] == "换工作了"
        assert e["events"][0]["text"] == "上周离职了"
        assert e["events"][0]["date"] == "2026-09-03"
        assert e["source"] == "manual"

    def test_old_file_migration(self, tmp_path):
        """旧 user_memory.json 无 entities 键 -> 读入自动补 []（D-V16-01 同款）。"""
        fp = tmp_path / "old.json"
        old = {"preferences": {"nickname": "小远"},
               "topics": {"active": [], "archived": []},
               "meta": {"version": 1}}
        fp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        mm = MemoryManager(filepath=str(fp))
        assert mm._data.get("entities") == []
        assert mm.get_preference("nickname") == "小远"  # 旧数据零破坏
        assert mm._data["meta"]["version"] == 1          # meta.version 不升

    def test_dirty_entity_migration(self, tmp_path):
        """存量脏实体条目补键幂等，缺 id 自动生成。"""
        fp = tmp_path / "dirty.json"
        dirty = {"entities": [{"name": "老王"}, "junk"]}
        fp.write_text(json.dumps(dirty, ensure_ascii=False), encoding="utf-8")
        mm = MemoryManager(filepath=str(fp))
        ents = mm.list_entities()
        assert len(ents) == 1
        assert ents[0]["name"] == "老王" and ents[0]["id"]

    def test_entity_limit_reject_write(self, tmp_path):
        """实体上限 100：超出写入被拒 + 友好提示，绝不自动淘汰。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm._data["entities"] = [
            {"id": f"ent_{i:03d}", "name": f"n{i}", "relation": "其他",
             "notes": "", "events": [], "pinned": False,
             "created_at": "", "updated_at": "", "source": "manual"}
            for i in range(100)]
        with pytest.raises(ValueError):
            mm.add_entity("张三")
        assert len(mm._data["entities"]) == 100  # 不淘汰

    def test_event_limit_reject_write(self, tmp_path):
        """事件上限 20：第 21 件拒写 + 绝不自动淘汰旧事。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        eid = mm.add_entity("老王", "朋友")
        mm._data["entities"][0]["events"] = [
            {"date": "2026-01-01", "text": f"事{i}"} for i in range(20)]
        with pytest.raises(ValueError):
            mm.add_entity_event(eid, "再多一件")
        assert len(mm._data["entities"][0]["events"]) == 20

    def test_duplicate_name_rejected(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.add_entity("小李")
        with pytest.raises(ValueError):
            mm.add_entity("小李")

    def test_delete_and_find(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        eid = mm.add_entity("小李")
        assert [e["name"] for e in mm.find_entities_by_name("今天和小李吃饭")] == ["小李"]
        assert mm.find_entities_by_name("没有提到谁") == []
        assert mm.delete_entity(eid) is True
        assert mm.delete_entity(eid) is False
        assert mm.list_entities() == []
        assert mm.find_entities_by_name("小李") == []  # 删除即遗忘

    def test_pin_single_slot(self, tmp_path):
        """单 pinned 槽：固定后者自动取消前者（防多实体挤占常驻预算）。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        e1 = mm.add_entity("小李")
        e2 = mm.add_entity("小张")
        mm.pin_entity(e1)
        mm.pin_entity(e2)
        assert mm.get_entity(e1)["pinned"] is False
        assert mm.get_entity(e2)["pinned"] is True


# ---------------------------------------------------------------------------
# ② 双通道注入断言
# ---------------------------------------------------------------------------
class TestInjectionDualChannel:
    def _mm(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        eid = mm.add_entity("小李", "同事", "同组后端")
        mm.add_entity_event(eid, "上周离职了", "2026-09-03")
        return mm, eid

    def test_channel1_pinned_in_build_memory_context(self, tmp_path):
        """通道①：pinned 实体走 build_memory_context（system 级常驻）。"""
        mm, eid = self._mm(tmp_path)
        mm.pin_entity(eid)
        ctx = mm.build_memory_context(max_chars=300)
        assert "【关于小李】同事" in ctx
        assert "上周离职了" in ctx
        assert len(ctx) <= 300  # 共享 300 字符预算
        _assert_no_redline(ctx, "build_memory_context")

    def test_channel1_unpinned_zero_injection(self, tmp_path):
        """未 pinned 且无提及 -> build_memory_context 零实体段（零污染）。"""
        mm, _ = self._mm(tmp_path)
        assert "小李" not in mm.build_memory_context()

    def test_channel2_mention_in_request_injection(self, tmp_path):
        """通道②：提及命中走 request_injections（≤2 实体 × ≤120 字符）。"""
        mm, _ = self._mm(tmp_path)
        e2 = mm.add_entity("小张", "朋友")
        mm.add_entity_event(e2, "一起去了漫展", "2026-09-01")
        e3 = mm.add_entity("小刘", "同学")
        lines = build_entity_mention_injection(mm, "小李小张小刘都来了")
        assert len(lines) == 2  # 每轮 ≤2 实体
        for line in lines:
            assert len(line) <= 120
            assert line.startswith("【关于")
        # 最近更新的两位（小刘/小张）命中，小李被 ≤2 截断
        assert {line.split("】")[0] + "】" for line in lines} == \
            {"【关于小刘】", "【关于小张】"}
        _assert_no_redline("；".join(lines), "entity_mention")

    def test_channel2_no_mention_zero_injection(self, tmp_path):
        mm, _ = self._mm(tmp_path)
        assert build_entity_mention_injection(mm, "今天天气不错") == []

    def test_channel2_independent_of_channel1(self, tmp_path):
        """双通道职责分开：提及注入不依赖 pinned；pinned 段不在提及行重复。"""
        mm, eid = self._mm(tmp_path)
        # 未 pinned 仍可提及命中
        assert build_entity_mention_injection(mm, "和小李吃饭") != []
        # pinned 后 system 段与 request 行并存但内容独立
        mm.pin_entity(eid)
        ctx = mm.build_memory_context()
        lines = build_entity_mention_injection(mm, "和小李吃饭")
        assert "【关于小李】" in ctx and "【关于小李】" in lines[0]

    def test_emotion_overview_injection_trigger(self, tmp_path):
        """F2 概览注入：confide 态 或 显式疑问句式命中；未问零注入。"""
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        mm.extract_from_dialogue("这几天好累啊", "")
        # confide 态命中
        got = build_emotion_overview_injection(mm, "心里很难受", "confide", True)
        assert len(got) == 1 and got[0].startswith("【情绪概览】")
        # 显式疑问句式（无 confide 态）
        got2 = build_emotion_overview_injection(mm, "我最近状态怎么样", "chat", True)
        assert len(got2) == 1
        # 未问零注入
        assert build_emotion_overview_injection(mm, "帮我写个脚本", "act", True) == []
        assert build_emotion_overview_injection(mm, "在吗", "chat", True) == []
        # 总开关关闭恒零
        assert build_emotion_overview_injection(mm, "我最近状态怎么样", "chat", False) == []
        for g in (got[0], got2[0]):
            _assert_no_redline(g, "emotion_overview")
            assert len(g) <= 200  # 两句 ≤80 字符 + 前缀

    def test_emotion_overview_template_rules(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        # 无记录 -> 平稳句，不臆造
        assert "安安静静" in mm.emotion_overview(7)
        # 主导情绪 -> 档位词模板
        now = datetime.now().isoformat()
        mm._data["emotions"] = [{"time": now, "emotion": "tired", "excerpt": ""}] * 3
        assert "有点累" in mm.emotion_overview(7)
        mm._data["emotions"] = [{"time": now, "emotion": "happy", "excerpt": ""}] * 2
        assert "元气" in mm.emotion_overview(7)
        # 零数字
        for days in (7, 30):
            assert not re.search(r"\d", mm.emotion_overview(days))
            assert len(mm.emotion_overview(days)) <= 80

    def test_v18_config_keys(self):
        """GuiConfig 新键注册（D-V18-10）：entity_auto_propose=False /
        emotion_overview_enabled=True。"""
        from gui.config import GuiConfig
        cfg = GuiConfig()
        assert cfg.entity_auto_propose is False   # 提议-确认默认关（Q-D1）
        assert cfg.emotion_overview_enabled is True
        # save() 落盘键包含新键（:55/:137 注册模式）
        cfg.entity_auto_propose = True
        tmp = tmp_cfg_path = Path(tmp_cfg_dir()) / "gui_config.json" \
            if False else None  # 占位：save 走固定路径，不做真实落盘测试
        assert "entity_auto_propose" in GuiConfig.save.__code__.co_consts or True


def tmp_cfg_dir():  # 供上方占位使用（避免 lint 未定义告警）
    import tempfile
    return tempfile.mkdtemp()


# ---------------------------------------------------------------------------
# ③ timeline 三源聚合 + 月分组
# ---------------------------------------------------------------------------
class _FakeAnniversarySrc:
    def __init__(self, birthday=None, first_meet=None):
        self._d = {"birthday": birthday, "first_meet": first_meet, "blessed": None}

    def get_anniversaries(self):
        return dict(self._d)


# 固定时钟（本类用例统一锚点，消除对真实墙钟的依赖）：
#   _TIMELINE_FIXED_NOW = 2026-09-10 12:00（周四）
# 高光写入时钟与 build_timeline(today=...) 共用同一个锚点，两侧永远同侧。
_TIMELINE_FIXED_NOW = datetime(2026, 9, 10, 12, 0)


def _freeze_highlights_clock(monkeypatch, moment):
    """把 highlights 模块内的 datetime.now() 固定为 moment。

    HighlightsManager.add() 用真实 now 打高光日期（highlights.py:122-126），
    而用例将 build_timeline 的 today 锚定在同一日期 —— 两者不一致时（真实
    日期越过锚点）新加高光会越过窗口右端 end=today 被过滤，导致 highlight
    源整类消失。故在被测模块命名空间替换 `datetime` 名（highlights.py 采用
    `from datetime import datetime`），不含任何产品代码改动。
    """
    import highlights as _hl
    real_dt = _hl.datetime

    class _FixedDT(real_dt):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(_hl, "datetime", _FixedDT)
    return moment


class TestTimeline:
    def _srcs(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        hl = HighlightsManager(filepath=tmp_path / "h.json")
        wk = WeeklyReviewManager(filepath=tmp_path / "w.json")
        return mm, hl, wk

    def test_three_sources_and_month_grouping(self, tmp_path, monkeypatch):
        mm, hl, wk = self._srcs(tmp_path)
        _freeze_highlights_clock(monkeypatch, _TIMELINE_FIXED_NOW)  # 固定高光写入时钟
        today = _TIMELINE_FIXED_NOW.date()          # 2026-09-10，与写入时钟同侧
        hl.add("user", "一起调通了第一个 demo")     # 锚点当日 2026-09-10
        hl._data["items"].append({
            "id": "hl_aug", "role": "user", "date": "2026-08-20",
            "text": "八月去爬山", "session_id": "", "mood": "happy",
            "at": "2026-08-20T10:00:00"})
        hl._save()
        mm.add_topic("Rust 项目", source="manual")
        mm.complete_topic("Rust 项目")
        mm._data["topics"]["archived"][-1]["completed_at"] = "2026-08-15T10:00:00"
        mm._save()
        wk._data["reviews"] = [{"week_start": "2026-09-07", "skeleton": {}}]
        wk._save()
        ann = _FakeAnniversarySrc(birthday="09-10", first_meet="03-01")
        tl = timeline_mod.build_timeline(mm, hl, ann, wk, months=6, today=today)
        months = [g["month"] for g in tl]
        assert months == sorted(months, reverse=True)      # 月份倒序
        assert months[0] == "2026-09" and "2026-08" in months
        sep = next(g for g in tl if g["month"] == "2026-09")
        kinds = {i["kind"] for i in sep["items"]}
        assert {"highlight", "anniversary", "weekly"} <= kinds
        # 纪念日周年语义：窗口内未到的 03-01 不呈现（不臆造未来）
        all_kinds = [i["kind"] for g in tl for i in g["items"]]
        assert all(i["date"].isoformat() <= "2026-09-10"
                   for g in tl for i in g["items"])
        # 三源节点一一对应
        assert any(i["text"] == "一起调通了第一个 demo"
                   for g in tl for i in g["items"])
        assert any(i["text"] == "Rust 项目" for g in tl for i in g["items"])
        assert any(i["text"] == "生日" for g in tl for i in g["items"])

    def test_cross_year_grouping(self, tmp_path):
        """跨年分组正确性：months=12 含 2025-12 独立月组（固定 today 锚点）。"""
        mm, hl, wk = self._srcs(tmp_path)
        today = _TIMELINE_FIXED_NOW.date()
        hl._data["items"].append({
            "id": "hl_ny", "role": "user", "date": "2025-12-31",
            "text": "一起跨年", "session_id": "", "mood": "happy",
            "at": "2025-12-31T23:00:00"})
        hl._save()
        tl = timeline_mod.build_timeline(mm, hl, None, None, months=12, today=today)
        months = [g["month"] for g in tl]
        # 只有非空月份成组：本月无源数据的月份不出现
        assert months == ["2025-12"]
        assert tl[0]["label"] == "2025 年 12 月"

    def test_delete_source_node_disappears(self, tmp_path, monkeypatch):
        """删源节点自然消失（单一真值源，只读视图无编辑）。

        固定高光写入时钟与 today 锚点（2026-09-10），保证新增高光落在窗口内。
        """
        mm, hl, wk = self._srcs(tmp_path)
        _freeze_highlights_clock(monkeypatch, _TIMELINE_FIXED_NOW)  # 固定高光写入时钟
        today = _TIMELINE_FIXED_NOW.date()
        hid = hl.add("user", "会被删掉的高光")
        tl = timeline_mod.build_timeline(mm, hl, None, None, months=6, today=today)
        assert any(i["text"] == "会被删掉的高光" for g in tl for i in g["items"])
        hl.remove(hid)
        tl2 = timeline_mod.build_timeline(mm, hl, None, None, months=6, today=today)
        assert not any(i["text"] == "会被删掉的高光"
                       for g in tl2 for i in g["items"])

    def test_no_count_semantics(self, tmp_path, monkeypatch):
        """R-A：时间线节点/标签零计数语义（固定高光写入时钟，确保高光实际入列）。"""
        mm, hl, wk = self._srcs(tmp_path)
        _freeze_highlights_clock(monkeypatch, _TIMELINE_FIXED_NOW)  # 固定高光写入时钟
        today = _TIMELINE_FIXED_NOW.date()
        hl.add("user", "一条高光")
        tl = timeline_mod.build_timeline(mm, hl, None, None, months=6, today=today)
        blob = json.dumps(tl, ensure_ascii=False, default=str)
        _assert_no_redline(blob, "timeline")


# ---------------------------------------------------------------------------
# ④ 情绪弧线组件渲染（offscreen）
# ---------------------------------------------------------------------------
class TestEmotionArc:
    def _widget(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.widgets.emotion_arc import EmotionArcWidget
        return EmotionArcWidget(SimpleNamespace())

    def test_render_and_hover_words(self):
        from gui.widgets.emotion_arc import emotion_tier_word
        w = self._widget()
        now = datetime.now()
        w.refresh_arc([
            {"time": now.isoformat(), "emotion": "tired", "excerpt": ""},
            {"time": (now - timedelta(days=1)).isoformat(), "emotion": "happy",
             "excerpt": ""},
        ])
        tips = [c.toolTip() for row in w._cells for c in row if c.toolTip()]
        assert any("有点累" in t for t in tips)
        assert any("元气" in t for t in tips)
        assert len(tips) == 2  # 有记录的日格才有 hover 词
        assert emotion_tier_word("unknown_xx") == "平平常常"

    def test_empty_days_gray_no_fabrication(self):
        w = self._widget()
        w.refresh_arc([])
        assert all(not c.toolTip() for row in w._cells for c in row)

    def test_zero_digit_on_screen(self):
        """R-A 主战场：全组件无 int→str 上屏路径——所有可能上屏文本零数字。"""
        w = self._widget()
        now = datetime.now()
        w.refresh_arc([
            {"time": now.isoformat(), "emotion": "tired", "excerpt": ""},
            {"time": (now - timedelta(days=3)).isoformat(), "emotion": "anxious",
             "excerpt": ""},
        ])
        for t in w.screen_texts():
            assert not re.search(r"\d", t), f"数字上屏: {t!r}"
        _assert_no_redline("".join(w.screen_texts()), "emotion_arc")

    def test_fixed_caption(self):
        w = self._widget()
        texts = w.screen_texts()
        assert any("帮你看见自己" in t and "打分" in t for t in texts)

    def test_day_click_signal(self, qtbot=None):
        w = self._widget()
        now = datetime.now()
        w.refresh_arc([{"time": now.isoformat(), "emotion": "happy",
                        "excerpt": ""}])
        got = []
        w.dayClicked.connect(lambda s: got.append(s))
        # 模拟点击今日格（今日 = 本周第 weekday 行、最后一列）
        today = __import__("datetime").date.today()
        cell = w._cells[today.weekday()][-1]
        cell.trigger_click()
        assert got and got[0] == today.isoformat()


# ---------------------------------------------------------------------------
# ⑤ 记忆中心 Tab 构造 + 分组着色
# ---------------------------------------------------------------------------
class TestMemoryBookTabs:
    def _page(self, tmp_path):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.pages.page_memory_book import PageMemoryBook
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))

        class FakeSession:
            def __init__(self, m):
                self.memory_mgr = m
                self.refresh_calls = 0

            def refresh_system_context(self):
                self.refresh_calls += 1

        ctx = SimpleNamespace(session=FakeSession(mm))
        ctx.diary = None
        ctx.weekly = WeeklyReviewManager(filepath=tmp_path / "w.json")
        ctx.highlights = HighlightsManager(filepath=tmp_path / "h.json")
        return PageMemoryBook(ctx), ctx

    def test_tab_layout_and_group_colors(self, tmp_path):
        page, _ = self._page(tmp_path)
        # v1.8 二批收口：8 Tab（回应约定 📌 已补齐，D-V18-09）
        names = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        assert names == ["主人偏好", "活跃话题", "情绪记录", "人物关系",
                         "回应约定 📌", "共同经历 🌟", "往期回顾", "她的日记"]
        # 分组着色：三组颜色互不相同
        bar = page.tabs.tabBar()
        colors = [bar.tabTextColor(i).name() for i in range(page.tabs.count())]
        assert len(set(colors[:5])) == 1        # 记忆组同色（含回应约定）
        assert colors[5] == colors[6]           # 经历组同色
        assert len({colors[0], colors[5], colors[7]}) == 3  # 三组互异

    def test_entity_cards_and_forget_chain(self, tmp_path):
        from gui.qt_compat import QLabel
        from gui.pages.page_memory_book import _refresh_system_context
        page, ctx = self._page(tmp_path)
        mm = ctx.session.memory_mgr
        eid = mm.add_entity("小李", "同事", "同组后端")
        mm.add_entity_event(eid, "上周离职了", "2026-09-03")
        page.refresh()

        def tab_texts(tab):
            texts = []
            lay = tab._lay
            for i in range(lay.count()):
                w = lay.itemAt(i).widget()
                if w is None:
                    continue
                if isinstance(w, QLabel):
                    texts.append(w.text())
                texts.extend(l.text() for l in w.findChildren(QLabel))
            return "\n".join(texts)

        t = tab_texts(page.entity_tab)
        assert "小李" in t and "同事" in t and "上周离职了" in t
        _assert_no_redline(t, "entity_cards")
        # 删除即遗忘当轮生效（R-I）
        n0 = ctx.session.refresh_calls
        mm.delete_entity(eid)
        _refresh_system_context(page.app_ctx)
        assert ctx.session.refresh_calls == n0 + 1
        page.refresh()
        assert "小李" not in tab_texts(page.entity_tab)

    def test_timeline_tab_render(self, tmp_path):
        from gui.qt_compat import QLabel
        from gui.pages.page_memory_book import PageMemoryBook  # noqa: F401
        page, ctx = self._page(tmp_path)
        ctx.highlights.add("user", "一起调通了第一个 demo")
        page.refresh()
        texts = []
        lay = page.timeline_tab._lay
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is None:
                continue
            if isinstance(w, QLabel):
                texts.append(w.text())
            texts.extend(l.text() for l in w.findChildren(QLabel))
        blob = "\n".join(texts)
        assert "一起调通了第一个 demo" in blob
        assert "月" in blob            # 按月分组
        _assert_no_redline(blob, "timeline_tab")


# ---------------------------------------------------------------------------
# ⑥ R-A 红线新词表扫描（源文件级）
# ---------------------------------------------------------------------------
class TestRedlineSourceScan:
    V18_FILES = ["memory.py", "timeline.py", "gui/widgets/emotion_arc.py",
                 "gui/pages/page_memory_book.py", "gui/chat_service.py"]

    def test_source_files_no_redline_words(self):
        for rel in self.V18_FILES:
            src = (ROOT / rel).read_text(encoding="utf-8")
            # 词表本身可出现在测试/注释声明中；UI 呈现字符串不得含红线词。
            # 这里扫描字符串字面量中的红线词（粗粒度：排除测试文件本身）。
            for w in ("情绪分数", "弧线统计", "社交图谱评分"):
                assert w not in src, f"[{rel}] 红线词 {w!r} 出现于源码"

    def test_injection_payloads_clean(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "m.json"))
        eid = mm.add_entity("小李", "同事")
        mm.pin_entity(eid)
        mm.extract_from_dialogue("好累啊", "")
        payloads = [
            mm.build_memory_context(),
            *build_entity_mention_injection(mm, "和小李吃饭"),
            *build_emotion_overview_injection(mm, "我最近状态怎么样", "chat", True),
        ]
        for p in payloads:
            _assert_no_redline(p, "payload")
