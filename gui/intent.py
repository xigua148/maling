"""intent —— 聊天意图五态纯规则分类（v1.6 P0-2 / D-V16-04）。

零 LLM token、零网络、零 Qt、零 core 依赖：词表匹配（优先）+ 句式正则。

五态（str 字面量，非 Enum —— 保持零依赖可序列化）：
    confide  只想说说（情绪倾诉，需要倾听与共情）
    chat     陪我聊聊（默认/未识别态，零附加）
    analyze  帮我分析（技术/原因分析；联网开启时直接检索，跳过二次判定）
    advise   给我建议（需要建议与方案）
    act      帮我行动（需要可执行的步骤与方案）

词表加载：内置默认词表兜底；模块加载时尝试读同目录 assets/intent_words.json
（{"state": [words]}，<20KB），成功则**合并覆盖**、失败静默用内置 —— 社区可
增补、离线可用；reload_words() 供设置页后续热加载（本期不接 UI）。

路由原则（design-v16 D-V16-04 / 共享知识 20「意图路由三不」）：
    不产生数值（R-A）、不入会话存档、不改变消息必达 ——
    未识别/低置信一律落 "chat"，误判时退化为普通聊天链（无消息黑洞）。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

__all__ = [
    "INTENT_STATES", "DEFAULT_WORDS", "INTENT_HINTS", "classify_intent",
    "detect", "reload_words", "current_words",
]

# 五态全集（chat 为默认/未识别态）
INTENT_STATES = ("confide", "chat", "analyze", "advise", "act")
DEFAULT_STATE = "chat"

# ---------------------------------------------------------------------------
# 内置默认词表（intent_words.json 缺失/脏数据时的兜底，与 JSON 同构）
# ---------------------------------------------------------------------------
DEFAULT_WORDS: Dict[str, List[str]] = {
    "confide": [
        "只想说说", "不需要建议", "别给我建议", "听我说", "我心里难受",
        "很难受", "撑不住", "想哭", "委屈", "难过", "emo", "破防", "崩溃",
        "心事", "烦死了", "心累", "郁闷", "不开心", "想找人说说", "没人懂",
    ],
    "chat": [
        "陪我聊", "聊聊", "在吗", "无聊", "说说话", "闲聊", "讲讲", "尬聊", "解闷",
    ],
    "analyze": [
        "帮我分析", "分析一下", "为什么", "什么原因", "怎么回事", "原理",
        "如何理解", "怎么看", "区别是什么", "优缺点", "对比一下", "排查",
        "报错", "编译", "部署", "算法", "异常", "调试", "怎么解读", "评估一下",
    ],
    "advise": [
        "给我建议", "有什么建议", "应该怎么办", "该怎么办", "怎么选", "推荐",
        "要不要", "值得吗", "方案", "怎么改进", "怎么优化", "有什么办法",
        "怎么解决", "怎么办",
    ],
    "act": [
        "帮我改", "帮我写", "帮我做", "帮我跑", "跑一下", "执行", "写一个",
        "写个", "修复", "重构", "新建", "删除掉", "改一下", "帮我实现",
        "帮我生成", "帮我提交", "打开", "关掉", "运行", "搭建", "配置好",
    ],
}

# 句式正则（词表未命中时的补充判定；逐条 try 编译，脏数据不致崩）
_DEFAULT_PATTERNS: Dict[str, List[str]] = {
    # 倾诉：情绪宣泄句式（第一人称 + 负向感受）
    "confide": [
        r"(我|感觉|觉得).{0,6}(好难过|好累|好烦|好委屈|好想哭|撑不下去|坚持不下)",
        r"(心情|状态).{0,4}(不好|很差|糟糕)",
    ],
    # 分析：疑问句式 + 求解释
    "analyze": [
        r"(什么|为啥|为什么).{0,8}(原因|情况|问题|报错|错误)",
        r"(解释|讲讲|说说).{0,6}(原理|机制|区别|逻辑)",
    ],
    # 行动：祈使句式（帮我/给我 + 动词）
    "act": [
        r"帮我(改|写|做|跑|修|删|建|生成|提交|实现|安装|配置|部署)",
        r"(新建|创建|运行|执行|跑)(一个|一下|起来)?[\u4e00-\u9fa5a-zA-Z0-9_]",
    ],
    # 建议：征求意向句式
    "advise": [
        r"(我该|我该不该|我是不是应该|你觉得).{0,10}(怎么办|怎么选|好不好|行不行)",
        r"(给|求)(点|个|些)?(建议|意见|方案)",
    ],
}

# ---------------------------------------------------------------------------
# 五态语气提示（只附加不接管 —— 经 ChatService 请求级注入基建插入请求副本，
# 绝不写 session.history；chat 态零附加）
# ---------------------------------------------------------------------------
INTENT_HINTS: Dict[str, str] = {
    "confide": (
        "【语气提示】用户此刻需要倾听与共情，不要列解决方案，不要分析对错，"
        "先接住情绪、给到陪伴感，再顺着对方的话轻轻回应。"
    ),
    "analyze": (
        "【语气提示】用户提出了一个想弄明白的问题，请给出有依据、条理清晰的分析，"
        "先给结论再展开，不要空泛铺垫。"
    ),
    "advise": (
        "【语气提示】用户在征求建议，请给出明确、可比较的选项与理由，"
        "直接说你的倾向，不要只罗列可能性不下判断。"
    ),
    "act": (
        "【语气提示】用户需要可执行的步骤与方案，直接给结构化的操作建议，"
        "能动手的部分给出具体命令/代码，不要长篇铺垫。"
    ),
    # chat 态零附加（验收：未识别场景零注入、零打扰）
    "chat": "",
}

# ---------------------------------------------------------------------------
# 词表加载（合并式；逐项 isinstance(list) 守卫，脏数据静默忽略）
# ---------------------------------------------------------------------------
_WORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "assets", "intent_words.json")

_words: Dict[str, List[str]] = {k: list(v) for k, v in DEFAULT_WORDS.items()}
_patterns: Dict[str, List[re.Pattern]] = {}


def _compile_patterns() -> None:
    """把句式正则编译缓存（DEFAULT + JSON 可选扩展 patterns 键）。"""
    _patterns.clear()
    merged = dict(_DEFAULT_PATTERNS)
    if isinstance(_raw_json_data, dict):
        extra = _raw_json_data.get("patterns")
        if isinstance(extra, dict):
            for k, v in extra.items():
                if isinstance(v, list):
                    merged.setdefault(k, []).extend(
                        p for p in v if isinstance(p, str) and p)
    for state, plist in merged.items():
        compiled = []
        for p in plist:
            try:
                compiled.append(re.compile(p))
            except re.error:
                continue
        if compiled:
            _patterns[state] = compiled


_raw_json_data: Optional[dict] = None


def _load_words_file() -> None:
    """读 intent_words.json 合并覆盖内置词表；任何失败静默用内置（离线可用）。"""
    global _raw_json_data, _words
    data = None
    for path in (_WORDS_FILE,):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                break
        except Exception:
            data = None
    # frozen 打包态：get_resource_path 兜底（assets/intent_words.json）
    if data is None:
        try:
            from gui.utils import get_resource_path
            p2 = get_resource_path("assets/intent_words.json")
            if p2 and os.path.exists(p2):
                with open(p2, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            data = None
    _raw_json_data = data if isinstance(data, dict) else None
    merged = {k: list(v) for k, v in DEFAULT_WORDS.items()}
    if isinstance(data, dict):
        for state, words in data.items():
            # 合并覆盖：JSON 词追加到内置词表之后（内置词保留，社区可增补）
            if state in INTENT_STATES and isinstance(words, list):
                extra = [w for w in words if isinstance(w, str) and w.strip()]
                merged[state] = merged.get(state, []) + extra
    _words = merged
    _compile_patterns()


_load_words_file()


def reload_words() -> None:
    """热加载词表（设置页后续接 UI 用；本期仅供测试/社区增补后手动调用）。"""
    _load_words_file()


def current_words() -> Dict[str, List[str]]:
    """当前生效词表的副本（测试/调试用）。"""
    return {k: list(v) for k, v in _words.items()}


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
def _hit_words(text: str, state: str) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in _words.get(state, []))


def _hit_patterns(text: str, state: str) -> bool:
    return any(p.search(text) for p in _patterns.get(state, []))


def classify_intent(text: str, context: Optional[dict] = None) -> str:
    """分类一条用户消息 -> 五态字符串；未识别/空文本恒返 "chat"。

    判定优先级（先 Specific 后泛化，防"帮我分析一下要不要重构"这类复合句误判）：
      1. confide（情绪倾诉 —— 最优先：一旦是倾诉，任何建议/行动语义都让位）
      2. act（祈使行动）
      3. analyze（分析）
      4. advise（建议）
      5. chat（词表命中或默认）

    context: 可选上下文（预留；本期不消费，保持签名稳定）。
    """
    t = (text or "").strip()
    if not t:
        return DEFAULT_STATE
    if _hit_words(t, "confide") or _hit_patterns(t, "confide"):
        return "confide"
    if _hit_words(t, "act") or _hit_patterns(t, "act"):
        return "act"
    if _hit_words(t, "analyze") or _hit_patterns(t, "analyze"):
        return "analyze"
    if _hit_words(t, "advise") or _hit_patterns(t, "advise"):
        return "advise"
    if _hit_words(t, "chat") or _hit_patterns(t, "chat"):
        return "chat"
    return DEFAULT_STATE


# detect：任务面命名（detect(query, context) -> 状态）；与 classify_intent 等价
def detect(query: str, context: Optional[dict] = None) -> str:
    return classify_intent(query, context)
