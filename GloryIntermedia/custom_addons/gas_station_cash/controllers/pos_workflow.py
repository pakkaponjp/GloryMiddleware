import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class PosWorkflow(http.Controller):

    @http.route("/gas_station_cash/pos/deposit_success", type="json", auth="user", methods=["POST"], csrf=False)
    def deposit_success(self, **payload):
        """
        Called when POS returns OK.
        Here you can:
        - create an audit record
        - or mark a deposit record as 'pos_ok'
        For now: log + return ok.
        """
        _logger.info("[POS_WORKFLOW] SUCCESS payload=%s", payload)

        # TODO: create your audit record here
        # Example placeholder:
        # request.env["gas.station.cash.audit"].sudo().create({...})

        return {"status": "ok", "action": "audit_ready"}

    @http.route("/gas_station_cash/pos/deposit_enqueue", type="json", auth="user", methods=["POST"], csrf=False)
    def deposit_enqueue(self, **payload):
        """
        Called when POS fails (non-OK or exception).
        Here you should store a retry job in DB for a cron to resend.
        For now: log + return queued.
        """
        _logger.warning("[POS_WORKFLOW] ENQUEUE payload=%s", payload)

        # TODO: store retry job in your model/table
        # Example placeholder:
        # request.env["gas.station.pos.job"].sudo().create({
        #   "transaction_id": payload.get("transaction_id"),
        #   "payload_json": payload,
        #   "state": "pending",
        #   "attempts": 0,
        # })

        return {"status": "queued"}
