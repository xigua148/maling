# -*- coding: utf-8 -*-
"""scene.py —— v1.8 F4 场景化陪伴（D-V18-07 / Q-D4 / Q-D5 / Q-D6）。

根级纯 stdlib 模块（与 timeline.py 同范式，无 Qt / 无服务依赖，可独立单测）：

- 四场景：💼工作(work) / ☕休息(rest) / 🌙睡前(sleep) / ✨自动(auto，默认态，
  非场景实体——auto 表示"按时段映射感知"）；
- 时段映射（Q-D4）：工作日（周一至周五）09:00–12:00 / 14:00–18:00 → 工作；
  22:30–次日 6:30（含周末）→ 睡前；其余 → 休息。周末不进工作场景；
- 手动切换**当日有效次日回落**（Q-D4）：GuiConfig 存 manual_scene +
  manual_scene_date（YYYY-MM-DD）；仅当日期 == 今天时覆盖自动感知，
  次日自然回落（无定时器、读取时惰性判定）；
- 每场景一套 system 语气指令文案（工作：简洁高效少寒暄 + 主动降档提示；
  休息：轻松随意；睡前：温柔安静、避免刺激性话题），经 request_injections
  基建注入（V16-0 请求级副本，不入 session.history；持续性底色另由
  chat_service 写幂等边界消息承载，⚠-5 双动作）；
- ~/.maid_coder/scenes.json 自定义场景映射表存取（本期仅映射表能力，
  自定义场景时段优先于内置映射；无 UI，供后续版本扩展）；
- scene_auto 总开关（GuiConfig，默认 True）：False = 场景功能整体关闭
  （无注入、无主动降档，NIGHT_CARE 深夜关怀不受影响）。

三层叠加优先级（Q-D5）：① 情绪陪伴激活（当轮 confide 命中 + 负面信号）
> ② 场景 > ③ 意图五态。情绪激活当轮场景注入挂起（逐轮判定，无持久模式）；
挂起判定与注入编排见 gui/chat_service.py（V18-12）。
"""
import json
import os
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# 场景常量与文案
# ---------------------------------------------------------------------------
SCENE_WORK = "work"
SCENE_REST = "rest"
SCENE_SLEEP = "sleep"
SCENE_AUTO = "auto"          # 选择器默认态（非场景实体，= 按时段自动感知）
SCENES = (SCENE_WORK, SCENE_REST, SCENE_SLEEP)

# UI 展示名（chip / 下拉 / 边界消息共用）
SCENE_LABELS = {
    SCENE_WORK: "💼 工作模式",
    SCENE_REST: "☕ 休息模式",
    SCENE_SLEEP: "🌙 睡前模式",
}

# 每场景一套 system 语气指令（D-V18-07；request_injections 注入用）。
# 措辞约束：一句话说清语气底色，不说教、不带数值（R-A 纪律）。
SCENE_TONES = {
    SCENE_WORK: (
        "【场景语气 · 工作】现在是主人的工作时间。回复请简洁高效、少寒暄，"
        "直奔主题先给结论；主人连续忙碌时可以在合适的地方轻轻提醒一句"
        "适当休息、起来活动一下（一句就好，不催促）。"
    ),
    SCENE_REST: (
        "【场景语气 · 休息】现在是主人的休息时间。回复可以轻松随意一些，"
        "像朋友闲聊，话题可以自然发散，不必刻意精简。"
    ),
    SCENE_SLEEP: (
        "【场景语气 · 睡前】现在是主人的睡前时间。回复请温柔安静、放缓节奏，"
        "避免刺激性或令人兴奋的话题，多给一些安心的陪伴感。"
    ),
}

# 场景切换幂等边界消息的识别前缀（chat_service 幂等替换用，仿 _ROLE_SWITCH_MARKER）
SCENE_BOUNDARY_MARKER = "【场景切换】"

# 时段映射（Q-D4，分钟数表示，[start, end) 左闭右开）
_WORK_WINDOWS = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))   # 工作日两段
_SLEEP_START = 22 * 60 + 30                               # 22:30
_SLEEP_END = 6 * 60 + 30                                  # 次日 6:30
_WEEKDAYS_WORK = (0, 1, 2, 3, 4)                          # 周一至周五（weekday()）

# 默认 scenes.json 路径（自定义场景映射表；用户数据，非记忆）
SCENES_FILE = os.path.join(os.path.expanduser("~"), ".maid_coder", "scenes.json")


def _minutes_of(now: datetime) -> int:
    return now.hour * 60 + now.minute


