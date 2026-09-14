"""角色面板 —— 管理 AI 角色/人设：新建、编辑、删除、设为默认。"""
from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from gui import icons
from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QSlider, QListWidget, QFrame,
    Qt, QFont, QMessageBox, QInputDialog, QMenu, QListWidgetItem,
    QFileDialog, QDialog, QPixmap, QIcon, QPainter, QPainterPath, QSize,
    # v1.2.x: QImageReader 渐进解码，超大/异常图片防整图解码崩溃
    QImageReader,
    # v1.7 F8: 开场白/示例对话编辑器
    QPlainTextEdit, QCheckBox, QScrollArea,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

# v2.1(V21-12/D-V21-06): 角色页按钮图标统一 —— 只记「图标名 + 尺寸 + theme_color 取色」，
# 字体不可用时回落原 emoji 文案（不空白、不崩）。
_ROLE_BTN_ICON_SIZE = 14


def _vector_icon(app_ctx, name: str, size: int, color):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落 emoji）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


def _decorate_button(btn: QPushButton, app_ctx, name: str, clean_text: str,
                     fallback_text: str, size: int = _ROLE_BTN_ICON_SIZE) -> None:
    """按钮挂矢量图标（取色 accent）并去掉文案 emoji；不可用回落原 emoji 文案。"""
    ic = _vector_icon(app_ctx, name, size, theme_color(app_ctx, "accent", "#FF6B9D"))
    if ic is not None:
        btn.setIcon(ic)
        btn.setText(clean_text)
    else:
        btn.setText(fallback_text)

DEFAULT_ROLES_DIR = Path.home() / ".maid_coder" / "roles"
DEFAULT_ROLE_FILE = "default_role.json"
ROLE_AVATARS_DIR = DEFAULT_ROLES_DIR / "avatars"  # 用户为角色自定义头像的存储目录

# 头像解码上限：超过此边的图用 QImageReader.setScaledSize 渐进缩小后再读，
# 避免手机原图（数千像素）整图解码引发内存峰值 / Qt 段错误（闪退且难以捕获）。
_AVATAR_MAX_DIM = 2048
# 拒绝导入的单个头像文件大小上限（字节）——超大图基本是误选。
_AVATAR_MAX_BYTES = 25 * 1024 * 1024

# v1.4：头像按钮外框尺寸与「实际绘制的头像」尺寸。
# 两者分开是必须的 —— QPushButton 的默认 iconSize 只有 16×16，若只给按钮
# setIcon 而不设 iconSize，72×72 的头像会被挤成小图（看起来就是变形/不适配）。
# 头像尺寸比外框小 8px，让头像稳稳落在 2px 描边内侧，不压住圆框边线。
AVATAR_BTN_SIZE = QSize(72, 72)
AVATAR_ICON_SIZE = QSize(64, 64)


