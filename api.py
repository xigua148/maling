from __future__ import annotations

import json
import logging
from typing import Callable, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core import AppConfig

class APIClient:
    """封装 DeepSeek API 调用，内置指数退避重试。"""

    def __init__(self, cfg: AppConfig, logger: logging.Logger):
        self.cfg = cfg
        self.logger = logger
        self._session = requests.Session()
        retry = Retry(
            total=cfg.api_retry_times,
            backoff_factor=1,
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        # P2-20: 多 API Key 轮换
        keys = cfg.api_keys if cfg.api_keys else ([cfg.api_key] if cfg.api_key else [])
        self._key_rotator = APIKeyRotator(keys)
        # v1.2.x(token): chat_stream_chunks 逐 chunk 解析到的 usage 暂存于此，
        # 供调用方在流结束后读取（OpenAI 兼容流式末块携带 usage）。
        self._last_stream_usage: Optional[dict] = None

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._key_rotator.current_key}",
            "Content-Type": "application/json",
        }

    def chat(
        self,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        tools: Optional[List[dict]] = None,
        use_reasoning: bool = False,
    ) -> dict:
        payload: dict = {
            "model": self.cfg.api_model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.api_max_tokens,
            "stream": stream,
            "temperature": temperature if temperature is not None else self.cfg.api_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        # v10.8: reasoning_effort / extra_body thinking 为 DeepSeek 专属参数，
        # 其他厂商一律不带，避免换厂商后因不识别字段而报错
        if use_reasoning and getattr(self.cfg, "api_provider", "deepseek") == "deepseek":
            payload["reasoning_effort"] = "high"
            payload["extra_body"] = {"thinking": {"type": "enabled"}}

        self.logger.debug("API 请求 payload: %s", json.dumps(payload, ensure_ascii=False, indent=2))

        last_err = None
        for attempt in range(max(1, len(self._key_rotator.keys))):
            try:
                resp = self._session.post(
                    self.cfg.api_url,
                    json=payload,
                    headers=self._headers(),
                    timeout=(10, 60),
                )
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403, 429):
                    self._key_rotator.mark_failed(self._key_rotator.current_key)
                    self._key_rotator.rotate()
                    last_err = e
                    continue
                if e.response is not None:
                    raise RuntimeError(f"API HTTP 错误 {e.response.status_code}: {e.response.text}") from e
                raise RuntimeError(f"API HTTP 错误: {e}") from e
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"API 请求失败: {e}") from e
        raise RuntimeError(f"所有 API Key 均已失效 ({len(self._key_rotator.keys)} 个): {last_err}")

    def chat_stream_chunks(
        self,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_response: Optional[Callable[[object], None]] = None,
    ):
        """v10.15: GUI 真流式专用 —— 逐 chunk yield 内容增量。

        与 chat_stream() 的区别：
        - chat_stream() 阻塞到全部接收完才返回整段文本（CLI 打印场景够用，
          GUI 伪流式的根源）；
        - 本方法是生成器，每收到一个 SSE content delta 就立即 yield，
          首字延迟 ≈ 服务端首包延迟。

        协作取消：cancel_check 返回 True 时关闭底层连接并抛出
        StreamCancelled（终止而非装作完成）；on_response 把响应对象
        交给调用方，便于从其他线程 close() 硬中断。
        """
        payload: dict = {
            "model": self.cfg.api_model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.api_max_tokens,
            "stream": True,
            "temperature": temperature if temperature is not None else self.cfg.api_temperature,
        }
        resp = None
        last_err = None
        for attempt in range(max(1, len(self._key_rotator.keys))):
            try:
                resp = self._session.post(
                    self.cfg.api_url,
                    json=payload,
                    headers=self._headers(),
                    timeout=(10, 60),
                    stream=True,
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403, 429):
                    self._key_rotator.mark_failed(self._key_rotator.current_key)
                    self._key_rotator.rotate()
                    last_err = e
                    continue
                raise RuntimeError(f"流式 API HTTP 错误: {e}") from e
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"流式 API 请求失败: {e}") from e
        else:
            raise RuntimeError(f"所有 API Key 均已失效 ({len(self._key_rotator.keys)} 个): {last_err}")

        if on_response is not None:
            try:
                on_response(resp)
            except Exception:
                pass

        self._last_stream_usage = None  # 本轮流式开始，重置上一轮用量
        try:
            for line in resp.iter_lines():
                if cancel_check is not None and cancel_check():
                    raise StreamCancelled()
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data = line_str[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        # OpenAI 兼容流式在最后一帧携带 usage（total_tokens 等）
                        if isinstance(chunk, dict) and isinstance(chunk.get("usage"), dict):
                            self._last_stream_usage = chunk["usage"]
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"流式 API 请求失败: {e}") from e
        finally:
            try:
                resp.close()
            except Exception:
                pass


    def chat_stream(
        self,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[List[dict]] = None,
        use_reasoning: bool = False,
    ) -> "Tuple[str, Optional[List[dict]], Optional[dict]]":
        """兼容性非流式入口（保留旧调用方不变）。

        内部委托 chat_stream_with_tools() 生成器，累积全部内容后返回
        (full_content, tool_calls_or_None, usage_or_None) 三元组。
        """
        full_content = ""
        gen = self.chat_stream_with_tools(
            messages, max_tokens=max_tokens, temperature=temperature,
            tools=tools, use_reasoning=use_reasoning,
        )
        for delta in gen:
            full_content += delta
        assembled = self._last_stream_tool_calls if self._last_stream_tool_calls else None
        return full_content, assembled, self._last_stream_usage

    def chat_stream_with_tools(
        self,
        messages: List[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        tools: Optional[List[dict]] = None,
        use_reasoning: bool = False,
    ):
        """v1.4.7: Agent 流式工具循环专用生成器。

        逐 chunk yield content delta（便于 GUI 实时渲染），
        同时内部收集 tool_calls 和 usage。
        迭代结束后读取：
        - self._last_stream_tool_calls  组装好的 tool_calls 列表（无则为空 list）
        - self._last_stream_usage       usage 字典（无则为 None）
        """
        payload: dict = {
            "model": self.cfg.api_model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.api_max_tokens,
            "stream": True,
            "temperature": temperature if temperature is not None else self.cfg.api_temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if use_reasoning and getattr(self.cfg, "api_provider", "deepseek") == "deepseek":
            payload["reasoning_effort"] = "high"
            payload["extra_body"] = {"thinking": {"type": "enabled"}}

        self._last_stream_usage = None
        self._last_stream_tool_calls = []
        tool_calls_buffer: Dict[int, dict] = {}
        has_tool_calls = False

        last_err = None
        resp = None
        for attempt in range(max(1, len(self._key_rotator.keys))):
            try:
                resp = self._session.post(
                    self.cfg.api_url,
                    json=payload,
                    headers=self._headers(),
                    timeout=(10, 60),
                    stream=True,
                )
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code in (401, 403, 429):
                    self._key_rotator.mark_failed(self._key_rotator.current_key)
                    self._key_rotator.rotate()
                    last_err = e
                    continue
                raise RuntimeError(f"流式 API HTTP 错误: {e}") from e
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"流式 API 请求失败: {e}") from e
        else:
            raise RuntimeError(f"所有 API Key 均已失效 ({len(self._key_rotator.keys)} 个): {last_err}")

        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data = line_str[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})

                        delta_tool_calls = delta.get("tool_calls")
                        if delta_tool_calls:
                            has_tool_calls = True
                            for tc in delta_tool_calls:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_buffer:
                                    tool_calls_buffer[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if tc.get("id"):
                                    tool_calls_buffer[idx]["id"] = tc["id"]
                                func_delta = tc.get("function", {})
                                if func_delta.get("name"):
                                    tool_calls_buffer[idx]["function"]["name"] = func_delta["name"]
                                if func_delta.get("arguments"):
                                    tool_calls_buffer[idx]["function"]["arguments"] += func_delta["arguments"]
                            continue

                        if not has_tool_calls:
                            content = delta.get("content", "")
                            if content:
                                yield content

                        if "usage" in chunk and chunk["usage"]:
                            self._last_stream_usage = chunk["usage"]
                    except json.JSONDecodeError:
                        continue

            if has_tool_calls:
                self._last_stream_tool_calls = [
                    tool_calls_buffer[i] for i in sorted(tool_calls_buffer.keys())
                ]
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"流式 API 请求失败: {e}") from e


class StreamCancelled(Exception):
    """v10.15: 用户主动取消流式请求（请求被真正中断，非播放停止）。"""


# ---------------------------------------------------------------------------
# 提示词管理
class APIKeyRotator:
    """P2-20: 多 API Key 轮换管理。"""
    def __init__(self, keys: List[str]):
        self.keys = [k.strip() for k in keys if k.strip()]
        self.current_idx = 0
        self.failed_keys: set = set()

    @property
    def current_key(self) -> str:
        if not self.keys:
            return ""
        # 跳过已失效的 key
        for _ in range(len(self.keys)):
            key = self.keys[self.current_idx % len(self.keys)]
            if key not in self.failed_keys:
                return key
            self.current_idx += 1
        return self.keys[0]  # 全部失效时返回第一个

    def mark_failed(self, key: str) -> None:
        self.failed_keys.add(key)
        if len(self.failed_keys) >= len(self.keys):
            self.failed_keys.clear()  # 全部失效后重置

    def rotate(self) -> str:
        self.current_idx = (self.current_idx + 1) % max(1, len(self.keys))
        return self.current_key


# 主循环
# ---------------------------------------------------------------------------
