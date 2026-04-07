# -*- coding: utf-8 -*-
"""
printer.py — พิมพ์ผ่าน Windows GDI (เหมือน Notepad) รองรับภาษาไทย 100%

Install:
    pip install pywin32

ทดสอบ:
    python printer.py
"""

import logging
import win32print
import win32ui
import win32con

logger = logging.getLogger(__name__)

PRINTER_NAME   = "XP-80C"
PAPER_WIDTH_PX = 550   # ปรับตาม DPI จริงของ printer ถ้าต้องการ

# Font ภาษาไทยที่มีใน Windows (เรียงตามความนิยม)
THAI_FONT = "TH Sarabun New"   # ถ้าไม่มีจะ fallback เป็น Tahoma อัตโนมัติ

FONT_SIZE_NORMAL = 24   # หน่วย: point
FONT_SIZE_LARGE  = 36


def _make_font(dc, size, bold=False):
    """สร้าง GDI font object"""
    log_pixels_y = dc.GetDeviceCaps(win32con.LOGPIXELSY)
    height = -int(size * log_pixels_y / 72)   # convert point → logical unit
    return win32ui.CreateFont({
        "name":   THAI_FONT,
        "height": height,
        "weight": win32con.FW_BOLD if bold else win32con.FW_NORMAL,
        "charset": win32con.ANSI_CHARSET,   # ให้ Windows เลือก glyph เอง
    })


def print_receipt(lines: list, cut: bool = True):
    """
    lines: list of dict  {text, align, double_height, bold}
    cut: ไม่ใช้ใน GDI mode (driver จัดการเอง) — เก็บไว้เพื่อ interface เดิม
    """
    pdc = win32ui.CreateDC()
    pdc.CreatePrinterDC(PRINTER_NAME)

    page_width  = pdc.GetDeviceCaps(win32con.HORZRES)   # px จริงของ printer
    line_height_normal = int(FONT_SIZE_NORMAL * pdc.GetDeviceCaps(win32con.LOGPIXELSY) / 72 * 1.4)
    line_height_large  = int(FONT_SIZE_LARGE  * pdc.GetDeviceCaps(win32con.LOGPIXELSY) / 72 * 1.4)

    margin_x = int(page_width * 0.02)   # ~2% margin ซ้าย-ขวา
    margin_y = int(line_height_normal * 0.5)

    try:
        pdc.StartDoc("Receipt")
        pdc.StartPage()

        y = margin_y
        for line in lines:
            text     = line.get("text", "")
            align    = line.get("align", "left")
            double_h = line.get("double_height", False)
            bold     = line.get("bold", False)

            font = _make_font(pdc, FONT_SIZE_LARGE if double_h else FONT_SIZE_NORMAL, bold)
            pdc.SelectObject(font)

            lh = line_height_large if double_h else line_height_normal

            if text:
                tw, _ = pdc.GetTextExtent(text)

                if align == "center":
                    x = max(margin_x, (page_width - tw) // 2)
                elif align == "right":
                    x = max(margin_x, page_width - tw - margin_x)
                else:
                    x = margin_x

                pdc.TextOut(x, y, text)

            y += lh

        pdc.EndPage()
        pdc.EndDoc()
        logger.info("GDI print OK → %s", PRINTER_NAME)

    except Exception as e:
        logger.error("GDI print FAILED: %s", e)
        raise
    finally:
        pdc.DeleteDC()


# ---------------------------------------------------------------------------
# Quick self-test  (python printer.py)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    CHARS = 42
    test_lines = [
        {"text": "=== TEST PRINT ===",   "align": "center", "double_height": True},
        {"text": "",                      "align": "left"},
        {"text": "ทดสอบภาษาไทย",          "align": "center"},
        {"text": "กขคงจฉชซ",             "align": "center"},
        {"text": "1234567890",            "align": "center"},
        {"text": "Normal Left",           "align": "left"},
        {"text": "Right Align",           "align": "right"},
        {"text": "-" * CHARS,             "align": "left"},
        {"text": "สาขา: สมุทรสาคร",        "align": "left"},
        {"text": "รวม:       1,000.00",   "align": "right", "bold": True},
        {"text": "",                      "align": "left"},
        {"text": "** END OF TEST **",     "align": "center"},
    ]

    print_receipt(test_lines)
    print("Done — check printer output.")