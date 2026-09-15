"""tests/test_v22_content_path.py —— 内容包「两态路径」守卫（源码态 vs 打包态，design-v22 §3.2 附注）。

**独立文件**（不并入 ``test_v22_worldbook.py``，避免与并行写者撞车）。

锁住那个「测试全绿但真机读不到」的经典盲区 —— 内容包随包依赖 spec ``datas`` 的
**target 必须等于「源码相对 `gui/` 的路径」**（``source_dir == gui/<target>``）。
四段断言：

    1. **源码态**：``get_resource_path("tavern/content/lantern/book.json").exists()`` 为真；
    2. **模拟打包态**：monkeypatch ``sys.frozen=True`` + ``sys._MEIPASS`` → 临时目录，
       并按 spec 的 target 规则在其下铺一份最小 content，断言同样能读到（且 content_dir /
       load_builtin_book / load_content 全通）；
    3. **反向守卫**：``get_resource_path("tavern_content")`` 不存在 —— 防有人改回错误形态
       （该写法源码态会静默读空）；
    4. **spec 声明守卫**：解析两个 ``*.spec`` 的 ``datas``，断言声明了
       ``('gui/tavern/content', 'tavern/content')``。**spec 批 3/批 5 才改** → 尚未声明时
       **skip 并打印提示**（不现在写死为必红），就位后自动转强断言；一旦出现
       ``source=gui/tavern/content`` 但 target 错，则**立即失败**。

零 Qt、纯函数（不建 QApplication，不受墙钟影响）。
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import List, Set, Tuple

import pytest

from gui.utils import get_resource_path
from gui.tavern import worldbook as wb

REPO = Path(__file__).resolve().parent.parent
SPEC_FILES: Tuple[str, ...] = ("maid_coder_gui.spec", "maid_coder_gui_onefile.spec")

#: spec ``datas`` 的正确形态（§3.2 唯一规则：target = 源码相对 gui/ 的路径）。
EXPECTED_SOURCE = "gui/tavern/content"
EXPECTED_TARGET = "tavern/content"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _write_minimal_pack(root: Path) -> None:
    """按 spec 的 target 规则在 ``root`` 下铺一份最小 content（``root/tavern/content/lantern/*``）。"""
    pack = root / EXPECTED_TARGET / "lantern"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "book.json").write_text(
        json.dumps(
            {"book_id": "lantern", "entries": [{"uid": 1, "title": "t", "keys": ["k"], "content": "c"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pack / "chapters.json").write_text(
        json.dumps({"book_id": "lantern", "reachable": {"": ["counter"]}, "chapters": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (pack / "transforms.json").write_text(
        json.dumps({"book_id": "lantern", "var_names": ["v"]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _string_pairs(text: str) -> Set[Tuple[str, str]]:
    """AST 提取源码里所有「两个字符串常量」组成的两元组（= 可能的 spec datas 条目）。

    与写法无关（``datas=[...]`` / ``datas += [...]`` 皆可命中），只认字符串字面量；
    解析失败或非字面量（如 ``os.path.join(...)``）→ 忽略（宁可漏检 → skip，不误报）。
    """
    pairs: Set[Tuple[str, str]] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - spec 语法必合法
        return pairs
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List)) and len(node.elts) == 2:
            first, second = node.elts
            if (
                isinstance(first, ast.Constant)
                and isinstance(second, ast.Constant)
                and isinstance(first.value, str)
                and isinstance(second.value, str)
            ):
                pairs.add((first.value, second.value))
    return pairs


# ---------------------------------------------------------------------------
# 1) 源码态
# ---------------------------------------------------------------------------

def test_source_mode_content_readable():
    # 源码态 base = <repo>/gui ⇒ "tavern/content" 解析到 gui/tavern/content
    assert get_resource_path("tavern/content") == REPO / "gui" / "tavern" / "content"
    assert get_resource_path("tavern/content/lantern/book.json").exists()
    for name in ("chapters.json", "transforms.json"):
        assert get_resource_path(f"tavern/content/lantern/{name}").exists()


# ---------------------------------------------------------------------------
# 2) 模拟打包态（sys.frozen + sys._MEIPASS）
# ---------------------------------------------------------------------------

def test_simulated_frozen_mode_content_readable(tmp_path, monkeypatch):
    _write_minimal_pack(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    # frozen 态 base = sys._MEIPASS ⇒ "tavern/content" 解析到 <MEIPASS>/tavern/content
    assert get_resource_path("tavern/content/lantern/book.json").exists()
    assert wb.content_dir() == (tmp_path / "tavern" / "content")

    result = wb.load_builtin_book("lantern")
    assert result.ok is True
    assert len(result.entries) == 1

    content = wb.load_content("lantern")
    assert content["book_id"] == "lantern"
    assert content["reachable"] == {"": ["counter"]}
    assert content["var_names"] == ["v"]


def test_simulated_frozen_mode_missing_pack_is_graceful(tmp_path, monkeypatch):
    # _MEIPASS 下没有 tavern/content ⇒ 非 strict 返回空壳（fail-closed），不崩
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert get_resource_path("tavern/content/lantern/book.json").exists() is False
    content = wb.load_content("lantern")
    assert content["reachable"] == {}
    assert content["node_ids"] == []


# ---------------------------------------------------------------------------
# 3) 反向守卫（错误形态 target=tavern_content）
# ---------------------------------------------------------------------------

def test_reverse_guard_wrong_target_absent():
    # 错误形态：把 datas target 写成 "tavern_content" —— 源码态会解析到 gui/tavern_content（静默读空）
    assert not get_resource_path("tavern_content").exists()
    # 语义提示：正确目录名是 tavern/content，不是 tavern_content
    assert get_resource_path("tavern/content").name == "content"


# ---------------------------------------------------------------------------
# 4) spec datas 声明守卫（尚未改 spec → skip；改错 target → 立即失败）
# ---------------------------------------------------------------------------

def test_spec_declares_content_datas():
    present = {name: REPO / name for name in SPEC_FILES if (REPO / name).exists()}
    if not present:
        pytest.skip(f"未找到 spec 文件：{SPEC_FILES}")

    declared: dict = {}
    for name, path in present.items():
        pairs = _string_pairs(path.read_text(encoding="utf-8"))
        declared[name] = [(s, t) for (s, t) in pairs if s == EXPECTED_SOURCE]

    if not any(declared.values()):
        pytest.skip(
            "spec 尚未声明内容包 datas（批 3/批 5 才改 spec）；"
            f"就位后本用例自动转强断言。期望条目: ({EXPECTED_SOURCE!r}, {EXPECTED_TARGET!r})。"
            f"当前各 spec 命中: { {n: v for n, v in declared.items()} }"
        )

    # 一旦有 source=gui/tavern/content 的声明 → target 必须正确（source_dir == gui/<target>）
    for name, entries in declared.items():
        for source, target in entries:
            assert target == EXPECTED_TARGET, (
                f"{name}: datas target 必须是 {EXPECTED_TARGET!r}（规则 source_dir == gui/<target>），实为 {target!r}"
            )
            assert source == f"gui/{target}", f"{name}: {source!r} 与 target {target!r} 不满足 gui/<target> 规则"

    assert any((EXPECTED_SOURCE, EXPECTED_TARGET) in entries for entries in declared.values()), (
        "至少一个 spec 应精确声明 "
        f"({EXPECTED_SOURCE!r}, {EXPECTED_TARGET!r})"
    )
