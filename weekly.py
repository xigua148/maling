"""weekly.py —— v1.6 P1-3 每周共同回顾存储与生成（纯 stdlib、本地、原子写）。

设计（docs/design-v16.md §2.10 / D-V16-10，Q-B4）：
  - 数据文件 `~/.maid_coder/weekly.json`：
    {"schema_version":1, "reviews":[{"week_start":"YYYY-MM-DD"(周一),
      "generated_at":ISO, "skeleton":{...}, "polished":null}]}，
    52 周滚动淘汰（写入时裁剪）。
  - 生成判定 maybe_generate()：now 为周日且 18:00–21:00（Q-B4）∧ 本周
    （week_start 键）无已生成记录 → 生成；**错过窗口不补**（无补发队列）；
    同周幂等（重开 app 不重复生成）。
  - 内容 = 规则骨架，零 LLM 默认；**档位词不报数字**（R-A：无「第 N 周」、
    无连续回顾、无对比图表、skeleton 无计数字段）。
  - 高光精选直接引用用户自己收藏的原文（R-I 安全面），≤3 条。
  - LLM 润色口（polished 字段）本期仅预留，默认关（GuiConfig.weekly_llm_polish）。
  - 红线：无系统通知无推送（R-C）；数据纯本地（R-I）。
  - 顶层零第三方依赖；get_user_data_dir 走函数内延迟 import（frozen
    hiddenimports 已收录 weekly）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("maid_coder.weekly")

_WEEKLY_LIMIT = 52          # 52 周滚动淘汰
_WINDOW_START = time(18, 0)  # Q-B4：周日 18:00–21:00
_WINDOW_END = time(21, 0)

# 消息量档位词（R-A：不报数字；全空=安静的一周，有活动按密度分三档）
PACE_QUIET = "安静的一周"
PACE_TIERS = {1: "清闲的一周", 3: "张弛有度的一周", 6: "忙碌的一周"}


def _default_filepath() -> Path:
    """用户数据目录：优先 gui.utils.get_user_data_dir，失败回落 ~/.maid_coder。"""
    try:
        from gui.utils import get_user_data_dir
        return get_user_data_dir() / "weekly.json"
    except Exception:
        return Path(os.path.expanduser("~/.maid_coder")) / "weekly.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """原子写 JSON（.tmp + os.replace），纯 stdlib。"""
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(path))


def week_start_of(now: datetime) -> str:
    """now 所在周的周一日期（YYYY-MM-DD）——幂等键，本地时区口径。"""
    d = now.date() - timedelta(days=now.weekday())
    return d.isoformat()


def _in_window(now: datetime) -> bool:
    """周日 18:00–21:00（含头不含尾）；错过即错过，无补发。"""
    return now.weekday() == 6 and _WINDOW_START <= now.time() < _WINDOW_END


def _parse_dt(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _in_week(value: Any, start: date, end: date) -> bool:
    """ISO 时间/日期落在本周 [start, end]（按日期口径）。"""
    dt = _parse_dt(value)
    if dt is None:
        return False
    return start <= dt.date() <= end


def _pace_word(activity: int) -> str:
    """活动度 → 档位词（0=安静；1-2 清闲；3-5 张弛有度；≥6 忙碌）。"""
    if activity <= 0:
        return PACE_QUIET
    if activity < 3:
        return PACE_TIERS[1]
    if activity < 6:
        return PACE_TIERS[3]
    return PACE_TIERS[6]


def _mood_note(emotions: List[dict]) -> str:
    """情绪概览档位描述（无计数，正向措辞）。"""
    if not emotions:
        return "这一周心情都挺平稳，平静也是好日子。"
    lows = {"tired", "lonely", "anxious", "concerned"}
    has_low = any(str(e.get("emotion", "")) in lows for e in emotions)
    has_up = any(str(e.get("emotion", "")) == "happy" for e in emotions)
    if has_up and has_low:
        return "有开心的日子，也有辛苦的日子，都是真实的一周。"
    if has_low:
        return "这周里有几天有点辛苦，码铃都轻轻记着呢。"
    return "大部分时间都很有干劲，看着就很安心。"


def _topic_lists(memory_mgr: Any, start: date, end: date) -> tuple:
    """本周新增/完成话题（纯读 memory 既有结构，不写任何字段）。"""
    new_topics: List[str] = []
    done_topics: List[str] = []
    if memory_mgr is None:
        return new_topics, done_topics
    try:
        topics = (list(memory_mgr.get_active_topics() or [])
                  + list(memory_mgr.get_archived_topics() or []))
    except Exception as exc:  # noqa: BLE001
        _logger.debug("weekly 读取话题失败（忽略）: %s", exc)
        return new_topics, done_topics
    seen = set()
    for t in topics:
        if not isinstance(t, dict):
            continue
        subject = str(t.get("subject", "")).strip()
        if not subject or subject in seen:
            continue
        seen.add(subject)
        mentioned = t.get("last_mentioned", "")
        completed = t.get("completed_at", "")
        if completed and _in_week(completed, start, end):
            done_topics.append(subject)
        elif mentioned and _in_week(mentioned, start, end):
            new_topics.append(subject)
    return new_topics, done_topics


class WeeklyReviewManager:
    """每周共同回顾：本地 json 读写、52 周滚动淘汰、周日窗口判定 + 规则骨架生成。"""

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = Path(filepath) if filepath is not None else _default_filepath()
        self._data = self._load()

    # -- 存取 --
    def _load(self) -> dict:
        try:
            if self.filepath.exists():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return self._merge_defaults(data)
        except (json.JSONDecodeError, IOError, OSError) as exc:
            _logger.warning("weekly.json 读取失败，重建默认: %s", exc)
        return self._default_data()

    @staticmethod
    def _default_data() -> dict:
        now = datetime.now().isoformat()
        return {"schema_version": 1,
                "meta": {"created_at": now, "updated_at": now},
                "reviews": []}

    def _merge_defaults(self, data: dict) -> dict:
        d = self._default_data()
        if not isinstance(data, dict):
            return d
        d["schema_version"] = int(data.get("schema_version", 1) or 1)
        if isinstance(data.get("meta"), dict):
            d["meta"].update(data["meta"])
        if isinstance(data.get("reviews"), list):
            d["reviews"] = [r for r in data["reviews"] if isinstance(r, dict)]
        self._prune(d)
        return d

    @staticmethod
    def _prune(d: dict) -> None:
        """52 周滚动淘汰（按 week_start 倒序保留最新 52 条）。"""
        reviews = d.get("reviews")
        if not isinstance(reviews, list):
            return
        reviews.sort(key=lambda r: str(r.get("week_start", "")), reverse=True)
        if len(reviews) > _WEEKLY_LIMIT:
            del reviews[_WEEKLY_LIMIT:]

    def _save(self) -> None:
        self._prune(self._data)
        self._data["meta"]["updated_at"] = datetime.now().isoformat()
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _atomic_write_json(self.filepath, self._data)

    def to_dict(self) -> dict:
        return self._data

    def list_reviews(self) -> List[dict]:
        """全部回顾（week_start 倒序，往期翻阅用）。"""
        reviews = [dict(r) for r in self._data.get("reviews", [])]
        reviews.sort(key=lambda r: str(r.get("week_start", "")), reverse=True)
        return reviews

    def get_by_week(self, week_start: str) -> Optional[dict]:
        """按周一键取单条回顾（page_home 本周卡片用）。"""
        for r in self._data.get("reviews", []):
            if str(r.get("week_start", "")) == str(week_start):
                return dict(r)
        return None

    # -- 生成 --
    def maybe_generate(self, now: datetime, highlights: Any = None,
                       memory_mgr: Any = None, companion: Any = None) -> Optional[dict]:
        """周日 18:00–21:00 窗口内首次调用 → 生成规则骨架并落盘；否则 None。

        - 窗口外恒 None（**错过不补**，无补发队列）；
        - 本周 week_start 键已有记录 → None（同周幂等）；
        - 生成内容零 LLM（polished 润色口本期不接）；
        - 任何数据源缺失/异常都降级为空档，绝不抛错阻断启动。
        """
        if not _in_window(now):
            return None
        ws = week_start_of(now)
        if self.get_by_week(ws) is not None:
            return None
        skeleton = self.build_skeleton(now, highlights, memory_mgr, companion)
        review = {"week_start": ws, "generated_at": now.isoformat(),
                  "skeleton": skeleton, "polished": None}
        self._data.setdefault("reviews", []).append(review)
        self._save()
        return dict(review)

    def build_skeleton(self, now: datetime, highlights: Any = None,
                       memory_mgr: Any = None, companion: Any = None) -> dict:
        """规则骨架（零 LLM、零数字、零计数字段——R-A）。"""
        ws_date = (now.date() - timedelta(days=now.weekday()))
        we_date = ws_date + timedelta(days=6)

        # ① 高光精选 ≤3（用户自己收藏的原文，R-I 安全面；只留文本——日期含数字，
        #    为满足 R-A「骨架零数字」剔除）
        picks: List[dict] = []
        if highlights is not None:
            try:
                raw = highlights.query_range(ws_date.isoformat(), we_date.isoformat(),
                                             limit=3)
                for it in raw or []:
                    text = str(it.get("text", "")).strip()
                    if text:
                        picks.append({"text": text})
            except Exception as exc:  # noqa: BLE001
                _logger.debug("weekly 读取高光失败（忽略）: %s", exc)

        # ② 话题与情绪
        new_topics, done_topics = _topic_lists(memory_mgr, ws_date, we_date)
        emotions: List[dict] = []
        if memory_mgr is not None and hasattr(memory_mgr, "get_emotions_history"):
            try:
                emotions = [e for e in (memory_mgr.get_emotions_history() or [])
                            if isinstance(e, dict) and _in_week(e.get("time", ""),
                                                                ws_date, we_date)]
            except Exception as exc:  # noqa: BLE001
                _logger.debug("weekly 读取情绪失败（忽略）: %s", exc)

        # ③ 消息量档位（有任一活动记录=有来有往，全空=安静的一周）
        activity = len(picks) + len(new_topics) + len(done_topics) + len(emotions)
        pace = _pace_word(activity)

        # ④ 相伴阶段（称谓档位词，不报天数——R-A）
        stage = ""
        if companion is not None:
            try:
                stage = str(companion.relation_stage_name() or "").strip()
            except Exception as exc:  # noqa: BLE001
                _logger.debug("weekly 读取相伴阶段失败（忽略）: %s", exc)

        return {
            "pace": pace,
            "new_topics": new_topics[:5],
            "done_topics": done_topics[:5],
            "highlights": picks,
            "mood_note": _mood_note(emotions),
            "relation_stage": stage,
        }
