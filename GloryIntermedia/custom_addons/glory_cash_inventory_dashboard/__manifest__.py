# -*- coding: utf-8 -*-
{
    'name': 'Glory Cash Inventory Dashboard',
    'version': '17.0.1.0.0',
    'category': 'Point of Sale',
    'summary': 'Cash Inventory Dashboard for Glory Cash Devices',
    'description': """
        Glory Cash Inventory Dashboard
        ==============================
        This module provides a dashboard to monitor cash inventory in Glory devices:
        - Real-time inventory monitoring
        - Notes and coins breakdown
        - Quantity histograms
        - Changeable status indicators
        
        Standalone module for inventory monitoring
    """,
    'author': 'Glory Convenience Store',
    'website': 'https://www.glory-global.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'views/inventory_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'glory_cash_inventory_dashboard/static/src/scss/inventory_dashboard.scss',
            'glory_cash_inventory_dashboard/static/src/js/inventory_dashboard.js',
            'glory_cash_inventory_dashboard/static/src/xml/inventory_dashboard.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

