# -*- coding: utf-8 -*-
"""
receipt_builder.py — สร้าง receipt lines สำหรับแต่ละประเภทธุรกรรม
"""

from datetime import datetime, timedelta

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


def _now_local():
    """UTC+7 datetime string."""
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M:%S")


def _baht(satang):
    """satang → formatted baht string."""
    return f"{satang / 100:,.2f}"


def _denom_label(fv_satang):
    """2000 → '฿20', 100000 → '฿1,000'"""
    baht = int(fv_satang / 100)
    return f"\u0e3f{baht:,}"


def _lr(left, right, width=RECEIPT_WIDTH):
    """Left-right aligned string."""
    space = max(1, width - len(left) - len(right))
    return left + " " * space + right


def _txt(text, align="left", bold=False, double_height=False):
    return {"text": text, "align": align, "bold": bold, "double_height": double_height}


def _header(company_name, branch_name, address, phone):
    """Common header for all receipts."""
    lines = []
    lines.append(_txt(company_name, align="center", bold=True, double_height=True))
    if branch_name:
        lines.append(_txt(branch_name, align="center"))
    if address:
        lines.append(_txt(address, align="center"))
    if phone:
        lines.append(_txt(f"โทร: {phone}", align="center"))
    lines.append(_txt(DOUBLE_LINE))
    return lines


