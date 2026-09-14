# -*- coding: utf-8 -*-
"""agent_task.py —— C3/C4 Agent 任务执行域（码铃 v1.2，TaskRun/TaskStep）

对应 docs/design-v12.md D4（任务 C-5/C-6/C-4 最小版）与 PRD C3-1/C4-1。
与既有系统的硬边界（PRD Q4/D4 裁决）：
- **不复用 PlanStore/FileChange**（core/plan_engine.py，/plan「文件变更方案」语义，session 在用）；
- **不复用 PagePlan 的 Plan/Task 模型**（gui/pages/page_plan.py，手工计划编辑器）；
  本模块是另一套「Agent 任务运行时执行清单」，持久化 ~/.maid_coder/task_runs/。

内容：
- TaskStep / TaskRun 数据模型（每步含 goal/acceptance/status/产出，可断点恢复）
- TaskRunStore：原子写落盘 ~/.maid_coder/task_runs/<task_id>.json
- TaskPlanner：LLM（可先 read_file/list_dir 探索）把大任务拆成 2~8 步 JSON
- C4 最小版：TaskRun.summary（goal/done_steps/current_blocker）每步后压缩更新
  + build_task_context() 生成供每轮注入的「[任务进度]」文本

本模块刻意保持轻依赖：只 import stdlib（json/os/dataclasses/logging）+ typing，
不顶层 import core / agent_tools / api —— LLM 能力用鸭子类型注入，便于自测 Fake 替换。
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

_logger = logging.getLogger("maid_coder.agent_task")

# 运行目录（D4 定稿）
_TASK_RUNS_DIR = os.path.expanduser("~/.maid_coder/task_runs")

# 状态常量
STEP_STATUSES = ("pending", "running", "passed", "failed", "healing", "aborted")
RUN_STATUSES = ("planned", "running", "paused", "done", "failed", "aborted")

PLAN_MIN_STEPS = 1            # 一步可完成（等价 v1.1 单步）
PLAN_MAX_STEPS = 8            # 大任务拆解上限
PLAN_MAX_TURNS = 4            # 规划阶段 LLM⇄只读工具 的最大轮数
STEP_BUDGET_DEFAULT = 8       # 单步内工具调用/思考轮数上限（可被 cfg.agent_max_steps 覆盖）

# 步骤通过/失败显式声明标记（C2-1 判定契约的前置；C-7 将在此之上加内层自愈）
STEP_OK_MARKER = "[步骤完成]"
STEP_FAIL_MARKER = "[步骤失败]"


def _now() -> str:
    return datetime.now().isoformat()


def _atomic_write_json(path: str, data: dict) -> None:
    """原子写 JSON（.tmp + os.replace）—— 与 companion.py 同语义，保持纯 stdlib。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class TaskStep:
    """单个执行步骤。"""
    idx: int                       # 1..n 序号
    goal: str                      # 本步要做什么
    acceptance: str                # 验收标准（用户声明或模型自拟）
    status: str = "pending"        # pending|running|passed|failed|healing|aborted
    retries_used: int = 0          # C2 自愈已用轮数（本批保持 0，C-7 使用）
    artifacts: List[str] = field(default_factory=list)  # 产出/验证命令输出摘要
    note: str = ""                 # 失败原因/阻塞点等

    def to_dict(self) -> dict:
        return {
            "idx": self.idx, "goal": self.goal, "acceptance": self.acceptance,
            "status": self.status, "retries_used": self.retries_used,
            "artifacts": list(self.artifacts), "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskStep":
        return cls(
            idx=int(d.get("idx", 0)),
            goal=str(d.get("goal", "") or ""),
            acceptance=str(d.get("acceptance", "") or ""),
            status=str(d.get("status") or "pending"),
            retries_used=int(d.get("retries_used", 0) or 0),
            artifacts=[str(x) for x in (d.get("artifacts") or [])],
            note=str(d.get("note", "") or ""),
        )


@dataclass
class TaskRun:
    """Agent 任务运行时执行清单（断点恢复单元）。"""
    task_id: str
    goal: str
    steps: List[TaskStep]
    status: str = "planned"        # planned|running|paused|done|failed|aborted
    created_at: str = ""
    updated_at: str = ""
    summary: Dict[str, Any] = field(default_factory=dict)  # C4: 每步后压缩更新

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id, "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status, "created_at": self.created_at,
            "updated_at": self.updated_at, "summary": dict(self.summary or {}),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TaskRun":
        steps = []
        for raw in d.get("steps") or []:
            try:
                steps.append(TaskStep.from_dict(raw))
            except Exception:
                continue
        return cls(
            task_id=str(d.get("task_id", "") or ""),
            goal=str(d.get("goal", "") or ""),
            steps=steps,
            status=str(d.get("status") or "planned"),
            created_at=str(d.get("created_at", "") or ""),
            updated_at=str(d.get("updated_at", "") or ""),
            summary=dict(d.get("summary") or {}),
        )


# ---------------------------------------------------------------------------
# summary 压缩记忆（C4 最小版）
# ---------------------------------------------------------------------------
def refresh_summary(run: TaskRun) -> dict:
    """每步状态变更后压缩更新 TaskRun.summary（C4: 目标+已完成+当前卡点）。

    summary = {"goal", "done", "total", "done_steps", "current",
               "current_blocker", "status"}。返回 summary（已写回 run）。
    """
    done: List[str] = []
    current_idx: Optional[int] = None
    current_goal = ""
    blocker = ""
    for s in run.steps:
        if s.status == "passed":
            done.append(f"#{s.idx} {s.goal}")
        elif s.status in ("failed", "aborted") and not blocker:
            blocker = s.note or s.goal
        elif s.status == "running" and current_idx is None:
            current_idx = s.idx
            current_goal = s.goal
    # 无 running 步时，把第一个未完成步标为 current（供汇报「下一步做什么」）
    if current_idx is None:
        for s in run.steps:
            if s.status not in ("passed", "failed", "aborted"):
                current_idx = s.idx
                current_goal = s.goal
                break
    run.summary = {
        "goal": run.goal,
        "done": len(done),
        "total": len(run.steps),
        "done_steps": done,
        "current": {"idx": current_idx, "goal": current_goal} if current_idx else None,
        "current_blocker": blocker,
        "status": run.status,
    }
    return run.summary


def build_task_context(run: TaskRun) -> str:
    """把 TaskRun.summary 压成「[任务进度]」注入文本（C4 每轮注入用）。"""
    s = run.summary or refresh_summary(run)
    parts = [f"任务目标: {s.get('goal') or run.goal}"]
    parts.append(f"已完成 {s.get('done', 0)}/{s.get('total', len(run.steps))} 步")
    ds = s.get("done_steps") or []
    if ds:
        parts.append("已完成步骤: " + "; ".join(ds[-5:]))
    cur = s.get("current") or {}
    if cur.get("goal"):
        parts.append(f"当前步骤 #{cur.get('idx')}: {cur['goal']}")
    if s.get("current_blocker"):
        parts.append(f"当前卡点: {s['current_blocker']}")
    return "[任务进度] " + " | ".join(parts)


# ---------------------------------------------------------------------------
# TaskRunStore：断点恢复
# ---------------------------------------------------------------------------
class TaskRunStore:
    """任务存档：~/.maid_coder/task_runs/<task_id>.json，每步状态变更即落盘。

    异常退出后，从第一个非 passed 步骤续跑（断点恢复）。
    base_dir 可注入（自测用临时目录），默认取用户数据目录。
    """

    def __init__(self, base_dir: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        self.base_dir = os.path.expanduser(base_dir) if base_dir else _TASK_RUNS_DIR
        self.logger = logger or _logger

    def _path(self, task_id: str) -> str:
        return os.path.join(self.base_dir, f"{task_id}.json")

    def save(self, run: TaskRun) -> None:
        os.makedirs(self.base_dir, exist_ok=True)
        run.updated_at = _now()
        _atomic_write_json(self._path(run.task_id), run.to_dict())

    def load(self, task_id: str) -> Optional[TaskRun]:
        p = self._path(task_id)
        if not os.path.exists(p):
            return None
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError, OSError) as e:
            self.logger.warning("任务存档损坏，无法恢复 %s: %s", task_id, e)
            return None
        run = TaskRun.from_dict(data)
        if not run.task_id or not run.steps:
            return None
        return run

    def delete(self, task_id: str) -> bool:
        p = self._path(task_id)
        try:
            os.remove(p)
            return True
        except OSError:
            return False

    def list(self) -> List[dict]:
        """列出全部存档摘要（continue 上次任务 / 管理用）。"""
        out: List[dict] = []
        if not os.path.isdir(self.base_dir):
            return out
        for name in sorted(os.listdir(self.base_dir), reverse=True):
            if not name.endswith(".json"):
                continue
            run = self.load(name[:-5])
            if run is None:
                continue
            s = run.summary or refresh_summary(run)
            out.append({
                "task_id": run.task_id, "goal": run.goal, "status": run.status,
                "updated_at": run.updated_at,
                "progress": f"{s.get('done', 0)}/{s.get('total', len(run.steps))}",
                "current_blocker": s.get("current_blocker") or "",
            })
        return out

    @staticmethod
    def next_resume_step(run: TaskRun) -> int:
        """返回第一个非 passed 步骤的 idx（1..n）；全过返回 0（无需续跑）。"""
        for s in run.steps:
            if s.status != "passed":
                return s.idx
        return 0


# ---------------------------------------------------------------------------
# 提示词构造
# ---------------------------------------------------------------------------
def planner_system_prompt(goal: str, planner_prompt: str = "") -> str:
    """规划阶段 system prompt：基于只读探索产出 2~8 步清单。"""
    extra = (planner_prompt or "").strip()
    return (
        "你是码铃（Agent 模式的任务规划器）。请把用户任务拆解为可逐步执行的步骤清单，"
        "每步都小而可验证（跑测试/读文件/改代码）。\n"
        "规则：\n"
        f"1. 步骤数 1~{PLAN_MAX_STEPS}（简单任务可 1 步 = 单步执行）；每步必须有 goal 与 acceptance。\n"
        "2. 可用 read_file/list_dir 等只读工具了解项目，不要修改任何文件；规划阶段不可调用写/执行类工具。\n"
        "3. 最终**只输出**一个 JSON（不要 Markdown 代码块之外的任何话），格式：\n"
        '   {"steps": [{"goal": "步骤目标", "acceptance": "验收标准"}]}\n'
        "4. 验收标准应具体可判（如「pytest tests/test_x.py 全绿且 exit_code==0」）。\n"
        "任务: " + goal + ("\n补充约束: " + extra if extra else "")
    )


def step_system_prompt(run: TaskRun, step: TaskStep, task_system: str = "") -> str:
    """步骤执行 system prompt：交代当前步骤与完成契约。"""
    base = (task_system or "").strip()
    base = base or (
        "你是码铃（Agent 模式），正在为主人完成一个多步任务。执行当前步骤时可用全部工具"
        "（只读 read_file/list_dir/git_status/git_diff；修改 write_file/git_commit；"
        "验证 run_command 仅白名单解释器在 workspace 内运行，属进程级非沙箱）。"
        "写文件与越界运行会征求主人授权，被拒时不要绕过。"
    )
    return (
        f"{base}\n\n"
        f"当前任务 #{run.task_id} 共 {len(run.steps)} 步，本步 {step.idx}/{len(run.steps)}。\n"
        f"[步骤目标] {step.goal}\n"
        f"[验收标准] {step.acceptance}\n\n"
        "工作方式：先了解现状 → 修改 → 用 run_command 或合理手段验证。\n"
        "完成契约：**当且仅当**验收确实达成（建议以 run_command 验证输出 exit_code==0 为准）后，"
        f"在最终回复的最后另起一行写 {STEP_OK_MARKER}（可附说明）；"
        f"无法达成时写 {STEP_FAIL_MARKER} 并说明卡点。"
        "不得在未真正验证通过时假装完成，也不得把失败当完成。"
    )


# ---------------------------------------------------------------------------
# TaskPlanner
# ---------------------------------------------------------------------------
class PlanFormatError(Exception):
    """规划结果不是合法步骤 JSON。"""


class TaskPlanner:
    """LLM 任务拆解器。

    api: 鸭子类型，需 .chat(messages, max_tokens=..., tools=[...]) -> OpenAI 兼容 dict。
    tool_provider: 鸭子类型，需 .schemas() / .execute(name, args)（通常传 AgentTools）；
        为 None 时规划走纯单次调用（模型不能探索）。
    """

    def __init__(self, api: Any, logger: Optional[logging.Logger] = None,
                 max_turns: int = PLAN_MAX_TURNS,
                 read_tool_names: Tuple[str, ...] = ("read_file", "list_dir", "git_status", "git_diff")):
        self.api = api
        self.logger = logger or _logger
        self.max_turns = max(1, int(max_turns))
        self.read_tool_names = read_tool_names

    # ------------------------------------------------------------------
    def plan(self, goal: str, planner_prompt: str = "",
             tool_provider: Any = None, max_tokens: int = 1500) -> List[TaskStep]:
        """把任务描述拆成步骤清单。返回 [TaskStep]（idx 从 1 起）。

        解析失败抛 PlanFormatError（由调用方决定任务 failed 处理）。
        """
        messages: List[dict] = [
            {"role": "system", "content": planner_system_prompt(goal, planner_prompt)},
            {"role": "user", "content": f"请把任务拆成步骤：{goal}"},
        ]
        tools = self._read_schemas(tool_provider)

        last_content = ""
        for _turn in range(self.max_turns):
            resp = self.api.chat(messages, max_tokens=max_tokens,
                                 temperature=0.2, tools=tools or None)
            msg = (resp or {}).get("choices", [{}])[0].get("message", {}) or {}
            tool_calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            if content:
                last_content = content

            if not tool_calls:
                steps = self._parse_steps(content or last_content)
                if steps:
                    return steps
                # 有内容但解析失败 → 让模型重试一次（带提示），仍失败则报错
                messages.append({"role": "assistant", "content": content or "(无输出)"})
                messages.append({"role": "user",
                                 "content": "输出不是合法步骤 JSON。请只输出 "
                                            '{"steps": [{"goal": ..., "acceptance": ...}]}，不要任何多余文字。'})
                continue

            # 规划期仅允许只读工具（读文件/列目录/看 git），防规划阶段触发授权弹窗/副作用
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = (tc.get("function") or {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}") or {}
                    if not isinstance(args, dict):
                        args = {"value": args}
                except json.JSONDecodeError:
                    args = {}
                if name not in self.read_tool_names or tool_provider is None:
                    note = f"规划阶段仅允许只读工具 {','.join(self.read_tool_names)}，已拒绝 {name}"
                else:
                    try:
                        note = tool_provider.execute(name, args)
                    except Exception as e:  # 规划探索异常不致命，回注让模型继续
                        note = f"工具 {name} 执行失败: {e}"
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""), "content": note})
        raise PlanFormatError(
            f"规划未能产出合法步骤 JSON（最后输出: {last_content[:200]!r}）"
        )

    # ------------------------------------------------------------------
    def _read_schemas(self, tool_provider: Any) -> List[dict]:
        """只放行只读工具的 schema（规划阶段模型只能看到这些）。"""
        if tool_provider is None:
            return []
        try:
            all_schemas = tool_provider.schemas()
        except Exception as e:
            self.logger.warning("读取工具 schema 失败: %s", e)
            return []
        return [
            s for s in all_schemas
            if (s.get("function") or {}).get("name") in self.read_tool_names
        ]

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_steps(text: str) -> List[TaskStep]:
        """容错解析：支持 ```json 代码块 / 裸 JSON / 前后缀散文包裹。"""
        if not text or not str(text).strip():
            return []
        raw = str(text).strip()
        # 1) 提取 JSON 块
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
        candidate = m.group(1) if m else raw
        # 2) 定位第一个 { 到最后一个 } 之间（容忍散文前后缀）
        s, e = candidate.find("{"), candidate.rfind("}")
        if s >= 0 and e > s:
            candidate = candidate[s:e + 1]
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            data = data["steps"]
        if not isinstance(data, list):
            return []
        steps: List[TaskStep] = []
        for i, item in enumerate(data, 1):
            if not isinstance(item, dict):
                continue
            goal = str(item.get("goal") or "").strip()
            if not goal:
                continue
            steps.append(TaskStep(
                idx=i, goal=goal,
                acceptance=str(item.get("acceptance") or "自拟验收标准：改动生效且无回归").strip(),
            ))
            if len(steps) >= PLAN_MAX_STEPS:
                break
        return steps if steps else []


# ---------------------------------------------------------------------------
# 便捷：新建 TaskRun
# ---------------------------------------------------------------------------
def new_task_run(goal: str, steps: List[TaskStep],
                 task_id: Optional[str] = None) -> TaskRun:
    """按步骤清单建 TaskRun（task_id 缺省自动生成 task_<8位hex>）。"""
    import uuid
    tid = task_id or ("task_" + uuid.uuid4().hex[:8])
    now = _now()
    run = TaskRun(task_id=tid, goal=goal, steps=steps,
                  status="planned", created_at=now, updated_at=now)
    refresh_summary(run)
    return run
