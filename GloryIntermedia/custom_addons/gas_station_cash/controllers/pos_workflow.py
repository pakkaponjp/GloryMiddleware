# pos_workflow.py
import json
import logging
from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class GasStationPosWorkflow(http.Controller):

    def _find_staff_id(self, staff_external_id):
        if not staff_external_id:
            return False
        staff = request.env["gas.station.staff"].sudo().search(
            [("external_id", "=", staff_external_id)], limit=1
        )
        return staff.id or False

    def _safe_dict(self, value):
        """Ensure pos_response is a dict (JS may send dict, but be defensive)."""
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return {"raw": value}
        return {"raw": str(value)}

    def _create_deposit_audit(
        self, *,
        tx_id,
        staff_external_id,
        amount,
        deposit_type,
        product_id,
        is_pos_related,
        pos_status,
        pos_resp=None,
        reason=None
    ):
        staff_id = self._find_staff_id(staff_external_id)
        if not staff_id:
            raise ValueError(f"Staff not found for external_id={staff_external_id}")

        pos_resp = self._safe_dict(pos_resp)
        amount = float(amount or 0.0)

        vals = {
            "name": tx_id or "/",
            "staff_id": staff_id,

            # Your model uses fields.Date; this will store date-only (OK for now)
            "date": fields.Date.today(),

            # ✅ store audit amount even when no lines exist
            "manual_total_amount": amount,

            "deposit_type": deposit_type,
            "product_id": product_id or False,

            "is_pos_related": bool(is_pos_related),
            "pos_transaction_id": tx_id,

            # ✅ 'na' | 'ok' | 'queued' | 'failed'
            "pos_status": pos_status,

            "pos_description": pos_resp.get("description") or pos_resp.get("discription"),
            "pos_time_stamp": pos_resp.get("time_stamp"),
            "pos_response_json": json.dumps(pos_resp, ensure_ascii=False),
            "pos_error": reason,

            # You currently set confirmed directly in your original code
            "state": "confirmed",
        }

        dep = request.env["gas.station.cash.deposit"].sudo().create(vals)
        _logger.info("[AUDIT] created deposit id=%s tx=%s pos_status=%s", dep.id, tx_id, pos_status)
        return dep.id

    @http.route("/gas_station_cash/pos/deposit_success", type="json", auth="user", methods=["POST"], csrf=False)
    def deposit_success(self, **payload):
        _logger.info("[POS_WORKFLOW] SUCCESS payload=%s", payload)

        dep_id = self._create_deposit_audit(
            tx_id=payload.get("transaction_id"),
            staff_external_id=payload.get("staff_id"),
            amount=payload.get("amount"),
            deposit_type=payload.get("deposit_type") or "oil",
            product_id=payload.get("product_id"),
            is_pos_related=True,
            pos_status="ok",
            pos_resp=payload.get("pos_response") or {},
            reason=None,
        )
        return {"status": "ok", "deposit_id": dep_id}

    @http.route("/gas_station_cash/pos/deposit_enqueue", type="json", auth="user", methods=["POST"], csrf=False)
    def deposit_enqueue(self, **payload):
        _logger.info("[POS_WORKFLOW] ENQUEUE payload=%s", payload)

        dep_id = self._create_deposit_audit(
            tx_id=payload.get("transaction_id"),
            staff_external_id=payload.get("staff_id"),
            amount=payload.get("amount"),
            deposit_type=payload.get("deposit_type") or "oil",
            product_id=payload.get("product_id"),
            is_pos_related=True,
            pos_status="queued",
            pos_resp=payload.get("pos_response") or {},
            reason=payload.get("reason") or "Queued for retry",
        )
        return {"status": "ok", "deposit_id": dep_id}

    # Optional but very useful: record audits for NON-POS products
    # (so Engine Oil non-POS products show only in Cash Deposit menu, not POS Deposit menu)
    @http.route("/gas_station_cash/cash/deposit_record", type="json", auth="user", methods=["POST"], csrf=False)
    def cash_deposit_record(self, **payload):
        _logger.info("[CASH_WORKFLOW] RECORD payload=%s", payload)

        dep_id = self._create_deposit_audit(
            tx_id=payload.get("transaction_id"),
            staff_external_id=payload.get("staff_id"),
            amount=payload.get("amount"),
            deposit_type=payload.get("deposit_type") or "engine_oil",
            product_id=payload.get("product_id"),
            is_pos_related=False,
            pos_status="na",
            pos_resp={},
            reason=payload.get("reason"),
        )
        return {"status": "ok", "deposit_id": dep_id}
