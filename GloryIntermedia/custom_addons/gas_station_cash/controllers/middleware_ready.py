# custom_addons/gas_station_cash/controllers/middleware_ready.py
# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home

_logger = logging.getLogger(__name__)


class GasStationCashHome(Home):
    """
    Extend the standard /web/login route to mark the middleware as READY
    whenever an Odoo user logs in successfully via the frontend.
    """

    @http.route()
    def web_login(self, redirect=None, **kw):
        # Call the normal Odoo login behaviour
        response = super().web_login(redirect=redirect, **kw)

        # If login succeeded, Odoo session has a uid
        if request.session.uid:
            cfg = request.env["ir.config_parameter"].sudo()
            cfg.set_param("gas_station_cash.mw_ready", "true")
            _logger.info(
                "GasStationCash: middleware marked READY on login (uid=%s)",
                request.session.uid,
            )

        return response