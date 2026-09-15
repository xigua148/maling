#!/usr/bin/env python3
"""校验 `_frozen_contract_baseline.sha256` 与当前工作区是否逐字节一致。

**为什么需要它**（第五轮验证 P2 的根修）：基线文件曾出现「手抄 hash 出错」——
人肉把 sha256 抄进基线，抄错了基线反而成为误导源。本脚本把「计算」与「比对」
合并为一步：要么直接用它**生成/刷新**基线（`--write`），要么**校验**（默认），
全程不允许任何手抄。

用法（仓库根目录）：
    python tools/check_frozen_baseline.py            # 校验，全部匹配 rc=0，有漂移 rc=1
    python tools/check_frozen_baseline.py --write    # 用当前文件实测值刷新基线的 hash 段

注意：`sha256sum -c` 对本基线文件**不可用**（基线是 CRLF，GNU coreutils 会报
"improperly formatted"）——这正是当初想手抄的诱因之一，本脚本两端都用 LF 写出。

基线格式：`<64位hex><两个空格><相对路径>` 行（兼容 sha256sum 文本格式），
`#` 开头为注释，`NAME = 值` 行为冻结常量记录（本脚本只校验 hash 行）。
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "_frozen_contract_baseline.sha256"

_HASH_LINE = re.compile(r"^([0-9a-f]{64})  (.+)$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse(text: str) -> list[tuple[str, str]]:
    out = []
    for line in text.splitlines():
        mm = _HASH_LINE.match(line.strip())
        if mm:
            out.append((mm.group(1), mm.group(2)))
    return out


def main(argv: list[str]) -> int:
    write = "--write" in argv
    if not BASELINE.exists():
        print(f"[FATAL] 基线文件不存在：{BASELINE}", file=sys.stderr)
        return 2

    original = BASELINE.read_text(encoding="utf-8")
    entries = _parse(original)
    if not entries:
        print("[FATAL] 基线里没有任何 hash 行（文件被清空/损坏？）", file=sys.stderr)
        return 2

    if write:
        # 用实测值重写每一行 hash（路径与其余内容原样保留），LF 输出。
        replaced = 0
        lines = []
        lookup = {p: h for h, p in entries}
        for line in original.splitlines():
            mm = _HASH_LINE.match(line.strip())
            if mm:
                path = REPO / mm.group(2)
                if path.exists():
                    actual = _sha256(path)
                    if actual != mm.group(1):
                        replaced += 1
                    lines.append(f"{actual}  {mm.group(2)}")
                    continue
            lines.append(line)
        BASELINE.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"[OK] 基线已刷新：改写 {replaced} 行（其余本就一致），LF 换行。")
        return 0

    fail = 0
    for want, rel in entries:
        path = REPO / rel
        if not path.exists():
            print(f"[MISSING] {rel}")
            fail += 1
            continue
        actual = _sha256(path)
        if actual != want:
            print(f"[DRIFT]   {rel}\n          基线 {want}\n          实测 {actual}")
            fail += 1
        else:
            print(f"[ok]      {rel}")
    total = len(entries)
    if fail:
        print(f"\n结果：{fail}/{total} 不匹配 —— 若为经批准的改动，跑 `--write` 刷新并注明原因。")
        return 1
    print(f"\n结果：全部 {total} 个文件逐字节一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
