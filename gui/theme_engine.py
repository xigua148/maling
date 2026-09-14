"""主题引擎 —— QSS 动态加载、配色映射、字体管理。

v1.2(B8/D7): 合并式收敛加载 —— 渲染链 = themes/base.qss(公共组件结构/布局层)
+ 主题 qss(配色/肤感层)。base 与主题 QSS 均引用 ${...} 变量（颜色 + layout token），
在 load_theme 时统一按当前主题替换。新增 get_layout_token() 供代码取数值型 token。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional

from gui import fonts
from gui.qt_compat import (
    QObject, Signal, QApplication, QFont, QTimer, QAbstractNativeEventFilter,
)
from gui.utils import get_resource_path


# ======================================================================
# v1.3(P2-7): 深色模式 —— 系统深浅读取（winreg，纯标准库）
# ======================================================================
def _read_system_light_theme() -> Optional[bool]:
    """读取 Windows 深浅色设置（AppsUseLightTheme）。

    返回 True=浅色 / False=深色 / None=读取失败（非 Windows、无该键或异常）。
    """
    if os.name != "nt":
        return None
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            value, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return bool(int(value))
    except Exception:
        return None


# ======================================================================
# v2.1(D-V21-11): 系统深浅实时性 —— 原生事件监听（去抖后转调既有轮询）
# ----------------------------------------------------------------------
# 只做「监听 + 去抖 + 转调既有 _poll_system_mode」，不改其实现、不改任何
# 既有契约签名（R-D）。安装失败时静默回落 30s 轮询（见 _start_system_poll）。
# ======================================================================
WM_SETTINGCHANGE = 0x001A                     # 系统设置变化（含主题/个性化）
WM_THEMECHANGED = 0x031A                      # 主题切换
WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320       # DWM 颜色变化
_WATCHED_THEME_MSGS = frozenset((
    WM_SETTINGCHANGE, WM_THEMECHANGED, WM_DWMCOLORIZATIONCOLORCHANGED,
))


def _native_msg_id(message) -> int:
    """从原生事件过滤器的 ``message`` 取 Windows 消息号；取不到 → 0（不抛）。

    跨 PySide6 版本兼容：``message`` 可能是 void 指针包装、``int`` 或可转
    ``int`` 的对象；按指针宽度取 ``MSG.message`` 字段（x64 偏移 8 / x86 偏移 4）。
    """
    try:
        import ctypes
        try:
            addr = int(message)
        except Exception:
            voidp = ctypes.cast(message, ctypes.c_void_p)
            addr = int(voidp.value or 0)
        if not addr:
            return 0
        offset = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 4
        return int(ctypes.c_uint.from_address(addr + offset).value)
    except Exception:
        return 0


class _SystemThemeEventFilter(QAbstractNativeEventFilter):
    """拦截 Windows 主题相关消息 → 通知引擎去抖转调既有 ``_poll_system_mode``。

    本类**只加订阅者**：返回 ``False``（不消费消息，交还 Qt/系统继续处理），
    不改 ``theme_changed`` / ``set_theme_mode`` 等任何契约。
    """

    def __init__(self, engine: "ThemeEngine"):
        super().__init__()
        self._engine = engine

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt 命名)
        try:
            if _native_msg_id(message) in _WATCHED_THEME_MSGS:
                self._engine._on_system_theme_message()
        except Exception:
            pass
        return False



class ThemeEngine(QObject):
    """主题引擎：管理 QSS 加载、配色映射、动态切换。"""

    theme_changed = Signal(str)  # 参数：主题名称

    # 公共组件结构层（先加载）；主题 qss 后加载做肤感覆盖。
    # design R1：v1.2 阶段一只保证 base 覆盖的新组件样式正确 + 主题切换即时生效，
    # 既有三套 QSS 的「收窄为肤感层」全量裁剪到 P2（U-5 offscreen 截图回归后执行）。
    BASE_QSS_FILE = "themes/base.qss"

    THEME_DEFINITIONS: Dict[str, Dict] = {
        "cute": {
            "name": "活泼可爱风",
            "qss_file": "themes/cute.qss",
            "colors": {
                "primary": "#FFB6C1",
                "primary_dark": "#FF69B4",
                "secondary": "#FFF8DC",
                "accent": "#E6E6FA",
                "bg": "#FFF5F5",
                "bg_card": "#FFFFFF",
                "text": "#5D4037",
                "text_secondary": "#757575",
                "border": "#FFE4E1",
                "shadow": "rgba(255,182,193,0.15)",
                "radius_sm": "8px",
                "radius_md": "12px",
                "radius_lg": "16px",
                "radius_pill": "20px",
                # R4: 新增控件色键注册（切换主题真正生效）
                "text_on_accent": "#FFFFFF",
                "bg_light": "#FFF0F3",
                "disabled_bg": "#E0E0E0",
                "disabled_text": "#9E9E9E",
                # v1.2(B8/D7): 公共语义色键（三主题同步注册；新 UI 一律 theme_color/取色器）
                "surface_muted": "#FFF9FA",      # 页面次级浅面（比 bg 略提亮）
                "text_hint": "#C9A0A6",          # 三级说明文字（比 text_secondary 更淡）
                "divider": "#EFE0E2",            # 细分隔线/描边
                "focus_accent": "#FF8AA5",       # 聚焦/选中强调描边
                "pet_bubble_bg": "#FFF5F7",      # 宠物/气泡类浮层背景
                # 连接态语义色（B9 状态点/提示文字用，禁止代码裸值）
                "state_ok": "#3FBF7F",
                "state_warn": "#E5A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（与 state_warn 同组、取值可区分）
                "state_danger": "#C0392B",
                # v1.2(B8/D7): layout token（QSS 用 px 字符串，随主题替换）
                "spacing_xs": "4px",
                "spacing_sm": "8px",
                "spacing_md": "12px",
                "spacing_lg": "20px",
            },
            # v1.2(B8/D7): 数值版 layout token（代码 get_layout_token 用，与 colors 对应）
            "layout": {
                "spacing_xs": 4, "spacing_sm": 8, "spacing_md": 12, "spacing_lg": 20,
                "radius_sm": 8, "radius_md": 12, "radius_lg": 16, "radius_pill": 20,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
        "minimal": {
            "name": "简约浅色清爽风",
            "qss_file": "themes/minimal.qss",
            "colors": {
                "primary": "#2196F3",
                "primary_dark": "#1976D2",
                "secondary": "#00BCD4",
                "accent": "#3F51B5",
                "bg": "#FFFFFF",
                "bg_card": "#FAFAFA",
                "text": "#212121",
                "text_secondary": "#757575",
                "border": "#E0E0E0",
                "shadow": "rgba(0,0,0,0.05)",
                "radius_sm": "4px",
                "radius_md": "6px",
                "radius_lg": "8px",
                "radius_pill": "6px",
                # R4: 新增控件色键注册（按冷色调配色）
                "text_on_accent": "#FFFFFF",
                "bg_light": "#E8F1FA",
                "disabled_bg": "#E0E0E0",
                "disabled_text": "#9E9E9E",
                # v1.2(B8/D7): 公共语义色键（冷调）
                "surface_muted": "#F3F6F9",
                "text_hint": "#A8B0B8",
                "divider": "#E8ECF0",
                "focus_accent": "#1976D2",
                "pet_bubble_bg": "#F5F7FA",
                "state_ok": "#3F9E6E",
                "state_warn": "#E0A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（与 state_warn 同组、取值可区分）
                "state_danger": "#C0392B",
                # v1.2(B8/D7): layout token（minimal 密度更高）
                "spacing_xs": "4px",
                "spacing_sm": "6px",
                "spacing_md": "10px",
                "spacing_lg": "16px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 6, "spacing_md": 10, "spacing_lg": 16,
                "radius_sm": 4, "radius_md": 6, "radius_lg": 8, "radius_pill": 6,
            },
            "font": {"family": "Segoe UI, Microsoft YaHei", "code": "Consolas, JetBrains Mono"},
        },
        "maid": {
            "name": "女仆粉",
            "qss_file": "themes/maid.qss",
            "colors": {
                "primary": "#FFB6C1",
                "primary_dark": "#FF69B4",
                "secondary": "#FFF0F5",
                "accent": "#FF69B4",
                "bg": "#FFF0F5",
                "bg_card": "#FFFFFF",
                "text": "#4A4A4A",
                "text_secondary": "#8A8A8A",
                "border": "#FFB6C1",
                "shadow": "rgba(255,182,193,0.2)",
                "radius_sm": "8px",
                "radius_md": "12px",
                "radius_lg": "16px",
                "radius_pill": "20px",
                # R4: 新增控件色键注册
                "text_on_accent": "#FFFFFF",
                "bg_light": "#FFF0F3",
                "disabled_bg": "#E0E0E0",
                "disabled_text": "#9E9E9E",
                # v1.2(B8/D7): 公共语义色键（粉调更深一档）
                "surface_muted": "#FFFAFC",
                "text_hint": "#C9A3AB",
                "divider": "#F0DAE0",
                "focus_accent": "#FF69B4",
                "pet_bubble_bg": "#FFF0F5",
                "state_ok": "#3FBF7F",
                "state_warn": "#E0A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（与 state_warn 同组、取值可区分）
                "state_danger": "#C0392B",
                # v1.2(B8/D7): layout token
                "spacing_xs": "4px",
                "spacing_sm": "8px",
                "spacing_md": "12px",
                "spacing_lg": "20px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 8, "spacing_md": 12, "spacing_lg": 20,
                "radius_sm": 8, "radius_md": 12, "radius_lg": 16, "radius_pill": 20,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
        # ==============================================================
        # v1.9 A 块（D-V19-09）：四风格增量条目（键位与旧三主题完全对齐）
        # 旧三主题（cute/minimal/maid）保留于本表（R-D），但 UI 入口只暴露四风格；
        # 旧配置值经 LEGACY_THEME_MAP 读时归一（D-V19-10）。
        # 视觉稿：D:/【试用测试】/ui_concept/码铃_UI四风格四字体.html
        # ==============================================================
        # ---------- A 现代极简 ----------
        "ui_minimal": {
            "name": "现代极简",
            "qss_file": "themes/ui_minimal.qss",
            "colors": {
                # v2.1(UI-P1) 第二轮软化：用户反馈「粉色太深、有点扎眼」—— 根因是饱和过高。
                # 本轮继续降饱和并提亮：H 锁定 339°，S 48%→40%，L 55%→62%（更淡更柔）。
                # 主色变淡后白字对比度仅 3.267，故 text_on_accent 改深色 #1C1C1E → 5.208。
                # 硬约束实测：primary+text_on_accent=5.208、primary_dark+text_on_accent=4.609、
                #             primary vs bg(#F7F7F8)=3.051（均达标）。
                # 配套浅粉底同批换算（同色相 H≈339，饱和按同比例下调），保证整体协调。
                "primary": "#C57792", "primary_dark": "#C46889", "secondary": "#F5EAEE",
                "accent": "#C57792",
                # v2.1(UI-P1 第三轮)：accent_text =「文字用」强调色，与「填充用」primary 分工。
                # 小字（12px 人名等）落在浅底上需 vs bg ≥4.5，而 primary 为求「淡/柔」仅 3.05，
                # 一色两用不可行（详见 _final_tone_report.md 第九节），故新增独立键。
                "accent_text": "#B45073",
                "bg": "#F7F7F8", "bg_card": "#FFFFFF", "surface_muted": "#FBFBFC",
                "border": "#EBEBEF", "text": "#1C1C1E", "text_secondary": "#76767D",
                "text_hint": "#8F8F96", "divider": "#F0F0F3",
                "shadow": "0 1px 3px rgba(0,0,0,0.05)",
                "bg_light": "#F5EAEE", "focus_accent": "#C57792",
                "text_on_accent": "#1C1C1E",
                "accent_light": "#F5EAEE",
                "bubble_user_bg": "#F0F0F3", "bubble_user_text": "#1C1C1E",
                "bubble_ai_bg": "#FFFFFF", "bubble_ai_text": "#1C1C1E",
                "chat_bg": "#F7F7F8", "chat_border": "#EBEBEF",
                "pet_bubble_bg": "#F1E4E9",
                "disabled_bg": "#E0E0E0", "disabled_text": "#9E9E9E",
                "state_ok": "#3F9E6E", "state_warn": "#E0A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（浅色，与 state_warn 可区分）
                "state_danger": "#C0392B",
                # v2.1(D-V21-16)：信息 / 警示语义色（浅色，对比度 ≥3:1）
                # 第二轮：text_secondary 加深至 4.211 后，warning 原值(4.123)反比次级文字更浅，
                # 破坏「info/warning 不浅于 text_secondary」层次约束，故同步加深至 4.535。
                "info": "#2F6FB5", "warning": "#A06411",
                "radius_sm": "8px", "radius_md": "14px", "radius_lg": "20px", "radius_pill": "24px",
                "spacing_xs": "4px", "spacing_sm": "6px", "spacing_md": "10px", "spacing_lg": "16px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 6, "spacing_md": 10, "spacing_lg": 16,
                "radius_sm": 8, "radius_md": 14, "radius_lg": 20, "radius_pill": 24,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
        # ---------- B 温暖奶油 ----------
        "ui_cream": {
            "name": "温暖奶油",
            "qss_file": "themes/ui_cream.qss",
            "colors": {
                "primary": "#FF8FA3", "primary_dark": "#F0708A", "secondary": "#FFEEF1",
                "accent": "#FF8FA3",
                # accent_text（文字用强调色）：h=349 s=40% l=51%，vs bg(#FFF8F3)=4.684。
                # 刻意降饱和（HSV 55.6%，对比被否掉的 #E6062E 的 97.4%）→ 呈莓/玫瑰色而非鲜红。
                "accent_text": "#B45062",
                "bg": "#FFF8F3", "bg_card": "#FFFFFF", "surface_muted": "#FFFBF8",
                # 第二轮：小字对比度修复 —— secondary 3.019→4.234、hint 2.161→3.022。
                "border": "#F5E6DC", "text": "#3D2E2A", "text_secondary": "#847566",
                "text_hint": "#9D8E7F", "divider": "#F1E2D8",
                "shadow": "0 6px 20px rgba(255,143,163,0.13)",
                "bg_light": "#FFEEF1", "focus_accent": "#FF8FA3",
                "text_on_accent": "#3D2E2A",
                "accent_light": "#FFEEF1",
                "bubble_user_bg": "#FFE8EF", "bubble_user_text": "#3D2E2A",
                "bubble_ai_bg": "#FFFFFF", "bubble_ai_text": "#3D2E2A",
                "chat_bg": "#FFF8F3", "chat_border": "#F5E6DC",
                "pet_bubble_bg": "#FFEEF1",
                "disabled_bg": "#E0E0E0", "disabled_text": "#9E9E9E",
                "state_ok": "#3F9E6E", "state_warn": "#E0A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（浅色，与 state_warn 可区分）
                "state_danger": "#C0392B",
                # v2.1(D-V21-16)：信息 / 警示语义色（浅色，暖调，对比度 ≥3:1）
                "info": "#2E6E9E", "warning": "#A86412",
                "radius_sm": "10px", "radius_md": "16px", "radius_lg": "20px", "radius_pill": "24px",
                "spacing_xs": "4px", "spacing_sm": "8px", "spacing_md": "12px", "spacing_lg": "20px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 8, "spacing_md": 12, "spacing_lg": 20,
                "radius_sm": 10, "radius_md": 16, "radius_lg": 20, "radius_pill": 24,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
        # ---------- C 深色夜间（dark_locked：强制深色，Q-E2） ----------
        "ui_night": {
            "name": "深色夜间",
            "qss_file": "themes/ui_night.qss",
            "dark_locked": True,
            "colors": {
                "primary": "#FF6B9D", "primary_dark": "#E0527F", "secondary": "#3A2430",
                "accent": "#FF6B9D",
                # accent_text（文字用强调色）：自身即深色，浅/深同值，vs bg(#131114)=7.039。
                "accent_text": "#FB6F9E",
                "bg": "#131114", "bg_card": "#1C1920", "surface_muted": "#211D26",
                "border": "#2C2733", "text": "#F2EFF5", "text_secondary": "#918A9C",
                "text_hint": "#6E6878", "divider": "#262230",
                "shadow": "0 2px 12px rgba(0,0,0,0.35)",
                "bg_light": "#3A2430", "focus_accent": "#FF6B9D",
                "text_on_accent": "#1C1920",
                "accent_light": "#3A2430",
                "bubble_user_bg": "#2B2130", "bubble_user_text": "#F2EFF5",
                "bubble_ai_bg": "#1F1B24", "bubble_ai_text": "#F2EFF5",
                "chat_bg": "#131114", "chat_border": "#2C2733",
                "pet_bubble_bg": "#3A2430",
                "code_bg": "#16161B", "code_text": "#F2F2F5", "code_lang": "#9A9AA2",
                "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
                "state_ok": "#4FD18F", "state_warn": "#E8B04C",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（ui_night 自身即深色，取深色值）
                "state_danger": "#EE7A7A",
                # v2.1(D-V21-16)：信息 / 警示语义色（ui_night 自身即深色，取深色值，对比度 ≥3:1）
                "info": "#6FB0E0", "warning": "#E0A84A",
                "radius_sm": "8px", "radius_md": "14px", "radius_lg": "20px", "radius_pill": "24px",
                "spacing_xs": "4px", "spacing_sm": "6px", "spacing_md": "10px", "spacing_lg": "16px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 6, "spacing_md": 10, "spacing_lg": 16,
                "radius_sm": 8, "radius_md": 14, "radius_lg": 20, "radius_pill": 24,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
        # ---------- D 鲸鱼娘深海（brand_persona：文案随人设，Q-E3） ----------
        "ui_whale": {
            "name": "鲸鱼娘深海",
            "qss_file": "themes/ui_whale.qss",
            "brand_persona": True,
            "colors": {
                "primary": "#2E9BB5", "primary_dark": "#228394", "secondary": "#E0F2F7",
                "accent": "#2E9BB5",
                # accent_text（文字用强调色）：vs bg(#EEF6FA)=4.511。
                "accent_text": "#247A8F",
                "bg": "#EEF6FA", "bg_card": "#FFFFFF", "surface_muted": "#F4FAFC",
                # 第二轮：小字对比度修复 —— secondary 3.359→4.227、hint 2.273→3.008。
                "border": "#D5E8F0", "text": "#12303F", "text_secondary": "#63778B",
                "text_hint": "#7C90A4", "divider": "#E3F0F5",
                "shadow": "0 4px 16px rgba(46,155,181,0.12)",
                "bg_light": "#E0F2F7", "focus_accent": "#2E9BB5",
                "text_on_accent": "#05202A",
                "accent_light": "#E0F2F7",
                "bubble_user_bg": "#DFF0F8", "bubble_user_text": "#12303F",
                "bubble_ai_bg": "#FFFFFF", "bubble_ai_text": "#12303F",
                "chat_bg": "#EEF6FA", "chat_border": "#D5E8F0",
                "pet_bubble_bg": "#E0F2F7",
                "disabled_bg": "#E0E0E0", "disabled_text": "#9E9E9E",
                "state_ok": "#3F9E6E", "state_warn": "#E0A02E",
                # v2.1(D-V21-17)：危险/破坏性操作语义色（浅色，与 state_warn 可区分）
                "state_danger": "#C0392B",
                # v2.1(D-V21-16)：信息 / 警示语义色（浅色，海蓝 / 琥珀，对比度 ≥3:1）
                # 第二轮：text_secondary 加深至 4.227 后，warning 原值(3.764)反比次级文字更浅，
                # 破坏「info/warning 不浅于 text_secondary」层次约束，故同步加深至 4.610。
                "info": "#1E7C96", "warning": "#96650D",
                "radius_sm": "10px", "radius_md": "18px", "radius_lg": "22px", "radius_pill": "26px",
                "spacing_xs": "4px", "spacing_sm": "8px", "spacing_md": "12px", "spacing_lg": "20px",
            },
            "layout": {
                "spacing_xs": 4, "spacing_sm": 8, "spacing_md": 12, "spacing_lg": 20,
                "radius_sm": 10, "radius_md": 18, "radius_lg": 22, "radius_pill": 26,
            },
            "font": {"family": "Microsoft YaHei, Segoe UI", "code": "JetBrains Mono"},
        },
    }

    # v1.9 A 块（D-V19-10）：旧配置值 → 新 id 读时映射（唯一真值源）。
    # UI 文案与代码不得再把 cute/minimal/maid 当作用户可见选项。
    LEGACY_THEME_MAP: Dict[str, str] = {
        "cute": "ui_cream",
        "maid": "ui_cream",
        "minimal": "ui_minimal",
    }
    # 四风格 id（UI 切换器/onboarding/设置页共用，唯一真值源）
    THEME_IDS = ("ui_minimal", "ui_cream", "ui_night", "ui_whale")
    DEFAULT_THEME_ID = "ui_minimal"

    def __init__(self, parent: QObject = None):
        super().__init__(parent)
        # v1.9 A 块：默认风格 = 现代极简（ui_minimal）；旧值经 LEGACY_THEME_MAP 读时归一
        self._current_theme: str = self.DEFAULT_THEME_ID
        self._qss_cache: Dict[str, str] = {}
        self._base_cache: Optional[str] = None  # base.qss 原始文本（三主题共享，只读一次）
        # v1.3(P2-7): 外观模式与生效明暗（light/dark/system；默认 light，旧观感不变）
        self._mode: str = "light"
        self._dark: bool = False
        self._system_poll: Optional[QTimer] = None
        # v2.1(D-V21-11): 原生事件监听器 + 主题变更去抖定时器（仅 system 模式下装卸）
        self._native_filter: Optional[_SystemThemeEventFilter] = None
        self._theme_debounce: Optional[QTimer] = None
        self._theme_debounce_ms: int = 300
        self._last_theme_name: str = ""
        # v1.4.3「主题强调色色盘」：运行时自定义强调色（#RRGGBB，空=用主题默认）。
        # 不写入 THEME_DEFINITIONS，仅 _active_palette 组装时覆盖强调色系键。
        self._custom_accent: str = ""

    def _read_base_qss(self) -> str:
        """读取公共组件结构层 base.qss；缺失时返回空串（退化为单文件加载，不崩）。"""
        if self._base_cache is not None:
            return self._base_cache
        base_path = get_resource_path(self.BASE_QSS_FILE)
        text = ""
        try:
            if base_path.exists():
                text = base_path.read_text(encoding="utf-8")
        except Exception:
            text = ""
        self._base_cache = text
        return text

    def load_theme(self, theme_name: str) -> bool:
        """加载并应用指定主题。

        v1.2(D7): 合并加载 —— base.qss(公共结构) 在前，主题 qss(肤感) 在后；
        同一轮变量替换把 ${颜色}/${layout}/${font_family} 全部代入。
        v1.3(P2-7): ${...} 替换改读「活动色板」（浅色=colors / 深色=colors+colors_dark），
        深色热切换复用本方法（theme_changed 单参信号签名不变）。
        v1.9 A(D-V19-10): 入口处旧值归一（LEGACY_THEME_MAP）+ 未知值回落默认风格，
        归一后回写 GuiConfig.theme_name（下次 save 落新值，旧配置零断档）。
        """
        requested = theme_name
        theme_name = self.LEGACY_THEME_MAP.get(theme_name, theme_name)
        if theme_name not in self.THEME_DEFINITIONS:
            theme_name = self.DEFAULT_THEME_ID

        theme_def = self.THEME_DEFINITIONS[theme_name]
        qss_path = get_resource_path(theme_def["qss_file"])

        if theme_name in self._qss_cache:
            theme_qss = self._qss_cache[theme_name]
        elif qss_path.exists():
            theme_qss = qss_path.read_text(encoding="utf-8")
            self._qss_cache[theme_name] = theme_qss
        else:
            theme_qss = self._build_default_qss(theme_def)
            self._qss_cache[theme_name] = theme_qss

        # v1.2(D7): base 公共层 + 主题肤感层（base 缺失时退回旧单文件行为）
        base_qss = self._read_base_qss()
        qss = f"{base_qss}\n{theme_qss}" if base_qss else theme_qss

        # v1.3(P2-7): 替换配色 / layout token 变量 —— 用当前生效模式下的活动色板
        # v1.4.3: 传入 theme_name 以便自定义强调色按主题/模式派生
        palette = self._active_palette(theme_def, theme_name)
        for key, value in palette.items():
            qss = qss.replace(f"${{{key}}}", value)

        # 替换字体变量（v1.9 B/D-V19-05：单一收口 fonts.font_family_chain）
        # ${font_family} 作用正文位；${font_title} 作用标题位（粉圆仅标题 —— Q-E4）
        # 注意：QSS 里必须用「QSS 出口」qss_font_family（逐族引号 + 通用族裸写）——
        # 模板若写成 font-family: "${font_family}"; 会把整条链当成单个族名（既有缺陷）。
        font_choice = self._font_choice()
        body_chain = fonts.font_family_chain(font_choice, "body")
        title_chain = fonts.font_family_chain(font_choice, "title")
        qss = qss.replace("${font_family}", fonts.qss_font_family(font_choice, "body"))
        qss = qss.replace("${font_title}", fonts.qss_font_family(font_choice, "title"))

        # 应用 QSS
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
            font = QFont(body_chain.split(",")[0].strip(), 10)
            app.setFont(font)

        self._current_theme = theme_name
        # v1.9 A(D-V19-10): 归一值回写配置（仅当用户存档是旧值/未知值时落盘）
        if requested != theme_name:
            self._persist_theme_choice(theme_name)
        self.theme_changed.emit(theme_name)
        return True

    def _persist_theme_choice(self, theme_name: str) -> None:
        """把归一后的 theme id 回写 GuiConfig（best-effort，失败不影响渲染）。"""
        try:
            from gui.config import GuiConfig
            cfg = GuiConfig.load()
            if getattr(cfg, "theme_name", None) != theme_name:
                cfg.theme_name = theme_name
                cfg.save()
        except Exception:
            pass

    @classmethod
    def normalize_theme_id(cls, theme_name: str) -> str:
        """旧值归一 + 未知值回落默认风格（UI 侧取当前风格 id 用）。"""
        tid = cls.LEGACY_THEME_MAP.get(theme_name or "", theme_name or "")
        return tid if tid in cls.THEME_DEFINITIONS else cls.DEFAULT_THEME_ID

    @classmethod
    def is_dark_locked(cls, theme_name: str) -> bool:
        """C 风格（ui_night）强制深色查询（Q-E2）。"""
        td = cls.THEME_DEFINITIONS.get(theme_name or "", {})
        return bool(td.get("dark_locked"))

    @classmethod
    def is_brand_persona(cls, theme_name: str) -> bool:
        """D 风格（ui_whale）文案随人设查询（Q-E3）。"""
        td = cls.THEME_DEFINITIONS.get(theme_name or "", {})
        return bool(td.get("brand_persona"))

    def is_dark_effective(self) -> bool:
        """当前是否生效深色色板（v1.9 A/D-V19-13：⚠-3 修正的消费侧查询口）。

        信号签名零变更；仅供 page_editor 等消费侧替代历史硬编码
        `theme_name == "cute"` 的明暗判断。
        """
        return bool(self._dark)

    def _font_choice(self) -> str:
        """当前界面字体选择（v1.9 B/D-V19-05）。

        读取 GuiConfig.font_family（设置页即时生效路径：写 cfg → save → load_theme，
        故此处能读到新值）；读不到配置时回落默认字体（资源圆体）—— 契约零变更，
        不新增入参。
        """
        try:
            from gui.config import GuiConfig
            return GuiConfig.load().font_family or fonts.default_font_choice()
        except Exception:
            return fonts.default_font_choice()

    # ------------------------------------------------------------------
    # v1.3(P2-7): 外观模式（light/dark/system）+ 活动色板
    # ------------------------------------------------------------------
    def set_theme_mode(self, mode: str) -> bool:
        """设置外观模式：light / dark / system。

        - mode 非法值回落 light；system 时安装原生事件监听（即时感知主题变更）
          并以 30s 低频轮询 winreg AppsUseLightTheme 兜底（v2.1 D-V21-11），
          感知变化即热切换（内部重入 load_theme current_theme，复用 theme_changed
          单参信号，**不改信号签名**）。
        - 保存由调用方（设置页）负责；本方法只负责引擎侧即时生效。
        """
        if mode not in ("light", "dark", "system"):
            mode = "light"
        self._mode = mode
        if mode == "system":
            # v2.1(D-V21-11): 事件监听优先（即时）+ 30s 低频轮询兜底
            self._install_system_listener()
            self._start_system_poll()
        else:
            self._uninstall_system_listener()
            self._stop_theme_debounce()
            self._stop_system_poll()
        self._sync_dark_effective()
        self._last_theme_name = self._current_theme
        # 已加载过主题 -> 重入 load_theme 全量重建（QSS + 取色都走活动色板）
        if self._last_theme_name in self.THEME_DEFINITIONS:
            return self.load_theme(self._last_theme_name)
        return True

    def mode(self) -> str:
        return self._mode

    def _resolve_dark_effective(self) -> bool:
        """按当前模式解析「是否应使用深色色板」。"""
        if self._mode == "dark":
            return True
        if self._mode == "light":
            return False
        # system：读取失败时维持上次有效值（不闪变）
        val = _read_system_light_theme()
        if val is None:
            return self._dark
        return not val

    def _sync_dark_effective(self) -> None:
        self._dark = self._resolve_dark_effective()

    def _active_palette(self, theme_def: Dict, theme_name: Optional[str] = None) -> Dict[str, str]:
        """活动色板：浅色=colors；深色={**colors, **colors_dark}（缺键回落 colors）。

        v1.4.3：若设置了自定义强调色（_custom_accent 合法），在主题默认色板上 merge
        主色派生出的强调色系 dict（运行时覆盖，不修改 THEME_DEFINITIONS 原数据）。
        """
        colors = theme_def.get("colors", {})
        if not self._dark:
            merged = dict(colors)
        else:
            dark = theme_def.get("colors_dark", {})
            merged = dict(colors)
            if dark:
                merged.update(dark)
        if self._custom_accent and _is_valid_accent_hex(self._custom_accent):
            mode = "dark" if self._dark else "light"
            name = theme_name or self._current_theme
            derived = derive_accent_palette(self._custom_accent, name, mode)
            if derived:
                merged.update(derived)
        return merged

    # ------------------------------------------------------------------
    # v1.4.3「主题强调色色盘」：自定义强调色存取（运行时覆盖色板）
    # ------------------------------------------------------------------
    def set_custom_accent(self, value: Optional[str]) -> None:
        """设置自定义强调色（#RRGGBB）；空串/None/非法值回落主题默认（清空）。"""
        if not value or not isinstance(value, str) or not value.strip():
            self._custom_accent = ""
            return
        if _is_valid_accent_hex(value):
            self._custom_accent = value.strip()
        else:
            # 非法值：安全回落默认，不抛异常
            self._custom_accent = ""

    def custom_accent(self) -> str:
        """返回当前生效的自定义强调色（空串=用主题默认）。"""
        return self._custom_accent

    def _start_system_poll(self) -> None:
        if self._system_poll is not None:
            return
        try:
            timer = QTimer(self)
            # v2.1(D-V21-11/D-3 回落): 事件监听为主，轮询由 5min 收紧至 30s 兜底
            timer.setInterval(30 * 1000)
            timer.timeout.connect(self._poll_system_mode)
            timer.start()
            self._system_poll = timer
        except Exception:
            self._system_poll = None

    # ------------------------------------------------------------------
    # v2.1(D-V21-11): 原生事件监听安装/卸载 + 去抖（仅 system 模式）
    # ------------------------------------------------------------------
    def _install_system_listener(self) -> None:
        """安装 Windows 主题变更原生事件监听；失败静默（回落 30s 轮询）。"""
        if self._native_filter is not None:
            return
        try:
            app = QApplication.instance()
            if app is None:
                return
            flt = _SystemThemeEventFilter(self)
            app.installNativeEventFilter(flt)
            self._native_filter = flt
        except Exception:
            self._native_filter = None

    def _uninstall_system_listener(self) -> None:
        """卸载原生事件监听（无监听/失败均静默，不抛）。"""
        flt, self._native_filter = self._native_filter, None
        if flt is None:
            return
        try:
            app = QApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(flt)
        except Exception:
            pass

    def _on_system_theme_message(self) -> None:
        """原生消息命中后的回调（去抖后转调既有 ``_poll_system_mode``）。"""
        self._schedule_theme_poll()

    def _schedule_theme_poll(self) -> None:
        """去抖调度：300ms 内的多次消息合并为一次 ``_poll_system_mode``。"""
        try:
            timer = self._theme_debounce
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(int(getattr(self, "_theme_debounce_ms", 300)))
                timer.timeout.connect(self._poll_system_mode)
                self._theme_debounce = timer
            timer.start()
        except Exception:
            # 定时器不可用 → 直接轮询一次（不崩，行为仍正确）
            try:
                self._poll_system_mode()
            except Exception:
                pass

    def _stop_theme_debounce(self) -> None:
        timer = self._theme_debounce
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _stop_system_poll(self) -> None:
        timer, self._system_poll = self._system_poll, None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _poll_system_mode(self) -> None:
        """system 模式轮询回调：系统深浅变化 -> 热切换（活动色板 + 信号广播）。"""
        if self._mode != "system":
            return
        before = self._dark
        self._sync_dark_effective()
        if self._dark != before and self._current_theme in self.THEME_DEFINITIONS:
            self.load_theme(self._current_theme)

    def get_color(self, color_key: str, fallback: Optional[str] = None) -> str:
        """获取当前主题的活动色板配色值（供代码中动态使用）。

        v1.3(P2-7): 改读活动色板 —— 深色模式下优先返回 colors_dark 的值。

        fallback: 主题中未定义该 key 时使用的默认色；
        未提供 fallback 时按原有行为返回 "#000000"。
        """
        theme_def = self.THEME_DEFINITIONS.get(self._current_theme, {})
        palette = self._active_palette(theme_def, self._current_theme)
        color = palette.get(color_key)
        if color is not None:
            return color
        return fallback if fallback is not None else "#000000"

    def get_layout_token(self, key: str, fallback: Optional[int] = None) -> Optional[int]:
        """获取当前主题的数值型 layout token（间距/圆角 px 数值，供代码 setSpacing 等使用）。

        v1.3(P2-7): 色板与 layout 一并取活动色板（layout token 深浅两套同值）。

        取值顺序：theme_def["layout"][key] → colors 里 "Npx" 字符串解析 → fallback。
        """
        theme_def = self.THEME_DEFINITIONS.get(self._current_theme, {})
        layout = theme_def.get("layout", {})
        if isinstance(layout, dict) and key in layout:
            return int(layout[key])
        palette = self._active_palette(theme_def)
        raw = palette.get(key)
        if raw is not None:
            m = re.search(r"\d+", str(raw))
            if m:
                return int(m.group(0))
        return fallback

    def current_theme_name(self) -> str:
        return self._current_theme

    @staticmethod
    def _default_qss_font_family(theme_def: Dict) -> str:
        """``_build_default_qss`` 用的 font-family 值（**QSS 形态**）。

        形态与 ``fonts.qss_font_family`` 一致：逐族加双引号、通用族（``sans-serif``）
        裸写。首族沿用原语义（``theme_def["font"]["family"]`` 的首族，缺省 ``Segoe UI``），
        其后接 ``fonts`` 家族链（含图标回退族 ``remixicon``，位于 generic 之前），去重保序。

        纯静态：只读入参 + 模块级 ``fonts``，不依赖实例状态。
        """
        chain = fonts.qss_font_family(fonts.default_font_choice(), "body")
        tokens = [t.strip() for t in chain.split(",") if t.strip()]
        raw = str((theme_def.get("font") or {}).get("family") or "").strip()
        head = raw.split(",")[0].strip() if raw else "Segoe UI"
        head_token = f'"{head}"' if head else ""
        if head_token and head_token not in tokens:
            tokens.insert(0, head_token)
        return ", ".join(tokens)

    @staticmethod
    def _build_default_qss(theme_def: Dict) -> str:
        """当 QSS 文件缺失时，构建极简默认样式。"""
        c = theme_def.get("colors", {})
        return f"""
QWidget {{
    background-color: {c.get('bg', '#FFFFFF')};
    color: {c.get('text', '#000000')};
    font-family: {ThemeEngine._default_qss_font_family(theme_def)};
}}
QPushButton {{
    background-color: {c.get('primary', '#2196F3')};
    color: white;
    border: none;
    border-radius: {c.get('radius_md', '6px')};
    padding: 6px 16px;
}}
QPushButton:hover {{
    background-color: {c.get('primary_dark', '#1976D2')};
}}
QPushButton:disabled {{
    background-color: #E0E0E0;
    color: #9E9E9E;
}}
QTextEdit, QPlainTextEdit {{
    background-color: {c.get('bg_card', '#FAFAFA')};
    border: 1px solid {c.get('border', '#E0E0E0')};
    border-radius: {c.get('radius_sm', '4px')};
    padding: 6px;
}}
QListWidget::item:selected {{
    background-color: {c.get('primary', '#2196F3')};
    color: white;
}}
QStatusBar {{
    background-color: {c.get('bg_card', '#FAFAFA')};
    border-top: 1px solid {c.get('border', '#E0E0E0')};
}}
"""


