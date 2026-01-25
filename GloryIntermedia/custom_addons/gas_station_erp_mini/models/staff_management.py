# -*- coding: utf-8 -*-
#
# File: GloryIntermedia/custom_addons/gas_station_erp_mini/models/staff_management.py
# Author: Pakkapon Jirachatmongkon
# Date: July 29, 2025
# Description: Models for staff management in the gas_station_erp_mini module
#
# License: P POWER GENERATING CO.,LTD.
#

import hashlib
import hmac
from odoo import models, fields, api, _

class GasStationStaff(models.Model):
    _name = 'gas.station.staff'
    _description = 'Gas Station Staff'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _sql_constraints = [
        ('employee_id_unique', 'UNIQUE(employee_id)', 'Employee ID must be unique.'),
    ]

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    nickname = fields.Char(string='Nickname', required=False)
    address1 = fields.Text(string='Address1')
    address2 = fields.Text(string='Address2')
    phone = fields.Char(string='Telephone Number')

    # The 'name' field is now a computed field from first_name and last_name
    name = fields.Char(string='Staff Name', compute='_compute_full_name', store=True, tracking=True)
    employee_id = fields.Char(string='Employee ID', required=True, copy=False, readonly=True, default=lambda self: _('New'), tracking=True)
    external_id = fields.Char(string='External ID', help='ID used for external systems', tracking=True)
    user_id = fields.Many2one('res.users', string='Related Odoo User', ondelete='set null',
                             help="Odoo user linked to this staff profile. Used for syncing roles and access.", tracking=True)
    role = fields.Selection([
        ('manager', 'Manager'),
        ('supervisor', 'Supervisor'),
        ('cashier', 'Cashier'),
        ('attendant', 'Attendant'),
        ('coffee_shop_staff', 'Coffee Shop Staff'),
        ('convenient_store_staff', 'Convenient Store Staff'),
        ('tenant', 'Tenant'),
    ], string='Role', default='attendant', required=True, tracking=True)
    pin_hash = fields.Char("PIN Hash", readonly=True)
    pin = fields.Char(string='PIN', size=4, help="4-digit PIN for quick access/authentication.", compute=False, store=False, tracking=True)
    fingerprint_id = fields.Char(string='Fingerprint ID', help="Unique ID for fingerprint authentication.", tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    def set_pin(self, raw_pin):
        """Hash and store PIN securely"""
        if not raw_pin:
            return
        salt = self.env["ir.config_parameter"].sudo().get_param("gas_station_pin_salt", "default_salt")
        hashed = hashlib.sha256((raw_pin + salt).encode()).hexdigest()
        self.write({"pin_hash": hashed})

    def check_pin(self, raw_pin):
        """Verify PIN against hash"""
        if not raw_pin:
            return False
        salt = self.env["ir.config_parameter"].sudo().get_param("gas_station_pin_salt", "default_salt")
        hashed = hashlib.sha256((raw_pin + salt).encode()).hexdigest()
        return hmac.compare_digest(hashed, self.pin_hash or "")

    @api.depends('first_name', 'last_name')
    def _compute_full_name(self):
        for record in self:
            record.name = f"{record.first_name or ''} {record.last_name or ''}".strip()

    @api.model
    def create(self, vals):
        if not vals.get('employee_id') or vals['employee_id'] == 'New':
            vals['employee_id'] = self.env['ir.sequence'].next_by_code('gas.station.staff')
        staff = super().create(vals)
        if vals.get("pin"):   # hash the PIN if provided
            staff.set_pin(vals["pin"])
        return staff
    
    def write(self, vals):
        res = super().write(vals)
        if vals.get("pin"):   # hash the PIN if updated
            self.set_pin(vals["pin"])
        return res