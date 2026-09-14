"""GUI 工具函数 —— 资源路径解析、用户数据目录等跨平台工具。"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET


def get_resource_path(relative_path: str) -> Path:
    """统一资源路径解析：PyInstaller (.exe) vs 源码运行。"""
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent
    return base_path / relative_path


def get_user_data_dir() -> Path:
    """获取用户数据目录（跨平台）。"""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    data_dir = base / "maid_coder"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def theme_color(app_ctx: Any, key: str, fallback: str) -> str:
    """统一从主题引擎取色；未取到则使用 fallback。

    新增 GUI 控件（不依赖 QSS 主题的）应使用本函数取色，避免硬编码。
    """
    theme_engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
    if theme_engine is None:
        return fallback
    try:
        return theme_engine.get_color(key, fallback)
    except Exception:
        return fallback


# v1.9(V19-16/D-V19-14): D 风格（ui_whale）品牌口吻 —— 界面自称随当前角色人设。
def brand_persona_self(app_ctx: Any) -> Optional[str]:
    """D 风格（ui_whale）下的界面自称：当前角色 given_name（取不到→"我"）。

    - 非 D 风格返回 None（调用方保留默认中性文案，零行为变化）；
    - 只影响「界面自称 / 欢迎语 / 状态口吻」这几处口吻文案；
      产品标识（码铃 / 窗口标题 / exe 名 / package 名）一律不经本函数（D-V19-14 边界）；
    - 来源统一走 C 块规则 persona.self_reference(given_name)，人设标签永不进自称位。
    """
    theme_engine = getattr(app_ctx, "theme_engine", None) if app_ctx is not None else None
    if theme_engine is None:
        return None
    try:
        if theme_engine.current_theme_name() != "ui_whale":
            return None
    except Exception:
        return None
    given = ""
    try:
        from gui.pages.page_role import RoleManager
        role = RoleManager().default_role
        given = getattr(role, "given_name", "") or ""
    except Exception:
        given = ""
    try:
        from persona import self_reference
        return self_reference(given, fallback="我")
    except Exception:
        return (given or "").strip() or "我"


# v10.15: 附件 payload 拼装阈值与文本扩展名白名单
ATTACHMENT_TEXT_MAX_BYTES = 50 * 1024  # 50KB，超过则正文截断并附「已截断」标注
ATTACHMENT_TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".html", ".htm", ".xml", ".css", ".scss", ".less",
    ".sql", ".csv", ".tsv", ".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".m", ".mm", ".go", ".rs", ".java", ".kt",
    ".rb", ".php", ".pl", ".lua", ".r", ".scala", ".swift",
    ".env", ".gitignore", ".gitattributes", ".editorconfig", ".lock",
}


def _is_text_attachment(ext: str) -> bool:
    return (ext or "").lower() in ATTACHMENT_TEXT_EXTS


def _human_size(num: int) -> str:
    n = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# Office 文本文档扩展名：用标准库 zipfile + xml.etree 抽取正文，无需第三方库
ATTACHMENT_OFFICE_TEXT_EXTS = {".docx", ".xlsx"}

# v1.2.x(看图): 可随消息以图片直传的类型（OpenAI 兼容多模态 image_url）
IMAGE_ATTACHMENT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _extract_docx_text(zf: zipfile.ZipFile) -> str:
    """从 .docx 的 word/document.xml 抽取正文：按段落拼接 <w:t>，段落间换行。"""
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    root = ET.fromstring(zf.read("word/document.xml"))
    lines = []
    for para in root.iter(ns + "p"):
        lines.append("".join(t.text or "" for t in para.iter(ns + "t")))
    return "\n".join(lines)


def _xlsx_sheet_rows(zf: zipfile.ZipFile, sheet_file: str, ns: str, shared: list[str]) -> list[str]:
    """抽取单个 xlsx sheet 的单元格文本，返回行文本列表。

    覆盖三种单元格：共享字符串引用 (t=s)、内联字符串 (t=inlineStr)、普通数值 (v)。
    行内列用 " | " 分隔，保留空格列以帮助模型理解表格结构。
    """
    try:
        root = ET.fromstring(zf.read(sheet_file))
    except (KeyError, ET.ParseError):
        return []
    out = []
    for row in root.iter(ns + "row"):
        cells = []
        for c in row.iter(ns + "c"):
            ctype = c.get("t")
            if ctype == "inlineStr":
                is_node = c.find(ns + "is")
                cells.append(
                    "".join(x.text or "" for x in is_node.iter(ns + "t"))
                    if is_node is not None else ""
                )
                continue
            v = c.find(ns + "v")
            if v is None or v.text is None:
                cells.append("")
            elif ctype == "s":
                try:
                    idx = int(v.text)
                except (TypeError, ValueError):
                    idx = -1
                cells.append(shared[idx] if 0 <= idx < len(shared) else "")
            else:
                cells.append(v.text)
        line = " | ".join(cells)
        if line.strip(" |"):
            out.append(line)
    return out


def _extract_xlsx_text(zf: zipfile.ZipFile) -> str:
    """从 .xlsx 抽取表格正文：共享字符串表 + 各 sheet 单元格。

    共享字符串缺失时（少见实现）至少回退输出字符串表内容本身。
    """
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    shared: list[str] = []
    try:
        sroot = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in sroot.iter(ns + "si"):
            shared.append("".join(t.text or "" for t in si.iter(ns + "t")))
    except (KeyError, ET.ParseError):
        shared = []
    sheet_files = [
        n for n in zf.namelist()
        if n.startswith("xl/worksheets/")
        and (base := n.rsplit("/", 1)[-1]).startswith("sheet")
        and base.endswith(".xml")
        and base[5:-4].isdigit()
    ]
    sheet_files.sort(key=lambda n: int(n.rsplit("/", 1)[-1][5:-4]))
    if not sheet_files:
        return "\n".join(shared)
    out = []
    for sf in sheet_files:
        rows = _xlsx_sheet_rows(zf, sf, ns, shared)
        if rows:
            out.append(f"### sheet {sf.rsplit('/', 1)[-1]}")
            out.extend(rows)
    return "\n".join(out)


def _extract_office_text(path: str, ext: str) -> Optional[str]:
    """轻量抽取 Office 文本文档正文（纯标准库 zipfile + xml.etree）。

    - .docx：读 word/document.xml，按段落拼接 <w:t> 文本；
    - .xlsx：读 xl/sharedStrings.xml + 各 sheet 单元格（共享串 / 内联串 / 数值）。

    文件不存在、不是 zip、缺少关键部件或 XML 损坏时返回 None，
    由调用方降级为诚实的「无法解析内容」标注，绝不假装读到正文。
    """
    try:
        with zipfile.ZipFile(path) as zf:
            if ext == ".docx":
                return _extract_docx_text(zf)
            if ext == ".xlsx":
                return _extract_xlsx_text(zf)
    except Exception:
        return None
    return None


def _attachment_text_block(header: str, content: str, raw_size: int) -> str:
    """把抽取/读取到的正文按 50KB 上限封装为 attachment 文本块。

    ≤ 50KB 全量附正文；超限截断并附「已截断，原文件 N KB」标注，与纯文本路径一致。
    """
    raw = content.encode("utf-8")
    if len(raw) <= ATTACHMENT_TEXT_MAX_BYTES:
        return f"{header}\n<attachment>\n{content}\n</attachment>"
    truncated = raw[:ATTACHMENT_TEXT_MAX_BYTES]
    return (
        f"{header}\n<attachment 截断到 {ATTACHMENT_TEXT_MAX_BYTES // 1024}KB，原文件 {_human_size(raw_size)}>\n"
        f"{truncated.decode('utf-8', errors='replace')}\n<attachment 截断结束>"
    )


def build_attachment_payload(text: str, attachments: Optional[list]) -> str:
    """v10.15+: 附件 payload 拼装（共享给面板 + 独立窗口）。

    行为（按文件类型如实区分，避免让模型「假装看到文件」）：
    - 文本类附件 ≤ 50KB：把内容直接读到 prompt 里，并在末尾加 `</attachment>`；
    - 文本类附件 > 50KB：截断到 50KB 读入，并附 `<attachment 截断到 50KB，原文件 N KB>` 标注；
    - Office 文本文档 .docx / .xlsx：抽取正文给模型（Word 段落文本 / Excel 单元格
      文本），同样受 50KB 截断约束；抽取失败则诚实标注无法解析，只附附件信息；
    - 其它二进制附件（如 .pdf / .doc / .ppt / 图片 / .exe）：只在 prompt 里做一行
      诚实标注，明确告诉 AI 只能看到附件文件名与大小、无法解析内容。

    返回值是发给 API 的完整文本（含用户正文 + 附件摘要）。
    """
    if not attachments:
        return text or ""
    parts: list[str] = [text] if text else [""]
    for a in attachments:
        name = a.get("name", "") or ""
        path = a.get("path", "") or ""
        size = int(a.get("size", 0) or 0)
        ext = (a.get("ext", "") or Path(name).suffix or "").lower()
        header = f"[附件] {name} ({_human_size(size)})"
        if _is_text_attachment(ext):
            if not (path and Path(path).exists()):
                parts.append(f"{header}\n<attachment 文件不存在或不可读，无法读取内容，仅附附件信息>")
                continue
            try:
                full_bytes = Path(path).read_bytes()
            except Exception as e:
                parts.append(f"{header}\n<attachment 读取失败：{e}>")
                continue
            if len(full_bytes) <= ATTACHMENT_TEXT_MAX_BYTES:
                try:
                    content = full_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    content = full_bytes.decode("utf-8", errors="replace")
                parts.append(f"{header}\n<attachment>\n{content}\n</attachment>")
            else:
                truncated = full_bytes[:ATTACHMENT_TEXT_MAX_BYTES]
                try:
                    decoded = truncated.decode("utf-8", errors="replace")
                except Exception:
                    decoded = truncated.decode("latin-1", errors="replace")
                parts.append(
                    f"{header}\n<attachment 截断到 {ATTACHMENT_TEXT_MAX_BYTES // 1024}KB，原文件 {_human_size(size)}>\n{decoded}\n<attachment 截断结束>"
                )
        elif ext in ATTACHMENT_OFFICE_TEXT_EXTS:
            content = _extract_office_text(path, ext)
            if content is None:
                parts.append(
                    f"{header}\n<office attachment: {ext}，文件不存在或非标准 {ext} 格式，无法解析内容，仅附附件信息>"
                )
            elif not content.strip():
                parts.append(
                    f"{header}\n<office attachment: {ext}，已解析但文档中没有可读文本内容>"
                )
            else:
                parts.append(_attachment_text_block(header, content, size))
        elif ext in IMAGE_ATTACHMENT_EXTS:
            # 图片走多模态直传通道（chat_service 组 image_url content）；
            # 此处给纯文本上下文一句中性说明，避免与「已附图」矛盾。
            parts.append(
                f"{header}\n<image attachment: 该图片已随消息以图片形式发送（需模型支持视觉）；若当前模型不支持视觉将无法读取图片内容>"
            )
        else:
            parts.append(
                f"{header}\n<binary attachment: {ext or '未知类型'}，无法解析内容，请按文件名/扩展名回答>"
            )
    return "\n".join(p for p in parts if p != "" or len(parts) == 1)
