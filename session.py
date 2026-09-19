from __future__ import annotations

import json
import logging
import os
import time
from typing import Dict, List, Optional

from core import AppConfig, G, R, Y, C, GR, B, print_typed
from api import APIClient
from persona import PersonaConfig, PromptManager
from security import scan_sensitive_info, build_tools_definition
from harness import call_harness, confirm_harness_call
from utils import _offline_cache_get, _offline_cache_save, _save_recovery, _atomic_write_json
from editors import FileEditor
from core.project_ctx import ProjectContext
from core.plan_engine import PlanStore
from managers import (
    sanitize_session_name, SessionManager, SnippetManager,
    TodoManager, PluginManager, StatsTracker,
)
from helpers import CodeSandbox, WebSearch, KnowledgeBase
from agents import AgentSystem
from memory import MemoryManager
from intimacy import IntimacyTracker
from greeting import GreetingEngine
from chat_mode import ChatModeManager

# ChatSession：封装所有状态
# ---------------------------------------------------------------------------

# v1.4.x(Bug1-延伸/Bug8): 表情指南缓存 —— 懒加载 gui.expr_markup，CLI 环境导入
# 失败返回 None（核心层零依赖 GUI）。模块级缓存避免每次构建 system 重复拼接。
_EXPRESSION_GUIDE_CACHE: Optional[str] = None


def _load_expression_guide() -> Optional[str]:
    global _EXPRESSION_GUIDE_CACHE
    if _EXPRESSION_GUIDE_CACHE is None:
        try:
            from gui.expr_markup import expression_guide_text
            _EXPRESSION_GUIDE_CACHE = expression_guide_text()
        except Exception:
            _EXPRESSION_GUIDE_CACHE = ""
    return _EXPRESSION_GUIDE_CACHE or None


# ---------------------------------------------------------------------------
# v2.5(D-V25-10): CLI 会话文件落点 —— 锚定用户数据目录
# ---------------------------------------------------------------------------
# 原实现用裸相对文件名 ``f"{name}.json"``，落点取决于**启动时的工作目录**：
# 换个目录跑 CLI，之前存的会话就「全部消失」（实际是写到了别处）。
# 与 D-V25-08（config.yaml 锚定应用根）属同一类问题，一并收口。
# 会话是**用户数据**，故落 ``~/.maid_coder/sessions/``（与 GUI 侧
# ``gui/session_manager.py`` 同一目录）；文件名加 ``cli_`` 前缀，避免与 GUI 的
# ``<session_id>.json`` 撞名 —— 两者序列化格式不同，撞名会互相破坏。


def _cli_session_dir() -> str:
    d = os.path.join(os.path.expanduser("~/.maid_coder"), "sessions")
    os.makedirs(d, exist_ok=True)
    return d


def _cli_session_file(name: str) -> str:
    return os.path.join(_cli_session_dir(), f"cli_{sanitize_session_name(name)}.json")


