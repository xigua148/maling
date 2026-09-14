#!/usr/bin/env python3
"""码铃内置字体构建脚本（v1.9 B 块 / 设计 D-V19-06）。

**仅构建期使用**，不进运行时、不进 exe（fonttools / brotli / py7zr 均非运行依赖）。

作用
----
1. 取源字体：
   · 资源圆体 Resource Han Rounded（正文 / 界面，Regular + Medium）
   · jf open 粉圆 Open Huninn（标题 / 点缀，标题子集）
2. 子集化（pyftsubset）：
   · 正文：GB2312 全字（6763 汉字 + 682 符号）+ ASCII + 中文标点（Q-E5）
   · 标题：界面标题字 + 常用词（体积压到数百 KB）
3. 产物落 ``gui/assets/fonts/``（⚠-2：与 spec datas 目标目录 ``assets/fonts`` 一致）。
4. OFL 许可副本人 ``gui/assets/fonts/``（随包）+ ``docs/third_party_licenses/``（源树）。

源字体获取方式（不入库大文件，E-5）
----------------------------------
- 资源圆体：官方仓库 https://github.com/CyanoHao/Resource-Han-Rounded
  release 资产为 ``RHR-CN-<ver>.7z``（GitHub Releases）。本脚本默认从官方 release
  下载；若本机直连 github.com 受限，可通过 ``--github-proxy`` 指定加速前缀
  （如 ``https://ghproxy.net/``），或用 ``--source-dir`` 指向人工下载解压后的目录。
- jf open 粉圆：官方仓库 https://github.com/justfont/open-huninn-font
  （字体在仓库 ``font/`` 目录内，经 jsDelivr 拉取）。

用法
----
    python tools/build_fonts.py                 # 全自动（下载 + 子集 + 落盘 + 许可副本）
    python tools/build_fonts.py --source-dir X  # 用本地已有的源字体目录（跳过下载）
    python tools/build_fonts.py --charset-only  # 只生成字表文件，便于核对
    python tools/build_fonts.py --github-proxy https://ghproxy.net/

依赖：``pip install fonttools brotli py7zr``（构建期临时安装即可）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FONT_OUT_DIR = REPO_ROOT / "gui" / "assets" / "fonts"
LICENSE_OUT_DIR = REPO_ROOT / "docs" / "third_party_licenses"
CACHE_DIR = REPO_ROOT / "build_fonts_cache"

CTX = ssl.create_default_context()

# ---- 源 URL ----
RHR_VERSION = "0.990"
RHR_7Z = (f"https://github.com/CyanoHao/Resource-Han-Rounded/releases/download/"
          f"v{RHR_VERSION}/RHR-CN-{RHR_VERSION}.7z")
RHR_OFL = "https://raw.githubusercontent.com/CyanoHao/Resource-Han-Rounded/master/OFL-License.txt"
HUNINN_TTF = "https://cdn.jsdelivr.net/gh/justfont/open-huninn-font@2.0/font/jf-openhuninn-2.0.ttf"
HUNINN_OFL = "https://cdn.jsdelivr.net/gh/justfont/open-huninn-font@2.0/license.txt"

# ---- 产物名（与 gui/fonts.py BUNDLED_FONTS 对齐）----
RHR_REGULAR_OUT = "ResourceHanRoundedCN-Regular.ttf"
RHR_MEDIUM_OUT = "ResourceHanRoundedCN-Medium.ttf"
HUNINN_OUT = "jf-openhuninn-subset.ttf"


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------
def _download(url: str, dest: Path, min_size: int, proxies: list[str] | None = None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    urls = [p + url for p in (proxies or [])] + [url]
    for u in urls:
        for attempt in range(3):
            have = dest.stat().st_size if dest.exists() else 0
            if have >= min_size:
                return True
            headers = {"User-Agent": "maling-build/1.0"}
            if have:
                headers["Range"] = f"bytes={have}-"
            try:
                req = urllib.request.Request(u, headers=headers)
                with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
                    mode = "ab" if (have and r.status == 206) else "wb"
                    if mode == "wb":
                        have = 0
                    with open(dest, mode) as f:
                        while True:
                            chunk = r.read(1 << 20)
                            if not chunk:
                                break
                            f.write(chunk)
                if dest.stat().st_size >= min_size:
                    print(f"  [ok] {dest.name} ({dest.stat().st_size} bytes) via {u.split('/')[2]}")
                    return True
            except Exception as exc:  # noqa: BLE001
                print(f"  [retry] {dest.name} attempt={attempt} {type(exc).__name__}: {exc}")
                time.sleep(2)
    return dest.exists() and dest.stat().st_size >= min_size


# ---------------------------------------------------------------------------
# 字表生成（GB2312 6763 + ASCII + 标点）
# ---------------------------------------------------------------------------
def _gb2312_all() -> str:
    """解码全部合法 GB2312 双字节码位 → 6763 汉字 + 682 符号。"""
    chars = []
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                chars.append(bytes([lead, trail]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return "".join(chars)


def build_body_charset() -> str:
    """正文子集字表：GB2312 全字 + ASCII(0x20-0x7E) + 中文标点（Q-E5）。"""
    parts = [_gb2312_all()]
    parts.append("".join(chr(c) for c in range(0x20, 0x7F)))
    parts.append("".join(chr(c) for c in range(0x3000, 0x3040)))   # CJK 标点
    parts.append("".join(chr(c) for c in range(0xFF00, 0xFFF0)))   # 全角字符
    # 去重保序
    seen = set()
    out = []
    for ch in "".join(parts):
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return "".join(out)


# 标题子集：界面标题 / 常用词（可复现，字表固化在脚本内；≈ 数千字规模内精选，体积压到数百 KB）
_TITLE_WORDS = (
    "码铃关于设置首页帮助项目编辑器计划工具箱记忆中心角色人设工坊模型接口界面字体主题外观风格"
    "外观模式强调色浅色深色跟随系统快捷切换保存取消确定返回新建删除编辑复制粘贴重命名导入导出"
    "欢迎你好早安午安晚安今天明天昨天上午下午晚上时间日期节日纪念日生日相遇心情情绪状态进度"
    "记录回忆日记待办提醒计划任务番茄钟专注休息游戏扫雷卡片列表详情统计概览图谱时间线场景"
    "回应约定工作学习生活陪伴对话聊天消息发送接收输入输出语音朗读截图看屏授权确认提示警告"
    "错误成功失败加载中处理中思考正在准备完成未完成开启关闭启用禁用开启中已开启已关闭"
    "温柔可爱精致圆润清新简洁现代商务文艺手写圆体黑体楷体幼圆雅黑等线粉圆资源简介说明"
    "版本更新日志许可协议开源组件致谢版权作者仓库地址用途第三方依赖在线离线本地云端"
    "春夏秋冬风雪雨露星辰山河江海花草木叶云霞光阴岁月时光流年故事天气风景心情思绪"
    "一心一意三心二意四面八方五湖四海七上八下九牛一毛十全十美守株待兔画蛇添足"
    "亡羊补牢掩耳盗铃刻舟求剑拔苗助长自相矛盾滥竽充数画龙点睛对牛弹琴杯弓蛇影"
    "井底之蛙南辕北辙望梅止渴卧薪尝胆破釜沉舟完璧归赵纸上谈兵指鹿为马朝三暮四"
    "数据结构算法函数变量循环条件判断异常处理调试测试运行编译构建部署发布维护升级"
    "文件目录路径名称大小类型格式编码解码加密解密上传下载同步备份恢复撤销重做"
    "窗口面板按钮菜单标签文本框下拉列表复选框单选框滑块进度条提示框对话框弹窗"
    "会员等级经验积分签到奖励任务成就排行榜好友关注粉丝动态评论点赞分享收藏"
    "添加移除清空重置刷新搜索筛选排序分组折叠展开上一页下一页首页尾页跳转"
    "详细简单复杂困难容易快速缓慢正确错误准确清楚明白疑惑理解掌握熟悉"
    "目标计划行动坚持努力进步成长改变突破挑战机遇选择决定结果过程方法"
    "清晨午后黄昏深夜凌晨黎明正午子夜季节气候温度阳光月色星空晚风细雨"
    "微笑开心快乐幸福温暖甜蜜安心踏实平静放松自在悠然惬意舒畅满足"
    "思念牵挂惦记关怀照顾守护陪伴理解包容信任支持鼓励安慰体谅珍惜"
    "代码程序软件系统平台框架模块组件服务接口数据库网络安全性能优化"
    "需求设计开发测试上线迭代版本需求变更缺陷修复代码评审持续集成"
)


def build_title_charset() -> str:
    """标题子集字表：ASCII + CJK 标点 + 固定界面标题/常用词表。"""
    parts = ["".join(chr(c) for c in range(0x20, 0x7F))]
    parts.append("".join(chr(c) for c in range(0x3000, 0x3040)))
    parts.append("".join(chr(c) for c in range(0xFF00, 0xFFF0)))
    parts.append(_TITLE_WORDS)
    seen = set()
    out = []
    for ch in "".join(parts):
        if ch not in seen:
            seen.add(ch)
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# 7z 解包
# ---------------------------------------------------------------------------
def _extract_rhr(zip_path: Path, weights: list[str], out_dir: Path) -> dict[str, Path]:
    """解出 RHR-CN 7z 中的指定权重 TTF（优先 .ttf）。

    注意：该 7z 为 **solid 压缩**（全部成员共享一个压缩块），py7zr 的
    ``extract(targets=[...])`` 对 solid 块会报 LZMAError，故统一用 ``extractall``
    解出后再按权重挑选（构建期临时目录，可接受）。
    """
    import py7zr

    out_dir.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(zip_path, mode="r") as z:
        print(f"  [7z] {len(z.getnames())} members (solid) → extractall")
        z.extractall(path=out_dir)

    result: dict[str, Path] = {}
    for path in out_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".ttf", ".otf"):
            continue
        low = path.name.lower()
        for weight in weights:
            if weight.lower() not in low:
                continue
            if weight not in result or (
                path.suffix.lower() == ".ttf" and result[weight].suffix.lower() != ".ttf"
            ):
                result[weight] = path
    return result


# ---------------------------------------------------------------------------
# pyftsubset
# ---------------------------------------------------------------------------
def _subset(src: Path, dest: Path, charset_file: Path, extra_args: list[str] | None = None) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "fontTools.subset", str(src),
        f"--text-file={charset_file}",
        f"--output-file={dest}",
        "--layout-features=*",
        "--name-IDs=*",
        "--notdef-outline",
        "--recommended-glyphs",
        "--drop-tables+=DSIG",
    ]
    if extra_args:
        cmd.extend(extra_args)
    print(f"  [subset] {src.name} -> {dest.name}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print("  [subset-FAIL]", proc.stderr[-800:])
        return False
    print(f"  [subset-ok] {dest.name} ({dest.stat().st_size} bytes)")
    return True


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Build bundled fonts for MaLing (v1.9 B).")
    parser.add_argument("--source-dir", default="", help="本地源字体目录（跳过下载）")
    parser.add_argument("--github-proxy", default="", help="GitHub 加速前缀，如 https://ghproxy.net/")
    parser.add_argument("--charset-only", action="store_true", help="只生成字表文件")
    parser.add_argument("--keep-cache", action="store_true", help="保留下载缓存")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FONT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    LICENSE_OUT_DIR.mkdir(parents=True, exist_ok=True)

    body_charset = build_body_charset()
    title_charset = build_title_charset()
    body_charset_file = CACHE_DIR / "charset_body.txt"
    title_charset_file = CACHE_DIR / "charset_title.txt"
    body_charset_file.write_text(body_charset, encoding="utf-8")
    title_charset_file.write_text(title_charset, encoding="utf-8")
    print(f"[charset] body={len(body_charset)} title={len(title_charset)} 字")
    if args.charset_only:
        return 0

    proxies = [args.github_proxy] if args.github_proxy else ["https://ghproxy.net/", "https://gh-proxy.com/", "https://ghfast.top/"]
    source_dir = Path(args.source_dir) if args.source_dir else None

    # ---- 1. 取源文件 ----
    if source_dir:
        rhr_src_zip = None
        rhr_dir = source_dir
    else:
        rhr_src_zip = CACHE_DIR / f"RHR-CN-{RHR_VERSION}.7z"
        if not _download(RHR_7Z, rhr_src_zip, 30_000_000, proxies):
            print("[WARN] 资源圆体下载失败：请用 --source-dir 指向人工下载解压的目录。")
            rhr_src_zip = None
        rhr_dir = CACHE_DIR / "rhr_extract"

    huninn_src = (source_dir / "jf-openhuninn-2.0.ttf") if source_dir else (CACHE_DIR / "jf-openhuninn-2.0.ttf")
    if source_dir is None and not _download(HUNINN_TTF, huninn_src, 4_000_000):
        print("[WARN] jf open 粉圆下载失败。")

    # ---- 2. 解包资源圆体 ----
    rhr_regular = rhr_medium = None
    if rhr_src_zip and rhr_src_zip.exists():
        found = _extract_rhr(rhr_src_zip, ["Regular", "Medium"], rhr_dir)
        rhr_regular = found.get("Regular")
        rhr_medium = found.get("Medium")
    elif rhr_dir.exists():
        for p in rhr_dir.rglob("*.ttf"):
            low = p.name.lower()
            if "cn" in low and "regular" in low:
                rhr_regular = p
            elif "cn" in low and "medium" in low:
                rhr_medium = p

    # ---- 3. 子集化 ----
    ok_r = ok_m = ok_h = False
    if rhr_regular and rhr_regular.exists():
        ok_r = _subset(rhr_regular, FONT_OUT_DIR / RHR_REGULAR_OUT, body_charset_file)
    else:
        print("[WARN] 资源圆体 Regular 源缺失，跳过。")
    if rhr_medium and rhr_medium.exists():
        ok_m = _subset(rhr_medium, FONT_OUT_DIR / RHR_MEDIUM_OUT, body_charset_file)
    else:
        print("[WARN] 资源圆体 Medium 源缺失，跳过。")
    if huninn_src.exists():
        ok_h = _subset(huninn_src, FONT_OUT_DIR / HUNINN_OUT, title_charset_file)
    else:
        print("[WARN] jf open 粉圆源缺失，跳过。")

    # ---- 4. 许可副本（随包 + 源树）----
    lic_pairs = [
        (RHR_OFL, "OFL-Resource-Han-Rounded.txt"),
        (HUNINN_OFL, "OFL-jf-open-huninn.txt"),
    ]
    for url, name in lic_pairs:
        cached = CACHE_DIR / name
        if not cached.exists() and not _download(url, cached, 1000):
            continue
        for dest_dir in (FONT_OUT_DIR, LICENSE_OUT_DIR):
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached, dest_dir / name)

    if not args.keep_cache:
        shutil.rmtree(CACHE_DIR, ignore_errors=True)

    print("\n[SUMMARY]")
    print(f"  resource_rounded Regular: {'OK' if ok_r else 'MISSING'}")
    print(f"  resource_rounded Medium : {'OK' if ok_m else 'MISSING'}")
    print(f"  huninn subset           : {'OK' if ok_h else 'MISSING'}")
    for name in (RHR_REGULAR_OUT, RHR_MEDIUM_OUT, HUNINN_OUT):
        p = FONT_OUT_DIR / name
        if p.exists():
            print(f"    {name}: {p.stat().st_size/1024/1024:.2f} MB")
    return 0 if (ok_r and ok_h) else 1


if __name__ == "__main__":
    raise SystemExit(main())
