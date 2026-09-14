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
