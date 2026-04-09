# -*- coding: utf-8 -*-
"""
receipt_builder2.py — สร้าง receipt lines สำหรับแต่ละประเภทธุรกรรม

Layout changes (ตาม feedback ลูกค้า):
  - Header: logo ซ้าย + company info ขวา
  - ประเภทรายการ: center + bold
  - Field order: หมวด → วันที่ → พนักงาน → เลขที่
  - Footer: Powered by P Power Generating Co., Ltd.
"""

from datetime import datetime, timedelta
from printer2 import LOGO_PATH, LOGO_WIDTH_PX

RECEIPT_WIDTH = 48
LINE          = "-" * RECEIPT_WIDTH
DOUBLE_LINE   = "=" * RECEIPT_WIDTH

DEPOSIT_TYPE_LABEL = {
    "oil":              "น้ำมันเชื้อเพลิง",
    "engine_oil":       "น้ำมันเครื่อง",
    "coffee_shop":      "ร้านกาแฟ",
    "convenient_store": "ร้านสะดวกซื้อ",
    "rental":           "ค่าเช่า",
    "deposit_cash":     "เงินเติมตู้",
    "exchange_cash":    "แลกเงิน",
    "other":            "อื่นๆ",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_local():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M:%S")


def _baht(satang):
    return f"{satang / 100:,.2f}"


def _denom_label(fv_satang):
    baht = fv_satang / 100
    if baht == int(baht):
        return f"\u0e3f{int(baht):,}"
    return f"\u0e3f{baht:g}"


def _txt(text, align="left", bold=False, double_height=False, small=False):
    return {
        "text": text,
        "align": align,
        "bold": bold,
        "double_height": double_height,
        "small": small,
    }


def _lr(left, right, bold=False, double_height=False):
    """Left + Right บนบรรทัดเดียว"""
    return {
        "text":          left,
        "right_text":    right,
        "align":         "left",
        "bold":          bold,
        "double_height": double_height,
    }


def _signature_block(label="ลายเซ็นพนักงาน"):
    return [
        _txt(""),
        _txt(label),
        _txt(""),
        _txt(""),
        _txt(""),
        _txt("." * RECEIPT_WIDTH),
        _txt(""),
    ]


# ── Header (logo left + company right) ───────────────────────────────────────

def _header(company_name, branch_name="", address="", phone="", logo_path=None):
    """
    Header แบบ logo ซ้าย / company info ขวา
    ถ้าไม่มี logo_path ให้ใช้ LOGO_PATH default
    """
    lines = []
    lines.append({
        "type":          "logo_header",
        "logo_path":     logo_path or LOGO_PATH,
        "logo_width_px": LOGO_WIDTH_PX,
        "company_name":  company_name,
        "branch_name":   branch_name,
        "address":       address,
        "phone":         phone,
    })
    lines.append(_txt(DOUBLE_LINE))
    return lines


# ── Footer (P Power branding) ─────────────────────────────────────────────────

def _footer():
    return [
        _txt(LINE),
        _txt("Powered by P Power Generating Co., Ltd.", align="center", small=True),
        _txt("สำนักงาน : 034-440-280-1",               align="center", small=True),
        _txt("ฝ่ายขาย : 081-989-9847",                 align="center", small=True),
        _txt(""),
    ]


# ── Receipt builders ──────────────────────────────────────────────────────────

def build_deposit_receipt(data: dict) -> list:
    """
    ใบเสร็จ Cash Deposit (oil, engine_oil, coffee_shop, etc.)
    Field order: ประเภทรายการ → หมวด → วันที่ → พนักงาน → เลขที่
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    deposit_type = data.get("deposit_type", "")
    type_label   = DEPOSIT_TYPE_LABEL.get(deposit_type, deposit_type)

    # ── ประเภทรายการ (center + bold) ──
    lines.append(_txt("ยอดเงินฝาก", align="center", bold=True, double_height=True))
    lines.append(_txt(f"หมวด: {type_label}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))

    # ── Denomination breakdown ──
    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])

    if notes or coins:
        lines.append(_txt("ชนิดเงิน", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv, qty = n.get("value", 0), n.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv, qty = c.get("value", 0), c.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
    else:
        lines.append(_txt("(ไม่มีข้อมูลรายละเอียดธนบัตร)"))

    lines.append(_txt(LINE))
    lines.append(_lr("รวม:", f"{_baht(data.get('total_satang', 0))} บาท", bold=True))
    lines.append(_txt(DOUBLE_LINE))
    lines += _signature_block("ลายเซ็นพนักงาน")
    lines += _footer()
    return lines


def build_deposit_with_amount_receipt(data: dict) -> list:
    """
    ใบเสร็จ Deposit with Amount (coffee_shop, convenient_store ที่ไม่มี breakdown)
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    deposit_type = data.get("deposit_type", "")
    type_label   = DEPOSIT_TYPE_LABEL.get(deposit_type, deposit_type)

    lines.append(_txt("ยอดเงินฝาก", align="center", bold=True, double_height=True))
    lines.append(_txt(f"หมวด: {type_label}"))
    if data.get("product_name"):
        lines.append(_txt(f"สินค้า: {data['product_name']}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))
    lines.append(_lr("จำนวนเงิน:", f"{_baht(data.get('total_satang', 0))} บาท", bold=True))
    lines.append(_txt(DOUBLE_LINE))
    lines += _signature_block("ลายเซ็นพนักงาน")
    lines += _footer()
    return lines


def build_withdrawal_receipt(data: dict) -> list:
    """ใบเสร็จ Withdrawal"""
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("ถอนเงิน", align="center", bold=True, double_height=True))
    lines.append(_txt(f"หมวด: {data.get('withdrawal_type', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))

    # Denomination breakdown (ถ้ามี)
    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])
    if notes or coins:
        lines.append(_txt("ชนิดเงิน", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv, qty = n.get("value", 0), n.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv, qty = c.get("value", 0), c.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        lines.append(_txt(LINE))

    lines.append(_lr("จำนวนเงิน:", f"{_baht(data.get('total_satang', 0))} บาท", bold=True))
    if data.get("notes"):
        lines.append(_txt(f"หมายเหตุ: {data['notes']}"))
    lines.append(_txt(DOUBLE_LINE))
    lines += _signature_block("ลายเซ็นผู้รับ")
    lines += _footer()
    return lines


def build_replenish_receipt(data: dict) -> list:
    """ใบเสร็จ Replenish (เติมเงินสำรองทอน)"""
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("เติมเงินสำรองทอน", align="center", bold=True, double_height=True))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))

    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])
    if notes or coins:
        lines.append(_txt("ชนิดเงิน", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv, qty = n.get("value", 0), n.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv, qty = c.get("value", 0), c.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
    else:
        lines.append(_txt("(ไม่มีข้อมูลรายละเอียดธนบัตร)"))

    lines.append(_txt(LINE))
    lines.append(_lr("รวม:", f"{_baht(data.get('total_satang', 0))} บาท", bold=True))
    lines.append(_txt(DOUBLE_LINE))
    lines += _footer()
    return lines


def build_close_shift_receipt(data: dict) -> list:
    """ใบสรุปปิดกะ"""
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("สรุปการปิดกะ", align="center", bold=True, double_height=True))
    lines.append(_txt(f"กะที่: {data.get('shift_number', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))
    lines.append(_lr("ยอดฝากรวม:",  f"{_baht(data.get('total_deposits', 0))} บาท"))
    lines.append(_lr("ยอดถอนรวม:",  f"{_baht(data.get('total_withdrawals', 0))} บาท"))
    lines.append(_lr("ยอดสุทธิ:",   f"{_baht(data.get('shift_net_total', 0))} บาท", bold=True))
    lines.append(_txt(LINE))
    lines.append(_lr("ยอด POS:", f"{_baht(data.get('pos_total', 0))} บาท"))
    recon_map   = {"matched": "ตรง", "over": "เกิน", "short": "ขาด", "pending": "รอตรวจ"}
    recon_label = recon_map.get(data.get("recon_status", "pending"), "รอตรวจ")
    lines.append(_txt(f"สถานะ: {recon_label}"))
    lines.append(_txt(DOUBLE_LINE))
    lines += _signature_block("ลายเซ็นพนักงาน")
    lines += _footer()
    return lines


def build_eod_receipt(data: dict) -> list:
    """ใบสรุปประจำวัน"""
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("สรุปประจำวัน (End of Day)", align="center", bold=True, double_height=True))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"จำนวนกะ: {data.get('shift_count', 0)} กะ"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))
    lines.append(_txt("รายได้แยกตามประเภท", bold=True))

    categories = [
        ("total_oil",              "น้ำมันเชื้อเพลิง"),
        ("total_engine_oil",       "น้ำมันเครื่อง"),
        ("total_coffee_shop",      "ร้านกาแฟ"),
        ("total_convenient_store", "ร้านสะดวกซื้อ"),
        ("total_rental",           "ค่าเช่า"),
        ("total_other",            "อื่นๆ"),
    ]
    for key, label in categories:
        val = data.get(key, 0)
        if val:
            lines.append(_lr(f"  {label}:", f"{_baht(val)} บาท"))

    lines.append(_txt(LINE))
    lines.append(_lr("รวมทั้งวัน:",    f"{_baht(data.get('eod_grand_total', 0))} บาท", bold=True))
    lines.append(_txt(LINE))
    lines.append(_lr("เก็บเข้ากล่อง:", f"{_baht(data.get('collected_amount', 0))} บาท"))
    lines.append(_lr("เงินสำรองทอน:",  f"{_baht(data.get('reserve_kept', 0))} บาท"))
    lines.append(_txt(DOUBLE_LINE))
    lines += _footer()
    return lines


def build_collect_cash_receipt(data: dict) -> list:
    """ใบเสร็จ Collect Cash"""
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    collect_type = data.get("collect_type", "all")
    type_label   = "เก็บเงินทั้งหมด" if collect_type == "all" else "เก็บเงิน (เหลือเงินสำรอง)"

    lines.append(_txt(type_label, align="center", bold=True, double_height=True))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(LINE))

    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])
    if notes or coins:
        lines.append(_txt("ชนิดเงิน (ก่อนเก็บ)", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv, qty = n.get("value", 0), n.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv, qty = c.get("value", 0), c.get("qty", 0)
            lines.append(_lr(f"  {_denom_label(fv)} x{qty}", f"{_baht(fv * qty)} บาท"))
        lines.append(_txt(LINE))

    lines.append(_lr("ยอดเก็บ:", f"{_baht(data.get('collected_amount', 0))} บาท", bold=True))
    if data.get("reserve_kept"):
        lines.append(_lr("เงินสำรองทอน:", f"{_baht(data['reserve_kept'])} บาท"))
    lines.append(_txt(DOUBLE_LINE))
    lines += _signature_block("ลายเซ็นพนักงาน")
    lines += _footer()
    return lines