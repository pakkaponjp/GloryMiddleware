# -*- coding: utf-8 -*-
from odoo import models, fields


class GasStationCashRental(models.Model):
    _name = "gas.station.cash.rental"
    _description = "Gas Station Rental Space"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    name = fields.Char(string="Rental Name", required=True)
    code = fields.Char(string="Rental Code", required=True)

    price = fields.Float(
        string="Default Rent Amount",
        required=True,
        default=0.0,
        help="Default rental price per period (day/month/etc. depending on your business rule).",
    )
    
    tenant_staff_id = fields.Many2one(
        "gas.station.staff",
        string="Tenant (Staff)",
        domain=[("role", "=", "tenant"), ("active", "=", True)],
        help=(
            "Gas Station Staff record with role 'Tenant'. "
            "The same tenant can rent multiple rental places."
        ),
    )

    is_pos_related = fields.Boolean(
        string="POS Related",
        help="If checked, deposits with this rental will be treated as POS-related in POS totals.",
    )

    active = fields.Boolean(default=True)
