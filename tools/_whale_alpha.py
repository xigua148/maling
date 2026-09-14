# -*- coding: utf-8 -*-
"""给鲸鱼娘立绘做透明背景（对齐小铃的透明 PNG）。

背景特征（实测）：接近纯白/浅灰（亮度 212~255），但**带噪点**（边框有 167~183 种颜色），
且**角色已触到画面边缘**，因此「从四角 flood fill」不可靠（实测四角透明率 2%~44% 不均）。

算法（不依赖 numpy/scipy）：
  1. 灰度化 → 候选背景 = 亮度 ≥ 阈值（自适应：取边框亮度分位数）
  2. 从**所有边框上的候选像素**出发做连通域标记（BFS）——只把**与边缘连通**的浅色区域
     判为背景，从而**不会误抠角色身上的白色**（围裙/花边/高光/眼睛）
  3. alpha：背景 0 / 前景 255，再轻度羽化做抗锯齿
  4. 输出 RGBA PNG
"""
from __future__ import annotations

import os
import sys
from collections import deque

from PIL import Image, ImageFilter


def _border_luma_percentile(gray, w, h, q=0.35):
    """用边框像素亮度分位数当阈值（自适应不同图的背景明暗）。"""
    vals = []
    for x in range(0, w, 4):
        vals.append(gray[x, 0]); vals.append(gray[x, h - 1])
    for y in range(0, h, 4):
        vals.append(gray[0, y]); vals.append(gray[w - 1, y])
    vals.sort()
    return vals[int(len(vals) * q)]


def _threshold_for(gray, w, h, luma_floor: int) -> int:
    """决定「背景亮度阈值」。

    实测结论（cheeky.png 阈值扫描）：
      thr=205 → **角色白围裙被误抠**（围裙 ~90% 像素 ≥205，且与边缘连通）
      thr=220~235 → 围裙安全保留、背景干净  ← 安全窗口
      thr=245 → 背景暗角去不掉，出现噪点
    ⇒ 取「边框亮度 p35」并**钳制在 218~232**，使所有图都落在安全窗口内。
    注意：真正决定成败的是**连通性**（只抠与边缘连通的区域）+ **阈值不能过低**；
    阈值过低会让角色的浅色部位（围裙/花边）也变成候选并与外部连通。
    """
    p35 = _border_luma_percentile(gray, w, h, q=0.35)
    # 下压 15 级吃掉背景暗角/渐变，但钳制在 218~232 的安全窗口内（<218 会误抠白围裙）
    return min(max(p35 - 15, luma_floor), 232)


