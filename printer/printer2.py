# -*- coding: utf-8 -*-
"""
printer2.py — พิมพ์ผ่าน Windows GDI รองรับภาษาไทย + full-width 80mm
              รองรับการวาด logo image ผ่าน StretchDIBits
"""

import ctypes
import logging
import struct
import win32ui
import win32con

logger = logging.getLogger(__name__)

PRINTER_NAME     = "XP-80C"
THAI_FONT        = "TH Sarabun New"

FONT_SIZE_NORMAL = 11   # point — เพิ่มจาก 10 เพื่อให้อ่านง่ายขึ้น
FONT_SIZE_LARGE  = 14   # point — header ใหญ่
FONT_SIZE_SMALL  = 9    # point — footer
LINE_SPACING     = 1.5
MARGIN_X_PCT     = 0.01  # 1% margin

# Logo file path — วาง logo.png ไว้ใน folder เดียวกับ printer2.py
LOGO_PATH        = r"C:\GloryMiddleware\printer\logo.png"
LOGO_WIDTH_PX    = 110   # ความกว้าง logo บนกระดาษ (pixel)

GDI32 = ctypes.windll.gdi32


# ── Font helpers ────────────────────────────────────────────────────────────

def _make_font(dc, size, bold=False):
    lpy    = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    height = -int(size * lpy / 72)
    return win32ui.CreateFont({
        "name":    THAI_FONT,
        "height":  height,
        "weight":  win32con.FW_BOLD if bold else win32con.FW_NORMAL,
        "charset": win32con.ANSI_CHARSET,
    })


def _lh(lpy, size):
    return int(size * lpy / 72 * LINE_SPACING)


# ── Logo via StretchDIBits (ctypes) ─────────────────────────────────────────

def _draw_logo_gdi(pdc, logo_path: str, dest_x: int, dest_y: int, target_w: int) -> int:
    """
    วาด logo image ลงบน printer DC โดยใช้ StretchDIBits
    Returns: actual height drawn (px), หรือ 0 ถ้า fail
    """
    try:
        from PIL import Image

        img      = Image.open(logo_path).convert("RGB")
        orig_w, orig_h = img.size
        target_h = max(1, int(target_w * orig_h / orig_w))
        img      = img.resize((target_w, target_h), Image.LANCZOS)

        # DIB = bottom-up → flip ก่อน
        img_flip = img.transpose(Image.FLIP_TOP_BOTTOM)
        pixels   = bytearray(img_flip.tobytes())  # RGB bytes

        # แปลง RGB → BGR (Windows DIB ใช้ BGR)
        for i in range(0, len(pixels), 3):
            pixels[i], pixels[i + 2] = pixels[i + 2], pixels[i]

        # แต่ละ row ต้อง align 4 bytes
        row_bytes = target_w * 3
        pad       = (4 - row_bytes % 4) % 4
        if pad:
            padded = bytearray()
            for row in range(target_h):
                padded += pixels[row * row_bytes:(row + 1) * row_bytes]
                padded += b'\x00' * pad
            pixels = padded

        # BITMAPINFOHEADER (40 bytes)
        bmi = struct.pack('<IiiHHIIiiII',
            40,           # biSize
            target_w,     # biWidth
            target_h,     # biHeight (positive = bottom-up)
            1,            # biPlanes
            24,           # biBitCount = 24-bit RGB
            0,            # biCompression = BI_RGB
            len(pixels),  # biSizeImage
            2835, 2835,   # pixels per meter (~72dpi)
            0, 0,         # clrUsed, clrImportant
        )

        hdc    = pdc.GetSafeHdc()
        result = GDI32.StretchDIBits(
            hdc,
            dest_x, dest_y, target_w, target_h,  # dest rect
            0, 0, target_w, target_h,             # src rect
            bytes(pixels),                         # pixel data
            bmi,                                  # BITMAPINFO
            0,                                    # DIB_RGB_COLORS
            0x00CC0020,                           # SRCCOPY
        )

        if result == 0:
            logger.warning("StretchDIBits returned 0 — logo อาจไม่แสดง")

        return target_h

    except Exception as e:
        logger.warning("Logo draw failed (%s): %s", logo_path, e)
        return 0


# ── Logo Header renderer ─────────────────────────────────────────────────────

