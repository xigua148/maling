"""gui/tavern/labels.py —— 机器名 → 人类可读中文（零 Qt，A2-5 补丁）。

面向 LLM 的文本（五段式 prompt + 前情提要 ``summary.text``）**不得**出现
``counter_photo`` / ``move_to`` / ``long_night`` / ``sit_down`` 这类下划线机器名 ——
说书人看到的应当是中文，而不是内容包里的内部 id。

本模块是「机器名 → 中文」的**唯一收口点**（``prompt.py`` / ``summarize.py`` 共用）：

    * **优先取内容包**：节点 ``id`` → 节点 ``title``（``chapters[].nodes[].title``）；
      以及内容包**可选**声明的扁平中文名表 ``content["labels"]``
      （``{"machine_name": "中文名", ...}``，覆盖场景 / 话题 / 物品 / var 值）。
    * **取不到 → 中性中文兜底**（按类别的泛化短语），**绝不回落机器名**。

硬约束：仅依赖标准库；**零 Qt**；纯函数；非法入参一律回落兜底（不抛）。
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = [
    "UNKNOWN_ACTION",
    "UNKNOWN_MODE",
    "UNKNOWN_REASON",
    "UNKNOWN_SCENE",
    "content_labels",
    "node_label",
    "scene_label",
    "transform_label",
    "mode_label",
    "reason_label",
    "labeled_values",
]


# ===========================================================================
# 中性中文兜底（**取不到中文名时的唯一去向**；绝不回落机器名）
# ===========================================================================

#: 未知变换 / 未知模式 / 未知未生效原因 / 未知地点的中性中文兜底。
UNKNOWN_ACTION: str = "做了个动作"
UNKNOWN_MODE: str = "照常进行"
UNKNOWN_REASON: str = "没能如愿"
UNKNOWN_SCENE: str = "这一处"


# ===========================================================================
# 变换 / 路由模式 / 未生效原因 —— 静态中文表（白名单固定，可穷举）
# ===========================================================================

#: 7 变换白名单（``model.TRANSFORM_WHITELIST``）→ 中文动词短语。
_TRANSFORM_LABELS: Dict[str, str] = {
    "move_to": "换了个地方",
    "take": "拿走一样东西",
    "give": "把东西交出去",
    "open": "打开一样东西",
    "ask_about": "问起一件事",
    "wait": "静静等着",
    "order": "点了一样东西",
}

#: 路由模式（``model.ROUTE_MODES``）→ 中文。
_MODE_LABELS: Dict[str, str] = {
    "verbatim": "照你说的做",
    "propose": "顺着你的意思",
    "narrate": "只是把话说下去",
}

#: 未生效原因码（``model.REASON_CODES``）→ 中文（前缀形如 ``xxx:yyy`` 取 ``xxx`` 段）。
_REASON_LABELS: Dict[str, str] = {
    "ok": "顺顺当当",
    "unknown_transform": "这一步没太听懂",
    "bad_args": "这一步说不太清",
    "precondition_failed": "眼下的情形还不允许",
    "forbidden": "这一步不能这么做",
    "invariant_violated": "这样做会前后打架",
    "llm_timeout": "她一时没接上话",
    "llm_bad_json": "她一时没接上话",
    "llm_disabled": "她一时没接上话",
}


# ===========================================================================
# 内容包中文名表（可选；内置包当前未声明 → 走中性兜底）
# ===========================================================================

def content_labels(content: Any) -> Dict[str, str]:
    """取内容包声明的扁平中文名表 ``content["labels"]``（非 dict / 非法项 → 丢弃）。"""
    if not isinstance(content, dict):
        return {}
    raw = content.get("labels")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and key and isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def node_label(content: Any, node_id: Any) -> str:
    """节点 ``id`` → 节点 ``title``（内容包 ``chapters[].nodes[]``）；取不到 → 空串。"""
    if not isinstance(content, dict) or not isinstance(node_id, str) or not node_id:
        return ""
    chapters = content.get("chapters")
    if not isinstance(chapters, list):
        return ""
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        nodes = chapter.get("nodes")
        if not isinstance(nodes, list):
            continue
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("id") == node_id:
                title = node.get("title")
                if isinstance(title, str) and title.strip():
                    return title.strip()
    return ""


def scene_label(content: Any, scene_id: Any) -> str:
    """地点 ``scene_id`` → 中文名。

    取内容包 ``labels`` 表；空 ``scene_id`` → 空串（调用方跳过该行）；
    有 ``scene_id`` 但查不到中文名 → :data:`UNKNOWN_SCENE`（中性中文，**绝不**回落机器名）。
    """
    if not isinstance(scene_id, str) or not scene_id:
        return ""
    return content_labels(content).get(scene_id) or UNKNOWN_SCENE


def transform_label(transform: Any) -> str:
    """变换机器名 → 中文动词短语；未知 → :data:`UNKNOWN_ACTION`。"""
    if isinstance(transform, str) and transform in _TRANSFORM_LABELS:
        return _TRANSFORM_LABELS[transform]
    return UNKNOWN_ACTION


def mode_label(mode: Any) -> str:
    """路由模式 → 中文；未知 → :data:`UNKNOWN_MODE`。"""
    if isinstance(mode, str) and mode in _MODE_LABELS:
        return _MODE_LABELS[mode]
    return UNKNOWN_MODE


def reason_label(reason: Any) -> str:
    """未生效原因码 → 中文；未知 → :data:`UNKNOWN_REASON`（前缀形如 ``a:b`` 取 ``a``）。"""
    if not isinstance(reason, str) or not reason:
        return UNKNOWN_REASON
    code = reason.split(":", 1)[0]
    return _REASON_LABELS.get(code, UNKNOWN_REASON)


def labeled_values(content: Any, values: Any, fallback: str) -> str:
    """把机器值列表翻成中文顿号串；**一项都取不到中文名 → ``fallback``（中性中文）**。

    只保留能在内容包 ``labels`` 表里查到中文名的项 —— 查不到的**丢弃**，
    绝不把机器名混进结果。
    """
    if not isinstance(values, (list, tuple)):
        return fallback
    table = content_labels(content)
    labels: List[str] = [table[v] for v in values if isinstance(v, str) and v in table]
    return "、".join(labels) if labels else fallback