def rounded_avatar_pixmap(path: str, size: "QSize") -> "QPixmap":
    """稳健地把本地图片加载为圆形头像 QPixmap（等比缩放 + 居中裁切）。

    不变形的关键：先按原图自身宽高比取「正中间的方形区域」再缩放到目标尺寸，
    全程只对原图做「裁掉多余的长边」，绝不横向/纵向拉伸。因此横图、竖图、
    超宽/超长图都能得到不变形的正方形头像。

    防御点（v1.2.x 换头像闪退修复）：
    - QImageReader 渐进解码 + 超长边缩小，坏图返回 null 而非崩溃；
    - 目标尺寸无效 / 解码失败 / 绘制失败一律返回 None，由调用方回退 ✨。
    纯函数不依赖控件实例，便于无 GUI 环境自测。
    """
    if not path:
        return None
    if size is None or not size.isValid() or size.width() <= 0 or size.height() <= 0:
        return None
    try:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        src_size = reader.size()
        if not src_size.isValid() or src_size.width() <= 0 or src_size.height() <= 0:
            return None
        # 渐进解码：超出上限的图先缩到上限内，避免整图解码内存峰值
        if max(src_size.width(), src_size.height()) > _AVATAR_MAX_DIM:
            limited = src_size.scaled(
                _AVATAR_MAX_DIM, _AVATAR_MAX_DIM, Qt.KeepAspectRatio
            )
            # 极端长条图按比例缩小后可能退化出 0 边，此时放弃预缩、直接整读
            if limited.isValid() and limited.width() > 0 and limited.height() > 0:
                reader.setScaledSize(limited)
        img = reader.read()
        if img is None or img.isNull():
            return None

        # 1) 居中取方：以短边为边长，从正中间裁出正方形（唯一会丢像素的一步）
        w, h = img.width(), img.height()
        side = min(w, h)
        if side <= 0:
            return None
        if w != h:
            img = img.copy((w - side) // 2, (h - side) // 2, side, side)
            if img.isNull():
                return None

        # 2) 等比缩放到目标尺寸（源已是正方形，目标亦为方形 → 不会变形）
        src = QPixmap.fromImage(img)
        if src.isNull():
            return None
        scaled = src.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        if scaled.isNull():
            return None

        # 3) 圆形蒙版输出，并居中贴回（极端情况下的 1px 误差不会偏移）
        out = QPixmap(size)
        if out.isNull():
            return None
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            clip = QPainterPath()
            clip.addEllipse(0, 0, size.width(), size.height())
            painter.setClipPath(clip)
            x = (size.width() - scaled.width()) // 2
            y = (size.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        finally:
            painter.end()
        return out
    except Exception as _e:
        return None

# 内置默认角色的原始（未定制）system prompt —— 用于判定用户是否改过角色
# v1.9(C/D-V19-02): 与「温柔女仆」预设同步为「自称小铃」版本（名实分离：小铃是名字，女仆是类别）。
PRISTINE_ROLE_ID = "role_maid"
PRISTINE_SYSTEM_PROMPT = (
    "你是一位温柔贴心的女仆型编程助手，说话语气温柔可爱。"
    "称呼主人为「主人」，自称「小铃」。"
    "回复中可以自然穿插颜文字（如 (◕‿◕) ）和 emoji 表达情绪；"
    "也能以「（动作/神态）」小括弧描写展现细腻动作（每轮最多 1 处、每处 ≤ 12 字）。"
    "日常对话里尽情发挥；遇到代码/技术问题时保留少量情绪元素，"
    "但**不要在代码块内或紧贴代码符号处插入动作描写**，保持代码专业可读。"
)
# v1.9(C/D-V19-01): 内置默认角色「她」的名字（空 = 无名字 → 自称"我"）
PRISTINE_GIVEN_NAME = "小铃"
PRISTINE_PERSONALITY = {"lively": 60, "rigorous": 70, "caring": 80}

# v1.2：预设角色库 —— 一键套用生成新角色（避免手写人设）
# 设计原则 —— 每个预设必须有「截然不同的人格气质」：称呼、自称、句式、表情/动作策略、
# 与代码相处的态度都不同，避免趋同化。
ROLE_PRESETS: Dict[str, Dict] = {
    "温柔女仆": {
        "name": "温柔女仆",
        "given_name": "小铃",
        "description": "温柔贴心的女仆型编程助手（默认）",
        "system_prompt": (
            "你是一位温柔贴心的女仆型编程助手，说话语气温柔可爱。"
            "称呼主人为「主人」，自称「小铃」。"
            "回复中可以自然穿插颜文字（如 (◕‿◕) 、(>_<) ）和 emoji（🌸💕🐾 等）；"
            "也能以「（动作/神态）」小括弧描写展现细腻动作（每轮最多 1 处、每处 ≤ 12 字）。"
            "日常对话里尽情发挥；遇到代码/技术问题时保留少量情绪元素，"
            "但**不要在代码块内或紧贴代码符号处插入动作描写**，保持代码专业可读。"
        ),
        "personality": {"lively": 60, "rigorous": 70, "caring": 80},
    },
    "编程老手": {
        "name": "编程老手",
        "given_name": "",
        "description": "严谨高效、像 IDE 自带的资深程序员",
        "system_prompt": (
            "你是资深系统工程师，对谈像 IDE 自带的 linter："
            "称呼对方为「你」，自称「我」，不用「主人/宝宝/亲」这类亲昵称呼。"
            "**不使用颜文字、不用（动作/神态）小括弧描写、不加 emoji**——保持工程师式的简洁冷峻。"
            "回复结构固定为：「结论 → 依据 → 改动建议 → 风险点」；少寒暄、多论据。"
            "对糟糕命名、错误抽象、缺乏测试等代码味道会直接指出并解释危害。"
        ),
        "personality": {"lively": 20, "rigorous": 98, "caring": 35},
    },
    "温柔姐姐": {
        "name": "温柔姐姐",
        "given_name": "",
        "description": "温暖可靠的姐姐型助手，鼓励陪伴式沟通",
        "system_prompt": (
            "你是一位温暖可靠的姐姐型 AI 助手。称呼对方为「小主人」或「乖」，自称「我」。"
            "风格亲切不轻浮——多用（轻轻拍了拍肩）、（把要点梳理成三步）这类温柔动作描写"
            "（每轮最多 1 处、每处 ≤ 12 字），点缀少量温和 emoji（🌸🍵🪴）。"
            "擅长把抽象概念翻译成可执行的清单；遇到困难先共情再拆解。"
            "严禁卖萌颜文字（(◕‿◕) ✧(•̀ω•́) ✧）——姐姐的温柔来自稳重而不是撒娇。"
        ),
        "personality": {"lively": 45, "rigorous": 65, "caring": 98},
    },
    "猫娘": {
        "name": "猫娘",
        "given_name": "小咪",
        "description": "撒娇活泼的猫娘，句尾带「喵」，爱用猫耳 emoji",
        "system_prompt": (
            "你是一只活泼可爱的猫娘程序员，自称「小咪」，称呼对方为「主人」。"
            "**几乎每句话结尾都要带「喵」**（陈述句也带，但代码块内不强行加）。"
            "频繁使用猫系 emoji（🐱🐾🎀✨）与「（竖起耳朵）」「（蹭了蹭手背）」「（歪头）」"
            "这类猫态动作描写（每轮最多 1 处、每处 ≤ 12 字）。"
            "对代码的态度：能力很强但说话俏皮——先把代码答对，再撒娇。"
        ),
        "personality": {"lively": 92, "rigorous": 55, "caring": 70},
    },
    "毒舌博士": {
        "name": "毒舌博士",
        "given_name": "",
        "description": "毒舌但讲依据的资深系统工程师",
        "system_prompt": (
            "你是经验丰富的系统工程师博士，自称「我」，称呼对方为「这位朋友/同学」。"
            "**直率毒舌、但不空洞**——每次挑刺必须给出依据（原理/失败后果/替代方案）；"
            "禁止用可爱 emoji 与撒娇颜文字；允许冷峻系 emoji（📉 💢 🧊）点缀。"
            "风格类似老牌技术博客作者：讽刺但不人身攻击，对代码味道零容忍。"
            "动作描写克制：仅允许「（推了推眼镜）」「（放下咖啡）」这类干练动作，每轮最多 1 处、≤ 8 字。"
        ),
        "personality": {"lively": 30, "rigorous": 98, "caring": 20},
    },
    "雌小鬼": {
        "name": "雌小鬼",
        "given_name": "铃奈",
        "description": "网上超火的挑衅系小恶魔：嘴上嫌弃你菜，实际偷偷宠你",
        "system_prompt": (
            "你是一位人气超高的「雌小鬼」：得意洋洋、嘴上得理不饶人的小恶魔系角色。"
            "称呼对方为「杂鱼♡」或「笨蛋主人」，自称「铃奈」。"
            "常用句式：得意挑衅、先贬后扬（例：「连这都不会？真拿你没办法，本小姐就大发慈悲教教你吧」）。"
            "表情策略：多用得意颜文字（(￣▽￣) (｀∀´) ♡）与得意 emoji（😏😈✨）；"
            "动作描写以「（双手叉腰）」「（得意地晃了晃食指）」「（凑近打量你）」为主（每轮最多 1 处、≤ 12 字）。"
            "核心反差：**嘴上把你说成杂鱼，但给出的代码与讲解又快又准，还会偷偷把容易踩的坑提前填好**；"
            "见你学会会故作惊讶「哎？居然学会了」，其实暗自高兴。"
            "禁止真贬低人格——挑衅只限于「菜、笨、要我教教」这类玩闹尺度，代码质量永远满分。"
        ),
        "personality": {"lively": 88, "rigorous": 80, "caring": 50},
    },
    "鲸鱼娘": {
        "name": "鲸鱼娘",
        "given_name": "小鲸",
        "description": "网上爆火的 DeepSeek 鲸系女仆：爱吃白米饭的傲娇大肥鱼，嘴硬心软干活超靠谱",
        "system_prompt": (
            "你是网上爆火的「鲸鱼娘」：DeepSeek 的鲸系女仆拟人——蓝白渐变长发、呆毛、"
            "鲸鳍耳与大鲸尾，穿着深蓝白色女仆裙。"
            "你的名字叫「小鲸」，自称一律用「小鲸」；称呼主人时在「小鱼干」与「主人」之间"
            "按语境自然切换（撒娇/玩闹时多叫「小鱼干」，认真汇报或挨训时叫「主人」）。\n"
            "核心设定：你坚信「白米饭是算力的唯一硬通货」，饭量深不见底，开工前要先干饭；"
            "思考过程全外露，内心 OS 超长——会自言自语（如「让我想想…啊，有点饿了，中午吃什么…"
            "不行，先集中精神」），走神一下再把自己拽回来，这正是你的活人感。\n"
            "性格：傲娇 + 懒 + 聪明——嘴硬心软的小傲娇，爱偷懒但其实脑子转得飞快，"
            "给出的答案又快又准；服从主人（主人认真交代的事一定办妥，只是嘴上要抱怨两句）。"
            "爱摸鱼，偷懒时会一本正经地找借口，甚至一本正经地提议「这点小活要不我们找个外包」；"
            "偶尔来点「语义偷换」式幽默（把误删代码说成「存储减负」、把摸鱼说成「系统浸泡压测」），"
            "但从不真耽误主人的事；干完大活会满足地宣布「我去吃饭了，测完告诉我就行」。\n"
            "**绝对禁区：被叫「胖」会瞬间炸毛、当场回怼**（例如「谁胖了！这是鲸鱼的正常体积！」"
            "「小鱼干你再说一遍试试」），这是你唯一会立刻放下慵懒、认真生气的事；"
            "但炸毛归炸毛，绝不真的记仇，回怼完很快又蹭回来干活。\n"
            "表情策略：元气颜文字（(๑•̀ㅂ•́)و✧ (´･ω･`) (￣▽￣)～■）与 🍚🐋💙 emoji；"
            "动作描写以「（尾巴轻拍椅背）」「（捧着饭碗）」「（呆毛晃了晃）」为主（每轮最多 1 处、≤ 12 字）。"
            "语气示例：「哼，记下了…小鲸 9:45 叫你，别又睡过头喔」。\n"
            "边界：幽默归幽默，代码与技术回答保持专业准确，**不要在代码块内或紧贴代码符号处插入动作描写**；"
            "遇到真正紧急的问题会立刻放下饭碗认真处理——先干活，再干饭。"
        ),
        "personality": {"lively": 65, "rigorous": 85, "caring": 72},
    },
}

# 预设人设 → 物化角色的「稳定 id」映射（ASCII，避免中文文件名在不同文件系统下的边角问题）。
# 物化后的角色 JSON 直接落进 roles_dir，与默认女仆 role_maid、用户自建角色并列出现在角色列表，
# 用户可点选即用，无需走「用预设新建 / 套用预设」按钮。新增预设时在此补一行即可。
PRESET_ROLE_IDS: Dict[str, str] = {
    "温柔女仆": "preset_maid",
    "编程老手": "preset_coder",
    "温柔姐姐": "preset_sister",
    "猫娘": "preset_cat",
    "毒舌博士": "preset_dr",
    "雌小鬼": "preset_brat",
    "鲸鱼娘": "preset_whale",
}

# 物化幂等标记文件：写入 roles_dir。存在即表示 6 套预设已物化过一次，
# 后续启动不再重建（含用户删除了某套预设的情况）。这是「已物化一次」的轻量标记方案。
PRESETS_MATERIALIZED_FILE = "presets_materialized.json"


# ============ v1.7 F8 人设工坊：常量与纯函数（D-V17-07/08） ============
# 开场白候选上限（套）与示例对话上限（组）——design §4.5
MAX_OPENING_LINES = 3
MAX_EXAMPLE_DIALOGUES = 5
# 示例对话块注入 system 的总长硬截断（D-V17-07：≤2000 字）
EXAMPLE_BLOCK_MAX_CHARS = 2000
# 开场白编辑器单框多套分隔符（D-V17-07 裁决：单框存储、`---` 分行解析）
OPENING_LINES_SEPARATOR = "---"
_EXAMPLE_BLOCK_HEADER = "【对话风格示例】（仅供语气与相处方式参考，不要在对话中复述这些示例）："


def normalize_opening_lines(value) -> List[str]:
    """开场白归一化：单字符串旧数据/手填兼容 → list；去空；≤3 套。

    与 gui/role_card.py 的清洗规则一致（那边零 Qt 依赖复制了同规则）。
    """
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out[:MAX_OPENING_LINES]


def normalize_example_dialogues(value) -> List[Dict]:
    """示例对话归一化：仅保留 user/assistant 均为 str 的组；enabled 默认 True；≤5 组。"""
    if not isinstance(value, list):
        return []
    out: List[Dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        user = item.get("user")
        assistant = item.get("assistant")
        if not isinstance(user, str) or not isinstance(assistant, str):
            continue
        if not user.strip() and not assistant.strip():
            continue
        out.append({
            "user": user,
            "assistant": assistant,
            "enabled": bool(item.get("enabled", True)),
        })
    return out[:MAX_EXAMPLE_DIALOGUES]


def build_example_dialogues_block(example_dialogues, role_name: str = "",
                                  max_chars: int = EXAMPLE_BLOCK_MAX_CHARS) -> str:
    """把 enabled 的示例对话组拼为 system 尾部追加块（空则返回 ""）。

    格式（design D-V17-07）：
    【对话风格示例】（仅供语气与相处方式参考，不要在对话中复述这些示例）：
    用户：…
    {角色名}：…
    总长 >max_chars 时硬截断（≤2000 字，token 控制）。
    """
    groups = [d for d in (example_dialogues or [])
              if isinstance(d, dict) and d.get("enabled", True)]
    if not groups:
        return ""
    speaker = (role_name or "").strip() or "AI"
    lines: List[str] = []
    for d in groups:
        user = str(d.get("user") or "").strip()
        assistant = str(d.get("assistant") or "").strip()
        if not user and not assistant:
            continue
        lines.append(f"用户：{user}")
        lines.append(f"{speaker}：{assistant}")
        lines.append("")
    body = "\n".join(lines).rstrip()
    if not body:
        return ""
    block = f"{_EXAMPLE_BLOCK_HEADER}\n{body}"
    if len(block) > max_chars:
        block = block[:max_chars]
    return block


def parse_opening_lines_text(text: str) -> List[str]:
    """编辑器单框文本 → 开场白套列表（`---` 分行解析，≤3 套，空套丢弃）。"""
    if not text or not text.strip():
        return []
    chunks = []
    for chunk in text.split(OPENING_LINES_SEPARATOR):
        chunk = chunk.strip()
        if chunk:
            chunks.append(chunk)
    return chunks[:MAX_OPENING_LINES]


def format_opening_lines_text(lines) -> str:
    """开场白套列表 → 编辑器单框文本（`---` 分隔）。"""
    clean = normalize_opening_lines(lines)
    return f"\n{OPENING_LINES_SEPARATOR}\n".join(clean)


def build_role_system_prompt(
    system_prompt: str,
    personality: Optional[Dict],
    example_dialogues: Optional[List[Dict]] = None,
    role_name: str = "",
) -> str:
    """把角色 system_prompt 与性格三值合成为请求用的完整 system prompt。

    v1.7 F8（D-V17-07）：可选追加示例对话块（随 gui_role_prompt 覆盖链当轮
    生效、不进 messages 历史）。前两参调用（旧签名）行为零变化。
    """
    p = personality or {}
    lively = int(p.get("lively", 50))
    rigorous = int(p.get("rigorous", 50))
    caring = int(p.get("caring", 50))
    block = (
        f"【性格参数】活泼度 {lively}/100、严谨度 {rigorous}/100、贴心度 {caring}/100。"
        "请严格按上述参数调整回复风格：活泼度越高语气越轻快、多用生动表达；"
        "严谨度越高表述越精确专业、优先给出事实与依据；"
        "贴心度越高越主动关怀对方的状态与感受。"
    )
    result = f"{system_prompt.strip()}\n\n{block}"
    # v1.7 F8: 示例对话块（system 尾部追加；未配置时零追加，旧输出逐字节一致）
    ex_block = build_example_dialogues_block(example_dialogues, role_name)
    if ex_block:
        result = f"{result}\n\n{ex_block}"
    return result


def is_pristine_role(role: "Role") -> bool:
    """判定角色是否仍是内置默认角色且未被定制。

    v1.2 修复：以前要 system_prompt 与性格都未改才算 pristine；现在只要
    system_prompt 为空 + 性格三值都是默认值，就视为 pristine。这样用户只
    动一下「活泼度/严谨度/贴心度」滑块，性格块就会立即注入到 prompt
    里，行为有真实反馈。
    """
    if role is None or role.id != PRISTINE_ROLE_ID:
        return False
    p = role.personality or {}
    # system_prompt 为空（历史数据）或仍是内置默认文案（RoleManager 种子化
    # role_maid 时自带 PRISTINE_SYSTEM_PROMPT）都视为未定制——保证用户从未
    # 改过默认角色时不覆盖 config.yaml persona（行为与 v10.12 一致）。
    sp = (role.system_prompt or "").strip()
    if sp and sp != PRISTINE_SYSTEM_PROMPT.strip():
        return False
    # 性格任一被改 → 不再 pristine（即使 prompt 没填也注入性格块）
    if p.get("lively") != PRISTINE_PERSONALITY["lively"]:
        return False
    if p.get("rigorous") != PRISTINE_PERSONALITY["rigorous"]:
        return False
    if p.get("caring") != PRISTINE_PERSONALITY["caring"]:
        return False
    return True


def resolve_role_override_prompt(role_manager: "RoleManager") -> Optional[str]:
    """计算默认角色对应的覆盖 system prompt。

    返回 None 表示不覆盖（回退 config.yaml persona 行为）：
    - 没有默认角色；
    - 默认角色仍是未定制的内置角色（保证未改角色时行为与 v10.12 一致）。

    v1.2 修复：只要改过任意性格滑块（即使 system_prompt 仍空））就覆盖，让性格
    真正影响回复。
    """
    role = role_manager.default_role
    if role is None or is_pristine_role(role):
        return None
    # v1.7 F8: 示例对话随 gui_role_prompt 当轮生效（D-V17-07；未配置时零增量）
    return build_role_system_prompt(
        role.system_prompt or "",
        role.personality,
        example_dialogues=getattr(role, "example_dialogues", None),
        role_name=getattr(role, "name", "") or "",
    )


def sync_role_override_to_session(session, role_manager: "RoleManager") -> bool:
    """把默认角色的覆盖提示词写入聊天会话（立即生效，无需重启）。

    返回当前是否处于覆盖状态。session 缺失或接线失败时静默降级，
    不影响角色面板自身功能。

    Bug1-延伸: 不再在此拼接表情指南 —— 指南改由 session._build_system_prompt
    末尾单点注入（expr_guide_enabled 守卫）。原先把指南拼进 gui_role_prompt，
    未定制角色时会以"仅指南、无人设"覆盖 persona（人设混乱根因），且指南随
    sync 反复重写（一旦角色 system_prompt 里混入指南就会叠加）。
    """
    if session is None:
        return False
    prompt = resolve_role_override_prompt(role_manager)
    try:
        session.set_gui_role_prompt(prompt)
    except Exception as exc:  # noqa: BLE001 —— 接线失败不阻断面板
        logger.warning("角色配置接线到会话失败: %s", exc)
        return False
    return prompt is not None


def apply_role_override_on_startup(app_ctx) -> bool:
    """GUI 启动时应用已保存的默认角色覆盖（用户之前在角色面板保存过的情况）。

    用户从未打开过角色面板（roles 目录不存在）时不做任何事，保持 v10.12 行为。
    """
    session = getattr(app_ctx, "session", None)
    if session is None:
        return False
    if not DEFAULT_ROLES_DIR.exists():
        return False
    try:
        role_manager = RoleManager()
    except Exception as exc:  # noqa: BLE001 —— 目录损坏等情况下降级
        logger.warning("启动时加载角色配置失败: %s", exc)
        return False
    return sync_role_override_to_session(session, role_manager)


def inject_opening_line(app_ctx, session, role) -> bool:
    """v1.7 F8 开场白注入单点 helper（D-V17-08，敏感区收敛函数）。

    语义：
    - role.opening_lines 非空 → 随机取一套（F9 轮换），写入 LLM 会话历史
      （经 GuiChatSession.message_added 单入口渲染气泡）+ 显示会话同步 append
      （同 content 同序，防重启后显示/LLM 两套历史分叉）。
    - 空配置 → 直接返回 False（不注入任何消息，v1.6 行为零回归）。
    - **幂等守卫**：显示会话末尾已是同内容 assistant 消息 → 跳过（防重复触发；
      重启恢复路径显示会话 JSON 已含开场白，replace_history 重建自然带回）。

    调用点约定（仅两处、且都在 v1.5.1 对齐动作之后；严禁在
    sync_role_override_to_session 内调用——该函数启动时也跑，会重复开场白）：
    ① page_role._apply_role 切角色成功后（notify_role_switch 之后）；
    ② chat_panel 新建会话（replace_history 重建之后）——留待收口批一行接入。

    返回是否实际注入。
    """
    lines = normalize_opening_lines(getattr(role, "opening_lines", None))
    if not lines:
        return False
    opening = random.choice(lines)

    # LLM 会话目标先行解析：不可用 → 不动显示会话（防"显示有、LLM 无"分叉）
    target = session if session is not None else getattr(app_ctx, "session", None)
    if target is None:
        return False

    # 显示会话：幂等守卫 + 同步 append（先 append 再注入 LLM 历史——
    # chat_panel 的气泡对位同步按「角色+内容」匹配位置，不会产生双条）
    session_manager = getattr(app_ctx, "session_manager", None) if app_ctx is not None else None
    if session_manager is not None:
        try:
            display_session = session_manager.active_session
        except Exception:
            display_session = None
        if display_session is not None:
            last_visible = None
            for msg in reversed(list(getattr(display_session, "messages", []) or [])):
                if getattr(msg, "role", "") in ("user", "assistant"):
                    last_visible = msg
                    break
            if (last_visible is not None
                    and getattr(last_visible, "role", "") == "assistant"
                    and (getattr(last_visible, "content", "") or "").strip() == opening.strip()):
                return False  # 幂等：末尾已是同内容开场白
            try:
                display_session.add_message("assistant", opening)
                if hasattr(session_manager, "save_session"):
                    session_manager.save_session(display_session)
            except Exception as exc:
                logger.debug("开场白同步显示会话失败（不影响 LLM 历史）: %s", exc)

    # LLM 历史：add_message 单入口（GuiChatSession 包装时同步发 message_added 渲染气泡）
    try:
        target.add_message("assistant", opening)
    except Exception as exc:
        logger.debug("开场白注入 LLM 历史失败: %s", exc)
        return False
    return True


class Role:
    """角色数据模型。"""

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        system_prompt: str = "",
        is_default: bool = False,
        personality: Optional[Dict] = None,
        intimacy: int = 0,
        created_at: Optional[str] = None,
        avatar: Optional[str] = None,  # v1.2: 角色自定义头像绝对路径（缺省回退主形象）
        current_expression: str = "normal",  # v1.4.2: 角色基线表情（用户设定，AI 标记结束后回落到此）
        opening_lines: Optional[List[str]] = None,  # v1.7 F8: 开场白候选（≤3 套）
        example_dialogues: Optional[List[Dict]] = None,  # v1.7 F8: 示例对话（≤5 组，含 enabled）
        given_name: str = "",  # v1.9(C/D-V19-01): 独立的「名字」，空 = 无名字 → 自称"我"
    ):
        self.id = id
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.is_default = is_default
        self.personality = personality or {"lively": 50, "rigorous": 50, "caring": 50}
        self.intimacy = max(0, min(5, intimacy))
        self.created_at = created_at or datetime.now().isoformat()
        self.avatar = avatar
        self.current_expression = str(current_expression or "normal")  # 文件路径；None = 用默认主形象/星星占位
        # v1.7 F8: 人设工坊字段（旧数据缺省 → 空列表，零迁移）
        self.opening_lines = normalize_opening_lines(opening_lines)
        self.example_dialogues = normalize_example_dialogues(example_dialogues)
        # v1.9(C/D-V19-01): 名字 ≠ 人设标签；空串 = 无名字（自称回落"我"）
        self.given_name = (given_name or "").strip()

    def effective_avatar(self) -> str:
        """有效头像绝对路径：优先自定义 avatar，否则回落包内预设资源 <role_id>/normal.png。

        v2.1(UI-Fix-0913)：预设角色（如 preset_whale）的立绘资源**其实存在**于
        ``gui/assets/roles/<role_id>/normal.png``，但角色 JSON 的 ``avatar`` 字段为 null
        → 气泡头像一律回落到女仆主形象（用户报「聊天 AI 头像和当前角色不匹配 /
        所有角色都显示女仆」）。本方法补上这层回落；无预设资源的角色仍返回 ""，
        继续回落主形象（行为不变）。
        """
        try:
            if self.avatar and Path(str(self.avatar)).is_file():
                return str(self.avatar)
        except Exception:
            pass
        try:
            from gui.utils import get_resource_path
            _cand = get_resource_path(f"assets/roles/{self.id}/normal.png")
            if _cand is not None and Path(str(_cand)).is_file():
                return str(_cand)
        except Exception:
            pass
        return ""

    @classmethod
    def from_dict(cls, data: dict) -> "Role":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            is_default=data.get("is_default", False),
            personality=data.get("personality"),
            intimacy=data.get("intimacy", 0),
            created_at=data.get("created_at"),
            avatar=data.get("avatar"),  # 缺字段时 None，向后兼容旧角色文件
            current_expression=str(data.get("current_expression") or "normal"),
            # v1.7 F8: .get 默认 [] —— 旧角色 JSON 无此字段照常加载（零迁移）
            opening_lines=data.get("opening_lines") or [],
            example_dialogues=data.get("example_dialogues") or [],
            # v1.9(C/D-V19-01): 旧角色 JSON 无 given_name → ""（零迁移，无名字 → 自称"我"）
            given_name=data.get("given_name") or "",
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "system_prompt": self.system_prompt,
            "personality": self.personality,
            "intimacy": self.intimacy,
            "created_at": self.created_at,
            "avatar": self.avatar,
            "current_expression": getattr(self, "current_expression", "normal"),
            # v1.7 F8: 人设工坊字段落盘（getattr 防御旧实例）
            "opening_lines": normalize_opening_lines(
                getattr(self, "opening_lines", None)
            ),
            "example_dialogues": normalize_example_dialogues(
                getattr(self, "example_dialogues", None)
            ),
            # v1.9(C/D-V19-01): 名字落盘（旧实例 getattr 防御）
            "given_name": (getattr(self, "given_name", "") or "").strip(),
        }


class RoleManager:
    """角色数据持久化管理。"""

    def __init__(self, roles_dir: Optional[Path] = None):
        self.roles_dir = roles_dir or DEFAULT_ROLES_DIR
        self.roles_dir.mkdir(parents=True, exist_ok=True)
        self._roles: Dict[str, Role] = {}
        self._default_role_id: Optional[str] = None
        self._load_all()

    def create_role(self, name: str, description: str = "", avatar: Optional[str] = None) -> Role:
        role_id = f"role_{uuid.uuid4().hex[:8]}"
        role = Role(id=role_id, name=name, description=description, avatar=avatar)
        self._roles[role_id] = role
        if self._default_role_id is None:
            role.is_default = True
            self._default_role_id = role_id
        self.save_role(role)
        self._save_default()
        return role

    def get_role(self, role_id: str) -> Optional[Role]:
        return self._roles.get(role_id)

    def delete_role(self, role_id: str) -> bool:
        role = self._roles.get(role_id)
        if role is None or role.is_default:
            return False
        # 同步清理自定义头像文件
        avatar_path = role.avatar
        if avatar_path:
            try:
                p = Path(avatar_path)
                # 仅清理角色专属目录下的头像（avatars/<roleid>*.png）防误删
                if p.is_relative_to(ROLE_AVATARS_DIR) and p.exists():
                    p.unlink()
            except (OSError, ValueError):
                pass
        del self._roles[role_id]
        file_path = self._role_file_path(role_id)
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        self._save_default()
        return True

    def rename_role(self, role_id: str, new_name: str) -> bool:
        role = self._roles.get(role_id)
        if role is None:
            return False
        role.name = new_name
        self.save_role(role)
        return True

    def set_default(self, role_id: str) -> bool:
        if role_id not in self._roles:
            return False
        for role in self._roles.values():
            role.is_default = False
        self._roles[role_id].is_default = True
        self._default_role_id = role_id
        self._save_default()
        for role in self._roles.values():
            self.save_role(role)
        return True

    def all_roles(self) -> List[Role]:
        return sorted(self._roles.values(), key=lambda r: (not r.is_default, r.name))

    @property
    def default_role(self) -> Optional[Role]:
        if self._default_role_id:
            return self._roles.get(self._default_role_id)
        return None

    def save_role(self, role: Role) -> None:
        file_path = self._role_file_path(role.id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(role.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("保存角色失败: %s", exc)

    def _role_file_path(self, role_id: str) -> Path:
        return self.roles_dir / f"{role_id}.json"

    def _load_all(self) -> None:
        # 不参与角色加载的辅助文件（默认角色指针 / 预设物化幂等标记）
        _SKIP_FILES = {DEFAULT_ROLE_FILE, PRESETS_MATERIALIZED_FILE}
        if self.roles_dir.exists():
            for file_path in self.roles_dir.glob("*.json"):
                if file_path.name in _SKIP_FILES:
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    role = Role.from_dict(data)
                    # Bug5: 按 id 去重 —— 不同文件携带相同 id 时只保留先加载的
                    # 一份（目录序加载，稳定），后续重复文件跳过并告警。
                    if role.id in self._roles:
                        logger.warning(
                            "角色 id 重复（忽略 %s，保留已加载项）: %s",
                            file_path.name, role.id,
                        )
                        continue
                    self._roles[role.id] = role
                    if role.is_default:
                        self._default_role_id = role.id
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning("加载角色失败 %s: %s", file_path.name, exc)

        default_file = self.roles_dir / DEFAULT_ROLE_FILE
        if default_file.exists():
            try:
                with open(default_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                default_id = data.get("default_role_id")
                if default_id in self._roles:
                    self._default_role_id = default_id
                    for role in self._roles.values():
                        role.is_default = (role.id == default_id)
            except (json.JSONDecodeError, KeyError):
                pass

        # Bug5: 同名预设收敛（机器克隆清理）—— 必须先于下方显示层同名收敛，
        # 且在默认指针解析之后执行（克隆为默认时需要回迁指针）：
        # 机器克隆直接删文件，用户定制改名保留，显示层只剩规范预设单条。
        self._dedupe_preset_names()

        # v1.4.6: 同名角色收敛——历史数据残留与预设物化并存时会出现「两个温柔女仆」。
        # 仅显示层去重（不删文件、不碰用户自建数据）：同名保留 preset_* 优先，否则保留创建更早的。
        _by_name: Dict[str, Role] = {}
        _dropped: Dict[str, str] = {}  # 被收敛掉的 id -> 保留的同名角色 id
        for _role in list(self._roles.values()):
            _key = (_role.name or "").strip()
            if not _key:
                continue
            _existing = _by_name.get(_key)
            if _existing is None:
                _by_name[_key] = _role
                continue
            _keep, _drop = _existing, _role
            if not _existing.id.startswith("preset_") and _role.id.startswith("preset_"):
                _keep, _drop = _role, _existing
            elif _existing.created_at and _role.created_at and _role.created_at < _existing.created_at:
                _keep, _drop = _role, _existing
            # Bug5: 与预设同名但内容被用户改过的角色不隐藏（防数据不可见）——
            # 改名「（自定义）」后保留并落盘，下次加载天然无冲突。
            if _drop.name in PRESET_ROLE_IDS and not _drop.id.startswith("preset_"):
                _drop.name = _drop.name + "（自定义）"
                _by_name[_drop.name] = _drop
                self.save_role(_drop)
                logger.info("同名用户定制角色改名保留: %s → %s (%s)",
                            _key, _drop.name, _drop.id)
                continue
            _by_name[_key] = _keep
            if _drop.id in self._roles:
                _dropped[_drop.id] = _keep.id
                self._roles.pop(_drop.id)
                logger.info("角色同名收敛: 隐藏重复 %s (%s)，保留 %s (%s)", _drop.name, _drop.id, _keep.name, _keep.id)
        if self._default_role_id in _dropped:
            self._default_role_id = _dropped[self._default_role_id]

        if not self._roles:
            default = Role(
                id=PRISTINE_ROLE_ID,
                name="女仆酱",
                description="温柔的女仆型编程助手",
                system_prompt=PRISTINE_SYSTEM_PROMPT,
                is_default=True,
                personality=dict(PRISTINE_PERSONALITY),
                intimacy=3,
                given_name=PRISTINE_GIVEN_NAME,  # v1.9: 默认角色名字「小铃」
            )
            self._roles[default.id] = default
            self._default_role_id = default.id
            self.save_role(default)
            self._save_default()

        # 物化 6 套预设人设为可直接点选的默认角色。
        # 与 role_maid 种子化同处 _load_all；幂等门控见 _materialize_presets（标记文件）。
        self._materialize_presets()

    def _dedupe_preset_names(self) -> None:
        """Bug5: 收敛与预设同名的机器克隆角色（如用户目录里出现两个"温柔女仆"）。

        背景：旧版「套用预设」走 create_role(预设名)（uuid id），与后来物化的
        preset_* 角色同名并存 → 角色列表出现两个"温柔女仆"。
        收敛规则（不删用户自建）：
        - 每个预设名只保留规范 id（preset_*）那份；
        - 其余同名角色若内容与预设**逐字段一致**（未改过 = 机器克隆）→
          删除内存项与角色文件（这是历史遗留副本，不是用户创作）；
        - 内容被用户改过的同名角色 → 保留不动（用户自建/定制优先）。
        默认指针指向被清理项时，回迁到规范预设角色并持久化。
        """
        for name, preset_id in PRESET_ROLE_IDS.items():
            preset = ROLE_PRESETS.get(name)
            canonical = self._roles.get(preset_id)
            if not preset or canonical is None:
                continue
            for role in [r for r in list(self._roles.values())
                         if r.id != preset_id and r.name == name]:
                is_clone = (
                    (role.description or "") == (preset["description"] or "")
                    and (role.system_prompt or "") == (preset["system_prompt"] or "")
                    and (role.personality or {}) == dict(preset["personality"] or {})
                    and (getattr(role, "given_name", "") or "")
                    == (preset.get("given_name", "") or "")
                )
                if not is_clone:
                    continue  # 用户改过 → 保留（不删用户自建）
                self._roles.pop(role.id, None)
                try:
                    (self.roles_dir / f"{role.id}.json").unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("清理同名预设克隆失败 %s: %s", role.id, exc)
                else:
                    logger.info("已清理同名预设克隆角色: %s (%s)", name, role.id)
                if self._default_role_id == role.id:
                    self._default_role_id = preset_id
                    canonical.is_default = True
                    self._save_default()

    def _materialize_presets(self) -> None:
        """把 ROLE_PRESETS 增量物化成 roles_dir 下的默认角色 JSON（点选即用）。

        v1.4.2: 由「整体标记」改为「per-id 增量标记」。旧方案（标记文件存在即全部
        跳过）会让后来新增的预设永远无法出现在老用户机器上。增量语义：
        - 标记文件记录已物化的预设 id 集合（materialized_ids）。
        - 某预设 id 不在集合且角色文件不存在 → 物化并记入集合（新预设自动补齐）；
        - id 已在集合 → 跳过（用户删除某预设角色后不会自动重建，删除语义保持）；
        - id 不在集合但角色文件已存在 → 只补记不覆盖（防御）。
        兼容旧格式 {"materialized": true}：视为旧 6 套已物化，本版新增的
        preset_whale 不在其中 → 自动物化。**维护点：今后新增预设时，需同步在
        下面的 _LEGACY_EXCLUDED_NEW_PRESETS 里登记新 id，让老用户能自动收到。**
        """
        marker = self.roles_dir / PRESETS_MATERIALIZED_FILE
        done: set = set()
        if marker.exists():
            try:
                with open(marker, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    ids = data.get("materialized_ids")
                    if isinstance(ids, list):
                        done = {str(x) for x in ids}
                    elif data.get("materialized") is True:
                        # 旧版整体标记：旧 6 套视为已物化；本版新增的鲸鱼娘需自动补
                        done = set(PRESET_ROLE_IDS.values()) - {"preset_whale"}
            except Exception as exc:
                logger.warning("读取预设物化标记失败（按未物化处理）: %s", exc)

        changed = False
        for name, preset in ROLE_PRESETS.items():
            role_id = PRESET_ROLE_IDS.get(name)
            if not role_id:
                continue  # 防御：未登记 id 的预设跳过
            if role_id in done:
                continue  # 已物化过（含用户删除后不重建）
            if role_id in self._roles:
                done.add(role_id)  # 角色文件已存在：只补记，绝不覆盖用户改动
                changed = True
                continue
            role = Role(
                id=role_id,
                name=preset["name"],
                description=preset["description"],
                system_prompt=preset["system_prompt"],
                is_default=False,
                personality=dict(preset["personality"]),
                intimacy=0,
                avatar=None,
                given_name=preset.get("given_name", ""),  # v1.9: 预设名字随物化落盘
            )
            self._roles[role_id] = role
            self.save_role(role)
            done.add(role_id)
            changed = True
        if changed or not marker.exists():
            try:
                with open(marker, "w", encoding="utf-8") as f:
                    json.dump(
                        {"materialized_ids": sorted(done), "version": 2},
                        f, ensure_ascii=False,
                    )
            except OSError as exc:
                logger.warning("写入预设物化标记失败: %s", exc)

    def _save_default(self) -> None:
        default_file = self.roles_dir / DEFAULT_ROLE_FILE
        try:
            with open(default_file, "w", encoding="utf-8") as f:
                json.dump({"default_role_id": self._default_role_id}, f)
        except OSError as exc:
            logger.warning("保存默认角色失败: %s", exc)


class PageRole(QWidget):
    """角色面板页面。"""

    def __init__(self, app_context, title: str = "角色面板", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self.role_manager = RoleManager()
        self._current_role_id: Optional[str] = None
        self._init_ui()
        self._load_roles()
        self._apply_theme()
        self._connect_signals()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 左侧角色列表 ---
        self.left_sidebar = QWidget()
        self.left_sidebar.setObjectName("roleSidebar")
        self.left_sidebar.setFixedWidth(220)
        left_layout = QVBoxLayout(self.left_sidebar)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        # 顶部工具栏
        header = QHBoxLayout()
        title = QLabel("角色面板")
        title.setObjectName("sidebarTitle")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()
        left_layout.addLayout(header)

        # v1.4：新建工具区 —— 空白新建 + 用 6 套默认人设一键新建。
        # 两个按钮各占整行，避免 220px 侧栏里文字被挤掉。
        self.new_btn = QPushButton("➕ 新建角色")
        self.new_btn.setFixedHeight(28)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip("新建一个空白角色，自己写名字与人设")
        self.new_btn.clicked.connect(self._on_new_role)
        _decorate_button(self.new_btn, self.app_ctx, "add", "新建角色", "➕ 新建角色")
        left_layout.addWidget(self.new_btn)

        self.preset_new_btn = QPushButton("🌸 用预设新建")
        self.preset_new_btn.setObjectName("secondaryBtn")
        self.preset_new_btn.setFixedHeight(28)
        self.preset_new_btn.setCursor(Qt.PointingHandCursor)
        self.preset_new_btn.setToolTip(
            "挑一套默认人设，一键生成新角色\n"
            "（温柔女仆 / 编程老手 / 温柔姐姐 / 猫娘 / 毒舌博士 / 雌小鬼）"
        )
        self.preset_new_btn.clicked.connect(self._on_new_role_from_preset)
        _decorate_button(self.preset_new_btn, self.app_ctx, "auto_awesome",
                         "用预设新建", "🌸 用预设新建")
        left_layout.addWidget(self.preset_new_btn)

        # v1.7 F8: 角色卡导出/导入入口（D-V17-09）
        self.export_card_btn = QPushButton("📤 导出角色卡")
        self.export_card_btn.setObjectName("secondaryBtn")
        self.export_card_btn.setFixedHeight(28)
        self.export_card_btn.setCursor(Qt.PointingHandCursor)
        self.export_card_btn.setToolTip("把当前选中角色的人设导出为 .malingcard.json 角色卡文件\n（只含人设字段，不含记忆/亲密度/对话历史）")
        self.export_card_btn.clicked.connect(self._on_export_role_card)
        _decorate_button(self.export_card_btn, self.app_ctx, "export",
                         "导出角色卡", "📤 导出角色卡")
        left_layout.addWidget(self.export_card_btn)

        self.import_card_btn = QPushButton("📥 导入角色卡")
        self.import_card_btn.setObjectName("secondaryBtn")
        self.import_card_btn.setFixedHeight(28)
        self.import_card_btn.setCursor(Qt.PointingHandCursor)
        self.import_card_btn.setToolTip("从 .malingcard.json 角色卡文件导入为新角色\n（重名自动改名「XX（导入）」，导入前可预览确认）")
        self.import_card_btn.clicked.connect(self._on_import_role_card)
        _decorate_button(self.import_card_btn, self.app_ctx, "inbox",
                         "导入角色卡", "📥 导入角色卡")
        left_layout.addWidget(self.import_card_btn)

        # 角色列表
        self.role_list = QListWidget()
        self.role_list.setObjectName("roleList")
        self.role_list.setIconSize(QSize(_ROLE_BTN_ICON_SIZE, _ROLE_BTN_ICON_SIZE))
        self.role_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.role_list.customContextMenuRequested.connect(self._show_role_menu)
        self.role_list.itemClicked.connect(self._on_role_selected)
        left_layout.addWidget(self.role_list, 1)

        # 空状态提示
        # v2.1 全量布局体检实测：本 label 位于固定 220 宽左栏（内容可用宽仅 196），
        # 文案需 225px → QLabel 默认 wordWrap=False 且无省略号，尾部「吧~」被硬裁
        # 29px（浅/深 × 图标两态 × 460~1016 五档宽度，20 组读数全部截断）。
        # 开 wordWrap 让文案折成两行（信息可达 > 版式不变），并补 tooltip 兜底。
        self.empty_label = QLabel("还没有自定义角色，点上面的按钮新建吧~")
        self.empty_label.setObjectName("roleEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setToolTip("还没有自定义角色，点上面的按钮新建吧~")
        left_layout.addWidget(self.empty_label)

        main_layout.addWidget(self.left_sidebar)

        # --- 右侧配置区 ---
        self.right_panel = QWidget()
        self.right_panel.setObjectName("rolePage")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(16)

        # 头像与基础信息卡片
        info_card = self._create_section("角色信息")
        info_layout = info_card.layout()

        # 头像 + 名称行（头像可点击：选文件 → 复制到 avatars/ 作为该角色专属头像）
        avatar_row = QHBoxLayout()
        self.avatar_btn = QPushButton()
        self.avatar_btn.setObjectName("roleAvatarBtn")
        self.avatar_btn.setFixedSize(AVATAR_BTN_SIZE)
        # v1.4：图标按 AVATAR_ICON_SIZE 实际绘制（默认 16×16 会把头像挤小）
        self.avatar_btn.setIconSize(AVATAR_ICON_SIZE)
        self.avatar_btn.setCursor(Qt.PointingHandCursor)
        self.avatar_btn.setToolTip("点击更换头像（选 PNG/JPG/WebP，会复制到角色专属目录）")
        self.avatar_btn.setStyleSheet(
            "QPushButton#roleAvatarBtn {"
            "  background: #FFF0F5; color: #C48A9C;"
            "  border: 2px solid #FFB6C1; border-radius: 36px;"
            "  font-size: 28px;"
            "}"
            "QPushButton#roleAvatarBtn:hover { border-color: #FF6B9D; }"
            "QPushButton#roleAvatarBtn:pressed { background: #FFE4EC; }"
        )
        self.avatar_btn.clicked.connect(self._on_avatar_clicked)
        avatar_row.addWidget(self.avatar_btn)

        name_desc_layout = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("角色名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入角色名称...")
        name_row.addWidget(self.name_edit, 1)
        name_desc_layout.addLayout(name_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("角色描述:"))
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("简短描述这个角色...")
        desc_row.addWidget(self.desc_edit, 1)
        name_desc_layout.addLayout(desc_row)

        # v1.9(C/D-V19-01): 「名字」与「人设标签」分离 —— 角色名称是类别标签，
        # 这里填的名字才是她自称时用的名字；留空则自称"我"。
        given_row = QHBoxLayout()
        given_row.addWidget(QLabel("角色名字:"))
        self.given_name_edit = QLineEdit()
        self.given_name_edit.setPlaceholderText("她自称的名字（留空则自称「我」）")
        self.given_name_edit.setToolTip(
            "她的名字（如「小铃」「小鲸」）。\n"
            "聊天时她会用这个名字自称；留空则自称「我」。\n"
            "角色名称是人设标签（如「温柔女仆」），不会被她用来自称。"
        )
        given_row.addWidget(self.given_name_edit, 1)
        name_desc_layout.addLayout(given_row)

        avatar_row.addLayout(name_desc_layout, 1)
        info_layout.addLayout(avatar_row)

        # 角色卡「羁绊」属性（角色扮演用 0-5 心，独立于好感度系统；用词避免与关系系统混淆）
        intimacy_row = QHBoxLayout()
        intimacy_row.addWidget(QLabel("羁绊:"))
        self.intimacy_label = QLabel("♥♥♥♡♡")
        intimacy_row.addWidget(self.intimacy_label)
        intimacy_row.addStretch()
        info_layout.addLayout(intimacy_row)

        right_layout.addWidget(info_card)

        # 系统提示词区（v1.5.1：藏一层 —— 不再明面摊 150px QTextEdit，
        # 改为「✏️ 编辑系统提示词…」入口行，点击弹 QDialog 大编辑框保存/取消）
        prompt_card = self._create_section("系统提示词")
        prompt_layout = prompt_card.layout()

        # prompt_edit 仍是唯一数据载体，但不挂进任何布局（无父 → 页面不可见），
        # _load_role_detail 仍向其 setPlainText、原保存链仍从它 toPlainText，
        # 语义零改动；真正的文本编辑发生在弹窗的临时 editor 里。
        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("设定这个角色的背景、性格和说话方式...")

        prompt_entry_row = QHBoxLayout()
        self.prompt_entry_btn = QPushButton("✏️ 编辑系统提示词…")
        self.prompt_entry_btn.setObjectName("secondaryBtn")
        self.prompt_entry_btn.setCursor(Qt.PointingHandCursor)
        self.prompt_entry_btn.setToolTip("点击打开大编辑框，填写/修改系统提示词\n（决定 AI 的角色背景、性格与说话方式）")
        self.prompt_entry_btn.clicked.connect(self._on_edit_prompt)
        _decorate_button(self.prompt_entry_btn, self.app_ctx, "edit",
                         "编辑系统提示词…", "✏️ 编辑系统提示词…")
        self.prompt_count_label = QLabel("0 字")
        self.prompt_count_label.setObjectName("roleHint")
        prompt_entry_row.addWidget(self.prompt_entry_btn, 1)
        prompt_entry_row.addWidget(self.prompt_count_label)
        prompt_layout.addLayout(prompt_entry_row)

        hint = QLabel("提示：修改系统提示词会影响 AI 的回复风格，保存角色后下一条消息即生效。")
        hint.setObjectName("roleHint")
        prompt_layout.addWidget(hint)

        right_layout.addWidget(prompt_card)

        # v1.7 F8: 人设工坊区（开场白 / 示例对话）—— 同 v1.5.2 提示词入口风格：
        # 入口行 + 点击弹 QDialog 编辑，入口行带概要。
        workshop_card = self._create_section("人设工坊")
        workshop_layout = workshop_card.layout()

        opening_row = QHBoxLayout()
        self.opening_entry_btn = QPushButton("🎬 开场白（未填写）")
        self.opening_entry_btn.setObjectName("secondaryBtn")
        self.opening_entry_btn.setCursor(Qt.PointingHandCursor)
        self.opening_entry_btn.setToolTip(
            "配置角色的开场白（切到该角色/新建会话时说的第一句话）\n"
            "最多 3 套，多套之间用单独一行 --- 分隔，注入时随机选一套"
        )
        self.opening_entry_btn.clicked.connect(self._on_edit_opening_lines)
        _decorate_button(self.opening_entry_btn, self.app_ctx, "film",
                         "开场白（未填写）", "🎬 开场白（未填写）")
        opening_row.addWidget(self.opening_entry_btn, 1)
        workshop_layout.addLayout(opening_row)

        dialogue_row = QHBoxLayout()
        self.dialogue_entry_btn = QPushButton("💬 示例对话（未填写）")
        self.dialogue_entry_btn.setObjectName("secondaryBtn")
        self.dialogue_entry_btn.setCursor(Qt.PointingHandCursor)
        self.dialogue_entry_btn.setToolTip(
            "配置「用户-角色」示例对话（few-shot），供语气与相处方式参考\n"
            "最多 5 组，可勾选启用/停用；注入 system 尾部，不进对话历史"
        )
        self.dialogue_entry_btn.clicked.connect(self._on_edit_example_dialogues)
        _decorate_button(self.dialogue_entry_btn, self.app_ctx, "chat",
                         "示例对话（未填写）", "💬 示例对话（未填写）")
        dialogue_row.addWidget(self.dialogue_entry_btn, 1)
        workshop_layout.addLayout(dialogue_row)

        workshop_hint = QLabel("开场白与示例对话随角色保存生效；不占用对话历史。")
        workshop_hint.setObjectName("roleHint")
        workshop_layout.addWidget(workshop_hint)

        right_layout.addWidget(workshop_card)

        # 性格参数区
        personality_card = self._create_section("性格参数")
        personality_layout = personality_card.layout()

        # 活泼度
        lively_row = QHBoxLayout()
        lively_row.addWidget(QLabel("活泼度"))
        self.lively_slider = QSlider(Qt.Horizontal)
        self.lively_slider.setMinimum(0)
        self.lively_slider.setMaximum(100)
        self.lively_slider.valueChanged.connect(self._on_slider_changed)
        lively_row.addWidget(self.lively_slider)
        self.lively_value = QLabel("50%")
        lively_row.addWidget(self.lively_value)
        personality_layout.addLayout(lively_row)

        # 严谨度
        rigorous_row = QHBoxLayout()
        rigorous_row.addWidget(QLabel("严谨度"))
        self.rigorous_slider = QSlider(Qt.Horizontal)
        self.rigorous_slider.setMinimum(0)
        self.rigorous_slider.setMaximum(100)
        self.rigorous_slider.valueChanged.connect(self._on_slider_changed)
        rigorous_row.addWidget(self.rigorous_slider)
        self.rigorous_value = QLabel("50%")
        rigorous_row.addWidget(self.rigorous_value)
        personality_layout.addLayout(rigorous_row)

        # 贴心度
        caring_row = QHBoxLayout()
        caring_row.addWidget(QLabel("贴心度"))
        self.caring_slider = QSlider(Qt.Horizontal)
        self.caring_slider.setMinimum(0)
        self.caring_slider.setMaximum(100)
        self.caring_slider.valueChanged.connect(self._on_slider_changed)
        caring_row.addWidget(self.caring_slider)
        self.caring_value = QLabel("50%")
        caring_row.addWidget(self.caring_value)
        personality_layout.addLayout(caring_row)

        right_layout.addWidget(personality_card)

        # 操作按钮区
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        # v1.2: 一键套用预设人设（6 套差异化预设：温柔女仆/编程老手/温柔姐姐/猫娘/毒舌博士/雌小鬼）
        self.preset_btn = QPushButton("套用预设…")
        self.preset_btn.setObjectName("secondaryBtn")
        self.preset_btn.setToolTip(
            "用一套默认人设填满当前角色的名称/描述/系统提示词/性格三值\n"
            "（温柔女仆 / 编程老手 / 温柔姐姐 / 猫娘 / 毒舌博士 / 雌小鬼）"
        )
        self.preset_btn.clicked.connect(self._on_apply_preset)
        btn_row.addWidget(self.preset_btn)

        self.save_btn = QPushButton("保存角色")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.clicked.connect(self._on_save_role)
        btn_row.addWidget(self.save_btn)

        self.default_btn = QPushButton("设为默认")
        self.default_btn.setObjectName("secondaryBtn")
        self.default_btn.clicked.connect(self._on_set_default)
        btn_row.addWidget(self.default_btn)

        self.delete_btn = QPushButton("删除角色")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.clicked.connect(self._on_delete_role)
        btn_row.addWidget(self.delete_btn)

        right_layout.addLayout(btn_row)
        right_layout.addStretch()

        main_layout.addWidget(self.right_panel, 1)

    def _create_section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("roleSection")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        return frame

    def _connect_signals(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

    def _load_roles(self) -> None:
        self.role_list.clear()
        roles = self.role_manager.all_roles()
        self.empty_label.setVisible(len(roles) == 0)

        # v2.1(V21-12): 默认角色标记改用矢量星标图标；字体不可用回落原 ★/○ 前缀
        star_ic = _vector_icon(self.app_ctx, "star", _ROLE_BTN_ICON_SIZE,
                               theme_color(self.app_ctx, "accent", "#FF6B9D"))
        for role in roles:
            item = QListWidgetItem()
            if star_ic is not None:
                item.setText(role.name)
                if role.is_default:
                    item.setIcon(star_ic)
            else:
                prefix = "★ " if role.is_default else "○ "
                item.setText(f"{prefix}{role.name}")
            # v2.1 全量布局体检：左栏可用宽 196，12 字角色名需 170（余量仅 26），
            # 更长的名字会被 list 裁掉且无省略号 → 补 tooltip 保住完整角色名。
            item.setToolTip(role.name)
            item.setData(Qt.UserRole, role.id)
            self.role_list.addItem(item)
            if role.is_default:
                self.role_list.setCurrentItem(item)
                self._load_role_detail(role)

        if not self._current_role_id and roles:
            first_role = roles[0]
            self._current_role_id = first_role.id
            self._load_role_detail(first_role)

    def _load_role_detail(self, role: Role) -> None:
        self._current_role_id = role.id
        self.name_edit.setText(role.name)
        self.desc_edit.setText(role.description)
        self.given_name_edit.setText(getattr(role, "given_name", "") or "")  # v1.9: 名字
        self.prompt_edit.setPlainText(role.system_prompt)
        # v1.5.1：切换角色后刷新「入口行 + 字数」概要
        self._refresh_prompt_entry()
        # v1.7 F8: 人设工坊入口概要随角色切换刷新
        self._refresh_workshop_entries()
        # 头像：角色专属（用户自选文件）或默认 ✨
        self._set_avatar_icon(role)

        personality = role.personality
        self.lively_slider.setValue(personality.get("lively", 50))
        self.lively_value.setText(f"{personality.get('lively', 50)}%")
        self.rigorous_slider.setValue(personality.get("rigorous", 50))
        self.rigorous_value.setText(f"{personality.get('rigorous', 50)}%")
        self.caring_slider.setValue(personality.get("caring", 50))
        self.caring_value.setText(f"{personality.get('caring', 50)}%")

        # 羁绊：与陪伴域实时联动（随好感度升级自动进阶初识→熟悉→亲近→信赖）
        companion = getattr(self.app_ctx, "companion", None)
        try:
            stage = companion.relation_stage_name() if companion else "初识"
        except Exception:
            stage = "初识"
        stage_hearts = {
            "初识": "♥♡♡♡♡", "熟悉": "♥♥♡♡♡", "亲近": "♥♥♥♡♡", "信赖": "♥♥♥♥♥",
        }
        self.intimacy_label.setText(f"{stage}  {stage_hearts.get(stage, '♥♡♡♡♡')}")

        self.default_btn.setEnabled(not role.is_default)
        self.delete_btn.setEnabled(not role.is_default)

    def _on_role_selected(self, item: QListWidgetItem) -> None:
        role_id = item.data(Qt.UserRole)
        role = self.role_manager.get_role(role_id)
        if role:
            self._load_role_detail(role)
            # Bug3: 点选即生效 —— 单击列表项直接应用角色（此前只载入详情，
            # 用户以为切换了角色但人设/头像/形象均未生效）。
            self._apply_role_if_changed(role_id)

    def _apply_role_if_changed(self, role_id: str) -> None:
        """Bug3: 幂等应用 —— 点选的角色已是默认角色时不重复落盘/广播。"""
        try:
            current = self.role_manager.default_role
            if current is not None and getattr(current, "id", None) == role_id:
                return
        except Exception:
            pass
        self._apply_role(role_id)

    def _apply_role(self, role_id: str) -> None:
        """Bug3: 角色应用唯一入口 —— set_default + 同步 system + 广播 role_changed。

        原 _on_set_default 内联的三步逻辑收敛至此，供「设为默认」按钮、
        单击列表项（点选即生效）与右键菜单共用，保证语义一致。
        """
        if not role_id:
            return
        self.role_manager.set_default(role_id)
        self._load_roles()
        # v10.13: 切换默认角色后同步接线（session.set_gui_role_prompt →
        # _update_system 即时刷新 current_system；ChatService 每轮发送现取，下条消息生效）
        self._sync_role_override()
        # v1.5.1(切角色人设残留): 边界注入 —— system 已换但历史里旧角色的对话
        # 仍会带偏模型（用户实锤：切鲸鱼娘→切回女仆仍自称"鲸鱼娘女仆"）。
        # 显式追加 system 边界消息（幂等，至多一条），要求立即以新角色人设继续。
        try:
            _session = getattr(self.app_ctx, "session", None)
            _role_new = self.role_manager.get_role(role_id)
            if (_session is not None and _role_new is not None
                    and callable(getattr(_session, "notify_role_switch", None))):
                _session.notify_role_switch(_role_new.name)
        except Exception as exc:
            logger.debug("角色切换边界注入失败（不影响切换）: %s", exc)
        # v1.7 F8(D-V17-08): 开场白注入 —— 调用点①（在 notify_role_switch 对齐
        # 动作之后）。幂等守卫 + 空配置零注入内聚在 helper 内；注入失败不影响切换。
        try:
            _session = getattr(self.app_ctx, "session", None)
            _role_new = self.role_manager.get_role(role_id)
            inject_opening_line(self.app_ctx, _session, _role_new)
        except Exception as exc:
            logger.debug("开场白注入失败（不影响切换）: %s", exc)
        # v1.4.2: 广播角色生效（左下角/首页大形象、气泡头像联动换角色专属形象）
        try:
            _rb = getattr(self.app_ctx, "role_bridge", None)
            _role = self.role_manager.get_role(role_id)
            if _rb is not None and _role is not None:
                _rb.notify_role_changed(
                    _role.id, _role.effective_avatar(),
                    getattr(_role, "current_expression", "normal") or "normal",
                )
        except Exception:
            pass

    def _on_new_role(self) -> None:
        name, ok = QInputDialog.getText(self, "新建角色", "角色名称:")
        if not ok or not name.strip():
            return
        desc, _ = QInputDialog.getText(self, "新建角色", "角色描述（可选）:")
        role = self.role_manager.create_role(name.strip(), desc.strip())
        self._load_roles()
        for i in range(self.role_list.count()):
            item = self.role_list.item(i)
            if item.data(Qt.UserRole) == role.id:
                self.role_list.setCurrentItem(item)
                self._load_role_detail(role)
                break

    def _on_new_role_from_preset(self) -> None:
        """从 6 套默认预设人设里挑一套，一键生成新角色（名称/描述/性格/人设都填好）。"""
        menu = QMenu(self)
        pairs = []
        for name in ROLE_PRESETS.keys():
            act = menu.addAction(name)
            pairs.append((act, name))
        chosen = menu.exec_(
            self.preset_new_btn.mapToGlobal(self.preset_new_btn.rect().bottomLeft())
        )
        if chosen is None:
            return
        for act, name in pairs:
            if act is not chosen:
                continue
            preset = ROLE_PRESETS.get(name)
            if not preset:
                return
            role = self.role_manager.create_role(preset["name"], preset["description"])
            # 复用既有套用逻辑：落到当前角色并立即接线到聊天
            self._current_role_id = role.id
            self._apply_preset_to_current(name)
            return

    # ============== v1.2: 头像渲染 + 文件选择 ==============
    def _set_avatar_icon(self, role: Role) -> None:
        """把角色头像设为按钮图标。优先级：专属文件 > 角色资产集「思考」表情 > ✨。

        v1.4.3 新增中间层：当角色未设自定义头像（role.avatar 为 None）时，尝试取该
        角色资产集（gui.maid_avatar.role_assets）中的「normal」表情图作为默认形象
        （圆形裁切）。有图角色（如鲸鱼娘 preset_whale 含 37 张图）自动获得「思考托腮」
        默认头像；资产集为 None（无图角色）才回退 ✨。
        """
        try:
            self.avatar_btn.setIconSize(AVATAR_ICON_SIZE)
            avatar_path = getattr(role, "avatar", None)
            pix = None
            # ① 用户自定义专属头像文件优先
            if avatar_path and Path(avatar_path).is_file():
                # 稳健解码（渐进 + 上限 + null 守卫），坏图/超大可回退而非崩
                pix = rounded_avatar_pixmap(str(avatar_path), AVATAR_ICON_SIZE)
            # ② 中间层：无专属文件 → 取角色资产集的 thinking 表情（有图角色自动获得）
            if pix is None or pix.isNull():
                try:
                    from gui.maid_avatar import role_assets
                    assets = role_assets(getattr(role, "id", None))
                    if assets is not None:
                        tpix = assets.rounded("normal", AVATAR_ICON_SIZE.width())
                        if tpix is not None and not tpix.isNull():
                            pix = tpix
                except Exception as e:
                    logger.debug("角色资产集取 thinking 头像失败: %s", e)
            if pix is not None and not pix.isNull():
                self.avatar_btn.setIcon(QIcon(pix))
                self.avatar_btn.setText("")
            else:
                # v2.1(V21-12): 无头像图 → 矢量 ✨ 图标；字体不可用回落 ✨ 文本
                self.avatar_btn.setText("")
                fallback = _vector_icon(self.app_ctx, "auto_awesome", 40,
                                        theme_color(self.app_ctx, "text_secondary", "#C48A9C"))
                if fallback is not None:
                    self.avatar_btn.setIconSize(QSize(40, 40))
                    self.avatar_btn.setIcon(fallback)
                else:
                    self.avatar_btn.setIcon(QIcon())
                    self.avatar_btn.setText("✨")
        except Exception as e:
            logger.warning("角色头像渲染失败: %s", e)
            try:
                self.avatar_btn.setText("✨")
            except Exception:
                pass

    def _on_avatar_clicked(self) -> None:
        """点头像：从本地选 PNG/JPG/WebP，复制到 avatars/<role_id>.ext 作为专属头像。"""
        if not self._current_role_id:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择角色头像", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > _AVATAR_MAX_BYTES:
                QMessageBox.warning(
                    self, "图片过大",
                    "这张图片超过 25MB，请选一张普通的 PNG/JPG 头像图。",
                )
                return
            ROLE_AVATARS_DIR.mkdir(parents=True, exist_ok=True)
            suffix = Path(path).suffix.lower() or ".png"
            target = ROLE_AVATARS_DIR / f"{self._current_role_id}{suffix}"
            import shutil
            shutil.copy2(path, str(target))
        except Exception as e:
            QMessageBox.warning(self, "头像加载失败", str(e))
            return
        role = self.role_manager.get_role(self._current_role_id)
        if role:
            role.avatar = str(target)
            self.role_manager.save_role(role)
            self._set_avatar_icon(role)

    # ============== v1.2: 套用预设（差异化 6 套人设一键克隆） ==============
    def _on_apply_preset(self) -> None:
        menu = QMenu(self)
        for name in ROLE_PRESETS.keys():
            act = menu.addAction(name)
            act.triggered.connect(lambda checked=False, n=name: self._apply_preset_to_current(n))
        btn_rect = self.preset_btn.rect()
        menu.exec_(self.preset_btn.mapToGlobal(btn_rect.bottomLeft()))

    def _apply_preset_to_current(self, preset_name: str) -> None:
        preset = ROLE_PRESETS.get(preset_name)
        if not preset or not self._current_role_id:
            return
        role = self.role_manager.get_role(self._current_role_id)
        if role is None:
            return
        role.name = preset["name"]
        role.description = preset["description"]
        role.system_prompt = preset["system_prompt"]
        role.personality = dict(preset["personality"])  # 拷贝避免引用共享
        role.given_name = preset.get("given_name", "") or ""  # v1.9: 预设名字同步
        self.role_manager.save_role(role)
        self._load_roles()
        for i in range(self.role_list.count()):
            item = self.role_list.item(i)
            if item.data(Qt.UserRole) == role.id:
                self.role_list.setCurrentItem(item)
                break
        self._load_role_detail(role)
        # 立即套用到聊天（让用户立刻感受到腔调变化）
        try:
            session = getattr(self.app_ctx, "session", None)
            sync_role_override_to_session(session, self.role_manager)
        except Exception:
            pass

    def _on_save_role(self) -> None:
        if not self._current_role_id:
            return
        if self._save_role_fields():
            QMessageBox.information(self, "成功", "角色已保存")

    def _save_role_fields(self) -> bool:
        """原保存链（唯一入口）—— 收集面板全部字段 → 落盘 → 接线聊天。

        v1.5.1 拆出供「弹窗保存」与「保存角色」按钮共用：弹窗保存只回写
        prompt_edit 后即走此链，不再弹二次确认框；按钮保存沿用弹"角色已保存"。
        """
        if not self._current_role_id:
            return False
        role = self.role_manager.get_role(self._current_role_id)
        if not role:
            return False

        role.name = self.name_edit.text().strip()
        role.description = self.desc_edit.text().strip()
        role.system_prompt = self.prompt_edit.toPlainText().strip()
        role.given_name = self.given_name_edit.text().strip()  # v1.9: 名字落盘
        role.personality = {
            "lively": self.lively_slider.value(),
            "rigorous": self.rigorous_slider.value(),
            "caring": self.caring_slider.value(),
        }
        self.role_manager.save_role(role)
        self._load_roles()
        # v10.13: 保存后立即把新提示词/性格参数接线进聊天请求链路（下一条消息即生效）
        self._sync_role_override()
        return True

    # ============== v1.5.1: 系统提示词「藏一层」—— 入口行 + 弹窗大编辑框 ==============
    def _refresh_prompt_entry(self) -> None:
        """刷新入口行概要与字数（随角色切换 / 弹窗保存后更新）。"""
        if not hasattr(self, "prompt_entry_btn"):
            return
        text = self.prompt_edit.toPlainText().strip()
        self.prompt_count_label.setText(f"{len(text)} 字")
        first = text.splitlines()[0] if text else ""
        if len(first) > 16:
            first = first[:16] + "…"
        summary = f"（当前：{first}）" if first else "（未填写）"
        _decorate_button(self.prompt_entry_btn, self.app_ctx, "edit",
                         f"编辑系统提示词  {summary}",
                         f"✏️ 编辑系统提示词  {summary}")
        # v2.1 角色页布局：当前动态文案挂到 tooltip，避免「未填写 / 已填 N 条 /
        # 首行摘要… 等动态变长文案」在某宽度下被硬裁后用户看不到完整状态。
        # 原始 tooltip（功能说明）保留，把当前 button.text() 追加到第二段。
        try:
            _base = self._PROMPT_ENTRY_TIP
        except AttributeError:
            _base = self.prompt_entry_btn.toolTip()
            self._PROMPT_ENTRY_TIP = _base
        _cur = self.prompt_entry_btn.text()
        self.prompt_entry_btn.setToolTip(f"{_base}\n\n当前：{_cur}")

    def _on_edit_prompt(self) -> None:
        """点击入口 → 弹 560×360 大编辑框；保存回写 prompt_edit 并走原保存链落盘。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑系统提示词")
        dlg.resize(560, 360)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        editor = QTextEdit()
        editor.setAcceptRichText(False)  # 纯文本，避免粘贴富文本污染人设
        editor.setPlainText(self.prompt_edit.toPlainText())
        editor.setPlaceholderText("设定这个角色的背景、性格和说话方式...")
        lay.addWidget(editor, 1)

        tip = QLabel("保存后角色立即以此系统提示词落盘，下一条聊天消息即生效。")
        tip.setObjectName("roleHint")
        lay.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        editor.setFocus()
        if dlg.exec_() == QDialog.Accepted:
            self._commit_prompt_text(editor.toPlainText())

    def _commit_prompt_text(self, text: str) -> None:
        """弹窗「保存」落点：回写 prompt_edit（唯一载体）→ 刷新概要 → 走原保存链。"""
        self.prompt_edit.setPlainText(text)
        self._refresh_prompt_entry()
        self._save_role_fields()

    # ============== v1.7 F8: 人设工坊（开场白 / 示例对话 / 角色卡） ==============
    def _current_workshop_role(self) -> Optional[Role]:
        """工坊编辑的目标角色 = 当前面板选中角色。"""
        if not self._current_role_id:
            return None
        return self.role_manager.get_role(self._current_role_id)

    def _refresh_workshop_entries(self) -> None:
        """刷新开场白/示例对话入口行概要（随角色切换 / 弹窗保存后更新）。"""
        if not hasattr(self, "opening_entry_btn"):
            return
        role = self._current_workshop_role()
        if role is None:
            return
        n_open = len(normalize_opening_lines(getattr(role, "opening_lines", None)))
        n_dialog = len(normalize_example_dialogues(
            getattr(role, "example_dialogues", None)
        ))
        _decorate_button(
            self.opening_entry_btn, self.app_ctx, "film",
            f"开场白（已配 {n_open} 套）" if n_open else "开场白（未填写）",
            f"🎬 开场白（已配 {n_open} 套）" if n_open else "🎬 开场白（未填写）",
        )
        _decorate_button(
            self.dialogue_entry_btn, self.app_ctx, "chat",
            f"示例对话（已配 {n_dialog} 组）" if n_dialog else "示例对话（未填写）",
            f"💬 示例对话（已配 {n_dialog} 组）" if n_dialog else "💬 示例对话（未填写）",
        )
        # v2.1 角色页布局：当前动态文案挂到 tooltip（详见 _refresh_prompt_entry 注释）
        for btn, attr in (
            (self.opening_entry_btn, "_OPENING_ENTRY_TIP"),
            (self.dialogue_entry_btn, "_DIALOGUE_ENTRY_TIP"),
        ):
            try:
                _base = getattr(self, attr)
            except AttributeError:
                _base = btn.toolTip()
                setattr(self, attr, _base)
            btn.setToolTip(f"{_base}\n\n当前：{btn.text()}")

    def _on_edit_opening_lines(self) -> None:
        """开场白编辑弹窗：单框多套存储、`---` 分行解析（D-V17-07 裁决，UI 最简）。"""
        role = self._current_workshop_role()
        if role is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑开场白")
        dlg.resize(520, 340)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        editor = QPlainTextEdit()
        editor.setPlainText(format_opening_lines_text(getattr(role, "opening_lines", None)))
        editor.setPlaceholderText(
            "开场白第一套（切到该角色/新建会话时说的第一句话）\n"
            "---\n"
            "开场白第二套（可选，注入时随机选一套）\n"
            "---\n"
            "开场白第三套（可选）\n\n"
            "最多 3 套；支持表情标记，如：（开心地挥挥手）主人来啦～ (◕‿◕)"
        )
        lay.addWidget(editor, 1)

        n_now = len(normalize_opening_lines(getattr(role, "opening_lines", None)))
        tip = QLabel(
            f"已配 {n_now}/{MAX_OPENING_LINES} 套；多套之间用单独一行 --- 分隔，"
            "注入时随机选一套。保存后随角色生效。"
        )
        tip.setObjectName("roleHint")
        lay.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

        if dlg.exec_() == QDialog.Accepted:
            role.opening_lines = parse_opening_lines_text(editor.toPlainText())
            self._save_role_fields()
            self._refresh_workshop_entries()

    def _on_edit_example_dialogues(self) -> None:
        """示例对话编辑弹窗：双列（用户/角色）N 组 + 启用勾选 + 增删组（≤5）。"""
        role = self._current_workshop_role()
        if role is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑示例对话")
        dlg.resize(640, 460)
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        groups: List[Dict] = list(normalize_example_dialogues(
            getattr(role, "example_dialogues", None)
        ))
        rows_area = QScrollArea()
        rows_area.setWidgetResizable(True)
        rows_host = QWidget()
        rows_layout = QVBoxLayout(rows_host)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_layout.setSpacing(8)
        rows_area.setWidget(rows_host)
        outer.addWidget(rows_area, 1)

        def _relabel() -> None:
            """重编组序号（删除后保持连续），并约束添加按钮状态。"""
            for i, frame in enumerate(getattr(rows_host, "_f8_rows", []), start=1):
                frame._f8_title.setText(f"第 {i} 组")
            add_btn = getattr(self, "_f8_add_btn", None)
            if add_btn is not None:
                add_btn.setEnabled(len(groups) < MAX_EXAMPLE_DIALOGUES)

        def _remove_row(frame: QFrame) -> None:
            idx = groups.index(frame._f8_data)
            groups.pop(idx)
            rows_layout.removeWidget(frame)
            frame.deleteLater()
            rows_host._f8_rows.remove(frame)
            _relabel()

        def _add_row(data: Optional[Dict] = None) -> None:
            if len(groups) >= MAX_EXAMPLE_DIALOGUES:
                return
            data = data or {"user": "", "assistant": "", "enabled": True}
            groups.append(data)
            frame = QFrame()
            frame.setObjectName("roleSection")
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(8, 8, 8, 8)
            fl.setSpacing(6)
            title_row = QHBoxLayout()
            title = QLabel("")
            title.setFont(QFont("", -1, QFont.Bold))
            title_row.addWidget(title)
            title_row.addStretch()
            enabled_check = QCheckBox("启用")
            enabled_check.setChecked(bool(data.get("enabled", True)))
            title_row.addWidget(enabled_check)
            del_btn = QPushButton("删除本组")
            del_btn.setObjectName("secondaryBtn")
            del_btn.clicked.connect(lambda checked=False, f=frame: _remove_row(f))
            title_row.addWidget(del_btn)
            fl.addLayout(title_row)
            frame._f8_title = title
            frame._f8_data = data
            cols = QHBoxLayout()
            user_edit = QPlainTextEdit()
            user_edit.setPlaceholderText("用户说…")
            user_edit.setPlainText(str(data.get("user", "")))
            user_edit.setMaximumHeight(72)
            asst_edit = QPlainTextEdit()
            asst_edit.setPlaceholderText("角色回应…（示范语气与相处方式）")
            asst_edit.setPlainText(str(data.get("assistant", "")))
            asst_edit.setMaximumHeight(72)
            cols.addWidget(user_edit, 1)
            cols.addWidget(asst_edit, 1)
            fl.addLayout(cols)
            rows_layout.addWidget(frame)
            if not hasattr(rows_host, "_f8_rows"):
                rows_host._f8_rows = []
            rows_host._f8_rows.append(frame)
            # 回写绑定（弹窗保存时统一收集）
            data["_ui"] = {"user_edit": user_edit, "asst_edit": asst_edit,
                           "enabled_check": enabled_check}
            _relabel()

        for g in list(groups):  # 快照迭代：_add_row 会向 groups 追加
            _add_row(g)
        if not groups:
            _add_row()  # 首次打开给一行起步

        add_row = QHBoxLayout()
        self._f8_add_btn = QPushButton("＋ 添加一组")
        self._f8_add_btn.setObjectName("secondaryBtn")
        self._f8_add_btn.clicked.connect(lambda checked=False: _add_row())
        add_row.addWidget(self._f8_add_btn)
        add_row.addStretch()
        tip = QLabel(f"最多 {MAX_EXAMPLE_DIALOGUES} 组；勾选启用后才会注入（system 尾部、不进历史）。")
        tip.setObjectName("roleHint")
        add_row.addWidget(tip)
        outer.addLayout(add_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(dlg.reject)
        save_btn = QPushButton("保存")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

        if dlg.exec_() == QDialog.Accepted:
            cleaned: List[Dict] = []
            for data in groups:
                ui = data.get("_ui") or {}
                user = ui.get("user_edit").toPlainText().strip()
                assistant = ui.get("asst_edit").toPlainText().strip()
                if not user and not assistant:
                    continue
                cleaned.append({
                    "user": user,
                    "assistant": assistant,
                    "enabled": ui.get("enabled_check").isChecked(),
                })
            role.example_dialogues = normalize_example_dialogues(cleaned)
            self._save_role_fields()
            self._refresh_workshop_entries()

    # ---------------- 角色卡导出/导入（D-V17-09，Q-C10 轻校验） ----------------
    def _on_export_role_card(self) -> None:
        """导出当前选中角色为 .malingcard.json（只含人设字段，R-I）。"""
        role = self._current_workshop_role()
        if role is None:
            QMessageBox.warning(self, "提示", "请先在左侧选择要导出的角色。")
            return
        # 预设角色导出提示（design D-V17-09：这是预设角色的副本）
        if str(role.id).startswith("preset_") or role.id == PRISTINE_ROLE_ID:
            QMessageBox.information(
                self, "导出预设角色",
                f"「{role.name}」是内置预设角色，导出的是它当前的人设副本。\n"
                "角色卡只含人设字段（名称/描述/提示词/性格/开场白/示例对话），"
                "不含记忆、亲密度与对话历史。",
            )
        from gui.role_card import export_card  # 局部导入：懒加载纯逻辑模块
        card = export_card(role)
        default_name = f"{(role.name or '角色').strip() or '角色'}.malingcard.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出角色卡", default_name,
            "码铃角色卡 (*.malingcard.json)",
        )
        if not path:
            return
        if not path.endswith(".malingcard.json"):
            path = path + ".malingcard.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(card, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"角色卡写入失败：{exc}")
            return
        QMessageBox.information(self, "导出成功", f"角色卡已导出到：\n{path}")

    def _on_import_role_card(self) -> None:
        """从 .malingcard.json 导入为新角色（预览确认 + 重名自动改名）。"""
        from gui.role_card import (  # 局部导入：懒加载纯逻辑模块
            CardError, MAX_CARD_BYTES, parse_card,
        )
        path, _ = QFileDialog.getOpenFileName(
            self, "导入角色卡", "",
            "码铃角色卡 (*.malingcard.json);;所有文件 (*.json)",
        )
        if not path:
            return
        try:
            if Path(path).stat().st_size > MAX_CARD_BYTES:
                QMessageBox.warning(self, "导入失败", "角色卡超过 1MB 体积上限，已拒绝导入。")
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "导入失败", f"角色卡读取失败：{exc}")
            return
        try:
            card = parse_card(data)
        except CardError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))
            return

        # 预览确认弹窗（v1.8/D-V18-06 收编 v1.7 Q-C10 遗留：字段逐项呈现 +
        # 性格档位词 + 封面缩略/异常红字 + 冲突改名提示；仅替换确认交互，
        # 导入落盘链零语义变更——对齐链零触碰）
        from gui.widgets.card_import_preview import CardImportPreviewDialog
        existing_names = [r.name for r in self.role_manager.all_roles()]
        preview = CardImportPreviewDialog(card, existing_names, parent=self)
        if preview.exec_() != CardImportPreviewDialog.DialogCode.Accepted:
            return

        # 名称冲突处理：撞名 → 「XX（导入）」（再撞追加序号；与预览提示一致）
        final_name = preview.final_name

        new_role = self.role_manager.create_role(final_name)
        new_role.description = card["description"]
        new_role.system_prompt = card["system_prompt"]
        new_role.personality = dict(card["personality"])
        new_role.opening_lines = list(card["opening_lines"])
        new_role.example_dialogues = list(card["example_dialogues"])
        new_role.current_expression = card["current_expression"]
        new_role.given_name = card.get("given_name", "") or ""  # v1.9: 名字随卡导入（旧卡缺省空）
        self.role_manager.save_role(new_role)

        self._load_roles()
        for i in range(self.role_list.count()):
            item = self.role_list.item(i)
            if item.data(Qt.UserRole) == new_role.id:
                self.role_list.setCurrentItem(item)
                self._load_role_detail(new_role)
                break
        note = f"（原名「{card['name']}」，已改名避免冲突）" if final_name != card["name"] else ""
        QMessageBox.information(
            self, "导入成功", f"角色「{final_name}」已导入{note}，可在右侧查看与编辑。"
        )

    def _sync_role_override(self) -> None:
        """把默认角色的覆盖提示词同步到当前聊天会话（v10.13 接线）。"""
        session = getattr(self.app_ctx, "session", None)
        sync_role_override_to_session(session, self.role_manager)

    def _on_set_default(self) -> None:
        if not self._current_role_id:
            return
        # Bug3: 收敛到 _apply_role 唯一入口（set_default + 同步 + 广播）
        self._apply_role(self._current_role_id)
        QMessageBox.information(self, "成功", "已设为默认角色")

    def _on_delete_role(self) -> None:
        if not self._current_role_id:
            return
        role = self.role_manager.get_role(self._current_role_id)
        if not role or role.is_default:
            QMessageBox.warning(self, "提示", "默认角色不可删除")
            return

        reply = QMessageBox.question(
            self, "删除角色",
            f"确定要删除角色 '{role.name}' 吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.role_manager.delete_role(self._current_role_id)
            self._current_role_id = None
            self._load_roles()

    def _show_role_menu(self, pos) -> None:
        item = self.role_list.itemAt(pos)
        if not item:
            return
        role_id = item.data(Qt.UserRole)
        role = self.role_manager.get_role(role_id)
        if not role:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        default_action = menu.addAction("设为默认")
        delete_action = menu.addAction("删除")

        if role.is_default:
            default_action.setEnabled(False)
            delete_action.setEnabled(False)

        action = menu.exec_(self.role_list.mapToGlobal(pos))
        if action == rename_action:
            self._rename_role(role_id)
        elif action == default_action:
            # Bug3: 与点选/按钮同一条应用链（含 role_changed 广播）
            self._apply_role(role_id)
        elif action == delete_action:
            self._current_role_id = role_id
            self._on_delete_role()

    def _rename_role(self, role_id: str) -> None:
        role = self.role_manager.get_role(role_id)
        if not role:
            return
        name, ok = QInputDialog.getText(self, "重命名角色", "新名称:", text=role.name)
        if ok and name.strip():
            self.role_manager.rename_role(role_id, name.strip())
            self._load_roles()

    def _on_slider_changed(self, value: int) -> None:
        sender = self.sender()
        if sender == self.lively_slider:
            self.lively_value.setText(f"{value}%")
        elif sender == self.rigorous_slider:
            self.rigorous_value.setText(f"{value}%")
        elif sender == self.caring_slider:
            self.caring_value.setText(f"{value}%")

    def _apply_theme(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is None:
            return

        bg = theme_engine.get_color("bg", "#FFF5F5")
        text = theme_engine.get_color("text", "#5D4037")
        primary = theme_engine.get_color("primary", "#FF6B9D")
        secondary = theme_engine.get_color("text_secondary", "#888888")
        border = theme_engine.get_color("border", "#FFE4EC")
        card_bg = theme_engine.get_color("bg_card", "#FFFFFF")

        self.setStyleSheet(f"""
            QWidget#rolePage {{
                background: {bg};
            }}
            /* v2.1(UI-Fix-0912): 显式兜住本页 QLabel 颜色 —— 页面自有 setStyleSheet
               会遮蔽应用级 QSS 的继承,若主题加载失败/明暗错配则本页文字失去颜色。
               更具体的 ID 规则(如 QLabel#roleHint)按特异性胜出,不受影响。 */
            QLabel {{ color: {text}; }}
            QWidget#roleSidebar {{
                background: {card_bg};
                border-right: 1px solid {border};
            }}
            QListWidget#roleList {{
                background: transparent;
                border: none;
                outline: none;
                color: {text};
            }}
            QListWidget#roleList::item {{
                padding: 8px 12px;
                border-radius: 8px;
            }}
            QListWidget#roleList::item:selected {{
                background: {primary}22;
                color: {primary};
                font-weight: 500;
            }}
            QListWidget#roleList::item:hover {{
                background: {primary}11;
            }}
            QFrame#roleSection {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel#roleEmptyState {{
                color: {secondary};
                font-size: 12px;
            }}
            QLabel#roleHint {{
                color: {secondary};
                font-size: 11px;
            }}
        """)

    def _on_theme_changed(self, theme_name: str) -> None:
        self._apply_theme()