# ======================================================================
# v1.4.3「主题强调色色盘」：主色 HSL 派生强调色系语义键
# ----------------------------------------------------------------------
# 用户选一主色（#RRGGBB），由 HSL 分解派生覆盖强调色系语义键：
#   accent / focus_accent / accent_light / text_on_accent / bg_light /
#   bubble_user_bg / bubble_user_text / chat_border
# 含深色模式变体（主色提明度提饱和，浅底键转为暗色调和）；不改
# THEME_DEFINITIONS 原数据，仅在 _active_palette 运行时覆盖。
# ======================================================================

def _is_valid_accent_hex(value: str) -> bool:
    """校验 #RRGGBB（6 位十六进制，大小写均可）。"""
    return isinstance(value, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", value.strip()) is not None


def _hex_to_hsl(hex_str: str):
    """#RRGGBB -> (h:0-360, s:0-1, l:0-1)。"""
    hx = hex_str.strip().lstrip("#")
    r = int(hx[0:2], 16) / 255.0
    g = int(hx[2:4], 16) / 255.0
    b = int(hx[4:6], 16) / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2.0
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6.0 if g < b else 0.0)
        elif mx == g:
            h = (b - r) / d + 2.0
        else:
            h = (r - g) / d + 4.0
        h /= 6.0
    return (h * 360.0, s, l)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """(h:0-360, s:0-1, l:0-1) -> #RRGGBB。参数自动夹取合法区间。"""
    h = ((h % 360.0) + 360.0) % 360.0
    s = max(0.0, min(1.0, s))
    l = max(0.0, min(1.0, l))
    if s == 0.0:
        v = int(round(l * 255.0))
        return f"#{v:02X}{v:02X}{v:02X}"
    c = (1.0 - abs(2.0 * l - 1.0)) * s
    hp = h / 60.0
    x = c * (1.0 - abs(hp % 2.0 - 1.0))
    if hp < 1.0:
        r1, g1, b1 = c, x, 0.0
    elif hp < 2.0:
        r1, g1, b1 = x, c, 0.0
    elif hp < 3.0:
        r1, g1, b1 = 0.0, c, x
    elif hp < 4.0:
        r1, g1, b1 = 0.0, x, c
    elif hp < 5.0:
        r1, g1, b1 = x, 0.0, c
    else:
        r1, g1, b1 = c, 0.0, x
    m = l - c / 2.0
    r = int(round((r1 + m) * 255.0))
    g = int(round((g1 + m) * 255.0))
    b = int(round((b1 + m) * 255.0))
    return f"#{r:02X}{g:02X}{b:02X}"


