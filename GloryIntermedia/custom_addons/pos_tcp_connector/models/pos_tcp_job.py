# custom_addons/pos_tcp_connector/models/pos_tcp_job.py
from odoo import models, fields

class PosTcpJob(models.Model):
    _name = 'pos.tcp.job'
    _description = 'POS TCP JSON Job Queue'
    _order = 'id desc'

    message_type = fields.Selection([
        ('heartbeat', 'Heartbeat'),
        ('deposit', 'Deposit'),
        ('close_shift', 'Close Shift'),
        ('end_of_day', 'End of Day'),
        ('transaction', 'Transaction'),
        ('z_summary', 'Z Summary'),
        ('audit', 'Audit'),
        ('restore', 'Restore'),
        ('custom', 'Custom'),
    ], required=True, default='custom')

    direction = fields.Selection([
        ('glory_to_pos', 'Glory → POS'),
        ('pos_to_glory', 'POS → Glory'),
    ], required=True, default='glory_to_pos', index=True)

    vendor = fields.Selection([
        ('firstpro', 'FirstPro'),
        ('flowco', 'FlowCo'),
    ], required=True, default='firstpro', index=True)

    terminal_id = fields.Char(string='POS Terminal ID', index=True)

    payload_json = fields.Text(string='Request JSON', required=True)
    response_json = fields.Text(string='Response JSON')

    state = fields.Selection([
        ('pending', 'Pending'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], required=True, default='pending', index=True)

    error_message = fields.Text(string='Error Message')
