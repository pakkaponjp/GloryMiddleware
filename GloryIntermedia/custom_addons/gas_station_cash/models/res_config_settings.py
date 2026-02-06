# -*- coding: utf-8 -*-
"""
File: models/res_config_settings.py
Description: Configuration settings for Gas Station Cash module
"""

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # =========================================================================
    # POS INTEGRATION SETTINGS
    # =========================================================================
    
    gas_pos_vendor = fields.Selection(
        selection=[
            ('local', 'Local/Test'),
            ('firstpro', 'FirstPro'),
            ('flowco', 'FlowCo'),
        ],
        string="POS Vendor",
        default='local',
        config_parameter='gas_station_cash.pos_vendor',
        help="Select which external POS vendor the middleware talks to"
    )

    # =========================================================================
    # COLLECTION SETTINGS
    # =========================================================================
    
    gas_collect_on_close_shift = fields.Boolean(
        string="Collect on Close Shift",
        default=False,
        config_parameter='gas_station_cash.collect_on_close_shift',
        help="If enabled, the middleware will collect cash into the collection box when the POS calls CloseShift"
    )
    
    gas_float_amount = fields.Float(
        string="Float Amount",
        default=5000.0,
        config_parameter='gas_station_cash.float_amount',
        help="Amount of cash to keep in the machine as float after collection"
    )

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
            ('all', 'Collect All Cash'),
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