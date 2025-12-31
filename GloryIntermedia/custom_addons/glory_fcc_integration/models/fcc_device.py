#
# File: GloryIntermedia/custom_addons/gas_station_cash/models/fcc_device.py
# Author: Pakkapon Jirachatmongkon
# Date: July 29, 2025
# Description: models for FCC Device integration in GloryIntermedia's custom addons
#
# License: P POWER GENERATING CO.,LTD.
#
from odoo import models, fields
class GloryFccDevice(models.Model):
    _name = 'glory.fcc.device'
    _description = 'FCC Device Integration'

    name = fields.Char(string='Device Name', required=True)
    device_id = fields.Char(string='Device ID', required=True)
    ip_address = fields.Char(string='IP Address', required=True)
    staus = fields.Selection(
        selection=[('connected', 'Connected'), ('disconnected', 'Disconnected')],
        default='disconnected',
    )
    last_heartbeat = fields.Datetime(string='Last Heartbeat', help='Timestamp of the last heartbeat received from the device')