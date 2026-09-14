# -*- coding: utf-8 -*-
r"""tools/build_release.py —— 码铃（MaLing）v2.0 发版制品脚本（V20-17）。

职责（docs/design-v20.md §7 / docs/prd-v20.md §6 第 5~7、10 步固化）：
    1. 把 onedir 产物目录压成 zip  → MaLing_v<X.Y.Z>_Desktop.zip
    2. 把 onefile 产物复制/改名     → MaLing_v<X.Y.Z>_Portable.exe
    3. 对上面两个文件各算 sha256    → <file>.sha256（内容 "<64hex>  <filename>"，**两个空格**）
    4. 生成 version.json 的人工粘贴片段（assets + downloads + release_url）→ version_fragment.json
       并同时打印到 stdout。

设计约束：
    * **纯标准库**（R-F 零新增第三方依赖）：argparse / hashlib / json / os / shutil / sys / zipfile。
    * **不自动改 version.json**（发版是人工步骤；本脚本只产出片段）。
    * Windows 长路径扩展前缀处理（先例 tools/pack_release_v190.py:long_path），
      onedir 内 Pi runtime 依赖树可能 > 260 字符。
    * **幂等可重跑**：已存在的输出文件直接覆盖。
    * **失败非 0 退出**：源缺失 / 版本号非法 / 打包异常 → 打印 ERROR 并 sys.exit(1)。
    * **fail-fast 守卫（V20-17 补强）**：打 zip 前校验 ①onedir 含 `_internal/pi_runtime`
      且文件数 ≥10000（Pi 是"打包后复制"，漏跑 `copy_pi_runtime.py --dist <onedir>`
      会产出缺 61MB+ Pi 运行时的包）②onedir 内嵌 `_internal/updater/maling_updater.exe`
      存在且体积 ≈7.2MB。任一不达标 → 非 0 退出，**绝不静默产残缺包**；
      仅 `--skip-pi-check`（默认关闭）可显式放行精简包。
    * `GITHUB_OWNER` 保持**占位**（R-O 分发诚实）：url 用 `https://github.com/<GITHUB_OWNER>/...`
      模板，除非显式 `--owner` 传入真实 owner。

用法示例：
    # 构建产物在 dist_v2.0.0f/（maling/ 目录 + MaLing_single.exe）
    python tools/build_release.py --version 2.0.0 --dist-dir dist_v2.0.0f --out release

    # 源路径与产物名不一致时显式指定
    python tools/build_release.py --version 2.0.0 \
        --onedir-src dist_v2.0.0f/maling \
        --single-src dist_v2.0.0f/MaLing_single.exe \
        --out release --channel stable

    # 拥有真实仓库后（R-O③ 硬闸完成后）
    python tools/build_release.py --version 2.0.0 --owner my-github-name
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
OWNER_PLACEHOLDER = "<GITHUB_OWNER>"
REPO = "maling"
CHUNK = 1024 * 1024

# ---- fail-fast 阈值（V20-17 补强：防"缺 Pi 运行时/缺 sidecar"的包被静默产出）----
# Pi 运行时是「打包后复制」：构建完 onedir 后必须跑
#   python copy_pi_runtime.py --dist <dist/maling>
# 才会把 pi_runtime 落进 <onedir>/_internal/。实测源 `_internal/pi_runtime` 与
# v1.9.0 分发目录均为 13,567 个文件（历史上曾漏跑而少 61MB）。取 10000 为下限。
PI_RUNTIME_MIN_FILES = 10000
# sidecar（maling_updater.exe）落包体积 ≈7.24MB（实测 7,592,326 B）→ 给宽容区间。
SIDECAR_MIN_BYTES = 6_000_000
SIDECAR_MAX_BYTES = 12_000_000


def long_path(p) -> str:
    """Windows 长路径前缀（>260 字符路径必须）。"""
    s = str(p)
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(s)
    return s


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(long_path(path), "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def count_files_long_path(root: Path) -> int:
    """长路径安全文件计数（Windows 扩展前缀，Pi 依赖树深度 >260）。"""
    prefixed = "\\\\?\\" + os.path.abspath(str(root))
    n = 0
    for _dirpath, _dirnames, filenames in os.walk(prefixed):
        n += len(filenames)
    return n


def guard_pi_runtime(onedir_src: Path, skip: bool) -> None:
    """fail-fast：onedir 产物必须已含 pi_runtime（万级文件），否则拒发。

    缺失 = 漏跑 `python copy_pi_runtime.py --dist <onedir_src>`，
    产出包 Pi 编程引擎直接不可用（历史事故：zip 少 61MB）。
    """
    if skip:
        print("WARNING: --skip-pi-check 已开启 → 跳过 pi_runtime 核验"
              "（仅用于有意出精简包；正式发版切勿使用）")
        return
    runtime = onedir_src / "_internal" / "pi_runtime"
    if not runtime.is_dir():
        raise RuntimeError(
            f"onedir 缺少 Pi 运行时: {runtime} —— 疑似漏跑 "
            f"`python copy_pi_runtime.py --dist {onedir_src}`；"
            "缺 Pi 的包不得发布（如确需精简包请显式 --skip-pi-check）")
    n = count_files_long_path(runtime)
    if n < PI_RUNTIME_MIN_FILES:
        raise RuntimeError(
            f"Pi 运行时文件数异常: {runtime} 仅 {n} 个（下限 {PI_RUNTIME_MIN_FILES}）"
            "—— 疑似收集不完整/长路径残留，请重跑 copy_pi_runtime.py 后重试")
    print(f"[guard] Pi 运行时核验通过: {runtime}（{n} 个文件）")


def guard_sidecar(onedir_src: Path, sidecar_src) -> None:
    """fail-fast：内嵌 sidecar 存在且体积合理（≈7.2MB）；可选校验独立源。"""
    embedded = onedir_src / "_internal" / "updater" / "maling_updater.exe"
    if not embedded.is_file():
        raise RuntimeError(
            f"onedir 未内嵌 sidecar: {embedded} —— 两个主 spec 的 datas "
            "('dist_updater/maling_updater.exe','updater') 未生效；"
            "请先 `pyinstaller --noconfirm --distpath dist_updater updater.spec` 再构建 onedir")
    size = embedded.stat().st_size
    if not (SIDECAR_MIN_BYTES <= size <= SIDECAR_MAX_BYTES):
        raise RuntimeError(f"内嵌 sidecar 体积异常: {embedded} = {size} B"
                           f"（期望 {SIDECAR_MIN_BYTES}~{SIDECAR_MAX_BYTES}）")
    print(f"[guard] 内嵌 sidecar 核验通过: {embedded}（{size} B）")
    if sidecar_src is not None:
        src = Path(sidecar_src)
        if not src.is_file():
            raise RuntimeError(f"sidecar 源不存在: {src}（--sidecar-src 指定）")
        ssize = src.stat().st_size
        if not (SIDECAR_MIN_BYTES <= ssize <= SIDECAR_MAX_BYTES):
            raise RuntimeError(f"sidecar 源体积异常: {src} = {ssize} B")
        print(f"[guard] sidecar 源核验通过: {src}（{ssize} B）")


def write_sha256_file(artifact: Path) -> str:
    """写 <artifact>.sha256，内容 '<64hex>  <filename>\\n'（两个空格），返回 hex。"""
    digest = sha256_file(artifact)
    sha_path = artifact.parent / (artifact.name + ".sha256")
    with open(long_path(sha_path), "w", encoding="ascii", newline="\n") as f:
        f.write(f"{digest}  {artifact.name}\n")
    return digest


def zip_onedir(src_dir: Path, out_zip: Path, zip_root: str) -> int:
    """把 src_dir 整目录压进 out_zip，顶层前缀 zip_root/。返回写入文件数。"""
    files = []
    # 注意：walk 用**非前缀**路径（relative_to 依赖未加 \\?\ 的基准），
    # long_path 只在 write 时逐文件套用（先例 tools/pack_release_v190.py）。
    for dirpath, _dirnames, filenames in os.walk(str(src_dir)):
        for fn in filenames:
            files.append(Path(dirpath) / fn)
    if not files:
        raise RuntimeError(f"onedir 源目录为空: {src_dir}")
    written = 0
    with zipfile.ZipFile(long_path(out_zip), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            rel = f.relative_to(src_dir).as_posix()
            zf.write(long_path(f), f"{zip_root}/{rel}")
            written += 1
    return written


def build_fragment(version: str, owner: str, channel: str,
                   onedir: dict, single: dict, mirror: str) -> dict:
    base = f"https://github.com/{owner}/{REPO}/releases/download/v{version}"
    return {
        "_comment": (
            "V20-17 生成的人工粘贴片段；请把 release_url/downloads/assets 合并进仓库 "
            "version.json。GITHUB_OWNER 占位必须在上线前替换（R-O③ 硬闸）。"
        ),
        "release_url": f"https://github.com/{owner}/{REPO}/releases/tag/v{version}",
        "channel": channel,
        "downloads": {
            "github": f"{base}/{onedir['filename']}",
            "mirror": mirror,
        },
        "assets": {
            "onedir": onedir,
            "single": single,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="码铃 v2.0 发版制品打包（zip + exe + sha256 + version.json 片段）")
    ap.add_argument("--version", required=True, help="版本号 X.Y.Z（不带 v 前缀）")
    ap.add_argument("--dist-dir", default="dist",
                    help="PyInstaller 产物目录（默认 dist）；onedir=dist/maling、onefile=dist/MaLing_single.exe")
    ap.add_argument("--onedir-src", default=None, help="onedir 产物目录（覆盖 --dist-dir/maling）")
    ap.add_argument("--single-src", default=None, help="onefile 产物 exe（覆盖 --dist-dir/MaLing_single.exe）")
    ap.add_argument("--out", default="release", help="输出目录（默认 release）")
    ap.add_argument("--channel", default="stable", choices=["stable", "beta"])
    ap.add_argument("--owner", default=OWNER_PLACEHOLDER,
                    help="GitHub owner；默认占位 <GITHUB_OWNER>（R-O 诚实，未替换前不得上线）")
    ap.add_argument("--mirror", default="", help="备用链 URL（可选，默认空）")
    ap.add_argument("--sidecar-src", default=None,
                    help="独立 sidecar 源路径（可选；用于额外校验 distpath 是否正确）")
    ap.add_argument("--skip-pi-check", action="store_true",
                    help="显式逃生开关：跳过 pi_runtime 核验（默认关闭=拦截；仅限有意出精简包）")
    args = ap.parse_args(argv)

    version = args.version.strip().lstrip("vV")
    if not VERSION_RE.match(version):
        print(f"ERROR: 版本号非法（要求 X.Y.Z）: {args.version!r}")
        return 1

    dist_dir = Path(args.dist_dir)
    onedir_src = Path(args.onedir_src) if args.onedir_src else dist_dir / "maling"
    single_src = Path(args.single_src) if args.single_src else dist_dir / "MaLing_single.exe"
    out_dir = Path(args.out)

    onedir_zip_name = f"MaLing_v{version}_Desktop.zip"
    single_exe_name = f"MaLing_v{version}_Portable.exe"

    # ---- 前置检查 ----
    if not onedir_src.is_dir():
        print(f"ERROR: onedir 源目录不存在: {onedir_src}")
        return 1
    if not single_src.is_file():
        print(f"ERROR: onefile 源不存在: {single_src}")
        return 1

    # ---- fail-fast 守卫（V20-17）：绝不静默产出缺 Pi / 缺 sidecar 的包 ----
    try:
        guard_pi_runtime(onedir_src, args.skip_pi_check)
        guard_sidecar(onedir_src, args.sidecar_src)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: 无法创建输出目录 {out_dir}: {exc}")
        return 1

    # ---- 1) zip onedir ----
    out_zip = out_dir / onedir_zip_name
    try:
        if out_zip.exists():
            os.remove(long_path(out_zip))
        zip_root = onedir_src.name or "maling"
        n_files = zip_onedir(onedir_src, out_zip, zip_root)
        print(f"[1/3] onedir zip: {out_zip}（{n_files} 个文件，顶层 {zip_root}/）")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: 打包 onedir 失败: {exc}")
        return 1

    # ---- 2) 复制/改名 onefile ----
    out_exe = out_dir / single_exe_name
    try:
        shutil.copyfile(long_path(single_src), long_path(out_exe))
        print(f"[2/3] onefile exe: {out_exe}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: 复制 onefile 失败: {exc}")
        return 1

    # ---- 3) sha256（两条）----
    try:
        zip_sha = write_sha256_file(out_zip)
        exe_sha = write_sha256_file(out_exe)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: 计算 sha256 失败: {exc}")
        return 1
    zip_size = out_zip.stat().st_size
    exe_size = out_exe.stat().st_size
    print(f"[3/3] sha256 onedir: {zip_sha}")
    print(f"      sha256 single: {exe_sha}")

    # ---- version.json 片段 ----
    fragment = build_fragment(
        version, args.owner, args.channel,
        onedir={"url": f"https://github.com/{args.owner}/{REPO}/releases/download/v{version}/{onedir_zip_name}",
                "mirror": args.mirror, "sha256": zip_sha, "size": zip_size,
                "filename": onedir_zip_name},
        single={"url": f"https://github.com/{args.owner}/{REPO}/releases/download/v{version}/{single_exe_name}",
                "mirror": args.mirror, "sha256": exe_sha, "size": exe_size,
                "filename": single_exe_name},
        mirror=args.mirror,
    )
    frag_path = out_dir / "version_fragment.json"
    with open(long_path(frag_path), "w", encoding="utf-8", newline="\n") as f:
        json.dump(fragment, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("\n===== version.json 人工粘贴片段（不自动改 version.json）=====")
    print(json.dumps(fragment, ensure_ascii=False, indent=2))
    print(f"\n片段已写入: {frag_path}")
    if args.owner == OWNER_PLACEHOLDER:
        print("WARNING: --owner 仍为占位 <GITHUB_OWNER>；"
              "上线前必须替换为真实 owner（R-O③ 硬闸），否则客户端无法下载。")
    print(f"\nDONE: onedir={zip_size} bytes  single={exe_size} bytes  输出目录={out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
