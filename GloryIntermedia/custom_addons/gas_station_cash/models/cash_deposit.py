# -*- coding: utf-8 -*-
# File: custom_addons/gas_station_cash/models/cash_deposit.py
# Description: Models for cash management - audit deposits from Cash Recycler

from odoo import models, fields, api, _


class GasStationCashDeposit(models.Model):
    _name = "gas.station.cash.deposit"
    _description = "Gas Station Cash Deposit"
    _order = "date desc, name desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
        tracking=True,
    )

    staff_id = fields.Many2one("gas.station.staff", string="Staff", required=True, tracking=True)
    date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now, tracking=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    deposit_line_ids = fields.One2many(
        "gas.station.cash.deposit.line",
        "deposit_id",
        string="Deposit Lines",
        copy=True,
    )

    total_amount = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("audited", "Audited"),
        ],
        string="Status",
        default="draft",
        readonly=True,
        tracking=True,
    )

    # ----- Deposit classification (from Cash Recycler menu buttons) -----
    deposit_type = fields.Selection(
        [
            ("oil", "Oil Sales"),
            ("engine_oil", "Engine Oil Sales"),
            ("rental", "Rental"),
            ("coffee_shop", "Coffee Shop Sales"),
            ("convenient_store", "Convenient Store Sales"),
            ("deposit_cash", "Replenish Cash"),
            ("exchange_cash", "Exchange Notes and Coins"),
        ],
        string="Deposit Type",
        default="oil",
        tracking=True,
        index=True,
    )

    product_id = fields.Many2one(
        "gas.station.cash.product",
        string="Gas Station Product",
        tracking=True,
        index=True,
    )

    is_pos_related = fields.Boolean(
        string="POS Related",
        default=False,
        index=True,
        tracking=True,
        help="If true, this deposit is linked to POS system.",
    )

    # ----- POS integration audit fields -----
    pos_transaction_id = fields.Char(string="POS Transaction ID", index=True, tracking=True)
    pos_status = fields.Selection(
        [
            ("na", "N/A"),
            ("ok", "OK"),
            ("queued", "Queued"),
            ("failed", "Failed"),
        ],
        string="POS Status",
        default="na",
        index=True,
        tracking=True,
    )
    pos_description = fields.Char(string="POS Description")
    pos_time_stamp = fields.Char(string="POS Timestamp")  # keep as string; POS sends ISO
    pos_response_json = fields.Text(string="POS Response JSON")
    pos_error = fields.Text(string="POS Error / Reason")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("gas.station.cash.deposit.sequence")
                    or _("New")
                )
        return super().create(vals_list)

    @api.depends("deposit_line_ids.subtotal")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.deposit_line_ids.mapped("subtotal"))

    # ----- Workflow actions -----
    def action_confirm(self):
        for rec in self:
            rec.state = "confirmed"

    def action_audit(self):
        for rec in self:
            rec.state = "audited"

    def action_draft(self):
        for rec in self:
            rec.state = "draft"


class GasStationCashDepositLine(models.Model):
    _name = "gas.station.cash.deposit.line"
    _description = "Gas Station Cash Deposit Line"

    deposit_id = fields.Many2one(
        "gas.station.cash.deposit",
        string="Cash Deposit",
        required=True,
        ondelete="cascade",
    )

    currency_id = fields.Many2one("res.currency", related="deposit_id.currency_id", readonly=True)
    company_id = fields.Many2one("res.company", related="deposit_id.company_id", readonly=True)

    currency_denomination = fields.Float(string="Denomination", required=True)
    quantity = fields.Integer(string="Quantity", required=True, default=1)

    subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        compute="_compute_subtotal",
        store=True,
    )

    @api.depends("currency_denomination", "quantity")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.currency_denomination or 0.0) * (line.quantity or 0)
