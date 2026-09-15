"""gui/widgets/tavern/__init__.py —— 酒馆功能域 · UI 控件包（域6，V22-07）。

本包按设计 §6.1「每 Tab 一个控件」组织；控件**只经 ``TavernService`` 的信号**更新，
不直接读写 store（§4.6）。

已交付（本包，V22-07 / 批 2）：
    * :class:`TavernHud`       —— 顶部状态条（章标题 + 场景 + 随身之物 + 状态点）；
    * :class:`TavernNarrative` —— 「今夜」叙述流（流式追加 + 贴底跟随 + 查询面重建）；
    * :class:`TavernInput`     —— 输入行 + 快捷动作排（自由输入 + 选项 + 中性提示）。

**文件域切分说明**：``tavern_worldbook`` / ``tavern_plays`` / ``tavern_trace`` 三个控件由其它工程师
并行交付，**不在本文件内 import**（避免与对方的落盘时序耦合）；页面按需
``from gui.widgets.tavern.tavern_worldbook import ...`` 直接引用对应子模块即可。

**文件命名纪律**（design §3.1 冻结）：本包全部控件模块一律以 ``tavern_`` 为前缀
（``tavern_narrative`` / ``tavern_input`` / ``tavern_hud`` / ``tavern_worldbook`` / ``tavern_plays`` /
``tavern_trace``）—— 避免与 ``gui/tavern/`` 下的同名短模块（``worldbook`` / ``plays`` …）
**同名不同包**导致 traceback / 日志 / grep 混淆。

接线契约（与页面拥有者约定）：
    * 各控件**自行订阅** TavernService 的**数据信号**（叙述 / 状态条 / 选项 / 忙态 / 降级）；
      页面**不要**再重复连接这些数据信号。
    * ``theme_engine.theme_changed`` 由**页面拥有者做总订阅**，槽内调用各控件的
      ``apply_theme()``；控件**不自行订阅** ``theme_changed``（避免重复订阅 → 多次重绘）。
"""
from __future__ import annotations

from .tavern_hud import TavernHud
from .tavern_input import TavernInput
from .tavern_narrative import TavernNarrative

__all__ = ["TavernHud", "TavernInput", "TavernNarrative"]
