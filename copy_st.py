# -*- coding: utf-8 -*-
"""copy_st.py —— 内置 SillyTavern 源码树的「构建后复制」（v2.3.1）。

用法::

    python copy_st.py --dist dist/maling     # 打包后：把 ST 树搬进 <app>/_internal/sillytavern
    python copy_st.py --report-only          # 只报体积/文件数，不复制

============================ 为什么不用 PyInstaller 的 datas ============================

ST 树有 19,744 个文件（占 onedir 总文件数的 **54%**），而 PyInstaller 对它**不做任何处理**
—— 不编译、不分析、不裁剪，纯粹是逐文件搬运 + 记 TOC。把这部分交给 robocopy 在构建后搬运：

* **文件数**：onedir 的 COLLECT 从约 4 万降到 1.7 万 → 热构建 <1 分钟；
* **冷构建**：实测冷启动那 48 分钟里，绝大部分耗在「首次落盘 + 杀软逐文件扫描」——
  把 2 万文件移出 PyInstaller 的搬运范围，等于把这段开销一并削掉；
* **长路径**：ST 依赖树含 >260 字符的深路径，robocopy 原生支持；而 `shutil.copytree`
  在中文路径下会失败（本项目在 Pi 树上已踩过，当时也是回退 robocopy）；
* **续传**：`/E` 支持中断续传，npm 那类"挂死到一半"的事故不会让整棵树白拷一遍。

============================ ⚠️ 合规纪律（不可违反） ============================

* **整树原样复制、不做任何裁剪**。尤其**不得**按 `*.md` 之类通配排除：大量依赖包的
  许可文本名为 `LICENSE.md` / `README.md`，删掉会违反 AGPL-3.0 §4
  "keep intact all notices"，并把「原样捆绑」变成「已修改」—— 那会直接击穿 R-H 豁免的前提。
* 复制后**必须**做完整性自检（源/目标文件数一致），不达标即非零退出。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
SRC_DIR = REPO / "vendor" / "sillytavern"
DEST_NAME = "sillytavern"
ENTRY = "server.js"


def count_files(root: Path) -> int:
    """长路径安全计数（``\\\\?\\`` 前缀绕过 MAX_PATH）。"""
    n = 0
    prefixed = "\\\\?\\" + str(root.resolve())
    for _dirpath, _dirnames, filenames in os.walk(prefixed):
        n += len(filenames)
    return n


def dir_size(root: Path) -> int:
    total = 0
    prefixed = "\\\\?\\" + str(root.resolve())
    for dirpath, _dirnames, filenames in os.walk(prefixed):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def mb(n: int) -> str:
    return f"{n / 1048576:.1f}MB"


def post_pack(dist_dir: Path) -> None:
    """打包后模式：把 ST 树复制进 ``<app>/_internal/sillytavern/``。"""
    if not (SRC_DIR / ENTRY).is_file():
        raise RuntimeError(f"源树不完整（缺 {ENTRY}）：{SRC_DIR}")
    internal = dist_dir / "_internal"
    if not internal.is_dir():
        raise RuntimeError(f"目标不像 onedir 产物（缺 _internal）：{dist_dir}")
    dst = internal / DEST_NAME
    dst.mkdir(parents=True, exist_ok=True)

    print(f"复制 SillyTavern → {dst}")
    # /E 含空目录、/NFL /NDL /NJH /NJS /NP 抑制逐文件噪声；退出码 <8 均为成功
    rc = subprocess.run(["robocopy", str(SRC_DIR), str(dst),
                         "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]).returncode
    if rc >= 8:
        raise RuntimeError(f"robocopy 失败 rc={rc}")

    src_n = count_files(SRC_DIR)
    dst_n = count_files(dst)
    if src_n != dst_n:
        raise RuntimeError(
            f"完整性自检失败：源 {src_n} 文件 vs 目标 {dst_n} 文件 —— "
            "存在未落盘文件（长路径残留？），不得视为成功")
    # 入口与许可文本必须都在（前者运行时必需，后者合规必需）
    for must in (ENTRY, "LICENSE", "package.json"):
        if not (dst / must).is_file():
            raise RuntimeError(f"目标树缺少关键文件：{must}")
    print(f"完整性自检通过：{src_n} 文件 / {mb(dir_size(dst))}")
    print(f"入口校验通过：{ENTRY} + LICENSE + package.json")


def report_only() -> None:
    if not SRC_DIR.is_dir():
        raise SystemExit(f"源树不存在：{SRC_DIR}")
    n = count_files(SRC_DIR)
    print(f"源树: {SRC_DIR}")
    print(f"  文件数 = {n}")
    print(f"  体积   = {mb(dir_size(SRC_DIR))}")
    print(f"  入口   = {ENTRY} 存在: {(SRC_DIR / ENTRY).is_file()}")
    print(f"  许可   = LICENSE 存在: {(SRC_DIR / 'LICENSE').is_file()}")


def main() -> None:
    ap = argparse.ArgumentParser(description="内置 SillyTavern 源码树的构建后复制")
    ap.add_argument("--dist", help="打包后模式：dist/<app> 目录（其下应有 _internal/）")
    ap.add_argument("--report-only", action="store_true", help="只报体积/文件数，不复制")
    args = ap.parse_args()
    if args.report_only:
        report_only()
        return
    if not args.dist:
        raise SystemExit("需要 --dist <app 目录> 或 --report-only")
    post_pack(Path(args.dist).resolve())


if __name__ == "__main__":
    main()