def _relative_luminance(hex_str: str) -> float:
    """WCAG 相对亮度（0=黑，1=白），用于 text_on_accent 对比度决策。"""
    hx = hex_str.strip().lstrip("#")

    def _lin(ch: str) -> float:
        c = int(ch, 16) / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _lin(hx[0:2]), _lin(hx[2:4]), _lin(hx[4:6])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def derive_accent_palette(accent_hex: str, theme_name: str = "cute", mode: str = "light") -> Dict[str, str]:
    """由主色 HSL 派生强调色系语义键 dict（浅/深两套）。

    覆盖键：accent / focus_accent / accent_light / text_on_accent /
    bg_light / bubble_user_bg / bubble_user_text / chat_border。

    - 浅色：主色尽量保留用户所选（仅保对比下限），浅底键按主色低饱和浅色调；
    - 深色：主色提明度提饱和以在深背景显眼，浅底键转为暗色调和；
    - text_on_accent：依据主色相对亮度自动选黑/白，保证对比度。

    accent_hex 非法时返回空 dict（调用方回落主题默认）。
    """
    if not _is_valid_accent_hex(accent_hex):
        return {}
    h, s, l = _hex_to_hsl(accent_hex)
    dark = (mode == "dark")
    if dark:
        # 主色：提亮提饱和，确保在深色背景上显眼可读
        a_l = max(0.60, min(0.72, 0.66 if l < 0.55 else l))
        a_s = max(0.55, min(0.95, s if s > 0.20 else 0.70))
        accent = _hsl_to_hex(h, a_s, a_l)
        focus = _hsl_to_hex(h, min(0.98, a_s + 0.05), min(0.80, a_l + 0.08))
        accent_light = _hsl_to_hex(h, min(0.60, s * 0.7), 0.24)
        bg_light = _hsl_to_hex(h, min(0.40, s * 0.6), 0.17)
        chat_border = _hsl_to_hex(h, min(0.50, s * 0.6), 0.32)
    else:
        # 主色：保留用户所选，仅夹取对比下限（不至于过亮/过暗）
        a_l = max(0.40, min(0.60, l))
        a_s = max(0.30, min(0.90, s if s > 0.05 else 0.45))
        accent = _hsl_to_hex(h, a_s, a_l)
        focus = _hsl_to_hex(h, min(0.95, a_s + 0.05), min(0.70, a_l + 0.08))
        accent_light = _hsl_to_hex(h, min(0.50, s * 0.7), 0.90)
        bg_light = _hsl_to_hex(h, min(0.40, s * 0.6), 0.96)
        chat_border = _hsl_to_hex(h, min(0.50, s * 0.6), 0.85)
    # 主色上文字：相对亮度 >= 0.5 用黑字，否则白字（保证对比度）
    # 阈值 0.1791 = WCAG 黑白对比度交叉点（(L+0.05)^2 = 1.05*0.05）；旧值 0.5 过松，
    # 会让中等亮度主色（如 #FF6B9D 亮度 0.28）误选白字，对比度仅 ~2.7。
    text_on = "#000000" if _relative_luminance(accent) >= 0.1791 else "#FFFFFF"
    return {
        "accent": accent,
        "focus_accent": focus,
        "accent_light": accent_light,
        "text_on_accent": text_on,
        "bg_light": bg_light,
        "bubble_user_bg": accent,
        "bubble_user_text": text_on,
        "chat_border": chat_border,
    }


