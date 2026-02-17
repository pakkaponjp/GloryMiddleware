# -*- coding: utf-8 -*-
# File: custom_addons/gas_station_cash/models/cash_withdrawal.py
# Description: Models for cash withdrawal audit from Cash Recycler

from odoo import models, fields, api, _


class GasStationCashWithdrawal(models.Model):
    _name = "gas.station.cash.withdrawal"
    _description = "Gas Station Cash Withdrawal"
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

    staff_id = fields.Many2one(
        "gas.station.staff",
        string="Staff",
        required=True,
        tracking=True,
        index=True,
        readonly=True,
    )
    date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    # ----- Withdrawal Lines -----
    withdrawal_line_ids = fields.One2many(
        "gas.station.cash.withdrawal.line",
        "withdrawal_id",
        string="Withdrawal Lines",
        copy=True,
        readonly=True,
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

    # ----- Withdrawal classification -----
    withdrawal_type = fields.Selection(
        [
            ("general", "General Withdrawal"),
            ("change", "Change/Float"),
            ("expense", "Petty Cash/Expense"),
            ("transfer", "Cash Transfer"),
        ],
        string="Withdrawal Type",
        default="general",
        tracking=True,
        index=True,
        readonly=True,
    )

    reason = fields.Text(
        string="Reason/Notes",
        tracking=True,
        help="Reason for withdrawal",
        readonly=True,
    )
    
    # ----- Notes (Editable) -----
    notes = fields.Text(
        string="Notes",
        help="Additional notes - can be edited anytime",
    )

    # ----- Glory Machine Info -----
    glory_session_id = fields.Char(
        string="Glory Session ID",
        index=True,
        readonly=True,
    )
    glory_transaction_id = fields.Char(
        string="Glory Transaction ID",
        index=True,
        readonly=True,
    )
    glory_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("dispensed", "Dispensed"),
            ("collected", "Collected"),
            ("failed", "Failed"),
        ],
        string="Glory Status",
        default="pending",
        index=True,
        tracking=True,
        readonly=True,
    )
    glory_response_json = fields.Text(
        string="Glory Response JSON",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("gas.station.cash.withdrawal.sequence")
                    or _("New")
                )
        return super().create(vals_list)

    @api.depends("withdrawal_line_ids.subtotal")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.withdrawal_line_ids.mapped("subtotal"))

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


class GasStationCashWithdrawalLine(models.Model):
    _name = "gas.station.cash.withdrawal.line"
    _description = "Gas Station Cash Withdrawal Line"

    withdrawal_id = fields.Many2one(
        "gas.station.cash.withdrawal",
        string="Cash Withdrawal",
        required=True,
        ondelete="cascade",
    )

    currency_id = fields.Many2one(
        "res.currency",
        related="withdrawal_id.currency_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="withdrawal_id.company_id",
        readonly=True,
    )

    denomination_type = fields.Selection(
        [
            ("note", "Note"),
            ("coin", "Coin"),
        ],
        string="Type",
        required=True,
        default="note",
        readonly=True,
    )

    currency_denomination = fields.Float(
        string="Denomination",
        required=True,
        readonly=True,
        help="Face value of note/coin (e.g., 1000, 500, 100, 20 for THB)",
    )
    quantity = fields.Integer(
        string="Quantity",
        required=True,
        default=1,
        readonly=True,
    )

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