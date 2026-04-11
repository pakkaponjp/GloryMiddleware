# -*- coding: utf-8 -*-
"""
Manual Cash Collection Record
Tracks collect cash operations triggered directly from Machine Control.
(Separate from Close Shift / End of Day which use gas.station.shift.audit)
"""
from odoo import models, fields, api, _
import json
import logging

_logger = logging.getLogger(__name__)


class GasStationCashCollect(models.Model):
    _name = 'gas.station.cash.collect'
    _description = 'Manual Cash Collection Record'
    _inherit = ['mail.thread']
    _order = 'collect_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
        tracking=True,
    )

    collect_date = fields.Datetime(
        string='Collection Date',
        required=True,
        readonly=True,
        default=fields.Datetime.now,
        tracking=True,
    )

    collect_type = fields.Selection([
        ('all',         'Collect All (No Float)'),
        ('leave_float', 'Collect with Float'),
    ], string='Collection Type', required=True, readonly=True, tracking=True)

    staff_external_id = fields.Char(
        string='Staff ID',
        readonly=True,
        index=True,
        help="Staff external_id from Machine Control session",
    )
    staff_id = fields.Many2one(
        'gas.station.staff',
        string='Staff',
        compute='_compute_staff_id',
        store=True,
        readonly=True,
    )

    collected_amount = fields.Float(
        string='Collected Amount',
        readonly=True,
        tracking=True,
        digits=(16, 2),
        help="Actual cash collected from the machine (THB)",
    )
    reserve_kept = fields.Float(
        string='Reserve (Float) Kept',
        readonly=True,
        digits=(16, 2),
        help="Float amount kept in the machine (THB)",
    )

    collection_breakdown = fields.Text(
        string='Collection Breakdown (JSON)',
        readonly=True,
        help="Denomination breakdown of collected cash (JSON) — consistent with shift_audit.collection_breakdown",
    )
    breakdown_display = fields.Html(
        string='Denomination Breakdown',
        compute='_compute_breakdown_display',
        sanitize=False,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        readonly=True,
        default=lambda self: self.env.company,
    )

    notes = fields.Text(string='Notes')

    # ── Sequence ──────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'gas.station.cash.collect'
                ) or _('New')
        return super().create(vals_list)

    # ── Compute staff record from external_id ─────────────────────────────
    @api.depends('staff_external_id')
    def _compute_staff_id(self):
        Staff = self.env['gas.station.staff'].sudo()
        for rec in self:
            if rec.staff_external_id:
                staff = Staff.search(
                    [('external_id', '=', rec.staff_external_id)], limit=1
                )
                rec.staff_id = staff.id if staff else False
            else:
                rec.staff_id = False

    def _parse_collection_breakdown(self):
        """Parse collection_breakdown JSON for QWeb report."""
        if not self.collection_breakdown:
            return {}
        try:
            bd = json.loads(self.collection_breakdown)
            notes = sorted(bd.get('notes') or [], key=lambda x: x.get('value', 0), reverse=True)
            coins = sorted(bd.get('coins') or [], key=lambda x: x.get('value', 0), reverse=True)
            return {'notes': notes, 'coins': coins}
        except Exception:
            return {}

    # ── Human-readable breakdown ───────────────────────────────────────────
    @api.depends('collection_breakdown')
    def _compute_breakdown_display(self):
        for rec in self:
            if not rec.collection_breakdown:
                rec.breakdown_display = '<em>No data</em>'
                continue
            try:
                bd = json.loads(rec.collection_breakdown)
                notes = bd.get('notes', [])
                coins = bd.get('coins', [])
                rows = []
                for n in sorted(notes, key=lambda x: x.get('value', 0), reverse=True):
                    fv  = n.get('value', 0)
                    qty = n.get('qty', 0)
                    rows.append(
                        f'<tr><td>&#3647;{int(fv/100):,}</td>'
                        f'<td style="text-align:right">x{qty}</td>'
                        f'<td style="text-align:right">{fv*qty/100:,.2f}</td></tr>'
                    )
                for c in sorted(coins, key=lambda x: x.get('value', 0), reverse=True):
                    fv  = c.get('value', 0)
                    qty = c.get('qty', 0)
                    rows.append(
                        f'<tr><td>&#3647;{fv/100:g}</td>'
                        f'<td style="text-align:right">x{qty}</td>'
                        f'<td style="text-align:right">{fv*qty/100:,.2f}</td></tr>'
                    )
                if rows:
                    rec.breakdown_display = (
                        '<table style="width:100%;border-collapse:collapse">'
                        '<tr><th>Denomination</th>'
                        '<th style="text-align:right">Qty</th>'
                        '<th style="text-align:right">Total (THB)</th></tr>'
                        + ''.join(rows) + '</table>'
                    )
                else:
                    rec.breakdown_display = '<em>No denominations</em>'
            except Exception:
                rec.breakdown_display = f'<pre>{rec.collection_breakdown}</pre>'