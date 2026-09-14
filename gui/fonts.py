"""码铃字体系统（v1.9 B 块 / 设计 D-V19-04 ~ D-V19-08）。

单一收口点：全站正文 / 标题字体一律经 :func:`font_family_chain` 取值，
QSS 的 ``${font_family}`` / ``${font_title}`` 与 ``app.setFont`` 都走它，
禁止在别处硬编码字体 family 字符串（共享知识 §6.2）。

职责：
  · 内置 OFL 字体（资源圆体 Regular/Medium + jf open 粉圆标题子集）随包注册，
    用 ``QFontDatabase.applicationFontFamilies()`` 取**真实 family name**（不凭文件名猜）。
  · 系统字体（幼圆 / 雅黑 / 楷体 / 等线）直接引用 Qt family。
  · 家族链：``<真实 family>, Microsoft YaHei, remixicon, sans-serif``（生僻字 /
    emoji 由 Qt 字形回退到雅黑，**图标字形**（PUA 码位）由 ``remixicon`` 回退族
    渲染 —— R-L④ / D-V21-06；图标族取自 ``gui.icons.FONT_FAMILY_NAME``，
    在通用族 ``sans-serif`` **之前**插入，绝不排在 generic 之后）。
  · 粉圆 scope 守卫：``huninn`` 是 title-only，在 ``scope="body"`` 时强制回落
    资源圆体（Q-E4：粉圆无法被误设为正文）。
  · **双出口**：:func:`font_family_chain` 返回裸链（``QFont`` / ``split(",")[0]``
    消费）；:func:`qss_font_family` 返回 QSS 形态（逐族加引号、通用族裸写），
    供 ``theme_engine`` 替换 ``${font_family}`` / ``${font_title}`` —— QSS 模板
    必须写成 ``font-family: ${font_family};``（**占位符外不得再加引号**，否则整条
    链被当成单个族名解析，见 :func:`qss_font_family` docstring）。

健壮性：所有 Qt 调用均 try/except 包裹；缺字体文件 / 无 QApplication 时静默
降级（family 链退到雅黑），不崩、不抛。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from gui.utils import get_resource_path

# 内置字体产物在 gui/ 下的相对目录（⚠-2：与 spec datas 目标目录一致）
FONT_DIR_REL = "assets/fonts"

# ---------------------------------------------------------------------------
# 六字体 id 常量（唯一真值源；id 与设计 §4.2 一致）
# ---------------------------------------------------------------------------
FONT_IDS: Dict[str, dict] = {
    "resource_rounded": {"label": "资源圆体（默认）", "scope": "body", "bundled": True},
    "huninn": {"label": "jf open 粉圆（仅标题 / 点缀）", "scope": "title", "bundled": True},
    "youyuan": {"label": "幼圆", "scope": "body", "bundled": False, "qt_family": "YouYuan"},
    "yahei": {"label": "雅黑", "scope": "body", "bundled": False, "qt_family": "Microsoft YaHei"},
    "kaiti": {"label": "楷体", "scope": "body", "bundled": False, "qt_family": "KaiTi"},
    "dengxian": {"label": "等线", "scope": "body", "bundled": False, "qt_family": "DengXian"},
}

# 下拉展示顺序（正文族在前，粉圆随后）
FONT_CHOICES = [
    "resource_rounded",
    "youyuan",
    "yahei",
    "kaiti",
    "dengxian",
    "huninn",
]
# 仅正文可用选项（设置页可用于「正文」语义的下拉；粉圆不在其中）
FONT_IDS_BODY = [fid for fid in FONT_CHOICES if FONT_IDS[fid]["scope"] == "body"]

# ---------------------------------------------------------------------------
# 内置字体清单：文件在 gui/assets/fonts/ 下；family_hint 仅用于多 family 时的
# 优选匹配（真实 family 仍以 Qt 注册结果为准，不凭文件名猜 —— E-2）。
# ---------------------------------------------------------------------------
BUNDLED_FONTS: Dict[str, dict] = {
    "resource_rounded": {
        "files": [
            "ResourceHanRoundedCN-Regular.ttf",
            "ResourceHanRoundedCN-Medium.ttf",
        ],
        "role": "body",
        "family_hint": "Resource Han Rounded CN",
    },
    "huninn": {
        "files": ["jf-openhuninn-subset.ttf"],
        "role": "title",
        "family_hint": "jf open 粉圓 2.0",
    },
}

# 回退链尾：系统高可读黑体 + 通用族（生僻字 / emoji 兜底，R-L④）
_FALLBACK_FAMILY = "Microsoft YaHei"
_GENERIC_FALLBACK = "sans-serif"

# CSS/QSS 通用族关键字：QSS 中**不得加引号**（加了会被当成具体族名，永不命中）。
# 仅这些关键字裸写，其余族名一律各自加双引号（D-V21-06 / QSS 出口形态）。
_GENERIC_FAMILIES = frozenset({
    "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
})

# 运行时状态：id -> 真实 family name（register_bundled_fonts 后填充）
_REGISTERED_FAMILIES: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# 纯逻辑查询
# ---------------------------------------------------------------------------
def default_font_choice() -> str:
    """默认界面字体 = 资源圆体（Q-E6）。"""
    return "resource_rounded"


def is_title_only(choice: str) -> bool:
    """Q-E4 守卫查询：该字体是否仅限标题 / 点缀位。"""
    return FONT_IDS.get(choice or "", {}).get("scope") == "title"


def font_choice_label(choice: str) -> str:
    """下拉展示文案。"""
    return FONT_IDS.get(choice or "", {}).get("label", choice or "")


def resolve_font_path(rel: str) -> Optional[Path]:
    """解析内置字体文件路径（frozen 态 = _MEIPASS/assets/fonts/...，源码态 = gui/assets/fonts/...）。"""
    try:
        return get_resource_path(f"{FONT_DIR_REL}/{rel}")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 注册（启动期一次性）
# ---------------------------------------------------------------------------
def _qt_font_database():
    """惰性取 QFontDatabase（便于无 Qt 环境导入本模块做纯逻辑测试）。"""
    try:
        from gui.qt_compat import QFontDatabase
        return QFontDatabase
    except Exception:
        return None


def register_bundled_fonts() -> Dict[str, str]:
    """把 gui/assets/fonts/ 下的内置字体注册进 Qt，记录**真实 family name**。

    返回 ``{font_id: real_family}``。任何异常（缺文件 / 无 Qt / 注册失败）均静默
    跳过该项，绝不抛出 —— 保证「缺字体优雅回退」（R-K⑤）。
    """
    db = _qt_font_database()
    if db is None:
        return dict(_REGISTERED_FAMILIES)

    for fid, meta in BUNDLED_FONTS.items():
        families = []
        for filename in meta.get("files", []):
            path = resolve_font_path(filename)
            if path is None or not path.exists():
                continue
            try:
                font_id = db.addApplicationFont(str(path))
                if font_id == -1:
                    continue
                registered = db.applicationFontFamilies(font_id) or []
                if registered:
                    families.append(registered[0])
            except Exception:
                continue
        if not families:
            continue
        hint = (meta.get("family_hint") or "").replace(" ", "").lower()
        chosen = families[0]
        for fam in families:
            if hint and fam.replace(" ", "").lower() == hint:
                chosen = fam
                break
        _REGISTERED_FAMILIES[fid] = chosen

    return dict(_REGISTERED_FAMILIES)


def registered_family(choice: str) -> Optional[str]:
    """返回已注册的**真实** family name；未注册（缺字体）返回 None。"""
    return _REGISTERED_FAMILIES.get(choice or "")


def _reset_registered_families() -> None:
    """仅供测试：清空注册缓存。"""
    _REGISTERED_FAMILIES.clear()


# ---------------------------------------------------------------------------
# 家族链（单一收口）
# ---------------------------------------------------------------------------
def _resolve_family(choice: str) -> Optional[str]:
    meta = FONT_IDS.get(choice or "")
    if meta is None:
        return None
    if meta.get("bundled"):
        return _REGISTERED_FAMILIES.get(choice)
    return meta.get("qt_family")


def _icon_family() -> Optional[str]:
    """图标字体族（文字链回退族，排在通用族 ``sans-serif`` 之前）。

    真值源 = ``gui.icons.FONT_FAMILY_NAME``（惰性 import，避免模块级循环依赖）。
    图标模块不可用 / 常量缺失时返回 ``None`` —— 此时家族链与引入图标族之前
    **逐字节一致**（缺资源优雅降级，R-K/R-Q）。
    """
    try:
        from gui.icons import FONT_FAMILY_NAME
    except Exception:
        return None
    return FONT_FAMILY_NAME or None


def font_family_chain(choice: Optional[str], scope: str = "body") -> str:
    """生成字体家族链（唯一收口点）。

    - ``scope="body"``：``<family>, Microsoft YaHei, remixicon, sans-serif``；
      若 ``choice`` 是 title-only（粉圆）→ 强制回落资源圆体（Q-E4 守卫）。
    - ``scope="title"``：choice=huninn 用粉圆真实 family，否则同 body。
    - 内置字体缺文件时退到默认字体的已注册 family，再退化到雅黑（不崩）。
    - 图标族（``remixicon``）在通用族 ``sans-serif`` 之前插入，且经去重保序
      **不重复、不排在 generic 之后**（D-V21-06：PUA 字形随文案流渲染）。
    """
    choice = (choice or "").strip() or default_font_choice()
    if choice not in FONT_IDS:
        choice = default_font_choice()

    # 粉圆仅标题位（Q-E4 单一收口守卫：无法被误设为正文）
    if scope == "body" and is_title_only(choice):
        choice = default_font_choice()

    family = _resolve_family(choice)
    if not family:
        # 内置字体缺失（打包疏漏 / 未子集化）→ 退到默认字体已注册 family
        family = _REGISTERED_FAMILIES.get(default_font_choice())

    parts = []
    if family:
        parts.append(family)
    parts.append(_FALLBACK_FAMILY)
    parts.append(_icon_family())  # 图标族：generic 之前的回退层
    parts.append(_GENERIC_FALLBACK)

    # 去重保序
    seen = set()
    ordered = []
    for item in parts:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ", ".join(ordered)


def primary_family(choice: Optional[str], scope: str = "body") -> str:
    """家族链首（供 ``QFont(...)`` 用）。"""
    return font_family_chain(choice, scope).split(",")[0].strip()


def qss_font_family(choice: Optional[str], scope: str = "body") -> str:
    """**QSS 出口**：把家族链渲染成 QSS 可解析的 family 列表。

    产出形如 ``"Resource Han Rounded CN", "Microsoft YaHei", "remixicon", sans-serif``：
    **每个族名各自加双引号，通用族（``sans-serif`` 等）不加引号**。

    为什么需要它（既有缺陷根因）：QSS 模板原先把占位符**整条包在一对引号里**
    （``font-family: "${font_family}";``），替换后 Qt 把整串当成**一个不存在的
    族名** → 整条链不解析 → 用户所选界面字体与图标字形均无法生效。本出口提供
    正确的逐族引号形态；配套把 QSS 模板的外引号去掉（``font-family: ${font_family};``）。

    注意：:func:`font_family_chain` 的返回格式**保持不变**（逗号连接的裸链，供
    ``app.setFont`` / ``split(",")[0]`` 等消费），本函数是**并列的第二个出口**，
    不是对旧出口的改动。
    """
    items = []
    for raw in font_family_chain(choice, scope).split(","):
        name = raw.strip()
        if not name:
            continue
        if name.lower() in _GENERIC_FAMILIES:
            items.append(name)
        else:
            items.append(f'"{name}"')
    return ", ".join(items)
