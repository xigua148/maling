# -*- mode: python ; coding: utf-8 -*-
r"""updater.spec —— 码铃 v2.0 自动更新 sidecar 打包（docs/design-v20.md §2 D-V20-08 / §5 V20-14）。

产物：dist_updater/maling_updater.exe（onefile，体积最小化）
    * 只收入口 `maling_updater.py`；**不收 gui/core/任何 Qt 模块**（守 R-F 零第三方依赖）。
    * console=True —— 与 design D-V20-08 的 "console=False" 定案**有意不同**，理由（实测决定）：
      1) `--version` 契约必须"打印自身版本"且被主进程用管道读取（`subprocess.run(...,
         capture_output=True)`）做版本一致性判定；PyInstaller 的 **windowed(runw) 引导器会把
         sys.stdout 置空**，console=False 下 `--version` 在管道里恒为空 → 契约失效。
      2) 换包时的"黑框"风险已由**拉起侧**消除：主进程按 D-V20-01 用
         `DETACHED_PROCESS | CREATE_NO_WINDOW` 拉起，console 子系统进程也不会显示窗口。
      3) 便于现场排障：可直接 `maling_updater.exe --version` / `-h`。
      副作用：用户若手工双击该 exe，会瞬时闪一个控制台并立刻以退出码 2 结束（无参拒绝运行），
      但该 exe 从不面向用户双击（位于 %APPDATA%/maid_coder/updater/，只由主进程拉起）。
    * upx=False（与主 spec 一致：UPX 显著提高杀软误报率，体积换安全）。
    * icon 复用应用图标，任务管理器里可辨识。

用法：
    pyinstaller updater.spec --noconfirm --clean    → dist_updater/maling_updater.exe

注意：本 spec **不修改**两个主 spec（内嵌 sidecar 的 datas 与收口由 V20-17 收尾批处理）。
"""
import os

block_cipher = None

# 体积最小化：把明确不会被 sidecar 用到的第三方库与重型/无关标准库排除。
# sidecar 仅依赖 argparse/ctypes/os/shutil/subprocess/json/hashlib/time/logging/
# pathlib/sys/tempfile/zipfile —— 下面这些即使被 PyInstaller 误扫到也一律剔除。
_EXCLUDES = [
    # GUI / 科学计算 / 网络 / 打包工具链（sidecar 一律不用）
    'PySide6', 'PyQt5', 'PyQt6', 'shiboken6', 'sip',
    'numpy', 'scipy', 'pandas', 'matplotlib', 'PIL', 'Pillow',
    'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna', 'chardet',
    'yaml', 'pygments', 'psutil', 'pyperclip',
    'speech_recognition', 'pyaudio', 'sounddevice', 'soundfile',
    'tkinter', '_tkinter',
    'setuptools', 'pip', 'wheel', 'pkg_resources',
    # 重型/交互式标准库（sidecar 无 TTY、无浏览器、无 GUI）
    'unittest', 'pydoc', 'doctest', 'pdb', 'bdb', 'cProfile', 'profile', 'pstats',
    'turtle', 'curses', 'idlelib', 'lib2to3', 'distutils',
]

a = Analysis(
    ['maling_updater.py'],
    pathex=[],
    binaries=[],
    datas=[],                       # sidecar 无外部资源依赖（纯标准库）
    hiddenimports=[],               # 无动态 import
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=_EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onefile：binaries/datas/zipfiles 全部内嵌进单个 exe
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='maling_updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,                   # 见文件头理由：--version 需可被管道读取；黑框由启动侧
                                    # CREATE_NO_WINDOW 消除
    icon='gui/assets/maling.ico',
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
