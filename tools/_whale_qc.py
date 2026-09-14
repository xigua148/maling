# -*- coding: utf-8 -*-
"""双向 QC（基于抠图工具的真实背景判定 mask）。

compute_bg_mask() 给出「与边缘连通的浅色背景」像素（应透明）。
  - 背景残留(%) = 判定为背景的像素中、成品 alpha 仍 >8（未抠掉）的比例 —— 越低越好
  - 角色空洞(%) = 判定为前景（角色/白围裙等）的像素中、成品 alpha 仍 ==0（被吃）的比例 —— 越低越好
羽化让边缘有渐变，背景残留会略 >0（正常）；>3% 或空洞 >0.3% 视为需关注。
"""
from __future__ import annotations

import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _whale_alpha import compute_bg_mask


def qc_one(src_path, dst_path, luma_floor=218):
    bg, w, h, thr, _ = compute_bg_mask(src_path, luma_floor=luma_floor)
    res = Image.open(dst_path).convert('RGBA')
    ra = res.split()[3].load()
    bg_total = bg_kept = fg_total = fg_hole = 0
    for i in range(w * h):
        if bg[i]:
            bg_total += 1
            if ra[i % w, i // w] > 8:
                bg_kept += 1
        else:
            fg_total += 1
            if ra[i % w, i // w] <= 8:
                fg_hole += 1
    residual = bg_kept / bg_total * 100 if bg_total else 0.0
    hole = fg_hole / fg_total * 100 if fg_total else 0.0
    return residual, hole, thr


def main():
    base = sys.argv[1]
    rows = []
    for name in sorted(os.listdir(base)):
        if not name.lower().endswith('.png'):
            continue
        p = os.path.join(base, name)
        r, hl, thr = qc_one(p, p)
        rows.append((name, r, hl, thr))
    rows.sort(key=lambda t: -(t[1] + t[2]))
    print(f"{'image':28s} {'bg_residual%':>12s} {'fg_hole%':>10s} {'thr':>5s}")
    for name, r, hl, thr in rows:
        flag = '  <-- check' if (r > 3 or hl > 0.3) else ''
        print(f"{name:28s} {r:12.2f} {hl:10.2f} {thr:5d}{flag}")
    if rows:
        mr = sum(r for _, r, _, _ in rows) / len(rows)
        mh = sum(hl for _, _, hl, _ in rows) / len(rows)
        print(f"\nmean bg_residual={mr:.2f}%  mean fg_hole={mh:.2f}%  n={len(rows)}")
        worst = [t for t in rows if (t[1] > 3 or t[2] > 0.3)]
        print(f"flagged={len(worst)}: " + ", ".join(f"{n}(r={r:.1f}/h={hl:.1f})" for n, r, hl, _ in worst))


if __name__ == '__main__':
    main()