def build_deposit_receipt(data: dict) -> list:
    """
    สร้าง receipt สำหรับ Cash Deposit

    data keys:
        company_name, branch_name, address, phone
        transaction_type: "deposit"
        reference: "TXN-xxx"
        deposit_type: "oil" | "engine_oil" | ...
        staff_name: str
        datetime_str: str (optional, ถ้าไม่ส่งมาใช้ตอนนี้)
        breakdown: {"notes": [{"qty":2,"value":2000},...], "coins": [...]}
        total_satang: int
    """
    lines = []

    # Header
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    # Transaction info
    deposit_type = data.get("deposit_type", "")
    type_label = DEPOSIT_TYPE_LABEL.get(deposit_type, deposit_type)
    lines.append(_txt("ประเภทรายการ: ยอดเงินฝาก", bold=True))
    lines.append(_txt(f"หมวด: {type_label}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(LINE))

    # Denomination breakdown
    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])

    has_breakdown = notes or coins
    if has_breakdown:
        lines.append(_txt("ชนิดเงิน", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv = n.get("value", 0)
            qty = n.get("qty", 0)
            total = fv * qty
            label = _denom_label(fv)
            left  = f"  {label:<10} x{qty}"
            right = f"{_baht(total)} บาท"
            lines.append(_txt(_lr(left, right)))

        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv = c.get("value", 0)
            qty = c.get("qty", 0)
            total = fv * qty
            label = _denom_label(fv)
            left  = f"  {label:<10} x{qty}"
            right = f"{_baht(total)} บาท"
            lines.append(_txt(_lr(left, right)))
    else:
        lines.append(_txt("(ไม่มีข้อมูลรายละเอียดธนบัตร)"))

    lines.append(_txt(LINE))

    # Total
    total_satang = data.get("total_satang", 0)
    lines.append(_txt(_lr("รวม:", f"{_baht(total_satang)} บาท"), bold=True))
    lines.append(_txt(DOUBLE_LINE))

    # Signature
    lines.append(_txt(""))
    lines.append(_txt("ลายเซ็นพนักงาน"))
    lines.append(_txt(""))
    lines.append(_txt("." * RECEIPT_WIDTH))
    lines.append(_txt(""))

    return lines


def build_withdrawal_receipt(data: dict) -> list:
    """
    สร้าง receipt สำหรับ Cash Withdrawal

    data keys:
        company_name, branch_name, address, phone
        reference, staff_name, datetime_str
        withdrawal_type: str
        total_satang: int
        notes: str (optional remark)
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("ประเภทรายการ: ถอนเงิน", bold=True))
    lines.append(_txt(f"หมวด: {data.get('withdrawal_type', '')}"))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(LINE))
    lines.append(_txt(_lr("จำนวนเงิน:", f"{_baht(data.get('total_satang', 0))} บาท"), bold=True))
    if data.get("notes"):
        lines.append(_txt(f"หมายเหตุ: {data['notes']}"))
    lines.append(_txt(DOUBLE_LINE))
    lines.append(_txt(""))
    lines.append(_txt("ลายเซ็นผู้รับ"))
    lines.append(_txt(""))
    lines.append(_txt("." * RECEIPT_WIDTH))
    lines.append(_txt(""))
    return lines


def build_close_shift_receipt(data: dict) -> list:
    """
    สร้าง receipt สำหรับ Close Shift

    data keys:
        company_name, branch_name, address, phone
        reference, staff_name, shift_number, datetime_str
        total_deposits, total_withdrawals, shift_net_total (satang)
        pos_total (satang)
        recon_status: "matched"|"over"|"short"|"pending"
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("สรุปการปิดกะ", align="center", bold=True))
    lines.append(_txt(LINE))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(f"กะที่: {data.get('shift_number', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(LINE))
    lines.append(_txt(_lr("ยอดฝากรวม:", f"{_baht(data.get('total_deposits', 0))} บาท")))
    lines.append(_txt(_lr("ยอดถอนรวม:", f"{_baht(data.get('total_withdrawals', 0))} บาท")))
    lines.append(_txt(_lr("ยอดสุทธิ:", f"{_baht(data.get('shift_net_total', 0))} บาท"), bold=True))
    lines.append(_txt(LINE))
    lines.append(_txt(_lr("ยอด POS:", f"{_baht(data.get('pos_total', 0))} บาท")))

    recon_map = {
        "matched": "ตรง",
        "over":    "เกิน",
        "short":   "ขาด",
        "pending": "รอตรวจ",
    }
    recon_label = recon_map.get(data.get("recon_status", "pending"), "รอตรวจ")
    lines.append(_txt(f"สถานะ: {recon_label}"))
    lines.append(_txt(DOUBLE_LINE))
    lines.append(_txt(""))
    lines.append(_txt("ลายเซ็นพนักงาน"))
    lines.append(_txt(""))
    lines.append(_txt("." * RECEIPT_WIDTH))
    lines.append(_txt(""))
    return lines


def build_eod_receipt(data: dict) -> list:
    """
    สร้าง receipt สำหรับ End of Day

    data keys:
        company_name, branch_name, address, phone
        reference, datetime_str
        shift_count
        total_oil, total_engine_oil, total_coffee_shop,
        total_convenient_store, total_rental, total_other (satang)
        eod_grand_total (satang)
        collected_amount, reserve_kept (satang)
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    lines.append(_txt("สรุปประจำวัน (End of Day)", align="center", bold=True))
    lines.append(_txt(LINE))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"จำนวนกะ: {data.get('shift_count', 0)} กะ"))
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
            lines.append(_txt(_lr(f"  {label}:", f"{_baht(val)} บาท")))

    lines.append(_txt(LINE))
    lines.append(_txt(_lr("รวมทั้งวัน:", f"{_baht(data.get('eod_grand_total', 0))} บาท"), bold=True))
    lines.append(_txt(LINE))
    lines.append(_txt(_lr("เก็บเข้ากล่อง:", f"{_baht(data.get('collected_amount', 0))} บาท")))
    lines.append(_txt(_lr("เงินสำรองทอน:", f"{_baht(data.get('reserve_kept', 0))} บาท")))
    lines.append(_txt(DOUBLE_LINE))
    lines.append(_txt(""))
    return lines


def build_collect_cash_receipt(data: dict) -> list:
    """
    สร้าง receipt สำหรับ Collect Cash (manual จาก Machine Control)

    data keys:
        company_name, branch_name, address, phone
        reference, staff_name, datetime_str
        collect_type: "all"|"leave_float"
        collected_amount (satang)
        reserve_kept (satang, optional)
    """
    lines = []
    lines += _header(
        data.get("company_name", "ปั๊มน้ำมัน"),
        data.get("branch_name", ""),
        data.get("address", ""),
        data.get("phone", ""),
    )

    collect_type = data.get("collect_type", "all")
    type_label = "เก็บเงินทั้งหมด" if collect_type == "all" else "เก็บเงิน (เหลือเงินสำรอง)"

    lines.append(_txt(f"ประเภทรายการ: {type_label}", bold=True))
    lines.append(_txt(f"เลขที่: {data.get('reference', '')}"))
    lines.append(_txt(f"วันที่: {data.get('datetime_str') or _now_local()}"))
    lines.append(_txt(f"พนักงาน: {data.get('staff_name', '')}"))
    lines.append(_txt(LINE))

    # Denomination breakdown
    breakdown = data.get("breakdown", {})
    notes = breakdown.get("notes", [])
    coins = breakdown.get("coins", [])
    if notes or coins:
        lines.append(_txt("ชนิดเงิน (ก่อนเก็บ)", bold=True))
        for n in sorted(notes, key=lambda x: x.get("value", 0)):
            fv  = n.get("value", 0)
            qty = n.get("qty", 0)
            lines.append(_txt(_lr(f"  THB{int(fv/100):,}  x{qty}", f"{_baht(fv*qty)} บาท")))
        for c in sorted(coins, key=lambda x: x.get("value", 0)):
            fv  = c.get("value", 0)
            qty = c.get("qty", 0)
            lines.append(_txt(_lr(f"  THB{int(fv/100):,}  x{qty}", f"{_baht(fv*qty)} บาท")))
        lines.append(_txt(LINE))

    lines.append(_txt(_lr("ยอดเก็บ:", f"{_baht(data.get('collected_amount', 0))} บาท"), bold=True))
    if data.get("reserve_kept"):
        lines.append(_txt(_lr("เงินสำรองทอน:", f"{_baht(data['reserve_kept'])} บาท")))
    lines.append(_txt(DOUBLE_LINE))
    lines.append(_txt(""))
    lines.append(_txt("ลายเซ็นพนักงาน"))
    lines.append(_txt(""))
    lines.append(_txt("." * RECEIPT_WIDTH))
    lines.append(_txt(""))
    return lines