# -*- coding: utf-8 -*-

import json
import logging

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class GasStationDepositWorkflow(http.Controller):
    """Single, clean workflow endpoint for deposits.

    JS calls this once after FCC cash-in END OK.

    Backend responsibilities:
      1) Create the deposit (audit) record
      2) If POS-related: attempt to send to POS over TCP
         - On success: mark pos_status=ok and store response
         - On failure: create a retry job and mark pos_status=queued

    This keeps the frontend simple and avoids multiple endpoints / race conditions.
    """

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
        """Finalize a deposit and optionally send to POS.

        Expected payload (JS JSON-RPC params):
          - transaction_id: str (optional)
          - staff_id: str (external id)
          - amount: number
          - deposit_type: 'oil'|'engine_oil'|...
          - product_id: int|None
          - is_pos_related: bool

        Returns:
          {status:'ok', deposit_id:int, pos_status:'na|ok|queued|failed'}
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

        # Create the deposit audit record FIRST (we always audit).
        # Use a single-line deposit_line to preserve total_amount computation.
        deposit = Deposit.create(
            {
                "name": tx_id,
                "staff_id": staff_id,
                "date": fields.Datetime.now(),
                "deposit_type": deposit_type,
                "product_id": product_id,
                "is_pos_related": is_pos_related,
                "pos_transaction_id": tx_id if is_pos_related else False,
                "pos_status": "na" if not is_pos_related else "queued",  # will be corrected below
                "deposit_line_ids": [
                    (0, 0, {"currency_denomination": amount, "quantity": 1}),
                ],
                "state": "confirmed",
            }
        )

        _logger.info(
            "[DEPOSIT_WORKFLOW] created deposit id=%s tx=%s type=%s pos_related=%s amount=%s",
            deposit.id,
            tx_id,
            deposit_type,
            is_pos_related,
            amount,
        )

        if not is_pos_related:
            # Nothing to send to POS.
            return {"status": "ok", "deposit_id": deposit.id, "pos_status": deposit.pos_status}

        # ----------------------- POS SEND (TCP) -----------------------
        # Payload matches your POS spec (TCP JSON line).
        pos_payload = {
            "action": "Deposit",
            "transaction_id": tx_id,
            "staff_id": staff_external_id,
            "amount": amount,
            "deposit_type": deposit_type,
            "product_id": product_id or None,
        }

        try:
            pos_resp = deposit.send_to_pos_tcp(pos_payload)
            pos_status = str(pos_resp.get("status") or "").upper()
            ok = pos_status == "OK"

            if ok:
                deposit.write(
                    {
                        "pos_status": "ok",
                        "pos_description": pos_resp.get("description") or pos_resp.get("discription"),
                        "pos_time_stamp": pos_resp.get("time_stamp"),
                        "pos_response_json": json.dumps(pos_resp, ensure_ascii=False),
                        "pos_error": False,
                    }
                )
                _logger.info("[DEPOSIT_WORKFLOW] POS OK deposit_id=%s tx=%s", deposit.id, tx_id)
                return {"status": "ok", "deposit_id": deposit.id, "pos_status": "ok"}

            # POS responded but not OK -> queue a retry job
            reason = pos_resp.get("description") or pos_resp.get("discription") or "POS returned non-OK"
            deposit.create_pos_job(pos_payload, error=reason)
            deposit.write(
                {
                    "pos_status": "queued",
                    "pos_description": pos_resp.get("description") or pos_resp.get("discription"),
                    "pos_time_stamp": pos_resp.get("time_stamp"),
                    "pos_response_json": json.dumps(pos_resp, ensure_ascii=False),
                    "pos_error": reason,
                }
            )
            _logger.warning(
                "[DEPOSIT_WORKFLOW] POS NOT OK -> queued deposit_id=%s tx=%s reason=%s",
                deposit.id,
                tx_id,
                reason,
            )
            return {"status": "ok", "deposit_id": deposit.id, "pos_status": "queued"}

        except Exception as e:
            # Network/timeout/etc -> queue job
            reason = str(e)
            deposit.create_pos_job(pos_payload, error=reason)
            deposit.write({"pos_status": "queued", "pos_error": reason})
            _logger.exception(
                "[DEPOSIT_WORKFLOW] POS ERROR -> queued deposit_id=%s tx=%s", deposit.id, tx_id
            )
            return {"status": "ok", "deposit_id": deposit.id, "pos_status": "queued", "warning": reason}
