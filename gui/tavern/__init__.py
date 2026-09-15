"""gui/tavern/__init__.py —— 酒馆功能域包入口（V22-00 契约冻结）。

**零 Qt 硬要求**（design-v22 §1.4 校正① / D-V22-06）：
    本包**不得** import Qt 或任何 UI 模块。若把 Qt controller 放进 ``__init__.py``，
    则 ``import gui.tavern.model`` 会先执行本文件 → 触发 Qt 导入，与「纯逻辑零 Qt、
    可无显示环境单测」的核心承诺自相矛盾。
    **Qt controller（``TavernService``）另立 ``gui/tavern/service.py``（批 2）**，
    本文件只导出常量与纯逻辑符号（``from gui.tavern import ...`` 全程零 Qt）。

公开出口见 :data:`__all__`。全部符号由 :mod:`gui.tavern.model` /
:mod:`gui.tavern.errors` 转发（二者均仅依赖标准库）。
"""
from __future__ import annotations

from .errors import (
    TavernContentError,
    TavernDataError,
    TavernError,
    TavernForbiddenError,
    TavernInvariantError,
    TavernRouteError,
    TavernStoreError,
    TavernValidationError,
)
from .model import (
    # 版本与顶层结构
    SCHEMA_VERSION,
    TOP_LEVEL_KEYS,
    default_tavern,
    merge_defaults,
    migrate,
    # 设置
    SETTING_DEFAULTS,
    SETTING_KEYS,
    NARRATOR_LENGTHS,
    # 变换白名单
    TransformSpec,
    TRANSFORM_WHITELIST,
    TRANSFORM_SPECS,
    DEFAULT_VAR_NAMES,
    MAX_VARS,
    # 不变量
    INVARIANTS,
    INVARIANT_RULES,
    check_i1,
    check_i2,
    check_i3,
    # 硬禁区
    ForbiddenRule,
    FORBIDDEN_RULES,
    FORBIDDEN_RULE_DESC,
    FORBIDDEN_STRUCTURE_FIELDS,
    # 三级路由与留痕
    RouteMode,
    ROUTE_MODES,
    Resolution,
    RESOLUTION_REQUIRED_KEYS,
    TranscriptEntry,
    TRANSCRIPT_ENTRY_KEYS,
    INPUT_KINDS,
    TRANSCRIPT_ROLES,
    REASON_CODES,
    REASON_PREFIXES,
    # prompt 五段式
    PROMPT_SEGMENTS,
    PROMPT_SEGMENT_ROLES,
    # 世界书
    WorldbookEntry,
    WORLDBOOK_ENTRY_FIELDS,
    SELECTIVE_LOGIC_MODES,
    LORE_POSITIONS,
    CONSTANT_ENTRY_LIMIT,
    LORE_MAX_CONTENT_CHARS,
    default_worldbook_entry,
    # 局 / 人物 / 书槽
    PLAY_KEYS,
    PLAY_STATUSES,
    new_play,
    default_play,
    merge_play,
    CastMember,
    CAST_MEMBER_KEYS,
    default_cast_member,
    BookSlot,
    BOOK_SLOT_KEYS,
    default_book_slot,
)

__all__ = [
    # —— 版本与顶层结构 ——
    "SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "default_tavern",
    "merge_defaults",
    "migrate",
    # —— 设置 ——
    "SETTING_DEFAULTS",
    "SETTING_KEYS",
    "NARRATOR_LENGTHS",
    # —— 变换白名单 ——
    "TransformSpec",
    "TRANSFORM_WHITELIST",
    "TRANSFORM_SPECS",
    "DEFAULT_VAR_NAMES",
    "MAX_VARS",
    # —— 不变量 ——
    "INVARIANTS",
    "INVARIANT_RULES",
    "check_i1",
    "check_i2",
    "check_i3",
    # —— 硬禁区 ——
    "ForbiddenRule",
    "FORBIDDEN_RULES",
    "FORBIDDEN_RULE_DESC",
    "FORBIDDEN_STRUCTURE_FIELDS",
    # —— 三级路由与留痕 ——
    "RouteMode",
    "ROUTE_MODES",
    "Resolution",
    "RESOLUTION_REQUIRED_KEYS",
    "TranscriptEntry",
    "TRANSCRIPT_ENTRY_KEYS",
    "INPUT_KINDS",
    "TRANSCRIPT_ROLES",
    "REASON_CODES",
    "REASON_PREFIXES",
    # —— prompt 五段式 ——
    "PROMPT_SEGMENTS",
    "PROMPT_SEGMENT_ROLES",
    # —— 世界书 ——
    "WorldbookEntry",
    "WORLDBOOK_ENTRY_FIELDS",
    "SELECTIVE_LOGIC_MODES",
    "LORE_POSITIONS",
    "CONSTANT_ENTRY_LIMIT",
    "LORE_MAX_CONTENT_CHARS",
    "default_worldbook_entry",
    # —— 局 / 人物 / 书槽 ——
    "PLAY_KEYS",
    "PLAY_STATUSES",
    "new_play",
    "default_play",
    "merge_play",
    "CastMember",
    "CAST_MEMBER_KEYS",
    "default_cast_member",
    "BookSlot",
    "BOOK_SLOT_KEYS",
    "default_book_slot",
    # —— 异常层级 ——
    "TavernError",
    "TavernDataError",
    "TavernStoreError",
    "TavernValidationError",
    "TavernForbiddenError",
    "TavernInvariantError",
    "TavernRouteError",
    "TavernContentError",
]
