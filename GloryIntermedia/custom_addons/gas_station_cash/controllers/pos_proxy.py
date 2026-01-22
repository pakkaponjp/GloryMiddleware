# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class GasStationPosProxy(http.Controller):

    @http.route("/gas_station_cash/pos/deposit", type="json", auth="user", methods=["POST"], csrf=False)
    def pos_deposit(self, **payload):
        """
        Request:
          {transaction_id, staff_id, amount}
        Response:
          POS response JSON
        """
        tx = payload.get("transaction_id")
        staff_id = payload.get("staff_id")
        amount = payload.get("amount")

        gateway = request.env["gas.station.pos.gateway"].sudo()
        resp = gateway.deposit(transaction_id=tx, staff_id=staff_id, amount=amount)

        _logger.debug("message: Sent deposit to POS: %s", { "transaction_id": tx, "staff_id": staff_id, "amount": amount })
        _logger.info("[POS] /pos/deposit tx=%s resp=%s", tx, resp)
        return resp
