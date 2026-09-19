"""core/path_guard.py —— L0 路径守卫（工作空间越界校验 + 备份路径生成）。

真值源下沉说明：
- 本模块的两个函数原定义于根级 `utils.py`（`_validate_file_path` / `_backup_path`）。
- `core/plan_engine.py` 需要它们，而 `core/` 属 L0，禁止 import 根级 L1 模块
  （`AGENTS.md §1`：import 方向只能 L2 → L1 → L0），且会形成
  `core.plan_engine → utils → core` 的循环依赖。
- 故把**实现**下沉至 L0；`utils.py` 改为从本模块**转发**同名符号，
  保证既有 L1 调用点（`editors.py` / `commands/*` 等）与测试入口不变。
- 函数签名、返回值、异常、副作用（备份路径与命名）与原实现**逐字一致**。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Tuple


def _backup_path(filepath: str) -> str:
    """生成带时间戳的备份路径，避免覆盖历史备份。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{filepath}.bak.{ts}"


def _validate_file_path(filepath: str, workspace: str = ".") -> Tuple[bool, str]:
    """验证文件路径是否在工作空间内，防止路径遍历。"""
    try:
        target = (Path(workspace) / filepath).resolve()
        base = Path(workspace).resolve()
        # 检查路径是否以 base 开头
        try:
            target.relative_to(base)
        except ValueError:
            return False, f"路径越界: {filepath} 不在工作目录 {workspace} 内"
        # 拒绝包含 .. 的原始路径
        if ".." in filepath.replace("\\", "/"):
            return False, "路径包含非法的父目录引用 .."
        return True, str(target)
    except Exception as e:
        return False, f"路径验证失败: {e}"


# ---------------------------------------------------------------------------
# v2.5(D-V25-08): 应用根目录解析 —— 根治「工作目录决定配置位置」
# ---------------------------------------------------------------------------
# 背景：config.yaml 此前一律用裸相对路径 Path("config.yaml") 解析，于是读/写
# 位置取决于**启动时的工作目录**。历史上出过「从运行对话框启动 → 工作目录变成
# System32 → 配置写不进 + 图标变默认」的事故；开发版与打包版也因此被迫各存一份
# 配置。改为锚定应用根后，从任何工作目录启动都读写同一份。
#
# 注意与 gui/main.py 的 BASE_DIR（= sys._MEIPASS，**打包资源**目录、只读）区分：
# 本函数返回的是**用户可写的安装目录**，两者在 onedir 形态下不是同一个位置。

def resolve_app_root() -> Path:
    """应用根目录（config.yaml 等可写相对资源的基准），返回绝对路径。

    - 打包形态（PyInstaller，``sys.frozen`` 为真）：**可执行文件所在目录**。
      onedir 与 onefile 同为 exe 旁 —— 这正是现有安装包里 config.yaml 的位置，
      因此本改动对既有安装**零迁移**。
    - 源码形态：项目根（本文件位于 ``core/``，上溯两级）。

    本函数只定位、**不创建目录**（创建交给写入方，失败时行为不变）。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_config_path() -> Path:
    """config.yaml 的绝对路径（= 应用根 / config.yaml）。"""
    return resolve_app_root() / "config.yaml"
