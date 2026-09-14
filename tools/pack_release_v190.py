# -*- coding: utf-8 -*-
r"""v1.9.0 分发 zip 打包脚本。

要点：
- 用 python zipfile（GNU tar 不产真 zip）
- 长路径前缀 \\?\ 处理（onedir 内 Pi runtime 依赖树路径 >260）
- 只打包 onedir 产物（本地测试用，zip 供发布）
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dist_v190f" / "maling"
OUT_DIR = ROOT / "release"
VERSION = "1.9.0"
ZIP_NAME = f"码铃_MaLing_v{VERSION}_桌面版.zip"


def long_path(p: Path) -> str:
    s = str(p)
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(s)
    return s


def main() -> int:
    if not SRC.exists():
        print(f"ERROR: 源目录不存在: {SRC}")
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ZIP_NAME
    if out.exists():
        out.unlink()

    files = []
    for dirpath, _dirnames, filenames in os.walk(SRC):
        for fn in filenames:
            files.append(Path(dirpath) / fn)
    total = len(files)
    print(f"待打包文件数: {total}")

    written = 0
    skipped = 0
    with zipfile.ZipFile(long_path(out), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in files:
            try:
                rel = f.relative_to(SRC).as_posix()
                zf.write(long_path(f), f"maling/{rel}")
                written += 1
            except (OSError, ValueError) as e:
                skipped += 1
                print(f"  SKIP {f}: {e}")
            if written % 2000 == 0 and written:
                print(f"  ... {written}/{total}")

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"DONE: {out}")
    print(f"文件数={written} 跳过={skipped} 大小={size_mb:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