def auto_scene(now: Optional[datetime] = None,
               extra_scenes: Optional[list] = None) -> str:
    """按时段映射返回当前场景（Q-D4）。

    - 睡前优先：22:30–次日 6:30（含周末）→ sleep；
    - 工作日（周一至周五）9:00–12:00 / 14:00–18:00 → work，周末不进工作；
    - 其余 → rest；
    - extra_scenes（自定义映射表，load_user_scenes 产物）逐条优先判定：
      [start,end) 命中且 weekday 允许 → 返回自定义场景 id。
    """
    now = now or datetime.now()
    m = _minutes_of(now)
    if extra_scenes:
        for sc in extra_scenes:
            try:
                start, end = int(sc["start"]), int(sc["end"])
                weekdays = sc.get("weekdays") or tuple(range(7))
                if start <= end:
                    in_win = start <= m < end
                else:  # 跨夜窗口（如 23:00–07:00）
                    in_win = m >= start or m < end
                if in_win and now.weekday() in tuple(weekdays):
                    return str(sc.get("id") or SCENE_REST)
            except (KeyError, TypeError, ValueError):
                continue
    if m >= _SLEEP_START or m < _SLEEP_END:
        return SCENE_SLEEP
    if now.weekday() in _WEEKDAYS_WORK:
        for start, end in _WORK_WINDOWS:
            if start <= m < end:
                return SCENE_WORK
    return SCENE_REST


def manual_scene_active(manual_override: Optional[dict],
                        now: Optional[datetime] = None) -> Optional[str]:
    """手动覆盖当日有效性判定（Q-D4：当日有效、次日回落）。

    manual_override 形如 {"scene": "work", "date": "YYYY-MM-DD"}（GuiConfig
    manual_scene + manual_scene_date 组装，见 resolve_manual_override）。
    仅当 scene 合法且 date == 今天时返回场景 id；否则 None（回落自动感知）。
    """
    if not isinstance(manual_override, dict):
        return None
    scene = str(manual_override.get("scene") or "").strip()
    date = str(manual_override.get("date") or "").strip()
    now = now or datetime.now()
    if scene in SCENES and date == now.strftime("%Y-%m-%d"):
        return scene
    return None


def resolve_manual_override(manual_scene: str = "",
                            manual_scene_date: str = "") -> Optional[dict]:
    """从 GuiConfig 两键组装 manual_override 入参（无效/未选返回 None）。"""
    scene = str(manual_scene or "").strip()
    if scene not in SCENES:
        return None
    return {"scene": scene, "date": str(manual_scene_date or "").strip()}


def current_scene(now: Optional[datetime] = None,
                  manual_override: Optional[dict] = None,
                  extra_scenes: Optional[list] = None) -> str:
    """当前场景判定主入口：手动覆盖（当日有效）> 时段自动映射。"""
    manual = manual_scene_active(manual_override, now)
    if manual:
        return manual
    return auto_scene(now, extra_scenes)


def scene_tone_text(scene: str) -> str:
    """场景语气指令文案（未收录场景回落休息档，绝不返回空串）。"""
    return SCENE_TONES.get(scene) or SCENE_TONES[SCENE_REST]


def scene_chip_text(scene: str) -> str:
    """首页场景 chip 文案（当前场景状态 + 点按切换提示）。"""
    label = SCENE_LABELS.get(scene)
    return f"{label} · 点按切换" if label else ""


def scene_boundary_text(scene: str) -> str:
    """场景切换幂等边界消息（⚠-5 双动作②；仿角色切换边界消息范式）。

    语气底色随 LLM 历史留存（request_injections 只活一轮，留不住"持续性"）；
    技术上下文仍然有效，与 notify_role_switch 同口径。
    """
    label = SCENE_LABELS.get(scene, SCENE_LABELS[SCENE_REST])
    tone = scene_tone_text(scene)
    # 去掉语气指令里的【场景语气 · X】前缀，避免与边界标记重复
    core = tone.split("]", 1)[-1].strip() if "]" in tone else tone
    return (
        f"{SCENE_BOUNDARY_MARKER}当前进入「{label}」。从此条起，回应语气整体"
        f"切换为：{core}此前其他场景的语气底色不再延续；正在讨论的内容与"
        f"技术上下文仍然有效。"
    )


def load_user_scenes(path: Optional[str] = None) -> list:
    """读取自定义场景映射表（~/.maid_coder/scenes.json；本期仅映射表能力）。

    文件格式：{"custom_scenes": [{"id": "study", "start": 19*60, "end": 21*60,
    "weekdays": [0,1,2,3,4,5,6], "label": "📚 学习模式", "tone": "..."}]}
    （start/end 为分钟数；weekdays 为 weekday() 值列表，缺省 = 全周）。
    缺文件 / 坏 JSON / 字段残缺 → 静默返回 []（零破坏降级）。
    """
    p = path or SCENES_FILE
    try:
        if not os.path.exists(p):
            return []
        data = json.loads(open(p, encoding="utf-8").read())
        scenes = data.get("custom_scenes") if isinstance(data, dict) else None
        if not isinstance(scenes, list):
            return []
        out = []
        for sc in scenes:
            if not isinstance(sc, dict) or "id" not in sc or "start" not in sc \
                    or "end" not in sc:
                continue
            out.append(sc)
        return out
    except Exception:
        return []


def save_user_scenes(scenes: list, path: Optional[str] = None) -> bool:
    """写入自定义场景映射表（原子性弱要求：小文件直写；失败返回 False）。"""
    p = path or SCENES_FILE
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"custom_scenes": list(scenes or [])}, fh,
                      ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
