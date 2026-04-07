# -*- coding: utf-8 -*-
"""
printer2.py — พิมพ์ผ่าน Windows GDI รองรับภาษาไทย + full-width 80mm
"""

import logging
import win32ui
import win32con

logger = logging.getLogger(__name__)

PRINTER_NAME     = "XP-80C"
THAI_FONT        = "TH Sarabun New"

FONT_SIZE_NORMAL = 10   # point  <- Normal Text
FONT_SIZE_LARGE  = 14   # point  <- Header Text (large)
LINE_SPACING     = 1.5
MARGIN_X_PCT     = 0.01  # 1% margin


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


def print_receipt(lines: list, cut: bool = True):
    pdc = win32ui.CreateDC()
    pdc.CreatePrinterDC(PRINTER_NAME)

    page_w   = pdc.GetDeviceCaps(win32con.HORZRES)
    lpy      = pdc.GetDeviceCaps(win32con.LOGPIXELSY)
    margin_x = max(4, int(page_w * MARGIN_X_PCT))
    usable_w = page_w - margin_x * 2

    # ★ debug — ดู log นี้เพื่อรู้ค่า page_w และ lpy จริงของ printer
    logger.info("page_w=%d px  lpy=%d dpi  usable_w=%d px  font_normal=%dpt",
                page_w, lpy, usable_w, FONT_SIZE_NORMAL)

    try:
        pdc.StartDoc("Receipt")
        pdc.StartPage()

        y = _lh(lpy, FONT_SIZE_NORMAL) // 2

        for line in lines:
            text       = line.get("text", "")
            right_text = line.get("right_text", "")
            align      = line.get("align", "left")
            double_h   = line.get("double_height", False)
            bold       = line.get("bold", False)

            size = FONT_SIZE_LARGE if double_h else FONT_SIZE_NORMAL
            font = _make_font(pdc, size, bold)
            pdc.SelectObject(font)
            line_h = _lh(lpy, size)

            if right_text:
                lw, _ = pdc.GetTextExtent(text)
                rw, _ = pdc.GetTextExtent(right_text)
                if lw + rw <= usable_w:
                    pdc.TextOut(margin_x, y, text)
                    pdc.TextOut(page_w - rw - margin_x, y, right_text)
                else:
                    # ชนกัน → left บรรทัดนี้, right บรรทัดถัดไปชิดขวา
                    pdc.TextOut(margin_x, y, text)
                    y += line_h
                    pdc.TextOut(page_w - rw - margin_x, y, right_text)

            elif text:
                tw, _ = pdc.GetTextExtent(text)
                display = text
                # ตัดถ้ายาวเกิน
                while tw > usable_w and len(display) > 1:
                    display = display[:-1]
                    tw, _ = pdc.GetTextExtent(display + "…")
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


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    W = 48
    test_lines = [
        {"text": "ปั๊มน้ำมัน ABC สาขาบางรัก", "align": "center", "double_height": True, "bold": True},
        {"text": "250 Executive Park Blvd, Suite 3400", "align": "center"},
        {"text": "โทร: +1 555-555-5556",               "align": "center"},
        {"text": "=" * W},
        {"text": "ประเภทรายการ: ยอดเงินฝาก",  "bold": True},
        {"text": "หมวด: น้ำมันเชื้อเพลิง"},
        {"text": "เลขที่: TXN-1775476500001"},
        {"text": "วันที่: 06/04/2569 18:55:06"},
        {"text": "พนักงาน: att01 abc"},
        {"text": "-" * W},
        {"text": "ชนิดเงิน", "bold": True},
        {"text": "  ฿20  x1",  "right_text": "20.00 บาท"},
        {"text": "  ฿50  x1",  "right_text": "50.00 บาท"},
        {"text": "-" * W},
        {"text": "รวม:",       "right_text": "70.00 บาท", "bold": True},
        {"text": "=" * W},
        {"text": ""},
        {"text": "ลายเซ็นพนักงาน", "bold": True},
        {"text": ""},
        {"text": ""},
        {"text": ""},
        {"text": ""},
        {"text": ""},
        {"text": ""},
        {"text": ""},
        {"text": "." * W},
        {"text": ""},
    ]
    print_receipt(test_lines)
    print("Done.")