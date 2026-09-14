#!/usr/bin/env python3
"""码铃图标字体构建脚本（v2.1 域3 / 设计 D-V21-06 / D-V21-07 / D-V21-14）。

**仅构建期使用**，不进运行时、不进 exe：``qtawesome`` / ``fonttools`` 均为构建机临时工具，
**不写入 ``requirements*.txt``、不进 dist 产物**（红线 R-F）。

它做什么
--------
1. 从**本地 wheel**（``UI设计工具集/Python包/qtawesome-1.4.2-py3-none-any.whl``）取出官方
   图标集字体与 charmap（离线，不联网），并用 ``qtawesome``（可选）交叉校验码位映射；
2. 按脚本内 ``ICON_MAP``（语义名 → 图标集字形名）解析出码位，用 ``pyftsubset`` **子集化**
   为 ``gui/assets/icons/maling_icons.ttf``（只留用到的字形，体积压到数十 KB）；
3. 生成 ``gui/assets/icons/icons_manifest.json``（``{"<语义名>": <码位整数>}``）；
4. 把图标集**许可全文**落到随包副本 ``gui/assets/icons/LICENSE``（源树副本见
   ``docs/third_party_licenses/remix_icon.txt``）。

用法
----
    python tools/build_icons.py                      # 全自动：本地 wheel → 子集 → manifest → LICENSE
    python tools/build_icons.py --check              # 只校验 ICON_MAP 里的字形名是否都在图标集内（不写盘）
    python tools/build_icons.py --list               # 打印当前「语义名 → 图标集字形名」映射
    python tools/build_icons.py --source-dir <dir>   # 用已解压的图标集目录（含 remixicon-*.ttf + charmap）
    python tools/build_icons.py --wheel <path.whl>   # 指定本地 qtawesome wheel（默认取工具集目录）
    python tools/build_icons.py --subset-python <py> # 指定带 fontTools 的解释器（默认自动探测）
    python tools/build_icons.py --add pin-line=pin-line --add cloud-off=cloud-off-line   # 本批追加名字

**如何新增一个图标名**（域5/6/8 等后续落点复现步骤，一句话）
    —— 在 ``ICON_MAP`` 里补一行 ``"语义名": "remix-图标名"``（或命令行 ``--add 语义名=remix名``），
    重跑本脚本即可：重建 TTF + manifest + 许可副本，运行时无需改代码（``gui/icons.py`` 读 manifest）。

依赖：``pip install fonttools``（构建期临时安装；本机亦可指定已带 fontTools 的解释器）。
      ``qtawesome`` 仅作**可选**码位交叉校验，缺失时脚本仍可离线完成构建。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "gui" / "assets" / "icons"
LICENSE_SRC = REPO_ROOT / "docs" / "third_party_licenses" / "remix_icon.txt"

TTF_OUT_NAME = "maling_icons.ttf"
MANIFEST_OUT_NAME = "icons_manifest.json"
LICENSE_OUT_NAME = "LICENSE"

# 默认本地 wheel（离线；不联网）——与团队交付的 UI 设计工具集同目录
DEFAULT_WHEEL = (
    REPO_ROOT.parent / "UI设计工具集" / "Python包" / "qtawesome-1.4.2-py3-none-any.whl"
)

# ---------------------------------------------------------------------------
# 图标集元数据（设计 D-V21-07 / D-V21-14；随包登记）
# ---------------------------------------------------------------------------
ICONSET = "remix_icon"                 # 与 gui/icons.py 的 ICONSET 常量一致（design §4.4）
ICONSET_DISPLAY = "Remix Icon"
ICONSET_VERSION = "2.5.0"
ICONSET_LICENSE = "Apache-2.0"
ICONSET_REPO = "https://github.com/Remix-Design/RemixIcon"
QTAAWESOME_PREFIX = "ri"
WHEEL_TTF_GLOB = "remixicon-*.ttf"
WHEEL_CHARMAP_GLOB = "remixicon-charmap-*.json"

# ---------------------------------------------------------------------------
# 语义名 → 图标集字形名（单一真值源；语义名即 manifest 键 = 全站 icon() 传入的名字）
#
# 命名纪律：语义名用**功能语义**（chat/settings/pref…），不得暴露图标集内部的 -line/-fill
# 命名；换图标集时只需改本表右值，manifest 键与全站落点零改动。
# ---------------------------------------------------------------------------
ICON_MAP: Dict[str, str] = {
    # ---- I-1 侧栏导航 10 项（键名与 design-v21 §2/§4.5 完全一致，域5 直接沿用）----
    "chat": "chat-3-line",
    "home": "home-line",
    "auto_awesome": "magic-line",
    "menu_book": "book-2-line",
    "edit": "edit-line",
    "list": "list-check",
    "person": "user-line",
    "settings": "settings-3-line",
    "tune": "equalizer-line",
    # ---- I-2 聊天顶栏 / 输入区工具（chat_panel 落点，域6）----
    "new_chat": "add-line",
    "sidebar_toggle": "menu-line",
    "export": "download-line",
    "expand": "fullscreen-line",
    "style": "brush-line",
    "stop": "stop-circle-line",
    "agent": "robot-line",
    "task": "task-line",
    "web": "global-line",
    "send": "send-plane-line",
    "attach": "attachment-line",
    "paste": "clipboard-line",
    "search": "search-line",
    "emoji": "emotion-happy-line",
    "voice": "mic-line",
    "camera": "camera-line",
    "screenshot": "screenshot-line",
    "game": "gamepad-line",
    "handsfree": "sound-module-line",
    "watch": "eye-line",
    "computer": "mouse-line",
    "retry": "refresh-line",
    "edit_resend": "edit-2-line",
    "rename": "draft-line",
    # ---- I-3 状态栏 3 项 + 设置分区 + 记忆中心 8 Tab（域5/4/8）----
    "theme": "palette-line",
    "mode": "speed-line",
    "api": "plug-line",
    "appearance": "brush-line",
    "motion": "play-circle-line",
    "glass": "contrast-drop-line",
    "power": "battery-line",
    "pref": "user-heart-line",
    "topic": "chat-1-line",
    "question_answer": "question-answer-line",
    "emotion": "emotion-line",
    "weekly": "history-line",
    "people": "group-line",
    "response": "bookmark-3-line",
    "shared": "footprint-line",
    "diary": "quill-pen-line",
    # ---- 通用控件 / 其他页复用（域8 及收口）----
    "add": "add-line",
    "close": "close-line",
    "check": "check-line",
    "delete": "delete-bin-line",
    "save": "save-line",
    "refresh": "refresh-line",
    "info": "information-line",
    "warning": "error-warning-line",
    "question": "question-line",
    "help": "question-line",
    "history": "history-line",
    "star": "star-line",
    "heart": "heart-line",
    "bookmark": "bookmark-line",
    "folder": "folder-3-line",
    "file": "file-text-line",
    "image": "image-line",
    "link": "link",
    "share": "share-line",
    "filter": "filter-line",
    "sort": "sort-asc",
    "more": "more-line",
    "back": "arrow-left-line",
    "forward": "arrow-right-line",
    "up": "arrow-up-line",
    "down": "arrow-down-line",
    "calendar": "calendar-line",
    "time": "time-line",
    "alarm": "alarm-line",
    "lightbulb": "lightbulb-line",
    "lock": "lock-line",
    "key": "key-2-line",
    "shield": "shield-line",
    "bug": "bug-line",
    "code": "code-s-slash-line",
    "terminal": "terminal-box-line",
    "database": "database-2-line",
    "server": "server-line",
    "cloud": "cloud-line",
    "wifi": "wifi-line",
    "cpu": "cpu-line",
    "git": "git-branch-line",
    "gift": "gift-line",
    "cake": "cake-line",
    "crown": "vip-crown-line",
    "trophy": "trophy-line",
    "medal": "medal-line",
    "flag": "flag-line",
    "compass": "compass-3-line",
    "map": "map-pin-line",
    "route": "route-line",
    "anchor": "anchor-line",
    "chart": "line-chart-line",
    "pie_chart": "pie-chart-line",
    "bar_chart": "bar-chart-line",
    "grid": "grid-line",
    "layout": "layout-line",
    "dashboard": "dashboard-line",
    "window": "window-line",
    "printer": "printer-line",
    "device": "device-line",
    "headphone": "headphone-line",
    "volume": "volume-up-line",
    "keyboard": "keyboard-line",
    "palette": "palette-line",
    "contrast": "contrast-line",
    "sun": "sun-line",
    "moon": "moon-line",
    "flash": "flashlight-line",
    "translate": "translate-2",
    "music": "music-line",
    "video": "video-line",
    "film": "film-line",
    "mail": "mail-line",
    "inbox": "inbox-line",
    "notification": "notification-3-line",
    "message": "message-3-line",
    "chat_history": "chat-history-line",
    "user_add": "user-add-line",
    "user_settings": "user-settings-line",
    "team": "team-line",
    "contacts": "contacts-line",
    "admin": "admin-line",
    "account": "account-circle-line",
    "thumb_up": "thumb-up-line",
    "thumb_down": "thumb-down-line",
    "star_half": "star-half-line",
    "eye_off": "eye-off-line",
    "scan": "scan-line",
    "fingerprint": "fingerprint-line",
    "alert": "alert-line",
    "loudspeaker": "speaker-3-line",
    "drop": "drop-line",
    "paint_brush": "paint-brush-line",
    "stack": "stack-line",
    "shape": "shape-line",
    "article": "article-line",
    "sticky_note": "sticky-note-line",
    "todo": "todo-line",
    "flow": "flow-chart",
    "puzzle": "apps-2-line",
    "plugin": "apps-line",
}


# ---------------------------------------------------------------------------
# charmap / 源文件解析
# ---------------------------------------------------------------------------
def _load_charmap_text(data: bytes) -> Dict[str, int]:
    """解析 qtawesome 风格 charmap：``{"glyph-name": "0xea01"}`` → ``{"glyph-name": 59905}``。"""
    raw = json.loads(data.decode("utf-8"))
    out: Dict[str, int] = {}
    for name, value in raw.items():
        if isinstance(value, int):
            out[name] = value
        elif isinstance(value, str):
            out[name] = int(value, 16) if value.lower().startswith("0x") else int(value, 16)
    return out


def _extract_from_wheel(wheel: Path, tmp_dir: Path) -> Tuple[Path, Dict[str, int]]:
    """从本地 wheel 取出图标集 TTF + charmap（离线）。"""
    if not wheel.exists():
        raise FileNotFoundError(f"本地 wheel 不存在：{wheel}")
    with zipfile.ZipFile(wheel) as z:
        ttf_names = [n for n in z.namelist() if Path(n).name and _match(Path(n).name, WHEEL_TTF_GLOB)]
        cmap_names = [n for n in z.namelist() if Path(n).name and _match(Path(n).name, WHEEL_CHARMAP_GLOB)]
        if not ttf_names or not cmap_names:
            raise RuntimeError(f"wheel 内未找到 {WHEEL_TTF_GLOB} / {WHEEL_CHARMAP_GLOB}：{wheel}")
        ttf_bytes = z.read(ttf_names[0])
        cmap = _load_charmap_text(z.read(cmap_names[0]))
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ttf_path = tmp_dir / Path(ttf_names[0]).name
    ttf_path.write_bytes(ttf_bytes)
    print(f"  [wheel] {wheel.name}: {Path(ttf_names[0]).name} ({len(ttf_bytes)} bytes) "
          f"+ {Path(cmap_names[0]).name} ({len(cmap)} glyphs)")
    return ttf_path, cmap


def _match(name: str, pattern: str) -> bool:
    from fnmatch import fnmatch
    return fnmatch(name, pattern)


def _load_from_source_dir(source_dir: Path) -> Tuple[Path, Dict[str, int]]:
    """从已解压目录取图标集 TTF + charmap。"""
    ttfs = sorted(source_dir.rglob(WHEEL_TTF_GLOB))
    cmaps = sorted(source_dir.rglob(WHEEL_CHARMAP_GLOB))
    if not ttfs or not cmaps:
        raise FileNotFoundError(f"源目录缺 {WHEEL_TTF_GLOB} / {WHEEL_CHARMAP_GLOB}：{source_dir}")
    cmap = _load_charmap_text(cmaps[0].read_bytes())
    print(f"  [source] {ttfs[0].name} + {cmaps[0].name} ({len(cmap)} glyphs)")
    return ttfs[0], cmap


# ---------------------------------------------------------------------------
# 码位解析 / 交叉校验
# ---------------------------------------------------------------------------
def resolve_codepoints(icon_map: Dict[str, str], charmap: Dict[str, int]) -> Tuple[Dict[str, int], List[str]]:
    """语义名 → 码位；返回 ``(manifest, 缺失字形名列表)``。"""
    manifest: Dict[str, int] = {}
    missing: List[str] = []
    for semantic, glyph_name in icon_map.items():
        cp = charmap.get(glyph_name)
        if cp is None:
            missing.append(glyph_name)
            continue
        manifest[semantic] = cp
    return manifest, missing


def _install_qtpy_shim(tmp_dir: Path) -> None:
    """qtawesome 依赖 ``qtpy`` 抽象层；构建期无 qtpy 时用 PySide6 就地搭一个最小垫片。

    仅**构建期临时目录**内生效（不进运行时、不进 exe），使 qtawesome 校验可离线完成。
    """
    shim = tmp_dir / "qtpy"
    shim.mkdir(parents=True, exist_ok=True)
    (shim / "__init__.py").write_text(
        "import sys\n"
        "from PySide6 import QtCore, QtGui, QtWidgets\n"
        "import PySide6 as _ps\n"
        "sys.modules.setdefault('qtpy.QtCore', QtCore)\n"
        "sys.modules.setdefault('qtpy.QtGui', QtGui)\n"
        "sys.modules.setdefault('qtpy.QtWidgets', QtWidgets)\n"
        "PYSIDE_VERSION = _ps.__version__\n",
        encoding="utf-8",
    )


def cross_check_with_qtawesome(manifest: Dict[str, int], icon_map: Dict[str, str],
                               wheel: Optional[Path]) -> str:
    """用 qtawesome（构建期可选）交叉校验码位（D-V21-07）。缺失则返回说明文本。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="maling_qtawesome_"))
    try:
        if wheel and wheel.exists():
            cmd = [sys.executable, "-m", "pip", "install", "--no-deps", "--quiet",
                   "--target", str(tmp_dir), str(wheel)]
            subprocess.run(cmd, capture_output=True, text=True)

        shim_needed = True
        try:
            import qtpy  # type: ignore  # noqa: PLC0415,F401
            shim_needed = False
        except Exception:
            pass
        if shim_needed:
            _install_qtpy_shim(tmp_dir)

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(tmp_dir))
        for mod in [m for m in list(sys.modules) if m == "qtawesome" or m.startswith("qtawesome.") or m == "qtpy" or m.startswith("qtpy.")]:
            del sys.modules[mod]

        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
        if QGuiApplication.instance() is None:
            QGuiApplication([])

        import qtawesome  # type: ignore  # noqa: PLC0415

        ok = 0
        bad: List[str] = []
        for semantic, glyph_name in icon_map.items():
            try:
                char = qtawesome.charmap(f"{QTAAWESOME_PREFIX}.{glyph_name}")
                if char and ord(char) == manifest.get(semantic):
                    ok += 1
                else:
                    bad.append(glyph_name)
            except Exception:
                bad.append(glyph_name)
        if bad:
            return f"qtawesome 交叉校验：{ok} 通过 / 码位不符或缺失 {len(bad)}（{bad[:6]}…）"
        return f"qtawesome 交叉校验：{ok} 个图标名码位全部一致（前缀 {QTAAWESOME_PREFIX}）"
    except Exception as exc:  # noqa: BLE001
        return f"qtawesome 交叉校验跳过（不可用：{type(exc).__name__}: {exc}）"
    finally:
        try:
            sys.path.remove(str(tmp_dir))
        except ValueError:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# fontTools 子集化