def _render_logo_header(pdc, line: dict, y: int, page_w: int, margin_x: int, lpy: int) -> int:
    """
    วาด header แบบ logo-ซ้าย / company info-ขวา
    Returns: total height used (px)
    """
    logo_path = line.get("logo_path", LOGO_PATH)
    logo_w    = line.get("logo_width_px", LOGO_WIDTH_PX)
    gap       = 10  # px ระหว่าง logo กับ text

    # วาด logo
    logo_h = _draw_logo_gdi(pdc, logo_path, margin_x, y, logo_w)

    # Text column เริ่มต้นหลัง logo
    text_x = margin_x + logo_w + gap
    text_y = y

    # Company name — bold, FONT_SIZE_NORMAL+1
    name_size = FONT_SIZE_NORMAL + 1
    font_bold = _make_font(pdc, name_size, bold=True)
    pdc.SelectObject(font_bold)
    lh_bold = _lh(lpy, name_size)
    pdc.TextOut(text_x, text_y, line.get("company_name", ""))
    text_y += lh_bold

    # Branch, address, phone — normal size
    font_norm = _make_font(pdc, FONT_SIZE_NORMAL, bold=False)
    pdc.SelectObject(font_norm)
    lh_norm = _lh(lpy, FONT_SIZE_NORMAL)

    for field in ["branch_name", "address"]:
        val = line.get(field, "")
        if val:
            pdc.TextOut(text_x, text_y, val)
            text_y += lh_norm

    phone = line.get("phone", "")
    if phone:
        pdc.TextOut(text_x, text_y, f"โทร: {phone}")
        text_y += lh_norm

    return max(y + logo_h, text_y) - y


# ── Main print function ──────────────────────────────────────────────────────

def print_receipt(lines: list, cut: bool = True):
    pdc = win32ui.CreateDC()
    pdc.CreatePrinterDC(PRINTER_NAME)

    page_w   = pdc.GetDeviceCaps(win32con.HORZRES)
    lpy      = pdc.GetDeviceCaps(win32con.LOGPIXELSY)
    margin_x = max(4, int(page_w * MARGIN_X_PCT))
    usable_w = page_w - margin_x * 2

    logger.info("page_w=%d px  lpy=%d dpi  usable_w=%d px  font_normal=%dpt",
                page_w, lpy, usable_w, FONT_SIZE_NORMAL)

    try:
        pdc.StartDoc("Receipt")
        pdc.StartPage()

        y = _lh(lpy, FONT_SIZE_NORMAL) // 2

        for line in lines:
            line_type = line.get("type", "text")

            # ── Logo header (logo left + text right) ──
            if line_type == "logo_header":
                used_h = _render_logo_header(pdc, line, y, page_w, margin_x, lpy)
                y += used_h
                continue

            # ── ข้อความปกติ ──
            text       = line.get("text", "")
            right_text = line.get("right_text", "")
            align      = line.get("align", "left")
            double_h   = line.get("double_height", False)
            bold       = line.get("bold", False)
            small      = line.get("small", False)   # สำหรับ footer

            if small:
                size = FONT_SIZE_SMALL
            elif double_h:
                size = FONT_SIZE_LARGE
            else:
                size = FONT_SIZE_NORMAL

            font   = _make_font(pdc, size, bold)
            pdc.SelectObject(font)
            line_h = _lh(lpy, size)

            if right_text:
                lw, _ = pdc.GetTextExtent(text)
                rw, _ = pdc.GetTextExtent(right_text)
                if lw + rw <= usable_w:
                    pdc.TextOut(margin_x, y, text)
                    pdc.TextOut(page_w - rw - margin_x, y, right_text)
                else:
                    pdc.TextOut(margin_x, y, text)
                    y += line_h
                    pdc.TextOut(page_w - rw - margin_x, y, right_text)

            elif text:
                tw, _ = pdc.GetTextExtent(text)
                display = text
                while tw > usable_w and len(display) > 1:
                    display = display[:-1]
                    tw, _  = pdc.GetTextExtent(display + "…")
                if display != text:
                    display += "…"

                if align == "center":
                    tw2, _ = pdc.GetTextExtent(display)
                    x = max(margin_x, (page_w - tw2) // 2)
                elif align == "right":
                    tw2, _ = pdc.GetTextExtent(display)
                    x = max(margin_x, page_w - tw2 - margin_x)
                else:
                    x = margin_x

                pdc.TextOut(x, y, display)

            y += line_h

        pdc.EndPage()
        pdc.EndDoc()
        logger.info("GDI print OK → %s", PRINTER_NAME)

    except Exception as e:
        logger.error("GDI print FAILED: %s", e)
        raise
    finally:
        pdc.DeleteDC()