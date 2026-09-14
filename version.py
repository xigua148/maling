"""version.py —— 版本号单源管理。

版本号唯一来源：version.json。
所有需要版本号的地方（GUI 标题、构建脚本、更新检查）都从这里读取。

用法：
    from version import get_version, get_version_info
    print(get_version())          # "1.4.8"
    print(get_version_info())     # 完整 dict
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

_VERSION_CACHE: Optional[dict] = None
_VERSION_FILE = Path(__file__).parent / "version.json"


def _load_version_file() -> dict:
    """加载 version.json（带缓存）。"""
    global _VERSION_CACHE
    if _VERSION_CACHE is not None:
        return _VERSION_CACHE
    try:
        with open(_VERSION_FILE, "r", encoding="utf-8") as f:
            _VERSION_CACHE = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _VERSION_CACHE = {"version": "0.0.0", "_error": str(e)}
    return _VERSION_CACHE


def get_version() -> str:
    """获取版本号字符串，如 '1.4.8'。"""
    return _load_version_file().get("version", "0.0.0")


def get_version_info() -> dict:
    """获取完整版本信息 dict。"""
    return dict(_load_version_file())


def get_version_tuple() -> tuple:
    """获取版本号元组，如 (1, 4, 8)。便于比较。"""
    v = get_version()
    try:
        parts = v.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def is_at_least(major: int, minor: int, patch: int = 0) -> bool:
    """检查当前版本是否 >= 指定版本。"""
    return get_version_tuple() >= (major, minor, patch)


def get_app_title() -> str:
    """获取应用标题字符串（用于窗口标题等）。"""
    return f"码铃 MaLing v{get_version()}"


def get_download_url(mirror: str = "github") -> str:
    """获取下载链接。"""
    info = get_version_info()
    downloads = info.get("downloads", {})
    return downloads.get(mirror, downloads.get("github", ""))


def invalidate_cache() -> None:
    """清除缓存（用于测试或热更新后）。"""
    global _VERSION_CACHE
    _VERSION_CACHE = None
