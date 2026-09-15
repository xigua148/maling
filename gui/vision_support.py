# -*- coding: utf-8 -*-
"""v1.4(B0) 视觉模型前提与降级 —— 启发式探测 + 引导文案 + 视觉小调用 worker。

（design-v14 D-V14-08 / §5 B0，design-v14 共享知识 25）

设计口径：
- 视觉前提为 **best-effort 启发式**，非权威；权威仍以 API 实际回包为准
  （v1.2.2 既有可读报错兜底保留，任何路径不静默失败）；
- `heuristic_supports_vision(model_name)`：命中视觉标记 → True；命中已知纯文本厂商
  （DeepSeek 官方纯文本）→ False；其余不确定 → None；
- `vision_guidance_text()`：复用 README 既有多厂商视觉端点口径
  （智谱 GLM / 通义 qwen-vl / OpenAI；deepseek-flash（V4.1）原生多模态已纳入识别）；
- `VisionQueryWorker`：B1 高价值分类 / B2 动作意图的**后台视觉小调用**
  （QThread，OpenAI 兼容多模态 content 直传 data URI，非流式），worker + 超时天然可取消；
- 分类系统提示词只让模型回严格 JSON，便于低成本解析（宁可少提示不可漏报错，
  漏报由「看一帧/按屏提问」人工兜底）。
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from gui.qt_compat import Signal
from gui.qt_exit_guard import ExitSafeQThread

logger = logging.getLogger("maid_coder.gui.vision_support")

#: 模型名里命中即判「很可能支持视觉」的标记（小写包含匹配）
_VISION_MARKERS = (
    "4v", "vl", "vision", "gpt-4o", "gpt-4.1", "gpt-5", "gpt-6", "gemini", "claude",
    "qwen-vl", "glm-4v", "internvl", "minicpm", "llava", "kosmos", "fuyu",
    "qwen2.5-vl", "phi-3.5-vision",
    # v1.7.3 起新一批「名字里没有 vision/vl 字样但官方确认原生多模态」的型号：
    # deepseek-flash(V4.1) / glm-5.3-flash / kimi-k3 系 / qwen3.8-max、qwen3.7-plus
    # ——必须先于下面 _TEXT_MARKERS 的 "deepseek"/"kimi" 前缀判断，否则会被误判纯文本。
    "deepseek-flash", "glm-5.3-flash", "kimi-k3", "kimi-k2.6", "kimi-k2.5",
    "qwen3.8-max", "qwen3.7-plus",
)
#: 命中即判「官方已知纯文本」的标记（需在视觉标记之后判断，防止 vision-exp 被误杀）
_TEXT_MARKERS = ("deepseek", "deepseek-chat", "deepseek-reasoner", "kimi", "glm-4-flash", "glm-4-air")

#: 高价值事件分类 system（只回 JSON）
CLASSIFY_SYSTEM_PROMPT = (
    "你是屏幕异常检测助手。请判断这张屏幕截图里是否出现**明显需要用户注意的报错/崩溃/异常**："
    "报错对话框、程序崩溃窗口、蓝屏、错误提示弹窗、磁盘/权限类严重警告等。"
    "普通窗口、正常运行的应用、网页内容都不算异常。"
    "只输出一行 JSON，不要任何解释：{\"anomaly\": true|false, \"summary\": \"异常的一句话中文摘要\"}"
)
#: 高价值事件判定「异常」的最低置信提示词标记：summary 非空即可用（模型已收敛到 yes/no）
_HIGH_VALUE_OK_MARKERS = ("yes", "是", "true", "异常", "报错", "崩溃", "错误", "警告")

#: B2 动作意图 system（只回 JSON；坐标以图片像素为准）
INTENT_SYSTEM_PROMPT = (
    "你是 GUI 操作意图解析器。用户会描述他想在这张屏幕截图上做的操作，"
    "你需要把操作翻译成严格的 JSON。坐标 (x,y) 必须是**这张图片自身的像素坐标**。"
    "可用动作：click（单击）、double_click（双击）、right_click（右键）、type（输入文字）、"
    "hotkey（快捷键，keys 形如 [\"ctrl\",\"s\"]）。"
    "只输出一行 JSON："
    "{\"type\":\"click\",\"description\":\"中文一句话说明点哪里\",\"x\":100,\"y\":200,"
    "\"text\":\"type 才需要\",\"keys\":[\"ctrl\",\"s\"],\"confidence\":0.9}\n"
    "规则：只有明确知道点哪里才填坐标与高置信(≥0.55)；不确定就把 confidence 降到 0.5 以下，"
    "不要瞎猜坐标；不做任何键鼠输入，只输出意图。"
)

_INTENT_ACTION_WHITELIST = ("click", "double_click", "right_click", "type", "hotkey")


def heuristic_supports_vision(model_name: Optional[str]) -> Optional[bool]:
    """模型名启发式：视觉标记→True；已知纯文本→False；其余→None（不确定，允许开启）。"""
    name = (model_name or "").strip().lower()
    if not name:
        return None
    if any(m in name for m in _VISION_MARKERS):
        return True
    # 官方 deepseek-v4-flash-vision-exp 含 vision，已被上面命中；纯文本分支随后
    if any(m in name for m in _TEXT_MARKERS):
        return False
    return None


def current_model_name(app_ctx) -> str:
    """读取当前生效模型名（AppConfig.api_model）；无则空串。"""
    cfg = getattr(app_ctx, "cfg", None)
    if cfg is None:
        return ""
    try:
        return str(getattr(cfg, "api_model", "") or "").strip()
    except Exception:
        return ""


def current_vision_support(app_ctx) -> Optional[bool]:
    """当前模型视觉支持启发式（None=不确定；权威以 API 实际回包为准）。"""
    return heuristic_supports_vision(current_model_name(app_ctx))


def vision_guidance_text() -> str:
    """开启看屏/操作前给用户的视觉模型引导文案（与 README「AI 看图」口径一致）。"""
    return (
        "看屏与操作都需要支持视觉的多模态模型（OpenAI 兼容端点发图）。\n"
        "示例可用模型：\n"
        "· 智谱 GLM（glm-5.3-flash 原生多模态；glm-4v-flash 有免费额度，最易上手）\n"
        "· 阿里通义 qwen-vl（qwen-vl-plus / qwen-vl-max）\n"
        "· OpenAI（gpt-5.6-terra / gpt-6-astra）\n"
        "DeepSeek 官方 deepseek-flash（V4.1-Flash）已原生支持看图；"
        "若你配置的是纯文本型号（如 deepseek-v4-pro），请改用 vision 型号"
        "（如 deepseek-flash、qwen-vl 系、glm-5.3-flash 等）。\n"
        "请在「设置 → 模型与接口」切换支持视觉的模型后再试。"
    )


def ensure_vision_model_hint(app_ctx) -> Optional[str]:
    """模型非视觉时给一句可读提示；视觉/不确定返回 None。

    返回 None 表示可以继续（含不确定情形，防启发式误杀自定义视觉模型）；否则返回提示文案。
    """
    support = current_vision_support(app_ctx)
    if support is False:
        return (
            "当前模型看起来是纯文本模型，大概率不支持看图/看屏。\n\n"
            + vision_guidance_text()
        )
    return None


def build_vision_messages(
    system: str, user_text: str, image_uri: Optional[str],
) -> List[dict]:
    """组装 OpenAI 兼容多模态 content（图片 data URI 直传）。"""
    if not image_uri:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ]
    content_parts = [{"type": "text", "text": user_text or ""}]
    content_parts.append({"type": "image_url", "image_url": {"url": image_uri}})
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content_parts},
    ]


class VisionQueryWorker(ExitSafeQThread):
    """一次后台视觉小调用（QThread，非流式；供 B1 分类 / B2 意图复用）。

    succeeded(str text, dict usage) / failed(str error)。

    退出自我收口（继承 :class:`gui.qt_exit_guard.ExitSafeQThread`）：本 worker 由
    ``ScreenWatchService._classify_worker`` / ``ComputerUseController._worker`` 以
    ``parent=承载对象`` 持有；若退出时网络调用仍在进行，父对象析构会**连坐析构仍在运行
    的 ``QThread``** → ``0xC0000409`` fail-fast。基类自挂 ``aboutToQuit`` + 父控件
    ``destroyed`` → 幂等有界 ``stop()``；超时则 detach + 强引用（对齐 kb_worker 取舍）。
    """

    succeeded = Signal(str, dict)
    failed = Signal(str)

    def __init__(self, api, messages: List[dict], temperature: float = 0.1,
                 max_tokens: int = 320, parent=None):
        super().__init__(parent)
        self._api = api
        self._messages = messages
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)

    def run(self) -> None:  # noqa: D102
        try:
            cfg = getattr(self._api, "cfg", None)
            max_tokens = self._max_tokens or int(getattr(cfg, "api_max_tokens", 512) or 512)
            resp = self._api.chat(
                self._messages,
                max_tokens=max_tokens,
                temperature=self._temperature,
                stream=False,
            )
            try:
                text = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
            except Exception:
                text = ""
            usage = resp.get("usage") or {}
            if not (text or "").strip():
                self.failed.emit("视觉模型没有返回内容，请确认模型支持图片输入。")
                return
            self.succeeded.emit(str(text), usage if isinstance(usage, dict) else {})
        except Exception as exc:  # noqa: BLE001
            err = f"视觉分析请求失败：{exc}"
            logger.info("VisionQueryWorker 失败: %s", exc)
            self.failed.emit(err)

    # ------------------------------------------------------------------
    # 便捷工具（供调用方解析/判定）
    # ------------------------------------------------------------------
    @staticmethod
    def parse_high_value(text: str) -> Optional[dict]:
        """解析分类 JSON → {anomaly: bool, summary: str}；异常判定带启发式兜底。"""
        if not text:
            return None
        try:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
            data = json.loads(text)
        except Exception:
            # 模型未严格回 JSON：降级按关键词粗判
            lower = (text or "").lower()
            anomaly = any(m in text for m in _HIGH_VALUE_OK_MARKERS)
            return {"anomaly": bool(anomaly and not _looks_negative(text)), "summary": text.strip()[:120]}
        if not isinstance(data, dict):
            return None
        summary = str(data.get("summary") or "").strip()
        anomaly = bool(data.get("anomaly"))
        # 负向句兜底：即使模型说 anomaly=true 但摘要为明确否定也视为无异常（少打扰）
        if anomaly and summary and _looks_negative(summary):
            anomaly = False
        return {"anomaly": anomaly, "summary": summary or text.strip()[:120]}

    @staticmethod
    def parse_intent(text: str) -> Optional[dict]:
        """解析 B2 动作意图 JSON → 动作 dict；非法/非白名单返回 None。"""
        if not text:
            return None
        try:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
            data = json.loads(text)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        atype = str(data.get("type") or "").strip()
        if atype not in _INTENT_ACTION_WHITELIST:
            return None
        try:
            confidence = float(data.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        action = {
            "type": atype,
            "description": str(data.get("description") or "")[:200],
            "confidence": confidence,
        }
        if atype in ("click", "double_click", "right_click"):
            try:
                action["x"] = int(data.get("x"))
                action["y"] = int(data.get("y"))
            except (TypeError, ValueError):
                return None  # 缺坐标的点击意图直接判非法（先问不乱点）
        if atype == "type":
            action["text"] = str(data.get("text") or "")
        if atype == "hotkey":
            keys = data.get("keys")
            if isinstance(keys, list):
                action["keys"] = [str(k).strip().lower() for k in keys if str(k).strip()]
            else:
                return None
        return action


def _looks_negative(text: str) -> bool:
    """是否像「没有异常/正常」的负向句（少打扰兜底）。"""
    t = (text or "").strip().lower()
    neg = ("无异常", "正常", "未发现", "没有异常", "没有发现", "none", "no anomaly",
           "not an error", "fine", "ok", "正常现象", "不是错误", "未见")
    return any(k in t for k in neg)
