# -*- coding: utf-8 -*-
#
# File: custom_addons/gas_station_erp_mini/__manifest__.py
# Author: Pakkapon Jirachatmongkon
# Date: July 29, 2025
# Description: Manifest file for Gas Station ERP Mini module
#
# License: P POWER GENERATING CO.,LTD.

{
    'name': "Gas Station ERP Mini",
    'summary': """
        Lightweight ERP module for managing gas station staff and syncing with frontend cash system.
    """,
    'description': """
        This module provides staff management functionality for gas stations.
        Features:
        - Create and manage gas station staff
        - Assign roles: Manager, Supervisor, Cashier, Staff
        - Designed to sync with Glory FCC Cash Machine and POS middleware
    """,
    'author': "Pakkapon Jirachatmongkon (P POWER GENERATING CO.,LTD.)",
    'website': "http://",
    'category': 'Gas Station/Staff',
    'version': '1.0',
    'depends': ['base', 'web', 'hr'],
    'data': [
        'security/gas_station_erp_mini_groups.xml',
        'security/ir.model.access.csv',
        'data/staff_sequence.xml',
        'views/gas_station_staff_views.xml', 
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
