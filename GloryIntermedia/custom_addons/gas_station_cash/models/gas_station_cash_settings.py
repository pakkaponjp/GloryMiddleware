# -*- coding: utf-8 -*-
"""
File: models/res_config_settings.py
Description: Configuration settings for Gas Station Cash module
"""

from odoo import api, fields, models


# Thai Baht denominations: (field_suffix, face_value_satang, label)
FLOAT_DENOMS = [
    # Notes
    ('note_1000', 100000, '฿1,000'),
    ('note_500',   50000, '฿500'),
    ('note_100',   10000, '฿100'),
    ('note_50',     5000, '฿50'),
    ('note_20',     2000, '฿20'),
    # Coins
    ('coin_10',     1000, '฿10'),
    ('coin_5',       500, '฿5'),
    ('coin_2',       200, '฿2'),
    ('coin_1',       100, '฿1'),
    ('coin_050',      50, '฿0.50'),
    ('coin_025',      25, '฿0.25'),
]


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # =========================================================================
    # POS INTEGRATION SETTINGS
    # =========================================================================

    gas_pos_vendor = fields.Selection(
        selection=[
            ('firstpro', 'FirstPro'),
            ('flowco',   'FlowCo'),
        ],
        string="POS Vendor",
        config_parameter='gas_station_cash.pos_vendor',
        help="Select which external POS vendor the middleware talks to (FirstPro or FlowCo)"
    )

    @api.model
    def get_values(self):
        """Sanitize legacy 'local' value that may still be stored in DB."""
        res = super().get_values()
        if res.get('gas_pos_vendor') == 'local':
            res['gas_pos_vendor'] = False
        return res

    @api.constrains('gas_pos_vendor')
    def _check_pos_vendor(self):
        for rec in self:
            if not rec.gas_pos_vendor:
                raise ValidationError("POS Vendor is required. Please select FirstPro or FlowCo.")

    # =========================================================================
    # COLLECTION SETTINGS
    # =========================================================================

    gas_collect_on_close_shift = fields.Boolean(
        string="Collect on Close Shift",
        default=False,
        config_parameter='gas_station_cash.collect_on_close_shift',
        help="If enabled, the middleware will collect cash into the collection box when the POS calls CloseShift"
    )

    gas_leave_float = fields.Boolean(
        string="Leave Float",
        default=False,
        config_parameter='gas_station_cash.leave_float',
        help="If enabled, the machine will keep the configured float denomination in the machine after collection"
    )

    gas_collect_on_end_of_day = fields.Boolean(
        string="Collect on End-of-Day",
        default=False,
        config_parameter='gas_station_cash.collect_on_end_of_day',
        help="If enabled, the middleware will collect cash at End-of-Day. Auto-enabled when Collect on Close Shift is on."
    )

    # --- Denomination quantities for float ---
    gas_float_note_1000 = fields.Integer(string="฿1,000 Notes", default=0,
        config_parameter='gas_station_cash.float_note_1000')
    gas_float_note_500  = fields.Integer(string="฿500 Notes",   default=0,
        config_parameter='gas_station_cash.float_note_500')
    gas_float_note_100  = fields.Integer(string="฿100 Notes",   default=0,
        config_parameter='gas_station_cash.float_note_100')
    gas_float_note_50   = fields.Integer(string="฿50 Notes",    default=0,
        config_parameter='gas_station_cash.float_note_50')
    gas_float_note_20   = fields.Integer(string="฿20 Notes",    default=0,
        config_parameter='gas_station_cash.float_note_20')
    gas_float_coin_10   = fields.Integer(string="฿10 Coins",    default=0,
        config_parameter='gas_station_cash.float_coin_10')
    gas_float_coin_5    = fields.Integer(string="฿5 Coins",     default=0,
        config_parameter='gas_station_cash.float_coin_5')
    gas_float_coin_2    = fields.Integer(string="฿2 Coins",     default=0,
        config_parameter='gas_station_cash.float_coin_2')
    gas_float_coin_1    = fields.Integer(string="฿1 Coins",     default=0,
        config_parameter='gas_station_cash.float_coin_1')
    gas_float_coin_050  = fields.Integer(string="฿0.50 Coins",  default=0,
        config_parameter='gas_station_cash.float_coin_050')
    gas_float_coin_025  = fields.Integer(string="฿0.25 Coins",  default=0,
        config_parameter='gas_station_cash.float_coin_025')

    # Float Amount — read-only, auto-calculated from denominations above
    gas_float_amount = fields.Float(
        string="Float Amount",
        default=0.0,
        config_parameter='gas_station_cash.float_amount',
        help="Total float amount calculated from denomination quantities (read-only)"
    )

    # =========================================================================
    # COMPUTE FLOAT AMOUNT ON CHANGE
    # =========================================================================

    def _compute_float_amount(self):
        """Recalculate gas_float_amount from denomination qty fields."""
        for rec in self:
            total_satang = (
                rec.gas_float_note_1000 * 100000 +
                rec.gas_float_note_500  *  50000 +
                rec.gas_float_note_100  *  10000 +
                rec.gas_float_note_50   *   5000 +
                rec.gas_float_note_20   *   2000 +
                rec.gas_float_coin_10   *   1000 +
                rec.gas_float_coin_5    *    500 +
                rec.gas_float_coin_2    *    200 +
                rec.gas_float_coin_1    *    100 +
                rec.gas_float_coin_050  *     50 +
                rec.gas_float_coin_025  *     25
            )
            rec.gas_float_amount = total_satang / 100.0

    @api.onchange('gas_collect_on_close_shift')
    def _onchange_collect_close_shift(self):
        """Auto-enable End-of-Day when Close Shift is turned on."""
        if self.gas_collect_on_close_shift:
            self.gas_collect_on_end_of_day = True

    @api.onchange(
        'gas_float_note_1000', 'gas_float_note_500', 'gas_float_note_100',
        'gas_float_note_50',   'gas_float_note_20',
        'gas_float_coin_10',   'gas_float_coin_5',   'gas_float_coin_2',
        'gas_float_coin_1',    'gas_float_coin_050',  'gas_float_coin_025',
    )
    def _onchange_float_denominations(self):
        self._compute_float_amount()

    # =========================================================================
    # GLORY API SETTINGS
    # =========================================================================

    gas_glory_api_url = fields.Char(
        string="Glory API URL",
        default='http://localhost:5000',
        config_parameter='gas_station_cash.glory_api_url',
        help="Base URL for the Glory Flask API middleware"
    )

    gas_glory_session_id = fields.Char(
        string="Glory Session ID",
        default='1',
        config_parameter='gas_station_cash.glory_session_id',
        help="Default session ID for Glory API calls"
    )

    # =========================================================================
    # END OF DAY SETTINGS
    # =========================================================================

    gas_eod_collect_mode = fields.Selection(
        selection=[
            ('all',            'Collect All Cash'),
            ('except_reserve', 'Keep Reserve Amount'),
        ],
        string="End of Day Collection Mode",
        default='except_reserve',
        config_parameter='gas_station_cash.eod_collect_mode',
        help="How to collect cash at End of Day: collect all or keep a reserve"
    )

    gas_eod_reserve_amount = fields.Float(
        string="End of Day Reserve Amount",
        default=5000.0,
        config_parameter='gas_station_cash.eod_reserve_amount',
        help="Amount of cash to keep as reserve at End of Day (when mode is 'Keep Reserve Amount')"
    )