class ChatSession:
    def __init__(self, cfg: AppConfig, api: APIClient, logger: logging.Logger):
        self.cfg = cfg
        self.api = api
        self.logger = logger
        self.pm = PromptManager(
            PersonaConfig(
                role=cfg.persona_role,
                title=cfg.persona_title,
                personality=cfg.persona_personality,
                address_user=cfg.persona_address_user,
                address_self=cfg.persona_address_self,
                given_name=getattr(cfg, "persona_given_name", ""),  # v1.9: 自称走名字规则
            )
        )

        # v10.13: 角色面板覆盖的 system prompt（None = 使用 config persona 构建）
        self.gui_role_prompt: Optional[str] = None

        # v1.4.x(Bug8): 表情指南注入开关 —— 默认关闭（CLI 不注入）；GUI 启动时
        # 置 True。指南在 _build_system_prompt 末尾单点追加，保证任何路径
        # （角色覆盖 / persona / 未开角色面板）下模型都收到且只收到一份。
        self.expr_guide_enabled: bool = False

        self.deep_mode = False
        self.coding_mode = False
        self.multi_mode = cfg.multi_enabled
        self.speed = cfg.output_speed
        self.stream_mode = cfg.stream_mode
        self.show_tokens = cfg.output_show_token_usage

        # 新增子系统
        self.memory_mgr = MemoryManager()
        self.intimacy = IntimacyTracker()
        self.greeting_engine = GreetingEngine()
        self.chat_mode = ChatModeManager()

        # 构建初始 system prompt（带记忆和亲密度注入）
        self.current_system = self._build_system_prompt()
        self.history: List[dict] = [{"role": "system", "content": self.current_system}]
        self.turn_count = 0
        self.session_id = "default"

        self._last_usage: Optional[dict] = None
        self._multi_usage: List[dict] = []
        # v1.2.x(token): 会话累计消耗 token（GUI 首页 Token 卡 / 聊天用量显示读数）
        self.token_used: int = 0
        # v1.6(P0-4/D-V16-08): 上下文精简标志 —— _trim_history 实际截断或
        # auto_summary 摘要发生过即置 True；ChatService 请求时检测该标志注入
        # 反套话指令（请求副本，不入历史），注入后复位。clear() 复位。
        self.context_trimmed: bool = False

        # 子系统
        self.file_editor = FileEditor(logger)
        self.project_ctx = ProjectContext(self)   # lazy init
        self.plan_store = PlanStore(logger)
        self.snippet_mgr = SnippetManager(cfg.snippets_file)
        self.todo_mgr = TodoManager(cfg.todos_file)
        self.code_sandbox = CodeSandbox(cfg.code_exec_timeout)
        self.web_search = WebSearch(cfg.web_search_max_results)
        self.kb = KnowledgeBase(cfg.kb_index_file)
        self.agent_sys = AgentSystem(api, cfg, logger)
        self.plugin_mgr = PluginManager(cfg.plugins_dir)
        self.stats = StatsTracker()

        if os.path.isdir(cfg.plugins_dir):
            self.plugin_mgr.load_plugins()

    def set_gui_role_prompt(self, prompt: Optional[str]) -> None:
        """v10.13: 设置角色面板覆盖的 system prompt。

        prompt 非空时，作为当前角色设定追加到通用 persona、记忆与关系规则后；
        传 None 清除该定制设定。立即生效（更新 history 首条 system 消息）。
        """
        self.gui_role_prompt = prompt or None
        self._update_system()

    # -- system prompt 构建 --
    def _build_system_prompt(self) -> str:
        # 通用 persona、记忆与关系规则始终保留；角色面板的定制提示词作为更具体的
        # 当前角色设定追加，避免覆盖式替换丢失亲密度阶段口吻。
        memory_ctx = self.memory_mgr.build_memory_context()
        intimacy_prompt = self.intimacy.build_intimacy_prompt()
        base = self.pm.build_system_prompt(
            deep=self.deep_mode,
            coding=self.coding_mode,
            intimacy_level=self.intimacy.level,
            memory_context=memory_ctx + "\n" + intimacy_prompt if memory_ctx else intimacy_prompt,
            chat_mode=self.chat_mode.is_chat_mode,
        )
        if self.gui_role_prompt:
            base = base + "\n\n【当前角色设定】\n" + self.gui_role_prompt
        # v1.4.x(Bug1-延伸/Bug8): 表情指南单点注入 —— 无论人设来自角色覆盖还是
        # persona，都在末尾追加同一份指南（expr_guide_enabled 守卫，CLI 不注入）。
        # 此前指南由 page_role.sync 拼进 gui_role_prompt，未定制角色时会出现
        # "仅指南、无人设"的覆盖串（人设混乱根因），且角色面板从未打开时完全不
        # 注入（标记输出率低的根因）；收敛到这里后两个问题同时消除。
        if self.expr_guide_enabled:
            guide = _load_expression_guide()
            if guide:
                base = base + "\n\n" + guide
        return base

    # -- 模式切换 --
    def toggle_deep(self) -> bool:
        self.deep_mode = not self.deep_mode
        self._update_system()
        return self.deep_mode

    def toggle_coding(self) -> bool:
        self.coding_mode = not self.coding_mode
        self._update_system()
        return self.coding_mode

    def toggle_multi(self) -> bool:
        self.multi_mode = not self.multi_mode
        return self.multi_mode

    def toggle_chat_mode(self) -> bool:
        """切换闲聊模式。"""
        state = self.chat_mode.toggle_chat()
        self._update_system()
        return state

    def set_chat_mode(self, enabled: bool) -> None:
        """强制设置闲聊模式状态。"""
        self.chat_mode.toggle_chat(force=enabled)
        self._update_system()

    def set_speed(self, speed: str) -> bool:
        if speed in ("fast", "normal", "slow"):
            self.speed = speed
            return True
        return False

    def toggle_stream(self) -> bool:
        self.stream_mode = not self.stream_mode
        return self.stream_mode

    def _update_system(self) -> None:
        self.current_system = self._build_system_prompt()
        if self.history and self.history[0]["role"] == "system":
            self.history[0]["content"] = self.current_system
        else:
            self.history.insert(0, {"role": "system", "content": self.current_system})

    def refresh_system_context(self) -> None:
        """v1.6(D-V16-02): 记忆等 system 上下文变更后的当轮刷新。

        一行薄包装 = _update_system()；CLI/GUI 共用。记忆中心页每次增删改后
        调用（app_ctx.session.refresh_system_context()），保证 system prompt
        里的记忆段落与 user_memory.json 实时一致（删除即遗忘当轮生效，R-I）。
        """
        self._update_system()

    def notify_role_switch(self, role_name: str) -> None:
        """v1.5.1: 角色切换边界注入（人设零残留）。

        背景（用户实机反馈 + 截图实锤）：切 A 角色 → 切回 B 角色后，模型仍自称
        A 角色。根因是**历史带偏** —— set_gui_role_prompt/_update_system 已把
        history[0] 的 system 换成新角色（正确），但 LLM 会话历史里保留着 A 角色
        语气的大量对话，模型顺着历史风格继续说 A 话。仅换 system 不足以覆盖。

        修复策略：切角色时在历史末尾追加一条 system 边界消息，明确要求模型
        忽略此前对话中其他人设的语气，严格按当前人设继续（比清历史温和，
        保留上下文连续性）。_trim_history 保留最近 4 条 injection system，
        边界消息在多轮内持续生效。
        """
        name = (role_name or "").strip() or "新角色"
        self.add_message("system", (
            f"[角色已切换为「{name}」。从此条起，你必须严格按照上方系统设定中的"
            f"「{name}」人设说话与行动；此前对话中任何其他人设的称呼、语气、自称"
            f"一律忽略，不得延续。]"
        ))

    # -- 历史管理 --
    def add_message(self, role: str, content: Optional[str] = None, **kwargs) -> None:
        msg: dict = {"role": role}
        if content is not None:
            msg["content"] = content
        msg.update(kwargs)
        self.history.append(msg)
        self._trim_history()

    def _trim_history(self) -> None:
        # 保留主 system prompt（第一条 system）和最近的上下文 injection system messages
        system_msgs = [m for m in self.history if m.get("role") == "system"]
        others = [m for m in self.history if m.get("role") != "system"]
        max_msgs = self.cfg.max_history_rounds * 2
        if len(others) > max_msgs:
            # v1.6(P0-4/D-V16-08): 实际截断发生 → 置位（GUI 链只有截断，无 auto_summary）
            self.context_trimmed = True
            others = others[-max_msgs:]
        # 主 prompt 必须保留；最近的 injection 上下文也保留（最多 4 条，防止丢失搜索/知识库上下文）
        main_system = system_msgs[:1] if system_msgs else []
        recent_injections = system_msgs[1:][-4:] if len(system_msgs) > 1 else []
        self.history = main_system + recent_injections + others

    def clear(self) -> None:
        self.history = [{"role": "system", "content": self.current_system}]
        self.turn_count = 0
        self._last_usage = None
        self._multi_usage = []
        self.token_used = 0
        # v1.6(P0-4): 会话清空 → 上下文精简标志复位
        self.context_trimmed = False

    # 角色切换边界消息的识别前缀（notify_role_switch 幂等替换用）
    _ROLE_SWITCH_MARKER = "【角色切换】"

    def notify_role_switch(self, role_name: str) -> None:
        """v1.5.1(切角色人设残留): 角色切换边界注入。

        根因：角色切换只替换 history[0] 的 system（_update_system），而历史中
        旧角色的 user/assistant 对话全部保留 —— 模型顺着历史语气继续，仍自称
        旧角色（用户实锤：切鲸鱼娘→切回女仆，AI 仍自称"鲸鱼娘女仆"）。
        修复：追加一条 system 边界消息显式告知人设已切换；同时移除上一条
        边界消息（按 _ROLE_SWITCH_MARKER 识别），保证历史中至多一条。
        """
        # 移除旧的边界消息（幂等）
        self.history = [
            m for m in self.history
            if not (m.get("role") == "system"
                    and str(m.get("content", "")).startswith(self._ROLE_SWITCH_MARKER))
        ]
        name = (role_name or "").strip() or "当前角色"
        self.history.append({
            "role": "system",
            "content": (
                f"{self._ROLE_SWITCH_MARKER}当前角色已切换为「{name}」。"
                f"请立即完全以「{name}」的人设、自称、称呼与语气继续对话；"
                f"此前对话中出现的任何其他人设痕迹（旧角色的自称/语气/称呼）一律忽略，"
                f"不得再使用。技术讨论的上下文（代码、结论）仍然有效。"
            ),
        })

    def replace_history(self, entries: List[dict]) -> None:
        """v1.5.1(切角色人设残留): 用显示会话消息整体重建 LLM 历史。

        背景：GUI 的显示会话（session_manager）与 LLM 会话历史是两套——
        LLM history 自启动起持续累积、跨显示会话切换从不清空，导致
        旧角色的对话泄漏进新会话/新角色。此方法在切换/新建显示会话时
        以显示会话的 user/assistant 消息重建 LLM 历史，首条强制为当前
        current_system（人设来源唯一）。

        注意：直接赋值、**不走 add_message** —— 不触发 GuiChatSession 的
        message_added 信号，避免切换会话时气泡被重放。
        """
        clean: List[dict] = []
        for e in entries or []:
            role = str(e.get("role") or "")
            content = e.get("content")
            if role not in ("user", "assistant") or not content:
                continue
            clean.append({"role": role, "content": str(content)})
        self.history = [{"role": "system", "content": self.current_system}] + clean

    def add_usage(self, usage: Optional[dict]) -> None:
        """累计一次响应的 token 用量（GUI/CLI 共用；无 usage 时仅刷新 _last_usage）。"""
        if not usage:
            return
        self._last_usage = usage
        total = usage.get("total_tokens")
        if isinstance(total, int) and total > 0:
            self.token_used += total

    # -- 自动摘要 --
    def auto_summary(self) -> bool:
        self.logger.info("正在进行 %d 轮自动摘要...", self.cfg.summary_interval)
        recent = [m for m in self.history if m["role"] != "system"][-20:]
        if not recent:
            return False
        text = "\n".join([f"{m['role']}: {m['content']}" for m in recent if m.get("content")])
        summary_messages = [
            {"role": "system", "content": "精炼摘要助手。用一段话总结对话核心剧情、关键事件和未完成任务，不遗漏重要信息。只输出摘要正文。"},
            {"role": "user", "content": f"总结：\n{text}"},
        ]
        try:
            resp = self.api.chat(summary_messages, max_tokens=500, temperature=0.5)
            summary = resp["choices"][0]["message"]["content"]
            usage = resp.get("usage")
            print(G(f"✅ 摘要已生成（约 {usage.get('completion_tokens', '?')} Token）："))
            print(f"   {summary}")
            self.history = [
                {"role": "system", "content": self.current_system},
                {"role": "user", "content": f"【前情提要】{summary}"},
                {"role": "assistant", "content": "好的，女仆已记住前情。"},
            ]
            self.turn_count = 0
            # v1.6(P0-4/D-V16-08): 摘要发生过 → 置位（CLI 链）
            self.context_trimmed = True
            return True
        except Exception as e:
            print(R(f"⚠️ 摘要生成失败: {e}"))
            return False

    # -- 会话持久化 --
    def save(self, name: Optional[str] = None) -> str:
        safe_name = sanitize_session_name(name or self.session_id)
        # v2.5(D-V25-10): 绝对路径（原为 CWD 相对，换目录即「会话丢失」）
        filename = _cli_session_file(safe_name)
        data = {
            "session_id": self.session_id,
            "deep_mode": self.deep_mode,
            "coding_mode": self.coding_mode,
            "multi_mode": self.multi_mode,
            "speed": self.speed,
            "stream_mode": self.stream_mode,
            "turn_count": self.turn_count,
            "history": self.history,
            # 新增：聊天增强状态
            "chat_mode": self.chat_mode.is_chat_mode,
            "memory": self.memory_mgr.to_dict(),
            "intimacy": self.intimacy.to_dict(),
        }
        # 使用原子写入，防止写入中断导致会话文件损坏
        _atomic_write_json(filename, data)

        # 亲密度：记录保存会话
        level_msg = self.intimacy.add_save()
        if level_msg:
            print(C(f"💕 {level_msg}"))

        return filename

    def load(self, name: Optional[str] = None) -> bool:
        safe_name = sanitize_session_name(name or self.session_id)
        # v2.5(D-V25-10): 绝对路径优先；向后兼容 —— 旧版本把会话写在启动目录下，
        # 若新位置没有而当前目录存在同名文件，则读旧位置（不改动、不删除旧文件，
        # 下一次 save() 自然落到新位置）。
        filename = _cli_session_file(safe_name)
        if not os.path.exists(filename):
            _legacy = f"{safe_name}.json"
            if os.path.exists(_legacy):
                filename = _legacy
            else:
                return False
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.deep_mode = data.get("deep_mode", False)
        self.coding_mode = data.get("coding_mode", False)
        self.multi_mode = data.get("multi_mode", False)
        self.speed = data.get("speed", "normal")
        self.stream_mode = data.get("stream_mode", False)
        self.turn_count = data.get("turn_count", 0)
        self.history = data.get("history", [])
        self.session_id = sanitize_session_name(data.get("session_id", "default"))

        # 恢复聊天增强状态
        if "chat_mode" in data:
            self.chat_mode.toggle_chat(force=data["chat_mode"])
        # v2.5(D-V25-07): **不再**从会话文件回放 memory / intimacy。
        # 二者都是全局单例数据（~/.maid_coder/user_memory.json / intimacy.json），
        # 而会话文件里嵌的那份是"存这个会话当时的快照"。加载旧会话会把快照
        # 整体替换掉全局数据（from_dict 内部还会 _save() 落盘），等于**用三周前
        # 的状态覆盖至今的全部记忆**——纯数据回退，不是恢复。
        # 会话文件仍保留这两个键（存档价值：可人工查证当时状态），只是不再应用。

        if not self.history or self.history[0].get("role") != "system":
            self._update_system()
        else:
            self.current_system = self.history[0]["content"]
        return True

    # -- 单轮对话（核心逻辑）--
    def single_turn(self, user_input: str) -> None:
        self.add_message("user", user_input)
        self.turn_count += 1
        self.stats.add_message()

        # 自动搜索
        if self.cfg.web_search_enabled and self.web_search.should_auto_search(user_input):
            print(C("🔍 检测到可能需要最新信息，正在搜索..."))
            results = self.web_search.search(user_input)
            search_context = self.web_search.format_results(results)
            if results:
                self.add_message("system", f"[联网搜索上下文]\n{search_context}")
                print(C("✅ 搜索结果已注入上下文"))

        # 知识库检索
        if hasattr(self.kb, '_index') and self.kb._index:
            kb_results = self.kb.search(user_input, top_k=3)
            if kb_results:
                kb_context = "\n\n".join([f"[{path}]\n{chunk[:500]}" for path, chunk, _ in kb_results])
                self.add_message("system", f"[本地知识库上下文]\n{kb_context}")

        # 情绪检测与关心
        emotion = self.memory_mgr.detect_emotion(user_input)
        if emotion:
            emotion_responses = {
                "tired": "主人看起来很累呢 (｡･ω･｡) 要不要休息一下？",
                "happy": "主人看起来心情很好呢~ 女仆也感到开心 ✨",
                "anxious": "主人别着急，慢慢来，女仆会陪着您的 💕",
                "lonely": "女仆在这里呢，主人想聊什么都可以~ 🌸",
            }
            if emotion in emotion_responses and self.intimacy.level >= 1:
                print(C(f"\n[女仆] {emotion_responses[emotion]}"))

        # 闲聊模式自动检测（仅提示词权重调整，不切换模式）
        if self.chat_mode.auto_detect_chat(user_input, self.intimacy.level):
            # 注入临时闲聊上下文
            self.add_message("system", "[当前对话偏向日常闲聊，请用自然温暖的语气回应。]")

        try:
            tools = build_tools_definition()
            if self.cfg.output_debug:
                print(GR("[调试] 调用 API..."))

            if self.stream_mode:
                # 流式模式
                print(C("\n[女仆] "), end="", flush=True)
                full_content, tool_calls, usage = self.api.chat_stream(
                    self.history,
                    max_tokens=self.cfg.api_max_tokens,
                    use_reasoning=self.deep_mode,
                    tools=tools,
                )
                self._last_usage = usage

                if tool_calls:
                    # 流式工具调用：循环处理所有 tool_call
                    all_results = []
                    for tc in tool_calls:
                        try:
                            func_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            func_args = {}
                        task = func_args.get("task", "")
                        tc_id = tc["id"]

                        print(C(f"\n[女仆] 正在调用工具 {tc['function'].get('name', '?')}..."))
                        result = call_harness(
                            task,
                            self.cfg.tools_harness_path,
                            self.cfg.workspace,
                            self.cfg.tools_harness_timeout,
                            self.logger,
                            self.cfg.command_safety_mode,
                            confirm_fn=confirm_harness_call,
                        )
                        print(f"\n{C('[女仆]')} {result}")
                        self.stats.bump_mode("tool")
                        all_results.append((tc, result))

                    # 回写历史：先写 assistant 的 tool_calls，再逐个写 tool 结果
                    self.add_message("assistant", content=None, tool_calls=tool_calls)
                    for tc, result in all_results:
                        self.add_message("tool", content=result, tool_call_id=tc["id"])

                    # 继续回答
                    print(C("\n[女仆] "), end="", flush=True)
                    follow_content, _, follow_usage = self.api.chat_stream(
                        self.history,
                        max_tokens=self.cfg.api_max_tokens,
                        use_reasoning=self.deep_mode,
                    )
                    self._merge_usage(follow_usage)
                    if follow_content:
                        self.add_message("assistant", follow_content)
                    self._post_process(follow_content or "")
                    final_assistant_content = follow_content or ""
                else:
                    self.add_message("assistant", full_content)
                    self._post_process(full_content)
                    final_assistant_content = full_content
            else:
                # 非流式模式
                resp_json = self.api.chat(
                    self.history,
                    max_tokens=self.cfg.api_max_tokens,
                    use_reasoning=self.deep_mode,
                    tools=tools,
                )
                assistant_msg = resp_json["choices"][0]["message"]
                self._last_usage = resp_json.get("usage")

                tool_calls = assistant_msg.get("tool_calls")
                if tool_calls:
                    # 非流式工具调用：循环处理所有 tool_call
                    all_results = []
                    for tool_call in tool_calls:
                        try:
                            function_args = json.loads(tool_call["function"]["arguments"])
                        except json.JSONDecodeError:
                            function_args = {}
                        task = function_args.get("task", "")
                        tool_call_id = tool_call["id"]

                        print(C(f"\n[女仆] 正在调用工具 {tool_call['function'].get('name', '?')}..."))
                        result = call_harness(
                            task,
                            self.cfg.tools_harness_path,
                            self.cfg.workspace,
                            self.cfg.tools_harness_timeout,
                            self.logger,
                            self.cfg.command_safety_mode,
                            confirm_fn=confirm_harness_call,
                        )
                        print(f"\n{C('[女仆]')} {result}")
                        self.stats.bump_mode("tool")
                        all_results.append((tool_call, result))

                    self.add_message("assistant", content=None, tool_calls=tool_calls)
                    for tool_call, result in all_results:
                        self.add_message("tool", content=result, tool_call_id=tool_call["id"])

                    if self.cfg.output_debug:
                        print(GR("[调试] 工具结果已回写，请求模型继续..."))
                    follow_resp = self.api.chat(
                        self.history,
                        max_tokens=self.cfg.api_max_tokens,
                        use_reasoning=self.deep_mode,
                    )
                    follow_msg = follow_resp["choices"][0]["message"]
                    follow_usage = follow_resp.get("usage")
                    self._merge_usage(follow_usage)

                    content = follow_msg.get("content", "")
                    if content:
                        print_typed(content, self.speed, prefix=C("\n[女仆] "))
                        self.add_message("assistant", content)
                        self._post_process(content)
                    final_assistant_content = content
                else:
                    content = assistant_msg.get("content", "")
                    print_typed(content, self.speed, prefix=C("\n[女仆] "))
                    self.add_message("assistant", content)
                    self._post_process(content)
                    final_assistant_content = content

            self._print_usage(self._last_usage)

            # Token 统计
            if self._last_usage:
                mode_label = "agent" if self.agent_sys.current_role else "normal"
                self.stats.add_tokens(self._last_usage.get("total_tokens", 0), mode=mode_label)

            # 自动摘要
            if self.turn_count > 0 and self.turn_count % self.cfg.summary_interval == 0:
                print(Y(f"\n🔔 已进行 {self.turn_count} 轮，自动生成摘要..."))
                if self.auto_summary():
                    print(G("✅ 历史已压缩"))

            # P0-4: 保存恢复点
            _save_recovery(self)

            # P2-19: 保存到离线缓存
            last_assistant_content = None
            for m in reversed(self.history):
                if m.get("role") == "assistant" and m.get("content"):
                    last_assistant_content = m["content"]
                    break
            if last_assistant_content:
                _offline_cache_save(user_input, last_assistant_content)

            # --- 聊天增强：对话后处理 ---
            # 自动提取记忆
            extracted = self.memory_mgr.extract_from_dialogue(user_input, final_assistant_content)
            if extracted and self.cfg.output_debug:
                self.logger.info("自动提取记忆: %s", extracted)

            # 归档过期话题
            archived_count = self.memory_mgr.archive_stale_topics()
            if archived_count > 0 and self.cfg.output_debug:
                self.logger.info("归档 %d 个过期话题", archived_count)

            # 亲密度更新
            level_msg = self.intimacy.add_interaction("dialogue")
            if level_msg:
                print(C(f"\n💕 {level_msg}"))

            # 感谢检测
            if self.intimacy.detect_gratitude(user_input):
                gratitude_msg = self.intimacy.add_gratitude()
                if gratitude_msg:
                    print(C(f"\n💕 {gratitude_msg}"))

        except Exception as e:
            print(R(f"\n❌ 请求失败: {e}"))
            # P2-19: 网络失败时尝试离线缓存
            cached = _offline_cache_get(user_input)
            if cached:
                print(Y("📦 [离线缓存] 使用本地缓存的相似回答:"))
                print_typed(cached, self.speed, prefix=C("\n[女仆] "))
                self.add_message("assistant", cached)
                self._post_process(cached)
            else:
                if self.history and self.history[-1].get("role") == "user" and self.history[-1].get("content") == user_input:
                    self.history.pop()
                self.turn_count -= 1

    def _merge_usage(self, follow_usage: Optional[dict]) -> None:
        if follow_usage and self._last_usage:
            self._last_usage = {
                "prompt_tokens": self._last_usage.get("prompt_tokens", 0) + follow_usage.get("prompt_tokens", 0),
                "completion_tokens": self._last_usage.get("completion_tokens", 0) + follow_usage.get("completion_tokens", 0),
                "total_tokens": self._last_usage.get("total_tokens", 0) + follow_usage.get("total_tokens", 0),
            }
        elif follow_usage:
            self._last_usage = follow_usage

    def _post_process(self, text: str) -> None:
        """后处理 assistant 回复：提取待办、检测敏感信息、格式化代码等。"""
        try:
            # 提取 Todo
            todo_count = self.todo_mgr.extract_from_text(text)
            if todo_count:
                print(Y(f"📝 自动提取 {todo_count} 条待办事项"))

            # 敏感信息检测
            if self.cfg.sensitive_info_scan:
                sensitive = scan_sensitive_info(text)
                if sensitive:
                    print(R("⚠️ 检测到疑似敏感信息:"))
                    for label, content in sensitive:
                        print(R(f"   [{label}] {content}"))

            # 代码格式化
            sandbox_result = self.code_sandbox.extract_code(text)
            if sandbox_result:
                lang, code = sandbox_result
                if lang == "python":
                    ok, formatted = self.code_sandbox.format_with_black(code)
                    if ok:
                        print(G("🎨 已用 black 格式化代码"))
        except Exception as e:
            print(R(f"⚠️ 后处理异常（不影响主流程）: {e}"))

        # 代码执行提示
        if self.cfg.code_exec_enabled and sandbox_result:
            lang, code = sandbox_result
            if lang == "python":
                print(Y("💻 检测到 Python 代码，输入 `/run` 运行"))

    def _print_usage(self, usage: Optional[dict]) -> None:
        if not self.show_tokens or not usage:
            return
        pt = usage.get("prompt_tokens", 0)
        ct = usage.get("completion_tokens", 0)
        print(GR(f"（输入{pt}/输出{ct} Token）"))


# ---------------------------------------------------------------------------
# 多模型协作
