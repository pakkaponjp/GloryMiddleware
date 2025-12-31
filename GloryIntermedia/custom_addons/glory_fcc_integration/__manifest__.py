#
# File: /C:/Users/TungMay/Desktop/GloryMiddleware/GloryIntermedia/custom_addons/glory_fcc_integration/__manifest__.py
# Author: Pakkapon Jirachatmongkon
# Date: July 29, 2025
# Description: Manifest file for Glory FCC Integration module
#
# License: P POWER GENERATING CO., LTD.
#
{
    'name': 'Glory FCC Integration',
    'version': '1.0',
    'category': 'Integration',
    'summary': 'Communicate with Glory FCC Emulator or Real Machine',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/glory_device_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}