def compute_bg_mask(src_path: str, *, luma_floor: int = 218, min_blob: int = 300,
                    open_kernel: int = 5):
    """返回 (bg, w, h, thr, im)：

    bg 为 bytearray(w*h)，bg[i]==1 表示「与边缘连通的浅色背景」像素（应被抠成透明）。
    其余为前景（角色本体 + 白围裙等内部浅色）。
    该函数与 make_transparent 共用同一套背景判定逻辑，供 QC 单源复用。
    """
    im = Image.open(src_path).convert('RGB')
    w, h = im.size
    # 先去噪再阈值：源图背景是「带噪点的浅灰」，不滤波会把噪点误判成前景（实测满是椒盐噪点）
    gray = im.convert('L').filter(ImageFilter.MedianFilter(3))
    gpx = gray.load()

    thr = _threshold_for(gpx, w, h, luma_floor)

    # 候选背景
    cand = bytearray(w * h)
    for y in range(h):
        base = y * w
        for x in range(w):
            if gpx[x, y] >= thr:
                cand[base + x] = 1

    # ★ 形态学开运算（先腐蚀后膨胀）：断开「角色浅色部位 → 背景」的**细窄连通路径**。
    #   实测 question/smug/ciallo/hungry 等姿势下，白围裙会经抗锯齿细边与背景连通，
    #   于是被 BFS 整块吃掉（深色底上显示为黑洞）。开运算能切断这类 1~2px 的桥接，
    #   而大块背景不受影响。
    if open_kernel >= 3:
        _m = Image.frombytes('L', (w, h), bytes(cand))
        _m = _m.filter(ImageFilter.MinFilter(open_kernel)).filter(ImageFilter.MaxFilter(open_kernel))
        cand = bytearray(_m.tobytes())

    # 从所有边框候选点出发 BFS
    bg = bytearray(w * h)
    dq = deque()
    for x in range(w):
        for y in (0, h - 1):
            i = y * w + x
            if cand[i] and not bg[i]:
                bg[i] = 1; dq.append(i)
    for y in range(h):
        for x in (0, w - 1):
            i = y * w + x
            if cand[i] and not bg[i]:
                bg[i] = 1; dq.append(i)

    while dq:
        i = dq.popleft()
        y, x = divmod(i, w)
        if x > 0:
            j = i - 1
            if cand[j] and not bg[j]: bg[j] = 1; dq.append(j)
        if x < w - 1:
            j = i + 1
            if cand[j] and not bg[j]: bg[j] = 1; dq.append(j)
        if y > 0:
            j = i - w
            if cand[j] and not bg[j]: bg[j] = 1; dq.append(j)
        if y < h - 1:
            j = i + w
            if cand[j] and not bg[j]: bg[j] = 1; dq.append(j)

    # 去斑：把「小于 min_blob 像素的孤立前景连通块」判回背景。
    #   源图背景带噪点，单靠中值滤波仍会残留椒盐点（实测肉眼可见）——这些噪点都是
    #   很小的孤立块，而角色本体（含分离的灯泡、鲸鱼尾）是大块，可安全区分。
    if min_blob > 0:
        seen = bytearray(w * h)
        for start in range(w * h):
            if bg[start] or seen[start]:
                continue
            comp = []
            dq2 = deque([start])
            seen[start] = 1
            while dq2:
                i = dq2.popleft()
                comp.append(i)
                y, x = divmod(i, w)
                if x > 0:
                    j = i - 1
                    if not bg[j] and not seen[j]: seen[j] = 1; dq2.append(j)
                if x < w - 1:
                    j = i + 1
                    if not bg[j] and not seen[j]: seen[j] = 1; dq2.append(j)
                if y > 0:
                    j = i - w
                    if not bg[j] and not seen[j]: seen[j] = 1; dq2.append(j)
                if y < h - 1:
                    j = i + w
                    if not bg[j] and not seen[j]: seen[j] = 1; dq2.append(j)
            if len(comp) < min_blob:
                for i in comp:
                    bg[i] = 1

    return bg, w, h, thr, im


def make_transparent(src_path: str, dst_path: str, *, luma_floor: int = 218,
                     feather: float = 0.8, min_blob: int = 300, bleed: int = 6,
                     open_kernel: int = 5) -> float:
    bg, w, h, thr, im = compute_bg_mask(
        src_path, luma_floor=luma_floor, min_blob=min_blob, open_kernel=open_kernel)

    # ★ 去白边（color decontamination）：羽化只模糊了「蒙版」，但边缘半透明像素的
    #   **颜色仍是原来的白背景** —— 直接输出会在深色主题上看到一圈白色光晕
    #   （实测过渡带 80.9% 的像素接近纯白）。修法：把角色颜色向外扩 N 像素覆盖掉白边。
    if bleed > 0:
        rgb = [im.getpixel((x, y)) for y in range(h) for x in range(w)]
        # 从全部前景像素出发做 BFS，向背景外扩最多 bleed 层（单遍，比逐层全图扫描快得多）
        dist = bytearray(w * h)
        dq = deque()
        for i in range(w * h):
            if not bg[i]:
                dist[i] = 1
                dq.append(i)
        while dq:
            i = dq.popleft()
            d = dist[i]
            if d >= bleed:
                continue
            y, x = divmod(i, w)
            for j in (i - 1 if x > 0 else -1,
                      i + 1 if x < w - 1 else -1,
                      i - w if y > 0 else -1,
                      i + w if y < h - 1 else -1):
                if j >= 0 and dist[j] == 0:
                    rgb[j] = rgb[i]
                    dist[j] = d + 1
                    dq.append(j)
        for y in range(h):
            base = y * w
            for x in range(w):
                if bg[base + x]:
                    im.putpixel((x, y), rgb[base + x])

    # 前景 mask（255=保留），背景=0
    mask = Image.new('L', (w, h), 255)
    mpx = mask.load()
    trans = 0
    for y in range(h):
        base = y * w
        for x in range(w):
            if bg[base + x]:
                mpx[x, y] = 0
                trans += 1
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))

    out = im.convert('RGBA')
    out.putalpha(mask)
    out.save(dst_path)
    return trans / (w * h) * 100


if __name__ == '__main__':
    src = sys.argv[1]
    dst = sys.argv[2]
    r = make_transparent(src, dst)
    print(f"{os.path.basename(src)} -> {os.path.basename(dst)}  透明占比={r:.1f}%")
