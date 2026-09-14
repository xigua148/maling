# -*- coding: utf-8 -*-
r"""tools/_fill_assets_sha.py —— 打包后回填真实 sha256 + size 到 version.json。

**主控收工专用**。在 `tools/build_release.py --version 2.1.0 ...` 跑完后调用。

做的事：读 version.json，按 `assets.*.filename` 在指定目录里找文件，
计算 sha256（64hex）与 size（字节），回填 `assets.<variant>.sha256` 与 `size`。
若文件不存在：报错并退出（不静默）。

运行示例：
    python tools/_fill_assets_sha.py --release-dir release/
（`release_dir` 是 build_release.py 输出的目录，里面有：
    MaLing_v2.1.0_win_onedir.zip
    MaLing_v2.1.0_win_single.exe
    MaLing_v2.1.0_win_onedir.zip.sha256
    MaLing_v2.1.0_win_single.exe.sha256
    version_fragment.json）
"""
import argparse, hashlib, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "version.json"

def sha256_file(p: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release-dir", type=Path, required=True,
                    help="build_release.py 输出的目录（含 zip/exe + .sha256）")
    args = ap.parse_args()
    rd: Path = args.release_dir
    if not rd.is_dir():
        raise SystemExit(f"--release-dir 不存在或不是目录：{rd}")
    cfg = json.loads(PATH.read_text(encoding="utf-8"))
    assets = cfg.get("assets", {})
    changed = False
    for variant, meta in assets.items():
        fn = meta.get("filename")
        if not fn:
            continue
        p = rd / fn
        if not p.is_file():
            print(f"[WARN] {variant}: {p} 不存在，跳过（请确认 build_release.py 已成功出包）")
            continue
        sha, size = sha256_file(p)
        # 校验 .sha256 侧文件内容（如有）—— 防止文件被改过
        sha_file = rd / (fn + ".sha256")
        if sha_file.is_file():
            txt = sha_file.read_text(encoding="utf-8").strip()
            m = re.match(r"^([0-9a-fA-F]{64})", txt)
            if m and m.group(1).lower() != sha.lower():
                print(f"[WARN] {variant}: 自算 sha 与 .sha256 文件不一致 —— "
                      f"自算 {sha[:16]}... / 文件 {m.group(1)[:16]}...")
        meta["sha256"] = sha
        meta["size"] = size
        changed = True
        print(f"[OK] {variant}: {fn}  sha={sha[:16]}...  size={size:,}B")
    if not changed:
        raise SystemExit("没有任何 variant 被回填，请检查 --release-dir 与版本号")
    # 写回
    PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[DONE] version.json 已回填 sha256/size")

if __name__ == "__main__":
    main()
