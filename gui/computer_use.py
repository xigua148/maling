# -*- coding: utf-8 -*-
"""v1.4(B2) ComputerUseController —— GUI 单步操作编排（design-v14 D-V14-11~14）。

**与 Agent（C 线）独立**（D-V14-11）：B2 不申请 agent_authorization_requested，也不复用
`agent_tools.authorize()` 的会话级缓存放行 —— 每次动作都走本控制器自己的**逐次授权增强弹窗**
（AuthorizeActionDialog，仅「允许这一次 / 拒绝」，R-G）。

流程（一次用户请求 → 一次意图 → 一次授权 → 一次执行）：
1. 取帧：看屏开启 → 复用最近帧；未开 → 一次性显式抓帧（用户触发，内存即弃，R-E 例外）；
2. 意图产出：VisionQueryWorker（后台线程，非流式）把 帧 + 用户原话 交给视觉模型，
   只回严格 JSON 动作意图；不使用 function calling（兼容面大，design §8.4）；
3. 解析校验：type ∈ 白名单 + 坐标/文本/键合法；置信 <0.55 或非法 → **先问不乱点**，
   发授权、不执行（气泡说明，结束）；
4. 逐次授权：区域缩略截图 + 动作 + type 明文预览 + 敏感红字 → 仅「允许这一次 / 拒绝」；
   拒绝 → 尊重结果，不重试不强推；
5. 执行：坐标 = 图像像素 → 逻辑虚拟桌面 → 命中屏 DPR → 物理像素（input_sim 单点换算），
   ctypes 注入；mock/日志桩可注入 executor 验证调用序列；
6. 反馈：成功/失败/拒绝均以 ChatService.screen_bubble 一条对话气泡呈现
   （scene=screen_action）；不做任何键鼠记录/输入日志。

守卫/降级（design §2.5）：无视觉模型/API 失败 → 可读气泡不执行；ctypes 异常 → 气泡不执行；
hotkey/type 白名单外 → 拒绝；低置信不执行。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from gui.qt_compat import QObject, Signal

logger = logging.getLogger("maid_coder.gui.computer_use")

APP_CTX_KEY = "computer_use"

#: 低置信阈值（低于此不执行，先问）
CONFIDENCE_FLOOR = 0.55


def get_computer_use_controller(app_ctx):
    """app 级 ComputerUseController 取/建（chat_panel 复用同一实例）。"""
    if app_ctx is None:
        return None
    ctrl = getattr(app_ctx, APP_CTX_KEY, None)
    if ctrl is None:
        try:
            ctrl = ComputerUseController(app_ctx)
            setattr(app_ctx, APP_CTX_KEY, ctrl)
        except Exception as exc:
            logger.warning("ComputerUseController 初始化失败: %s", exc)
            return None
    return ctrl


class ComputerUseController(QObject):
    """GUI 单步操作控制器（无 LLM 时拒绝执行；可离线 mock executor 单测）。"""

    #: 忙碌变化（处理动作意图期间 True）
    busy_changed = Signal(bool)

    def __init__(self, app_ctx, parent: Optional[QObject] = None, executor=None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        from gui.input_sim import NativeInputSimulator
        self._executor = executor if executor is not None else NativeInputSimulator()
        self._busy = False
        self._worker = None
        self._pending = {}   # 当前动作上下文（帧 meta/坐标换算参数）

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def is_busy(self) -> bool:
        return self._busy

    def handle_request(self, user_text: str, parent_widget=None) -> bool:
        """接收一条「动作意图」请求（用户手动触发 / 屏幕理解建议），进入处理。"""
        text = (user_text or "").strip()
        if not text:
            return False
        if self._busy:
            self._bubble("码铃还在处理上一个操作，稍等再试一下？", "screen_action")
            return False
        # 视觉前提：启发式纯文本模型 → 可读引导，不执行（D-V14-08 不静默失败）
        try:
            from gui.vision_support import ensure_vision_model_hint
            hint = ensure_vision_model_hint(self._app_ctx)
            if hint:
                self._bubble(hint, "screen_action")
                return False
        except Exception:
            pass
        frame = self._acquire_frame()
        if frame is None:
            self._bubble("没法获取当前屏幕的画面，操作先停一下（稍后再试）。", "screen_action")
            return False
        uri, meta = frame
        self._pending = {"uri": uri, "meta": meta}
        self._launch_intent(text, uri)
        return True

    # ------------------------------------------------------------------
    # 内部：意图产出
    # ------------------------------------------------------------------
    def _launch_intent(self, user_text: str, uri: str) -> None:
        api = getattr(self._app_ctx, "api", None)
        if api is None:
            self._bubble("API 服务尚未就绪，无法理解屏幕内容。", "screen_action")
            return
        try:
            from gui.vision_support import (
                INTENT_SYSTEM_PROMPT, build_vision_messages, VisionQueryWorker,
            )
        except Exception as exc:
            logger.warning("vision_support 不可用: %s", exc)
            self._bubble("屏幕理解组件暂不可用，请稍后再试。", "screen_action")
            return
        messages = build_vision_messages(
            INTENT_SYSTEM_PROMPT,
            "用户想做的操作：「%s」\n请按系统要求只输出一个动作意图 JSON。" % (user_text[:400]),
            uri,
        )
        worker = VisionQueryWorker(api, messages, temperature=0.0, max_tokens=200, parent=self)
        self._busy = True
        try:
            self.busy_changed.emit(True)
        except Exception:
            pass
        worker.succeeded.connect(self._on_intent_ready)
        worker.failed.connect(self._on_intent_failed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_intent_ready(self, text: str, usage: dict) -> None:
        self._busy = False
        try:
            self.busy_changed.emit(False)
        except Exception:
            pass
        self._worker = None
        try:
            from gui.vision_support import VisionQueryWorker
            action = VisionQueryWorker.parse_intent(text)
        except Exception:
            action = None
        if action is None:
            self._bubble("码铃没想清楚要点的位置… 能再说具体些吗？（比如「点右上角的确定」）",
                         "screen_action")
            return
        try:
            confidence = float(action.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < CONFIDENCE_FLOOR:
            self._bubble("码铃不太确定要点哪 / 填什么（置信度有点低），先不动手，你再说具体些？",
                         "screen_action")
            return
        self._route_action(action)

    def _on_intent_failed(self, err: str) -> None:
        self._busy = False
        try:
            self.busy_changed.emit(False)
        except Exception:
            pass
        self._worker = None
        self._bubble(f"{err}\n\n（看屏 / 操作需要支持视觉的模型，可在设置里切换）", "screen_action")

    # ------------------------------------------------------------------
    # 内部：授权 + 执行
    # ------------------------------------------------------------------
    def _route_action(self, action: dict) -> None:
        uri = self._pending.get("uri")
        meta = self._pending.get("meta") or {}
        vr = meta.get("virtual") or {}
        img_w = int(meta.get("img_w") or 0)
        img_h = int(meta.get("img_h") or 0)
        geos = meta.get("geo") or []

        atype = action.get("type")
        # 点击类：图像像素 → 逻辑虚拟桌面
        action["x_img"] = action.get("x")
        action["y_img"] = action.get("y")
        if atype in ("click", "double_click", "right_click"):
            if img_w <= 0 or img_h <= 0 or not vr:
                self._bubble("屏幕几何信息缺失，无法换算点击位置。", "screen_action")
                return
            try:
                from gui.input_sim import image_to_logical
                lx, ly = image_to_logical(
                    vr.get("x", 0), vr.get("y", 0), vr.get("w", 0), vr.get("h", 0),
                    img_w, img_h, action["x_img"], action["y_img"],
                )
            except Exception:
                self._bubble("点击位置换算失败，操作取消。", "screen_action")
                return
            action["x"] = int(round(lx))
            action["y"] = int(round(ly))
        elif atype == "hotkey" and not action.get("keys"):
            self._bubble("快捷键为空，操作取消。", "screen_action")
            return
        elif atype == "type" and not action.get("text"):
            self._bubble("要输入的文本为空，操作取消。", "screen_action")
            return

        # 授权弹窗（逐次；仅这一次 / 拒绝）
        preview = self._make_preview(uri, action.get("x_img"), action.get("y_img"))
        from gui.widgets.authorize_action_dialog import AuthorizeActionDialog
        dlg = AuthorizeActionDialog(action, preview)
        if dlg.exec_() != AuthorizeActionDialog.Accepted:
            self._bubble("好的，码铃不动啦～", "screen_action")
            return
        # 授权通过 → 执行（物理像素换算 + ctypes 注入）
        try:
            if atype in ("click", "double_click", "right_click"):
                self._exec_click(action, geos)
            elif atype == "type":
                self._exec_type(action)
            elif atype == "hotkey":
                self._exec_hotkey(action)
            else:
                self._bubble(f"不支持的动作类型：{atype}", "screen_action")
        except Exception as exc:
            logger.warning("computer_use 执行失败: %s", exc)
            self._bubble(f"操作没能执行：{exc}", "screen_action")

    def _exec_click(self, action: dict, geos: list) -> None:
        from gui.input_sim import logical_to_physical
        phys = logical_to_physical(geos, action["x"], action["y"])
        if phys is None:
            self._bubble("目标点不在任何可用屏幕上，没有执行。", "screen_action")
            return
        px, py = phys
        desc = (action.get("description") or "").strip()
        if action.get("type") == "double_click":
            ok = self._executor.click(px, py, double=True)
            verb = "双击"
        elif action.get("type") == "right_click":
            ok = self._executor.click(px, py, right=True)
            verb = "右键点"
        else:
            ok = self._executor.click(px, py)
            verb = "点了"
        where = f"『{desc}』" if desc else ""
        if ok:
            self._bubble(f"已{verb} ({action['x']}, {action['y']}) 的{where}（仅这一次）", "screen_action")
        else:
            self._bubble("操作执行失败（当前环境可能不允许键鼠注入）。", "screen_action")

    def _exec_type(self, action: dict) -> None:
        text = action.get("text") or ""
        ok = self._executor.type_text(text)
        if ok:
            preview = (text[:20] + "…") if len(text) > 20 else text
            self._bubble(f"已输入「{preview}」（仅这一次）", "screen_action")
        else:
            self._bubble("输入执行失败（当前环境可能不允许键鼠注入）。", "screen_action")

    def _exec_hotkey(self, action: dict) -> None:
        keys = action.get("keys") or []
        ok = self._executor.hotkey(keys)
        if ok:
            self._bubble("已按下 " + " + ".join(str(k) for k in keys), "screen_action")
        else:
            self._bubble("快捷键执行失败（当前环境可能不允许键鼠注入）。", "screen_action")

    # ------------------------------------------------------------------
    # 内部：取帧 / 预览 / 反馈
    # ------------------------------------------------------------------
    def _acquire_frame(self):
        """取当前帧：看屏开启 → 复用最近帧；未开 → 一次性显式抓帧（内存即弃）。"""
        watch = getattr(self._app_ctx, "screen_watch", None)
        if watch is not None:
            try:
                if watch.is_running():
                    uri = watch.latest_frame_data_uri()
                    if uri:
                        return uri, watch.latest_frame_meta()
            except Exception:
                pass
        # 一次性显式抓帧（R-E 例外：用户触发的即时帧，不进持续采集）
        try:
            from gui.screen_grab import grab_virtual_desktop, pixmap_to_data_uri
            result = grab_virtual_desktop()
            if not result.ok or result.pixmap is None or result.pixmap.isNull():
                return None
            uri = pixmap_to_data_uri(result.pixmap)
            if not uri:
                return None
            vr = result.virtual_rect
            meta = {
                "virtual": {"x": vr.x(), "y": vr.y(), "w": vr.width(), "h": vr.height()},
                "img_w": result.image_width,
                "img_h": result.image_height,
                "dpr": result.dpr,
                "geo": result.screen_geos,
                "ts": time.time(),
            }
            return uri, meta
        except Exception as exc:
            logger.warning("computer_use 即时抓帧失败: %s", exc)
            return None

    def _make_preview(self, uri: Optional[str], x_img=None, y_img=None):
        """从帧 data URI 解码 → 以 (x_img,y_img) 为中心裁一块缩略图（失败空 QPixmap）。"""
        try:
            if not uri or x_img is None or y_img is None:
                return None
            import base64
            _, _, b64 = uri.partition(",")
            raw = base64.b64decode(b64) if b64 else b""
            if not raw:
                return None
            from PySide6.QtGui import QImage, QPixmap
            img = QImage.fromData(raw)
            if img is None or img.isNull():
                return None
            pm = QPixmap.fromImage(img)
            from gui.screen_grab import crop_region
            return crop_region(pm, int(x_img), int(y_img), 280, 180)
        except Exception as exc:
            logger.debug("授权预览图生成失败: %s", exc)
            return None

    def _bubble(self, text: str, scene: str = "screen_action") -> None:
        chat_service = getattr(self._app_ctx, "chat_service", None)
        if chat_service is None:
            logger.info("[screen_bubble][%s] %s", scene, text)
            return
        try:
            if not chat_service.screen_bubble(text, scene):
                logger.info("[screen_bubble][%s] 投递失败: %s", scene, text)
        except Exception as exc:
            logger.warning("screen_bubble 失败: %s", exc)
