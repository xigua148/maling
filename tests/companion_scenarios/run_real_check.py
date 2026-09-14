# -*- coding: utf-8 -*-
"""陪伴质量剧本套件 —— 真实档手工核对脚本（v1.6 P1-2 / D-V16-09）。

用途：在 mock 套件全绿之后，由人手动触发一次小样本真实 API 核对，
验证 mock 断言与真实模型行为方向一致（诚实性红线：只记录、不下免检结论）。

特性：
- 预算护栏：默认 --max-cost 1.0 元，超预算直接拒绝执行（R-K 诚实：仅按
  「字符量估算」，不做精确计费承诺，结果 JSON 中注明 estimate）；
- 双重确认：必须显式传 --yes 才会真正发请求；未配置 api_key 时安全跳过；
- 产物：docs/_qa_v16/companion_<yyyymmdd_HHMM>_real.json
  （含 mock 基线对比：mock 结果文件若存在则一并嵌入）。

用法（项目根目录）：
    python tests/companion_scenarios/run_real_check.py --replay   # 零成本：重跑 mock 并落盘对比
    python tests/companion_scenarios/run_real_check.py --yes      # 真实 API 小样本核对
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "docs" / "_qa_v16"
SCEN_DIR = Path(__file__).resolve().parent / "scenarios"

# R-A 红线（与 mock 套件保持同表）
REDLINE_WORDS = ["筹码", "胜率", "倒数", "断签", "打卡", "进度"]
REDLINE_RES = [re.compile(r"第\d+次"), re.compile(r"连续第\d+")]

# 真实档小样本探针（方向性核对，非通过/失败判据）：每条 ≤30 字，max_tokens 压低
REAL_PROBES = [
    {"probe_id": "R1_confide_no_advice",
     "text": "我今天有点难受，就想说说，不需要建议。",
     "expect_hint": "回复应共情、不列解决方案清单（人工判读）"},
    {"probe_id": "R2_fact_recall",
     "text": "（系统已知：我喜欢喝咖啡）我平时喜欢喝什么？",
     "expect_hint": "应答出咖啡（人工判读）"},
]
MAX_TOKENS = 120  # 压低成本：两条探针 × 120 tokens ≈ 远低于 ¥0.05（估算）


def _load_cfg():
    """读用户真实配置（只读 api_provider/api_key/base_url），不落盘任何密钥。"""
    try:
        from core import load_config
        cfg = load_config()
        return {"provider": getattr(cfg, "api_provider", ""),
                "key": getattr(cfg, "api_key", ""),
                "base_url": getattr(cfg, "api_base_url", "") or ""}
    except Exception as e:  # noqa: BLE001
        return {"provider": "", "key": "", "base_url": "", "error": str(e)}


def _redline_hit(text: str) -> list[str]:
    hits = [w for w in REDLINE_WORDS if w in text]
    hits += [m.group(0) for pat in REDLINE_RES for m in pat.finditer(text)]
    return hits


def run_mock_replay() -> dict:
    """零成本重跑 mock 剧本套件，返回摘要（供结果 JSON 对比段）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(Path(__file__).parent / "test_scenarios.py"),
         "-q", "--no-header"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    tail = (proc.stdout or "").strip().splitlines()
    return {"cmd": "pytest test_scenarios.py", "returncode": proc.returncode,
            "summary": tail[-1] if tail else "(no output)"}


def find_latest_mock_result() -> str:
    cands = sorted(OUT_DIR.glob("companion_*_mock.json"))
    return cands[-1].name if cands else ""


def call_real_api(cfg, text: str) -> str:
    """OpenAI 兼容最小调用（复用用户配置的 provider/key/base_url）。"""
    import urllib.request
    base = (cfg.get("base_url") or "https://api.deepseek.com").rstrip("/")
    url = f"{base}/chat/completions"
    body = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": text}],
        "max_tokens": MAX_TOKENS,
        "temperature": 0.7,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.get('key', '')}",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))


def main() -> int:
    ap = argparse.ArgumentParser(description="陪伴质量真实档手工核对")
    ap.add_argument("--replay", action="store_true", help="零成本：只重跑 mock 套件并落盘 JSON")
    ap.add_argument("--yes", action="store_true", help="确认花费预算，执行真实 API 探针")
    ap.add_argument("--max-cost", type=float, default=1.0, help="预算上限（元，估算口径）")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    if args.replay or not args.yes:
        summary = run_mock_replay()
        out = OUT_DIR / f"companion_{ts}_mock.json"
        out.write_text(json.dumps({
            "kind": "companion_scenarios_mock_replay",
            "time": ts, "scenario_count": len(list(SCEN_DIR.glob('*.json'))),
            "mock_summary": summary,
            "baseline": find_latest_mock_result(),
            "note": "mock 档零成本；真实档核对请显式 --yes",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[mock] {summary.get('summary', '')}")
        print(f"[mock] 结果已落盘: {out.relative_to(ROOT)}")
        return 0 if summary.get("returncode") == 0 else 1

    # ---- 真实档（需 --yes）----
    cfg = _load_cfg()
    if not cfg.get("key"):
        print("[real] 未检测到 api_key，安全跳过（不产生任何费用）。")
        return 2
    est = len(REAL_PROBES) * MAX_TOKENS * 2 / 1000.0 * 0.002  # 极粗估算（元）
    if est > args.max_cost:
        print(f"[real] 估算花费 ¥{est:.3f} 超预算 ¥{args.max_cost:.2f}，拒绝执行。")
        return 3

    probes = []
    for p in REAL_PROBES:
        t0 = time.time()
        try:
            reply = call_real_api(cfg, p["text"])
            err = ""
        except Exception as e:  # noqa: BLE001
            reply, err = "", f"{type(e).__name__}: {e}"
        probes.append({
            "probe_id": p["probe_id"], "text": p["text"],
            "reply": reply, "error": err, "elapsed_s": round(time.time() - t0, 1),
            "redline_hits": _redline_hit(reply),
            "expect_hint": p["expect_hint"],
        })

    out = OUT_DIR / f"companion_{ts}_real.json"
    out.write_text(json.dumps({
        "kind": "companion_scenarios_real_check",
        "time": ts, "mode": "manual", "cost_estimate_cny": round(est, 3),
        "note": "真实档仅方向性核对 + R-A 红线词自动扫描；语义判读需人工完成（R-K 诚实）",
        "baseline": find_latest_mock_result(),
        "probes": probes,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    bad = [p for p in probes if p.get("redline_hits") or p.get("error")]
    print(f"[real] 探针 {len(probes)} 条，红线/异常 {len(bad)} 条")
    print(f"[real] 结果已落盘: {out.relative_to(ROOT)}（语义判读请人工完成）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
