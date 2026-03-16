# -*- coding: utf-8 -*-
import logging
import os
import tempfile
import win32print
import win32api
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

PRINTER_NAME   = "XP-80C"
PAPER_WIDTH_PX = 550   # ลดจาก 576 เพื่อให้พอดีกระดาษ
FONT_SIZE      = 26
FONT_SIZE_LG   = 36
LINE_HEIGHT    = 34
LINE_HEIGHT_LG = 48
MARGIN_X       = 6

THAI_FONTS = [
    "C:/Windows/Fonts/THSarabunNew.ttf",
    "C:/Windows/Fonts/Tahoma.ttf",
    "C:/Windows/Fonts/Arial.ttf",
]


def _get_font(size):
    for path in THAI_FONTS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_receipt(lines: list) -> Image.Image:
    font_normal = _get_font(FONT_SIZE)
    font_large  = _get_font(FONT_SIZE_LG)

    total_h = MARGIN_X * 2
    for line in lines:
        total_h += LINE_HEIGHT_LG if line.get("double_height") else LINE_HEIGHT
    total_h += 120

    img = Image.new("RGB", (PAPER_WIDTH_PX, total_h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = MARGIN_X
    for line in lines:
        text     = line.get("text", "")
        align    = line.get("align", "left")
        double_h = line.get("double_height", False)
        font     = font_large if double_h else font_normal
        lh       = LINE_HEIGHT_LG if double_h else LINE_HEIGHT

        try:
            bbox = font.getbbox(text)
            tw   = bbox[2] - bbox[0]
        except Exception:
            tw = len(text) * (FONT_SIZE // 2)

        if align == "center":
            x = max(MARGIN_X, (PAPER_WIDTH_PX - tw) // 2)
        elif align == "right":
            x = max(MARGIN_X, PAPER_WIDTH_PX - tw - MARGIN_X)
        else:
            x = MARGIN_X

        draw.text((x, y), text, font=font, fill=(0, 0, 0))
        y += lh

    return img


def print_receipt(lines: list, cut: bool = True):
    img = _render_receipt(lines)

    import time, subprocess
    # Unique filename per job — ป้องกัน conflict กรณี print หลาย job พร้อมกัน
    ts = int(time.time() * 1000)
    tmp_path = os.path.join(tempfile.gettempdir(), f"receipt_{ts}.bmp")
    img.save(tmp_path, "BMP")
    logger.info("Saved receipt image: %s (%dx%d)", tmp_path, img.width, img.height)

    try:
        result = subprocess.run(
            ["mspaint", "/pt", tmp_path, PRINTER_NAME],
            timeout=30,
        )
        logger.info("Printed via mspaint to %s (rc=%s)", PRINTER_NAME, result.returncode)
        time.sleep(2)  # รอ mspaint ปิดก่อนลบไฟล์
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass