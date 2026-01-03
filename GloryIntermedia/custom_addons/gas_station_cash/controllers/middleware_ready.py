# controllers/middleware_ready.py
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class GasStationMiddlewareReady(http.Controller):

    @http.route("/gas_station_cash/middleware/ready", type="json", auth="user", methods=["POST"], csrf=False)
    def middleware_ready(self, **kw):
        _logger.info("[MIDDLEWARE] ready called %s", kw)
        return {"status": "ok"}

    @http.route("/gas_station_cash/middleware/not_ready", type="json", auth="user", methods=["POST"], csrf=False)
    def middleware_not_ready(self, **kw):
        _logger.info("[MIDDLEWARE] not_ready called %s", kw)
        return {"status": "ok"}
