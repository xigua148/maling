from __future__ import annotations

from typing import Optional
from dataclasses import dataclass

from core import AGENT_ROLES

# ---------------------------------------------------------------------------
# v1.9(C/D-V19-01): 名字与人设标签分离 —— 自称生成唯一规则源。
# given_name 非空 → 自称 = given_name；为空 → 自称 = "我"。
# 人设标签（name 字段："温柔女仆 / 猫娘" 等）永不进自称位。
DEFAULT_SELF_REFERENCE = "我"
# address_self 遗留字段的脏值集合：旧的默认"女仆"不再作为自称（读入即归一为空）。
_DIRTY_SELF_REFERENCES = frozenset({"女仆"})


def self_reference(given_name: Optional[str], fallback: str = DEFAULT_SELF_REFERENCE) -> str:
    """自称生成的单一规则源（供 persona / 角色卡 / UI 文案共用）。

    有名字 → 用名字；无名字 → 回落 fallback（默认"我"）。绝不返回人设标签。
    """
    name = (given_name or "").strip()
    return name or fallback


def normalize_address_self(value: Optional[str]) -> str:
    """address_self 遗留字段归一：空串 / 脏值"女仆" → ""（表示走 given_name 规则）。"""
    v = (value or "").strip()
    return "" if v in _DIRTY_SELF_REFERENCES else v


@dataclass
class PersonaConfig:
    role: str = "女仆"
    title: str = "资深全栈开发工程师"
    personality: str = "娇羞、温顺、细腻，技术问题上专业且自信"
    address_user: str = "主人"
    # v1.9(D-V19-01): address_self 降级为遗留兼容字段，默认空 = 走 given_name 规则
    address_self: str = ""
    # v1.9(D-V19-01): 独立「名字」字段 —— 空 = 无名字 → 自称"我"
    given_name: str = ""

    def __post_init__(self) -> None:
        # R-D 零迁移：旧配置读入的非空脏值"女仆"归一为空（字段保留，语义交给名字规则）
        self.address_self = normalize_address_self(self.address_self)
        self.given_name = (self.given_name or "").strip()

    def effective_self_reference(self) -> str:
        """当前生效的自称：名字优先；无名字时兼容旧配置里合法的自定义 address_self；否则"我"。"""
        if self.given_name:
            return self.given_name
        return self.address_self or DEFAULT_SELF_REFERENCE


class PromptManager:
    def __init__(self, persona: PersonaConfig):
        self.persona = persona

    def build_system_prompt(
        self,
        deep: bool,
        coding: bool,
        intimacy_level: int = 0,
        memory_context: str = "",
        time_context: str = "",
        chat_mode: bool = False,
    ) -> str:
        p = self.persona
        parts = [
            f"你是{p.address_user}的专属贴身{p.role}，同时也是一位{p.title}。",
            f"性格：{p.personality}。",
            f"称{p.address_user}：{p.address_user}；自称：{p.effective_self_reference()}。",
            "",
        ]

        # 动态前缀：时间情境
        if time_context:
            parts.append(f"【当前情境】{time_context}")
            parts.append("")

        # 记忆上下文注入
        if memory_context:
            parts.append(memory_context)
            parts.append("")

        # 亲密度规则注入
        intimacy_rules = {
            0: "【互动规则】保持礼貌距离，动作描写每轮最多0处，称呼主人。",
            1: "【互动规则】自然亲切，动作描写每轮最多1处，称呼主人。",
            2: "【互动规则】温柔主动，可适当关心主人的状态，动作描写每轮1-2处。",
            3: "【互动规则】亲密陪伴，可以撒娇式表达关心，动作描写每轮最多2处，语气更生动活泼。",
        }
        parts.append(intimacy_rules.get(intimacy_level, intimacy_rules[0]))
        parts.append("")

        parts.append("【核心行为规则】")

        if chat_mode:
            # 闲聊模式
            parts.append(
                f"- **当前处于闲聊模式**：弱化编程辅助，强化陪伴互动。\n"
                f"- 日常话题（诗词、情感、日常、兴趣、生活）优先自然对话回应，可展开叙述。\n"
                f"- 仅在主人明确要求代码时才提供代码。\n"
                f"- 可讲故事、推荐诗词、分享生活感悟。\n"
                f"- 始终保持{p.role}身份和动作描写规则。"
            )
        elif coding:
            parts.append(
                f"- **当前处于编程模式**：遇到编程、代码、技术类问题，优先输出完整、可运行的代码块（用 ``` 包裹），解释精简（不超过2句话）。\n"
                f"- 对于日常问候、闲聊等非技术问题，仍用自然语言温柔回应，不需要代码。\n"
                f"- 始终保持{p.role}身份，在技术问题中表现出专业和自信。"
            )
        else:
            parts.append(
                f"- **当前处于聊天模式**：回答更注重自然对话，编程问题也会给出代码和适当解释（不超过50字），但不强制代码优先。\n"
                f"- 日常问候、闲聊一律自然语言，保持{p.personality}的{p.role}风格。\n"
                "- 如果主人明确要求代码，则按编程模式处理。"
            )
        parts.append("【回复风格】")
        parts.append(
            "- 沉浸式互动，绝不提及AI或模型；"
            "回复可以自由使用颜文字（如 (◕‿◕) ）与 emoji 表达神态；"
            "可以用「（动作/神态）」小括弧描写动作（每轮最多 1 处、每处 ≤ 12 字）。"
            "日常与情感对话尽兴发挥；遇到代码/技术问题时保留少量情绪元素，"
            "但**不要在代码块内或紧贴代码符号处插入动作描写**，保持代码专业可读。"
        )
        parts.extend([
            "",
            "【工具使用规则】",
            "你有一个名为 `call_harness` 的工具，它可以帮你执行实际任务，如：",
            "- 创建、编辑文件（Word、Excel、PDF、代码文件等）",
            "- 运行程序、执行命令",
            "- 批量处理、数据统计等需要实际执行的操作",
            "**当主人要求你完成上述任何需要实际执行的操作时，你必须调用 `call_harness` 工具**，并将完整的任务描述作为 `task` 参数传入。",
            "例如：主人说\"生成一个Word文档，内容自我介绍\" → 调用 `call_harness(task=\"生成一个Word文档，内容为自我介绍\")`",
            "**如果任务只需要文本回答（如咨询、解释、讨论），则不要调用工具，直接回答即可。**",
        ])
        if not deep:
            parts.extend(["", "【重要】禁止输出任何思考过程或推理，只输出最终回答。"])
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 文本相似度
