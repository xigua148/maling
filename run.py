#!/usr/bin/env python3
"""
码铃（MaLing）- Cross-platform launcher
Usage:
    python run.py          # Launch GUI mode (default)
    python run.py --cli    # Launch CLI mode

This script is the RECOMMENDED way to start 码铃 (MaLing) on any platform.
It is immune to cmd.exe encoding/codepage issues that plague .bat files.

版本号从 core.__version__ 单一来源读取，禁止再硬编码。
"""
from __future__ import annotations

try:
    import argparse
    import os
    import platform
    import subprocess
    import sys
    from pathlib import Path
except ModuleNotFoundError as _e:
    _missing = str(_e).replace("No module named '", "").replace("'", "")
    print(f"\n缺少依赖模块：{_missing}\n")
    print("这是码铃第一次运行，需要先安装依赖。\n")
    print("请按以下步骤操作：")
    print("1. 打开终端，进入项目目录")
    print("2. 运行：python install.py")
    print("3. 安装完成后，运行：python run.py\n")
    print("或者手动安装：")
    print("   pip install -r requirements_gui.txt\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
class Colors:
    BOLD = "\033[1m"
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"


# ---------------------------------------------------------------------------
# Version（从 core.__version__ 单一来源读取，禁止硬编码）
# ---------------------------------------------------------------------------
try:
    _sys_path = list(sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from core import __version__ as APP_VERSION
    sys.path[:] = _sys_path
except Exception:
    APP_VERSION = "1.0.0"  # core 加载失败时的兜底，与 core.__version__ 保持一致


class NoColor:
    BOLD = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    CYAN = ""
    NC = ""


def print_error(c, msg): print(f"{c.RED}[X]{c.NC}  {msg}")

def print_info(c, msg):  print(f"{c.BLUE}[i]{c.NC}  {msg}")


def pause():
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------
def python_path(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description=f"码铃 v{APP_VERSION} cross-platform launcher",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Launch CLI mode instead of GUI",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored terminal output",
    )
    args = parser.parse_args()

    c = NoColor if args.no_color else Colors

    # Auto-disable colors on Windows if not a TTY
    if platform.system() == "Windows" and not sys.stdout.isatty():
        c = NoColor

    project_dir = Path(__file__).resolve().parent
    venv_dir = project_dir / "venv"
    venv_python = python_path(venv_dir)

    # Check virtual environment
    if not venv_python.exists():
        print()
        print_error(c, "Virtual environment not found!")
        print()
        print("Please run the installer first:")
        print("    python install.py")
        print()
        print("Or install manually:")
        print("    python -m venv venv")
        if platform.system() == "Windows":
            print("    venv\\Scripts\\pip install -r requirements_gui.txt")
        else:
            print("    venv/bin/pip install -r requirements_gui.txt")
        print()
        pause()
        sys.exit(1)

    mode = "cli" if args.cli else "gui"

    print()
    print(f"{c.CYAN}============================================{c.NC}")
    print(f"{c.CYAN}   码铃 v{APP_VERSION} is starting...{c.NC}")
    print(f"{c.CYAN}============================================{c.NC}")
    print()

    os.chdir(project_dir)

    if mode == "cli":
        print_info(c, "Mode: CLI (command line)")
        print_info(c, "Entry: main.py")
        print()
        result = subprocess.run([str(venv_python), "main.py"])
    else:
        print_info(c, "Mode: GUI (graphical interface)")
        print_info(c, "Entry: gui/main.py")
        print()
        result = subprocess.run([str(venv_python), "gui/main.py"])

    # Show error hint if the program exited non-zero
    if result.returncode != 0:
        print()
        print_error(c, f"Program exited with code {result.returncode}")
        print()
        print("Possible causes:")
        print("  - Missing API Key (configure on first run)")
        print("  - Dependencies not installed correctly")
        print("  - Port conflict or other runtime error")
        print()
        print("Try:")
        print("  1. Check config.yaml or .env for API Key")
        print("  2. Re-run: python install.py")
        print("  3. Read the error message above")
        print()
        pause()

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
