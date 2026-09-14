"""quotations.py —— v1.7 F3 每日一句语录库 + ritual.json 按日限次存储（纯 stdlib）。

设计（docs/design-v17.md D-V17-02 / D-V17-10）：
  - 语录库 `gui/assets/quotations.json`：自创 ≥200 条（R-H 全自创零引用），
    主题池 morning/afternoon/night/all + 亲昵子池 intimate（阶段加权用）；
    加载守卫同 intent_words.json 模式：内置小池兜底，打包态走
    get_resource_path（gui.utils 延迟 import，frozen hiddenimports 已收录）；
  - `pick_quote(date_str, slot, weight)`：以 date+slot 的 **md5 稳定哈希**选择
    （内置 hash() 有 PYTHONHASHSEED 随机化，跨进程不稳定——禁用），当日确定、
    同日同槽恒同句（24h 不重复语义 = 当日一次一槽，由 RitualStore 按日限次保证）；
    按阶段加权：warm/intimate → 亲昵子池优先（确定性比例，非随机）；
  - `RitualStore`：`~/.maid_coder/ritual.json` 按日重置（date != today 即清），
    `{"date", "given": ["morning","afternoon","goodnight"], "quote_morning",
    "quote_afternoon"}`，原子写；早安/午后/晚安三通道共用（D-V17-02 三通道
    + D-V17-10 存储裁决）。
  - 红线：语录与仪式无「第 N 天」、无签到、无连续语义（R-A）；全自创（R-H）。
  - 顶层零第三方依赖、零 Qt；gui.utils 走函数内延迟 import。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 内置兜底小池（quotations.json 缺失/脏数据时兜底；同样全自创）
# ---------------------------------------------------------------------------
_FALLBACK_POOLS: Dict[str, List[str]] = {
    "morning": [
        "早安。今天的阳光不错，适合把想做的事轻轻推开一个头。",
        "新的一天，不必急，慢慢来也可以很稳。",
        "清晨的风比闹钟温柔，先伸个懒腰吧。",
        "早安，今天也请对自己温柔一点。",
        "窗外的天亮了，你的节奏由你定。",
        "把今天的第一个微笑留给镜子里的自己吧。",
    ],
    "afternoon": [
        "午后适合把肩膀放下来，深呼吸三次。",
        "走远了一点也没关系，停下来看看窗外再出发。",
        "下午茶时间到，记得补充一点水分。",
        "累了就趴一会儿，灵感喜欢找休息的人。",
        "午后的光斜斜的，正好发一小会儿呆。",
        "再撑一下下，傍晚的风已经在路上了。",
    ],
    "night": [
        "夜深了，把今天的事交给枕头保管吧。",
        "晚安，愿你的梦里没有未完成。",
        "星星都打烊了，你也早点休息呀。",
        "今天辛苦了，剩下的交给明天。",
        "夜色很轻，刚好盖住一整天的疲惫。",
        "放下屏幕，让眼睛也放个假吧。",
    ],
    "all": [
        "慢慢来，比较快。",
        "今天的状态就是今天最好的状态。",
        "小事累积起来，也会变成很了不起的事。",
        "允许自己有做不到的时候。",
        "把注意力放在能改变的部分就好。",
        "你已经比昨天多懂一点点了，这就够好。",
    ],
    "intimate": [
        "今天也想悄悄夸你：一直很努力的你，真的很棒。",
        "不管今天顺不顺利，我都在这儿。",
        "喝口热水，我在你身边陪你一会儿。",
        "你低头认真的时候，时间都变温柔了。",
        "想对你说的话很多，先从「辛苦了」开始。",
        "今晚的月亮很好看，分你一半。",
    ],
}

# 槽位 → 主池映射（早安/午后/晚安；goodnight 语录走 night 池）
_SLOT_POOLS = {
    "morning": "morning",
    "afternoon": "afternoon",
    "goodnight": "night",
    "night": "night",
}


def _default_ritual_filepath() -> Path:
    """ritual.json 落点：优先 gui.utils.get_user_data_dir，失败回落 ~/.maid_coder。"""
    try:
        from gui.utils import get_user_data_dir
        return get_user_data_dir() / "ritual.json"
    except Exception:
        return Path(os.path.expanduser("~/.maid_coder")) / "ritual.json"


def _quotations_asset_path() -> Optional[Path]:
    """语录库 JSON 路径：候选 = get_resource_path（打包态）→ 仓库相对路径，
    返回第一个**实际存在**的（get_resource_path 对缺失文件不抛错，需显式校验）。"""
    cands = []
    try:
        from gui.utils import get_resource_path
        cands.append(Path(get_resource_path(os.path.join("gui", "assets",
                                                         "quotations.json"))))
    except Exception:
        pass
    try:
        cands.append(Path(__file__).resolve().parent / "gui" / "assets"
                     / "quotations.json")
    except Exception:
        pass
    for p in cands:
        try:
            if p.exists():
                return p
        except OSError:
            continue
    return None


def _load_pools() -> Dict[str, List[str]]:
    """加载语录库（守卫：脏数据逐条清洗、非空字符串、缺池用兜底合并）。"""
    pools: Dict[str, List[str]] = {k: list(v) for k, v in _FALLBACK_POOLS.items()}
    path = _quotations_asset_path()
    if path is not None:
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    for key, items in raw.items():
                        if not isinstance(items, list):
                            continue
                        clean = [str(x).strip() for x in items
                                 if isinstance(x, str) and str(x).strip()]
                        seen = set(pools.get(key, []))
                        for q in clean:
                            if q not in seen:
                                seen.add(q)
                        pools[key] = clean + [q for q in pools.get(key, [])
                                              if q not in set(clean)]
        except (json.JSONDecodeError, IOError, OSError):
            pass
    return pools


def _stable_hash(text: str) -> int:
    """md5 稳定哈希（跨进程/跨日一致；内置 hash() 受 PYTHONHASHSEED 影响禁用）。"""
    return int(hashlib.md5(text.encode("utf-8")).hexdigest()[:12], 16)


def pick_quote(date_str: str, slot: str, weight: str = "plain",
               pools: Optional[Dict[str, List[str]]] = None) -> str:
    """按日期+槽位确定性抽取一句（当日确定、同日同槽恒同句）。

    - weight ∈ {"plain", "warm", "intimate"}：warm/intimate 亲昵子池优先
      （确定性比例：warm 命中 1/2、intimate 命中 2/3，由稳定哈希分桶）；
    - 候选 = 主池（slot 映射）+ all 池兜底；池空 → 兜底池；全空 → 固定文案。
    """
    pools = pools or _load_pools()
    key = _SLOT_POOLS.get(slot, "all")
    base = list(pools.get(key) or [])
    all_pool = list(pools.get("all") or [])
    intimate = list(pools.get("intimate") or [])
    h = _stable_hash(f"{date_str}|{slot}")
    # 阶段加权（确定性比例）：命中亲昵分支 → 候选 = 亲昵子池（独占，
    # 保证 warm=1/2、intimate=2/3 的可断言比例）；未命中 → 主池 + all 兜底。
    if weight == "intimate" and intimate and h % 3 != 0:
        cand = intimate
    elif weight == "warm" and intimate and h % 2 == 0:
        cand = intimate
    else:
        cand = base + [q for q in all_pool if q not in base]
    if not cand:
        cand = list(_FALLBACK_POOLS["all"])
    if not cand:
        return "今天也请好好照顾自己。"
    return cand[h % len(cand)]


class RitualStore:
    """ritual.json 按日限次存储（早安/午后/晚安三通道共用的记账本）。"""

    SLOTS = ("morning", "afternoon", "goodnight")

    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = Path(filepath) if filepath is not None else _default_ritual_filepath()
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if self.filepath.exists():
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return self._merge(data)
        except (json.JSONDecodeError, IOError, OSError):
            pass
        return self._merge({})

    @staticmethod
    def _merge(data: dict) -> dict:
        return {
            "date": str(data.get("date", "") or ""),
            "given": [str(s) for s in (data.get("given") or [])
                      if str(s) in RitualStore.SLOTS],
            "quote_morning": data.get("quote_morning"),
            "quote_afternoon": data.get("quote_afternoon"),
        }

    def _save(self) -> None:
        try:
            self.filepath.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        try:
            from utils import _atomic_write_json
            _atomic_write_json(self.filepath, self._data)
        except Exception:
            # 兜底原子写（.tmp + os.replace），与 utils 同语义
            tmp = str(self.filepath) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(self.filepath))

    def ensure_today(self, now: Optional[datetime] = None) -> None:
        """按日重置（date != today 即清空；跨日首次访问触发）。"""
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        if self._data.get("date") != today:
            self._data = self._merge({})
            self._data["date"] = today
            self._save()

    def given(self, slot: str, now: Optional[datetime] = None) -> bool:
        """当日该槽位是否已发过（自动先做跨日重置）。"""
        self.ensure_today(now)
        return slot in self._data.get("given", [])

    def mark_given(self, slot: str, quote: Optional[str] = None,
                   now: Optional[datetime] = None) -> None:
        """记账：槽位入 given；morning/afternoon 额外存语录内容。"""
        self.ensure_today(now)
        if slot in self.SLOTS and slot not in self._data.get("given", []):
            self._data.setdefault("given", []).append(slot)
        if quote and slot in ("morning", "afternoon"):
            self._data[f"quote_{slot}"] = str(quote)
        self._save()

    def quote_of(self, slot: str) -> Optional[str]:
        """当日已发的语录内容（无则 None）。"""
        return self._data.get(f"quote_{slot}")


def goodnight_due(now: datetime, store: RitualStore, enabled: bool = True) -> bool:
    """晚安仪式判定（纯函数，供托盘退出编舞调用）。

    条件：开关开 ∧ 深夜时段（23:00–5:00）∧ 当日未发过 goodnight。
    错过不补：当日 app 未在深夜退出即错过，无补发队列。
    """
    if not enabled:
        return False
    if not (now.hour >= 23 or now.hour < 5):
        return False
    return not store.given("goodnight", now)
