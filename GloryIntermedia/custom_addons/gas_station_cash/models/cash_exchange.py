# -*- coding: utf-8 -*-
import json
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
    staff_id = fields.Many2one("gas.station.staff", string="Staff", readonly=True)
    staff_external_id = fields.Char(string="Staff External ID", readonly=True)
    staff_name = fields.Char(string="Staff Name", readonly=True)

    # Cash-in / Cash-out
    cashin_amount = fields.Monetary(
        string="Cash-In Amount", currency_field="currency_id", readonly=True,
        help="Amount customer deposited into machine.",
    )
    cashout_amount = fields.Monetary(
        string="Cash-Out Amount", currency_field="currency_id", readonly=True,
        help="Amount dispensed to customer.",
    )
    currency_id = fields.Many2one(
        "res.currency", string="Currency", required=True,
        default=lambda self: self.env.company.currency_id, readonly=True,
    )

    # Denomination breakdown (JSON — stored in satang)
    cashin_breakdown_json  = fields.Text(string="Cash-In Breakdown (JSON)",  readonly=True)
    cashout_breakdown_json = fields.Text(string="Cash-Out Breakdown (JSON)", readonly=True)

    # Human-readable computed summaries
    cashin_breakdown_summary = fields.Text(
        string="Cash-In Breakdown",
        compute="_compute_breakdown_summaries",
        readonly=True,
    )
    cashout_breakdown_summary = fields.Text(
        string="Cash-Out Breakdown",
        compute="_compute_breakdown_summaries",
        readonly=True,
    )

    machine_status = fields.Selection(
        [("ok", "OK"), ("failed", "Failed"), ("unknown", "Unknown")],
        string="Machine Status", default="unknown", readonly=True,
    )
    machine_response_json = fields.Text(string="Machine Response (JSON)", readonly=True)
    notes = fields.Text(string="Notes", readonly=True)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_breakdown(json_str):
        """Convert stored satang breakdown JSON into a readable text table."""
        if not json_str:
            return "—"
        try:
            data = json.loads(json_str)
        except Exception:
            return json_str  # fallback: show raw

        lines = []
        notes = data.get("notes") or []
        coins = data.get("coins") or []

        if notes:
            lines.append("Notes:")
            for item in notes:
                val_satang = item.get("value", 0)
                qty        = item.get("qty", 0)
                thb        = val_satang / 100
                subtotal   = thb * qty
                lines.append(f"  ฿{thb:,.0f}  ×{qty}  = ฿{subtotal:,.0f}")

        if coins:
            lines.append("Coins:")
            for item in coins:
                val_satang = item.get("value", 0)
                qty        = item.get("qty", 0)
                thb        = val_satang / 100
                subtotal   = thb * qty
                lines.append(f"  ฿{thb:,.2f}  ×{qty}  = ฿{subtotal:,.2f}")

        if not lines:
            return "—"
        return "\n".join(lines)

    @api.depends("cashin_breakdown_json", "cashout_breakdown_json")
    def _compute_breakdown_summaries(self):
        for rec in self:
            rec.cashin_breakdown_summary  = self._format_breakdown(rec.cashin_breakdown_json)
            rec.cashout_breakdown_summary = self._format_breakdown(rec.cashout_breakdown_json)

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def _parse_breakdown_json(self, json_str):
        """Parse breakdown JSON for QWeb report — returns list of {thb, qty, subtotal}."""
        if not json_str:
            return []
        try:
            data = json.loads(json_str)
        except Exception:
            return []
        rows = []
        for item in (data.get("notes") or []) + (data.get("coins") or []):
            val_satang = item.get("value", 0)
            qty        = item.get("qty", 0)
            thb        = val_satang / 100.0
            if qty > 0:
                rows.append({"thb": thb, "qty": qty, "subtotal": thb * qty})
        return sorted(rows, key=lambda x: -x["thb"])

    @api.model
    def save_exchange(self, vals):
        """Called from JS after successful dispense."""
        staff = self.env["gas.station.staff"].sudo().search(
            [("external_id", "=", vals.get("staff_external_id", ""))], limit=1
        )
        record = self.sudo().create({
            "staff_id":               staff.id if staff else False,
            "staff_external_id":      vals.get("staff_external_id", ""),
            "staff_name":             (staff.nickname or staff.name) if staff else vals.get("staff_name", ""),
            "cashin_amount":          vals.get("cashin_amount", 0),
            "cashout_amount":         vals.get("cashout_amount", 0),
            "cashin_breakdown_json":  json.dumps(vals.get("cashin_breakdown", {}), ensure_ascii=False),
            "cashout_breakdown_json": json.dumps(vals.get("cashout_breakdown", {}), ensure_ascii=False),
            "machine_status":         vals.get("machine_status", "unknown"),
            "machine_response_json":  json.dumps(vals.get("machine_response", {}), ensure_ascii=False),
            "notes":                  vals.get("notes", ""),
        })
        return {"status": "ok", "exchange_id": record.id, "name": record.name}