from __future__ import annotations

import difflib
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple, Dict

from core import AppConfig, G, R
from api import APIClient
from utils import _backup_path, _find_latest_backup, _validate_file_path

# ---------------------------------------------------------------------------
class FileEditor:
    """支持 /read /edit /apply /undo 的文件编辑系统。"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self._pending_diff: Optional[Tuple[str, str, str]] = None  # (filepath, original, modified)
        self._backup_map: Dict[str, str] = {}  # filepath -> .bak path

    def read_file(self, filepath: str, workspace: str = ".") -> str:
        # 路径安全检查
        ok, msg = _validate_file_path(filepath, workspace)
        if not ok:
            return f"❌ {msg}"
        p = Path(filepath).expanduser()
        if not p.exists():
            return f"错误: 文件不存在: {filepath}"
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            # 限制显示长度
            display = content[:3000]
            if len(content) > 3000:
                display += f"\n... (共 {len(content)} 字符，已截断)"
            return f"📄 {filepath}:\n```\n{display}\n```"
        except Exception as e:
            return f"读取失败: {e}"

    def edit_file(self, filepath: str, instruction: str, api: APIClient, cfg: AppConfig,
                  system_prompt: str, workspace: str = ".") -> str:
        """让 AI 根据自然语言描述生成 diff。"""
        # 路径安全检查
        ok, msg = _validate_file_path(filepath, workspace)
        if not ok:
            return f"❌ {msg}"
        p = Path(filepath).expanduser()
        if not p.exists():
            return f"错误: 文件不存在: {filepath}"
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                original = f.read()
        except Exception as e:
            return f"读取失败: {e}"

        edit_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"请根据以下指令修改文件，输出完整的修改后文件内容。\n"
                f"文件路径: {filepath}\n"
                f"修改指令: {instruction}\n\n"
                f"原始内容:\n```\n{original[:5000]}\n```\n\n"
                f"请输出修改后的完整文件内容（用 ``` 包裹）："
            )},
        ]
        try:
            resp = api.chat(edit_messages, max_tokens=cfg.api_max_tokens)
            modified = resp["choices"][0]["message"].get("content", "")
            # 提取代码块
            match = re.search(r"```(?:\w+)?\n(.*?)\n```", modified, re.DOTALL)
            if match:
                modified = match.group(1)

            # 生成 diff
            diff = list(difflib.unified_diff(
                original.splitlines(keepends=True),
                modified.splitlines(keepends=True),
                fromfile=filepath,
                tofile=filepath + ".new",
            ))
            diff_str = "".join(diff)
            if not diff_str:
                return "ℹ️ 未检测到变更。"

            self._pending_diff = (str(p), original, modified)
            return f"📋 生成的 diff:\n```diff\n{diff_str[:3000]}\n```\n输入 `/apply` 确认应用，或 `/edit` 重新生成。"
        except Exception as e:
            return f"生成修改方案失败: {e}"

    def apply(self) -> str:
        if not self._pending_diff:
            return "没有待应用的修改。"
        filepath, original, modified = self._pending_diff
        # 备份：使用 /edit 时保存的 original，写入带时间戳的备份
        bak_path = _backup_path(filepath)
        try:
            with open(bak_path, "w", encoding="utf-8") as f:
                f.write(original)
            self._backup_map[filepath] = bak_path

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(modified)
            self._pending_diff = None
            return G(f"✅ 已应用修改并备份到 {bak_path}")
        except Exception as e:
            return f"应用失败: {e}"

    def undo(self, filepath: Optional[str] = None) -> str:
        if filepath:
            bak = _find_latest_backup(filepath)
            if not bak or not os.path.exists(bak):
                return f"没有找到备份文件: {filepath}.bak*"
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)
                return G(f"✅ 已撤销 {filepath} 的修改（使用备份: {bak}）")
            except Exception as e:
                return f"撤销失败: {e}"

        if self._backup_map:
            last = list(self._backup_map.keys())[-1]
            bak = self._backup_map.get(last)
            if not bak or not os.path.exists(bak):
                bak = _find_latest_backup(last)
            if not bak or not os.path.exists(bak):
                return f"没有找到备份文件: {last}.bak*"
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(last, "w", encoding="utf-8") as f:
                    f.write(content)
                return G(f"✅ 已撤销 {last} 的修改（使用备份: {bak}）")
            except Exception as e:
                return f"撤销失败: {e}"
        return "没有可撤销的修改。"


# ---------------------------------------------------------------------------
# 会话管理器
