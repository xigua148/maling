"""gui/tavern/errors.py —— 酒馆功能域异常层级（V22-00 契约冻结，纯逻辑零 Qt）。

设计依据：docs/design-v22.md §3.1 / §4.3（`class TavernError(Exception)`）、
§4.4（坏档恢复矩阵「绝不抛」）、对齐 gui/role_card.py::CardError 的既有写法
（**含中文消息、可直接呈现给用户**）。

约束（硬）：本模块仅依赖标准库；**不得在 import 期触发任何 Qt 导入** ——
`import gui.tavern.errors` 必须在无 PySide6 的环境下成功（design-v22 D-V22-06）。

层级：

    TavernError                  # 域根异常（中文消息 + 可选机读 reason）
    ├── TavernDataError          # 数据层：坏档 / schema / 迁移
    │   └── TavernStoreError     # 落盘 IO（原子写 / 快照轮转）
    ├── TavernValidationError    # 本地校验器：未知变换 / args 非法 / pre 不满足
    │   ├── TavernForbiddenError     # 6 条硬禁区命中
    │   └── TavernInvariantError     # I1/I2/I3 被违反
    ├── TavernRouteError         # 三级路由层
    └── TavernContentError       # 内容包加载（世界书 / 章节 / 变换声明）
"""
from __future__ import annotations

from typing import Optional

__all__ = [
    "TavernError",
    "TavernDataError",
    "TavernStoreError",
    "TavernValidationError",
    "TavernForbiddenError",
    "TavernInvariantError",
    "TavernRouteError",
    "TavernContentError",
]


class TavernError(Exception):
    """酒馆域根异常。

    Attributes:
        message: 中文错误消息（可直接呈现给用户，与 ``CardError`` 同口径）。
        reason: 机读短码（如 ``precondition_failed:item_not_in_scene``），
            供「记录」Tab 归因与调词表；无则空串。**不参与 UI 文案**。
    """

    def __init__(self, message: str = "酒馆出错了", *, reason: str = "") -> None:
        super().__init__(message)
        self.message: str = message
        self.reason: str = reason

    def __str__(self) -> str:  # pragma: no cover - 直通，仅为可读性
        return self.message


class TavernDataError(TavernError):
    """数据层异常：坏档 / schema 版本异常 / 迁移失败。

    注意：``TavernStore.load`` 依 design-v22 §4.4「坏档恢复矩阵 L0–L6」**绝不抛**；
    本异常仅用于 ``save`` 等「无法安全继续」的写路径，或被测代码显式升级场景。
    """


class TavernStoreError(TavernDataError):
    """存档 IO 异常：原子写失败 / 付目录创建失败 / 快照轮转失败。"""


class TavernValidationError(TavernError):
    """本地校验器异常：未知变换 / args 结构非法 / 前置条件不满足。

    对应 design-v22 §4.2 校验器步骤 1–3 的 reject（``unknown_transform`` /
    ``bad_args`` / ``precondition_failed:<reason>``）。
    """


class TavernForbiddenError(TavernValidationError):
    """硬禁区命中（design-v22 §4.2「硬禁区」6 条，校验器最高优先级）。"""


class TavernInvariantError(TavernValidationError):
    """不变量被违反（design-v22 §4.2 的 I1 集合互斥 / I2 引用有效 / I3 只增不改）。"""


class TavernRouteError(TavernError):
    """三级路由层异常。

    注意：路由的降级铁律（design-v22 D-V22-12）要求 **LLM 关闭 / 超时 / 畸形
    JSON / 异常一律降级为 ``narrate`` 且不抛**；本异常仅保留给「路由入参本身
    不可用」等理论场景（如 state 非 dict），默认路径不应触发。
    """


class TavernContentError(TavernError):
    """内容包加载异常：世界书 / 章节 / 变换声明结构非法。"""

    def __init__(self, message: str = "内容包不可用", *, reason: str = "", source: Optional[str] = None) -> None:
        super().__init__(message, reason=reason)
        self.source: str = source or ""
