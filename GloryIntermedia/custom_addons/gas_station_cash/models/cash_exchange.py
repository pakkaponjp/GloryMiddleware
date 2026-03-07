# -*- coding: utf-8 -*-
from odoo import models, fields, api


class GasStationCashExchange(models.Model):
    _name = "gas.station.cash.exchange"
    _description = "Gas Station Cash Exchange Audit"
    _order = "exchange_time desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="Reference",
        readonly=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("gas.station.cash.exchange") or "NEW",
    )
    exchange_time = fields.Datetime(
        string="Exchange Time",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )

    # Staff
    staff_id = fields.Many2one(
        "gas.station.staff",
        string="Staff",
        readonly=True,
    )
    staff_external_id = fields.Char(
        string="Staff External ID",
        readonly=True,
    )
    staff_name = fields.Char(
        string="Staff Name",
        readonly=True,
    )

    # Cash-in (deposited by customer)
    cashin_amount = fields.Monetary(
        string="Cash-In Amount",
        currency_field="currency_id",
        readonly=True,
        help="Amount customer deposited into machine.",
    )

    # Cash-out (dispensed back to customer)
    cashout_amount = fields.Monetary(
        string="Cash-Out Amount",
        currency_field="currency_id",
        readonly=True,
        help="Amount dispensed to customer.",
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        readonly=True,
    )

    # Denomination breakdown (JSON)
    cashin_breakdown_json = fields.Text(
        string="Cash-In Breakdown (JSON)",
        readonly=True,
    )
    cashout_breakdown_json = fields.Text(
        string="Cash-Out Breakdown (JSON)",
        readonly=True,
    )

    # Machine response
    machine_status = fields.Selection(
        [("ok", "OK"), ("failed", "Failed"), ("unknown", "Unknown")],
        string="Machine Status",
        default="unknown",
        readonly=True,
    )
    machine_response_json = fields.Text(
        string="Machine Response (JSON)",
        readonly=True,
    )

    notes = fields.Text(
        string="Notes",
        readonly=True,
    )

    @api.model
    def save_exchange(self, vals):
        """
        Called from JS after successful dispense.
        vals keys:
          staff_external_id, cashin_amount, cashout_amount,
          cashin_breakdown, cashout_breakdown,
          machine_status, machine_response, notes
        """
        staff = self.env["gas.station.staff"].sudo().search(
            [("external_id", "=", vals.get("staff_external_id", ""))], limit=1
        )

        import json
        record = self.sudo().create({
            "staff_id":               staff.id if staff else False,
            "staff_external_id":      vals.get("staff_external_id", ""),
            "staff_name":             staff.nickname or staff.name if staff else vals.get("staff_name", ""),
            "cashin_amount":          vals.get("cashin_amount", 0),
            "cashout_amount":         vals.get("cashout_amount", 0),
            "cashin_breakdown_json":  json.dumps(vals.get("cashin_breakdown", {}), ensure_ascii=False),
            "cashout_breakdown_json": json.dumps(vals.get("cashout_breakdown", {}), ensure_ascii=False),
            "machine_status":         vals.get("machine_status", "unknown"),
            "machine_response_json":  json.dumps(vals.get("machine_response", {}), ensure_ascii=False),
            "notes":                  vals.get("notes", ""),
        })
        return {"status": "ok", "exchange_id": record.id, "name": record.name}