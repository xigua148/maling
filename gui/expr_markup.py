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

# v2.1(UI-Fix-0912-3): 放宽标记识别 —— 原正则只认 `[[表情:ascii_id]]`，
# 但指南里给模型的是「happy=开心微笑」这类「id=中文描述」，模型很自然会输出
# `[[表情:开心]]`（中文名）、`[表情:happy]`（单方括号）或 `[[表情:]]`（空值），
# 这些都漏进了正文（用户看到 `[[表情:开心]]` 这种协议文本 = 「不知道是什么」）。
# 现支持：1~2 个方括号 + 中英冒号 + 英文 id / 中文名 / 空值。
_MARKUP_RE = re.compile(
    r"\[{1,2}\s*(?:表情|表情包|emotion|expression|emo)\s*[:：]\s*"
    r"([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fff]{1,8})?\s*\]{1,2}",
    re.IGNORECASE,
)

# 标记关键字（长在前，便于前缀匹配）
_MARKUP_KEYS = ("表情包", "表情", "emotion", "expression", "emo")


def _is_open_prefix(s: str) -> bool:
    """``s`` 以 ``[`` 开头时，判断它**是否可能**是标记的开头（含"还没读全"的情况）。

    流式过滤必须跨 chunk 缓冲：收到 ``[`` / ``[[`` / ``[[表`` / ``[[表情:`` 时都不能急着
    放行，否则标记会被拆散漏进正文（这正是原实现用 ``startswith("[[")`` 在守的边界）。
    只有确定「不可能成为标记」才立即按普通文本放行（如 ``[0]`` / ``[链接]``）。
    """
    if not s.startswith("["):
        return False
    body = s.lstrip("[")
    if len(s) - len(body) > 2:          # 超过两个左方括号 → 不是标记
        return False
    if not body:                         # "[", "[[" → 继续等
        return True
    body = body.lstrip()                 # 允许关键字前有空白
    if not body:
        return True
    if body[0] in ":：":                 # 已出现冒号 → 是标记
        return True
    low = body.lower()
    return any(k.startswith(low) or low.startswith(k) for k in _MARKUP_KEYS)


def resolve_expression_token(raw: str) -> Optional[str]:
    """把标记里的原始值解析成表情 id；解析不出返回 None（但标记本身仍会被剥离）。

    - 英文 id：原样小写返回（由下游 resolve_expression 做合法性兜底）
    - 中文名：先精确匹配指南描述，再按「前缀/包含」匹配
      （指南写 `happy=开心微笑`，模型可能只取「开心」）
    """
    t = (raw or "").strip().lower()
    if not t:
        return None
    if re.fullmatch(r"[a-z_][a-z0-9_]*", t):
        return t
    for eid, desc in _EXPRESSION_GUIDE_ITEMS:
        if t == desc:
            return eid
    for eid, desc in _EXPRESSION_GUIDE_ITEMS:
        if desc.startswith(t) or (len(t) >= 2 and t in desc):
            return eid
    return None

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
    ids: List[str] = []
    for m in _MARKUP_RE.finditer(text):
        eid = resolve_expression_token(m.group(1) or "")
        if eid:
            ids.append(eid)
    # 无论能否解析出 id，标记本身一律剥离（协议文本绝不能让用户看到）
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
            # 此刻 _buf 以 "[" 开头。只有「可能成为标记开头」才值得缓冲等待闭合；
            # 确定不可能的（如 "[0]" / "[链接]"）立即按普通文本放行，避免吞正文。
            if not _is_open_prefix(self._buf):
                out.append(self._buf[0])
                self._buf = self._buf[1:]
                continue
            # 找最近的闭合 "]"（单/双方括号都收）
            j = self._buf.find("]")
            if j == -1:
                if len(self._buf) > self._MAX_PENDING:
                    out.append(self._buf[:1])
                    self._buf = self._buf[1:]
                    continue
                break  # 等待更多 chunk
            end = j + 1
            if end < len(self._buf) and self._buf[end] == "]":
                end += 1  # 吃成对的双右括号
            elif end == len(self._buf) and self._buf.startswith("[["):
                # 只收到第一个 ']' 且它是缓冲末尾 —— 下一个字符可能还是 ']'（即 "]]"）。
                # 若此刻就按单右括号收掉，会漏出一个多余的 ']' 进正文 → 再等一个字符。
                break
            token = self._buf[:end]
            m = _MARKUP_RE.fullmatch(token)
            if m:
                eid = resolve_expression_token(m.group(1) or "")
                if eid:
                    self.captured.append(eid)
                    if self._on_expression is not None and len(self.captured) == 1:
                        try:
                            self._on_expression(eid)
                        except Exception:
                            pass
                # 解析不出 id 的标记同样吞掉（协议文本不能让用户看到）
            else:
                out.append(token)  # 非协议 → 原样放行
            self._buf = self._buf[end:]
        return "".join(out)

    def flush(self) -> str:
        """流结束：把缓冲里**仍完整的标记**也剥掉，其余原样放行（模型截断时不吞正文）。"""
        rest, self._buf = self._buf, ""
        if not rest:
            return ""
        out: List[str] = []
        while rest:
            i = rest.find("[")
            if i == -1:
                out.append(rest)
                break
            out.append(rest[:i])
            rest = rest[i:]
            m = _MARKUP_RE.match(rest)
            if m:
                eid = resolve_expression_token(m.group(1) or "")
                if eid and eid not in self.captured:
                    self.captured.append(eid)
                rest = rest[m.end():]
            else:
                out.append(rest[0])
                rest = rest[1:]
        return "".join(out)
