from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from core import AppConfig, AGENT_ROLES, C, G, GR, R, Y  # v10.15: 多模型工作流的颜色常量
from api import APIClient
from persona import self_reference  # v1.9(C/D-V19-01): 自称走名字规则（有名字用名字，无名字"我"）
from security import _text_similarity as text_similarity

# ---------------------------------------------------------------------------
class AgentSystem:
    def __init__(self, api: APIClient, cfg: AppConfig, logger: logging.Logger):
        self.api = api
        self.cfg = cfg
        self.logger = logger
        self.current_role: Optional[str] = None

    def get_role_prompt(self, role: str) -> str:
        return AGENT_ROLES.get(role, {}).get("prompt", "")

    def get_role_name(self, role: str) -> str:
        return AGENT_ROLES.get(role, {}).get("name", role)

    def get_role_desc(self, role: str) -> str:
        return AGENT_ROLES.get(role, {}).get("desc", "")

    def auto_detect_role(self, query: str) -> str:
        """根据用户输入自动判断最合适的角色。"""
        keywords = {
            "product": ["需求", "功能", "用户故事", "PRD", "产品", "规划", "设计"],
            "arch": ["架构", "设计", "方案", "接口", "性能", "数据库", "缓存", "微服务"],
            "dev": ["代码", "实现", "写", "debug", "调试", "bug", "报错", "优化", "重构"],
            "review": ["审查", "review", "质检", "安全", "测试", "coverage", "漏洞"],
        }
        scores = {role: 0 for role in keywords}
        for role, words in keywords.items():
            for w in words:
                if w in query:
                    scores[role] += 1
        best = max(scores, key=scores.get)
        if scores[best] == 0:
            return "dev"  # 默认研发
        return best

    def run_agent(self, role: str, query: str, history: Optional[List[dict]] = None) -> Tuple[str, Optional[dict]]:
        """用指定角色回答，融合女仆人设。返回 (content, usage)。"""
        role_prompt = self.get_role_prompt(role)
        role_name = self.get_role_name(role)
        # 融合人设前缀 + 角色专业能力（v1.9: 自称取 given_name 规则，缺省"我"）
        _given_name = getattr(self.cfg, "persona_given_name", "") or ""
        fused_prompt = (
            f"你是主人的专属贴身女仆，当前以「{role_name}」的身份为主人服务。\n"
            f"性格：娇羞、温顺、细腻，技术问题上专业且自信。\n"
            f"称用户：主人；自称：{self_reference(_given_name)}。\n"
            f"沉浸式互动，绝不提及AI或模型。可适当加入动作描写（每轮最多1处，每处≤10字）。\n"
            f"工具使用规则：当任务需要实际执行操作时，必须调用 `call_harness` 工具。\n\n"
            f"以下是你的专业能力：\n\n"
            f"{role_prompt}"
        )
        messages = [{"role": "system", "content": fused_prompt}]
        if history:
            messages.extend([m for m in history if m["role"] in ("user", "assistant")])
        messages.append({"role": "user", "content": query})
        try:
            resp = self.api.chat(messages, max_tokens=self.cfg.api_max_tokens)
            return resp["choices"][0]["message"].get("content", ""), resp.get("usage")
        except Exception as e:
            return f"Agent 调用失败: {e}", None

    def run_workflow(self, task: str, session_history: List[dict]) -> Tuple[str, Optional[dict]]:
        """自动串联多 Agent 工作流。返回 (content, total_usage)。"""
        outputs = []
        total_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        steps = [
            ("product", "请分析以下需求，输出结构化的产品需求文档（PRD）："),
            ("arch", "基于以上 PRD，设计系统架构和技术方案："),
            ("dev", "基于以上架构设计，编写核心代码实现："),
            ("review", "审查以上代码，给出质量评估和安全建议："),
        ]

        context = task
        for i, (role, prefix) in enumerate(steps, 1):
            print(C(f"\n🔄 工作流步骤 {i}/4: {self.get_role_name(role)} 正在处理..."))
            query = f"{prefix}\n\n{context}"
            result, usage = self.run_agent(role, query)
            if result.startswith("Agent 调用失败"):
                err_msg = f"❌ 工作流中断于步骤 {i} ({self.get_role_name(role)}): {result}"
                outputs.append(f"## 步骤 {i}: {self.get_role_name(role)}\n\n{err_msg}")
                print(R(err_msg))
                break
            outputs.append(f"## 步骤 {i}: {self.get_role_name(role)}\n\n{result}")
            context = result[:2000]  # 压缩上下文
            if usage:
                total_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                total_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                total_usage["total_tokens"] += usage.get("total_tokens", 0)

        return "\n\n---\n\n".join(outputs), (total_usage if total_usage["total_tokens"] > 0 else None)


