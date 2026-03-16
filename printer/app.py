# -*- coding: utf-8 -*-
"""
app.py — Flask Print Service สำหรับ Xprinter XP-T80Q (Windows)

Endpoints:
    POST /print/deposit          — ใบเสร็จ Cash Deposit
    POST /print/withdrawal       — ใบเสร็จ Cash Withdrawal
    POST /print/close_shift      — ใบสรุปปิดกะ
    POST /print/eod              — ใบสรุป End of Day
    POST /print/collect_cash     — ใบเสร็จ Collect Cash
    GET  /health                 — Health check
"""

import logging
from flask import Flask, request, jsonify
from printer import print_receipt
from receipt_builder import (
    build_deposit_receipt,
    build_withdrawal_receipt,
    build_close_shift_receipt,
    build_eod_receipt,
    build_collect_cash_receipt,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)


def _print_or_error(builder_fn, data):
    """Build receipt lines and print. Return JSON response."""
    try:
        lines = builder_fn(data)
        print_receipt(lines)
        logger.info("Printed: %s", data.get("reference", ""))
        return jsonify({"status": "OK", "message": "Printed successfully"}), 200
    except Exception as e:
        logger.error("Print error: %s", e)
        return jsonify({"status": "FAILED", "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "OK", "service": "print_service"}), 200


@app.route("/print/deposit", methods=["POST"])
def print_deposit():
    """
    Body (JSON):
        company_name, branch_name, address, phone
        reference, deposit_type, staff_name, datetime_str
        breakdown: {"notes": [{"qty":2,"value":2000},...], "coins":[...]}
        total_satang: int
    """
    data = request.get_json(force=True) or {}
    logger.info("Print deposit: ref=%s", data.get("reference"))
    return _print_or_error(build_deposit_receipt, data)


@app.route("/print/withdrawal", methods=["POST"])
def print_withdrawal():
    """
    Body (JSON):
        company_name, branch_name, address, phone
        reference, withdrawal_type, staff_name, datetime_str
        total_satang: int, notes: str
    """
    data = request.get_json(force=True) or {}
    logger.info("Print withdrawal: ref=%s", data.get("reference"))
    return _print_or_error(build_withdrawal_receipt, data)


@app.route("/print/close_shift", methods=["POST"])
def print_close_shift():
    """
    Body (JSON):
        company_name, branch_name, address, phone
        reference, shift_number, staff_name, datetime_str
        total_deposits, total_withdrawals, shift_net_total, pos_total (satang)
        recon_status: "matched"|"over"|"short"|"pending"
    """
    data = request.get_json(force=True) or {}
    logger.info("Print close_shift: ref=%s", data.get("reference"))
    return _print_or_error(build_close_shift_receipt, data)


@app.route("/print/eod", methods=["POST"])
def print_eod():
    """
    Body (JSON):
        company_name, branch_name, address, phone
        reference, datetime_str, shift_count
        total_oil, total_engine_oil, total_coffee_shop,
        total_convenient_store, total_rental, total_other (satang)
        eod_grand_total, collected_amount, reserve_kept (satang)
    """
    data = request.get_json(force=True) or {}
    logger.info("Print EOD: ref=%s", data.get("reference"))
    return _print_or_error(build_eod_receipt, data)


@app.route("/print/collect_cash", methods=["POST"])
def print_collect_cash():
    """
    Body (JSON):
        company_name, branch_name, address, phone
        reference, staff_name, datetime_str
        collect_type: "all"|"leave_float"
        collected_amount, reserve_kept (satang)
    """
    data = request.get_json(force=True) or {}
    logger.info("Print collect_cash: ref=%s", data.get("reference"))
    return _print_or_error(build_collect_cash_receipt, data)


if __name__ == "__main__":
    logger.info("Print Service starting on port 5006...")
    app.run(host="0.0.0.0", port=5006, debug=False)