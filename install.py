#!/usr/bin/env python3
"""
码铃（MaLing）- Cross-platform installation bootstrap
Usage: python install.py [--no-color]

This script is the RECOMMENDED way to install 码铃 (MaLing) on any platform.
It is immune to cmd.exe encoding/codepage issues that plague .bat files.

版本号从 core/__init__.py 的 __version__ 单一来源文本级读取
（安装依赖前不能 import core），禁止再硬编码。
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Version（单一来源：core/__init__.py 的 __version__，文本级读取）
# ---------------------------------------------------------------------------
def _core_version() -> str:
    """从 core/__init__.py 文本级提取 __version__（安装依赖前无法 import core）。"""
    try:
        src = (Path(__file__).resolve().parent / "core" / "__init__.py").read_text(
            encoding="utf-8"
        )
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', src, re.M)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "1.0.0"  # 读取失败的兜底，与 core.__version__ 保持一致


APP_VERSION = _core_version()


# ---------------------------------------------------------------------------
# Color / text helpers
# ---------------------------------------------------------------------------
class Colors:
    """ANSI escape codes for terminal styling."""
    BOLD = "\033[1m"
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"  # No Color


class NoColor:
    """Drop-in replacement when --no-color is used."""
    BOLD = ""
    RED = ""
    GREEN = ""
    YELLOW = ""
    BLUE = ""
    CYAN = ""
    NC = ""


def header(c):
    print()
    print(f"{c.CYAN}============================================{c.NC}")
    print(f"{c.CYAN}   码铃 v{APP_VERSION} - Installation Wizard{c.NC}")
    print(f"{c.CYAN}============================================{c.NC}")
    print()


def print_success(c, msg): print(f"{c.GREEN}[OK]{c.NC} {msg}")

def print_info(c, msg):    print(f"{c.BLUE}[i]{c.NC}  {msg}")

def print_warn(c, msg):    print(f"{c.YELLOW}[!]{c.NC}  {msg}")

def print_error(c, msg):   print(f"{c.RED}[X]{c.NC}  {msg}")


def pause():
    """Wait for a key press, cross-platform."""
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------------------
# Python detection
# ---------------------------------------------------------------------------
MIN_PY_MAJOR, MIN_PY_MINOR = 3, 10


def _parse_python_version(stdout: str) -> tuple[int, int] | None:
    """Extract (major, minor) from 'Python 3.12.1' style output."""
    m = re.search(r"Python\s+(\d+)\.(\d+)", stdout)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def detect_python() -> Path:
    """
    Return the path to a suitable Python 3.10+ interpreter.
    We are already running under *some* Python, so this is mostly a sanity
    check plus a fallback for exotic PATH setups.
    """
    # The interpreter currently running this script
    current = Path(sys.executable).resolve()
    current_ver = sys.version_info[:2]
    if current_ver >= (MIN_PY_MAJOR, MIN_PY_MINOR):
        return current

    # Otherwise search PATH for alternatives (rare, but possible)
    candidates = ["python3.12", "python3.11", "python3.10", "python3", "python"]
    for cmd in candidates:
        exe = _which(cmd)
        if not exe:
            continue
        try:
            out = subprocess.run(
                [str(exe), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            ver = _parse_python_version(out.stdout + out.stderr)
            if ver and ver >= (MIN_PY_MAJOR, MIN_PY_MINOR):
                return exe
        except Exception:
            continue

    return None


def _which(cmd: str) -> Path | None:
    """Find an executable in PATH (simple cross-platform which)."""
    path_env = os.environ.get("PATH", "")
    for directory in path_env.split(os.pathsep):
        candidate = Path(directory) / cmd
        if os.access(candidate, os.X_OK):
            return candidate
        # Windows also needs .exe / .cmd / .bat
        for suffix in (".exe", ".cmd", ".bat"):
            candidate_ext = candidate.with_suffix(suffix)
            if os.access(candidate_ext, os.X_OK):
                return candidate_ext
    return None


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------
def platform_name() -> str:
    system = platform.system()
    if system == "Windows":
        return "Windows"
    if system == "Darwin":
        return "macOS"
    return "Linux"


def pip_path(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "pip.exe"
    return venv_dir / "bin" / "pip"


def python_path(venv_dir: Path) -> Path:
    if platform.system() == "Windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


# ---------------------------------------------------------------------------
# Installation steps
# ---------------------------------------------------------------------------
def step_detect_python(c) -> Path:
    print(f"{c.BOLD}[1/4]{c.NC} Detecting Python environment...")
    py = detect_python()
    if py is None:
        print()
        print_error(c, f"Python {MIN_PY_MAJOR}.{MIN_PY_MINOR}+ not found!")
        print()
        print(f"码铃 v{APP_VERSION} requires Python 3.10 or newer.")
        print()
        pn = platform_name()
        if pn == "Windows":
            print("How to install Python on Windows:")
            print("  1. Visit https://www.python.org/downloads/")
            print("  2. Download Python 3.12 (or 3.11/3.10)")
            print('  3. During install, CHECK "Add Python to PATH"')
            print("  4. Re-open this terminal and run again")
            print()
            print("Quick link:")
            print("  https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe")
        elif pn == "macOS":
            print("How to install Python on macOS:")
            print("  brew install python@3.12")
            print()
            print("Or visit: https://www.python.org/downloads/macos/")
        else:
            print("How to install Python on Linux:")
            print("  Ubuntu/Debian: sudo apt install python3.12 python3.12-venv python3-pip")
            print("  Fedora/RHEL:   sudo dnf install python3.12 python3-pip")
            print("  Arch:          sudo pacman -S python python-pip")
        print()
        pause()
        sys.exit(1)

    # Print version info
    out = subprocess.run(
        [str(py), "--version"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    print_info(c, f"Found Python: {(out.stdout + out.stderr).strip()}")
    return py


def step_create_venv(c, python_exe: Path, venv_dir: Path):
    print()
    print(f"{c.BOLD}[2/4]{c.NC} Creating virtual environment...")
    if venv_dir.exists():
        print_warn(c, "Virtual environment already exists, skipping...")
        return
    try:
        subprocess.run(
            [str(python_exe), "-m", "venv", str(venv_dir)],
            check=True,
            timeout=120,
        )
        print_success(c, f"Created virtual environment: {venv_dir.name}/")
    except subprocess.CalledProcessError as exc:
        print()
        print_error(c, "Failed to create virtual environment!")
        print()
        print("Possible causes:")
        print("  - The 'venv' module is not installed")
        print("  - No write permission in the current directory")
        print("  - Disk is full")
        print()
        print("Try:")
        print(f"  {python_exe} -m ensurepip --upgrade")
        print("  Check directory permissions / disk space")
        print()
        pause()
        sys.exit(1)


def step_install_deps(c, venv_dir: Path, requirements: Path):
    print()
    print(f"{c.BOLD}[3/4]{c.NC} Installing dependencies (may take a few minutes)...")
    print_info(c, f"Source: {requirements.name}")
    print()

    pip = pip_path(venv_dir)

    # Upgrade pip first (non-fatal)
    try:
        subprocess.run(
            [str(pip), "install", "--upgrade", "pip"],
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass

    # Install requirements
    try:
        subprocess.run(
            [str(pip), "install", "-r", str(requirements)],
            check=True,
        )
        print_success(c, "Dependencies installed!")
    except subprocess.CalledProcessError:
        print()
        print_error(c, "Dependency installation failed!")
        print()
        print("Possible causes:")
        print("  - Network issue (PyPI unreachable)")
        print(f"  - {requirements.name} is missing or corrupted")
        print("  - A package needs a C++ compiler (rare for wheels)")
        print()
        print("Try these fixes:")
        print("  1. Check your internet, or use a mirror:")
        print(f"     {pip} install -r {requirements.name} -i https://pypi.tuna.tsinghua.edu.cn/simple")
        print("  2. Install PySide6 separately (it's the largest):")
        print(f"     {pip} install 'PySide6>=6.5'")
        if platform.system() == "Linux":
            print("  3. Install build tools:")
            print("     sudo apt install build-essential")
        print()
        pause()
        sys.exit(1)


def step_done(c):
    print()
    print(f"{c.BOLD}[4/4]{c.NC} Installation complete!")
    print()
    print(f"{c.GREEN}============================================{c.NC}")
    print(f"{c.GREEN}   Installation successful! 码铃 v{APP_VERSION} is ready{c.NC}")
    print(f"{c.GREEN}============================================{c.NC}")
    print()
    print("How to start:")
    print()
    print("  GUI mode (default):")
    print("    python run.py")
    print()
    print("  CLI mode:")
    print("    python run.py --cli")
    print()
    print("First time?")
    print("  You will be asked for an API Key (DeepSeek, etc.)")
    print("  Or create a .env file:")
    print('    DEEPSEEK_API_KEY=sk-your-key-here')
    print()
    print("Common commands:")
    print("  /help    Show all commands")
    print("  /deep    Toggle deep-thinking mode")
    print("  /code    Enter coding mode")
    print("  /save    Save current session")
    print()
    print(f"{c.CYAN}============================================{c.NC}")
    print()
    pause()


def main():
    parser = argparse.ArgumentParser(
        description=f"码铃 v{APP_VERSION} cross-platform installer",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored terminal output",
    )
    args = parser.parse_args()

    c = NoColor if args.no_color else Colors

    # Disable colors automatically on Windows if stdout is not a terminal
    if platform.system() == "Windows" and not sys.stdout.isatty():
        c = NoColor

    header(c)

    project_dir = Path(__file__).resolve().parent
    venv_dir = project_dir / "venv"
    requirements = project_dir / "requirements_gui.txt"

    if not requirements.exists():
        print_error(c, f"{requirements.name} not found in project directory!")
        pause()
        sys.exit(1)

    python_exe = step_detect_python(c)
    step_create_venv(c, python_exe, venv_dir)
    step_install_deps(c, venv_dir, requirements)
    step_done(c)


if __name__ == "__main__":
    main()
