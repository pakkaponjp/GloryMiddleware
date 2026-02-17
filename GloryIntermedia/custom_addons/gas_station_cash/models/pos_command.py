# -*- coding: utf-8 -*-
"""
File: models/pos_command.py
Description: POS Command model for tracking commands and overlay display
"""

from odoo import models, fields, api
import json
import logging

_logger = logging.getLogger(__name__)


class GasStationPosCommand(models.Model):
    _name = 'gas.station.pos_command'
    _description = 'POS Command'
    _order = 'create_date desc'

    name = fields.Char(
        string='Name',
        required=True,
        readonly=True,
    )
    action = fields.Char(
        string='Action',
        readonly=True,
    )
    request_id = fields.Char(
        string='Request ID',
        readonly=True,
    )
    pos_terminal_id = fields.Char(
        string='Terminal ID',
        readonly=True,
    )
    staff_external_id = fields.Char(
        string='Staff ID',
        readonly=True,
    )
    pos_shift_id = fields.Char(
        string='POS Shift ID',
        readonly=True,
    )
    status = fields.Selection([
        ('processing', 'Processing'),
        ('collection_complete', 'Collection Complete'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='Status', default='processing', readonly=True)
    message = fields.Text(
        string='Message',
        readonly=True,
    )
    started_at = fields.Datetime(
        string='Started At',
        readonly=True,
    )
    finished_at = fields.Datetime(
        string='Finished At',
        readonly=True,
    )
    payload_in = fields.Text(
        string='Input Payload',
        readonly=True,
    )
    payload_out = fields.Text(
        string='Output Payload',
        readonly=True,
    )
    
    # Collection result fields
    collected_amount = fields.Float(
        string='Collected Amount',
        readonly=True,
    )
    collection_breakdown = fields.Text(
        string='Collection Breakdown (JSON)',
        readonly=True,
    )
    
    # ----- Notes (Editable) -----
    notes = fields.Text(
        string="Notes",
        help="Additional notes - can be edited anytime",
    )

    def push_overlay(self):
        """Push overlay notification to frontend via bus."""
        self.ensure_one()
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': self.status,
            'message': self.message or 'processing...',
        }
        
        _logger.info("PUSH OVERLAY channel=%s event=pos_command payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)

    def update_overlay_message(self, message):
        """Update the overlay message and push to frontend."""
        self.ensure_one()
        self.write({'message': message})
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': self.status,
            'message': message,
        }
        
        _logger.info("UPDATE OVERLAY channel=%s payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)

    def mark_collection_complete(self, result: dict):
        """
        Mark command as collection complete - shows unlock popup.
        
        Args:
            result: dict containing collection results
        """
        self.ensure_one()
        
        collected_amount = result.get('collected_amount', 0.0)
        collected_breakdown = result.get('collected_breakdown', {})
        
        self.write({
            'status': 'collection_complete',
            'message': 'Collection complete',
            'payload_out': json.dumps(result, ensure_ascii=False, default=str),
            'collected_amount': collected_amount,
            'collection_breakdown': json.dumps(collected_breakdown, ensure_ascii=False),
        })
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': 'collection_complete',
            'message': 'การนำเงินลง Collection Box เสร็จสิ้น',
            # Data for unlock popup
            'show_unlock_popup': True,
            'collected_amount': collected_amount,
            'collected_breakdown': collected_breakdown,
        }
        
        _logger.info("COLLECTION COMPLETE channel=%s payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)

    def mark_done(self, result: dict = None):
        """Mark command as done and hide overlay."""
        self.ensure_one()
        
        self.write({
            'status': 'done',
            'message': 'Success',
            'finished_at': fields.Datetime.now(),
            'payload_out': json.dumps(result or {}, ensure_ascii=False, default=str),
        })
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': 'done',
            'message': 'Success',
        }
        
        _logger.info("MARK DONE channel=%s payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)

    def mark_failed(self, error_message: str):
        """Mark command as failed."""
        self.ensure_one()
        
        self.write({
            'status': 'failed',
            'message': error_message,
            'finished_at': fields.Datetime.now(),
        })
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': 'failed',
            'message': error_message,
        }
        
        _logger.info("MARK FAILED channel=%s payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)

    def mark_insufficient_reserve(self, result: dict = None):
        """
        Mark command as completed but with insufficient reserve warning.
        No collection happened, no unlock needed.
        
        Args:
            result: dict containing:
                - current_cash: Current cash amount in machine
                - required_reserve: Required reserve amount
                - shortfall: Amount needed to meet reserve
        """
        self.ensure_one()
        
        result = result or {}
        current_cash = result.get('current_cash', 0.0)
        required_reserve = result.get('required_reserve', 0.0)
        shortfall = result.get('shortfall', 0.0)
        
        self.write({
            'status': 'done',
            'message': f'Insufficient reserve (Current: {current_cash:.2f} / Required: {required_reserve:.2f})',
            'finished_at': fields.Datetime.now(),
            'payload_out': json.dumps(result, ensure_ascii=False, default=str),
        })
        
        channel = ('odoo', f'gas_station_cash:{self.pos_terminal_id}')
        
        payload = {
            'command_id': self.id,
            'action': self.action,
            'request_id': self.request_id,
            'status': 'insufficient_reserve',
            'message': 'Insufficient reserve cash in machine',
            'show_unlock_popup': False,
            # Reserve info for display
            'current_cash': current_cash,
            'required_reserve': required_reserve,
            'shortfall': shortfall,
        }
        
        _logger.info("INSUFFICIENT RESERVE channel=%s payload=%s", channel, payload)
        
        self.env['bus.bus']._sendone(channel, 'pos_command', payload)