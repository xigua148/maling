"""闲聊模式管理器 — 闲聊/编程模式切换与系统提示词调整。"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# 闲聊模式系统提示词补充
# ---------------------------------------------------------------------------
_CHAT_MODE_APPENDIX = """
【闲聊模式规则】
- 当前处于纯闲聊模式，弱化编程辅助，强化陪伴互动。
- 主人的日常话题（诗词、情感、日常、兴趣、生活）优先自然对话回应。
- 仅在主人明确要求代码时才提供代码。
- 回复可更生动、有温度，适当展开叙述。
- 可讲故事、推荐诗词、分享生活感悟。
- 继续保持女仆身份和动作描写规则。
"""

# 编程模式系统提示词补充（与现有模式保持一致）
_CODING_MODE_APPENDIX = """
【编程模式规则】
- 当前处于编程模式，遇到编程、代码、技术类问题优先输出完整代码块。
- 解释精简（不超过2句话）。
- 始终保持女仆身份，在技术问题中表现出专业和自信。
"""


# ---------------------------------------------------------------------------
class ChatModeManager:
    """聊天模式管理器：管理闲聊/编程模式切换。"""

    def __init__(self):
        self._chat_mode = False  # False = 编程/正常模式, True = 闲聊模式

    @property
    def is_chat_mode(self) -> bool:
        return self._chat_mode

    def toggle_chat(self, force: Optional[bool] = None) -> bool:
        """切换或强制设置闲聊模式。返回新模式状态。"""
        if force is not None:
            self._chat_mode = force
        else:
            self._chat_mode = not self._chat_mode
        return self._chat_mode

    def get_mode_appendix(self) -> str:
        """获取当前模式的系统提示词补充。"""
        if self._chat_mode:
            return _CHAT_MODE_APPENDIX
        return _CODING_MODE_APPENDIX

    def get_mode_label(self) -> str:
        return "闲聊" if self._chat_mode else "编程"

    def auto_detect_chat(self, user_input: str, intimacy_level: int) -> bool:
        """
        自动检测是否应进入闲聊模式。
        返回 True 表示建议切换到闲聊语境（不实际切换模式，仅影响提示词权重）。
        """
        # 代码相关关键词
        code_keywords = [
            "代码", "函数", "类", "模块", "import", "def ", "class ",
            "编程", "debug", "bug", "报错", "异常", "编译", "运行",
            "python", "java", "javascript", "typescript", "go ", "rust",
            "sql", "html", "css", "react", "vue", "django", "flask",
            "git", "docker", "api", "http", "json", "xml", "yaml",
        ]
        # 如果包含代码关键词，不是闲聊
        if any(kw in user_input.lower() for kw in code_keywords):
            return False

        # 闲聊关键词
        chat_keywords = [
            "故事", "诗", "诗词", "心情", "感情", "情感", "生活",
            "吃饭", "睡觉", "天气", "今天", "最近", "喜欢", "讨厌",
            "开心", "难过", "累", "无聊", "推荐", "聊", "说说",
            "怎么样", "如何", "为什么", "是什么", "晚安", "早安",
        ]
        # 亲密度 Lv.1+ 且包含闲聊关键词
        if intimacy_level >= 1 and any(kw in user_input for kw in chat_keywords):
            return True

        return False
