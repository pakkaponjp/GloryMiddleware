# -*- coding: utf-8 -*-
"""
File: models/gas_station_cash_settings.py
Description: Configuration settings for Gas Station Cash module
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


# (field_suffix, cap_key, face_value_satang, label)
WM_DENOMS = [
    ('note_1000', 'note_1000', 100000, '฿1,000'),
    ('note_500',  'note_500',   50000, '฿500'),
    ('note_100',  'note_100',   10000, '฿100'),
    ('note_50',   'note_50',     5000, '฿50'),
    ('note_20',   'note_20',     2000, '฿20'),
    ('coin_10',   'coin_10',     1000, '฿10'),
    ('coin_5',    'coin_5',       500, '฿5'),
    ('coin_2',    'coin_2',       200, '฿2'),
    ('coin_1',    'coin_1',       100, '฿1'),
    ('coin_050',  'coin_050',      50, '฿0.50'),
    ('coin_025',  'coin_025',      25, '฿0.25'),
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

    @api.onchange('gas_leave_float')
    def _onchange_leave_float(self):
        """Clear all float denomination quantities (and amount) when Leave Float is turned off."""
        if not self.gas_leave_float:
            self.gas_float_note_1000 = 0
            self.gas_float_note_500  = 0
            self.gas_float_note_100  = 0
            self.gas_float_note_50   = 0
            self.gas_float_note_20   = 0
            self.gas_float_coin_10   = 0
            self.gas_float_coin_5    = 0
            self.gas_float_coin_2    = 0
            self.gas_float_coin_1    = 0
            self.gas_float_coin_050  = 0
            self.gas_float_coin_025  = 0
            self.gas_float_amount    = 0.0

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
    # WATERMARK SETTINGS — denomination near-empty / near-full thresholds
    # =========================================================================
    # Low  (Near Empty): qty < threshold → แนะนำ Replenish
    # High (Near Full):  qty > threshold → แนะนำ Collect/Exchange
    # High default = stacker capacity from odoo.conf [glory_machine_config]
    # Low  default = 0 (disabled until user configures)

    # Notes — Low watermark (Near Empty)
    gas_wm_low_note_1000 = fields.Integer(string="฿1,000 Low",  default=0, config_parameter='gas_station_cash.wm_low_note_1000')
    gas_wm_low_note_500  = fields.Integer(string="฿500 Low",    default=0, config_parameter='gas_station_cash.wm_low_note_500')
    gas_wm_low_note_100  = fields.Integer(string="฿100 Low",    default=0, config_parameter='gas_station_cash.wm_low_note_100')
    gas_wm_low_note_50   = fields.Integer(string="฿50 Low",     default=0, config_parameter='gas_station_cash.wm_low_note_50')
    gas_wm_low_note_20   = fields.Integer(string="฿20 Low",     default=0, config_parameter='gas_station_cash.wm_low_note_20')
    # Notes — High watermark (Near Full)
    gas_wm_high_note_1000 = fields.Integer(string="฿1,000 High", default=0, config_parameter='gas_station_cash.wm_high_note_1000')
    gas_wm_high_note_500  = fields.Integer(string="฿500 High",   default=0, config_parameter='gas_station_cash.wm_high_note_500')
    gas_wm_high_note_100  = fields.Integer(string="฿100 High",   default=0, config_parameter='gas_station_cash.wm_high_note_100')
    gas_wm_high_note_50   = fields.Integer(string="฿50 High",    default=0, config_parameter='gas_station_cash.wm_high_note_50')
    gas_wm_high_note_20   = fields.Integer(string="฿20 High",    default=0, config_parameter='gas_station_cash.wm_high_note_20')

    # Coins — Low watermark (Near Empty)
    gas_wm_low_coin_10  = fields.Integer(string="฿10 Low",   default=0, config_parameter='gas_station_cash.wm_low_coin_10')
    gas_wm_low_coin_5   = fields.Integer(string="฿5 Low",    default=0, config_parameter='gas_station_cash.wm_low_coin_5')
    gas_wm_low_coin_2   = fields.Integer(string="฿2 Low",    default=0, config_parameter='gas_station_cash.wm_low_coin_2')
    gas_wm_low_coin_1   = fields.Integer(string="฿1 Low",    default=0, config_parameter='gas_station_cash.wm_low_coin_1')
    gas_wm_low_coin_050 = fields.Integer(string="฿0.50 Low", default=0, config_parameter='gas_station_cash.wm_low_coin_050')
    gas_wm_low_coin_025 = fields.Integer(string="฿0.25 Low", default=0, config_parameter='gas_station_cash.wm_low_coin_025')
    # Coins — High watermark (Near Full)
    gas_wm_high_coin_10  = fields.Integer(string="฿10 High",   default=0, config_parameter='gas_station_cash.wm_high_coin_10')
    gas_wm_high_coin_5   = fields.Integer(string="฿5 High",    default=0, config_parameter='gas_station_cash.wm_high_coin_5')
    gas_wm_high_coin_2   = fields.Integer(string="฿2 High",    default=0, config_parameter='gas_station_cash.wm_high_coin_2')
    gas_wm_high_coin_1   = fields.Integer(string="฿1 High",    default=0, config_parameter='gas_station_cash.wm_high_coin_1')
    gas_wm_high_coin_050 = fields.Integer(string="฿0.50 High", default=0, config_parameter='gas_station_cash.wm_high_coin_050')
    gas_wm_high_coin_025 = fields.Integer(string="฿0.25 High", default=0, config_parameter='gas_station_cash.wm_high_coin_025')

    # -------------------------------------------------------------------------
    # WATERMARK % DISPLAY — transient, not stored, no config_parameter
    # -------------------------------------------------------------------------
    # Notes Low %
    gas_wm_low_note_1000_pct  = fields.Char(string="", readonly=True)
    gas_wm_low_note_500_pct   = fields.Char(string="", readonly=True)
    gas_wm_low_note_100_pct   = fields.Char(string="", readonly=True)
    gas_wm_low_note_50_pct    = fields.Char(string="", readonly=True)
    gas_wm_low_note_20_pct    = fields.Char(string="", readonly=True)
    # Notes High %
    gas_wm_high_note_1000_pct = fields.Char(string="", readonly=True)
    gas_wm_high_note_500_pct  = fields.Char(string="", readonly=True)
    gas_wm_high_note_100_pct  = fields.Char(string="", readonly=True)
    gas_wm_high_note_50_pct   = fields.Char(string="", readonly=True)
    gas_wm_high_note_20_pct   = fields.Char(string="", readonly=True)
    # Coins Low %
    gas_wm_low_coin_10_pct    = fields.Char(string="", readonly=True)
    gas_wm_low_coin_5_pct     = fields.Char(string="", readonly=True)
    gas_wm_low_coin_2_pct     = fields.Char(string="", readonly=True)
    gas_wm_low_coin_1_pct     = fields.Char(string="", readonly=True)
    gas_wm_low_coin_050_pct   = fields.Char(string="", readonly=True)
    gas_wm_low_coin_025_pct   = fields.Char(string="", readonly=True)
    # Coins High %
    gas_wm_high_coin_10_pct   = fields.Char(string="", readonly=True)
    gas_wm_high_coin_5_pct    = fields.Char(string="", readonly=True)
    gas_wm_high_coin_2_pct    = fields.Char(string="", readonly=True)
    gas_wm_high_coin_1_pct    = fields.Char(string="", readonly=True)
    gas_wm_high_coin_050_pct  = fields.Char(string="", readonly=True)
    gas_wm_high_coin_025_pct  = fields.Char(string="", readonly=True)

    # =========================================================================
    # GET VALUES — seed High watermark only on first-ever load
    # =========================================================================

    @api.model
    def get_values(self):
        """
        Load settings.
        Seed High watermark with stacker capacity ONLY when the ICP key has NEVER been saved.
        ICP.get_param() returns False (not '0', not None) when the key does not exist at all —
        this correctly distinguishes 'never set' from 'user saved 0 or any other value'.
        """
        res = super().get_values()
        if res.get('gas_pos_vendor') == 'local':
            res['gas_pos_vendor'] = False

        cap = self._read_stacker_capacity()
        ICP = self.env['ir.config_parameter'].sudo()

        for suffix, cap_key, _satang, _label in WM_DENOMS:
            icp_key = f'gas_station_cash.wm_high_{suffix}'
            if ICP.get_param(icp_key) is False:      # key never saved → seed once with capacity
                res[f'gas_wm_high_{suffix}'] = cap.get(cap_key, 0)

        # Populate % display strings on page load
        res.update(self._compute_wm_pct_values(res, cap))
        return res

    # =========================================================================
    # STACKER CAPACITY READER
    # =========================================================================

    @api.model
    def _read_stacker_capacity(self) -> dict:
        """
        Read stacker capacity from odoo.conf [glory_machine_config].
        Returns dict: {note_1000: int, ..., coin_025: int}
        Returns empty dict if section not found.
        """
        import configparser
        from odoo.tools import config as odoo_config

        conf_path = getattr(odoo_config, 'rcfile', None)
        if not conf_path:
            return {}

        parser = configparser.ConfigParser()
        parser.read(conf_path)

        if not parser.has_section('glory_machine_config'):
            return {}

        section = parser['glory_machine_config']

        def _int(key, fallback=0):
            try:
                return int(section.get(key, fallback))
            except (ValueError, TypeError):
                return fallback

        return {
            'note_1000': _int('stacker_note_1000_capacity'),
            'note_500':  _int('stacker_note_500_capacity'),
            'note_100':  _int('stacker_note_100_capacity'),
            'note_50':   _int('stacker_note_50_capacity'),
            'note_20':   _int('stacker_note_20_capacity'),
            'coin_10':   _int('stacker_coin_10_capacity'),
            'coin_5':    _int('stacker_coin_5_capacity'),
            'coin_2':    _int('stacker_coin_2_capacity'),
            'coin_1':    _int('stacker_coin_1_capacity'),
            'coin_050':  _int('stacker_coin_050_capacity'),
            'coin_025':  _int('stacker_coin_025_capacity'),
        }

    # =========================================================================
    # WATERMARK % HELPERS
    # =========================================================================

    def _pct_str(self, qty, capacity):
        """Return '12.5%' string, or '—' when capacity is 0 (not configured)."""
        if not capacity:
            return '—'
        return f'{(qty or 0) / capacity * 100:.1f}%'

    def _compute_wm_pct_values(self, values, cap=None):
        """Compute all 22 pct display strings from a values dict + capacity dict."""
        if cap is None:
            cap = self._read_stacker_capacity()
        pct = {}
        for suffix, cap_key, _satang, _label in WM_DENOMS:
            capacity = cap.get(cap_key, 0)
            pct[f'gas_wm_low_{suffix}_pct']  = self._pct_str(values.get(f'gas_wm_low_{suffix}',  0), capacity)
            pct[f'gas_wm_high_{suffix}_pct'] = self._pct_str(values.get(f'gas_wm_high_{suffix}', 0), capacity)
        return pct

    # =========================================================================
    # WATERMARK ONCHANGE — split by Low / High so we always reset the edited field
    # =========================================================================
    # Design rule:
    #   - User edits High → validate High only  (never touch Low)
    #   - User edits Low  → validate Low only   (never touch High)
    #
    # High validation:
    #   High > capacity   → reset High = capacity (100%)
    #   High ≤ Low        → reset High = capacity (100%)
    #
    # Low validation:
    #   Low < 0           → reset Low = 0 (0%)
    #   Low ≥ High        → reset Low = 0 (0%)
    # =========================================================================

    def _refresh_wm_pct(self):
        """Recompute all % display fields from current field values."""
        cap = self._read_stacker_capacity()
        values = {}
        for suffix, _cap_key, _satang, _label in WM_DENOMS:
            values[f'gas_wm_low_{suffix}']  = getattr(self, f'gas_wm_low_{suffix}',  0) or 0
            values[f'gas_wm_high_{suffix}'] = getattr(self, f'gas_wm_high_{suffix}', 0) or 0
        for field_name, pct_val in self._compute_wm_pct_values(values, cap).items():
            setattr(self, field_name, pct_val)

    @api.onchange(
        'gas_wm_high_note_1000', 'gas_wm_high_note_500', 'gas_wm_high_note_100',
        'gas_wm_high_note_50',   'gas_wm_high_note_20',
        'gas_wm_high_coin_10',   'gas_wm_high_coin_5',   'gas_wm_high_coin_2',
        'gas_wm_high_coin_1',    'gas_wm_high_coin_050',  'gas_wm_high_coin_025',
    )
    def _onchange_wm_high(self):
        """
        User is editing a High (Near Full) field.
        Validate High only — never touch Low.
          - High > capacity → reset High = capacity (100%)
          - High ≤ Low      → reset High = capacity (100%)
        """
        cap = self._read_stacker_capacity()
        warning_lines = []

        for suffix, cap_key, _satang, label in WM_DENOMS:
            capacity = cap.get(cap_key, 0)
            high_field = f'gas_wm_high_{suffix}'
            low_val    = getattr(self, f'gas_wm_low_{suffix}', 0) or 0
            high       = max(0, getattr(self, high_field, 0) or 0)

            reset = False
            if capacity and high > capacity:
                warning_lines.append(
                    f'{label} Near Full (High) exceeds stacker capacity ({capacity}). '
                    f'Reset to {capacity} (100%). Please re-enter a valid value.'
                )
                reset = True
            elif not (high > low_val):
                warning_lines.append(
                    f'{label} Near Full (High) must be greater than Near Empty (Low={low_val}). '
                    f'Reset to {capacity} (100%). Please re-enter a valid value.'
                )
                reset = True

            if reset:
                setattr(self, high_field, capacity)

        self._refresh_wm_pct()
        if warning_lines:
            return {'warning': {'title': 'Near Full (High) value invalid', 'message': '\n'.join(warning_lines)}}

    @api.onchange(
        'gas_wm_low_note_1000', 'gas_wm_low_note_500', 'gas_wm_low_note_100',
        'gas_wm_low_note_50',   'gas_wm_low_note_20',
        'gas_wm_low_coin_10',   'gas_wm_low_coin_5',   'gas_wm_low_coin_2',
        'gas_wm_low_coin_1',    'gas_wm_low_coin_050',  'gas_wm_low_coin_025',
    )
    def _onchange_wm_low(self):
        """
        User is editing a Low (Near Empty) field.
        Validate Low only — never touch High.
          - Low < 0    → reset Low = 0 (0%)
          - Low is not < High → reset Low = 0 (0%)
        """
        cap = self._read_stacker_capacity()
        warning_lines = []

        for suffix, cap_key, _satang, label in WM_DENOMS:
            low_field = f'gas_wm_low_{suffix}'
            high_val  = getattr(self, f'gas_wm_high_{suffix}', 0) or 0
            low       = getattr(self, low_field, 0) or 0

            reset = False
            if low < 0:
                warning_lines.append(
                    f'{label} Near Empty (Low) cannot be negative. Reset to 0 (0%). Please re-enter a valid value.'
                )
                reset = True
            elif not (low < high_val):
                warning_lines.append(
                    f'{label} Near Empty (Low) must be less than Near Full (High={high_val}). '
                    f'Reset to 0 (0%). Please re-enter a valid value.'
                )
                reset = True

            if reset:
                setattr(self, low_field, 0)

        self._refresh_wm_pct()
        if warning_lines:
            return {'warning': {'title': 'Near Empty (Low) value invalid', 'message': '\n'.join(warning_lines)}}

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