# ---------------------------------------------------------------------------
# 敏感信息检测
# 多模型协作
# ---------------------------------------------------------------------------
class MultiModelCollaborator:
    def __init__(self, api: APIClient, cfg: AppConfig, logger: logging.Logger):
        self.api = api
        self.cfg = cfg
        self.logger = logger
        self._usage_log: List[dict] = []

    def _log_usage(self, resp: dict, label: str) -> None:
        usage = resp.get("usage")
        if usage:
            self._usage_log.append({"label": label, **usage})

    def _print_usage_summary(self) -> None:
        if not self._usage_log:
            return
        total = sum(u.get("total_tokens", 0) for u in self._usage_log)
        print(GR("\n[Token 用量明细]"))
        for u in self._usage_log:
            print(GR(f"  {u['label']}: 输入{u.get('prompt_tokens',0)}/输出{u.get('completion_tokens',0)}"))
        print(GR(f"  总计: {total} Token"))

    def run(self, user_query: str, deep_mode: bool = False, speed: str = "normal") -> Tuple[str, Optional[dict]]:
        print(C("\n🧠 启动多模型协作模式..."))
        self._usage_log = []

        if self.cfg.multi_parallel_gen_review:
            # 注: 当前版本生成与评审仍为串行执行，parallel 选项预留为未来并发优化
            print("  [1/3] 生成者与评审者准备中...")
            gen_result = self._generate(user_query, deep_mode)
            rev_result = self._review(user_query, gen_result["text"], deep_mode)
        else:
            gen_result = self._generate(user_query, deep_mode)
            rev_result = self._review(user_query, gen_result["text"], deep_mode)

        gen_answer = gen_result["text"]
        review = rev_result["text"]

        first_line = review.strip().splitlines()[0].strip().upper() if review.strip() else ""
        if first_line == "[PASS]" or not review.strip():
            print(G("  ✅ 评审通过，直接采用生成者答案。"))
            self._print_usage_summary()
            return gen_answer, self._total_usage()

        print(R(f"  ❌ 评审不通过: {review[:200]}..."))

        print("  [2/3] 修正者正在改进...")
        revised = self._revise(user_query, gen_answer, review, deep_mode)
        revised_answer = revised["text"]

        similarity = text_similarity(gen_answer, revised_answer)
        self.logger.debug("原始与修正后相似度: %.2f", similarity)

        if similarity >= self.cfg.multi_judge_threshold:
            print(Y(f"  ⏭️ 相似度 {similarity:.0%} ≥ 阈值 {self.cfg.multi_judge_threshold:.0%}，跳过裁判，直接采用修正者输出。"))
            self._print_usage_summary()
            return revised_answer, self._total_usage()

        print("  [3/3] 裁判进行最终仲裁...")
        final = self._judge(gen_answer, revised_answer, deep_mode)
        self._print_usage_summary()
        return final["text"], self._total_usage()

    def _total_usage(self) -> Optional[dict]:
        if not self._usage_log:
            return None
        return {
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in self._usage_log),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in self._usage_log),
            "total_tokens": sum(u.get("total_tokens", 0) for u in self._usage_log),
        }

    def _generate(self, query: str, deep: bool) -> dict:
        messages = [
            {"role": "system", "content": "你是一位专业助手，请针对用户问题给出准确、完整的初步回答。不要谦虚，直接输出答案。"},
            {"role": "user", "content": query},
        ]
        resp = self.api.chat(messages, max_tokens=self.cfg.api_max_tokens, use_reasoning=deep)
        self._log_usage(resp, "生成者")
        return {"text": resp["choices"][0]["message"]["content"]}

    def _review(self, query: str, answer: str, deep: bool) -> dict:
        messages = [
            {"role": "system", "content": (
                "你是一位严格的评审专家，请对以下回答进行审查，找出其中的事实错误、逻辑漏洞、"
                "缺失重要信息、表述不清之处。\n"
                "输出格式：第一行固定为 [PASS] 或 [FAIL]，后面接详细意见（如果需要）。"
            )},
            {"role": "user", "content": f"问题：{query}\n\n回答：{answer}"},
        ]
        resp = self.api.chat(messages, max_tokens=1000, use_reasoning=deep)
        self._log_usage(resp, "评审者")
        return {"text": resp["choices"][0]["message"]["content"]}

    def _revise(self, query: str, original: str, review: str, deep: bool) -> dict:
        messages = [
            {"role": "system", "content": "你是一位资深编辑，请根据评审意见，对原始回答进行修正和完善。输出修正后的完整回答。"},
            {"role": "user", "content": f"原始问题：{query}\n原始回答：{original}\n\n评审意见：{review}\n\n请输出修正后的完整回答："},
        ]
        resp = self.api.chat(messages, max_tokens=self.cfg.api_max_tokens, use_reasoning=deep)
        self._log_usage(resp, "修正者")
        return {"text": resp["choices"][0]["message"]["content"]}

    def _judge(self, original: str, revised: str, deep: bool) -> dict:
        messages = [
            {"role": "system", "content": (
                "你是一位公正的裁判，请综合原始回答和修正后的回答，"
                "选择其中更正确、更完整、更清晰的一个作为最终答案。"
                "如果两者各有优劣，可综合输出一个更好的答案。输出最终答案即可。"
            )},
            {"role": "user", "content": f"原始回答：{original}\n\n修正后回答：{revised}\n\n请输出最终答案："},
        ]
        resp = self.api.chat(messages, max_tokens=self.cfg.api_max_tokens, use_reasoning=deep)
        self._log_usage(resp, "裁判")
        return {"text": resp["choices"][0]["message"]["content"]}


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
