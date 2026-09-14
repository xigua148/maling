# -*- coding: utf-8 -*-
"""copy_pi_runtime.py —— Pi 运行时捆绑收集脚本（v1.7.3）。

把本机全局安装的 Pi（pi-coding-agent@0.85.1，自带嵌套依赖树）+ Node 运行时
收集到分发包的 `_internal/pi_runtime/`，让分发用户开箱即用 Pi 试点，无需自行
npm install。

结构：
    _internal/pi_runtime/node.exe                      # Node 22.22.2
    _internal/pi_runtime/node_modules/
      @earendil-works/pi-coding-agent/                 # Pi 0.85.1（含嵌套依赖）
        dist/bundle/cli.js                             # RPC 启动入口

启动方式（pi_backend.resolve_pi_launch）：`node.exe <cli.js> --mode rpc ...`

用法：
    python copy_pi_runtime.py                 # 收集到 <repo>/_internal/pi_runtime
    python copy_pi_runtime.py --dist dist/码铃  # 打包后复制到 dist/<app>/_internal/
    python copy_pi_runtime.py --report-only   # 只测体积不复制

精简项（选择性复制实现，全程零删除）：docs/ examples/ 顶层 *.md / *.map
（sourcemap）——实测约 14MB；@esbuild 已只含 win32-x64，无需额外处理。
版本锁定：pi-coding-agent 0.85.1（不符即报错，防 RPC 协议漂移）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PI_REQUIRED_VERSION = "0.85.1"
PI_PACKAGE = "@earendil-works/pi-coding-agent"

REPO = Path(__file__).resolve().parent


def _run(cmd: list) -> str:
    # Windows 下 npm 是 .cmd shim，必须先解析绝对路径（WinError 2）
    resolved = shutil.which(cmd[0]) or shutil.which(cmd[0] + ".cmd") or cmd[0]
    out = subprocess.run([resolved] + cmd[1:], capture_output=True, text=True,
                         timeout=60, encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"命令失败 {' '.join(cmd)}: {out.stderr.strip()[:300]}")
    return (out.stdout or "").strip()


def locate_sources() -> tuple[Path, Path, str]:
    """定位全局 node_modules、node.exe 与 pi 版本。"""
    npm_root = Path(_run(["npm", "root", "-g"]))
    npm_prefix = Path(_run(["npm", "prefix", "-g"]))
    node_exe = npm_prefix / "node.exe"
    if not node_exe.exists():
        raise RuntimeError(f"未找到 node.exe: {node_exe}")
    pkg_dir = npm_root / PI_PACKAGE
    if not pkg_dir.exists():
        raise RuntimeError(f"未找到全局 Pi 包: {pkg_dir}\n"
                           f"请先 npm install -g --ignore-scripts @earendil-works/pi-coding-agent@{PI_REQUIRED_VERSION}")
    version = (json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
               .get("version", ""))
    if version != PI_REQUIRED_VERSION:
        raise RuntimeError(f"Pi 版本不符: {version}（要求 {PI_REQUIRED_VERSION}）")
    return npm_root, node_exe, version


def dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB"


def _copy_pkg(pkg_src: Path, pkg_dst: Path) -> None:
    """选择性复制 pi 包：跳过 docs/examples/*.md/*.map（精简约 14MB）。

    注意：不做复制后删除（rmtree 大树会被宿主安全守卫拦截），精简完全
    在复制阶段完成；重跑用 dirs_exist_ok=True 续传，零删除。
    """
    pkg_dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        pkg_src, pkg_dst, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("docs", "examples", "*.md", "*.map", "*.log"),
    )


def collect(target_root: Path, report_only: bool = False) -> None:
    npm_root, node_exe, version = locate_sources()
    pkg_src = npm_root / PI_PACKAGE
    src_size = dir_size(pkg_src)
    print(f"源: {pkg_src}")
    print(f"Pi 版本: {version}（锁定 {PI_REQUIRED_VERSION}）")
    print(f"node.exe: {node_exe}（{mb(node_exe.stat().st_size)}）")
    print(f"Pi 包原始体积: {mb(src_size)}")

    if report_only:
        print(f"预估捆绑体积（精简后）: ~{mb(src_size + node_exe.stat().st_size - 14 * 1024 * 1024)}"
              "（docs/examples/md/map 精简约 14MB）")
        return

    dest_nm = target_root / "node_modules"
    pkg_dst = dest_nm / PI_PACKAGE
    print("复制 pi-coding-agent（含嵌套依赖树，选择性精简）…")
    _copy_pkg(pkg_src, pkg_dst)
    shutil.copy2(node_exe, target_root / "node.exe")
    cli = pkg_dst / "dist" / "bundle" / "cli.js"
    if not cli.exists():
        raise RuntimeError(f"收集后缺少启动入口: {cli}")
    final = dir_size(target_root)
    print(f"完成: {target_root}")
    print(f"  node.exe + cli.js 校验通过: {cli}")
    print(f"捆绑总体积: {mb(final)}（源码态 zip 增量预估 ~{mb(final // 3)}，JS 压缩比约 3:1）")


def post_pack(dist_dir: Path) -> None:
    """打包后模式：把 _internal/pi_runtime 复制进 dist/<app>/_internal/，
    并附带 pi_gateway 门禁扩展（打包 datas 不含 pi_gateway 时兜底）。

    零删除续传语义：不 rmtree 旧目录（大树删除会被宿主安全守卫拦截，
    且与 collect 的选择性复制同精神）——直接 dirs_exist_ok=True 覆盖复制，
    以源为权威对齐内容；支持中断后续传。
    """
    src_runtime = REPO / "_internal" / "pi_runtime"
    if not src_runtime.exists():
        raise RuntimeError("尚未收集运行时：先执行 `python copy_pi_runtime.py`")
    internal = dist_dir / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    dst_runtime = internal / "pi_runtime"
    print("复制 pi_runtime →", dst_runtime)
    try:
        shutil.copytree(src_runtime, dst_runtime, dirs_exist_ok=True)
    except shutil.Error as exc:
        # 长路径兜底：Pi 依赖树含 >260 字符的深层文件（dist-types 等），
        # shutil 会 WinError 3；robocopy 原生支持长路径且可续传。
        # 退出码 <8 均为成功（1=有复制，0=无差异）。
        print(f"copytree 失败（疑似长路径），转 robocopy 续传: {str(exc)[:200]}")
        cmd = ["robocopy", str(src_runtime), str(dst_runtime),
               "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP"]
        rc = subprocess.run(cmd).returncode
        if rc >= 8:
            raise RuntimeError(f"robocopy 失败: rc={rc}")
    gate_src = REPO / "pi_gateway" / "maling_gate.js"
    gate_dst = internal / "pi_gateway"
    gate_dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(gate_src, gate_dst / "maling_gate.js")
    print("复制门禁扩展 →", gate_dst / "maling_gate.js")
    src_n = _count_files_lp(src_runtime)
    dst_n = _count_files_lp(dst_runtime)
    if src_n != dst_n:
        print(f"⚠️ 完整性自检：源 {src_n} 文件 vs 打包内 {dst_n} 文件——"
              "存在未落盘文件（长路径残留），请排查 dist 内 pi_runtime")
    else:
        print(f"完整性自检通过：{src_n} 文件全部落盘")
    print(f"打包态 _internal 增量: {mb(dir_size(dst_runtime) + 100 * 1024)}")


def _count_files_lp(root: Path) -> int:
    """长路径安全文件计数（\\\\?\\ 前缀绕过 MAX_PATH=260 限制）。"""
    n = 0
    prefixed = "\\\\?\\" + str(root)
    for dirpath, _dirnames, filenames in os.walk(prefixed):
        n += len(filenames)
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="Pi 运行时捆绑收集")
    ap.add_argument("--dist", help="打包后模式：dist/<app> 目录")
    ap.add_argument("--report-only", action="store_true", help="只测体积不复制")
    args = ap.parse_args()

    if args.dist:
        post_pack(Path(args.dist).resolve())
        return 0
    target = REPO / "_internal" / "pi_runtime"
    collect(target, report_only=args.report_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
