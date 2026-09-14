# -*- coding: utf-8 -*-
"""把鲸鱼娘立绘分别贴在黑底/棋盘格底上合成接触印相表，便于肉眼判断：
   黑底 -> 残白（背景没抠掉）= 瑕疵；棋盘底 -> 透出的格子 = 角色被吃（洞）。
"""
from __future__ import annotations

import os
import sys

from PIL import Image

COLS = 6


def checker(w, h, cell=16):
    img = Image.new('RGB', (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (255, 0, 255) if ((x // cell + y // cell) % 2 == 0) else (0, 255, 255)
    return img


def composite_on(src_png, bg, cell_size):
    fg = Image.open(src_png).convert('RGBA')
    w, h = fg.size
    if bg == 'black':
        base = Image.new('RGB', (w, h), (0, 0, 0))
    else:
        base = checker(w, h, cell_size)
    base.paste(fg, (0, 0), fg)
    return base


def main():
    d = sys.argv[1]
    bg = sys.argv[2] if len(sys.argv) > 2 else 'black'
    out = sys.argv[3] if len(sys.argv) > 3 else '_contact_black.png'
    names = sorted(n for n in os.listdir(d) if n.lower().endswith('.png'))
    cell = Image.open(os.path.join(d, names[0])).convert('RGBA').size
    cw, ch = cell
    cols = COLS
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * cw, rows * ch), (20, 20, 20) if bg == 'black' else (30, 30, 30))
    for idx, n in enumerate(names):
        r, c = divmod(idx, cols)
        comp = composite_on(os.path.join(d, n), bg, 16)
        sheet.paste(comp, (c * cw, r * ch))
    sheet.save(out)
    print(f"wrote {out} ({cols}x{rows} grid, cell={cw}x{ch})")


if __name__ == '__main__':
    main()
