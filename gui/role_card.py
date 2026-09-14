"""gui/role_card.py —— v1.7 F8/F9 角色卡导出/导入/校验（纯逻辑，零 Qt 依赖）。

设计依据：design-v17.md D-V17-09 / §4.5 / Q-C10。
- 导出 = 人设字段子集白名单（name/description/system_prompt/personality/
  opening_lines/example_dialogues/current_expression）+ 版本标记；
  **绝不含** avatar 路径 / 角色 id / 记忆 / 亲密度 / 对话历史（R-I 红线）。
- 导入 = 轻量校验（Q-C10：体积 ≤1MB + 字段白名单 + 类型守卫；预览确认页列 v1.7.x）。
- 重名策略：`dedupe_import_name` 收敛为「XX（导入）」，仍冲突则追加序号。

本模块不建 Role 实例（避免耦合 page_role 的 Qt 导入链）——parse_card 返回
清洗后的干净 payload dict，由调用方（page_role）决定新建/覆盖。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

# 与 page_role 的归一化常量保持一致（此处复制常量而非 import，维持零 Qt 依赖；
# page_role.normalize_* 的边界规则与本模块一致：≤3 套开场白 / ≤5 组示例）。
MAX_OPENING_LINES = 3
MAX_EXAMPLE_DIALOGUES = 5

CARD_TYPE = "malingcard"
# v1.8(D-V18-06/Q-D7): schema v2 —— v1 卡全字段兼容（cover_image 缺省空）；
# v2 卡导入时未知字段忽略不崩（前向兼容铁则）。
SCHEMA_VERSION = 2
# Q-C10：单卡体积上限 1MB
MAX_CARD_BYTES = 1024 * 1024
# v1.8(D-V18-06/Q-D7): 封面上限 —— 压到 512px 内等比缩放后 base64 ≤500KB
COVER_MAX_PIXEL = 512
COVER_MAX_B64_BYTES = 500 * 1024

# 导出字段白名单（R-I：无 avatar/id/intimacy/created_at/历史；
# 记忆 / 亲密度 / 对话历史 / API 配置 / entities / response_rules 永不入卡）
EXPORT_FIELDS = (
    "name", "description", "system_prompt", "personality",
    "opening_lines", "example_dialogues", "current_expression",
    "cover_image",
    # v1.9(C/D-V19-01): 名字随卡携带（旧卡缺字段 → 空 → 自称"我"，零崩溃）
    "given_name",
)


class CardError(Exception):
    """角色卡解析失败（含原因的中文消息，直接呈现给用户）。"""


def _clamp_slider(value, default: int = 50) -> int:
    """性格三值守卫：非数值回默认，越界夹取 0-100。"""
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, v))


def _clean_opening_lines(value) -> List[str]:
    """开场白清洗：str 兼容单套旧数据；仅保留非空 str；≤3 套。"""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out[:MAX_OPENING_LINES]


def _clean_example_dialogues(value) -> List[Dict]:
    """示例对话清洗：仅保留 {user, assistant} 均为 str 的组；enabled 默认 True；≤5 组。"""
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


def export_card(role) -> Dict:
    """从 Role 实例导出角色卡 dict（字段白名单，R-I）。

    只读 getattr 防御：对缺新字段的旧 Role 对象也能安全导出（默认空）。
    v1.8(D-V18-06): schema v2 —— cover_image 恒写键（无封面为空串），
    保证白名单断言 EXPORT_FIELDS ⊆ card.keys() 恒真。
    """
    personality = getattr(role, "personality", None)
    return {
        "card_type": CARD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now().isoformat(),
        "name": str(getattr(role, "name", "") or ""),
        "description": str(getattr(role, "description", "") or ""),
        "system_prompt": str(getattr(role, "system_prompt", "") or ""),
        "personality": {
            "lively": _clamp_slider((personality or {}).get("lively", 50)),
            "rigorous": _clamp_slider((personality or {}).get("rigorous", 50)),
            "caring": _clamp_slider((personality or {}).get("caring", 50)),
        },
        "opening_lines": _clean_opening_lines(getattr(role, "opening_lines", None)),
        "example_dialogues": _clean_example_dialogues(
            getattr(role, "example_dialogues", None)
        ),
        "current_expression": str(
            getattr(role, "current_expression", "normal") or "normal"
        ),
        # v1.8: cover_image（data URI ≤500KB；无封面空串——列表回退既有头像逻辑）
        "cover_image": str(getattr(role, "cover_image", "") or ""),
        # v1.9(C/D-V19-01): 名字（空串 = 无名字 → 自称"我"）
        "given_name": str(getattr(role, "given_name", "") or ""),
    }


def prepare_cover_image(path: str) -> str:
    """本地图 -> 等比压至 COVER_MAX_PIXEL 内 + base64 ≤COVER_MAX_B64_BYTES 的 data URI。

    v1.8(D-V18-06)：导入时选本地图（PNG/JPG/WebP）→ QImageReader 读入 →
    长边 >512px 等比缩放（SmoothTransformation）→ PNG 先试（保透明），
    超 500KB 转 JPEG 逐级降质（90→60）→ 仍超限抛 CardError。
    单文件自包含分享心智：返回 "data:image/<mime>;base64,<b64>" 直接内嵌卡。
    惰性 import Qt（保持本模块顶层零 Qt 依赖）。
    """
    import base64 as _b64
    import io as _io

    try:
        from PySide6.QtGui import QImage, QImageReader, Qt as QtEnum
    except Exception as exc:  # pragma: no cover - Qt 环境缺失（测试/cli）
        raise CardError(f"封面读取需要图形环境：{exc}") from exc

    reader = QImageReader(str(path))
    image = reader.read()
    if image is None or image.isNull():
        raise CardError(f"封面图片读取失败：{reader.errorString() or '不支持的格式'}")

    # 等比缩到 512px 内（长边）
    long_side = max(image.width(), image.height())
    if long_side > COVER_MAX_PIXEL:
        ratio = COVER_MAX_PIXEL / float(long_side)
        from PySide6.QtGui import QTransform
        transform = QTransform()
        transform.scale(ratio, ratio)
        image = image.transformed(transform, QtEnum.SmoothTransformation)

    def _encode(img, fmt: str, quality: int = -1) -> bytes:
        buf = _io.BytesIO()
        from PySide6.QtCore import QBuffer, QByteArray
        ba = QByteArray()
        qbuf = QBuffer(ba)
        qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
        img.save(qbuf, fmt.upper(), quality)
        qbuf.close()
        buf.write(bytes(ba))
        return buf.getvalue()

    png = _encode(image, "PNG")
    mime, raw = ("image/png", png) if len(png) <= COVER_MAX_B64_BYTES else (None, None)
    if raw is None:
        for quality in (90, 80, 70, 60):
            jpg = _encode(image, "JPEG", quality)
            if len(jpg) <= COVER_MAX_B64_BYTES:
                mime, raw = "image/jpeg", jpg
                break
    if raw is None:
        raise CardError("封面压缩后仍超过 500KB，请换一张小一点的图片。")
    encoded = _b64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def parse_card(data, size_limit: int = MAX_CARD_BYTES) -> Dict:
    """校验并清洗角色卡 payload，返回白名单内干净 dict（Q-C10 轻校验）。

    抛 CardError 的情形：
    - data 非 dict / 序列化体积超限；
    - card_type 存在但不为 malingcard（缺失容忍——手写 JSON 也能导入）；
    - name 缺失或非字符串非空。

    其余字段全部类型守卫 + 默认值，绝不抛错（缺字段 = 默认值）。
    """
    if not isinstance(data, dict):
        raise CardError("角色卡格式不正确：根节点必须是 JSON 对象")
    try:
        serialized = json.dumps(data, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise CardError(f"角色卡序列化失败：{exc}") from exc
    if len(serialized.encode("utf-8")) > size_limit:
        raise CardError("角色卡超过 1MB 体积上限，已拒绝导入")

    card_type = data.get("card_type")
    if card_type is not None and str(card_type) != CARD_TYPE:
        raise CardError(f"不是码铃角色卡（card_type={card_type!r}）")

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CardError("角色卡缺少有效的角色名称（name）")

    personality_raw = data.get("personality")
    personality = {
        "lively": _clamp_slider(
            personality_raw.get("lively", 50) if isinstance(personality_raw, dict) else 50
        ),
        "rigorous": _clamp_slider(
            personality_raw.get("rigorous", 50) if isinstance(personality_raw, dict) else 50
        ),
        "caring": _clamp_slider(
            personality_raw.get("caring", 50) if isinstance(personality_raw, dict) else 50
        ),
    }
    return {
        "name": name.strip()[:50],
        "description": str(data.get("description") or ""),
        "system_prompt": str(data.get("system_prompt") or ""),
        "personality": personality,
        "opening_lines": _clean_opening_lines(data.get("opening_lines")),
        "example_dialogues": _clean_example_dialogues(data.get("example_dialogues")),
        "current_expression": str(data.get("current_expression") or "normal"),
        # v1.8(D-V18-06): v2 卡封面（data URI）；v1 卡缺省空串全兼容；
        # 非法/超限封面置空（预览弹窗红字提示 +「仍要导入」降级路径）。
        "cover_image": _clean_cover_image(data.get("cover_image")),
        # v1.9(C/D-V19-01): 名字（旧卡缺字段 → ""，零崩溃；空 = 无名字 → 自称"我"）
        "given_name": str(data.get("given_name") or "").strip()[:30],
    }


def _clean_cover_image(value) -> str:
    """封面字段清洗：仅接受 data URI / 裸 base64 字符串，≤500KB；异常置空。"""
    s = str(value or "").strip()
    if not s:
        return ""
    if not s.startswith("data:image/"):
        s = f"data:image/png;base64,{s}"
    if len(s.encode("utf-8")) > COVER_MAX_B64_BYTES:
        return ""   # 超限降级：不拒卡（v1 兼容铁则），预览弹窗红字提示
    return s


def dedupe_import_name(name: str, existing_names: Optional[List[str]] = None) -> str:
    """导入重名收敛：撞名 → 「XX（导入）」；再撞 → 「XX（导入2）」「XX（导入3）」…"""
    existing = set(existing_names or [])
    if name not in existing:
        return name
    base = f"{name}（导入）"
    if base not in existing:
        return base
    seq = 2
    while f"{name}（导入{seq}）" in existing:
        seq += 1
    return f"{name}（导入{seq}）"


def personality_tier_word(value: int) -> str:
    """性格三值 -> 档位词（v1.8/D-V18-06，R-A：预览呈现不显数值）。"""
    v = _clamp_slider(value)
    if v >= 65:
        return "偏上"
    if v >= 35:
        return "适中"
    return "偏低"


def card_summary_text(card: Dict) -> str:
    """预览确认框用的人读摘要（纯文本拼接，零依赖）。

    v1.8(D-V18-06/R-A): 性格三值以「偏上/适中/偏低」档位词呈现，不显数值。
    """
    n_open = len(card.get("opening_lines") or [])
    n_dialog = len(card.get("example_dialogues") or [])
    desc = (card.get("description") or "").strip()
    given = (card.get("given_name") or "").strip()
    p = card.get("personality") or {}
    lines = [
        f"角色名称：{card.get('name', '')}",
        f"角色描述：{desc if desc else '（空）'}",
        # v1.9(C/D-V19-01): 名字（空 = 无名字 → 自称"我"，R-A：不显数值）
        f"角色名字：{given if given else '（未设置，自称「我」）'}",
        f"性格参数：活泼{personality_tier_word(p.get('lively', 50))} · "
        f"严谨{personality_tier_word(p.get('rigorous', 50))} · "
        f"贴心{personality_tier_word(p.get('caring', 50))}",
        f"开场白：{n_open} 套",
        f"示例对话：{n_dialog} 组",
        f"系统提示词：{len((card.get('system_prompt') or '').strip())} 字",
    ]
    return "\n".join(lines)
