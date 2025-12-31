# -*- coding: utf-8 -*-
#
# File: custom_addons/pos_tcp_connector/__manifest__.py
# Author: Pakkapon Jirachatmongkon
# Date: December 2, 2025
# Description: Manifest file for Gas Station POS TCP JSON Connector module
#
# License: P POWER GENERATING CO.,LTD.

{
    'name': "Gas Station POS TCP JSON Connector",
    'summary': """
        TCP(JSON) connector between GloryIntermedia (Gas Station Cash) and 3rd-party POS.
    """,
    'description': """
        This module provides a TCP(JSON) connector for gas station POS integration.

        Features (planned):
        - Send real-time transaction JSON from GloryIntermedia to POS
        - Heartbeat JSON between GloryIntermedia and POS
        - Queue jobs when POS is offline, and replay when it comes back online
    """,
    'author': "Pakkapon Jirachatmongkon (P POWER GENERATING CO.,LTD.)",
    'website': "http://",
    'category': 'Gas Station/Integration',
    'version': '1.0',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        # later: security, views, cron, etc.
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
