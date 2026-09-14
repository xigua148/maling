"""女仆日记（v1.7 F7 / design-v17 §2.5）。

分层契约（R-D 增量）：
  - 本模块纯 stdlib（存储 + 摘要 payload 组装 + 提示词模板）；LLM 调用由
    GUI 层（gui/main.py 生成线程）执行——根级零网络依赖可单测。
  - 存储：~/.maid_coder/diaries.json，365 篇滚动淘汰（highlights 范式）。
  - R-I 硬线：payload 只含**摘要要点**（高光文本/话题名/情绪档位词/消息量
    档位词），绝不含对话原文——build_diary_payload 字段白名单即断言面。
  - Q-C6：次日启动后台补写昨日；失败静默（should_write 仍 True 自然重试），
    绝不落占位假日记。
  - Q-C2：默认开、GuiConfig.diary_enabled 可关。
  - R-A：无"连续写日记 N 天"语义。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

_DIARY_LIMIT = 365  # 滚动淘汰上限（约一年）

# R-I 断言面：payload 白名单键（任何新增键都必须先过隐私评审）
PAYLOAD_KEYS = {"date", "role_name", "highlights", "new_topics", "done_topics",
                "mood_word", "volume_word", "note"}


def _default_filepath() -> Path:
    """diaries.json 默认路径（~/.maid_coder/，R-I 全本地）。"""
    home = Path.home()
    return home / ".maid_coder" / "diaries.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写（utils._atomic_write_json 优先，回落手写——根级不依赖 GUI）。"""
    try:
        from utils import _atomic_write_json as _aw
        _aw(str(path), data)
        return
    except Exception:
        pass
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        import os
        os.replace(tmp, str(path))
    except OSError:
        with open(str(path), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# DiaryManager：存储 + 翻阅 + 导出
# ---------------------------------------------------------------------------
class DiaryManager:
    """diaries.json 读写（365 篇滚动淘汰，date 唯一幂等）。"""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = Path(filepath) if filepath is not None else _default_filepath()
        self._data = self._load()

    # -- 存取 --
    def _default_data(self) -> dict:
        now = datetime.now().isoformat()
        return {"schema_version": 1,
                "meta": {"created_at": now, "updated_at": now},
                "entries": []}

    def _load(self) -> dict:
        try:
            if self.filepath.exists():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge(data)
        except (json.JSONDecodeError, IOError, OSError):
            pass
        return self._default_data()

    def _merge(self, data: Any) -> dict:
        d = self._default_data()
        if not isinstance(data, dict):
            return d
        d["schema_version"] = int(data.get("schema_version", 1) or 1)
        if isinstance(data.get("meta"), dict):
            d["meta"].update(data["meta"])
        if isinstance(data.get("entries"), list):
            d["entries"] = [e for e in data["entries"] if isinstance(e, dict)]
        self._prune(d)
        return d

    @staticmethod
    def _prune(d: dict) -> None:
        """365 篇滚动淘汰（date 倒序保留最新）。"""
        entries = d.get("entries")
        if not isinstance(entries, list):
            return
        entries.sort(key=lambda e: str(e.get("date", "")), reverse=True)
        if len(entries) > _DIARY_LIMIT:
            del entries[_DIARY_LIMIT:]

    def _save(self) -> None:
        self._prune(self._data)
        self._data["meta"]["updated_at"] = datetime.now().isoformat()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _atomic_write_json(self.filepath, self._data)

    # -- 条目 --
    def has_entry(self, date: str) -> bool:
        return any(str(e.get("date", "")) == str(date)
                   for e in self._data.get("entries", []))

    def add_entry(self, date: str, role_name: str, mood: str,
                  content: str) -> bool:
        """新增一篇（同 date 幂等——已有则拒绝，防占位/重播）。"""
        date = str(date or "").strip()
        content = str(content or "").strip()
        if not date or not content or self.has_entry(date):
            return False
        self._data["entries"].append({
            "date": date,
            "role_name": str(role_name or "码铃"),
            "mood": str(mood or ""),
            "content": content,
            "generated_at": datetime.now().isoformat(),
        })
        self._save()
        return True

    def list_entries(self) -> List[dict]:
        """全部日记（date 倒序，翻阅用）。"""
        entries = [dict(e) for e in self._data.get("entries", [])]
        entries.sort(key=lambda e: str(e.get("date", "")), reverse=True)
        return entries

    # -- 导出（纯 stdlib 拼 Markdown）--
    def export_markdown(self, out_path: str, entries: Optional[List[dict]] = None) -> str:
        """导出 Markdown（全部或指定子集），返回写出路径。"""
        items = entries if entries is not None else self.list_entries()
        lines = ["# 她的日记", ""]
        for e in items:
            mood = str(e.get("mood", "")).strip()
            head = str(e.get("date", ""))
            if mood:
                head += f"　{mood}"
            lines.append(f"## {head}")
            lines.append("")
            lines.append(str(e.get("content", "")).strip())
            lines.append("")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return str(out)


# ---------------------------------------------------------------------------
# 摘要 payload（R-I：只含要点，绝不含对话原文）
# ---------------------------------------------------------------------------
def _in_day(stamp: str, day: str) -> bool:
    return str(stamp or "").startswith(str(day))


def _highlights_of_day(highlights_mgr: Any, day: str) -> List[str]:
    """当日新增高光文本（highlights.query_range，v1.6 已有）。"""
    if highlights_mgr is None or not hasattr(highlights_mgr, "query_range"):
        return []
    try:
        rows = highlights_mgr.query_range(day, day) or []
    except Exception:
        return []
    out: List[str] = []
    for r in rows:
        text = str(r.get("text", "")).strip() if isinstance(r, dict) else str(r).strip()
        if text:
            out.append(text)
    return out


def _topics_of_day(memory_mgr: Any, day: str) -> tuple:
    """当日新增/完成话题名（纯读 memory，weekly 同款模式）。"""
    new_topics: List[str] = []
    done_topics: List[str] = []
    if memory_mgr is None:
        return new_topics, done_topics
    try:
        topics = (list(memory_mgr.get_active_topics() or [])
                  + list(memory_mgr.get_archived_topics() or []))
    except Exception:
        return new_topics, done_topics
    seen = set()
    for t in topics:
        if not isinstance(t, dict):
            continue
        subject = str(t.get("subject", "")).strip()
        if not subject or subject in seen:
            continue
        seen.add(subject)
        if _in_day(t.get("completed_at", ""), day):
            done_topics.append(subject)
        elif _in_day(t.get("last_mentioned", ""), day):
            new_topics.append(subject)
    return new_topics, done_topics


def _emotions_of_day(memory_mgr: Any, day: str) -> List[str]:
    if memory_mgr is None or not hasattr(memory_mgr, "get_emotions_history"):
        return []
    try:
        rows = memory_mgr.get_emotions_history() or []
    except Exception:
        return []
    out: List[str] = []
    for e in rows:
        if isinstance(e, dict):
            if _in_day(e.get("ts", "") or e.get("created_at", ""), day):
                emo = str(e.get("emotion", "")).strip()
                if emo:
                    out.append(emo)
    return out


_MOOD_WORDS = {"happy": "开心", "tired": "有点累", "lonely": "有点想你",
               "anxious": "有点不安", "concerned": "有点担心"}


def _mood_word(memory_mgr: Any, day: str) -> str:
    """当日情绪档位词（companion/memory 检测记录 → 词；无数值 R-A）。"""
    emos = _emotions_of_day(memory_mgr, day)
    if not emos:
        return "平静"
    if any(e == "happy" for e in emos):
        return "开心"
    lows = [e for e in emos if e in _MOOD_WORDS]
    if lows:
        return _MOOD_WORDS[lows[0]]
    return "平静"


def _volume_word(n_signals: int) -> str:
    """消息量档位词（由要点信号数估计，绝不含具体条数——R-A 无计数）。"""
    if n_signals <= 0:
        return "安静的一天"
    if n_signals <= 3:
        return "平常的一天"
    return "热闹的一天"


def build_diary_payload(memory_mgr: Any = None, highlights_mgr: Any = None,
                        companion: Any = None, date: str = "",
                        role_name: str = "") -> dict:
    """昨日摘要 payload（R-I 白名单键；结构化字段，可断言）。

    只含：高光文本（用户自己收藏的要点）、话题名、情绪档位词、消息量
    档位词——**绝不含对话原文**。
    """
    day = str(date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"))
    highlights = _highlights_of_day(highlights_mgr, day)
    new_topics, done_topics = _topics_of_day(memory_mgr, day)
    emos = _emotions_of_day(memory_mgr, day)
    mood_word = _mood_word(memory_mgr, day)
    volume_word = _volume_word(len(highlights) + len(new_topics)
                               + len(done_topics) + len(emos))
    return {
        "date": day,
        "role_name": str(role_name or "码铃"),
        "highlights": highlights,
        "new_topics": new_topics,
        "done_topics": done_topics,
        "mood_word": mood_word,
        "volume_word": volume_word,
        "note": "",
    }


def payload_activity(payload: dict) -> int:
    """payload 内容信号数（0 = 昨日无内容，不该写日记）。"""
    return (len(payload.get("highlights") or [])
            + len(payload.get("new_topics") or [])
            + len(payload.get("done_topics") or []))


def should_write(diary_mgr: DiaryManager, payload: dict) -> bool:
    """昨日有内容且未写过（Q-C6；失败静默重试语义的判定面）。"""
    day = str(payload.get("date", ""))
    if not day or payload_activity(payload) <= 0:
        return False
    return not diary_mgr.has_entry(day)


def build_diary_prompt(payload: dict, stage: str = "",
                       diary_tone: bool = False) -> str:
    """生成提示词（以 {角色名} 第一人称写 100–200 字日记）。

    diary_tone：F5 特权表消费（信赖阶段 → 口吻更亲密；无任何数值语义）。
    """
    role = str(payload.get("role_name", "码铃"))
    tone = ""
    if diary_tone:
        tone = "\n语气可以更软更亲近一点（像写给最信任的人），但保持克制、不腻。"
    stage_note = f"\n你们现在处在「{stage}」的阶段。" if stage else ""
    return (
        f"以「{role}」的第一人称，根据下面的当日摘要要点，写一篇 100–200 字的日记。"
        f"{stage_note}"
        "要求：像随手记下的小日子，自然、温暖、口语化；只写摘要里提到的事和感受，"
        "不要编造摘要之外的具体事件，不要出现数字计数或任务统计类的词，"
        "也不要写成待办清单的样子。"
        f"{tone}\n"
        "只输出日记正文本身。\n\n当日摘要（JSON）：\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def extract_diary_content(raw: str) -> str:
    """LLM 输出清洗：去首尾空白/成对引号包裹；空内容返回空串（绝不落占位）。"""
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'“”":
        text = text[1:-1].strip()
    if text.lower().startswith("好的") or text.startswith("以下是"):
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1:].strip()
    return text
