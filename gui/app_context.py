"""AppContext —— 集中式状态容器，所有页面通过同一引用访问共享状态。"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AppContext:
    """应用级上下文：持有所有可跨页面访问的业务对象。"""

    # CLI 核心对象（直接复用）
    cfg: Any = None
    api: Any = None
    session: Any = None
    router: Any = None
    collaborator: Any = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("maid_coder.gui"))

    # v10.14: GUI 好感度追踪器（与 CLI 持久化到同一份 intimacy.json）
    intimacy: Any = None

    # GUI 层新增对象
    config: Any = None              # GuiConfig
    theme_engine: Any = None        # ThemeEngine
    page_manager: Any = None        # PageManager
    chat_service: Any = None        # ChatService
    gui_session: Any = None         # GuiChatSession
    session_manager: Any = None     # SessionManager

    # 运行时状态
    project_dir: Optional[str] = None
    current_project_root: Optional[str] = None
    current_file_path: Optional[str] = None
    current_role: str = "default"

    # v2.2.5: 诊断包（gui/diagnostics.py）的**运行时信息段**：段名 -> 取文本的可调用。
    # 页面在这里注册"只有它自己拿得到"的信息 —— 典型是内置酒馆的服务端输出：
    # tavern_backend 以 DEBUG 级记录 node 的 stdout，而文件 handler 是 INFO 级，
    # 于是打包态**根本落不了盘**（v2.2.3 排障时就因此少了一条关键线索）。
    # 诊断包按段名各写一个文件，单个段取失败只降级该段、不影响整包。
    diagnostics_providers: dict = field(default_factory=dict)
