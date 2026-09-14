from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

from core import Y
from security import is_command_safe


# ---------------------------------------------------------------------------
# 交互式确认（v10.14 重构）
# ---------------------------------------------------------------------------
def confirm_harness_call(task_prompt: str) -> bool:
    """CLI 默认的 harness 确认函数：TTY 下问用户 Y/n；非 TTY 一律返回 True。

    行为说明（v10.14 设计取舍）：
    - CLI 主循环（session.single_turn）调用本函数后调用 call_harness。
    - 非 TTY（脚本、CI、子进程）下不阻塞用户，自动放行；上层若要更严
      的策略可自行包装本函数或传不同的 confirm_fn 给 call_harness。
    - GUI 当前没有接入 call_harness；若未来接入，建议在调用方
      弹 QMessageBox.question 后再传 confirm_fn=lambda _: True
      或直接传自己的对话框包装函数。

    ⚠ 风险说明（fail-open，与 AGENTS.md §2.1 存在张力）：
    - 本函数在**非 TTY**（脚本 / CI / 子进程 / GUI）下**返回 True 自动放行**，
      属 fail-open；§2.1 要求「确认渠道未配置时一律拒绝」。当前仅靠前置的
      `is_command_safe(task_prompt, safety_mode)`（默认 blacklist）兜底，
      并非完全无防护，但**仍与 §2.1 精神不符**（已记为既存红线，见
      `_codebase_map.md §6.8.3 #3`）。
    - 正确修法：为 GUI 路径传入**显式确认对话框**（在调用方弹窗后再决定），
      而非在 harness 内部把非 TTY 直接改为拒绝——后者会让**永远非 TTY 的 GUI
      直接失去 harness 功能**，属功能回归。
    - 该修法需要改动 `confirm_fn` 的注入点 `session.py`（`call_harness` 的
      confirm_fn 由 `session.py` 传入），而 `session.py` 属保护区，
      **需另行授权后方可实施**。当前**不修行为**，仅留此说明。
    """
    if not sys.stdin.isatty():
        return True
    print(Y("⚠️ 即将执行外部命令，请确认安全性。"))
    print(f"   任务描述: {task_prompt[:120]}{'...' if len(task_prompt) > 120 else ''}")
    try:
        ans = input(Y("   继续执行？(Y/n): ")).strip()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    return ans.lower() in ("y", "yes", "")


# ---------------------------------------------------------------------------
def call_harness(task_prompt: str, harness_path: str, workspace: str, timeout: int,
                 logger: logging.Logger, safety_mode: str = "blacklist",
                 confirm_fn: Optional[Callable[[str], bool]] = None) -> str:
    """执行 harness 工具。

    v10.14 重构：
    - 交互式确认抽出到 confirm_harness_call（CLI 默认）；本函数不再
      硬拒非 TTY，也不再主动调用 input()。
    - confirm_fn=None 时不确认直接执行（GUI / 自动化场景）。
    - 增加基于 safety_mode 的命令安全检查（blacklist/whitelist/off）。
    - 删除 shell=True 回退分支，FileNotFoundError 直接报错返回——避免
      把整段 task_prompt 放进 shell 命令行扩大注入面。
    """
    # 1) 基于 safety_mode 的字符串匹配安全检查
    safe, reason = is_command_safe(task_prompt, safety_mode)
    if not safe:
        logger.warning("harness 调用被安全策略拦截: %s", reason)
        return f"❌ 已拒绝执行：{reason}"

    # 2) 交互式确认（CLI 默认；GUI 应传自己的对话框包装或 None）
    if confirm_fn is not None and not confirm_fn(task_prompt):
        return "已取消执行（用户拒绝）。"

    # 3) 解析 harness 路径
    path_obj = Path(harness_path)
    if not path_obj.exists():
        found = shutil.which(harness_path)
        if not found:
            return f"错误: 未找到 harness 可执行文件 '{harness_path}'"
        path_obj = Path(found)

    cmd_list = [str(path_obj), "--profile", "headless", task_prompt]
    logger.debug("执行命令: %s", cmd_list)

    # 4) 真正执行（仅 shell=False；FileNotFoundError 不再降级）
    try:
        result = subprocess.run(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            cwd=workspace,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        err = result.stderr.strip() if result.stderr else "执行失败，无错误输出"
        return f"执行失败 (exit={result.returncode}): {err}"
    except subprocess.TimeoutExpired:
        return "错误: 命令执行超时"
    except FileNotFoundError as e:
        # v10.14: 不再降级到 shell=True（避免把 task_prompt 串到 shell）
        return f"错误: harness 不可执行 ({e})"
    except Exception as e:
        return f"执行异常: {e}"


# ---------------------------------------------------------------------------
# 文件编辑器
