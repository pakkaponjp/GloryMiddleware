import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class PosHttpProxy(http.Controller):

    @http.route("/gas_station_cash/pos/deposit_http", type="json", auth="user", methods=["POST"], csrf=False)
    def pos_deposit_http(self, **payload):
        """
        Forward deposit request to Flask POS receiver: POST /Deposit
        Expected payload:
          {transaction_id, staff_id, amount}
        """
        ICP = request.env["ir.config_parameter"].sudo()
        base_url = (ICP.get_param("gas_station_cash.pos_http_base_url") or "http://127.0.0.1:9100").rstrip("/")
        url = f"{base_url}/Deposit"

        _logger.info("[POS_HTTP] -> %s payload=%s", url, payload)

        try:
            r = requests.post(url, json=payload, timeout=5)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _logger.exception("[POS_HTTP] error calling POS receiver")
            return {"status": "FAILED", "description": str(e), "echo": payload}

        _logger.info("[POS_HTTP] <- %s", data)
        return data
