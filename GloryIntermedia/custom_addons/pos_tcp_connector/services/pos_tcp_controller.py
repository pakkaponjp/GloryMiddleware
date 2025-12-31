
import json
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class PosTcpConnectorController(http.Controller):

    # Small helper to send JSON nicely
    def _json_response(self, payload, status=200):
        return request.make_response(
            json.dumps(payload),
            status=status,
            headers=[("Content-Type", "application/json")],
        )

    def _ensure_middleware_ready_or_fail(self, staff_id=None):
        """
        Called from each incoming POS endpoint.
        If middleware is NOT ready -> returns HTTP response with FAILED.
        If ready -> returns None and caller continues normal logic.
        """
        ready = request.env["pos.connector.mixin"].sudo().is_middleware_ready()
        if not ready:
            msg = "Middleware is not ready."
            _logger.warning(
                "Incoming POS call blocked: middleware not ready (staff_id=%s)", staff_id
            )
            return self._json_response(
                {
                    "status": "FAILED",
                    "msg": msg,
                },
                status=503,
            )
        return None