"""agent_engine.py —— AgentEngine 统一调度器（码铃 Agent 化的核心新模块）

职责：把"LLM 推理 ↔ 工具执行"的循环收拢成一个可复用引擎。
CLI 与 GUI 共用本引擎，避免各写一套工具循环。

流程：
  用户任务
    → 组装 messages（system + history + user）
    → 带 tools 调 API
    → 若返回 tool_calls：
        逐个 execute() 执行（AgentTools 内部处理授权）
        tool 结果回写历史
        回到"带 tools 调 API"（最多 max_steps 轮）
    → 否则：content 即最终答案，结束

与现有代码的关系（对应蓝图 D3）：
- 本引擎独立存在，不改动 session.single_turn 的旧循环；
- 事件回调 on_event 供 GUI 推送"工具轨迹"到界面；
- cancel_check 供 GUI 停止按钮协作取消。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from api import APIClient
from core import AppConfig
from agent_tools import AgentTools
from agent_task import STEP_FAIL_MARKER, STEP_OK_MARKER, TaskRun

# 事件类型（v1.1 既有）
EVT_LLM_START = "llm_start"        # 即将请求模型（第 N 轮）
EVT_TOOL_CALL = "tool_call"        # 模型请求调用工具：{name, arguments}
EVT_TOOL_DONE = "tool_done"        # 工具执行完成：{name, ok, summary}
EVT_TOOL_DENIED = "tool_denied"    # 工具被授权拒绝：{name}
EVT_FINAL = "final"                # 最终答案就绪：{content}
EVT_MAX_STEPS = "max_steps"        # 达到步数上限

# v1.2(C3/C2, D5 只增不改)：managed 任务步骤事件
EVT_TASK_PLAN   = "task_plan"     # {task_id, goal, steps: n}
EVT_STEP_START  = "step_start"    # {idx, total, goal}
EVT_STEP_PASS   = "step_pass"     # {idx, note}
EVT_STEP_FAIL   = "step_fail"     # {idx, error_summary}
EVT_HEAL_TRY    = "heal_try"      # {idx, attempt, max_retries, fail_summary}（C2 使用）
EVT_STOP_HEAL   = "stop_heal"     # {idx, reason}（C2 自愈中止/超限）
EVT_TASK_PAUSED = "task_paused"   # {idx, reason}（用户停止 → 断点暂停落盘）
EVT_TASK_DONE   = "task_done"     # {ok, summary}


class AgentEngine:
    def __init__(self, api: APIClient, cfg: AppConfig, logger: logging.Logger,
                 tools: Optional[AgentTools] = None,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 cancel_check: Optional[Callable[[], bool]] = None,
                 max_steps: int = 8,
                 companion: Any = None,
                 on_content_chunk: Optional[Callable[[str], None]] = None):
        self.api = api
        self.cfg = cfg
        self.logger = logger
        self.tools = tools or AgentTools(cfg, logger)
        self.on_event = on_event or (lambda ev, data: None)
        self.cancel_check = cancel_check or (lambda: False)
        self.max_steps = max_steps
        # v1.2(C3)：companion 弱耦合（getattr 守卫，无则空转）——任务完成事件钩子
        self.companion = companion
        # v1.4.7: 流式 content delta 回调（GUI 实时渲染）
        self.on_content_chunk = on_content_chunk or (lambda chunk: None)

    # ------------------------------------------------------------------
    def run(self, system_prompt: str, history: List[dict], user_input: str) -> str:
        """执行一轮 agent 任务，返回最终文本答案。

        v1.4.7: 最终回答阶段支持流式 content delta 回调（on_content_chunk），
        GUI 可实时渲染文字而非等待全部完成。

        history: 现有会话非 system 消息（[{role, content}...]），会被复制后扩展，
                 不会污染调用方持有的原列表。
        """
        messages: List[dict] = [{"role": "system", "content": system_prompt}]
        for m in history:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append({"role": m["role"], "content": m["content"]})
        messages.append({"role": "user", "content": user_input})

        tools_schemas = self.tools.schemas()

        for step in range(1, self.max_steps + 1):
            if self.cancel_check():
                return "（已取消）"

            self.on_event(EVT_LLM_START, {"step": step})
            content, tool_calls = self._chat(messages, tools=tools_schemas)

            if not tool_calls:
                # 最终回答：content 已通过 _chat 流式回调推送给 GUI
                self.on_event(EVT_FINAL, {"content": content, "step": step})
                return content

            # 有工具调用：先记录 assistant 的 tool_calls，再逐个执行并回写
            messages.append({"role": "assistant", "content": content or None, "tool_calls": tool_calls})
            for tc in tool_calls:
                if self.cancel_check():
                    return "（已取消）"
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        arguments = {"value": arguments}
                except json.JSONDecodeError:
                    arguments = {}

                self.on_event(EVT_TOOL_CALL, {"step": step, "name": name, "arguments": arguments})
                result = self.tools.execute(name, arguments)

                status = "error"
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        status = parsed.get("status", "error")
                except Exception:
                    status = "ok"  # 非 JSON 也视为有输出
                summary = result[:200] if len(result) > 200 else result
                if status == "denied":
                    self.on_event(EVT_TOOL_DENIED, {"name": name})
                else:
                    self.on_event(EVT_TOOL_DONE, {"name": name, "ok": status == "ok", "summary": summary})

                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": result})

            # 循环继续：模型将基于工具结果产出最终答案或再次调用工具

        self.on_event(EVT_MAX_STEPS, {"max_steps": self.max_steps})
        return f"任务步骤超过上限（{self.max_steps} 轮）仍未收敛，请简化需求或分步执行。"

    # ------------------------------------------------------------------
    def _chat(self, messages: List[dict], tools: Optional[List[dict]] = None) -> Tuple[str, list]:
        """v1.4.7: 流式工具调用 —— content delta 实时推送给 GUI，tool_calls 收集后返回。

        返回 (accumulated_content, tool_calls_list)。
        - 无 tool_calls 时：content 已通过 on_content_chunk 逐块推送，accumulated_content 为完整文本。
        - 有 tool_calls 时：content 为空（模型在 tool_call 阶段不发 content），返回组装好的 tool_calls。
        """
        gen = self.api.chat_stream_with_tools(
            messages,
            max_tokens=self.cfg.api_max_tokens,
            use_reasoning=False,
            tools=tools,
        )
        accumulated = []
        for delta in gen:
            if delta:
                accumulated.append(delta)
                try:
                    self.on_content_chunk(delta)
                except Exception:
                    pass
        content = "".join(accumulated)
        tool_calls = getattr(self.api, "_last_stream_tool_calls", []) or []
        return content, tool_calls

    # ==================================================================
    # v1.2(C3/C2/C4)：managed 任务入口（规划 → 逐步执行 → C2 自愈 → 事件）。run() 旧路径不改。
    # 时序：TaskPlanner 拆解 → TaskRun 落盘 → for step：
    #     运行态标记/事件 → 步内工具子循环(预算, 每轮注入[任务进度]) → 判定契约
    #     → 未通过进 C2 内层自愈（失败摘要回注，最多 agent_max_retries 轮）
    #     → 通过(EVT_STEP_PASS + heal 事件) / 超限(EVT_STOP_HEAL + failed + 卡点上报)
    # ==================================================================
    def run_managed_task(
        self,
        goal: str,
        planner_prompt: str = "",
        task_ctx_fn: Optional[Callable[[TaskRun], str]] = None,
        task_system: str = "",
        task_run: Optional[TaskRun] = None,
        store: Any = None,
        step_budget: Optional[int] = None,
        planner_turns: int = 4,
    ) -> TaskRun:
        """C3/C2/C4 步骤化执行入口（design D4/D5）。

        返回 TaskRun（status ∈ done/failed/paused）。全部步骤 passed → done；
        步骤未通过先进 C2 内层自愈（最多 agent_max_retries 轮，失败摘要回注，
        write_file/run_command 修改复验）；超限 → 该步 failed、不自动跳过、
        卡点写入 summary；用户停止 → paused 落盘（断点恢复，从第一个非 passed 步骤续跑）。
        每轮 LLM 请求前注入 build_task_context 的「[任务进度]」临时上下文（C4，
        仅任务域短程进度，与 memory 跨会话画像分离、互不写入）。
        """
        from agent_task import (
            TaskPlanner, TaskRunStore, build_task_context, new_task_run,
            refresh_summary, step_system_prompt,
        )

        store = store or TaskRunStore(logger=self.logger)
        budget = step_budget or int(getattr(self.cfg, "agent_max_steps", 8) or 8)

        # ---- 1) 规划：新建任务（LLM 拆步骤）或断点续跑（给定 task_run）----
        if task_run is None:
            planner = TaskPlanner(self.api, self.logger, max_turns=planner_turns)
            steps = planner.plan(goal, planner_prompt=planner_prompt,
                                 tool_provider=self.tools)
            run = new_task_run(goal, steps)
            self.on_event(EVT_TASK_PLAN, {"task_id": run.task_id, "goal": run.goal,
                                          "steps": len(run.steps)})
        else:
            run = task_run
            if run.status == "done":
                return run
            if run.status not in ("planned", "paused", "running", "failed"):
                self.logger.warning("任务 %s 状态 %s 不可续跑", run.task_id, run.status)
                return run

        run.status = "running"
        refresh_summary(run)
        store.save(run)

        # ---- 2) 逐步骤执行（跳过已 passed；失败先进 C2 自愈，超限才 failed）----
        try:
            for step in run.steps:
                if step.status == "passed":
                    continue
                if self.cancel_check():
                    return self._pause_run(run, store, step.idx, "user_stop")
                step.status = "running"
                step.note = ""
                refresh_summary(run)
                store.save(run)
                self.on_event(EVT_STEP_START, {"idx": step.idx, "total": len(run.steps),
                                               "goal": step.goal})
                outcome = self._run_one_step(run, step, budget, task_system, task_ctx_fn)
                if outcome == "cancelled":
                    return self._pause_run(run, store, step.idx, "user_stop")
                passed, detail = outcome

                # C2 内层自愈：attempt 1 未通过 → 失败摘要回注，让模型 write_file/run_command
                # 修改复验，最多 agent_max_retries 轮；授权规则不绕过（走各工具自身授权）。
                heal_ok = False
                if not passed:
                    hr = self._heal_step(run, step, store, detail, budget,
                                         task_system, task_ctx_fn)
                    if hr == "cancelled":
                        self.on_event(EVT_STOP_HEAL, {"idx": step.idx, "reason": "用户中止自愈"})
                        return self._pause_run(run, store, step.idx, "user_stop")
                    heal_ok, detail = hr

                if passed or heal_ok:
                    step.status = "passed"
                    step.note = detail
                    refresh_summary(run)
                    store.save(run)
                    self.on_event(EVT_STEP_PASS, {"idx": step.idx, "note": detail})
                    if heal_ok:
                        self._notify_companion_heal(run, step.idx,
                                                    getattr(step, "retries_used", 0))
                else:
                    # 自愈超限（heal 返回 False）或 attempt1 直接失败：failed 即止、
                    # 不自动跳过，卡点写入 summary 等用户接管
                    step.status = "failed"
                    step.note = detail
                    refresh_summary(run)
                    store.save(run)
                    self.on_event(EVT_STEP_FAIL, {"idx": step.idx,
                                                  "error_summary": (detail or "")[:200]})
                    break

            # ---- 3) 收尾判定 ----
            if run.status == "paused":
                return run
            all_passed = bool(run.steps) and all(s.status == "passed" for s in run.steps)
            run.status = "done" if all_passed else "failed"
            if not all_passed:
                run.summary["current_blocker"] = next(
                    (s.note or s.goal for s in run.steps if s.status == "failed"), "")
            refresh_summary(run)
            store.save(run)
            self.on_event(EVT_TASK_DONE, {"ok": all_passed, "summary": dict(run.summary)})
            if all_passed:
                self._notify_companion_done(run)
            return run
        except Exception as e:
            self.logger.exception("managed 任务异常: %s", e)
            if run.status != "paused":
                run.status = "failed"
                run.summary["current_blocker"] = f"引擎异常: {e}"
                refresh_summary(run)
            store.save(run)
            self.on_event(EVT_TASK_DONE, {"ok": False, "summary": dict(run.summary)})
            return run

    # ------------------------------------------------------------------
    def _run_one_step(self, run: TaskRun, step, budget: int,
                      task_system: str,
                      task_ctx_fn: Optional[Callable[[TaskRun], str]],
                      seed: Optional[str] = None) -> Tuple[object, str]:
        """单步工具子循环（一次尝试 = attempt 1 或一次 heal 尝试）。

        返回:
        - "cancelled" 用户停止
        - (True, note)  通过（C2-1 判定契约：显式声明完成 + 验证性 run_command exit 0）
        - (False, note) 未通过（进入 C2 自愈时由上层决定是否重试）
        seed: 该次尝试的引导语（如自愈第 n 次的失败摘要回注）。
        """
        from agent_task import build_task_context, step_system_prompt

        sys_prompt = step_system_prompt(run, step, task_system)
        tools_schemas = self.tools.schemas()
        messages: List[dict] = [{"role": "system", "content": sys_prompt}]

        last_verify_exit: Optional[int] = None  # 本步最近一次 run_command exit_code
        step.artifacts = []
        final_content = ""

        for _round in range(1, budget + 1):
            if self.cancel_check():
                return "cancelled"
            # C4：每轮请求前注入 [任务进度]（临时 user 项，不污染持久历史）。
            # 首轮且带 seed（heal 引导）时并入同一条 user，避免连续 user 碎片。
            ctx_text = task_ctx_fn(run) if task_ctx_fn else build_task_context(run)
            if _round == 1 and seed:
                user_text = f"{seed}\n\n{ctx_text}\n请继续执行本步骤。"
            else:
                user_text = f"{ctx_text}\n请继续执行本步骤。"
            messages.append({"role": "user", "content": user_text})

            resp = self._chat(messages, tools=tools_schemas)
            assistant_msg = (resp or {}).get("choices", [{}])[0].get("message", {}) or {}
            tool_calls = assistant_msg.get("tool_calls") or []
            content = assistant_msg.get("content") or ""
            if content:
                final_content = content
            if not tool_calls:
                return self._judge_step(final_content, last_verify_exit)

            # 有工具调用：执行并回写（事件轨迹与 run() 同口径）
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                if self.cancel_check():
                    return "cancelled"
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    arguments = json.loads(fn.get("arguments") or "{}")
                    if not isinstance(arguments, dict):
                        arguments = {"value": arguments}
                except json.JSONDecodeError:
                    arguments = {}
                self.on_event(EVT_TOOL_CALL, {"step": step.idx, "name": name,
                                              "arguments": arguments})
                result = self.tools.execute(name, arguments)
                status = "error"
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict):
                        status = parsed.get("status", "error")
                except Exception:
                    status = "ok"
                summary = result[:200] if len(result) > 200 else result
                if status == "denied":
                    self.on_event(EVT_TOOL_DENIED, {"name": name})
                else:
                    self.on_event(EVT_TOOL_DONE, {"name": name, "ok": status == "ok",
                                                  "summary": summary})
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": result})
                # 验证性证据（C2-1 判定契约输入；本批只记录供判定/产物展示）
                if name == "run_command":
                    try:
                        p = json.loads(result)
                        if isinstance(p, dict) and isinstance(p.get("exit_code"), int):
                            last_verify_exit = p["exit_code"]
                            step.artifacts.append(
                                f"[{step.idx}] run_command exit={last_verify_exit} "
                                f"({p.get('elapsed_seconds', '?')}s)")
                    except Exception:
                        pass
                elif name == "write_file" and status == "ok":
                    step.artifacts.append(f"[{step.idx}] write_file")

        # 预算耗尽仍未产出最终回答
        tail = (final_content or "").strip().splitlines()
        note = (tail[-1][:120] if tail else "") or "模型在预算内未收敛"
        return False, f"步骤 {step.idx} 超过 {budget} 轮预算仍未明确收尾，最后输出: {note}"

    # ------------------------------------------------------------------
    @staticmethod
    def _judge_step(final_content: str, last_verify_exit: Optional[int]) -> Tuple[bool, str]:
        """步骤完成判定（C3 骨架版，C2-1 判定契约的本地弱化实现）。

        规则：模型显式声明失败 → failed；
        声明完成且最近验证 exit_code ∈ (None, 0) → passed；
        有失败验证(≠0)却声明完成 / 未按契约声明 → failed（等 C-7 内层自愈接管）。
        """
        lines = [ln.strip() for ln in (final_content or "").splitlines()]
        # 声明标记允许后附说明：「[步骤完成] 说明」也视为显式声明
        declared_ok = any(ln == STEP_OK_MARKER or ln.startswith(STEP_OK_MARKER) for ln in lines)
        declared_fail = any(ln == STEP_FAIL_MARKER or ln.startswith(STEP_FAIL_MARKER) for ln in lines)
        has_fail_verify = last_verify_exit is not None and last_verify_exit != 0
        body = (final_content or "").strip()[-300:]

        if declared_fail:
            return False, f"模型声明步骤失败: {body}"
        if declared_ok and not has_fail_verify:
            return True, "模型声明完成" + (f"，最近验证 run_command exit=0" if last_verify_exit == 0 else "")
        if declared_ok and has_fail_verify:
            return False, (f"模型声明完成但最近验证性 run_command exit_code={last_verify_exit}≠0，"
                           "按判定契约视为未通过（C-7 自愈接管）")
        if last_verify_exit == 0:
            # 未显式声明但最近验证全绿：宽松通过（减少强格式依赖的误伤）
            return True, "最近验证性 run_command exit=0，视为通过"
        if not final_content.strip():
            return False, "模型未产出任何内容"
        return False, f"模型未按契约声明完成/失败，最后输出: {body}"

    # ------------------------------------------------------------------
    def _heal_step(self, run: TaskRun, step, store: Any, fail_note: str, budget: int,
                   task_system: str,
                   task_ctx_fn: Optional[Callable[[TaskRun], str]]) -> object:
        """C2 内层自愈：失败摘要回注 → 模型 write_file/run_command 修改复验。

        返回:
        - "cancelled"          用户停止（上层转 pause）
        - (True, note)         自愈成功（某次尝试通过；note = 成功说明）
        - (False, note)        超过 agent_max_retries 轮仍未通过（EVT_STOP_HEAL 已在
                               内部发出；上层转 failed 并写入卡点）
        授权不绕过：每次 write_file/run_command 仍走各自 L1 授权规则。
        """
        from agent_task import refresh_summary

        max_retries = self._max_retries()
        if max_retries <= 0:
            return (False, fail_note)
        note = fail_note
        for attempt in range(1, max_retries + 1):
            if self.cancel_check():
                return "cancelled"
            step.status = "healing"
            step.retries_used = attempt
            refresh_summary(run)
            store.save(run)
            self.on_event(EVT_HEAL_TRY, {"idx": step.idx, "attempt": attempt,
                                         "max_retries": max_retries,
                                         "fail_summary": (note or "")[:200]})
            seed = (
                f"[自愈第 {attempt}/{max_retries} 次] 上一步尝试未通过，失败信息如下：\n"
                f"{note}\n"
                "请基于失败原因定位问题：用 write_file 修改代码、用 run_command 复验"
                "（仍在 workspace 白名单内，越界/非法命令会被拒绝）。"
                "通过后按本步契约显式声明完成；不要重复同样的错误尝试。"
            )
            out = self._run_one_step(run, step, budget, task_system, task_ctx_fn, seed=seed)
            if out == "cancelled":
                return "cancelled"
            passed, note = out
            if passed:
                step.retries_used = attempt
                return (True, note)
        self.logger.warning("步骤 #%s 自愈超过 %s 轮仍未通过", step.idx, max_retries)
        self.on_event(EVT_STOP_HEAL, {"idx": step.idx,
                                      "reason": f"自愈超过 {max_retries} 轮上限",
                                      "fail_summary": (note or "")[:200]})
        return (False, note)

    # ------------------------------------------------------------------
    def _max_retries(self) -> int:
        """读取 agent_max_retries（默认 3，上限 10，0 = 关闭自愈）。"""
        try:
            n = int(getattr(self.cfg, "agent_max_retries", 3) or 3)
        except (TypeError, ValueError):
            n = 3
        return max(0, min(n, 10))

    # ------------------------------------------------------------------
    def _pause_run(self, run: TaskRun, store: Any, idx: int, reason: str) -> TaskRun:
        """用户停止：TaskRun 置 paused 落盘，当前步骤回退 pending（断点续跑）。"""
        from agent_task import refresh_summary
        for s in run.steps:
            if s.status in ("running", "healing"):
                s.status = "pending"
        run.status = "paused"
        refresh_summary(run)
        store.save(run)
        self.logger.info("任务 %s 已暂停（断点 #%s）: %s", run.task_id, idx, reason)
        self.on_event(EVT_TASK_PAUSED, {"idx": idx, "reason": reason})
        return run

    # ------------------------------------------------------------------
    def _notify_companion_heal(self, run: TaskRun, step_idx: int, attempt: int = 0) -> None:
        """自愈修复成功 → companion.ingest_event('heal')（弱耦合，无则空转）。"""
        companion = self.companion
        if companion is None:
            return
        try:
            fn = getattr(companion, "ingest_event", None)
            if callable(fn):
                fn("heal", {"task_id": run.task_id, "step_idx": step_idx,
                            "attempt": attempt})
        except Exception as e:
            self.logger.warning("companion heal 投递失败: %s", e)

    # ------------------------------------------------------------------
    def _notify_companion_done(self, run: TaskRun) -> None:
        """任务全过 → companion.ingest_event('agent_done')（弱耦合，无则空转）。"""
        companion = self.companion
        if companion is None:
            return
        try:
            fn = getattr(companion, "ingest_event", None)
            if callable(fn):
                fn("agent_done", {"task_id": run.task_id, "goal": run.goal,
                                  "steps": len(run.steps)})
        except Exception as e:  # 陪伴钩子异常不影响主流程
            self.logger.warning("companion agent_done 投递失败: %s", e)

