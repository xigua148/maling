# -*- coding: utf-8 -*-
"""v1.4(B1a) ScreenWatchService —— 持续看屏核心服务（design-v14 D-V14-07/09/10）。

纯服务、无 UI：周期采集 → 内存 JPEG data URI 帧 → 显著变化触发 → 高价值分类节流 →
帧计数 / token 累计 / 单会话帧上限自停。UI（screen_watch_bar / chat_panel）订阅信号渲染。

红线落点（design-v14 §9 / R-B / R-E / R-G）：
- **只在你显式开启（start）时采集**：关停/达限/退出三路径即停并置空内存帧；
- 帧仅内存 data URI，**不落盘 / 不进历史 / 不写日志**（三路径弃帧断言）——唯一日志是帧号与
  状态变化等元信息，绝不写图像字节；
- 不做任何行为统计、不留时间轴、不产出报告；只答「当下这一帧」；
- 高价值分类（显著变化帧）最低间隔 90s；主动提示节流 ≤1 条/30min（内存时间戳）+ 可关
  （screen_watch_notice_enabled）。

配置读取一律 getattr(config, key, default) 容错（V-1.4-0 完成前默认值生效，完成后即真值）：
- screen_watch_enabled(False) / screen_watch_interval_s|_sec(30) /
  screen_watch_change_threshold|_ratio(0.04) / screen_watch_frame_limit|_max_frames(200) /
  screen_watch_notice_enabled(True)

坐标口径：CaptureResult.virtual_rect（逻辑虚拟桌面）+ 帧图物理像素宽 img_w ↔ 逻辑宽
vr.width() 的等比关系 = 图上坐标换算依据（design-v14 共享知识 22）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Callable, Optional

from gui.qt_compat import QObject, QTimer, Signal

logger = logging.getLogger("maid_coder.gui.screen_watch")

# ---------------------------------------------------------------------------
# 配置键（V-1.4-0 前的别名容错：design §4.1 命名优先，附 task 别名）
# ---------------------------------------------------------------------------
SW_KEYS = {
    "enabled": ("screen_watch_enabled",),
    "interval": ("screen_watch_interval_s", "screen_watch_interval_sec"),
    "threshold": ("screen_watch_change_threshold", "screen_watch_change_ratio"),
    "frame_limit": ("screen_watch_frame_limit", "screen_watch_max_frames"),
    "notice": ("screen_watch_notice_enabled",),
}

#: 默认常量（getattr 兜底）
DEFAULT_INTERVAL_S = 30
DEFAULT_CHANGE_RATIO = 0.04
DEFAULT_FRAME_LIMIT = 200
DEFAULT_NOTICE_ENABLED = True
#: 高价值显著帧「分类」最小间隔（秒）—— 宁可少提示不可漏报错（design-v14 §8.5）
CLASSIFY_MIN_GAP_S = 90.0
#: 主动提示节流（秒）：≤1 条/30min（R-C）
NOTICE_MIN_GAP_S = 1800.0

#: ScreenWatchService 在 app_ctx 上的挂载键（chat_panel / main(V-1.4-0) 共用同一实例）
APP_CTX_KEY = "screen_watch"


def _cfg_read(cfg, aliases, default):
    """按别名优先级读配置；无 config 或全缺 → default。"""
    if cfg is None:
        return default
    for key in aliases:
        if hasattr(cfg, key):
            try:
                return getattr(cfg, key)
            except Exception:
                continue
    return default


def read_sw(cfg, name: str, default):
    """对外读屏配置（chat_panel / page_settings 复用）。"""
    aliases = SW_KEYS.get(name)
    if not aliases:
        return default
    return _cfg_read(cfg, aliases, default)


def write_sw(cfg, name: str, value) -> None:
    """对外写屏配置：写入全部别名 + save()（V-1.4-0 前字段缺省仅运行态；完成后真落盘）。

    不直接改 gui/config.py（汇交点文件 V-1.4-0 预编，B 线只读）。
    """
    if cfg is None:
        return
    aliases = SW_KEYS.get(name) or (name,)
    for key in aliases:
        try:
            setattr(cfg, key, value)
        except Exception:
            continue
    try:
        cfg.save()
    except Exception:
        pass


def _sw_interval(cfg) -> int:
    v = read_sw(cfg, "interval", DEFAULT_INTERVAL_S)
    try:
        v = max(3, int(v))
    except (TypeError, ValueError):
        v = DEFAULT_INTERVAL_S
    return v


def _sw_threshold(cfg) -> float:
    v = read_sw(cfg, "threshold", DEFAULT_CHANGE_RATIO)
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = DEFAULT_CHANGE_RATIO
    return max(0.001, min(1.0, v))


def _sw_frame_limit(cfg) -> int:
    v = read_sw(cfg, "frame_limit", DEFAULT_FRAME_LIMIT)
    try:
        v = max(1, int(v))
    except (TypeError, ValueError):
        v = DEFAULT_FRAME_LIMIT
    return v


def _sw_notice_enabled(cfg) -> bool:
    return bool(read_sw(cfg, "notice", DEFAULT_NOTICE_ENABLED))


class ScreenWatchService(QObject):
    """持续看屏核心服务（app 级单例语义；get_screen_watch_service 取实例）。"""

    #: 运行/停止（False 表示已停采；UI 同步 chip 显隐/按钮态）
    watch_state_changed = Signal(bool)
    #: 每次成功采集并生成本会话内存帧 → (data_uri, meta_json)；「最近帧」供被动/按屏提问
    frame_captured = Signal(str, str)
    #: 显著变化（变化率≥阈值）→ float ratio
    screen_changed = Signal(float)
    #: 帧计数 / token 累计变化 → chip 刷新
    stats_changed = Signal()
    #: 单会话帧上限自动暂停 → int limit（UI 气泡 + chip 状态）
    auto_paused = Signal(int)
    #: 已过 30min 节流的高价值主动提示文案 → UI 以对话气泡呈现（仅 bubble，不 toast）
    high_value_notice = Signal(str)
    #: 一次性说明（分类失败/暂停等低优先级文案，UI 可闪显）
    notice = Signal(str)
    #: 暂停态变化（True=已暂停[含帧上限自停/手动]；False=运行中）
    paused_changed = Signal(bool)

    def __init__(self, app_ctx, parent: Optional[QObject] = None,
                 frame_provider: Optional[Callable] = None):
        super().__init__(parent)
        self._app_ctx = app_ctx
        self._cfg = getattr(app_ctx, "config", None) if app_ctx is not None else None
        #: 屏抓源（默认 screen_grab.grab_virtual_desktop；测试可注入 mock）
        self._frame_provider = frame_provider or _default_frame_provider

        self._running = False
        self._paused = False
        self._limit_reached = False

        self._timer = QTimer(self)
        self._timer.setInterval(_sw_interval(self._cfg) * 1000)
        self._timer.timeout.connect(self._on_tick)

        # 内存帧链（三路径弃帧的唯二持有点：最近帧 data URI + 压缩图灰缩略用于 diff）
        self._frame_uri: Optional[str] = None
        self._frame_meta: dict = {}
        self._frame_pixmap = None          # 仅存最近一帧（供 B2 crop/坐标换算；关闭即置 None）
        self._prev_gray = None              # QImage 灰缩略
        self._prev_uri: Optional[str] = None

        # 会话级（内存，随 app 生命周期，不落盘）
        self._frame_count: int = 0          # 本会话已送视觉分析的帧数
        self._token_total: int = 0          # 视觉调用累计 usage.total_tokens
        self._classify_busy = False
        self._last_classify_ts: float = 0.0
        self._last_notice_ts: float = 0.0
        self._classify_worker = None

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def frame_count(self) -> int:
        return self._frame_count

    def token_total(self) -> int:
        return self._token_total

    def latest_frame_data_uri(self) -> Optional[str]:
        """取帧口（B2 建议动作复用 / 被动提问复用）；未运行或从未采集返回 None。"""
        return self._frame_uri

    def latest_frame_meta(self) -> dict:
        return dict(self._frame_meta)

    def latest_frame_pixmap(self):
        return self._frame_pixmap

    def refresh_config(self) -> None:
        """设置页改配置后调用：interval 即时生效 + 阈值/上限下次判定生效。"""
        if self._timer is not None:
            try:
                self._timer.setInterval(_sw_interval(self._cfg) * 1000)
            except Exception:
                pass

    def start(self) -> bool:
        """显式开启持续采集（仅用户触发；offline/无 API 环境仍可采集但不分类）。"""
        if self._running:
            return True
        # 上次达帧上限自动暂停后，用户再次显式开启 = 续开新会话，重置帧计数
        if self._limit_reached:
            self._frame_count = 0
            self._token_total = 0
            self._limit_reached = False
        self._paused = False
        self._running = True
        try:
            self._timer.start()
        except Exception as exc:
            logger.warning("看屏定时器启动失败: %s", exc)
            self._running = False
            return False
        self._on_tick()  # 开启即先看一帧（用户显式操作的即时帧）
        self.watch_state_changed.emit(True)
        self.paused_changed.emit(False)
        logger.info("ScreenWatch 已开启（间隔 %ss, 阈值 %s, 帧上限 %s）",
                    _sw_interval(self._cfg), _sw_threshold(self._cfg),
                    _sw_frame_limit(self._cfg))
        return True

    def stop(self, discard: bool = True) -> None:
        """停采（用户关闭 / 面板销毁 / 退出）：停表 + 置空内存帧（R-E/R-G 弃帧三路径之一）。"""
        was = self._running or self._paused
        self._running = False
        try:
            self._timer.stop()
        except Exception:
            pass
        if discard:
            self._discard_frames()
        self._paused = False
        if was:
            self.watch_state_changed.emit(False)
            self.paused_changed.emit(False)

    def restart(self) -> bool:
        """重启（帧上限续开 / 设置变更后重挂）。幂等。"""
        self.stop(discard=True)
        return self.start()

    def shutdown(self) -> None:
        """quit 生命周期卫生（V-1.4-0 主窗 quit 列表调用；幂等）。"""
        try:
            self.stop(discard=True)
        except Exception:
            pass

    def capture_now(self) -> Optional[str]:
        """「看一帧」即时采集：抓新帧 → 更新最近帧 → 返回 data URI；失败 None。

        与周期 tick 共用 _capture_store（不额外触发分类，避免即时看帧误打扰）。
        """
        if not self._running:
            return None
        return self._capture_store(trigger_classify=False)

    def note_analysis(self, tokens: int = 0) -> bool:
        """调用方在「屏幕帧已送视觉模型」时打点：+1 帧 / 累计 token / 上限自停。

        服务已停/暂停时不计数（避免停采后迟到回调污染会话计数）。
        返回 False 表示本次已达上限被暂停（后续调用方应停止再送）。
        """
        if not self._running or self._paused:
            return True
        self._frame_count += 1
        self._add_tokens(tokens)
        limit = _sw_frame_limit(self._cfg)
        if self._frame_count >= limit:
            self._auto_pause(limit)
            return False
        return True

    def note_tokens(self, tokens: int) -> None:
        """补记 token（调用后异步到账的 usage）。"""
        self._add_tokens(tokens)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        if not self._running or self._paused:
            return
        self._capture_store(trigger_classify=True)

    def _capture_store(self, trigger_classify: bool) -> Optional[str]:
        """抓帧 → diff → 更新最近帧 → （可选）显著变化分类。任何失败静默不崩。"""
        try:
            result = self._frame_provider()
        except Exception as exc:
            logger.debug("看屏帧采集失败: %s", exc)
            return None
        if result is None or not getattr(result, "ok", False) or getattr(result, "pixmap", None) is None:
            return None
        from gui.screen_grab import pixmap_to_data_uri, pixmap_to_image, _to_gray_thumb
        pixmap = result.pixmap
        try:
            uri = pixmap_to_data_uri(pixmap)
        except Exception as exc:
            logger.debug("看屏帧压缩失败: %s", exc)
            return None
        if not uri:
            return None

        img = pixmap_to_image(pixmap)
        # 变化率：新帧 vs 上一帧（灰缩略）；首帧无前一帧按 0（不误触发）
        ratio = 0.0
        if img is not None:
            try:
                cur_gray = _to_gray_thumb(img, 96)
                from gui.screen_grab import frame_changed_ratio
                if cur_gray is not None and self._prev_gray is not None:
                    ratio = frame_changed_ratio(self._prev_gray, cur_gray)
                self._prev_gray = cur_gray
            except Exception as exc:
                logger.debug("看屏帧 diff 失败: %s", exc)

        vr = getattr(result, "virtual_rect", None)
        meta = {
            "virtual": {
                "x": vr.x() if vr is not None else 0,
                "y": vr.y() if vr is not None else 0,
                "w": vr.width() if vr is not None else 0,
                "h": vr.height() if vr is not None else 0,
            },
            "img_w": result.image_width,
            "img_h": result.image_height,
            "dpr": getattr(result, "dpr", 1.0),
            "geo": getattr(result, "screen_geos", None) or [],
            "ts": time.time(),
            "ratio": round(float(ratio), 4),
        }
        # 内存链：仅保留最近帧（R-E 弃帧）
        self._frame_uri = uri
        self._frame_meta = meta
        self._frame_pixmap = pixmap
        self._frame_captured_emit(uri, meta)

        if ratio >= _sw_threshold(self._cfg):
            self.screen_changed.emit(float(ratio))
            if trigger_classify and _sw_notice_enabled(self._cfg):
                self._maybe_classify(uri, meta)
        return uri

    def _frame_captured_emit(self, uri: str, meta: dict) -> None:
        try:
            self.frame_captured.emit(uri, json.dumps(meta, ensure_ascii=False))
        except Exception:
            pass

    # -- 高价值事件判定（显著变化帧分类 + 节流）--
    def _maybe_classify(self, uri: str, meta: dict) -> None:
        """显著变化帧分类：距上次 ≥90s 才跑一次低成本视觉调用；结果异常 → 30min 节流提示。

        守卫：非运行/暂停/忙/无帧/无 API/启发式纯文本模型 → 跳过（不浪费 token 不崩）。
        """
        if self._classify_busy:
            return
        now = time.time()
        if now - self._last_classify_ts < CLASSIFY_MIN_GAP_S:
            return
        app_ctx = self._app_ctx
        api = getattr(app_ctx, "api", None)
        if api is None:
            return
        # 纯文本模型不送视觉分类（避免必然报错烧 token；不确定模型放行让 API 兜底）
        try:
            from gui.vision_support import current_vision_support
            if current_vision_support(app_ctx) is False:
                return
        except Exception:
            pass
        try:
            from gui.vision_support import CLASSIFY_SYSTEM_PROMPT, build_vision_messages, VisionQueryWorker
        except Exception:
            return
        messages = build_vision_messages(CLASSIFY_SYSTEM_PROMPT, "请判断这张屏幕截图是否有异常。", uri)
        worker = VisionQueryWorker(api, messages, temperature=0.0, max_tokens=160, parent=self)
        self._classify_busy = True
        self._last_classify_ts = now
        worker.succeeded.connect(self._on_classify_done)
        worker.failed.connect(self._on_classify_failed)
        worker.finished.connect(worker.deleteLater)
        self._classify_worker = worker
        worker.start()

    def _on_classify_done(self, text: str, usage: dict) -> None:
        self._classify_busy = False
        self._classify_worker = None
        # 分类调用也是一次帧分析：计帧 + 累计 token
        try:
            tokens = int((usage or {}).get("total_tokens") or 0) or 0
        except (TypeError, ValueError):
            tokens = 0
        self.note_analysis(tokens=tokens)
        try:
            from gui.vision_support import VisionQueryWorker
            parsed = VisionQueryWorker.parse_high_value(text)
        except Exception:
            parsed = None
        if not parsed or not parsed.get("anomaly"):
            return
        summary = str(parsed.get("summary") or "").strip()
        if not summary:
            return
        # R-C 节流：≤1 条/30min（内存时间戳，随 app 生命周期）
        now = time.time()
        if now - self._last_notice_ts < NOTICE_MIN_GAP_S:
            return
        self._last_notice_ts = now
        try:
            self.high_value_notice.emit(summary)
        except Exception:
            pass

    def _on_classify_failed(self, err: str) -> None:
        self._classify_busy = False
        self._classify_worker = None
        logger.info("看屏高价值分类失败（静默，不影响看屏）: %s", err)

    # -- 帧数/token/上限 --
    def _add_tokens(self, tokens: int) -> None:
        try:
            tokens = int(tokens or 0)
        except (TypeError, ValueError):
            tokens = 0
        if tokens <= 0:
            return
        self._token_total += tokens
        self._stats_changed_emit()

    def _auto_pause(self, limit: int) -> None:
        """单会话帧上限自动暂停（Q-B3 成本护栏）。"""
        if not self._running and not self._paused:
            return
        self._running = False
        self._paused = True
        self._limit_reached = True
        try:
            self._timer.stop()
        except Exception:
            pass
        logger.info("看屏已达单会话帧上限 %s，自动暂停", limit)
        try:
            self.auto_paused.emit(limit)
        except Exception:
            pass
        try:
            self.paused_changed.emit(True)
        except Exception:
            pass
        # 内存帧保留在暂停态（用户可查看最近帧），关停/续开时按路径置空/重置

    def _stats_changed_emit(self) -> None:
        try:
            self.stats_changed.emit()
        except Exception:
            pass

    def _discard_frames(self) -> None:
        """弃帧：置空最近帧引用（不落盘；图像字节只存内存变量，随引用释放）。"""
        self._frame_uri = None
        self._frame_meta = {}
        self._frame_pixmap = None
        self._prev_gray = None
        self._prev_uri = None

    def _frame_count_internal(self) -> int:  # noqa: F841 (保留测试读口别名)
        return self._frame_count


def _default_frame_provider():
    """默认屏抓源（延迟 import，避免 QImage 相关在弱环境下拖累模块导入）。"""
    from gui.screen_grab import grab_virtual_desktop
    return grab_virtual_desktop()


def get_screen_watch_service(app_ctx):
    """app 级 ScreenWatchService 取/建（chat_panel / main V-1.4-0 挂载共用同一实例）。"""
    if app_ctx is None:
        return None
    svc = getattr(app_ctx, APP_CTX_KEY, None)
    if svc is None:
        try:
            svc = ScreenWatchService(app_ctx)
            setattr(app_ctx, APP_CTX_KEY, svc)
        except Exception as exc:
            logger.warning("ScreenWatchService 初始化失败: %s", exc)
            return None
    return svc