# ======================================================================
# v1.3(P2-7): colors_dark 自动装配 + 语义色键两套注册
# ----------------------------------------------------------------------
# - colors_dark 与 colors「同键」（不得缺键）：装配期遍历 colors 每个键，
#   深色覆盖优先、未覆盖键（layout token / 渐变项）自动回落同值。
# - 新增语义色键（chat_bg/chat_border/bubble_*/accent_light 等既有 get_color
#   fallback 用法）正式补注册进三主题 colors 与 colors_dark（B8 双套注册），
#   使深色模式下气泡/浮窗/输入区表面能随活动色板切换。
# ======================================================================

# 每主题深色覆盖（覆盖 colors 里需要翻转的颜色键；layout token 不写即沿用）
_DARK_OVERRIDES: Dict[str, Dict[str, str]] = {
    "cute": {
        "primary": "#D96B8F", "primary_dark": "#C24E79",
        "secondary": "#3B2C34", "accent": "#E98FAF",
        "bg": "#231A20", "bg_card": "#2E222A",
        "text": "#F2E7EC", "text_secondary": "#BBA6AF",
        "border": "#4A3844", "shadow": "rgba(0,0,0,0.4)",
        "text_on_accent": "#FFFFFF",
        "bg_light": "#3A2A33",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "surface_muted": "#2A1F26", "text_hint": "#9D8893",
        "divider": "#45323F", "focus_accent": "#FF9EB5",
        "pet_bubble_bg": "#2E222A",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
    },
    "minimal": {
        "primary": "#3E8FE0", "primary_dark": "#2E7AC8",
        "secondary": "#2F4858", "accent": "#5A9CF8",
        "bg": "#1D1F24", "bg_card": "#272A31",
        "text": "#ECEFF4", "text_secondary": "#A6ADBB",
        "border": "#3B404C", "shadow": "rgba(0,0,0,0.4)",
        "text_on_accent": "#FFFFFF",
        "bg_light": "#2E3440",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "surface_muted": "#24262D", "text_hint": "#8C94A6",
        "divider": "#363B46", "focus_accent": "#6CA8FA",
        "pet_bubble_bg": "#272A31",
        "state_ok": "#4FCE8F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
    },
    "maid": {
        "primary": "#F0679A", "primary_dark": "#D24E80",
        "secondary": "#3B2730", "accent": "#FF8FB0",
        "bg": "#241820", "bg_card": "#31222B",
        "text": "#F5E7EE", "text_secondary": "#C2A7B4",
        "border": "#523645", "shadow": "rgba(0,0,0,0.42)",
        "text_on_accent": "#FFFFFF",
        "bg_light": "#402B36",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "surface_muted": "#2C1D26", "text_hint": "#A98899",
        "divider": "#4C3442", "focus_accent": "#FF9EB5",
        "pet_bubble_bg": "#31222B",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
    },
    # ---- v1.9 A 块（D-V19-15，PM 已复核定稿）：四风格深色变体 ----
    # A 极简·深：冷灰深，用户气泡「同族深底 + 同族浅字」（PM 阻塞项已修）
    "ui_minimal": {
        "primary": "#FF5E93", "primary_dark": "#E0447A", "secondary": "#2E2129",
        "accent": "#FF5E93",
        # accent_text（深色态）：vs bg(#17171A)=5.476
        "accent_text": "#C57792",
        "bg": "#17171A", "bg_card": "#1F1F23", "surface_muted": "#242429",
        "border": "#303036", "text": "#EDEDF0", "text_secondary": "#9A9AA2",
        "text_hint": "#7E7E88", "divider": "#2A2A30",
        "shadow": "rgba(0,0,0,0.40)",
        "bg_light": "#2E2129", "focus_accent": "#FF7AA6",
        # text_on_accent 不写死极值，交 derive_accent_palette 按主色明度自动选字（D-V19-15②）
        "text_on_accent": "#1C1C1E",
        "accent_light": "#4A2434",
        "bubble_user_bg": "#3A2430", "bubble_user_text": "#F2DCE6",
        "bubble_ai_bg": "#1C1C21", "bubble_ai_text": "#E8E8EC",
        "chat_bg": "#17171A", "chat_border": "#34343B",
        "pet_bubble_bg": "#242429",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
        # v2.1(D-V21-16)：信息 / 警示语义色（深色变体，对比度 ≥3:1）
        "info": "#6FA8DC", "warning": "#E2A445",
    },
    # B 奶油·深：暖棕深
    "ui_cream": {
        "primary": "#FF9FB2", "primary_dark": "#EF8497", "secondary": "#38292B",
        "accent": "#FF9FB2",
        # accent_text（深色态）：沿用本主题浅色主色（与 minimal/whale 同惯例），
        # vs bg(#201A17)=7.949；既是主题本征粉、又天然满足「非鲜红」。
        "accent_text": "#FF8FA3",
        "bg": "#201A17", "bg_card": "#2A2320", "surface_muted": "#312925",
        "border": "#453A33", "text": "#F3E9E3", "text_secondary": "#B9A79C",
        "text_hint": "#9A8072", "divider": "#3B322C",
        "shadow": "rgba(0,0,0,0.42)",
        "bg_light": "#38292B", "focus_accent": "#FFB3C2",
        "text_on_accent": "#FFFFFF",
        "accent_light": "#4A2F34",
        "bubble_user_bg": "#4A2F34", "bubble_user_text": "#F7E4E8",
        "bubble_ai_bg": "#2A2320", "bubble_ai_text": "#EFE3DC",
        "chat_bg": "#241D1A", "chat_border": "#4E4038",
        "pet_bubble_bg": "#312925",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
        # v2.1(D-V21-16)：信息 / 警示语义色（深色变体，暖调）
        "info": "#7FB0D8", "warning": "#E3A94F",
    },
    # C 夜间：colors_dark == colors（自身即深色；dark_locked）—— 全键同值以免被
    # _SEMANTIC_DARK_DEFAULTS 的默认粉色语义键覆盖。
    "ui_night": {
        "primary": "#FF6B9D", "primary_dark": "#E0527F", "secondary": "#3A2430",
        "accent": "#FF6B9D",
        # accent_text：ui_night 全键同值不变式，深色覆盖与浅色取同值
        "accent_text": "#FB6F9E",
        "bg": "#131114", "bg_card": "#1C1920", "surface_muted": "#211D26",
        "border": "#2C2733", "text": "#F2EFF5", "text_secondary": "#918A9C",
        "text_hint": "#6E6878", "divider": "#262230",
        "shadow": "0 2px 12px rgba(0,0,0,0.35)",
        "bg_light": "#3A2430", "focus_accent": "#FF6B9D",
        "text_on_accent": "#1C1920",
        "accent_light": "#3A2430",
        "bubble_user_bg": "#2B2130", "bubble_user_text": "#F2EFF5",
        "bubble_ai_bg": "#1F1B24", "bubble_ai_text": "#F2EFF5",
        "chat_bg": "#131114", "chat_border": "#2C2733",
        "pet_bubble_bg": "#3A2430",
        "code_bg": "#16161B", "code_text": "#F2F2F5", "code_lang": "#9A9AA2",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
        # v2.1(D-V21-16)：信息 / 警示语义色（ui_night 全键同值，防被默认色覆盖）
        "info": "#6FB0E0", "warning": "#E0A84A",
    },
    # D 深海·深：深海深蓝
    "ui_whale": {
        "primary": "#4FC0DA", "primary_dark": "#3AA6C0", "secondary": "#12333E",
        "accent": "#4FC0DA",
        # accent_text（深色态）：沿用本主题浅色主色，vs bg(#0E1A21)=5.446
        "accent_text": "#2E9BB5",
        "bg": "#0E1A21", "bg_card": "#14232C", "surface_muted": "#182A34",
        "border": "#24404E", "text": "#E2F1F7", "text_secondary": "#8FAEBE",
        "text_hint": "#6B8C9D", "divider": "#1D3641",
        "shadow": "rgba(0,0,0,0.38)",
        "bg_light": "#12333E", "focus_accent": "#6AD2E8",
        "text_on_accent": "#12303F",
        "accent_light": "#16404D",
        "bubble_user_bg": "#12333E", "bubble_user_text": "#E2F1F7",
        "bubble_ai_bg": "#13242D", "bubble_ai_text": "#DCEDF5",
        "chat_bg": "#0F1D25", "chat_border": "#2A4A59",
        "pet_bubble_bg": "#182A34",
        "disabled_bg": "#3A3A3A", "disabled_text": "#8A8A8A",
        "state_ok": "#4FD18F", "state_warn": "#E8B04C",
        # v2.1(D-V21-17)：危险/破坏性操作语义色（深色变体，提亮红，与 state_warn 可区分）
        "state_danger": "#EE7A7A",
        # v2.1(D-V21-16)：信息 / 警示语义色（深色变体，海蓝深底协调）
        "info": "#5FC0DC", "warning": "#E0A94A",
    },
}

