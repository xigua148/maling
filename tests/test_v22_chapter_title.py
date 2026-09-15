"""tests/test_v22_chapter_title.py —— 章标题归属修复（V22-10 后续 · 真实缺陷回归）。

背景（真实缺陷）：``TavernService._chapter_title`` 原实现只比对 ``chapter.get("id") == play["chapter_id"]``。
但内容包章键是 ``chapter_id``（不是 ``id``）→ 比较**永不成立** → 恒回落 ``play["title"]``；
且 ``chapter_id`` 是硬禁区字段（``engine._CROSS_CHAPTER_FIELDS``），**全仓无写入点、恒为 ch1**。
二者叠加 → HUD 顶部那条**永远显示书/局标题**，玩家看不到真正的章标题。

修复：以**当前 ``node_id`` 归属的章**为真值来源，三级回落（node_id → chapter_id(双键) → 局标题），
纯读、不写任何 state。

本文件用**真实内容包** ``load_content("lantern")`` 断言（不 monkeypatch 内容包）。offscreen / 零墙钟。
"""
from __future__ import annotations

import copy
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gui.qt_compat import QApplication  # noqa: E402

from gui.tavern import model as m  # noqa: E402
from gui.tavern import worldbook as wb  # noqa: E402
from gui.tavern.service import TavernService  # noqa: E402

#: 真实内容包章节标题（与 content/lantern/chapters.json 锚定；≠ 书标题）。
CH1_TITLE = "灯笼还亮着"
CH2_TITLE = "雨夜来客"
CH3_TITLE = "天亮之前"
BOOK_TITLE = "灯笼酒馆"


def _qapp() -> "QApplication":
    return QApplication.instance() or QApplication([])


def _app_ctx() -> SimpleNamespace:
    return SimpleNamespace(
        api=None, cfg=None, companion=None, intimacy=None,
        theme_engine=None, config=None, logger=None,
    )


@pytest.fixture(scope="module")
def svc(tmp_path_factory) -> TavernService:
    """真实 service（tmp 存档目录，绝不碰 ~/.maid_coder），内容包走真实解析入口。"""
    _qapp()
    base = tmp_path_factory.mktemp("tavern_title")
    return TavernService(_app_ctx(), base_dir=base, synchronous=True)


def _play(node_id: str = "opening", chapter_id: str = "ch1",
          title: str = BOOK_TITLE, book_id: str = "lantern") -> dict:
    play = m.new_play(book_id, title, 1)
    play["node_id"] = node_id
    play["chapter_id"] = chapter_id
    return play


# ===========================================================================
# 0. 锚定：真实内容包的章/书标题确如所期
# ===========================================================================

def test_content_pack_titles_are_anchored():
    content = wb.load_content("lantern")
    titles = {ch.get("chapter_id"): ch.get("title") for ch in content["chapters"]}
    assert titles.get("ch1") == CH1_TITLE
    assert titles.get("ch2") == CH2_TITLE
    assert titles.get("ch3") == CH3_TITLE
    book_title = content["worldbook"].get("title")
    assert book_title == BOOK_TITLE
    # 关键：章标题 ≠ 书标题（原缺陷正是把章标题显示成了书标题）
    assert CH1_TITLE != BOOK_TITLE


# ===========================================================================
# 1. 一级回落：按当前 node_id 归属的章
# ===========================================================================

def test_chapter_title_follows_node_id_in_ch1(svc):
    play = _play(node_id="opening")
    assert svc._chapter_title(play) == CH1_TITLE
    # ★ 抓原缺陷：绝不是书标题
    assert svc._chapter_title(play) != BOOK_TITLE


def test_chapter_title_follows_node_id_in_ch2(svc):
    for node in ("guest_arrives", "table_talk", "letter_open", "wine_taste"):
        assert svc._chapter_title(_play(node_id=node)) == CH2_TITLE, node


def test_chapter_title_follows_node_id_in_ch3(svc):
    for node in ("last_call", "photo_person", "guest_thanks", "ending_dawn"):
        assert svc._chapter_title(_play(node_id=node)) == CH3_TITLE, node


def test_node_id_beats_misleading_chapter_id(svc):
    """node_id 是真值来源：即便 chapter_id 谎报 ch1，也应按真实所在章返回。"""
    play = _play(node_id="photo_person", chapter_id="ch1")   # 节点在 ch3
    assert svc._chapter_title(play) == CH3_TITLE


# ===========================================================================
# 2. 二级回落：chapter_id（两个键都认）
# ===========================================================================

def test_fallback_to_chapter_id_when_node_unknown(svc):
    # 未知 node_id + 合法 chapter_id → 按 chapter_id 找回章标题
    assert svc._chapter_title(_play(node_id="does_not_exist", chapter_id="ch2")) == CH2_TITLE
    assert svc._chapter_title(_play(node_id="", chapter_id="ch3")) == CH3_TITLE


def test_fallback_accepts_legacy_id_key(svc, monkeypatch):
    """旧写法章键为 ``id``（非 ``chapter_id``）时，二级回落仍能命中。"""
    legacy = {
        "chapters": [{"id": "ch1", "title": CH1_TITLE, "nodes": []}],
    }
    monkeypatch.setattr(svc, "_content_for", lambda book_id: legacy)
    assert svc._chapter_title(_play(node_id="unknown", chapter_id="ch1")) == CH1_TITLE


# ===========================================================================
# 3. 三级回落与退化输入（不抛）
# ===========================================================================

def test_fallback_to_play_title_when_nothing_matches(svc):
    play = _play(node_id="unknown", chapter_id="ch9", title="某一夜")
    assert svc._chapter_title(play) == "某一夜"


def test_degenerate_play_returns_empty_not_crash(svc):
    assert svc._chapter_title(None) == ""        # 非 dict
    assert svc._chapter_title({}) == ""          # 空 dict（无 title 可回落）
    # 缺 chapters 的内容包也不抛，回落局标题
    monkey_ok = {"chapters": None}
    svc._content_cache["lantern"] = monkey_ok    # 仅本用例内破坏缓存，随后还原
    try:
        assert svc._chapter_title(_play(node_id="opening", title="局标题回落")) == "局标题回落"
    finally:
        svc._content_cache.clear()


def test_chapter_title_is_pure_read(svc):
    """纯读：调用前后 play 逐字段不变（不写 vars / node_id / chapter_id / turn）。"""
    play = _play(node_id="photo_person")
    before = copy.deepcopy(play)
    svc._chapter_title(play)
    assert play == before
