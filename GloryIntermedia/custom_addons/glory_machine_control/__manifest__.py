# -*- coding: utf-8 -*-
{
    'name': 'Glory Machine Control',
    'version': '17.0.1.0.0',
    'category': 'Glory Cash Recycler',
    'summary': 'Machine Control Interface for Glory Cash Devices',
    'description': """
        Glory Machine Control
        =====================
        This module provides a web interface for controlling Glory cash handling devices:
        - Cash-in operations
        - Cash-out operations
        - Machine status monitoring

        Standalone module for machine control interface
    """,
    'author': 'Glory Convenience Store',
    'website': 'https://www.glory-global.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'views/machine_control_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'glory_machine_control/static/src/js/machine_control.js',
            'glory_machine_control/static/src/xml/machine_control.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