# 语义键浅色注册默认值（历史控件 fallback 值，现正式入库以支持深色）
_SEMANTIC_LIGHT_DEFAULTS: Dict[str, str] = {
    "accent_light": "#FFB6C1",
    "bubble_user_bg": "#FF9EB5",
    "bubble_ai_bg": "#FFFFFF",
    "bubble_user_text": "#FFFFFF",
    "bubble_ai_text": "#4A4A4A",
    "chat_bg": "#FFF8FA",
    "chat_border": "#FFE4EC",
    # v1.9 A：代码区（始终深色底 + 浅字的代码块约定），供新 QSS 走 token 无裸色
    "code_bg": "#2B2B33",
    "code_text": "#F8F8F2",
    "code_lang": "#A9A9B4",
    # v2.1(D-V21-16/域4 后续)：信息 / 警示语义色（辅助语义，背景对比度 ≥3:1）。
    # 与 state_ok/state_warn 家族邻近但独立键：state_* 为连接/运行态状态点，
    # info/warning 为内容/分组型语义色（记忆中心分组 Tab 等着色）。
    "info": "#2F6FB5",
    "warning": "#A96A12",
}

# 语义键深色注册默认值
_SEMANTIC_DARK_DEFAULTS: Dict[str, str] = {
    "accent_light": "#E8799E",
    "bubble_user_bg": "#D6517D",
    "bubble_ai_bg": "#32323A",
    "bubble_user_text": "#FFFFFF",
    "bubble_ai_text": "#EDEDED",
    "chat_bg": "#221D24",
    "chat_border": "#40323C",
    "code_bg": "#16161B",
    "code_text": "#F2F2F5",
    "code_lang": "#9A9AA2",
    # v2.1(D-V21-16/域4 后续)：信息 / 警示语义色（深色变体）
    "info": "#6FA8DC",
    "warning": "#E2A445",
}

