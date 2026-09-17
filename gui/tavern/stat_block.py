# -*- coding: utf-8 -*-
"""gui/tavern/stat_block.py —— 结构化自然语言「状态块」解析器（纯逻辑、零 Qt）。

================================ 为什么是这个格式 ================================

酒馆的模型输出既要讲故事、又要推动数值。业界常见做法是让模型吐 JSON，但：

* **token 开销大** —— 每个键名都要引号、括号、逗号、转义；
* **脱格式代价高** —— 模型对"代码结构"的漏字符率明显高于自然语言，漏一个右花括号
  整个响应就废了；而自然语言漏一个词，句子照样读得懂。

本模块采用**结构化自然语言**，让输出长这样::

    【状态】苏小染|女|显|平静|好感度 1000/1000
    【变化】
    类型: 背包物品
    长夜酒 +1
    旧照片 -1
    类型: 属性
    photo_seen = true

两条解析路线并存，这正是该格式的弹性所在：

1. **固定位置**（``【状态】`` 行内以 ``|`` 分隔）—— 姓名 / 性别 / 显隐 / 心情 / 好感度
   这几个「每回合都要有」的常见字段位置固定，零歧义、零额外 token。
2. **万能键**（``【变化】`` 块内 ``键: 值`` / ``键 = 值`` / ``键 +N`` / ``键 -N``）——
   **代码不必预先认识这些键**：解析出来先存着，用到时再读。于是新增属性、道具、
   自定义数值都不需要改代码、也不必改 ``transforms.json``。

一句话：**常见项固定位置、特殊项万能键**；代码只硬匹配"一般的那部分"，
其余交给模型自由发挥，后端照单收下。

============================ 与现有机制的关系 ============================

``gui/tavern/content/lantern/transforms.json`` 走的是**代码预设**路线（``var_names`` +
每个 quick_action 显式声明 ``effects: [{field, op, value}]``）—— 只有代码允许的变更才可能发生。
本模块走**模型驱动**路线。两者互补而非替代：

* 预设项（剧情关键开关、章节节点）仍应由代码保证，**不要**开放给模型；
* 本模块负责"模型自由发挥的那部分"（道具增减、好感度漂移、临时标记）。

``RESERVED_KEYS`` 就是这条边界：列在其中的键**模型的写入会被拒绝并记入 warnings**，
避免模型越权改玩法关键量。

================================ 纪律 ================================

* **纯函数**：不修改入参、不做 IO、不 import Qt（与 ``gui/tavern`` 其余模块一致）；
* **永不抛异常**：任何畸形输入都退化成"能解析多少算多少"，问题进 ``warnings``；
* **未知行原样保留**（``unknown``）—— 宁可多存，也不静默丢弃模型输出。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "FIXED_FIELDS",
    "RESERVED_KEYS",
    "StatDelta",
    "parse_stat_block",
    "render_stat_block",
]

#: 固定位置字段的语义名 —— **顺序即位置**，与 prompt 侧的约定必须一致。
FIXED_FIELDS: Tuple[str, ...] = ("name", "gender", "visibility", "mood", "affinity")

#: 保留键：这些键不允许模型直接写（玩法关键量，只能由代码/预设变更）。
RESERVED_KEYS = frozenset({"turn", "scene_id", "node_id", "chapter"})

#: 段落起始标记（半角/全角方括号都认）。
_STATE_MARKERS = ("【状态】", "[状态]", "【当前状态】", "[当前状态]")
_CHANGE_MARKERS = ("【变化】", "[变化]", "【数值变化】", "[数值变化]", "【变更】", "[变更]")

#: 分组标题行：``类型: 背包物品`` —— 只用于归类，本身不产生变更。
_TYPE_RE = re.compile(r"^\s*(?:类型|分类|type)\s*[:：=]\s*(?P<kind>.+?)\s*$", re.IGNORECASE)

#: 增减行：``长夜酒 +1`` / ``好感度 -5`` / ``金币 +100``（含全角正负号与全角数字零容忍场景）。
_DELTA_RE = re.compile(
    r"^\s*(?P<key>[^+\-=:：\s]+)\s*(?P<sign>[+\-－＋])\s*(?P<num>\d+(?:\.\d+)?)\s*$")

#: 赋值行：``photo_seen = true`` / ``心情: 雀跃``（键里允许空格外的常见字符）。
_SET_RE = re.compile(r"^\s*(?P<key>[^:：=\s][^:：=]*?)\s*[:：=]\s*(?P<value>.*?)\s*$")

_FULLWIDTH = {"：": ":", "＝": "=", "｜": "|", "＋": "+", "－": "-", "　": " "}

#: 固定字段单元格可能自带的中文标签（剥掉后再按位置取用）。
_FIELD_LABELS = frozenset(FIXED_FIELDS) | {
    "姓名", "名字", "性别", "显隐", "心情", "好感度", "好感"}


def _normalize(line: str) -> str:
    """把常见的全角标点归一为半角（模型混用全半角是常态）。"""
    out = line
    for src, dst in _FULLWIDTH.items():
        out = out.replace(src, dst)
    return out


def _coerce(raw: str) -> Any:
    """把文本值收敛成 bool / int / float / str（**保持原样**优先，不猜）。"""
    low = raw.strip().lower()
    if low in ("true", "yes", "是", "真"):
        return True
    if low in ("false", "no", "否", "假"):
        return False
    if re.fullmatch(r"[+-]?\d+", low):
        return int(low)
    if re.fullmatch(r"[+-]?\d+\.\d+", low):
        return float(low)
    return raw.strip()


def _parse_affinity(raw: str) -> Optional[Dict[str, Any]]:
    """``好感度 1000/1000`` → ``{"value": 1000, "max": 1000, "raw": ...}``。"""
    m = re.match(r"^\s*(?P<cur>-?\d+)\s*/\s*(?P<mx>-?\d+)\s*$", raw)
    if not m:
        return None
    return {"value": int(m.group("cur")), "max": int(m.group("mx"))}


@dataclass
class StatDelta:
    """一次解析的结果。**全部为新增数据的描述，不含任何写入动作**（由调用方决定怎么落）。

    Attributes:
        fixed: 固定位置字段 → 值（``affinity`` 为 ``{"value","max"}`` 或字符串）。
        sets: 万能键赋值（``键 -> 值``），已做 bool/int/float 收敛。
        deltas: 万能键增减（``键 -> ±数值``），调用方按"存在则增减、不存在则新建"处理。
        items: 归在"背包物品"类下的增减（``类型: 背包物品`` 之后的增减行）。
        unknown: 未能识别但**原样保留**的行（含分组上下文），供人工/后续规则消化。
        warnings: 解析过程中的问题（保留键被拒、数值非法等），**永不为 None**。
        saw_state: 是否见过 ``【状态】`` 段（用于判断"模型压根没按格式输出"）。
        saw_change: 是否见过 ``【变化】`` 段。
    """

    fixed: Dict[str, Any] = field(default_factory=dict)
    sets: Dict[str, Any] = field(default_factory=dict)
    deltas: Dict[str, float] = field(default_factory=dict)
    items: Dict[str, float] = field(default_factory=dict)
    unknown: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    saw_state: bool = False
    saw_change: bool = False

    @property
    def is_empty(self) -> bool:
        """没有任何有效变更（调用方据此跳过落盘，避免无谓写）。"""
        return not (self.fixed or self.sets or self.deltas or self.items)


def parse_stat_block(text: Any) -> StatDelta:
    """解析模型输出里的状态块。**纯函数、永不抛**。

    容忍：全角标点、多余空行/空格、段标记缺失、值里含冒号、未知行。
    不做：写状态、校验语义合法性（那是调用方与 store 的事）。

    Args:
        text: 模型完整回复（只挑出状态块，其余叙述文本会被忽略）。

    Returns:
        :class:`StatDelta`；``text`` 非字符串或为空时返回空结果（``saw_*`` 全 False）。
    """
    result = StatDelta()
    if not isinstance(text, str) or not text.strip():
        return result

    section: Optional[str] = None          # None / "state" / "change"
    kind = ""                              # 当前分组（如"背包物品"）
    state_taken = False                    # 固定位置行只取第一行

    for raw_line in text.splitlines():
        line = _normalize(raw_line).strip()
        if not line:
            continue

        # ---- 段标记 ----
        marker = next((m for m in _STATE_MARKERS if line.startswith(m)), None)
        if marker is not None:
            section = "state"
            result.saw_state = True
            rest = line[len(marker):].strip()
            if rest:
                _parse_state_line(rest, result, state_taken)
                state_taken = True
            continue

        marker = next((m for m in _CHANGE_MARKERS if line.startswith(m)), None)
        if marker is not None:
            section = "change"
            result.saw_change = True
            kind = ""
            rest = line[len(marker):].strip()
            if rest:                        # 【变化】后面同一行接内容也认
                _parse_change_line(rest, result, kind)
            continue

        if section == "state":
            if not state_taken:
                _parse_state_line(line, result, state_taken=False)
                state_taken = True
            else:
                result.unknown.append(f"[state] {line}")
            continue

        if section == "change":
            kind = _parse_change_line(line, result, kind)
            continue

        # 段标记之外的行：不是本解析器的活儿，忽略（不记 warning，避免噪声）。
    return result


def _strip_label(cell: str) -> str:
    """剥掉单元格自带的标签：``心情: 平静`` / ``好感度 1000/1000`` → 只留值。

    模型经常把语义名一起写出来（冒号分隔或空格分隔两种都见过），按位置取用前先剥掉。
    """
    for sep in (":", " "):
        head, found, tail = cell.partition(sep)
        if found and head.strip() in _FIELD_LABELS:
            return tail.strip()
    return cell


def _parse_state_line(line: str, result: StatDelta, state_taken: bool) -> None:
    """解析 ``苏小染|女|显|平静|好感度 1000/1000``（位置即语义）。

    ``【状态】`` 段**可以出现多次，以最后一次为准** —— 模型有用「变化前 / 变化后」
    两段式输出的习惯，末段才是终态。
    """
    parts = [p.strip() for p in line.split("|")]
    for idx, sem in enumerate(FIXED_FIELDS):
        if idx >= len(parts) or not parts[idx]:
            continue
        raw = _strip_label(parts[idx])
        if sem == "affinity":
            parsed = _parse_affinity(raw)
            if parsed is not None:
                result.fixed[sem] = parsed
            else:
                # 允许省略 "/上限" 的写法
                num = re.search(r"-?\d+", raw)
                result.fixed[sem] = (
                    {"value": int(num.group()), "max": None} if num else raw)
            continue
        result.fixed[sem] = raw
    extra = parts[len(FIXED_FIELDS):]
    for p in extra:
        if p:
            result.unknown.append(f"[state-extra] {p}")


def _parse_change_line(line: str, result: StatDelta, kind: str) -> str:
    """解析 ``【变化】`` 块内的一行；返回（可能更新的）当前分组名。"""
    m = _TYPE_RE.match(line)
    if m is not None:
        return m.group("kind").strip()

    m = _DELTA_RE.match(line)
    if m is not None:
        key = m.group("key").strip()
        num = float(m.group("num"))
        if m.group("sign") in ("-", "－"):
            num = -num
        if key in RESERVED_KEYS:
            result.warnings.append(f"拒绝写入保留键: {key}")
            result.unknown.append(line)
            return kind
        if "背包" in kind or "物品" in kind or "道具" in kind:
            result.items[key] = result.items.get(key, 0.0) + num
        else:
            result.deltas[key] = result.deltas.get(key, 0.0) + num
        return kind

    m = _SET_RE.match(line)
    if m is not None:
        key = m.group("key").strip()
        if not key:
            result.unknown.append(line)
            return kind
        if key in RESERVED_KEYS:
            result.warnings.append(f"拒绝写入保留键: {key}")
            result.unknown.append(line)
            return kind
        value = _coerce(m.group("value"))
        if "背包" in kind or "物品" in kind or "道具" in kind:
            # 物品用赋值语义（"长夜酒: 2"）也归到 items，便于统一按数量处理
            result.items[key] = float(value) if isinstance(value, (int, float)) else 1.0
        else:
            result.sets[key] = value
        return kind

    result.unknown.append(line)
    return kind


def render_stat_block(
    fixed: Optional[Dict[str, Any]] = None,
    deltas: Optional[Dict[str, float]] = None,
    items: Optional[Dict[str, float]] = None,
) -> str:
    """按同一格式**渲染**一个状态块（供 prompt 侧给示例、或调试回放用）。"""
    lines: List[str] = []
    if fixed:
        cells = []
        for sem in FIXED_FIELDS:
            val = fixed.get(sem, "")
            if sem == "affinity" and isinstance(val, dict):
                mx = val.get("max")
                val = f"{val.get('value')}/{mx}" if mx else str(val.get("value"))
            cells.append(str(val or " "))
        lines.append("【状态】" + "|".join(cells))
    if deltas or items:
        lines.append("【变化】")
        for key, num in (deltas or {}).items():
            lines.append(f"{key} {num:+.0f}")
        if items:
            lines.append("类型: 背包物品")
            for key, num in items.items():
                lines.append(f"{key} {num:+.0f}")
    return "\n".join(lines)
