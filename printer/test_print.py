# -*- coding: utf-8 -*-
"""
test_print.py — ทดสอบ receipt format โดยไม่ต้องมีเครื่องพิมพ์
"""

from receipt_builder import (
    build_deposit_receipt,
    build_withdrawal_receipt,
    build_close_shift_receipt,
    build_eod_receipt,
    build_collect_cash_receipt,
)

COMPANY = {
    "company_name": "ปั๊ม พี พาวเวอร์",
    "branch_name":  "สาขาหลัก",
    "address":      "123 ถ.สุขุมวิท กรุงเทพฯ",
    "phone":        "02-xxx-xxxx",
}


def print_lines(lines):
    for line in lines:
        text = line.get("text", "")
        bold = line.get("bold", False)
        prefix = "**" if bold else "  "
        print(prefix + text)


if __name__ == "__main__":
    print("\n" + "="*60)
    print("TEST: DEPOSIT RECEIPT")
    print("="*60)
    data = {
        **COMPANY,
        "reference":    "TXN-1773617438540",
        "deposit_type": "oil",
        "staff_name":   "Attendant01",
        "datetime_str": "16/03/2026 14:30:25",
        "breakdown": {
            "notes": [
                {"qty": 2, "value": 2000},
                {"qty": 1, "value": 5000},
            ],
            "coins": [],
        },
        "total_satang": 9000,
    }
    print_lines(build_deposit_receipt(data))

    print("\n" + "="*60)
    print("TEST: CLOSE SHIFT RECEIPT")
    print("="*60)
    cs_data = {
        **COMPANY,
        "reference":         "SHIFT-2603161430",
        "shift_number":      1,
        "staff_name":        "Attendant01",
        "datetime_str":      "16/03/2026 14:30:25",
        "total_deposits":    90000,
        "total_withdrawals": 0,
        "shift_net_total":   90000,
        "pos_total":         90000,
        "recon_status":      "matched",
    }
    print_lines(build_close_shift_receipt(cs_data))

    print("\n" + "="*60)
    print("TEST: EOD RECEIPT")
    print("="*60)
    eod_data = {
        **COMPANY,
        "reference":         "EOD-2603161500",
        "datetime_str":      "16/03/2026 15:00:00",
        "shift_count":       3,
        "total_oil":         150000,
        "total_engine_oil":  50000,
        "total_coffee_shop": 20000,
        "total_convenient_store": 0,
        "total_rental":      0,
        "total_other":       0,
        "eod_grand_total":   220000,
        "collected_amount":  170000,
        "reserve_kept":      50000,
    }
    print_lines(build_eod_receipt(eod_data))