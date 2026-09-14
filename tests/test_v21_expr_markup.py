# -*- coding: utf-8 -*-
"""v2.1(UI-Fix-0912-3) 表情标记协议 —— 变体剥离 + 流式零穿帮回归。

背景（用户实测报告）：
    指南给模型的是「happy=开心微笑」这种「id=中文描述」，模型很自然地会输出
    `[[表情:开心]]`（中文名）、`[表情:happy]`（单方括号）或 `[[表情:]]`（空值）。
    原正则只认 `[[表情:ascii_id]]`，这些变体全部**漏进聊天正文** ——
    用户看到 `[[表情:开心]]` 这种协议文本，反馈「表情这个功能很搞笑，根本不知道是什么」。
"""
from __future__ import annotations

import pytest

from gui.expr_markup import MarkupStreamFilter, final_expression

# (说明, 输入, 期望正文, 期望最终表情)
VARIANT_CASES = [
    ("双方括号+英文 id", "主人好呀 [[表情:happy]]", "主人好呀", "happy"),
    ("单方括号", "主人好呀 [表情:happy]", "主人好呀", "happy"),
    ("中文名", "主人好呀 [[表情:开心]]", "主人好呀", "happy"),
    ("中文全名（指南原文）", "主人好呀 [[表情:开心微笑]]", "主人好呀", "happy"),
    ("全角冒号+中文名", "主人好呀 [[表情：害羞]]", "主人好呀", "shy"),
    ("空值", "主人好呀 [[表情:]]", "主人好呀", None),
    ("英文 key", "主人好呀 [[expression:happy]]", "主人好呀", "happy"),
    ("emo 简写", "主人好呀 [emo:clap]", "主人好呀", "clap"),
    ("多标记取最后", "[[表情:thinking]]想好了 [[表情:clap]]", "想好了", "clap"),
]


@pytest.mark.parametrize("tag,src,want_body,want_expr", VARIANT_CASES)
def test_variant_markup_stripped(tag, src, want_body, want_expr):
    """所有变体都必须从正文剥离，且尽量解析出表情 id。"""
    body, _ids, last = final_expression(src)
    assert "表情" not in body, f"[{tag}] 协议文本泄漏进正文: {body!r}"
    assert "expression" not in body.lower(), f"[{tag}] 泄漏: {body!r}"
    assert "[" not in body, f"[{tag}] 残留方括号: {body!r}"
    assert body == want_body, f"[{tag}] 正文不符: {body!r} != {want_body!r}"
    assert last == want_expr, f"[{tag}] 表情解析不符: {last!r} != {want_expr!r}"


@pytest.mark.parametrize(
    "src,keep",
    [
        ("数组 arr[0] 和 [链接] 应保留", "arr[0]"),
        ("主人好呀（开心地笑了）", "开心地笑"),
        ("看这个 [1,2,3] 列表", "[1,2,3]"),
    ],
)
def test_non_markup_brackets_preserved(src, keep):
    """非协议方括号不得被误吞（否则会破坏正常正文）。"""
    body, _ids, _last = final_expression(src)
    assert keep in body, f"误吞了正常内容: {body!r}"


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, None])
@pytest.mark.parametrize(
    "src,want_out,want_captured",
    [
        ("[[表情:开心]]主人好", "主人好", ["happy"]),
        ("[表情:happy]主人好", "主人好", ["happy"]),
        ("前文[[表情:害羞]]后文", "前文后文", ["shy"]),
        ("[[表情:clap]]做完啦", "做完啦", ["clap"]),
    ],
)
def test_stream_filter_no_leak(chunk_size, src, want_out, want_captured):
    """流式过滤器：任意切块粒度下都不得泄漏标记，也不得多漏 ']'。"""
    f = MarkupStreamFilter()
    if chunk_size is None:
        out = f.feed(src)
    else:
        out = "".join(f.feed(src[i:i + chunk_size]) for i in range(0, len(src), chunk_size))
    out += f.flush()
    assert "表情" not in out, f"[chunk={chunk_size}] 泄漏: {out!r}"
    assert out == want_out, f"[chunk={chunk_size}] 输出不符: {out!r} != {want_out!r}"
    assert f.captured == want_captured, f"[chunk={chunk_size}] 捕获不符: {f.captured}"


@pytest.mark.parametrize("chunk_size", [1, 2, 5])
def test_stream_filter_preserves_plain_brackets(chunk_size):
    """流式下普通方括号必须原样保留。"""
    src = "数组arr[0]要保留"
    f = MarkupStreamFilter()
    out = "".join(f.feed(src[i:i + chunk_size]) for i in range(0, len(src), chunk_size))
    out += f.flush()
    assert out == src, f"[chunk={chunk_size}] 误改正文: {out!r}"
    assert f.captured == []
