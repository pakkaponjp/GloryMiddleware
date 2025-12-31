# -*- coding: utf-8 -*-
#
# File: custom_addons/gas_station_cash/models/cash_deposit.py
# Author: Gemini (updated by ChatGPT)
# Description: Models for cash management + POS audit fields
#
# License: P POWER GENERATING CO.,LTD.

import json

from odoo import models, fields, api, _


class GasStationCashDeposit(models.Model):
    _name = 'gas.station.cash.deposit'
    _description = 'Gas Station Cash Deposit'
    _order = 'date desc, name desc'

    # Add POS connector mixin so this model can call send_to_pos_tcp() / create_pos_job()
    _inherit = ['mail.thread', 'mail.activity.mixin', 'pos.connector.mixin']

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _('New'),
        tracking=True,
    )

    staff_id = fields.Many2one('gas.station.staff', string='Staff', required=True, tracking=True)

    # Use Datetime (not Date) so we preserve exact operation time in audit
    date = fields.Datetime(string='Date', required=True, default=fields.Datetime.now, tracking=True)

    deposit_line_ids = fields.One2many(
        'gas.station.cash.deposit.line',
        'deposit_id',
        string='Deposit Lines',
        copy=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )

    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='company_currency_id',
        compute='_compute_total_amount',
        store=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('audited', 'Audited'),
        ],
        string='Status',
        default='draft',
        readonly=True,
        tracking=True,
    )

    # ----- Audit dimensions (what kind of deposit) -----
    deposit_type = fields.Selection(
        [
            ('oil', 'Oil Sales'),
            ('engine_oil', 'Engine Oil Sales'),
            ('rental', 'Rental'),
            ('coffee_shop', 'Coffee Shop Sales'),
            ('convenient_store', 'Convenient Store Sales'),
            ('deposit_cash', 'Replenish Cash'),
            ('exchange_cash', 'Exchange Notes and Coins'),
        ],
        string='Deposit Type',
        default='oil',
        tracking=True,
        index=True,
    )

    # Optional: the selected “gas station cash product” (engine oil product list)
    product_id = fields.Many2one(
        'gas.station.cash.product',
        string='Gas Station Product',
        tracking=True,
        index=True,
    )

    # This drives the menu split: Cash Deposits vs POS Deposits
    is_pos_related = fields.Boolean(
        string='POS Related',
        default=False,
        index=True,
        tracking=True,
        help='If true, this deposit is also part of POS integration (appears in POS Deposits menu).'
    )

    # ----- POS integration audit fields -----
    pos_transaction_id = fields.Char(string='POS Transaction ID', index=True, tracking=True)

    pos_status = fields.Selection(
        [
            ('na', 'N/A'),
            ('ok', 'OK'),
            ('queued', 'Queued'),
            ('failed', 'Failed'),
        ],
        string='POS Status',
        default='na',
        index=True,
        tracking=True,
    )

    pos_description = fields.Char(string='POS Description')
    pos_time_stamp = fields.Char(string='POS Timestamp')  # keep as string; POS sends ISO
    pos_response_json = fields.Text(string='POS Response JSON')
    pos_error = fields.Text(string='POS Error / Reason')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('gas.station.cash.deposit.sequence') or _('New')
        return super().create(vals_list)

    @api.depends('deposit_line_ids.subtotal')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.deposit_line_ids.mapped('subtotal'))

    # ----- basic workflow -----
    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'

    def action_audit(self):
        for rec in self:
            rec.state = 'audited'

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    # ----- POS helpers (server-side) -----
    def _set_pos_fields(self, *, tx_id, status, resp=None, reason=None):
        """Small helper to update POS audit fields consistently."""
        resp = resp or {}
        self.write({
            'pos_transaction_id': tx_id,
            'pos_status': status,
            'pos_description': resp.get('description') or resp.get('discription') or False,
            'pos_time_stamp': resp.get('time_stamp') or False,
            'pos_response_json': json.dumps(resp, ensure_ascii=False) if resp else False,
            'pos_error': reason or False,
        })


class GasStationCashDepositLine(models.Model):
    _name = 'gas.station.cash.deposit.line'
    _description = 'Gas Station Cash Deposit Line'

    deposit_id = fields.Many2one(
        'gas.station.cash.deposit',
        string='Cash Deposit',
        required=True,
        ondelete='cascade',
    )

    currency_denomination = fields.Float(string='Denomination', required=True)
    quantity = fields.Integer(string='Quantity', required=True, default=1)

    currency_id = fields.Many2one('res.currency', related='deposit_id.currency_id', readonly=True)
    company_currency_id = fields.Many2one('res.currency', related='deposit_id.company_currency_id', readonly=True)

    subtotal = fields.Monetary(
        string='Subtotal',
        currency_field='company_currency_id',
        compute='_compute_subtotal',
        store=True,
    )

    @api.depends('currency_denomination', 'quantity')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.currency_denomination or 0.0) * (line.quantity or 0)