# ---------------------------------------------------------------------------
def _probe_python(candidate: str) -> bool:
    try:
        proc = subprocess.run([candidate, "-c", "import fontTools.subset"],
                              capture_output=True, text=True, timeout=60)
        return proc.returncode == 0
    except Exception:
        return False


def find_subset_python(explicit: str = "") -> Optional[str]:
    """找到一个带 fontTools 的解释器（构建期工具，非运行时依赖）。"""
    candidates: List[str] = []
    if explicit:
        candidates.append(explicit)
    env_py = os.environ.get("MALING_SUBSET_PYTHON", "")
    if env_py:
        candidates.append(env_py)
    candidates.append(sys.executable)
    # 本机受管解释器版本目录（便于在默认 env 未装 fontTools 时仍可构建）
    for base in (
        Path.home() / ".workbuddy" / "binaries" / "python" / "versions",
        Path("C:/Users/Administrator/.workbuddy/binaries/python/versions"),
    ):
        if base.is_dir():
            candidates.extend(str(p) for p in sorted(base.glob("*/python.exe")))
    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if _probe_python(cand):
            return cand
    return None


def subset(src_ttf: Path, dest_ttf: Path, codepoints: List[int], subset_python: str) -> bool:
    dest_ttf.parent.mkdir(parents=True, exist_ok=True)
    unicodes = ",".join(f"U+{cp:04X}" for cp in sorted(set(codepoints)))
    cmd = [
        subset_python, "-m", "fontTools.subset", str(src_ttf),
        f"--unicodes={unicodes}",
        f"--output-file={dest_ttf}",
        "--layout-features=*",
        "--name-IDs=*",
        "--notdef-outline",
        "--recommended-glyphs",
        "--drop-tables+=DSIG",
    ]
    print(f"  [subset] {src_ttf.name} → {dest_ttf.name}（{len(set(codepoints))} 个字形）")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("  [subset-FAIL]", (proc.stderr or proc.stdout)[-1200:])
        return False
    print(f"  [subset-ok] {dest_ttf.name} ({dest_ttf.stat().st_size} bytes)")
    return True