# 每主题语义键个性覆盖（如 minimal 冷色）
_SEMANTIC_THEME_LIGHT: Dict[str, Dict[str, str]] = {
    "minimal": {
        "accent_light": "#90CAF9",
        "bubble_user_bg": "#4C8BF5",
        "chat_bg": "#F6F9FE",
        "chat_border": "#DDE7F5",
    },
    "maid": {
        "chat_bg": "#FFF4F8",
        "chat_border": "#FFDCE6",
    },
}
_SEMANTIC_THEME_DARK: Dict[str, Dict[str, str]] = {
    "minimal": {
        "accent_light": "#6CA8FA",
        "bubble_user_bg": "#3578E0",
        "chat_bg": "#191B20",
        "chat_border": "#3A414E",
    },
    "maid": {
        "chat_bg": "#20151C",
        "chat_border": "#523244",
    },
}


def _augment_theme_palettes() -> None:
    """给 THEME_DEFINITIONS 补 colors_dark（与 colors 同键）并注册语义键。"""
    for name, td in ThemeEngine.THEME_DEFINITIONS.items():
        colors = td["colors"]
        # 1) 语义键浅色入库
        sem_light = dict(_SEMANTIC_LIGHT_DEFAULTS)
        sem_light.update(_SEMANTIC_THEME_LIGHT.get(name, {}))
        for key, value in sem_light.items():
            colors.setdefault(key, value)
        # 2) 深色覆盖 = 每主题深色变体 + 语义键深色
        overrides = dict(_DARK_OVERRIDES.get(name, {}))
        sem_dark = dict(_SEMANTIC_DARK_DEFAULTS)
        sem_dark.update(_SEMANTIC_THEME_DARK.get(name, {}))
        for key, value in sem_dark.items():
            overrides.setdefault(key, value)
        # 3) colors_dark：遍历 colors 每键；覆盖优先，未覆盖沿用浅色值
        dark: Dict[str, str] = {}
        for key, value in colors.items():
            dark[key] = overrides.get(key, value)
        for key, value in overrides.items():
            dark.setdefault(key, value)
        td["colors_dark"] = dark


