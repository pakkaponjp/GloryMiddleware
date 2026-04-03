from odoo import models, fields, api, _

# =============================================================================
# GAS STATION CASH REPLENISH
# =============================================================================

class GasStationCashReplenishLine(models.Model):
    _name = 'gas.station.cash.replenish.line'
    _description = 'Replenish Cash Line — denomination breakdown'

    replenish_id = fields.Many2one(
        'gas.station.cash.replenish',
        string='Replenish',
        required=True,
        ondelete='cascade',
        index=True,
    )
    currency_denomination = fields.Float(
        string='Denomination (THB)',
        required=True,
    )
    quantity = fields.Integer(string='Quantity', default=0)
    subtotal = fields.Monetary(
        string='Subtotal',
        currency_field='currency_id',
        compute='_compute_subtotal',
        store=True,
    )
    currency_id = fields.Many2one(
        related='replenish_id.currency_id',
        store=True,
    )

    @api.depends('currency_denomination', 'quantity')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.currency_denomination * rec.quantity


class GasStationCashReplenish(models.Model):
    _name = 'gas.station.cash.replenish'
    _description = 'Cash Replenish — เติมเงินเข้าเครื่อง Glory'
    _order = 'replenish_date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('gas.station.cash.replenish') or 'RPL-NEW',
        copy=False,
    )
    replenish_date = fields.Datetime(
        string='Replenish Date',
        default=fields.Datetime.now,
        required=True,
    )
    staff_id = fields.Many2one(
        'gas.station.staff',
        string='Staff',
        index=True,
    )
    mode = fields.Selection([
        ('set', 'Initial Set'),
        ('top_up', 'Top Up'),
    ], string='Mode', default='set', required=True,
       help="set = first replenishment, top_up = additional replenishment")
    state = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='confirmed', required=True)
    notes = fields.Text(string='Notes')

    replenish_line_ids = fields.One2many(
        'gas.station.cash.replenish.line',
        'replenish_id',
        string='Denomination Lines',
    )
    total_amount = fields.Monetary(
        string='Total Amount',
        currency_field='currency_id',
        compute='_compute_total_amount',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    # Link to shift audit
    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        index=True,
        ondelete='set null',
    )
    audit_shift_number = fields.Integer(
        string='Shift #',
        related='audit_id.shift_number',
        store=True,
    )

    @api.depends('replenish_line_ids.subtotal')
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.replenish_line_ids.mapped('subtotal'))   