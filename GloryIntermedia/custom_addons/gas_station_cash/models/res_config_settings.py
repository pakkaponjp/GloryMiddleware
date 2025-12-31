from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    gas_pos_vendor = fields.Selection(
        [
            ("firstpro", "FirstPro"),
            ("flowco", "FlowCo"),
        ],
        string="POS Vendor",
        config_parameter="gas_station_cash.pos_vendor",
    )

    gas_collect_on_close_shift = fields.Boolean(
        string="Collect on Close Shift",
        config_parameter="gas_station_cash.collect_on_close_shift",
    )

    gas_float_amount = fields.Monetary(
        string="Float Amount",
        currency_field="company_currency_id",
        config_parameter="gas_station_cash.float_amount",
    )

    company_currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        readonly=True,
    )
