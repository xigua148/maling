"""GUI 专属配置管理 —— 主题、窗口状态持久化。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from gui.utils import get_user_data_dir

logger = logging.getLogger("maid_coder.gui")


class GuiConfig:
    """GUI 专属配置，持久化到本地 JSON。"""

    @staticmethod
    def _config_path() -> Path:
        return get_user_data_dir() / "gui_config.json"

    def __init__(self) -> None:
        # v1.9 A(D-V19-10/D-V19-12): 四风格 id 之一（ui_minimal/ui_cream/ui_night/ui_whale）
        # 为唯一真值源；旧值（cute/minimal/maid）由 ThemeEngine.LEGACY_THEME_MAP 读时归一。
        # 新用户默认「现代极简」ui_minimal。
        self.theme_name: str = "ui_minimal"
        self.font_size: int = 14
        self.code_theme: str = "github-light"
        # ---- v1.9 B/D-V19-08: 界面字体（六 id：见 gui/fonts.py FONT_IDS）----
        # 默认资源圆体（内置 OFL）；老存档无本键时 hasattr 循环跳过 → 取本类默认
        # = 自动升级到资源圆体（Q-E6 零迁移成本）。
        self.font_family: str = "resource_rounded"
        self.window_opacity: float = 1.0
        self.sidebar_visible: bool = True
        self.chat_panel_visible: bool = True
        self.window_geometry: Optional[str] = None
        self.last_project_root: Optional[str] = None
        self.first_run: bool = True
        self.maid_mode: bool = True
        # v1.4 宠物形态：统一为「女仆小人」maid（「女仆小兽」入口已按用户要求
        # 移除）；存档值优先，未存时用本默认。历史 chibi 存档由消费侧
        # maid_pet.resolve_pet_style 统一回落 maid，防环依赖。
        self.pet_style: str = "maid"
        # v1.2.3: 窗口角落 MaidPet（聊天主屏右上角小立绘）显隐开关，默认关
        # 设置页可即时切换；存档值优先，未存时使用本默认。
        self.pet_enabled: bool = False
        # ---- v1.3 P1-1: TTS 语音（朗读回复）----
        self.tts_enabled: bool = True      # 朗读按钮总开关（默认开）
        self.tts_auto_read: bool = False   # 自动朗读 AI 回复（默认关）
        self.tts_speed: int = 50           # 语速 0..100（默认 50）
        # ---- v1.3 P1-3: 全局热键 + 关闭行为 ----
        self.hotkey_toggle: str = "Ctrl+Alt+M"       # 全局呼出/隐藏主窗
        self.hotkey_screenshot: str = "Ctrl+Alt+S"   # 截图提问热键
        self.close_quits: bool = False               # 「关闭窗口直接退出」默认不勾 = X 隐藏到托盘
        # ---- v1.3 P2-7: 外观模式 ----
        self.theme_mode: str = "light"               # light / dark / system（默认浅色，不改旧用户观感）
        # ---- v1.9 A(D-V19-11/Q-E2): 进入 C 深色夜间（ui_night）前的原外观模式暂存 ----
        # 默认 ""（未进入过 / 已离开）；进入时记住原 mode，离开时恢复并清空。
        self.theme_mode_before_night: str = ""
        # ---- v1.4.3「主题强调色色盘」：自定义强调色（#RRGGBB，空=用主题默认）----
        self.custom_accent: str = ""                 # 空串回落主题默认强调色
        # ---- v1.5.0: GUI 聊天页「🌐 联网」开关（命中 should_auto_search 才检索注入）----
        self.web_search_enabled_gui: bool = False
        # ---- v1.6(P0-2): 聊天意图选态持久化（"auto"=自动识别；其余为手动覆盖态：
        # confide/chat/analyze/advise/act，见 gui/intent.py）----
        self.chat_intent_mode: str = "auto"
        # ---- v1.6(P1-3/D-V16-10): 周回顾 LLM 润色口（本期无 UI 入口，默认关）----
        self.weekly_llm_polish: bool = False
        # ---- v1.7(F3/D-V17-02/Q-C5): 深夜关 app 晚安托盘气泡（可关）----
        self.ritual_goodnight: bool = True
        # ---- v1.7(F7/D-V17-05/Q-C2): 女仆日记（默认开可关）----
        self.diary_enabled: bool = True
        # ---- v1.7(F10b/D-V17-06/Q-C1): 群聊全局默认（R-J② 默认关；会话级 metadata 可覆盖）----
        self.group_no_at_policy: str = "rotate"    # 无@策略：rotate | silent
        # v1.8 收尾：group_chatter_enabled / metadata.chatter 已退役（F10 自由发言调度取代）
        # ---- v1.8(D-V18-01/Q-D1): 记忆图谱提议-确认链（默认关，无确认绝不写入）----
        self.entity_auto_propose: bool = False
        # ---- v1.8(D-V18-03/D-V18-10): F2 情绪概览注入总开关（confide/疑问句式命中时）----
        self.emotion_overview_enabled: bool = True
        # ---- v1.8(D-V18-07/D-V18-10): F4 场景化陪伴 ----
        self.scene_auto: bool = True                  # 场景自动感知总开关（False=整体关闭）
        self.manual_scene: str = ""                   # 手动选择场景（work/rest/sleep；""=自动感知）
        self.manual_scene_date: str = ""              # 手动选择生效日（YYYY-MM-DD；当日有效次日回落 Q-D4）
        self.scene_work_proactive_cap: int = 1        # 工作场景主动条数上限（Q-D6：3→1，可调 0=工作时段不打扰）
        # ---- v1.8(D-V18-08/D-V18-10): F7 影像记忆增强档（Q-D8 默认关零调用）----
        self.vision_memory_enhance: bool = False
        # ---- v1.7.2(T3): 编程引擎选择（"agent"=内置 AgentEngine；"pi"=Pi 试点 RPC）。
        # 仅影响 Agent 模式（task_type="agent"）；managed 任务仍走内置（Pi 无对应物）。
        self.coding_engine: str = "agent"
        # ---- v1.3 P2-5: 开机自启开关的 UI 镜像（真值源在注册表 autostart.py）----
        self.autostart_enabled: bool = False
        # ---- v1.4（V-1.4-0 预编汇交点，A/B 线共用；docs/design-v14.md §3.2/§4.1）----
        # B 线「持续看屏」偏好（默认全关/低频；B 线消费，从此只读不再编辑）
        self.screen_watch_enabled: bool = False        # 持续看屏总开关
        self.screen_watch_interval_sec: int = 30       # 周期采集间隔（秒）
        self.screen_watch_change_ratio: float = 0.04   # 帧显著变化判定阈值 0..1
        self.screen_watch_max_frames: int = 200        # 单会话已分析帧上限
        self.screen_watch_autopause: bool = True       # 达帧上限自动暂停
        # 命名别名键（design-v14 §4.1 表格命名，消费侧任选一族，缺省兼容）
        self.screen_watch_interval_s: int = 30
        self.screen_watch_frame_limit: int = 200
        self.screen_watch_notice_enabled: bool = True  # 高价值事件主动提示总开关
        # A 线「番茄钟」偏好（A 线消费，从此只读不再编辑）
        self.pomodoro_work_min: int = 25               # 专注时长（分钟，对话框可调）
        self.pomodoro_break_min: int = 5               # 休息时长（分钟）
        self.pomodoro_tts: bool = True                 # 到点可选语音（受 tts_enabled 守卫）
        # ---- v2.0(D-V20-07/§4.6): 自动更新设置（GuiConfig 是频道唯一真值源）----
        self.update_channel: str = "stable"   # 更新频道：stable / beta
        self.auto_check: bool = True          # 启动自动检查更新（关=仅手动入口）
        self.auto_download: bool = True       # 后台自动下载（安装仍需用户确认，Q-U9）
        self.use_mirror: bool = True          # 启用备用链（镜像）
        self.mirror_url: str = ""             # 自定义镜像直链（其 host 进 R-M 白名单）

    @classmethod
    def load(cls) -> "GuiConfig":
        """从本地文件加载配置，不存在则返回默认实例。"""
        cfg = cls()
        path = cls._config_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for key, value in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
                # v1.4：「女仆小兽」形态已移除，历史存档里的 chibi 一律归一为 maid，
                # 保证设置页下拉与消费侧读到的是同一个形态（下次保存即落盘 maid）。
                if cfg.pet_style != "maid":
                    cfg.pet_style = "maid"
                logger.info("GUI 配置已加载: %s", path.resolve())
            except Exception as exc:
                logger.warning("GUI 配置加载失败，使用默认: %s", exc)
        return cfg

    def save(self) -> None:
        """保存配置到本地文件。"""
        data = {
            "theme_name": self.theme_name,
            "font_size": self.font_size,
            "code_theme": self.code_theme,
            # v1.9 B/D-V19-08: 界面字体
            "font_family": self.font_family,
            "window_opacity": self.window_opacity,
            "sidebar_visible": self.sidebar_visible,
            "chat_panel_visible": self.chat_panel_visible,
            "window_geometry": self.window_geometry,
            "last_project_root": self.last_project_root,
            "first_run": self.first_run,
            "maid_mode": self.maid_mode,
            "pet_style": self.pet_style,
            "pet_enabled": self.pet_enabled,
            # v1.3 P1-1: TTS
            "tts_enabled": self.tts_enabled,
            "tts_auto_read": self.tts_auto_read,
            "tts_speed": self.tts_speed,
            # v1.3 P1-3: 热键 + 关闭行为
            "hotkey_toggle": self.hotkey_toggle,
            "hotkey_screenshot": self.hotkey_screenshot,
            "close_quits": self.close_quits,
            # v1.3 P2-7 / P2-5
            "theme_mode": self.theme_mode,
            # v1.9 A(D-V19-11): C 深色夜间进出暂存原外观模式
            "theme_mode_before_night": self.theme_mode_before_night,
            "autostart_enabled": self.autostart_enabled,
            # v1.4.3「主题强调色色盘」
            "custom_accent": self.custom_accent,
            # v1.5.0: GUI 联网开关
            "web_search_enabled_gui": self.web_search_enabled_gui,
            # v1.6(P0-2): 聊天意图选态
            "chat_intent_mode": self.chat_intent_mode,
            # v1.6(P1-3): 周回顾润色口（预留）
            "weekly_llm_polish": self.weekly_llm_polish,
            # v1.7.2(T3): 编程引擎选择
            "coding_engine": self.coding_engine,
            # v1.7(F3): 深夜晚安托盘气泡
            "ritual_goodnight": self.ritual_goodnight,
            "diary_enabled": self.diary_enabled,
            # v1.7(F10b): 群聊全局默认（无@策略）
            "group_no_at_policy": self.group_no_at_policy,
            # v1.8: 记忆图谱提议-确认开关 + 情绪概览注入总开关
            "entity_auto_propose": self.entity_auto_propose,
            "emotion_overview_enabled": self.emotion_overview_enabled,
            # v1.8(D-V18-07): 场景化陪伴（自动感知开关 / 手动场景 / 生效日 / 工作降档上限）
            "scene_auto": self.scene_auto,
            "manual_scene": self.manual_scene,
            "manual_scene_date": self.manual_scene_date,
            "scene_work_proactive_cap": self.scene_work_proactive_cap,
            # v1.8(D-V18-08): 影像记忆增强档（默认关）
            "vision_memory_enhance": self.vision_memory_enhance,
            # v1.4（V-1.4-0 预编）：B 线 screen_watch_* + A 线 pomodoro_*
            "screen_watch_enabled": self.screen_watch_enabled,
            "screen_watch_interval_sec": self.screen_watch_interval_sec,
            "screen_watch_change_ratio": self.screen_watch_change_ratio,
            "screen_watch_max_frames": self.screen_watch_max_frames,
            "screen_watch_autopause": self.screen_watch_autopause,
            "screen_watch_interval_s": self.screen_watch_interval_s,
            "screen_watch_frame_limit": self.screen_watch_frame_limit,
            "screen_watch_notice_enabled": self.screen_watch_notice_enabled,
            "pomodoro_work_min": self.pomodoro_work_min,
            "pomodoro_break_min": self.pomodoro_break_min,
            "pomodoro_tts": self.pomodoro_tts,
            # v2.0(D-V20-07/§4.6): 自动更新设置（既有键零改动）
            "update_channel": self.update_channel,
            "auto_check": self.auto_check,
            "auto_download": self.auto_download,
            "use_mirror": self.use_mirror,
            "mirror_url": self.mirror_url,
        }
        try:
            self._config_path().write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("GUI 配置已保存")
        except Exception as exc:
            logger.error("GUI 配置保存失败: %s", exc)
