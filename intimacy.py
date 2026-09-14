"""亲密度与情绪温度系统 — 4级亲密度模型。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from utils import _atomic_write_json


# ---------------------------------------------------------------------------
# 亲密度等级定义
# ---------------------------------------------------------------------------
_INTIMACY_LEVELS = [
    {"level": 0, "name": "初识", "min_score": 0, "max_score": 9,
     "desc": "礼貌、正式，动作少", "action_limit": 0},
    {"level": 1, "name": "熟悉", "min_score": 10, "max_score": 49,
     "desc": "自然、偶尔关心，动作1处", "action_limit": 1},
    {"level": 2, "name": "亲近", "min_score": 50, "max_score": 149,
     "desc": "温柔、主动关心，动作1-2处", "action_limit": 2},
    {"level": 3, "name": "信赖", "min_score": 150, "max_score": 999999,
     "desc": "亲密、撒娇式关心，动作2处，语气生动", "action_limit": 2},
]

# 得分规则
_SCORE_RULES = {
    "dialogue": 1,        # 每次对话
    "save_session": 2,    # 保存会话
    "deep_feature": 3,    # 使用深度功能
    "gratitude": 2,       # 感谢/夸奖
    "consecutive_day": 5, # 连续3天使用（每日只计一次）
}

# 感谢/夸奖关键词
_GRATITUDE_KEYWORDS = [
    "谢谢", "感谢", "真好", "真棒", "太棒", "很棒", "厉害", "优秀", "完美",
    "不错", "辛苦了", "有你真好", "好棒", "真好用", "满意", "喜欢",
    "厉害呀", "真厉害", "漂亮", "可以啊", "靠谱", "贴心",
]

# 否定前缀：命中则忽略紧跟的感谢词（避免「不喜欢/不太满意」被误判为夸奖）
_NEGATION_PREFIXES = ["不", "别", "没", "无", "非", "不太", "并不", "从不", "一点都不", "一点也不", "不怎么"]

# ---------------------------------------------------------------------------
# v1.7(F5/D-V17-04): 关系阶段特权表 —— 按 level 键；**无"闲聊话术变体"键**
#（Q-C9 裁决：砍掉该特权，idle_hello 文案池零改动，A9 零回归面）。
# 全表无数值语义（R-A）：address_style=称呼；goodnight_variant=晚安撒娇变体
#（F3 消费）；diary_tone=日记口吻更亲密（F7 消费）；quote_pool_weight=语录池
# 加权档位（F3 消费："plain"=基础池 / "warm"=亲昵子池优先 / "intimate"=亲昵子池
# 优先且比重更高）。
# ---------------------------------------------------------------------------
_STAGE_PRIVILEGES = {
    0: {"address_style": "您", "goodnight_variant": False,
        "diary_tone": False, "quote_pool_weight": "plain"},
    1: {"address_style": "你", "goodnight_variant": False,
        "diary_tone": False, "quote_pool_weight": "warm"},
    2: {"address_style": "你", "goodnight_variant": True,
        "diary_tone": False, "quote_pool_weight": "warm"},
    3: {"address_style": "你", "goodnight_variant": True,
        "diary_tone": True, "quote_pool_weight": "intimate"},
}



# ---------------------------------------------------------------------------
def _intimacy_dir() -> str:
    d = os.path.expanduser("~/.maid_coder")
    os.makedirs(d, exist_ok=True)
    return d


def _intimacy_path() -> str:
    return os.path.join(_intimacy_dir(), "intimacy.json")


# ---------------------------------------------------------------------------
class IntimacyTracker:
    """亲密度追踪器：记录分数、等级、连续使用天数。"""

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath or _intimacy_path()
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    # v1.7(F5): notified_stage 兜底默认 -1（旧数据零迁移，R-D）
                    data.setdefault("notified_stage", -1)
                    return data
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "score": 0,
            "level": 0,
            "total_dialogues": 0,
            "total_saves": 0,
            "last_interaction_date": "",
            "consecutive_days": 0,
            "daily_score_today": 0,
            "history": [],
            # v1.7(F5/D-V17-04): 已播报到的阶段（-1 = 从未播报）
            "notified_stage": -1,
        }

    def _save(self) -> None:
        _atomic_write_json(self.filepath, self._data)

    def _get_level_info(self, score: int) -> dict:
        for lvl in _INTIMACY_LEVELS:
            if lvl["min_score"] <= score <= lvl["max_score"]:
                return lvl
        return _INTIMACY_LEVELS[0]

    def _check_level_up(self, old_score: int, new_score: int) -> Optional[str]:
        old_lvl = self._get_level_info(old_score)
        new_lvl = self._get_level_info(new_score)
        if new_lvl["level"] > old_lvl["level"]:
            # §3.9 红线：升级反馈只用关系称谓文本，不暴露等级/数值（防养成焦虑）
            return (
                f"女仆感觉和主人更亲近了呢~ "
                f"现在我们是「{new_lvl['name']}」的关系啦 💕"
            )
        return None

    # -- 分数操作 --

    def add_interaction(self, interaction_type: str = "dialogue") -> Optional[str]:
        """记录一次互动并可能加分。返回升级提示（如果有）。"""
        old_score = self._data["score"]
        today = datetime.now().strftime("%Y-%m-%d")
        last_date = self._data.get("last_interaction_date", "")

        # 每日上限：最多 +10 分/天
        if last_date != today:
            self._data["daily_score_today"] = 0
            self._data["last_interaction_date"] = today
            # 连续天数
            if last_date:
                try:
                    last_dt = datetime.strptime(last_date, "%Y-%m-%d")
                    if (datetime.now() - last_dt).days == 1:
                        self._data["consecutive_days"] = self._data.get("consecutive_days", 0) + 1
                    elif (datetime.now() - last_dt).days > 1:
                        self._data["consecutive_days"] = 1
                except ValueError:
                    self._data["consecutive_days"] = 1
            else:
                self._data["consecutive_days"] = 1

        # 加分
        points = _SCORE_RULES.get(interaction_type, 1)
        if self._data["daily_score_today"] + points > 10:
            points = max(0, 10 - self._data["daily_score_today"])

        if points > 0:
            self._data["score"] += points
            self._data["daily_score_today"] += points

        # 统计
        if interaction_type == "dialogue":
            self._data["total_dialogues"] = self._data.get("total_dialogues", 0) + 1
        elif interaction_type == "save_session":
            self._data["total_saves"] = self._data.get("total_saves", 0) + 1

        # 连续3天奖励
        if self._data.get("consecutive_days", 0) >= 3 and interaction_type == "dialogue":
            # 连续3天奖励每天只加一次
            if not self._data.get("consecutive_bonus_today", "") == today:
                if self._data["daily_score_today"] + 5 <= 10:
                    self._data["score"] += 5
                    self._data["daily_score_today"] += 5
                self._data["consecutive_bonus_today"] = today

        self._data["level"] = self._get_level_info(self._data["score"])["level"]

        # 记录历史
        self._data.setdefault("history", []).append({
            "type": interaction_type,
            "points": points,
            "date": datetime.now().isoformat(),
            "score_after": self._data["score"],
        })
        # 限制历史长度
        if len(self._data["history"]) > 100:
            self._data["history"] = self._data["history"][-100:]

        self._save()
        return self._check_level_up(old_score, self._data["score"])

    def detect_gratitude(self, user_msg: str) -> bool:
        """检测用户消息中是否包含感谢/夸奖（排除否定语境，如「不喜欢」）。"""
        text = (user_msg or "").strip()
        if not text:
            return False
        # 纯负面/抱怨句（含否定词且不含任何可能的夸奖意图）直接判负
        pure_negative = re.fullmatch(r"[^，。！？\n]*?(?:不|没|别|太)[^，。！？\n]*?(?:好|行|满意|喜欢|棒|对|靠谱|贴心)[^，。！？\n]*", text)
        if pure_negative and not any(kw in text for kw in ("但", "不过", "但是", "可是", "只是", "然而")):
            return False
        for kw in _GRATITUDE_KEYWORDS:
            idx = text.find(kw)
            while idx != -1:
                # 检查关键词前是否有否定前缀
                neg_hit = False
                for neg in _NEGATION_PREFIXES:
                    if text[max(0, idx - len(neg)):idx] == neg:
                        neg_hit = True
                        break
                if not neg_hit:
                    return True
                idx = text.find(kw, idx + 1)
        return False

    def add_gratitude(self) -> Optional[str]:
        """记录一次感谢/夸奖。"""
        return self.add_interaction("gratitude")

    def add_deep_feature(self) -> Optional[str]:
        """记录一次深度功能使用。"""
        return self.add_interaction("deep_feature")

    def add_save(self) -> Optional[str]:
        """记录一次保存会话。"""
        return self.add_interaction("save_session")

    # -- 查询 --

    @property
    def score(self) -> int:
        return self._data["score"]

    @property
    def level(self) -> int:
        return self._data["level"]

    def level_name(self) -> str:
        return self._get_level_info(self._data["score"])["name"]

    def level_desc(self) -> str:
        return self._get_level_info(self._data["score"])["desc"]

    def action_limit(self) -> int:
        return self._get_level_info(self._data["score"])["action_limit"]

    # -- v1.7(F5/D-V17-04): 阶段特权 / 播报记账 --

    def stage_privileges(self, level: Optional[int] = None) -> dict:
        """当前（或指定）阶段的特权快照（副本；无"闲聊话术变体"键，Q-C9）。"""
        lvl = self._get_level_info(self._data["score"])["level"] if level is None else level
        return dict(_STAGE_PRIVILEGES.get(int(lvl), _STAGE_PRIVILEGES[0]))

    @property
    def notified_stage(self) -> int:
        """已播报到的阶段（-1 = 从未播报；恰一次播报记账，重启不重播）。"""
        try:
            return int(self._data.get("notified_stage", -1))
        except (TypeError, ValueError):
            return -1

    def mark_stage_notified(self, level: int) -> None:
        """阶段播报记账并落盘（写盘失败由调用方降级，见 D-V17-04 风险点）。"""
        self._data["notified_stage"] = int(level)
        self._save()

    def stage_announcement(self, level: Optional[int] = None) -> str:
        """阶段升级播报句（无数值位——R-A 硬线，模板定稿审查）。"""
        lvl = self._get_level_info(self._data["score"])["level"] if level is None else int(level)
        name = self.level_name()
        for l in _INTIMACY_LEVELS:
            if l["level"] == lvl:
                name = l["name"]
                break
        return f"主人，码铃感觉我们更亲近了——现在是「{name}」的关系啦 💕"

    def build_intimacy_prompt(self) -> str:
        """生成注入系统提示词的关系阶段段（v1.7 F5 阶段化扩展，签名不变）。

        阶段化注入 = 称呼 + 语气 + 特权说明；无 Lv/分数（R-A，连 system 侧
        也不暴露数值语义）；升级/切角色后由既有 _update_system 链当轮生效。
        """
        lvl = self._get_level_info(self._data["score"])
        priv = self.stage_privileges(lvl["level"])
        if priv["address_style"] == "您":
            address = "称呼主人时用「您」，保持礼貌距离。"
        else:
            address = "称呼主人时用「你」，自然亲近。"
        if lvl["level"] <= 0:
            tone = "保持礼貌距离，动作描写每轮最多0处。"
        elif lvl["level"] == 1:
            tone = "自然亲切，动作描写每轮最多1处。"
        elif lvl["level"] == 2:
            tone = "温柔主动，可适当关心主人的状态，动作描写每轮1-2处。"
        else:
            tone = "亲密陪伴，可以撒娇式表达关心，动作描写每轮最多2处，语气更生动活泼。"
        extra = ""
        if priv["goodnight_variant"]:
            extra = "夜深道别时可以更软更黏一点。"
        return f"【关系阶段】{lvl['name']} — {address}{tone}{extra}"

    def report(self) -> str:
        """返回亲密度报告（供 /mood 命令使用）。"""
        lvl = self._get_level_info(self._data["score"])
        lines = [
            "💕 亲密度报告",
            f"  当前等级: {lvl['name']} (Lv.{lvl['level']})",
            f"  当前分数: {self._data['score']} / 下一级需 {lvl['max_score'] + 1}",
            f"  总对话数: {self._data.get('total_dialogues', 0)}",
            f"  总会话保存: {self._data.get('total_saves', 0)}",
            f"  连续使用天数: {self._data.get('consecutive_days', 0)}",
            f"  今日得分: {self._data.get('daily_score_today', 0)} / 10",
            "",
            "  等级说明:",
        ]
        for l in _INTIMACY_LEVELS:
            marker = "▶" if l["level"] == lvl["level"] else " "
            lines.append(f"    {marker} Lv.{l['level']} {l['name']}: {l['min_score']}-{l['max_score']}分 — {l['desc']}")
        return "\n".join(lines)

    # -- 序列化 --

    def to_dict(self) -> dict:
        return dict(self._data)

    def from_dict(self, data: dict) -> None:
        defaults = {
            "score": 0,
            "level": 0,
            "total_dialogues": 0,
            "total_saves": 0,
            "last_interaction_date": "",
            "consecutive_days": 0,
            "daily_score_today": 0,
            "history": [],
            "notified_stage": -1,
        }
        self._data = {**defaults, **data}
        self._save()
