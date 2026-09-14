"""highlights.py —— v1.3 P2-3 高光回忆册存储（纯 stdlib、本地、原子写）

设计（docs/design-v13.md D-V13-06 / §4.2，PRD P2-3）：
  - 独立文件 `get_user_data_dir()/highlights.json`（Windows 桌面版目录见 gui.utils），
    避免总量无上界、逐条独立生命周期撑大 companion.json 的整档原子写（架构裁决）。
  - 快照 = {id, role(user|assistant), date(YYYY-MM-DD), text(<=500 字截断),
           session_id, mood(当时 companion.mood), at(ISO)}；session 只作回溯定位不强链。
  - 上限 500 条滚动淘汰（写进 manager，UI 不显示计数）；全部读写显式 encoding="utf-8"；
    原子写先写 `.tmp` 再 `os.replace`（与 companion._atomic_write_json 同语义）。
  - 红线：数据纯本地绝不上云；不做打卡/断签/连续收藏 N 天/成就（R-A）。
  - 顶层零第三方依赖（PySide6 不 import）；get_user_data_dir 走函数内延迟 import，
    避免把 gui 包拉入本模块的 import 链（frozen hiddenimports 已收录 highlights）。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

_logger = logging.getLogger("maid_coder.highlights")

_HIGHLIGHT_LIMIT = 500       # 上限条数（滚动淘汰）
_TEXT_LIMIT = 500            # 单条文本截断字数


def _default_data_dir() -> Path:
    """用户数据目录：优先 gui.utils.get_user_data_dir（Windows 桌面版 APPDATA/maid_coder）。"""
    try:
        from gui.utils import get_user_data_dir
        return get_user_data_dir()
    except Exception:
        return Path(os.path.expanduser("~/.maid_coder"))


def _default_filepath() -> Path:
    return _default_data_dir() / "highlights.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写 JSON（.tmp + os.replace），纯 stdlib。"""
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def _truncate_text(text: str, limit: int = _TEXT_LIMIT) -> str:
    s = (text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _default_data() -> dict:
    now = datetime.now().isoformat()
    return {
        "schema_version": 1,
        "meta": {"created_at": now, "updated_at": now},
        "items": [],
    }


class HighlightsManager:
    """高光回忆管理器：本地 json 增删查、500 条上限滚动淘汰、原子写。"""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = Path(filepath) if filepath is not None else _default_filepath()
        self._data = self._load()

    # -- 读写 --
    def _load(self) -> dict:
        try:
            if self.filepath.exists():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge_defaults(data)
        except (json.JSONDecodeError, IOError, OSError) as exc:
            _logger.warning("highlights.json 读取失败，重建默认: %s", exc)
        return _default_data()

    def _merge_defaults(self, data: dict) -> dict:
        d = _default_data()
        if not isinstance(data, dict):
            return d
        d["schema_version"] = int(data.get("schema_version", 1) or 1)
        if isinstance(data.get("meta"), dict):
            d["meta"].update(data["meta"])
        if isinstance(data.get("items"), list):
            d["items"] = data["items"]
        # 字段守卫：文本超长截断、缺 id/role 的脏条目剔除
        cleaned = []
        for it in d["items"]:
            if not isinstance(it, dict) or not it.get("id"):
                continue
            if it.get("role") not in ("user", "assistant"):
                continue
            it["text"] = _truncate_text(it.get("text"))
            cleaned.append(it)
        d["items"] = cleaned
        if len(d["items"]) > _HIGHLIGHT_LIMIT:
            del d["items"][:-_HIGHLIGHT_LIMIT]
        return d

    def _save(self) -> None:
        self._data["meta"]["updated_at"] = datetime.now().isoformat()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _atomic_write_json(self.filepath, self._data)

    def to_dict(self) -> dict:
        return self._data

    # -- 业务 API --
    def add(self, role: str, text: str, session_id: str = "", mood: str = "normal") -> str:
        """收藏一条高光回忆；返回新 id。text 超过 500 字自动截断。"""
        now = datetime.now()
        item = {
            "id": "hl_" + uuid.uuid4().hex[:8],
            "role": role if role in ("user", "assistant") else "assistant",
            "date": now.strftime("%Y-%m-%d"),
            "text": _truncate_text(text),
            "session_id": str(session_id or ""),
            "mood": str(mood or "normal"),
            "at": now.isoformat(),
        }
        items = self._data.setdefault("items", [])
        items.append(item)
        if len(items) > _HIGHLIGHT_LIMIT:
            del items[:-_HIGHLIGHT_LIMIT]
        self._save()
        return item["id"]

    def remove(self, item_id: str) -> bool:
        """按 id 移除一条；不存在返回 False。"""
        items = self._data.get("items") or []
        before = len(items)
        self._data["items"] = [it for it in items if it.get("id") != item_id]
        if len(self._data["items"]) != before:
            self._save()
            return True
        return False

    def clear(self) -> None:
        """清空全部高光回忆（整档重写，无事务诉求）。"""
        self._data["items"] = []
        self._save()

    def all(self) -> List[dict]:
        """返回全部条目副本（时间倒序）。"""
        items = list(self._data.get("items") or [])
        items.sort(key=lambda it: str(it.get("at", "")), reverse=True)
        return [dict(it) for it in items]

    def query_range(self, start_date: str, end_date: str, limit: int = 3) -> List[dict]:
        """v1.6(P1-3/D-V16-10): 按日期区间取高光（含首尾，时间倒序，≤limit 条）。

        纯读方法；start_date/end_date 为 "YYYY-MM-DD"（inclusive）；
        非法区间返回空表；供 weekly 规则骨架引用（用户收藏原文，R-I 安全面）。
        """
        try:
            sd = datetime.strptime(str(start_date), "%Y-%m-%d").date()
            ed = datetime.strptime(str(end_date), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return []
        if sd > ed:
            return []
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 3
        if limit <= 0:
            return []
        hits = []
        for it in self._data.get("items") or []:
            try:
                d = datetime.strptime(str(it.get("date", "")), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            if sd <= d <= ed:
                hits.append(dict(it))
        hits.sort(key=lambda it: str(it.get("at", "")), reverse=True)
        return hits[:limit]
