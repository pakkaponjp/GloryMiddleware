# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class CashExchangeController(http.Controller):

    @http.route("/gas_station_cash/exchange/save", type="json", auth="user", methods=["POST"], csrf=False)
    def save_exchange(self, **kwargs):
        """
        Save exchange audit record.
        JS payload:
          staff_external_id : str
          cashin_amount     : float  (THB)
          cashout_amount    : float  (THB)
          cashin_breakdown  : {notes:[{value,qty}], coins:[{value,qty}]}
          cashout_breakdown : {notes:[{value,qty}], coins:[{value,qty}]}
          machine_status    : 'ok' | 'failed'
          machine_response  : dict
          notes             : str (optional)
        """
        try:
            result = request.env["gas.station.cash.exchange"].sudo().save_exchange(kwargs)
            _logger.info(
                "[ExchangeAudit] Saved: id=%s ref=%s staff=%s in=%.2f out=%.2f",
                result.get("exchange_id"),
                result.get("name"),
                kwargs.get("staff_external_id"),
                kwargs.get("cashin_amount", 0),
                kwargs.get("cashout_amount", 0),
            )
            return result
        except Exception as e:
            _logger.exception("[ExchangeAudit] Failed to save exchange audit")
            return {"status": "error", "message": str(e)}