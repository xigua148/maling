"""指令模板注册表 —— 聊天输入框的 `/` 快捷指令：内置 8 个 + 用户自定义。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("maid_coder.gui")

COMMANDS_FILE = Path.home() / ".maid_coder" / "commands.json"

# 内置指令：(name, description, template)
BUILTIN_COMMANDS: List[Dict] = [
    {"name": "/explain", "description": "解释代码", "template": "/explain "},
    {"name": "/optimize", "description": "优化建议", "template": "/optimize "},
    {"name": "/test", "description": "生成测试", "template": "/test "},
    {"name": "/fix", "description": "修复bug", "template": "/fix "},
    {"name": "/refactor", "description": "重构", "template": "/refactor "},
    {"name": "/doc", "description": "生成文档", "template": "/doc "},
    {"name": "/translate", "description": "翻译", "template": "/translate "},
    {"name": "/summary", "description": "总结", "template": "/summary "},
]


class CommandRegistry:
    """管理内置与用户自定义指令。"""

    def __init__(self, commands_file: Optional[Path] = None):
        self.commands_file = commands_file or COMMANDS_FILE
        self._builtin: List[Dict] = list(BUILTIN_COMMANDS)
        self._custom: List[Dict] = []
        self._load_custom()

    def _load_custom(self) -> None:
        if not self.commands_file.exists():
            return
        try:
            with open(self.commands_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            custom = data.get("commands", [])
            if isinstance(custom, list):
                self._custom = [
                    {
                        "name": item.get("name", ""),
                        "description": item.get("description", ""),
                        "template": item.get("template", item.get("name", "") + " "),
                    }
                    for item in custom
                    if isinstance(item, dict) and item.get("name")
                ]
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("加载自定义指令失败: %s", exc)

    def save_custom(self) -> None:
        try:
            self.commands_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.commands_file, "w", encoding="utf-8") as f:
                json.dump({"commands": self._custom}, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("保存自定义指令失败: %s", exc)

    def add_custom(self, name: str, description: str = "") -> bool:
        if not name.strip():
            return False
        if not name.startswith("/"):
            name = "/" + name
        if self.get(name) is not None:
            return False
        self._custom.append({
            "name": name,
            "description": description,
            "template": name + " ",
        })
        self.save_custom()
        return True

    def get(self, name: str) -> Optional[Dict]:
        for cmd in self._builtin + self._custom:
            if cmd["name"] == name:
                return cmd
        return None

    def all_commands(self) -> List[Dict]:
        return self._builtin + self._custom

    def search(self, prefix: str) -> List[Dict]:
        """按前缀过滤指令（用于补全列表）。prefix 已含或不含 / 均可。"""
        if not prefix.startswith("/"):
            prefix = "/" + prefix
        return [c for c in self.all_commands() if c["name"].startswith(prefix)]
