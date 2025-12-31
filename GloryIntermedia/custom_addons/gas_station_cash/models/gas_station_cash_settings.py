# custom_addons/gas_station_cash/models/gas_station_cash_settings.py
# -*- coding: utf-8 -*-

from odoo import models, fields


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # Which POS vendor is used (FirstPro / FlowCo)
    gas_pos_vendor = fields.Selection(
        [
            ("firstpro", "FirstPro"),
            ("flowco", "FlowCo"),
        ],
        string="POS Vendor",
        config_parameter="gas_station_cash.pos_vendor",
        help="Default POS vendor used by the middleware TCP JSON connector.",
    )

    # Whether we should collect cash (move to collection box) on Close Shift
    gas_collect_on_close_shift = fields.Boolean(
        string="Collect Cash on Close Shift",
        config_parameter="gas_station_cash.collect_on_close_shift",
        help="If enabled, the middleware will perform a cash collection "
             "on Close Shift and leave only the float for change.",
    )

    # Float amount to leave in the machine after collection
    gas_float_amount = fields.Float(
        string="Float Amount to Leave",
        config_parameter="gas_station_cash.float_amount",
        help="Float amount that should remain in the cash recycler "
             "after a Close Shift collection.",
    )
