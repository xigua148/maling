"""CommandRouter — 命令路由器：注册表 + 分发器 + 帮助生成器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
from collections import defaultdict


@dataclass
class CommandInfo:
    """命令元数据，注册时自动收集。"""
    name: str                           # 命令名（不含斜杠）
    handler: Callable                   # 处理函数
    description: str = ""               # 一句话描述
    usage: str = ""                     # 用法示例
    category: str = "其他"              # 分类（用于帮助分组）
    aliases: List[str] = field(default_factory=list)  # 别名


class CommandContext:
    """命令执行上下文，替代当前闭包变量传递。"""

    def __init__(
        self,
        session: Any,
        cmd: str,
        args: List[str],
        raw_input: str,
        cfg: Any,
        api: Any,
        collaborator: Any,
    ):
        self.session = session
        self.cmd = cmd
        self.args = args
        self.raw_input = raw_input
        self.cfg = cfg
        self.api = api
        self.collaborator = collaborator

    # 便捷属性
    @property
    def user_input(self) -> str:
        """原始用户输入（用于直通 AI 模式）。"""
        return self.raw_input


# Handler 签名类型
CommandHandler = Callable[[CommandContext], Optional[bool]]
# 返回 None/True: 继续 REPL; 返回 False: 退出 REPL


class CommandRouter:
    """命令路由器：注册表 + 分发器 + 帮助生成器。"""

    def __init__(self):
        self._registry: Dict[str, CommandInfo] = {}          # name -> info
        self._aliases: Dict[str, str] = {}                   # alias -> canonical name
        self._categories: Dict[str, List[CommandInfo]] = defaultdict(list)
        self._fallbacks: List[CommandHandler] = []           # fallback 链

    # ── 注册 API ──

    def register(
        self,
        name: str,
        handler: CommandHandler,
        *,
        description: str = "",
        usage: str = "",
        category: str = "其他",
        aliases: Optional[List[str]] = None,
    ) -> CommandHandler:
        """显式注册命令。可作为装饰器使用，也可直接调用。"""
        if name in self._registry:
            raise ValueError(f"命令 '{name}' 已被注册")
        info = CommandInfo(
            name=name,
            handler=handler,
            description=description,
            usage=usage,
            category=category,
            aliases=aliases or [],
        )
        self._registry[name] = info
        self._categories[category].append(info)
        for alias in (aliases or []):
            if alias in self._registry or alias in self._aliases:
                raise ValueError(f"别名 '{alias}' 冲突")
            self._aliases[alias] = name
        return handler

    def command(
        self,
        name: str,
        *,
        description: str = "",
        usage: str = "",
        category: str = "其他",
        aliases: Optional[List[str]] = None,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """装饰器版注册：@router.command("read", description="...")"""
        def decorator(handler: CommandHandler) -> CommandHandler:
            return self.register(
                name, handler,
                description=description,
                usage=usage,
                category=category,
                aliases=aliases,
            )
        return decorator

    def add_fallback(self, handler: CommandHandler) -> None:
        """注册 fallback handler，按注册顺序组成链。"""
        self._fallbacks.append(handler)

    # ── 查询 API ──

    def resolve(self, cmd: str) -> Optional[CommandInfo]:
        """解析命令名（支持别名）。"""
        if cmd in self._registry:
            return self._registry[cmd]
        canonical = self._aliases.get(cmd)
        if canonical:
            return self._registry.get(canonical)
        return None

    def is_registered(self, cmd: str) -> bool:
        return cmd in self._registry or cmd in self._aliases

    # ── 分发 API ──

    def dispatch(self, ctx: CommandContext) -> bool:
        """
        执行命令分发。
        返回 True: 继续 REPL; 返回 False: 退出程序。
        """
        info = self.resolve(ctx.cmd)
        if info:
            try:
                result = info.handler(ctx)
                return False if result is False else True
            except Exception as e:
                print(f"[CommandRouter] 命令 '/{ctx.cmd}' 执行出错: {e}")
                return True

        # 无匹配命令 → 走 fallback 链（multi_mode / agent / single_turn）
        for fallback in self._fallbacks:
            try:
                result = fallback(ctx)
                if result is not None:
                    return False if result is False else True
            except Exception as e:
                print(f"[CommandRouter] fallback 执行出错: {e}")
        return True

    # ── 帮助生成 ──

    def build_help(self, session: Any) -> str:
        """按类别自动生成帮助文本。"""
        from core import _fmt, STYLES
        b = lambda t: _fmt(t, STYLES.BLUE)
        c = lambda t: _fmt(t, STYLES.CYAN)
        gr = lambda t: _fmt(t, STYLES.GRAY)

        lines = [
            b("╔══════════════════════════════════════════════════════╗"),
            b("║         女仆编程师 v2.0 — 命令帮助                  ║"),
            b("╚══════════════════════════════════════════════════════╝"),
            "",
        ]

        # 类别排序：按预设优先级，其余按字母序
        priority = ["模式切换", "输出控制", "会话管理", "文件编辑", "代码片段",
                    "代码执行", "Git 集成", "知识库", "Agent 系统", "搜索",
                    "Todo", "开发者工具", "聊天增强 · Phase 1", "扩展", "其他"]
        sorted_cats = sorted(
            self._categories.keys(),
            key=lambda cat: (priority.index(cat) if cat in priority else 999, cat)
        )

        for cat in sorted_cats:
            infos = self._categories[cat]
            if not infos:
                continue
            lines.append(c(f"【{cat}】"))
            for info in infos:
                usage = info.usage or f"/{info.name}"
                desc = info.description
                line = f"  {usage:<30} {desc}"
                lines.append(line)
            lines.append("")

        lines.append(gr("提示: 旧命令（deep/code/multi/clear/quit）仍兼容。"))
        return "\n".join(lines)

    def get_command_list(self) -> List[str]:
        """返回所有命令名（用于 Tab 补全）。"""
        names = set(self._registry.keys())
        names.update(self._aliases.keys())
        return sorted(names)
