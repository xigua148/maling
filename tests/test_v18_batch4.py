# -*- coding: utf-8 -*-
"""v1.8 第四批测试（F7 影像记忆 V18-14/15/16，D-V18-08）。

覆盖（team-lead 指定六类针对性）：
  ① 影像记忆数据层：50 条滚动淘汰、读时迁移、CRUD（memory.py）；
  ② 发送成功钩子：带图成功落一条；无图 / 失败 / 取消 / demo 零落；
  ③ 召回注入：指代句式命中引用真实内容；无记忆只注入诚实文案不编造；
  ④ R-I 硬线断言：user_memory.json 无 base64 / data URI，恶意存量消毒；
  ⑤ 角色卡导出白名单：vision_memories 永不入卡（export_card 断言）；
  ⑥ 群聊带图零写入：暂存在 _on_stream_finished 顶部分流前被丢弃。

隔离：MemoryManager 全部 tmp_path；Qt offscreen；零真实 ~/.maid_coder。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from memory import MemoryManager  # noqa: E402
from gui.chat_service import (  # noqa: E402
    ChatService,
    build_vision_recall_injection,
    first_paragraph_digest,
    vision_recall_hit,
    _VISION_HONESTY_TEXT,
)
from gui.role_card import EXPORT_FIELDS, export_card  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    from gui.qt_compat import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# 公共小件（test_v18_batch3 同款 harness）
# ---------------------------------------------------------------------------
class _FakeSession:
    def __init__(self, mm):
        self.memory_mgr = mm
        self.history = []


def _make_svc(tmp_path, mm=None):
    from gui.chat_service import ChatService as _CS  # noqa: F811
    mm = mm or MemoryManager(filepath=str(tmp_path / "m.json"))
    cfg = SimpleNamespace(api_key="test-key", chat_intent_mode="auto",
                          entity_auto_propose=False,
                          emotion_overview_enabled=True,
                          vision_memory_enhance=False,
                          scene_auto=False)
    app_ctx = SimpleNamespace(config=cfg, session=_FakeSession(mm))
    svc = ChatService(app_ctx)
    captured = []
    svc._launch_worker = lambda payload: captured.append(payload)
    return svc, captured, mm


_IMG_ATTACH = [{"name": "a.png", "ext": ".png", "path": "x.png", "size": 10}]


# ---------------------------------------------------------------------------
# ① 数据层：50 条滚动淘汰 + 读时迁移 + CRUD
# ---------------------------------------------------------------------------
class TestVisionDataLayer:
    def test_add_query_delete_roundtrip(self, tmp_path):
        fp = tmp_path / "memory.json"
        mm = MemoryManager(filepath=str(fp))
        vid = mm.add_vision_memory("这个报错怎么搞", "先看栈顶那行",
                                   "用户分享了一张图片")
        assert vid.startswith("vis_")
        # 重新加载（落盘 -> 读时迁移幂等）
        mm2 = MemoryManager(filepath=str(fp))
        items = mm2.list_vision_memories()
        assert len(items) == 1
        assert items[0]["user_text"] == "这个报错怎么搞"
        assert items[0]["assistant_digest"] == "先看栈顶那行"
        assert items[0]["image_note"] == "用户分享了一张图片"
        assert items[0]["source_mode"] == "default"
        assert items[0]["time"]  # ISO 时间在
        # 删除即遗忘
        assert mm2.delete_vision_memory(vid) is True
        assert mm2.list_vision_memories() == []
        assert mm2.delete_vision_memory("vis_nope") is False

    def test_rolling_eviction_keeps_newest_50(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "memory.json"))
        for i in range(55):
            mm.add_vision_memory(f"消息{i}", f"回应{i}")
        items = mm.list_vision_memories()
        assert len(items) == 50                       # 上限精确 50
        texts = {e["user_text"] for e in items}
        assert "消息0" not in texts and "消息4" not in texts   # 最旧 5 条被淘汰
        assert "消息54" in texts and "消息5" in texts          # 最新全部保留
        # 时间倒序：首条是最新
        assert items[0]["user_text"] == "消息54"

    def test_old_file_migration(self, tmp_path):
        """v1.7 旧文件无 vision_memories 键 -> 读时迁移补 []，meta.version 不升。"""
        fp = tmp_path / "memory.json"
        old = {"preferences": {"language": "python"},
               "meta": {"created_at": "2026-01-01T00:00:00",
                        "updated_at": "", "version": 1}}
        fp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        mm = MemoryManager(filepath=str(fp))
        assert mm.list_vision_memories() == []
        assert mm._data["meta"]["version"] == 1
        # 既有偏好数据经 v1.6 归一化结构（value/source/created_at/updated_at）
        assert mm._data["preferences"]["language"]["value"] == "python"

    def test_query_scoring_and_fallback(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mm.add_vision_memory("报错截图怎么搞", "先看栈顶")
        mm.add_vision_memory("晚饭吃什么", "推荐番茄牛腩")
        # 关键词重叠命中
        hits = mm.query_vision_memories(keyword="报错", limit=2)
        assert hits and hits[0]["user_text"] == "报错截图怎么搞"
        # 零命中回落时间倒序 top2（仍是真实存档，不编造）
        fb = mm.query_vision_memories(keyword="完全无关词", limit=2)
        assert len(fb) == 2

    def test_digest_helper(self):
        assert first_paragraph_digest("第一段回应\n\n第二段") == "第一段回应"
        assert first_paragraph_digest("x" * 80) == "x" * 50   # 50 字截断
        assert first_paragraph_digest("") == ""
        assert first_paragraph_digest("   \n  \n") == ""


# ---------------------------------------------------------------------------
# ② 发送成功钩子：带图成功落一条；无图/失败/取消/demo 零落
# ---------------------------------------------------------------------------
class TestVisionHook:
    def test_image_send_success_stores_one(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("这个报错怎么搞", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        assert svc._pending_vision is not None           # 暂存在
        assert svc._pending_vision["user_text"] == "这个报错怎么搞"
        svc._on_stream_finished("先看栈顶那行\n再看依赖版本", {"total_tokens": 5})
        items = mm.list_vision_memories()
        assert len(items) == 1                           # 成功路径恰好一条
        assert items[0]["user_text"] == "这个报错怎么搞"
        assert items[0]["assistant_digest"] == "先看栈顶那行"   # 首段摘要
        assert items[0]["image_note"] == "用户分享了一张图片"    # 中性描述
        assert svc._pending_vision is None               # 一次性消费

    def test_plain_text_zero_write(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("纯文本消息", task_type="chat", suppress_echo=True)
        assert svc._pending_vision is None
        svc._on_stream_finished("收到啦", {"total_tokens": 1})
        assert mm.list_vision_memories() == []

    def test_non_image_attachment_zero_write(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("看下日志", task_type="chat", suppress_echo=True,
                         attachments=[{"name": "a.txt", "ext": ".txt",
                                       "path": "a.txt", "size": 5}])
        assert svc._pending_vision is None
        svc._on_stream_finished("收到", {})
        assert mm.list_vision_memories() == []

    def test_cancelled_zero_write(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._on_stream_finished("半截回复", {"cancelled": True})
        assert mm.list_vision_memories() == []

    def test_api_error_clears_stash(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._on_api_error("boom")
        assert svc._pending_vision is None
        svc._on_stream_finished("不该被存", {})
        assert mm.list_vision_memories() == []

    def test_demo_mode_zero_write(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        svc._app_ctx.config.api_key = ""                 # 无 key → demo
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        assert svc._pending_vision is None               # demo 发送侧就不暂存
        svc._on_stream_finished("模拟回复", {})
        assert mm.list_vision_memories() == []

    def test_unrecognized_note_on_empty_uris(self, tmp_path, qapp):
        """诚实边界①：图片组装失败（未真正送达模型）→ 仍存但记「当时无法识别内容」。"""
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._mark_vision_viewed([])                      # 模拟 _launch_worker 空结果
        svc._on_stream_finished("我当时没能看到图", {})
        items = mm.list_vision_memories()
        assert len(items) == 1
        assert items[0]["image_note"] == "当时无法识别内容"

    def test_viewed_note_unchanged_with_uris(self, tmp_path, qapp):
        svc, _, _ = _make_svc(tmp_path)
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._mark_vision_viewed(["data:image/png;base64,xxx"])
        assert svc._pending_vision["image_note"] == "用户分享了一张图片"


# ---------------------------------------------------------------------------
# ③ 召回注入：指代命中引用真实内容；无记忆诚实文案；带新附件不召回
# ---------------------------------------------------------------------------
class TestVisionRecall:
    def test_pattern_variants(self):
        assert vision_recall_hit("上次那张图怎么回事")
        assert vision_recall_hit("之前发的截图你还记得吗")
        assert vision_recall_hit("昨天那张照片真好看")
        assert not vision_recall_hit("帮我画一张图")          # 无时间指代
        assert not vision_recall_hit("上次我们聊到哪了")        # 无图像词
        assert not vision_recall_hit("")
        assert not vision_recall_hit(None)

    def test_builder_injects_real_content_and_honesty(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mm.add_vision_memory("这个报错怎么搞", "先看栈顶那行")
        lines = build_vision_recall_injection(mm, "上次那张截图怎么样了")
        assert len(lines) == 2
        assert lines[0].startswith("【之前的分享】")
        assert "这个报错怎么搞" in lines[0]                   # 引用真实内容
        assert "先看栈顶那行" in lines[0]
        assert "只能记得当时的对话内容" in lines[1]             # R-K 诚实边界
        assert "无法重新查看图片本身" in lines[1]

    def test_builder_no_memory_honest_only(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "memory.json"))
        lines = build_vision_recall_injection(mm, "上次那张图呢")
        assert len(lines) == 1
        assert "没有留下相关记录" in lines[0]
        assert "无法重新查看图片本身" in lines[0]               # 诚实不编造

    def test_builder_zero_cost_without_pattern(self, tmp_path):
        mm = MemoryManager(filepath=str(tmp_path / "memory.json"))
        mm.add_vision_memory("带图消息", "回应")
        assert build_vision_recall_injection(mm, "普通聊天消息") == []
        assert build_vision_recall_injection(None, "上次那张图") == []

    def test_send_path_recall_with_memories(self, tmp_path, qapp):
        svc, captured, mm = _make_svc(tmp_path)
        mm.add_vision_memory("这个报错怎么搞", "先看栈顶那行")
        svc.send_message("上次那张截图怎么回事", task_type="chat",
                         suppress_echo=True)
        lines = captured[-1]["request_injections"]
        assert any("【之前的分享】" in l for l in lines)

    def test_send_path_skips_recall_with_new_attachment(self, tmp_path, qapp):
        """带新图当轮是新分享 → 不召回（指代句式命中也被附件条件抑制）。"""
        svc, captured, mm = _make_svc(tmp_path)
        mm.add_vision_memory("旧图消息", "旧回应")
        svc.send_message("上次那张截图我再发一次", task_type="chat",
                         suppress_echo=True, attachments=_IMG_ATTACH)
        lines = captured[-1]["request_injections"]
        assert not any("【之前的分享】" in l for l in lines)


# ---------------------------------------------------------------------------
# ④ R-I 硬线：文件零二进制 + 恶意存量消毒
# ---------------------------------------------------------------------------
class TestRIPrivacyHardLine:
    def test_file_never_contains_image_data(self, tmp_path):
        fp = tmp_path / "memory.json"
        mm = MemoryManager(filepath=str(fp))
        mm.add_vision_memory("带图消息", "回应摘要", "用户分享了一张图片")
        raw = fp.read_text(encoding="utf-8")
        assert "base64," not in raw
        assert "data:image" not in raw
        assert "data:application" not in raw

    def test_malicious_existing_entries_sanitized(self, tmp_path):
        """读时迁移消毒：存量字段携带 data URI / base64 痕迹 → 清空回落中性描述。"""
        fp = tmp_path / "memory.json"
        dirty = {"vision_memories": [
            {"id": "vis_bad1", "time": "2026-09-03T15:20:00",
             "user_text": "data:image/png;base64,iVBORw0KG",
             "assistant_digest": "看不清base64,AAAA",
             "image_note": "data:image/jpeg;base64,9j/4AA"},
            {"id": "vis_bad2", "time": "2026-09-04T10:00:00",
             "user_text": "正常文字", "assistant_digest": "正常回应",
             "image_note": "", "source_mode": "weird"},
        ]}
        fp.write_text(json.dumps(dirty, ensure_ascii=False), encoding="utf-8")
        mm = MemoryManager(filepath=str(fp))
        items = mm.list_vision_memories()                 # 时间倒序：09-04 在前
        by_id = {e["id"]: e for e in items}
        bad1, bad2 = by_id["vis_bad1"], by_id["vis_bad2"]
        assert bad1["user_text"] == ""                    # 恶意字段清空
        assert bad1["image_note"] == "用户分享了一张图片"     # 回落中性描述
        assert bad2["image_note"] == "用户分享了一张图片"     # 缺失回落
        assert bad2["user_text"] == "正常文字"               # 正常字段保留
        assert bad2["source_mode"] == "default"           # 非法枚举回落
        mm._save()   # 归一化数据回写后，磁盘上同样零图像数据痕迹
        raw = fp.read_text(encoding="utf-8")
        assert "base64," not in raw and "data:image" not in raw


# ---------------------------------------------------------------------------
# ⑤ 角色卡白名单：vision_memories 永不随卡导出（R-I）
# ---------------------------------------------------------------------------
class TestRoleCardWhitelist:
    def test_export_excludes_vision_memories(self):
        role = SimpleNamespace(name="码铃", description="d", system_prompt="s",
                               personality={"lively": 60, "rigorous": 40,
                                            "caring": 80},
                               opening_lines=["hi"], example_dialogues=[],
                               current_expression="normal", cover_image="")
        card = export_card(role)
        assert "vision_memories" not in card
        assert "vision_memories" not in EXPORT_FIELDS
        # 顺带：entities / response_rules 同样不入卡（第二批白名单回归）
        assert "entities" not in card and "response_rules" not in card


# ---------------------------------------------------------------------------
# ⑥ 群聊带图零写入：暂存在分流前被丢弃
# ---------------------------------------------------------------------------
class TestGroupZeroWrite:
    def test_group_active_drops_stash(self, tmp_path, qapp, monkeypatch):
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("大家看这张图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        assert svc._pending_vision is not None
        svc._group_active = True                          # 群聊轮
        monkeypatch.setattr(svc, "_on_group_stream_finished",
                            lambda text, usage: None, raising=False)
        svc._on_stream_finished("群聊回复", {"total_tokens": 3})
        assert mm.list_vision_memories() == []            # 零写入
        assert svc._pending_vision is None                # 暂存被丢弃（不串下一轮）

    def test_group_then_private_no_stale_write(self, tmp_path, qapp,
                                               monkeypatch):
        """群聊轮丢弃的暂存不会串到下一轮单聊（无图也落一条的陈旧串档）。"""
        svc, captured, mm = _make_svc(tmp_path)
        svc.send_message("看这张图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._group_active = True
        monkeypatch.setattr(svc, "_on_group_stream_finished",
                            lambda text, usage: None, raising=False)
        svc._on_stream_finished("群聊回复", {})            # 群聊轮：暂存被丢弃
        svc._group_active = False
        svc._on_stream_finished("随后的单聊回复", {})       # 单聊轮：暂存已空
        assert mm.list_vision_memories() == []            # 两轮均零写入


# ---------------------------------------------------------------------------
# ⑦ V18-16 UI：往期回顾 Tab 影像记忆条目（文字卡无缩略图）+ 删除链
# ---------------------------------------------------------------------------
class TestVisionMemoryTab:
    def _page(self, tmp_path):
        from PySide6.QtWidgets import QApplication, QLabel
        QApplication.instance() or QApplication([])
        from gui.pages.page_memory_book import PageMemoryBook
        from highlights import HighlightsManager
        from weekly import WeeklyReviewManager
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
        return PageMemoryBook(ctx), ctx, QLabel

    @staticmethod
    def _tab_texts(tab, QLabel):
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

    def test_vision_entries_render_text_cards(self, tmp_path):
        """有影像记忆 -> 文字卡呈现对话事实（无缩略图/无图像数据）。"""
        page, ctx, QLabel = self._page(tmp_path)
        ctx.session.memory_mgr.add_vision_memory(
            "这个报错怎么搞", "先看栈顶那行", "用户分享了一张图片")
        page.refresh()
        t = self._tab_texts(page.weekly_tab, QLabel)
        assert "这个报错怎么搞" in t          # 配文（对话事实）
        assert "先看栈顶那行" in t            # 当时回应
        assert "码铃只记得当时的对话" in t     # 诚实说明
        assert "data:image" not in t and "base64" not in t   # R-I：无图像痕迹

    def test_no_vision_zero_noise(self, tmp_path):
        """无影像记忆 -> 零额外条目（不打扰既有周记流）。"""
        page, ctx, QLabel = self._page(tmp_path)
        page.refresh()
        t = self._tab_texts(page.weekly_tab, QLabel)
        assert "那些发过的图" not in t

    def test_delete_chain_forget_immediately(self, tmp_path, monkeypatch):
        """删除链：物理移除 + 当轮 refresh_system_context + 列表消失（R-I）。"""
        page, ctx, QLabel = self._page(tmp_path)
        mm = ctx.session.memory_mgr
        vid = mm.add_vision_memory("带图消息", "回应")
        page.refresh()
        # 跳过确认弹窗（按文字选中「忘掉」按钮）
        monkeypatch.setattr("gui.pages.page_memory_book.QMessageBox.exec_",
                            lambda self: None)
        monkeypatch.setattr(
            "gui.pages.page_memory_book.QMessageBox.clickedButton",
            lambda self: next(b for b in self.buttons() if b.text() == "忘掉"))
        page._on_delete_vision(vid)
        assert mm.list_vision_memories() == []
        assert ctx.session.refresh_calls >= 1   # 删除即遗忘当轮生效
        page.refresh()
        assert "带图消息" not in self._tab_texts(page.weekly_tab, QLabel)


# ---------------------------------------------------------------------------
# ⑧ V18-17 R-K 三核对点（源码态 offscreen 等价验证）
# ---------------------------------------------------------------------------
class TestRKCheckpoints:
    def _page(self, tmp_path, mm=None, theme_engine=None):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from gui.pages.page_memory_book import PageMemoryBook
        from highlights import HighlightsManager
        from weekly import WeeklyReviewManager
        mm = mm or MemoryManager(filepath=str(tmp_path / "m.json"))

        class FakeSession:
            def __init__(self, m):
                self.memory_mgr = m

        ctx = SimpleNamespace(session=FakeSession(mm))
        ctx.diary = None
        ctx.weekly = WeeklyReviewManager(filepath=tmp_path / "w.json")
        ctx.highlights = HighlightsManager(filepath=tmp_path / "h.json")
        if theme_engine is not None:
            ctx.theme_engine = theme_engine
        return PageMemoryBook(ctx), ctx

    def test_rk1_memory_book_8_tabs_dark_mode(self, tmp_path):
        """R-K①：记忆中心 8 Tab 深色模式渲染（offscreen 深色 theme）。"""
        from gui.qt_compat import QFrame
        from gui.theme_engine import ThemeEngine
        engine = ThemeEngine()
        assert engine.set_theme_mode("dark") is True
        assert engine.load_theme("cute") is True
        dark_card = engine.get_color("bg_card", "#FFFFFF")
        assert dark_card.lower() != "#ffffff"            # 深色活动色板生效
        page, ctx = self._page(tmp_path, theme_engine=engine)
        ctx.session.memory_mgr.add_vision_memory("深色下的带图消息", "深色回应")
        page.refresh()   # 深色 theme 下全量重建（含影像记忆文字卡）
        names = [page.tabs.tabText(i) for i in range(page.tabs.count())]
        assert len(names) == 8                           # D-V18-09 满 8 Tab
        assert names[-2] == "往期回顾"
        # 影像条目卡在深色 theme 下取到深色卡底（_EntryCard 走 theme_color 动态取色）
        cards = [w for w in page.weekly_tab.findChildren(QFrame)
                 if (w.objectName() or "") == "memoryBookCard"]
        assert cards
        # 深色渲染断言：至少一张卡的样式表使用深色 bg_card（非浅色 fallback）
        assert any(dark_card.lower() in (c.styleSheet() or "").lower()
                   for c in cards)

    def test_rk2_role_card_v2_roundtrip_compat(self, tmp_path):
        """R-K②：角色卡 v2 导入导出兼容（v1 旧卡导入零回归 + v2 round-trip）。"""
        import gui.role_card as rc
        assert rc.SCHEMA_VERSION == 2
        role = SimpleNamespace(name="码铃", description="d", system_prompt="s",
                               personality={"lively": 60, "rigorous": 40,
                                            "caring": 80},
                               opening_lines=["hi"], example_dialogues=[],
                               current_expression="normal", cover_image="")
        card_v2 = rc.export_card(role)
        assert card_v2["schema_version"] == 2
        assert "cover_image" in card_v2
        # v2 卡再导入 → 字段一致（round-trip，dist 态同源逻辑）
        parsed = rc.parse_card(json.loads(json.dumps(card_v2)))
        assert parsed["name"] == "码铃"
        assert parsed["system_prompt"] == "s"
        # v1 旧卡（无 schema_version / cover_image）导入全兼容
        card_v1 = {k: v for k, v in card_v2.items()
                   if k not in ("schema_version", "cover_image")}
        parsed_v1 = rc.parse_card(card_v1)
        assert parsed_v1["name"] == "码铃"
        assert parsed_v1.get("cover_image", "") == ""

    def test_rk3_vision_memory_lands_in_maid_coder_dir(self, tmp_path, monkeypatch):
        """R-K③：影像记忆落位 ~/.maid_coder/user_memory.json（隔离 HOME 验证）。"""
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(os.path, "expanduser",
                            lambda p: str(fake_home / p.lstrip("~/")) if p.startswith("~/")
                            else str(fake_home / p))
        from memory import MemoryManager as _MM, _memory_path
        expected = fake_home / ".maid_coder" / "user_memory.json"
        assert str(_memory_path()) == str(expected)
        mm = _MM()                                       # 无 filepath → 默认路径
        vid = mm.add_vision_memory("落位验证消息", "落位回应")
        assert expected.exists()                          # 落位于 ~/.maid_coder/
        raw = expected.read_text(encoding="utf-8")
        assert "落位验证消息" in raw
        assert "base64," not in raw and "data:image" not in raw   # R-I 落盘也干净
        mm2 = _MM()                                       # 重启可读（持久化）
        items = mm2.list_vision_memories()
        assert len(items) == 1 and items[0]["id"] == vid


# ---------------------------------------------------------------------------
# 增强档开关（Q-D8 默认关）+ GuiConfig 注册
# ---------------------------------------------------------------------------
class TestEnhanceTierConfig:
    def test_config_default_off_and_roundtrip(self, tmp_path, monkeypatch):
        """GuiConfig.vision_memory_enhance 注册（D-V18-10）+ round-trip（APPDATA 隔离）。"""
        monkeypatch.setenv("APPDATA", str(tmp_path))
        from gui.config import GuiConfig
        cfg = GuiConfig()
        assert cfg.vision_memory_enhance is False         # Q-D8 默认关
        cfg.vision_memory_enhance = True
        cfg.save()
        cfg2 = GuiConfig.load()
        assert cfg2.vision_memory_enhance is True

    def test_hook_falls_back_when_enabled(self, tmp_path, qapp):
        """增强档开启但识别通道未接入 → 静默回落默认档（source_mode=default，不编造）。"""
        svc, captured, mm = _make_svc(tmp_path)
        svc._app_ctx.config.vision_memory_enhance = True
        svc.send_message("看图", task_type="chat", suppress_echo=True,
                         attachments=_IMG_ATTACH)
        svc._on_stream_finished("普通回应", {})
        items = mm.list_vision_memories()
        assert len(items) == 1
        assert items[0]["source_mode"] == "default"