_augment_theme_palettes()


# ======================================================================
# v1.9 A(D-V19-11/Q-E2): C 深色夜间进出收口 helper（引擎 + 配置侧）
# ----------------------------------------------------------------------
# 进入 ui_night：记住原 theme_mode → 暂存 theme_mode_before_night →
#   theme_mode="dark" → set_theme_mode("dark")；
# 离开 ui_night：若暂存非空 → 恢复该值并 set_theme_mode(原值) → 清空暂存。
# 引擎侧零新增状态；UI 侧（外观模式下拉收起）由调用方处理。
# ======================================================================
def apply_night_lock(engine, cfg, theme_name: str) -> bool:
    """按 theme_name 是否为 C 深色夜间收口「强制深色 / 恢复原模式」。

    返回 True 表示当前处于深色锁定（调用方应收起外观模式选择器）。
    best-effort：engine / cfg 为 None 时安全返回。
    """
    locked = ThemeEngine.is_dark_locked(theme_name)
    if cfg is not None:
        if locked:
            # 首次进入才记住原模式（重进 C 风格不丢原设置）
            if not getattr(cfg, "theme_mode_before_night", ""):
                before = getattr(cfg, "theme_mode", "light") or "light"
                if before not in ("light", "dark", "system"):
                    before = "light"
                cfg.theme_mode_before_night = before
            cfg.theme_mode = "dark"
        else:
            before = getattr(cfg, "theme_mode_before_night", "") or ""
            if before:
                cfg.theme_mode = before
                cfg.theme_mode_before_night = ""
    if engine is not None and hasattr(engine, "set_theme_mode"):
        try:
            engine.set_theme_mode(getattr(cfg, "theme_mode", "dark") if cfg is not None else "dark")
        except Exception:
            pass
    return locked