# ---------------------------------------------------------------------------
# 落盘
# ---------------------------------------------------------------------------
def write_manifest(manifest: Dict[str, int], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({k: manifest[k] for k in sorted(manifest)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_license(dest: Path) -> bool:
    """把图标集许可全文复制为随包副本（源树副本 = docs/third_party_licenses/remix_icon.txt）。"""
    if not LICENSE_SRC.exists():
        print(f"  [license-WARN] 源树许可副本缺失：{LICENSE_SRC}")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LICENSE_SRC, dest)
    print(f"  [license] {LICENSE_SRC.name} → {dest}")
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Build bundled icon font for MaLing (v2.1 D3).")
    parser.add_argument("--wheel", default="", help="本地 qtawesome wheel 路径（默认取工具集目录）")
    parser.add_argument("--source-dir", default="", help="已解压的图标集目录（跳过 wheel）")
    parser.add_argument("--subset-python", default="", help="带 fontTools 的解释器（默认自动探测）")
    parser.add_argument("--add", action="append", default=[], metavar="NAME=GLYPH",
                        help="本批追加语义名映射（可重复），如 --add pin=map-pin-line")
    parser.add_argument("--check", action="store_true", help="只校验映射存在性，不写盘、不子集化")
    parser.add_argument("--list", action="store_true", help="打印当前语义名 → 图标集字形名映射")
    parser.add_argument("--no-qtawesome", action="store_true", help="跳过 qtawesome 交叉校验")
    args = parser.parse_args()

    icon_map = dict(ICON_MAP)
    for item in args.add:
        if "=" not in item:
            print(f"[ERROR] --add 需形如 NAME=GLYPH：{item}")
            return 2
        name, glyph = item.split("=", 1)
        icon_map[name.strip()] = glyph.strip()

    if args.list:
        for semantic in sorted(icon_map):
            print(f"  {semantic:20s} → {icon_map[semantic]}")
        print(f"[list] 共 {len(icon_map)} 个语义名")
        return 0

    tmp_dir = Path(tempfile.mkdtemp(prefix="maling_build_icons_"))
    try:
        wheel = Path(args.wheel) if args.wheel else DEFAULT_WHEEL
        if args.source_dir:
            src_ttf, charmap = _load_from_source_dir(Path(args.source_dir))
        else:
            src_ttf, charmap = _extract_from_wheel(wheel, tmp_dir)

        manifest, missing = resolve_codepoints(icon_map, charmap)
        if missing:
            print(f"[ERROR] 以下图标集字形名不存在于 {ICONSET_DISPLAY} {ICONSET_VERSION}：")
            for name in missing:
                print(f"    - {name}")
            return 2
        print(f"[resolve] 语义名 {len(icon_map)} 个 → 唯一字形 {len(set(manifest.values()))} 个")

        if not args.no_qtawesome:
            print(f"[check] {cross_check_with_qtawesome(manifest, icon_map, wheel)}")

        if args.check:
            print("[check] 映射全部有效（未写盘）")
            return 0

        subset_python = find_subset_python(args.subset_python)
        if not subset_python:
            print("[ERROR] 未找到带 fontTools 的 Python 解释器。"
                  "请 `pip install fonttools` 或用 --subset-python 指定（构建期临时依赖，勿写入 requirements）。")
            return 3
        print(f"[fonttools] 使用解释器：{subset_python}")

        ok_ttf = subset(src_ttf, OUT_DIR / TTF_OUT_NAME, list(manifest.values()), subset_python)
        write_manifest(manifest, OUT_DIR / MANIFEST_OUT_NAME)
        ok_lic = write_license(OUT_DIR / LICENSE_OUT_NAME)

        print("\n[SUMMARY]")
        print(f"  iconset        : {ICONSET} ({ICONSET_DISPLAY} {ICONSET_VERSION}, {ICONSET_LICENSE})")
        print(f"  语义名 / 字形  : {len(manifest)} / {len(set(manifest.values()))}")
        ttf = OUT_DIR / TTF_OUT_NAME
        if ttf.exists():
            print(f"  {TTF_OUT_NAME}: {ttf.stat().st_size} bytes ({ttf.stat().st_size/1024:.1f} KB)")
        print(f"  {MANIFEST_OUT_NAME}: {'OK' if (OUT_DIR / MANIFEST_OUT_NAME).exists() else 'MISSING'}")
        print(f"  {LICENSE_OUT_NAME}: {'OK' if ok_lic else 'MISSING'}")
        return 0 if (ok_ttf and ok_lic) else 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
