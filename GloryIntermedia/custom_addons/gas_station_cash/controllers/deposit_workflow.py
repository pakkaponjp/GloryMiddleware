# -*- coding: utf-8 -*-
import logging
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class GasStationDepositWorkflow(http.Controller):

    def _find_staff_id(self, staff_external_id):
        if not staff_external_id:
            return False
        staff = request.env["gas.station.staff"].sudo().search(
            [("external_id", "=", staff_external_id)], limit=1
        )
        return staff.id or False

    @http.route(
        "/gas_station_cash/deposit/finalize",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def finalize(self, **payload):
        """
        Audit-only finalize (no POS yet)

        params:
          - transaction_id (optional)
          - staff_id (external_id)
          - amount
          - deposit_type
          - product_id
          - is_pos_related (bool)
        """
        tx_id = payload.get("transaction_id") or f"TXN-{int(fields.Datetime.now().timestamp()*1000)}"
        staff_external_id = payload.get("staff_id")
        amount = float(payload.get("amount") or 0.0)
        deposit_type = payload.get("deposit_type") or "oil"
        product_id = payload.get("product_id") or False
        is_pos_related = bool(payload.get("is_pos_related"))

        staff_id = self._find_staff_id(staff_external_id)
        if not staff_id:
            return {
                "status": "error",
                "code": "STAFF_NOT_FOUND",
                "message": f"Staff not found for external_id={staff_external_id}",
            }

        Deposit = request.env["gas.station.cash.deposit"].sudo()

        # Important: create 1 line so total_amount != 0 (because total_amount is computed from lines)
        deposit = Deposit.create({
            "name": tx_id,
            "staff_id": staff_id,
            "date": fields.Datetime.now(),
            "deposit_type": deposit_type,
            "product_id": product_id,
            "is_pos_related": is_pos_related,
            "pos_transaction_id": tx_id if is_pos_related else False,
            "pos_status": "na",
            "deposit_line_ids": [(0, 0, {"currency_denomination": amount, "quantity": 1})],
            "state": "confirmed",
        })

        _logger.info(
            "[DEPOSIT_FINALIZE] created deposit id=%s tx=%s type=%s pos_related=%s amount=%s",
            deposit.id, tx_id, deposit_type, is_pos_related, amount,
        )

        return {"status": "ok", "deposit_id": deposit.id}
