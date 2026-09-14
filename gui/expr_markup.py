"""gui/expr_markup.py —— v1.4.2 AI 自选表情协议（标记解析 + 指南文本）。

设计：AI 在回复末尾（或行内）输出 [[表情:xxx]] 标记（xxx = 表情 id），
发送前由 chat_service 在系统消息尾注入「表情选择指南」；回复完成后：
  1. extract() 提取全部标记 → 取最后一个作为最终表情；
  2. 正文剥离全部标记（用户看不到协议文本）；
  3. 经 companion_bridge.mood_changed 广播表情 id（订阅方 set_maid_expression
     直接按 id 显示——心情名与表情 id 同名机制，角色资产集切换后自动显示该角色的图）。
模型未输出标记 → 走既有心情/活动态机制，互不干扰。
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

# [[表情:xxx]] / [[表情：xxx]]（中英冒号均容错）
_MARKUP_RE = re.compile(r"\[\[表情[:：]\s*([A-Za-z_][A-Za-z0-9_]*)\s*\]\]")

# 36 标准表情中文速查（供 AI 选择参考；角色专属扩展表情由指南动态补充提示）
_EXPRESSION_GUIDE_ITEMS: List[Tuple[str, str]] = [
    ("normal", "平静默认"),
    ("happy", "开心微笑"),
    ("giggle", "捂嘴偷笑"),
    ("wink", "眨眼俏皮"),
    ("shy", "害羞脸红"),
    ("surprised", "惊讶吃惊"),
    ("thinking", "思考中"),
    ("focus", "认真专注"),
    ("typing", "敲键盘打字中"),
    ("tired", "疲惫",
     ),
    ("sigh", "叹气"),
    ("sleep", "闭眼晚安"),
    ("concerned", "担忧关切"),
    ("pout", "生气嘟嘴"),
    ("smug", "得意"),
    ("cheeky", "调皮"),
    ("teary", "委屈含泪"),
    ("cry", "大哭"),
    ("nod", "点头同意"),
    ("shake", "摇头否定"),
    ("clap", "鼓掌庆祝"),
    ("victory", "胜利剪刀手"),
    ("sparkle", "期待星星眼"),
    ("heart", "比心"),
    ("bow", "鞠躬"),
    ("greet", "招手打招呼"),
    ("wave", "挥手告别"),
    ("alert", "警觉"),
    ("question", "疑惑提问"),
    ("meltdown", "崩溃抱头"),
    ("sweat", "汗颜流汗"),
    ("sit", "盘腿坐陪伴"),
    ("coffee", "喝咖啡醒神"),
    ("cake", "蛋糕庆祝彩蛋"),
    ("sakura", "樱花彩蛋"),
    ("snow", "雪彩蛋"),
]


def extract_expressions(text: str) -> Tuple[str, List[str]]:
    """从 AI 回复中提取表情标记。

    返回 (剥离标记后的正文, 按出现顺序的表情 id 列表)。
    无标记时正文原样返回、列表为空。
    """
    if not text:
        return text, []
    ids: List[str] = [m.group(1).strip().lower() for m in _MARKUP_RE.finditer(text)]
    clean = _MARKUP_RE.sub("", text)
    # 清理剥离后遗留的空行堆积（标记通常独占一行）
    clean = re.sub(r"\n{3,}", "\n\n", clean).rstrip()
    return clean, ids


def final_expression(text: str) -> Tuple[str, str, Optional[str]]:
    """一步到位：返回 (剥离标记正文, 全部 id 列表, 最终表情 id 或 None)。

    最终表情取「最后一个」标记——模型的收尾情绪最能代表回复结束时的状态。
    """
    clean, ids = extract_expressions(text)
    return clean, ids, (ids[-1] if ids else None)


def expression_guide_text(extra_ids: Optional[List[str]] = None) -> str:
    """生成注入 system 消息尾部的「表情选择指南」。

    extra_ids：当前角色资产集里的扩展表情（彩蛋）id，一并提供给模型选用。
    """
    lines = ["/**表情差分指令（内部协议，严格遵守）**/"]
    lines.append(
        "你必须在回复的**第一行**（正文之前）单独输出一行表情标记，格式：[[表情:表情id]]，"
        "用来决定你这一轮回复时形象所呈现的表情与动作——用户会在读到你的正文之前先看到你的表情变化。"
        "规则：①每一轮回复都必须以标记开头（这是硬性要求，不是可选项，"
        "漏发标记视为格式错误）；"
        "②每次回复只输出 1 个标记；③标记不算正文内容，用户看不到它，请勿在正文里提及该协议。"
        "示例：用户打招呼 → 第一行输出 [[表情:greet]]；用户夸你 → [[表情:shy]]；"
        "你在思考分析 → [[表情:thinking]]；任务完成 → [[表情:clap]]；"
        "用户说再见 → [[表情:wave]]。"
        "错误示范（禁止）：不输出标记直接开始正文。"
        "可选表情 id 及含义："
    )
    items = [f"{eid}={desc}" for eid, desc in _EXPRESSION_GUIDE_ITEMS]
    if extra_ids:
        items.extend(f"{eid}=(本角色的专属表情彩蛋)" for eid in extra_ids)
    lines.append("、".join(items))
    lines.append("请根据你此刻真实的情绪与对话内容自主判断该用哪个表情——像人一样自然，不要机械轮换。")
    return "\n".join(lines)


class MarkupStreamFilter:
    """流式标记过滤器：跨 chunk 缓冲识别 [[表情:xxx]] 并吞掉，其余原样放行。

    用在 chat_service 的流式管道（ApiWorker emit 之前），保证气泡渲染从头到尾
    看不到任何协议文本（零穿帮）。非协议的 [[...]]（如用户正文里恰好出现）原样
    放行不误伤。captured 记录捕获到的表情 id 序列（最终取最后一个）。
    """

    _MAX_PENDING = 64  # 未闭合缓冲上限：超过视为普通文本放行，防 "[[" 长期滞留

    def __init__(self, on_expression=None) -> None:
        self._buf = ""
        self.captured: List[str] = []
        # v1.4.2: 捕获到标记即回调（表情在正文出现前切换）——仅第一个触发
        self._on_expression = on_expression

    def feed(self, chunk: str) -> str:
        self._buf += chunk or ""
        out: List[str] = []
        while self._buf:
            i = self._buf.find("[")
            if i == -1:
                out.append(self._buf)
                self._buf = ""
                break
            if i > 0:
                out.append(self._buf[:i])
                self._buf = self._buf[i:]
            if not self._buf.startswith("[["):
                # 单个 "[" 可能是跨 chunk "[[" 的前半 → 留 1 字符等待下一段
                out.append(self._buf[0])
                self._buf = self._buf[1:]
                continue
            j = self._buf.find("]]")
            if j == -1:
                if len(self._buf) > self._MAX_PENDING:
                    out.append(self._buf[:1])
                    self._buf = self._buf[1:]
                    continue
                break  # 等待更多 chunk
            token = self._buf[:j + 2]
            m = _MARKUP_RE.fullmatch(token)
            if m:
                eid = m.group(1).strip().lower()
                self.captured.append(eid)
                if self._on_expression is not None and len(self.captured) == 1:
                    try:
                        self._on_expression(eid)
                    except Exception:
                        pass
            else:
                out.append(token)  # 非协议 → 原样放行
            self._buf = self._buf[j + 2:]
        return "".join(out)

    def flush(self) -> str:
        """流结束：缓冲里未闭合的内容原样放行（模型异常截断时不吞正文）。"""
        rest, self._buf = self._buf, ""
        return rest
