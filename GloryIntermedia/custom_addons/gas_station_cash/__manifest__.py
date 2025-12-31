# -*- coding: utf-8 -*-
#
# File: custom_addons/gas_station_cash/__manifest__.py
# Author: Gemini
# Date: August 2, 2025
# Description: Manifest file for Gas Station Cash module
#
# License: P POWER GENERATING CO.,LTD.

{
    'name': "Gas Station Cash",
    'summary': "Module for managing cash deposits from gas station cashiers.",
    'description': """
        This module provides functionality to manage cash deposits for gas stations.
        Features:
        - Create and manage cash deposit records.
        - Define deposit lines with currency denominations.
        - Track deposits by staff member.
    """,
    'author': "Pakkapon Jirachatmongkon (P POWER GENERATING CO.,LTD.)",
    'website': "http://",
    'category': 'Gas Station/Cash',
    'version': '1.0',
    'depends': [
        'base',
        'web',
        'product',
        'base_setup',
        'pos_tcp_connector',
        'gas_station_erp_mini'
    ],
    'data': [
        'security/ir.model.access.csv',
        #'views/glory_control_views.xml',
        #'views/res_config_settings_views.xml',
        'views/gas_station_cash_views.xml',
        'views/cash_recycler_views.xml',
        'views/gas_station_cash_settings_views.xml',
        'views/gas_station_cash_product_views.xml',
        'views/gas_station_cash_rental_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'gas_station_cash/static/src/scss/cash_recycler.scss',
            'gas_station_cash/static/src/scss/pin_entry.scss',
            'gas_station_cash/static/src/scss/glory_control_panel.scss',
            'gas_station_cash/static/src/js/translation_helper.js',
            'gas_station_cash/static/src/js/live_cash_in_screen.js',
            'gas_station_cash/static/src/js/cash_deposit_summary_screen.js',
            'gas_station_cash/static/src/js/cash_in_mini_summary_screen.js',
            'gas_station_cash/static/src/js/cash_recycler_app.js',
            'gas_station_cash/static/src/js/pin_entry_screen.js',
            'gas_station_cash/static/src/js/oil_deposit_screen.js',
            'gas_station_cash/static/src/js/engine_oil_deposit_screen.js',
            'gas_station_cash/static/src/js/rental_deposit_screen.js',
            'gas_station_cash/static/src/js/coffee_shop_deposit_screen.js',
            'gas_station_cash/static/src/js/convenient_store_deposit_screen.js',
            'gas_station_cash/static/src/js/deposit_cash_screen.js',
            'gas_station_cash/static/src/js/exchange_cash_screen.js',
            'gas_station_cash/static/src/js/main.js',
            'gas_station_cash/static/src/js/glory_control_panel.js',
            'gas_station_cash/static/src/xml/cash_recycler_templates.xml',
            'gas_station_cash/static/src/xml/live_cash_in_screen_template.xml',
            'gas_station_cash/static/src/xml/cash_deposit_summary_templates.xml',
            'gas_station_cash/static/src/xml/cash_in_mini_summary_screen_templates.xml',
            'gas_station_cash/static/src/xml/pin_entry_screen_templates.xml',
            'gas_station_cash/static/src/xml/oil_deposit_templates.xml',
            'gas_station_cash/static/src/xml/engine_oil_deposit_templates.xml',
            'gas_station_cash/static/src/xml/rental_deposit_templates.xml',
            'gas_station_cash/static/src/xml/coffee_shop_deposit_templates.xml',
            'gas_station_cash/static/src/xml/convenient_store_deposit_templates.xml',
            'gas_station_cash/static/src/xml/deposit_cash_templates.xml',
            'gas_station_cash/static/src/xml/exchange_cash_templates.xml',
            'gas_station_cash/static/src/xml/glory_control_panel_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
