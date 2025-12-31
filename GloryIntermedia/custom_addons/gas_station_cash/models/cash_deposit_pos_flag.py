# custom_addons/gas_station_cash/models/cash_deposit_pos_flag.py
# -*- coding: utf-8 -*-

from odoo import models, fields


class GasStationCashDeposit(models.Model):
    _inherit = "gas.station.cash.deposit"

    is_pos_related = fields.Boolean(
        string="Include in POS totals",
        help=(
            "If checked, this deposit will be included in POS shift / end-of-day "
            "cash totals sent to the POS."
        ),
        default=True,  # you can change default later if needed
    )