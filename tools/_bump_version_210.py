# -*- coding: utf-8 -*-
r"""tools/_bump_version_210.py —— 一次性脚本：把 version.json 升到 v2.1.0。

**主控收工专用**。做的事：
  1. 备份 version.json → version.json.bak
  2. 改 `version` 为 "2.1.0"
  3. 改 `release_url` / `downloads` / `assets.*.url` 全部指向 v2.1.0
  4. 改 `released_at` = 当天日期（2026-09-11）
  5. `min_updatable` 保持 "2.0.0"（v2.0 引入自动更新，不能抬高）
  6. `assets.*.sha256/size` **占位为 None/0**（待打包后回填；运行时读取到空值时不崩 —— 见 _fill_assets_sha.py）

**运行后不可改回**（除非从 .bak 恢复）。运行前会自动校验当前 version.json 的 version == "2.0.0"，
防止重复执行。
"""
import json, shutil, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "version.json"
BAK = PATH.with_suffix(".json.bak_210")

EXPECTED_OLD = "2.0.0"
NEW = "2.1.0"

# AGENTS.md §5: 版本号三处同步 = version + downloads URL + 构建目录名
# 构建目录名 = dist_v<XYZ>f/，XYZ = 版本号数字拼接 = "210" → dist_v210f/
# 下载文件名 = MaLing_v<XYZ>_<variant>.<ext>
GITHUB_OWNER = "xigua148"  # 与现有 version.json 一致
TAG = f"v{NEW}"
DATE = "2026-09-11"

ASSETS_TPL = {
    "onedir": {
        "url": f"https://github.com/{GITHUB_OWNER}/maling/releases/download/{TAG}/MaLing_v{NEW}_win_onedir.zip",
        "mirror": "",
        "sha256": None,   # 打包后由 _fill_assets_sha.py 回填
        "size": 0,
        "filename": f"MaLing_v{NEW}_win_onedir.zip",
    },
    "single": {
        "url": f"https://github.com/{GITHUB_OWNER}/maling/releases/download/{TAG}/MaLing_v{NEW}_win_single.exe",
        "mirror": "",
        "sha256": None,
        "size": 0,
        "filename": f"MaLing_v{NEW}_win_single.exe",
    },
}

def main():
    raw = PATH.read_text(encoding="utf-8")
    # 去掉 _comment 等仅作注释的字段（load 时丢弃）
    cfg = json.loads(raw)
    if cfg.get("version") != EXPECTED_OLD:
        raise SystemExit(
            f"version.json 当前 version={cfg.get('version')!r}，"
            f"期望 {EXPECTED_OLD!r}（防止重复执行或顺序错误）"
        )
    if BAK.exists():
        raise SystemExit(f"备份已存在 {BAK}，请先确认上次升级已完成或手动清理")
    shutil.copy2(PATH, BAK)
    print(f"[OK] 备份 → {BAK}")
    cfg["version"] = NEW
    cfg["released_at"] = DATE
    cfg["release_url"] = f"https://github.com/{GITHUB_OWNER}/maling/releases/tag/{TAG}"
    cfg["downloads"] = {
        "github": ASSETS_TPL["onedir"]["url"],
        "mirror": "",
    }
    cfg["assets"] = ASSETS_TPL
    # 备注里加一条 v2.1.0 摘要（插在队首，便于检索）
    new_note = (
        f"v2.1.0 视觉一致性收口：图标字形体系 · 字体族链修复 · 字号单一收口；"
        f"三处循环动效回退（ripple/bars/typing→pulse/文字节奏）；侧栏滚动条 hover 才显示；"
        f"KB 检索/建索引异步化（QThread）；核心层 L0→L1 反向依赖修（path_guard.py）；"
        f"命令白名单收敛为 ALLOWED_COMMANDS 子集（+子集守卫）；气泡姓名走 given_name（人设≠人名）。"
    )
    notes = cfg.get("notes", [])
    cfg["notes"] = [new_note] + [n for n in notes if not n.startswith("v2.1.0 ")]
    # 写回（保持原 indent=2 + ensure_ascii=False，与现有风格一致）
    PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[OK] version.json 已升到 {NEW}（build dir = dist_v210f/）")
    print(f"[NOTE] assets.*.sha256/size = None/0 → 打包后运行 tools/_fill_assets_sha.py 回填")

if __name__ == "__main__":
    main()
