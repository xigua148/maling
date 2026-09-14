"""timeline.py —— v1.8(F3/D-V18-04/Q-D10) 共同经历时间线：三源聚合纯函数。

纯 stdlib、零 Qt、零 LLM、零网络；只读视图，不提供任何写入/编辑（单一真值
源：删高光/删话题/删日记 → 节点自然消失，R-I）。默认回看 6 个月，UI 侧
「展开更早」按 6 个月分段追加（months 参数透传，不做无限滚动）。

三源 + 周记存在性（design D-V18-04）：
  ① highlights（用户收藏原文，HighlightsManager.query_range 复用，≤500 字既有保证）
  ② topics.archived（已完成话题：completed_at + subject）
  ③ anniversaries（纪念日周年语义月节点：birthday / first_meet，MM-DD）
  ④ weekly 存在性（周记节点，点击跳往期回顾 Tab）

红线（R-A）：节点只有「日期 + 原文/标题 + 类型」，**无计数、无统计、无
「第 N 条记忆」**；月份标签为「YYYY 年 M 月」自然日期呈现（非计数语义）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, List, Optional

__all__ = ["build_timeline"]

# 节点类型（UI 呈现用 icon 映射在 page_memory_book 侧，本模块保持零依赖）
KIND_HIGHLIGHT = "highlight"    # ✨ 收藏的高光
KIND_TOPIC = "topic"            # ✅ 一起完成的事
KIND_ANNIVERSARY = "anniversary"  # 🎂 值得记着的日子
KIND_WEEKLY = "weekly"          # 📒 那一周的小结

_ANNIVERSARY_LABELS = {
    "birthday": "生日",
    "first_meet": "初次相见的日子",
}


def _parse_date(value: Any) -> Optional[date]:
    """'YYYY-MM-DD'（或 ISO 前缀）-> date；空/非法返回 None。"""
    s = str(value or "").strip()
    if len(s) >= 10:
        s = s[:10]
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _month_key(d: date) -> str:
    """date -> 'YYYY-MM' 月份分组键（跨年分组正确性的唯一真值）。"""
    return f"{d.year:04d}-{d.month:02d}"


def _month_label(key: str) -> str:
    """'YYYY-MM' -> 'YYYY 年 M 月'（自然日期呈现，非计数语义）。"""
    try:
        y, m = key.split("-")
        return f"{int(y)} 年 {int(m)} 月"
    except (TypeError, ValueError):
        return key


def _window_start(months: int, today: date) -> date:
    """回看起点：今天所在月往前推 months 个月的 1 日（含当月，含首尾）。"""
    months = max(1, int(months))
    y, m = today.year, today.month
    total = (y * 12 + (m - 1)) - (months - 1)
    return date(total // 12, total % 12 + 1, 1)


def _source_items(memory_mgr: Any, highlights_mgr: Any,
                  anniversary_src: Any, weeks_mgr: Any,
                  start: date, end: date, today: date) -> List[dict]:
    """从四类只读源拉取窗口内节点（任何单源失败静默跳过，不拖垮整表）。"""
    items: List[dict] = []
    start_s, end_s = start.isoformat(), end.isoformat()

    # ① 高光（query_range(start,end,limit) 复用；limit 放大取全窗）
    if highlights_mgr is not None and hasattr(highlights_mgr, "query_range"):
        try:
            for it in (highlights_mgr.query_range(start_s, end_s, limit=999) or []):
                d = _parse_date(it.get("date"))
                text = str(it.get("text", "")).strip()
                if d is None or not text:
                    continue
                items.append({"kind": KIND_HIGHLIGHT, "date": d,
                              "text": text, "ref": str(it.get("id", ""))})
        except Exception:
            pass

    # ② 已完成话题（topics.archived：completed_at + subject）
    if memory_mgr is not None and hasattr(memory_mgr, "get_archived_topics"):
        try:
            for t in (memory_mgr.get_archived_topics() or []):
                if not isinstance(t, dict) or t.get("status") != "completed":
                    continue
                d = _parse_date(t.get("completed_at"))
                subject = str(t.get("subject", "")).strip()
                if d is None or not subject:
                    continue
                if start <= d <= end:
                    items.append({"kind": KIND_TOPIC, "date": d,
                                  "text": subject, "ref": subject})
        except Exception:
            pass

    # ③ 纪念日（周年语义 MM-DD：窗口内每个月各生成一次月节点）
    if anniversary_src is not None and hasattr(anniversary_src, "get_anniversaries"):
        try:
            ann = anniversary_src.get_anniversaries() or {}
        except Exception:
            ann = {}
        for kind in ("birthday", "first_meet"):
            mmdd = str(ann.get(kind) or "").strip()
            if len(mmdd) != 5 or mmdd[2] != "-":
                continue
            try:
                am, ad = int(mmdd[:2]), int(mmdd[3:])
            except ValueError:
                continue
            # 遍历窗口各月，命中该 MM-DD 即生成节点（跨年正确）
            cur = date(start.year, start.month, 1)
            while cur <= end:
                if cur.month == am:
                    try:
                        d = date(cur.year, am, ad)
                    except ValueError:
                        d = date(cur.year, am, 28)  # 2-29 等非法日 -> 月末语义
                    if start <= d <= min(end, today):
                        items.append({
                            "kind": KIND_ANNIVERSARY, "date": d,
                            "text": _ANNIVERSARY_LABELS.get(kind, "纪念日"),
                            "ref": kind,
                        })
                # 下一个月 1 日
                nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
                cur = nxt

    # ④ 周记存在性（点击跳往期回顾 Tab；只挂存在性节点，不展开内容）
    if weeks_mgr is not None and hasattr(weeks_mgr, "list_reviews"):
        try:
            for r in (weeks_mgr.list_reviews() or []):
                d = _parse_date(r.get("week_start"))
                if d is None or not (start <= d <= end):
                    continue
                items.append({"kind": KIND_WEEKLY, "date": d,
                              "text": "那一周的小结", "ref": str(r.get("week_start", ""))})
        except Exception:
            pass

    return items


def build_timeline(memory_mgr: Any, highlights_mgr: Any,
                   anniversary_src: Any = None, weeks_mgr: Any = None,
                   months: int = 6, today: Optional[date] = None) -> List[dict]:
    """聚合三源 + 周记存在性为按月分组的时间线（纯函数，只读，可独立单测）。

    返回 [{"month": "2026-09", "label": "2026 年 9 月", "items": [...]}]，
    月份倒序（最近在上）；月内节点按日期倒序、同日按类型稳定排序。
    未来日期的源数据（脏数据/时钟偏差）不呈现（不臆造未来经历）。
    """
    today = today or date.today()
    start = _window_start(months, today)
    end = today
    raw = _source_items(memory_mgr, highlights_mgr, anniversary_src,
                        weeks_mgr, start, end, today)
    groups: dict = {}
    for it in raw:
        key = _month_key(it["date"])
        groups.setdefault(key, []).append(it)
    out: List[dict] = []
    for key in sorted(groups.keys(), reverse=True):
        month_items = sorted(
            groups[key],
            key=lambda it: (it["date"], str(it.get("kind"))),
            reverse=True,
        )
        out.append({"month": key, "label": _month_label(key),
                    "items": month_items})
    return out
