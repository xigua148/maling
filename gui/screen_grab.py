# -*- coding: utf-8 -*-
"""v1.4(B3) 屏抓共享底座 —— 虚拟桌面整帧合成 + 内存帧工具（design-v14 D-V14-07）。

与 screen_capture.py 的职责边界（R-D/R-E 关键，design-v14 §2.3）：
- screen_capture = 用户手动选区对话框（产物 = 临时 PNG 进附件条，属 R-E「用户主动截一张」例外）；
- screen_grab + ScreenWatchService = 用户显式开启的持续模式**内存帧**服务（产物 = 内存 data URI，
  不落盘）。两者共享本模块的底层屏抓函数，**不重造第二套截屏**。

本模块能力（纯函数/数据类，无 QWidget，可 offscreen 单测）：
- CaptureResult：合成帧 + 虚拟桌面逻辑矩形 + 基准 DPR + 各屏几何快照；
- grab_virtual_desktop()：从 screen_capture._capture_desktop 语义抽取的独立实现
  （多屏 grabWindow + 主屏 DPR 基准合成；混合 DPR 已知边界一并继承）；
- pixmap_to_jpeg_bytes / pixmap_to_data_uri：QImage 等比缩放到 max_width 后存 JPEG（内存），
  失败回落 PNG —— 只经 Qt 自带编解码，不引 Pillow/numpy（R-F）；
- frame_changed_ratio()：缩略灰度字节差比 0..1（QImage.bits() memoryview，无第三方）；
- crop_region()：B2 授权缩略图用（图像像素坐标系矩形裁剪）。

坐标口径（design-v14 共享知识 22）：合成帧为「虚拟桌面逻辑矩形」按主屏 DPR 放大后的
**物理像素图**；其宽度 img_w 对应逻辑宽度 vr.width()，任意图上像素可等比反算回逻辑坐标。
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap, QScreen

logger = logging.getLogger("maid_coder.gui.screen_grab")

# 送视觉模型的整帧图最长边上限（先等比缩小再 JPEG，控 token/体积）
_JPEG_MAX_WIDTH = 1568
_JPEG_QUALITY = 82


@dataclass
class CaptureResult:
    """一次虚拟桌面整帧抓取结果（全部内存，无落盘）。"""

    pixmap: Optional[QPixmap]           # 合成位图（物理像素；可能为 None = 失败）
    virtual_rect: QRect                  # 虚拟桌面逻辑矩形（各屏 geometry 并集，可含负坐标）
    dpr: float                           # 合成基准 DPR（主屏）
    ok: bool = False
    screen_geos: List[Tuple[int, int, int, int, float]] = field(default_factory=list)
    #                              (geo.x, geo.y, geo.w, geo.h, devicePixelRatio)

    @property
    def image_width(self) -> int:
        """合成位图物理像素宽（与 virtual_rect 宽度构成坐标换算比例）。"""
        if self.pixmap is None:
            return 0
        return self.pixmap.width()

    @property
    def image_height(self) -> int:
        if self.pixmap is None:
            return 0
        return self.pixmap.height()


def grab_virtual_desktop() -> CaptureResult:
    """抓取整个虚拟桌面合成帧（多屏并集 + 主屏 DPR 基准，行为等价 screen_capture 旧逻辑）。

    失败返回 CaptureResult(ok=False)，绝不抛异常、绝不写盘。
    """
    try:
        screens: List[QScreen] = QGuiApplication.screens()
        if not screens:
            logger.debug("screen_grab: 无可用屏幕")
            return CaptureResult(None, QRect(), 1.0, False, [])
        # 虚拟桌面逻辑矩形 = 各屏 geometry 并集
        vr = QRect()
        geos: List[Tuple[int, int, int, int, float]] = []
        for sc in screens:
            geo = sc.geometry()
            vr = vr.united(QRect(geo))
            dpr_sc = float(sc.devicePixelRatio() or 1.0)
            geos.append((geo.x(), geo.y(), geo.width(), geo.height(), dpr_sc))
        dpr = float(QGuiApplication.primaryScreen().devicePixelRatio() or 1.0)
        dpr = max(1.0, dpr)
        w = int(vr.width() * dpr)
        h = int(vr.height() * dpr)
        if w <= 0 or h <= 0:
            logger.debug("screen_grab: 合成尺寸无效 (%dx%d)", w, h)
            return CaptureResult(None, vr, dpr, False, geos)
        canvas = QPixmap(w, h)
        canvas.setDevicePixelRatio(dpr)  # 后续 paint 以逻辑尺寸 1:1 呈现（沿用 P1-2 口径）
        canvas.fill(QColor(0, 0, 0))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        try:
            for sc in screens:
                pm = sc.grabWindow(0)  # 已带该屏 dpr 的高分辨率位图
                if pm is None or pm.isNull():
                    continue
                geo = sc.geometry()
                target = QRectF(
                    (geo.x() - vr.x()) * dpr,
                    (geo.y() - vr.y()) * dpr,
                    geo.width() * dpr,
                    geo.height() * dpr,
                )
                painter.drawPixmap(target, pm, QRectF(pm.rect()))
        finally:
            painter.end()
        return CaptureResult(canvas, vr, dpr, True, geos)
    except Exception as exc:
        logger.warning("screen_grab: 虚拟桌面整帧合成失败: %s", exc)
        return CaptureResult(None, QRect(), 1.0, False, [])


# ---------------------------------------------------------------------------
# 内存帧工具（JPEG/data URI / 帧差比 / 区域裁剪）
# ---------------------------------------------------------------------------

def pixmap_to_image(pm: QPixmap) -> Optional[QImage]:
    """QPixmap → QImage（物理像素矩阵）；失败返回 None。"""
    if pm is None:
        return None
    try:
        img = pm.toImage()
        if img is None or img.isNull():
            return None
        return img
    except Exception as exc:
        logger.debug("pixmap_to_image 失败: %s", exc)
        return None


def image_scaled(img: QImage, max_width: int = _JPEG_MAX_WIDTH) -> QImage:
    """等比缩放到最长边 ≤ max_width（超宽才缩放）。"""
    if img is None or img.isNull():
        return img
    try:
        if img.width() <= max_width and img.height() <= max_width:
            return img
        if img.width() >= img.height():
            tw = max_width
            th = max(1, int(img.height() * max_width / max(1, img.width())))
        else:
            th = max_width
            tw = max(1, int(img.width() * max_width / max(1, img.height())))
        return img.scaled(
            tw, th,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception as exc:
        logger.debug("image_scaled 失败: %s", exc)
        return img


def qimage_to_jpeg_bytes(img: QImage, quality: int = _JPEG_QUALITY) -> Optional[bytes]:
    """QImage → JPEG bytes（内存）；JPEG 失败回落 PNG bytes。"""
    if img is None or img.isNull():
        return None
    fmt = "JPEG"
    data = _qimage_save_to_bytes(img, fmt, quality)
    if data:
        return data
    # 回落 PNG（透明/极端色板等 JPEG 不支持的场景）
    data = _qimage_save_to_bytes(img, "PNG", quality)
    return data or None


def _qimage_save_to_bytes(img: QImage, fmt: str, quality: int) -> Optional[bytes]:
    try:
        arr = QByteArray()
        buf = QBuffer(arr)
        buf.open(QBuffer.OpenModeFlag.WriteOnly)
        try:
            if fmt == "JPEG":
                # QImage.save 不直接支持 quality，写为带质量的 JPEG 用 QImageWriter
                from PySide6.QtGui import QImageWriter
                writer = QImageWriter(buf, QByteArray(fmt.encode("ascii")))
                writer.setQuality(int(quality))
                ok = writer.write(img)
            else:
                ok = img.save(buf, fmt)
            if not ok:
                return None
        finally:
            buf.close()
        data = bytes(arr)
        return data or None
    except Exception as exc:
        logger.debug("图像编码 %s 失败: %s", fmt, exc)
        return None


def image_bytes_to_data_uri(raw: bytes, mime: str = "image/jpeg") -> str:
    """bytes → data URI（内存，不落盘）。"""
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def pixmap_to_data_uri(
    pm: QPixmap, max_width: int = _JPEG_MAX_WIDTH, quality: int = _JPEG_QUALITY,
) -> Optional[str]:
    """整帧 QPixmap → 压缩 JPEG data URI（超长等比缩到 max_width）。失败返回 None。"""
    img = pixmap_to_image(pm)
    if img is None:
        return None
    scaled = image_scaled(img, max_width)
    data = qimage_to_jpeg_bytes(scaled, quality)
    if data is None:
        return None
    mime = "image/jpeg"  # JPEG 失败回落时可能是 PNG bytes
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    return image_bytes_to_data_uri(data, mime)


def frame_changed_ratio(a: QImage, b: QImage, thumb: int = 96) -> float:
    """两帧差异比 0..1：都缩为最长边 thumb 的灰度图后逐字节比较。

    - 复用 QImage.bits() memoryview，无 numpy/Pillow（R-F）；
    - 返回 0.0（完全相同）~ 1.0（完全不同）；任一帧无效返回 1.0（视为变化）。
    """
    if a is None or b is None or a.isNull() or b.isNull():
        return 1.0
    try:
        ga = _to_gray_thumb(a, thumb)
        gb = _to_gray_thumb(b, thumb)
        if ga is None or gb is None:
            return 1.0
        wa, ha = ga.width(), ga.height()
        wb, hb = gb.width(), gb.height()
        # 理论同屏两帧宽高一致；异常/变形帧仍按公共区比较（防御）
        w, h = min(wa, wb), min(ha, hb)
        if w <= 0 or h <= 0:
            return 1.0
        ba = bytes(ga.constBits()) if w == wa and h == ha else bytes(_sub_area(ga, w, h))
        bb = bytes(gb.constBits()) if w == wb and h == hb else bytes(_sub_area(gb, w, h))
        total = max(1, w * h)
        if len(ba) < total or len(bb) < total:
            return 1.0
        diff = sum(1 for x, y in zip(ba[:total], bb[:total]) if x != y)
        return diff / float(total)
    except Exception as exc:
        logger.debug("帧差比计算失败: %s", exc)
        return 1.0


def _to_gray_thumb(img: QImage, thumb: int) -> Optional[QImage]:
    """等比缩放到最长边 thumb 的灰度 QImage（Format_Grayscale8）。"""
    try:
        if img.width() >= img.height():
            tw = thumb
            th = max(1, int(img.height() * thumb / max(1, img.width())))
        else:
            th = thumb
            tw = max(1, int(img.width() * thumb / max(1, img.height())))
        scaled = img.scaled(
            tw, th,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        gray = scaled.convertToFormat(QImage.Format.Format_Grayscale8)
        return gray
    except Exception as exc:
        logger.debug("灰度缩略失败: %s", exc)
        return None


def _sub_area(img: QImage, w: int, h: int) -> bytes:
    """裁剪图像左上角 w×h 区域为 bytes（逐行像素）。"""
    out = bytearray()
    for y in range(h):
        start = y * img.bytesPerLine()
        row = bytes(img.constBits()[start:start + img.bytesPerLine()])
        out.extend(row[:w])
    return bytes(out)


def crop_region(pm: QPixmap, center_x: int, center_y: int, w: int = 280, h: int = 180) -> QPixmap:
    """B2 授权缩略图：按**图像像素坐标**裁剪以 (center_x,center_y) 为中心 w×h 的区域。

    坐标解释权归调用方（图上有比例换算后得到中心像素）；pm 为合成帧或压缩帧 QPixmap。
    """
    try:
        if pm is None or pm.isNull():
            return QPixmap()
        img = pixmap_to_image(pm)
        if img is None:
            return QPixmap()
        left = int(center_x) - int(w) // 2
        top = int(center_y) - int(h) // 2
        left = max(0, min(left, img.width() - 1))
        top = max(0, min(top, img.height() - 1))
        wc = min(int(w), img.width() - left)
        hc = min(int(h), img.height() - top)
        if wc <= 0 or hc <= 0:
            return QPixmap()
        crop_img = img.copy(left, top, wc, hc)
        pm = QPixmap.fromImage(crop_img)
        return pm if pm is not None and not pm.isNull() else QPixmap()
    except Exception as exc:
        logger.debug("区域裁剪失败: %s", exc)
        return QPixmap()


def image_size_of_uri(uri: str) -> Optional[Tuple[int, int]]:
    """从 data URI 解码出图像的像素尺寸（用于坐标比例换算）；失败返回 None。

    v1.4.1-勘：QImageReader 需 QIODevice 构造（PySide6 不支持 QByteArray 直接构造，
    会抛 TypeError 被吞导致恒 None）——先经 QBuffer 走 reader，再回落 QImage.fromData。
    """
    try:
        if not uri or not uri.startswith("data:image/"):
            return None
        header, _, b64 = uri.partition(",")
        raw = base64.b64decode(b64) if b64 else b""
        if not raw:
            return None
        from PySide6.QtGui import QImageReader
        arr = QByteArray(raw)
        buf = QBuffer(arr)
        opened = buf.open(QBuffer.OpenModeFlag.ReadOnly)
        if opened:
            try:
                reader = QImageReader(buf)
                size = reader.size()
                if size is not None and size.isValid() and size.width() > 0 and size.height() > 0:
                    return size.width(), size.height()
            finally:
                buf.close()
        img = QImage.fromData(raw)
        if img is not None and not img.isNull():
            return img.width(), img.height()
        return None
    except Exception as exc:
        logger.debug("data URI 尺寸解析失败: %s", exc)
        return None
