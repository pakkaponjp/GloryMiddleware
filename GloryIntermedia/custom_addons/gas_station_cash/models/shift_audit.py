# -*- coding: utf-8 -*-
"""
Shift Audit Model - สำหรับบันทึก Close Shift และ End of Day

รวม Close Shift และ End-of-Day ไว้ใน model เดียว:
- Close Shift = ปิดกะปกติ (Shift #1, #2, #3, ...)
- End of Day  = Shift สุดท้ายของวัน (is_last_shift=True)

Audit Lines แบบ Unified:
- pos_data      : ข้อมูลจาก POS (FlowCo per-staff / FirstPro N/A)
- cash_deposit  : Cash Deposit ที่เกิดใน shift นี้
- cash_withdrawal: Cash Withdrawal ที่เกิดใน shift นี้
- cash_exchange : Cash Exchange ที่เกิดใน shift นี้
"""
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta
import json
import logging

_logger = logging.getLogger(__name__)


class GasStationShiftAudit(models.Model):
    _name = 'gas.station.shift.audit'
    _description = 'Gas Station Shift Audit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'close_time desc, id desc'
    _rec_name = 'name'

    # =====================================================================
    # BASIC FIELDS
    # =====================================================================
    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('reconciled', 'Reconciled'),
        ('discrepancy', 'Discrepancy'),
    ], string='Status', default='draft', tracking=True, readonly=True)

    # =====================================================================
    # SHIFT TYPE & SEQUENCE
    # =====================================================================
    audit_type = fields.Selection([
        ('close_shift', 'Close Shift'),
        ('end_of_day', 'End of Day'),
    ], string='Audit Type', default='close_shift', required=True, tracking=True, readonly=True)

    is_last_shift = fields.Boolean(
        string='Last Shift (EOD)',
        default=False,
        readonly=True,
        help="ถ้า True = เป็น shift สุดท้ายของวัน (End of Day)"
    )

    shift_number = fields.Integer(
        string='Shift Number',
        default=1,
        readonly=True,
        help="ลำดับ shift ในรอบ EOD (1, 2, 3, ... reset หลัง EOD)"
    )

    previous_eod_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Previous EOD',
        readonly=True,
        help="อ้างอิงถึง End of Day ก่อนหน้า"
    )

    # =====================================================================
    # POS VENDOR
    # =====================================================================
    pos_vendor = fields.Selection([
        ('firstpro', 'FirstPro'),
        ('flowco', 'FlowCo'),
    ], string='POS Vendor', readonly=True, index=True,
        help="ระบบ POS ที่ส่ง command นี้มา"
    )

    # =====================================================================
    # STAFF & TERMINAL INFO
    # =====================================================================
    staff_id = fields.Many2one(
        'res.users',
        string='Staff (Odoo User)',
        readonly=True,
    )
    staff_external_id = fields.Char(
        string='Staff ID (External)',
        index=True,
        readonly=True,
        help="Staff ID จาก POS/Glory"
    )
    staff_name = fields.Char(
        string='Staff Name',
        readonly=True,
    )

    pos_terminal_id = fields.Char(
        string='POS Terminal ID',
        index=True,
        readonly=True
    )
    pos_shift_id = fields.Char(
        string='POS Shift ID',
        index=True,
        readonly=True,
    )

    # =====================================================================
    # TIME PERIOD
    # =====================================================================
    shift_start_time = fields.Datetime(
        string='Shift Start Time',
        readonly=True,
    )
    close_time = fields.Datetime(
        string='Close Time',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
        readonly=True
    )

    period_start = fields.Datetime(
        string='Period Start',
        compute='_compute_period',
        store=True,
    )
    period_end = fields.Datetime(
        string='Period End',
        compute='_compute_period',
        store=True,
    )

    # =====================================================================
    # POS TOTALS (ยอดที่ส่งไป POS - เฉพาะ shift นี้)
    # =====================================================================
    pos_oil_total = fields.Monetary(
        string='POS Oil Total',
        currency_field='currency_id',
        readonly=True,
    )
    pos_engine_oil_total = fields.Monetary(
        string='POS Engine Oil Total',
        currency_field='currency_id',
        readonly=True
    )
    pos_other_total = fields.Monetary(
        string='POS Other Total',
        currency_field='currency_id',
        readonly=True
    )
    pos_total_amount = fields.Monetary(
        string='POS Total Amount',
        compute='_compute_pos_totals',
        store=True,
        currency_field='currency_id'
    )
    pos_transaction_count = fields.Integer(
        string='POS Transaction Count',
        readonly=True
    )

    # POS Reconciliation
    pos_reported_total = fields.Monetary(
        string='POS Reported Total',
        currency_field='currency_id',
        readonly=True,
    )
    pos_difference = fields.Monetary(
        string='POS Difference',
        compute='_compute_pos_difference',
        store=True,
        currency_field='currency_id'
    )

    # =====================================================================
    # POS PRODUCT AMOUNT RECONCILIATION
    # =====================================================================
    pos_product_amount = fields.Monetary(
        string='POS Product Amount',
        currency_field='currency_id',
        readonly=True,
        help="ยอดขายสินค้าที่ POS ส่งมาตอน CloseShift/EndOfDay"
    )
    glory_collected_amount = fields.Monetary(
        string='Glory Collected Amount',
        currency_field='currency_id',
        readonly=True,
        help="ยอดเงินที่ Glory เก็บได้ใน shift นี้ (sum of deposits)"
    )
    cash_difference = fields.Monetary(
        string='Cash Difference',
        compute='_compute_cash_difference',
        store=True,
        currency_field='currency_id',
        help="ส่วนต่างระหว่างยอด POS กับยอด Glory (Glory - POS)"
    )
    cash_difference_percent = fields.Float(
        string='Difference %',
        compute='_compute_cash_difference',
        store=True,
        digits=(5, 2),
    )
    reconciliation_status = fields.Selection([
        ('pending', 'Pending'),
        ('matched', 'Matched'),
        ('over', 'Over'),
        ('short', 'Short'),
    ], string='Reconciliation Status',
        compute='_compute_cash_difference',
        store=True,
    )

    # =====================================================================
    # DEPOSIT TOTALS BY TYPE (ยอดทั้งหมดใน shift นี้)
    # =====================================================================
    total_oil = fields.Monetary(string='Total Oil', currency_field='currency_id', readonly=True)
    total_engine_oil = fields.Monetary(string='Total Engine Oil', currency_field='currency_id', readonly=True)
    total_coffee_shop = fields.Monetary(string='Total Coffee Shop', currency_field='currency_id', readonly=True)
    total_convenient_store = fields.Monetary(string='Total Convenient Store', currency_field='currency_id', readonly=True)
    total_rental = fields.Monetary(string='Total Rental', currency_field='currency_id', readonly=True)
    total_deposit_cash = fields.Monetary(string='Total Deposit Cash', currency_field='currency_id', readonly=True)
    total_exchange_cash = fields.Monetary(string='Total Exchange Cash', currency_field='currency_id', readonly=True)
    total_other = fields.Monetary(string='Total Other', currency_field='currency_id', readonly=True)
    total_all_deposits = fields.Monetary(string='Total All Deposits', currency_field='currency_id', readonly=True)
    total_replenish = fields.Monetary(string='Total Replenish Cash', currency_field='currency_id', readonly=True)

    # =====================================================================
    # EOD CUMULATIVE TOTALS (ยอดรวมตั้งแต่ EOD ก่อนหน้า)
    # =====================================================================
    eod_total_oil = fields.Monetary(string='EOD Total Oil', currency_field='currency_id', readonly=True)
    eod_total_engine_oil = fields.Monetary(string='EOD Total Engine Oil', currency_field='currency_id', readonly=True)
    eod_total_coffee_shop = fields.Monetary(string='EOD Total Coffee Shop', currency_field='currency_id', readonly=True)
    eod_total_convenient_store = fields.Monetary(string='EOD Total Convenient Store', currency_field='currency_id', readonly=True)
    eod_total_rental = fields.Monetary(string='EOD Total Rental', currency_field='currency_id', readonly=True)
    eod_total_deposit_cash = fields.Monetary(string='EOD Total Deposit Cash', currency_field='currency_id', readonly=True)
    eod_total_exchange_cash = fields.Monetary(string='EOD Total Exchange Cash', currency_field='currency_id', readonly=True)
    eod_total_other = fields.Monetary(string='EOD Total Other', currency_field='currency_id', readonly=True)
    eod_grand_total = fields.Monetary(string='EOD Grand Total', currency_field='currency_id', readonly=True)
    eod_pos_total = fields.Monetary(string='EOD POS Total', currency_field='currency_id', readonly=True)
    eod_total_replenish = fields.Monetary(string='EOD Total Replenish Cash', currency_field='currency_id', readonly=True)

    # =====================================================================
    # COLLECTION BOX (End of Day)
    # =====================================================================
    collected_amount = fields.Monetary(
        string='Collected Amount',
        currency_field='currency_id',
        readonly=True,
        help="จำนวนเงินที่เก็บจาก Collection Box"
    )
    reserve_kept = fields.Monetary(
        string='Reserve Kept',
        currency_field='currency_id',
        readonly=True,
        help="เงินสำรองที่เก็บไว้ในตู้"
    )
    float_amount = fields.Float(
        string='Float / Reserve',
        digits=(16, 2),
        readonly=True,
        help="Actual cash ที่เหลือจริงในเครื่องหลังปิดกะ (snapshot จาก Glory)"
    )
    float_target = fields.Float(
        string='Float Target',
        digits=(16, 2),
        readonly=True,
        help="Target float ที่ตั้งไว้ใน Settings ณ เวลาปิดกะ"
    )
    float_difference = fields.Monetary(
        string='Float Difference',
        currency_field='currency_id',
        compute='_compute_float_difference',
        store=True,
        help="Actual float − Target float (ปกติ = 0, ติดลบเมื่อเงินสำรองไม่พอ)"
    )
    collection_expected = fields.Monetary(
        string='Collection Expected',
        compute='_compute_collection',
        store=True,
        currency_field='currency_id'
    )
    collection_difference = fields.Monetary(
        string='Collection Difference',
        compute='_compute_collection',
        store=True,
        currency_field='currency_id'
    )
    collection_breakdown = fields.Text(
        string='Collection Breakdown',
        readonly=True,
        help="รายละเอียดธนบัตร/เหรียญ (JSON)"
    )

    # =====================================================================
    # COMPUTED FIELDS — cash flow & vendor-aware reconciliation
    # =====================================================================

    total_withdrawals = fields.Monetary(
        string='Total Withdrawals',
        currency_field='currency_id',
        compute='_compute_withdrawal_totals',
        store=True,
        help='Sum of all withdrawal audit lines in this shift',
    )
    shift_net_total = fields.Monetary(
        string='Shift Total (Net)',
        currency_field='currency_id',
        compute='_compute_withdrawal_totals',
        store=True,
        help='Total Deposits − Total Withdrawals',
    )

    total_exchange_cashout = fields.Monetary(
        string='Total Exchange Cash-Out',
        currency_field='currency_id',
        compute='_compute_exchange_totals',
        store=True,
        help='Sum of cashout_amount from all exchange lines in this shift',
    )

    pos_reported_sale_total = fields.Monetary(
        string='POS Reported Sale Total',
        currency_field='currency_id',
        compute='_compute_pos_reported_sale',
        store=True,
        help='FlowCo: sum(saleamt_fuel + saleamt_lube) from pos_data lines\n'
             'FirstPro: firstpro_product_amount from pos_data line',
    )

    recon_difference = fields.Monetary(
        string='Recon Difference',
        currency_field='currency_id',
        compute='_compute_recon_difference',
        store=True,
        help='FlowCo: (Odoo oil + engine_oil) − (POS saleamt_fuel + saleamt_lube)\n'
             'FirstPro: Odoo engine_oil − product_amount  '
             '(fuel is N/A from FirstPro — considered reconciled)',
    )

    staff_summary = fields.Char(
        string='Amount by Staff',
        compute='_compute_staff_summary',
        store=False,
        help='Quick text summary of deposit/withdrawal totals per staff',
    )

    # =====================================================================
    # AUDIT LINES (Unified)
    # =====================================================================
    audit_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='Audit Lines',
        readonly=True,
    )

    # Filtered views per type (for UI tabs)
    pos_data_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='POS Staff Lines',
        readonly=True,
        domain=[('line_type', '=', 'pos_data')],
    )
    cash_deposit_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='Deposit Lines',
        readonly=True,
        domain=[('line_type', '=', 'cash_deposit')],
    )
    cash_withdrawal_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='Withdrawal Lines',
        readonly=True,
        domain=[('line_type', '=', 'cash_withdrawal')],
    )
    cash_exchange_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='Exchange Lines',
        readonly=True,
        domain=[('line_type', '=', 'cash_exchange')],
    )
    cash_replenish_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='Replenish Lines',
        readonly=True,
        domain=[('line_type', '=', 'cash_replenish')],
    )

    # =====================================================================
    # RELATED DEPOSITS (legacy link - kept for backward compatibility)
    # =====================================================================
    deposit_ids = fields.One2many(
        'gas.station.cash.deposit',
        'audit_id',
        string='Related Deposits',
        readonly=True
    )
    total_deposit_count = fields.Integer(
        string='Deposit Count',
        compute='_compute_deposit_count',
        store=True
    )

    # Shifts in this EOD period
    shift_audit_ids = fields.One2many(
        'gas.station.shift.audit',
        'parent_eod_id',
        string='Shifts in Period',
        readonly=True,
    )
    parent_eod_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Parent EOD',
        readonly=True,
    )
    shift_count_in_period = fields.Integer(
        string='Shifts in Period',
        compute='_compute_shift_count',
        store=True
    )

    # =====================================================================
    # FLOWCO RAW DATA  (populated only when pos_vendor = flowco)
    # =====================================================================
    flowco_shift_number = fields.Char(string='FlowCo Shift Number', readonly=True)
    flowco_pos_id = fields.Integer(string='FlowCo POS ID', readonly=True)
    flowco_timestamp = fields.Datetime(string='FlowCo Timestamp', readonly=True)
    pos_data_raw = fields.Text(string='POS Data (Raw JSON)', readonly=True,
        help="raw JSON ของ data[] จาก FlowCo — ใช้สำหรับ debug/audit trail")

    # =====================================================================
    # NOTES & METADATA
    # =====================================================================
    notes = fields.Text(string='Notes')
    reconciliation_notes = fields.Text(string='Reconciliation Notes')

    currency_id = fields.Many2one(
        'res.currency', string='Currency', readonly=True,
        default=lambda self: self.env.company.currency_id
    )
    company_id = fields.Many2one(
        'res.company', string='Company', readonly=True,
        default=lambda self: self.env.company
    )

    # =====================================================================
    # COMPUTED METHODS
    # =====================================================================

    @api.depends('previous_eod_id', 'close_time', 'shift_start_time', 'audit_type')
    def _compute_period(self):
        for record in self:
            record.period_end = record.close_time
            if record.audit_type == 'end_of_day':
                if record.previous_eod_id:
                    record.period_start = record.previous_eod_id.close_time
                else:
                    record.period_start = record.shift_start_time or (
                        record.close_time - timedelta(days=7) if record.close_time else False
                    )
            else:
                record.period_start = record.shift_start_time

    @api.depends('pos_oil_total', 'pos_engine_oil_total', 'pos_other_total')
    def _compute_pos_totals(self):
        for record in self:
            record.pos_total_amount = (
                (record.pos_oil_total or 0) +
                (record.pos_engine_oil_total or 0) +
                (record.pos_other_total or 0)
            )

    @api.depends('pos_total_amount', 'pos_reported_total')
    def _compute_pos_difference(self):
        for record in self:
            record.pos_difference = (
                record.pos_total_amount - (record.pos_reported_total or 0)
                if record.pos_reported_total else 0
            )

    @api.depends('eod_grand_total', 'collected_amount', 'reserve_kept', 'audit_type')
    def _compute_collection(self):
        for record in self:
            if record.audit_type == 'end_of_day':
                record.collection_expected = record.eod_grand_total
                record.collection_difference = (
                    (record.collected_amount or 0) +
                    (record.reserve_kept or 0) -
                    (record.eod_grand_total or 0)
                )
            else:
                record.collection_expected = 0
                record.collection_difference = 0

    @api.depends('float_amount', 'float_target')
    def _compute_float_difference(self):
        for rec in self:
            if not rec.float_target:
                rec.float_difference = 0.0
            else:
                rec.float_difference = (rec.float_amount or 0) - (rec.float_target or 0)

    @api.depends('deposit_ids')
    def _compute_deposit_count(self):
        for record in self:
            record.total_deposit_count = len(record.deposit_ids)

    @api.depends('pos_product_amount', 'glory_collected_amount', 'total_all_deposits')
    def _compute_cash_difference(self):
        TOLERANCE = 0.01
        for record in self:
            pos_amount = record.pos_product_amount or 0.0
            glory_amount = record.glory_collected_amount or record.total_all_deposits or 0.0
            difference = glory_amount - pos_amount
            record.cash_difference = difference
            record.cash_difference_percent = (
                (difference / pos_amount) * 100 if pos_amount > 0 else 0.0
            )
            # reconciliation_status is set by _compute_recon_difference (vendor-aware)
            # do not set it here

    @api.depends('audit_line_ids.amount', 'audit_line_ids.line_type')
    def _compute_withdrawal_totals(self):
        for rec in self:
            wth_lines = rec.audit_line_ids.filtered(
                lambda l: l.line_type == 'cash_withdrawal'
            )
            rec.total_withdrawals = sum(wth_lines.mapped('amount'))
            rec.shift_net_total = (rec.total_all_deposits or 0) - rec.total_withdrawals

    @api.depends('audit_line_ids.amount', 'audit_line_ids.line_type')
    def _compute_exchange_totals(self):
        for rec in self:
            exc_lines = rec.audit_line_ids.filtered(
                lambda l: l.line_type == 'cash_exchange'
            )
            rec.total_exchange_cashout = sum(exc_lines.mapped('amount'))

    @api.depends(
        'audit_line_ids.line_type',
        'audit_line_ids.pos_source',
        'audit_line_ids.saleamt_fuel',
        'audit_line_ids.saleamt_lube',
        'audit_line_ids.firstpro_product_amount',
        'pos_vendor',
    )
    def _compute_pos_reported_sale(self):
        for rec in self:
            pos_lines = rec.audit_line_ids.filtered(
                lambda l: l.line_type == 'pos_data'
            )
            if rec.pos_vendor == 'flowco':
                rec.pos_reported_sale_total = sum(
                    (l.saleamt_fuel or 0) + (l.saleamt_lube or 0)
                    for l in pos_lines
                )
            else:
                # FirstPro: product_amount = engine oil only
                rec.pos_reported_sale_total = sum(
                    l.firstpro_product_amount or 0 for l in pos_lines
                )

    @api.depends(
        'total_oil', 'total_engine_oil',
        'pos_reported_sale_total', 'pos_vendor',
    )
    def _compute_recon_difference(self):
        """
        Vendor-aware reconciliation difference.

        FlowCo  : (Odoo oil + Odoo engine_oil) − (POS saleamt_fuel + saleamt_lube)
                  Positive = Odoo collected more than POS reported (Over)
                  Negative = Odoo collected less than POS reported (Short)

        FirstPro: Odoo engine_oil − POS product_amount
                  Fuel is not sent by FirstPro → treated as reconciled (no diff)
        """
        TOLERANCE = 0.01
        for rec in self:
            if rec.pos_vendor == 'flowco':
                odoo_total = (rec.total_oil or 0) + (rec.total_engine_oil or 0)
            else:
                # FirstPro: compare engine oil only
                odoo_total = rec.total_engine_oil or 0

            diff = odoo_total - (rec.pos_reported_sale_total or 0)
            rec.recon_difference = diff

            # Also update reconciliation_status based on recon_difference
            # (override the old cash_difference-based status)
            pos_amt = rec.pos_reported_sale_total or 0
            if pos_amt == 0 and odoo_total == 0:
                rec.reconciliation_status = 'pending'
            elif abs(diff) <= TOLERANCE:
                rec.reconciliation_status = 'matched'
            elif diff > TOLERANCE:
                rec.reconciliation_status = 'over'
            else:
                rec.reconciliation_status = 'short'

    def _compute_staff_summary(self):
        """
        Build a short text summary of deposit/withdrawal amounts per staff.
        Example: "7B8U: dep 700 / wth 200  |  4401: dep 500"
        """
        for rec in self:
            staff_data = {}

            for line in rec.audit_line_ids:
                staff_key = None

                if line.line_type == 'pos_data':
                    staff_key = line.staff_external_id or '—'
                elif line.line_type == 'cash_deposit' and line.deposit_id:
                    staff_key = (
                        line.deposit_id.staff_id.name
                        or line.deposit_id.staff_id.employee_id
                        or '—'
                    )
                elif line.line_type == 'cash_withdrawal' and line.withdrawal_id:
                    staff_key = (
                        line.withdrawal_id.staff_id.name
                        or line.withdrawal_id.staff_id.employee_id
                        or '—'
                    )
                else:
                    continue

                if staff_key not in staff_data:
                    staff_data[staff_key] = {'dep': 0.0, 'wth': 0.0}

                if line.line_type == 'cash_deposit':
                    staff_data[staff_key]['dep'] += line.amount or 0
                elif line.line_type == 'cash_withdrawal':
                    staff_data[staff_key]['wth'] += line.amount or 0

            if not staff_data:
                rec.staff_summary = ''
                continue

            parts = []
            for staff, totals in staff_data.items():
                dep = totals['dep']
                wth = totals['wth']
                if wth:
                    parts.append(f"{staff}: dep {dep:,.0f} / wth {wth:,.0f}")
                else:
                    parts.append(f"{staff}: dep {dep:,.0f}")

            rec.staff_summary = '  |  '.join(parts)

    @api.depends('shift_audit_ids')
    def _compute_shift_count(self):
        for record in self:
            record.shift_count_in_period = len(record.shift_audit_ids)

    # =====================================================================
    # CRUD METHODS
    # =====================================================================

    def _generate_reference(self, audit_type, shift_number, close_time):
        if not close_time:
            close_time = fields.Datetime.now()
        # Convert UTC to local +7
        from datetime import timedelta
        close_local = close_time + timedelta(hours=7)
        dt_str = close_local.strftime('%y%m%d%H%M')
        return f"EOD-{dt_str}" if audit_type == 'end_of_day' else f"SHIFT-{dt_str}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('shift_number'):
                vals['shift_number'] = self._get_next_shift_number()
            if vals.get('name', _('New')) == _('New'):
                audit_type = vals.get('audit_type', 'close_shift')
                if vals.get('is_last_shift'):
                    audit_type = 'end_of_day'
                close_time = vals.get('close_time') or fields.Datetime.now()
                if isinstance(close_time, str):
                    close_time = fields.Datetime.from_string(close_time)
                vals['name'] = self._generate_reference(audit_type, vals['shift_number'], close_time)
            if not vals.get('previous_eod_id'):
                vals['previous_eod_id'] = self._get_previous_eod_id()

        records = super().create(vals_list)
        for record in records:
            if record.audit_type == 'end_of_day':
                record._link_shifts_to_eod()
        return records

    def _get_next_shift_number(self):
        previous_eod = self._get_previous_eod()
        if previous_eod:
            return self.search_count([
                ('close_time', '>', previous_eod.close_time),
                ('audit_type', '=', 'close_shift'),
                ('id', '!=', self.id if self.id else 0),
            ]) + 1
        return self.search_count([('audit_type', '=', 'close_shift')]) + 1

    def _get_previous_eod(self):
        return self.search([('audit_type', '=', 'end_of_day')], order='close_time desc', limit=1)

    def _get_previous_eod_id(self):
        previous_eod = self._get_previous_eod()
        return previous_eod.id if previous_eod else False

    def _link_shifts_to_eod(self):
        self.ensure_one()
        if self.audit_type != 'end_of_day':
            return
        domain = [
            ('audit_type', '=', 'close_shift'),
            ('close_time', '<=', self.close_time),
            ('parent_eod_id', '=', False),
        ]
        if self.previous_eod_id:
            domain.append(('close_time', '>', self.previous_eod_id.close_time))
        self.search(domain).write({'parent_eod_id': self.id})

    # =====================================================================
    # ACTION METHODS
    # =====================================================================

    def action_confirm(self):
        for record in self:
            if record.state != 'draft':
                raise UserError(_('Only draft audits can be confirmed.'))
            record.state = 'confirmed'

    def action_reconcile(self):
        for record in self:
            if record.state != 'confirmed':
                raise UserError(_('Only confirmed audits can be reconciled.'))
            if record.audit_type == 'end_of_day' and abs(record.collection_difference) > 0.01:
                record.state = 'discrepancy'
            elif abs(record.pos_difference) > 0.01:
                record.state = 'discrepancy'
            else:
                record.state = 'reconciled'

    def action_reset_draft(self):
        for record in self:
            record.state = 'draft'

    def action_mark_as_eod(self):
        """FlowCo: mark shift ล่าสุดเป็น End of Day"""
        for record in self:
            if record.audit_type != 'close_shift':
                raise UserError(_('Only Close Shift can be marked as End of Day.'))
            record.write({'audit_type': 'end_of_day', 'is_last_shift': True})
            record._link_shifts_to_eod()

    # =====================================================================
    # BUSINESS METHODS — สำหรับ pos_commands.py เรียกใช้
    # =====================================================================

    @api.model
    def create_from_shift_close(self, command, deposits, shift_start=None,
                                 product_amount=None, flowco_data=None,
                                 withdrawals=None, exchanges=None,
                                 current_cash=None, float_target=None,
                                 replenishments=None):
        """
        สร้าง Shift Audit จาก Close Shift command

        Args:
            command         : gas.station.pos_command record หรือ dict-like
            deposits        : recordset gas.station.cash.deposit
            shift_start     : datetime เวลาเริ่ม shift
            product_amount  : float ยอดขายสินค้าจาก POS
            flowco_data     : dict — parsed FlowCo CloseShift payload (optional)
                              keys: shift_number, pos_id, timestamp, data[]
            withdrawals     : recordset gas.station.cash.withdrawal (optional)
            exchanges       : recordset gas.station.cash.exchange (optional)
            current_cash    : float actual cash ที่เหลือจริงในเครื่องจาก Glory
            float_target    : float target float ก่อน update setting (ป้องกัน timing issue)
            replenishments  : recordset gas.station.cash.replenish (optional)

        Returns:
            gas.station.shift.audit record
        """
        _logger.info("=" * 60)
        _logger.info("Creating Shift Audit from CLOSE SHIFT...")

        deposits = deposits or self.env['gas.station.cash.deposit']
        withdrawals = withdrawals or self.env['gas.station.cash.withdrawal']
        exchanges = exchanges or self.env['gas.station.cash.exchange']
        replenishments = replenishments or self.env['gas.station.cash.replenish']

        totals = self._calculate_deposit_totals(deposits)

        # Read vendor from Odoo Settings — single source of truth
        vendor = self.env['ir.config_parameter'].sudo().get_param(
            'gas_station_cash.pos_vendor', 'firstpro'
        )
        _is_flowco = (vendor == 'flowco')

        # Parse command info
        staff_external_id = getattr(command, 'staff_external_id', None) if command else None
        pos_terminal_id = getattr(command, 'pos_terminal_id', None) if command else None
        pos_shift_id = getattr(command, 'pos_shift_id', None) if command else None

        # FlowCo metadata
        flowco_shift_number = None
        flowco_pos_id = 0
        flowco_timestamp = None
        pos_data_raw = None
        pos_staff_lines = []

        if _is_flowco:
            flowco_shift_number = str(flowco_data.get('shift_number', '') or '')
            try:
                flowco_pos_id = int(flowco_data.get('pos_id') or 0)
            except (TypeError, ValueError):
                flowco_pos_id = 0

            ts_raw = flowco_data.get('timestamp')
            if ts_raw:
                try:
                    from dateutil import parser as dtparser
                    import pytz
                    dt = dtparser.parse(ts_raw)
                    if dt.tzinfo:
                        dt = dt.astimezone(pytz.utc).replace(tzinfo=None)
                    flowco_timestamp = dt
                except Exception as ts_err:
                    _logger.warning("Could not parse FlowCo timestamp '%s': %s", ts_raw, ts_err)

            raw_lines = flowco_data.get('data') or []
            if raw_lines:
                pos_data_raw = json.dumps(raw_lines, ensure_ascii=False)
                for row in raw_lines:
                    pos_staff_lines.append({
                        'line_type': 'pos_data',
                        'pos_source': 'flowco',
                        'staff_external_id': str(row.get('staff_id', '') or ''),
                        'saleamt_fuel': float(row.get('saleamt_fuel') or 0),
                        'dropamt_fuel': float(row.get('dropamt_fuel') or 0),
                        'saleamt_lube': float(row.get('saleamt_lube') or 0),
                        'dropamt_lube': float(row.get('dropamt_lube') or 0),
                        'pos_line_status': str(row.get('status', '') or ''),
                    })

        # FirstPro: สร้าง 1 pos_data line แบบ N/A (product_amount เก็บไว้รอข้อมูลเพิ่มเติม)
        elif vendor == 'firstpro':
            firstpro_shiftid = getattr(command, 'pos_shift_id', None) if command else None
            pos_staff_lines.append({
                'line_type': 'pos_data',
                'pos_source': 'firstpro',
                'staff_external_id': staff_external_id or '',
                'firstpro_shiftid': str(firstpro_shiftid or ''),
                'firstpro_product_amount': float(product_amount or 0),
                # FlowCo fields → N/A
                'saleamt_fuel': 0.0,
                'dropamt_fuel': 0.0,
                'saleamt_lube': 0.0,
                'dropamt_lube': 0.0,
                'pos_line_status': 'N/A',
            })

        vals = {
            'audit_type': 'close_shift',
            'is_last_shift': False,
            'shift_start_time': shift_start,
            'close_time': fields.Datetime.now(),
            'pos_vendor': vendor,

            'staff_external_id': staff_external_id,
            'pos_terminal_id': pos_terminal_id,
            'pos_shift_id': pos_shift_id,

            'pos_oil_total': totals['pos_oil'],
            'pos_engine_oil_total': totals['pos_engine_oil'],
            'pos_other_total': totals['pos_other'],
            'pos_transaction_count': totals['pos_count'],

            'pos_product_amount': product_amount or 0.0,
            'glory_collected_amount': totals['total_all'],

            'total_oil': totals['total_oil'],
            'total_engine_oil': totals['total_engine_oil'],
            'total_coffee_shop': totals['total_coffee_shop'],
            'total_convenient_store': totals['total_convenient_store'],
            'total_rental': totals['total_rental'],
            'total_deposit_cash': totals['total_deposit_cash'],
            'total_exchange_cash': totals['total_exchange_cash'],
            'total_other': totals['total_other'],
            'total_all_deposits': totals['total_all'],
            'total_replenish': sum(r.total_amount for r in replenishments) if replenishments else 0.0,

            'flowco_shift_number': flowco_shift_number or False,
            'flowco_pos_id': flowco_pos_id or 0,
            'flowco_timestamp': flowco_timestamp or False,
            'pos_data_raw': pos_data_raw or False,
            'float_target': float(float_target) if float_target is not None else float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'gas_station_cash.float_amount', 0
                ) or 0
            ),
            'float_amount': float(current_cash) if current_cash is not None else 0.0,
        }

        audit = self.create(vals)

        # ── สร้าง Audit Lines ─────────────────────────────────────────────
        AuditLine = self.env['gas.station.shift.audit.line'].sudo()

        # 1. POS data lines (FlowCo per-staff หรือ FirstPro N/A)
        for line_vals in pos_staff_lines:
            line_vals['audit_id'] = audit.id
            AuditLine.create(line_vals)

        # 2. Cash Deposit lines
        for deposit in deposits:
            AuditLine.create({
                'audit_id': audit.id,
                'line_type': 'cash_deposit',
                'deposit_id': deposit.id,
            })

        # 3. Cash Withdrawal lines
        for withdrawal in withdrawals:
            AuditLine.create({
                'audit_id': audit.id,
                'line_type': 'cash_withdrawal',
                'withdrawal_id': withdrawal.id,
            })

        # 4. Cash Exchange lines
        for exchange in exchanges:
            AuditLine.create({
                'audit_id': audit.id,
                'line_type': 'cash_exchange',
                'exchange_id': exchange.id,
            })

        # 5. Replenish Cash lines
        for replenish in replenishments:
            AuditLine.create({
                'audit_id': audit.id,
                'line_type': 'cash_replenish',
                'replenish_id': replenish.id,
            })

        # Link deposits to audit (legacy audit_id field)
        if deposits:
            deposits.write({'audit_id': audit.id})
        if withdrawals:
            withdrawals.write({'audit_id': audit.id})
        if exchanges:
            exchanges.write({'audit_id': audit.id})
        if replenishments:
            replenishments.write({'audit_id': audit.id})

        _logger.info(
            "✅ Created Shift Audit: %s (vendor=%s, shift=%d, pos_lines=%d, "
            "deposits=%d, withdrawals=%d, exchanges=%d)",
            audit.name, vendor, audit.shift_number,
            len(pos_staff_lines), len(deposits), len(withdrawals), len(exchanges)
        )
        _logger.info("=" * 60)
        return audit

    @api.model
    def create_from_end_of_day(self, command, deposits, collection_result=None,
                                shift_start=None, product_amount=None,
                                flowco_data=None, withdrawals=None, exchanges=None,
                                current_cash=None, replenishments=None):
        """
        สร้าง Shift Audit จาก End of Day command (Last Shift)

        FirstPro : สร้าง EOD record ใหม่ (เป็น shift สุดท้ายเลย)
        FlowCo   : ไม่ถูกเรียกตรงนี้ — ใช้ mark_last_shift_as_eod() แทน

        Args:
            command          : gas.station.pos_command record หรือ dict-like
            deposits         : recordset gas.station.cash.deposit
            collection_result: dict ผลลัพธ์จาก collection
            shift_start      : datetime เวลาเริ่ม shift
            product_amount   : float ยอดขายสินค้าจาก POS
            flowco_data      : dict (ไม่ใช้ใน EOD path แต่รับไว้ครบ signature)
            withdrawals      : recordset gas.station.cash.withdrawal
            exchanges        : recordset gas.station.cash.exchange
            replenishments   : recordset gas.station.cash.replenish

        Returns:
            gas.station.shift.audit record
        """
        _logger.info("=" * 60)
        _logger.info("🌙 Creating Shift Audit from END OF DAY (FirstPro)...")

        deposits = deposits or self.env['gas.station.cash.deposit']
        withdrawals = withdrawals or self.env['gas.station.cash.withdrawal']
        exchanges = exchanges or self.env['gas.station.cash.exchange']
        replenishments = replenishments or self.env['gas.station.cash.replenish']
        collection_result = collection_result or {}

        totals = self._calculate_deposit_totals(deposits)
        eod_totals = self._calculate_eod_totals(totals)

        staff_external_id = getattr(command, 'staff_external_id', None) if command else None
        pos_terminal_id = getattr(command, 'pos_terminal_id', None) if command else None
        pos_shift_id = getattr(command, 'pos_shift_id', None) if command else None

        vals = {
            'audit_type': 'end_of_day',
            'is_last_shift': True,
            'shift_start_time': shift_start,
            'close_time': fields.Datetime.now(),
            'pos_vendor': self.env['ir.config_parameter'].sudo().get_param(
                'gas_station_cash.pos_vendor', 'firstpro'
            ),

            'staff_external_id': staff_external_id,
            'pos_terminal_id': pos_terminal_id,
            'pos_shift_id': pos_shift_id,

            'pos_oil_total': totals['pos_oil'],
            'pos_engine_oil_total': totals['pos_engine_oil'],
            'pos_other_total': totals['pos_other'],
            'pos_transaction_count': totals['pos_count'],

            'pos_product_amount': product_amount or 0.0,
            'glory_collected_amount': totals['total_all'],

            'total_oil': totals['total_oil'],
            'total_engine_oil': totals['total_engine_oil'],
            'total_coffee_shop': totals['total_coffee_shop'],
            'total_convenient_store': totals['total_convenient_store'],
            'total_rental': totals['total_rental'],
            'total_deposit_cash': totals['total_deposit_cash'],
            'total_exchange_cash': totals['total_exchange_cash'],
            'total_other': totals['total_other'],
            'total_all_deposits': totals['total_all'],
            'total_replenish': sum(r.total_amount for r in replenishments) if replenishments else 0.0,

            'eod_total_oil': eod_totals['oil'],
            'eod_total_engine_oil': eod_totals['engine_oil'],
            'eod_total_coffee_shop': eod_totals['coffee_shop'],
            'eod_total_convenient_store': eod_totals['convenient_store'],
            'eod_total_rental': eod_totals['rental'],
            'eod_total_deposit_cash': eod_totals['deposit_cash'],
            'eod_total_exchange_cash': eod_totals['exchange_cash'],
            'eod_total_other': eod_totals['other'],
            'eod_grand_total': eod_totals['grand_total'],
            'eod_pos_total': eod_totals['pos_total'],
            'eod_total_replenish': eod_totals.get('replenish', 0.0),

            'collected_amount': collection_result.get('collected_amount', 0.0),
            'reserve_kept': collection_result.get('reserve_kept', 0.0),
            'collection_breakdown': json.dumps(
                collection_result.get('collected_breakdown', {}),
                ensure_ascii=False
            ) if collection_result.get('collected_breakdown') else None,
            'float_target': float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'gas_station_cash.float_amount', 0
                ) or 0
            ),
            'float_amount': float(current_cash) if current_cash is not None else 0.0,
        }

        audit = self.create(vals)

        # ── สร้าง Audit Lines ─────────────────────────────────────────────
        AuditLine = self.env['gas.station.shift.audit.line'].sudo()

        # FirstPro EOD: 1 pos_data line แบบ N/A
        firstpro_shiftid = getattr(command, 'pos_shift_id', None) if command else None
        AuditLine.create({
            'audit_id': audit.id,
            'line_type': 'pos_data',
            'pos_source': 'firstpro',
            'staff_external_id': staff_external_id or '',
            'firstpro_shiftid': str(firstpro_shiftid or ''),
            'firstpro_product_amount': float(product_amount or 0),
            'saleamt_fuel': 0.0,
            'dropamt_fuel': 0.0,
            'saleamt_lube': 0.0,
            'dropamt_lube': 0.0,
            'pos_line_status': 'N/A',
        })

        # Cash Deposit lines
        for deposit in deposits:
            AuditLine.create({'audit_id': audit.id, 'line_type': 'cash_deposit', 'deposit_id': deposit.id})

        # Cash Withdrawal lines
        for withdrawal in withdrawals:
            AuditLine.create({'audit_id': audit.id, 'line_type': 'cash_withdrawal', 'withdrawal_id': withdrawal.id})

        # Cash Exchange lines
        for exchange in exchanges:
            AuditLine.create({'audit_id': audit.id, 'line_type': 'cash_exchange', 'exchange_id': exchange.id})

        # Replenish Cash lines
        for replenish in replenishments:
            AuditLine.create({'audit_id': audit.id, 'line_type': 'cash_replenish', 'replenish_id': replenish.id})

        # Link legacy audit_id fields
        if deposits:
            deposits.write({'audit_id': audit.id})
        if withdrawals:
            withdrawals.write({'audit_id': audit.id})
        if exchanges:
            exchanges.write({'audit_id': audit.id})
        if replenishments:
            replenishments.write({'audit_id': audit.id})

        _logger.info(
            "🌙 ✅ Created EOD Audit: %s (product_amount=%.2f, glory=%.2f, "
            "collected=%.2f, deposits=%d, withdrawals=%d, exchanges=%d)",
            audit.name,
            product_amount or 0,
            totals['total_all'],
            collection_result.get('collected_amount', 0),
            len(deposits), len(withdrawals), len(exchanges)
        )
        _logger.info("=" * 60)
        return audit

    @api.model
    def mark_last_shift_as_eod(self, collection_result=None, withdrawals=None, exchanges=None):
        """
        FlowCo EOD path: หา shift ล่าสุด → mark เป็น EOD → generate daily report

        FlowCo ส่ง EndOfDay ด้วย data=[] (empty) หลังจาก CloseShift ครั้งสุดท้าย
        เราจึงไม่สร้าง record ใหม่ แต่แค่ update shift ล่าสุดให้เป็น EOD

        Args:
            collection_result: dict ผลลัพธ์จาก collection (optional)
            withdrawals      : recordset gas.station.cash.withdrawal ใน EOD period
            exchanges        : recordset gas.station.cash.exchange ใน EOD period

        Returns:
            gas.station.shift.audit record ที่ถูก mark เป็น EOD
        """
        _logger.info("=" * 60)
        _logger.info("🌙 [FlowCo] Marking last shift as End of Day...")

        collection_result = collection_result or {}
        withdrawals = withdrawals or self.env['gas.station.cash.withdrawal']
        exchanges = exchanges or self.env['gas.station.cash.exchange']

        # หา shift ล่าสุดที่ยังเป็น close_shift
        last_shift = self.search([
            ('audit_type', '=', 'close_shift'),
            ('is_last_shift', '=', False),
        ], order='close_time desc', limit=1)

        if not last_shift:
            raise UserError(_('No close_shift record found to mark as End of Day.'))

        # คำนวณ EOD totals รวม shifts ก่อนหน้า
        current_totals = {
            'pos_oil': last_shift.pos_oil_total or 0,
            'pos_engine_oil': last_shift.pos_engine_oil_total or 0,
            'pos_other': last_shift.pos_other_total or 0,
            'pos_count': last_shift.pos_transaction_count or 0,
            'total_oil': last_shift.total_oil or 0,
            'total_engine_oil': last_shift.total_engine_oil or 0,
            'total_coffee_shop': last_shift.total_coffee_shop or 0,
            'total_convenient_store': last_shift.total_convenient_store or 0,
            'total_rental': last_shift.total_rental or 0,
            'total_deposit_cash': last_shift.total_deposit_cash or 0,
            'total_exchange_cash': last_shift.total_exchange_cash or 0,
            'total_other': last_shift.total_other or 0,
            'total_all': last_shift.total_all_deposits or 0,
        }
        eod_totals = self._calculate_eod_totals(current_totals)

        last_shift.write({
            'audit_type': 'end_of_day',
            'is_last_shift': True,
            'pos_vendor': self.env['ir.config_parameter'].sudo().get_param(
                'gas_station_cash.pos_vendor', 'firstpro'
            ),

            'eod_total_oil': eod_totals['oil'],
            'eod_total_engine_oil': eod_totals['engine_oil'],
            'eod_total_coffee_shop': eod_totals['coffee_shop'],
            'eod_total_convenient_store': eod_totals['convenient_store'],
            'eod_total_rental': eod_totals['rental'],
            'eod_total_deposit_cash': eod_totals['deposit_cash'],
            'eod_total_exchange_cash': eod_totals['exchange_cash'],
            'eod_total_other': eod_totals['other'],
            'eod_grand_total': eod_totals['grand_total'],
            'eod_pos_total': eod_totals['pos_total'],

            'collected_amount': collection_result.get('collected_amount', 0.0),
            'reserve_kept': collection_result.get('reserve_kept', 0.0),
            'collection_breakdown': json.dumps(
                collection_result.get('collected_breakdown', {}),
                ensure_ascii=False
            ) if collection_result.get('collected_breakdown') else last_shift.collection_breakdown,
            'float_target': float(
                self.env['ir.config_parameter'].sudo().get_param(
                    'gas_station_cash.float_amount', 0
                ) or 0
            ),
            'float_amount': float(collection_result.get('current_cash', 0.0)),
        })

        last_shift._link_shifts_to_eod()

        # เพิ่ม Withdrawal & Exchange lines ที่ยังไม่มี
        AuditLine = self.env['gas.station.shift.audit.line'].sudo()

        for withdrawal in withdrawals:
            existing = AuditLine.search([
                ('audit_id', '=', last_shift.id),
                ('line_type', '=', 'cash_withdrawal'),
                ('withdrawal_id', '=', withdrawal.id),
            ], limit=1)
            if not existing:
                AuditLine.create({
                    'audit_id': last_shift.id,
                    'line_type': 'cash_withdrawal',
                    'withdrawal_id': withdrawal.id,
                })

        for exchange in exchanges:
            existing = AuditLine.search([
                ('audit_id', '=', last_shift.id),
                ('line_type', '=', 'cash_exchange'),
                ('exchange_id', '=', exchange.id),
            ], limit=1)
            if not existing:
                AuditLine.create({
                    'audit_id': last_shift.id,
                    'line_type': 'cash_exchange',
                    'exchange_id': exchange.id,
                })

        if withdrawals:
            withdrawals.write({'audit_id': last_shift.id})
        if exchanges:
            exchanges.write({'audit_id': last_shift.id})

        _logger.info("🌙 ✅ [FlowCo] Marked %s as EOD (eod_grand_total=%.2f)",
                     last_shift.name, eod_totals['grand_total'])
        _logger.info("=" * 60)
        return last_shift

    # =====================================================================
    # INTERNAL CALCULATION HELPERS
    # =====================================================================

    def _calculate_deposit_totals(self, deposits):
        """คำนวณยอดรวมจาก deposits แยกตาม type"""
        result = {
            'pos_oil': 0.0, 'pos_engine_oil': 0.0, 'pos_other': 0.0, 'pos_count': 0,
            'total_oil': 0.0, 'total_engine_oil': 0.0, 'total_coffee_shop': 0.0,
            'total_convenient_store': 0.0, 'total_rental': 0.0, 'total_deposit_cash': 0.0,
            'total_exchange_cash': 0.0, 'total_other': 0.0, 'total_all': 0.0,
        }
        if not deposits:
            return result

        for deposit in deposits:
            amount = deposit.total_amount or 0.0
            dtype = deposit.deposit_type

            if dtype == 'oil':
                result['total_oil'] += amount
            elif dtype == 'engine_oil':
                result['total_engine_oil'] += amount
            elif dtype == 'coffee_shop':
                result['total_coffee_shop'] += amount
            elif dtype == 'convenient_store':
                result['total_convenient_store'] += amount
            elif dtype == 'rental':
                result['total_rental'] += amount
            elif dtype == 'deposit_cash':
                result['total_deposit_cash'] += amount
            elif dtype == 'exchange_cash':
                result['total_exchange_cash'] += amount
            else:
                result['total_other'] += amount

            result['total_all'] += amount

            is_pos_related = getattr(deposit, 'is_pos_related', False)
            pos_status = getattr(deposit, 'pos_status', '')
            if is_pos_related and pos_status == 'ok':
                result['pos_count'] += 1
                if dtype == 'oil':
                    result['pos_oil'] += amount
                elif dtype == 'engine_oil':
                    result['pos_engine_oil'] += amount
                else:
                    result['pos_other'] += amount

        return result

    def _calculate_eod_totals(self, current_shift_totals):
        """คำนวณ EOD totals รวมจาก shifts ก่อนหน้า + shift ปัจจุบัน"""
        previous_eod = self._get_previous_eod()
        domain = [('audit_type', '=', 'close_shift'), ('parent_eod_id', '=', False)]
        if previous_eod:
            domain.append(('close_time', '>', previous_eod.close_time))
        previous_shifts = self.search(domain)

        eod = {
            'oil': current_shift_totals.get('total_oil', 0),
            'engine_oil': current_shift_totals.get('total_engine_oil', 0),
            'coffee_shop': current_shift_totals.get('total_coffee_shop', 0),
            'convenient_store': current_shift_totals.get('total_convenient_store', 0),
            'rental': current_shift_totals.get('total_rental', 0),
            'deposit_cash': current_shift_totals.get('total_deposit_cash', 0),
            'exchange_cash': current_shift_totals.get('total_exchange_cash', 0),
            'other': current_shift_totals.get('total_other', 0),
            'grand_total': current_shift_totals.get('total_all', 0),
            'pos_total': (
                current_shift_totals.get('pos_oil', 0) +
                current_shift_totals.get('pos_engine_oil', 0) +
                current_shift_totals.get('pos_other', 0)
            ),
        }

        for shift in previous_shifts:
            eod['oil'] += shift.total_oil or 0
            eod['engine_oil'] += shift.total_engine_oil or 0
            eod['coffee_shop'] += shift.total_coffee_shop or 0
            eod['convenient_store'] += shift.total_convenient_store or 0
            eod['rental'] += shift.total_rental or 0
            eod['deposit_cash'] += shift.total_deposit_cash or 0
            eod['exchange_cash'] += shift.total_exchange_cash or 0
            eod['other'] += shift.total_other or 0
            eod['grand_total'] += shift.total_all_deposits or 0
            eod['pos_total'] += shift.pos_total_amount or 0

        _logger.info("EOD totals from %d previous shifts: grand_total=%.2f",
                     len(previous_shifts), eod['grand_total'])
        return eod


# =============================================================================
# UNIFIED SHIFT AUDIT LINE
# =============================================================================

class GasStationShiftAuditLine(models.Model):
    """
    Unified Audit Line สำหรับ 1 ShiftAudit record

    line_type = 'pos_data'       → ข้อมูลจาก POS (FlowCo per-staff / FirstPro N/A)
    line_type = 'cash_deposit'   → link → gas.station.cash.deposit
    line_type = 'cash_withdrawal'→ link → gas.station.cash.withdrawal
    line_type = 'cash_exchange'  → link → gas.station.cash.exchange
    """
    _name = 'gas.station.shift.audit.line'
    _description = 'Shift Audit Line — Unified'
    _order = 'audit_id, line_type, id'

    # ── Relationship ──────────────────────────────────────────────────────
    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Line Type ─────────────────────────────────────────────────────────
    line_type = fields.Selection([
        ('pos_data', 'POS Data'),
        ('cash_deposit', 'Cash Deposit'),
        ('cash_withdrawal', 'Cash Withdrawal'),
        ('cash_exchange', 'Cash Exchange'),
        ('cash_replenish', 'Replenish Cash'),
    ], string='Line Type', required=True, index=True)

    # =====================================================================
    # POS DATA FIELDS  (line_type = 'pos_data')
    # =====================================================================

    pos_source = fields.Selection([
        ('flowco', 'FlowCo'),
        ('firstpro', 'FirstPro'),
    ], string='POS Source',
        help="ระบบ POS ที่ส่งข้อมูลนี้มา"
    )

    # Staff identification
    staff_external_id = fields.Char(
        string='Staff ID (External)',
        index=True,
        help="staff_id จาก POS payload (RFID UID สำหรับ FlowCo / staff_id สำหรับ FirstPro)"
    )
    staff_record_id = fields.Many2one(
        'gas.station.staff',
        string='Staff Record',
        compute='_compute_staff_record',
        store=True,
    )

    # ── FlowCo fields ─────────────────────────────────────────────────────
    saleamt_fuel = fields.Monetary(
        string='Sale Fuel',
        currency_field='currency_id',
        default=0.0,
        help="saleamt_fuel จาก FlowCo | N/A สำหรับ FirstPro"
    )
    dropamt_fuel = fields.Monetary(
        string='Drop Fuel',
        currency_field='currency_id',
        default=0.0,
        help="dropamt_fuel จาก FlowCo | N/A สำหรับ FirstPro"
    )
    saleamt_lube = fields.Monetary(
        string='Sale Lube',
        currency_field='currency_id',
        default=0.0,
        help="saleamt_lube จาก FlowCo | N/A สำหรับ FirstPro"
    )
    dropamt_lube = fields.Monetary(
        string='Drop Lube',
        currency_field='currency_id',
        default=0.0,
        help="dropamt_lube จาก FlowCo | N/A สำหรับ FirstPro"
    )

    # ── Computed drop discrepancy (FlowCo) ───────────────────────────────
    fuel_diff = fields.Monetary(
        string='Fuel Diff (Sale - Drop)',
        currency_field='currency_id',
        compute='_compute_flowco_diff',
        store=True,
    )
    lube_diff = fields.Monetary(
        string='Lube Diff (Sale - Drop)',
        currency_field='currency_id',
        compute='_compute_flowco_diff',
        store=True,
    )

    # ── FirstPro fields ───────────────────────────────────────────────────
    firstpro_shiftid = fields.Char(
        string='FirstPro Shift ID',
        help="shiftid จาก FirstPro payload"
    )
    firstpro_product_amount = fields.Monetary(
        string='Product Amount (FirstPro)',
        currency_field='currency_id',
        default=0.0,
        help="product_amount จาก FirstPro — ยอดขาย engine oil สำหรับ reconcile\n"
             "N/A ในปัจจุบัน รอข้อมูลเพิ่มเติมจาก FirstPro"
    )

    # ── POS Line Status ───────────────────────────────────────────────────
    pos_line_status = fields.Char(
        string='POS Status',
        help="status จาก FlowCo: 'OK'/'ERROR' | 'N/A' สำหรับ FirstPro"
    )
    is_error = fields.Boolean(
        string='Has Error',
        compute='_compute_is_error',
        store=True,
    )

    # =====================================================================
    # CASH TRANSACTION LINKS  (line_type != 'pos_data')
    # =====================================================================

    deposit_id = fields.Many2one(
        'gas.station.cash.deposit',
        string='Cash Deposit',
        ondelete='set null',
        index=True,
    )
    withdrawal_id = fields.Many2one(
        'gas.station.cash.withdrawal',
        string='Cash Withdrawal',
        ondelete='set null',
        index=True,
    )
    exchange_id = fields.Many2one(
        'gas.station.cash.exchange',
        string='Cash Exchange',
        ondelete='set null',
        index=True,
    )
    replenish_id = fields.Many2one(
        'gas.station.cash.replenish',
        string='Replenish Cash',
        ondelete='set null',
        index=True,
    )

    # =====================================================================
    # SUMMARY AMOUNT (computed — ยอดที่ relevant ตาม line_type)
    # =====================================================================
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
        compute='_compute_amount',
        store=True,
        help="ยอดเงินที่สรุปสำหรับ line นี้\n"
             "pos_data       → firstpro_product_amount (FirstPro) / saleamt_fuel+lube (FlowCo)\n"
             "cash_deposit   → deposit total_amount\n"
             "cash_withdrawal→ withdrawal total_amount\n"
             "cash_exchange  → cashout_amount"
    )

    # ── FirstPro: related fields from parent audit for diff display ──────
    audit_total_engine_oil = fields.Monetary(
        string='Odoo Eng Oil',
        currency_field='currency_id',
        related='audit_id.total_engine_oil',
        store=True,
    )
    audit_total_oil = fields.Monetary(
        string='Odoo Oil (Fuel)',
        currency_field='currency_id',
        related='audit_id.total_oil',
        store=True,
    )
    firstpro_eng_diff = fields.Monetary(
        string='Eng Diff',
        currency_field='currency_id',
        compute='_compute_firstpro_eng_diff',
        store=True,
        help="FirstPro: Odoo engine_oil − POS product_amount"
    )

    @api.depends('audit_total_engine_oil', 'firstpro_product_amount', 'pos_source')
    def _compute_firstpro_eng_diff(self):
        for rec in self:
            if rec.pos_source == 'firstpro':
                rec.firstpro_eng_diff = (rec.audit_total_engine_oil or 0) - (rec.firstpro_product_amount or 0)
            else:
                rec.firstpro_eng_diff = 0.0

    # ── Related display fields (อ่านจาก linked records) ──────────────────
    deposit_type = fields.Selection(
        related='deposit_id.deposit_type',
        string='Deposit Type',
        store=True,
    )
    deposit_state = fields.Selection(
        related='deposit_id.state',
        string='Deposit Status',
        store=True,
    )
    withdrawal_type = fields.Selection(
        related='withdrawal_id.withdrawal_type',
        string='Withdrawal Type',
        store=True,
    )

    # ── Currency (relay from parent audit) ───────────────────────────────
    currency_id = fields.Many2one(
        related='audit_id.currency_id',
        store=True,
        readonly=True,
    )

    # =====================================================================
    # COMPUTE
    # =====================================================================

    @api.depends('staff_external_id', 'pos_source')
    def _compute_staff_record(self):
        Staff = self.env['gas.station.staff'].sudo()
        for rec in self:
            if not rec.staff_external_id:
                rec.staff_record_id = False
                continue
            if rec.pos_source == 'flowco':
                # FlowCo: match ด้วย tag_id (RFID UID)
                staff = Staff.search([('tag_id', '=', rec.staff_external_id)], limit=1)
            else:
                # FirstPro: match ด้วย external_id / staff code
                staff = Staff.search([('external_id', '=', rec.staff_external_id)], limit=1)
            rec.staff_record_id = staff.id if staff else False

    @api.depends('pos_line_status')
    def _compute_is_error(self):
        for rec in self:
            status = (rec.pos_line_status or '').upper()
            rec.is_error = status not in ('OK', 'N/A', '')

    @api.depends('saleamt_fuel', 'dropamt_fuel', 'saleamt_lube', 'dropamt_lube')
    def _compute_flowco_diff(self):
        for rec in self:
            rec.fuel_diff = (rec.saleamt_fuel or 0.0) - (rec.dropamt_fuel or 0.0)
            rec.lube_diff = (rec.saleamt_lube or 0.0) - (rec.dropamt_lube or 0.0)

    @api.depends(
        'line_type', 'pos_source',
        'firstpro_product_amount', 'saleamt_fuel', 'saleamt_lube',
        'deposit_id.total_amount',
        'withdrawal_id.total_amount',
        'exchange_id.cashout_amount',
    )
    def _compute_amount(self):
        for rec in self:
            if rec.line_type == 'pos_data':
                if rec.pos_source == 'firstpro':
                    rec.amount = rec.firstpro_product_amount or 0.0
                else:
                    # FlowCo: sale fuel + sale lube
                    rec.amount = (rec.saleamt_fuel or 0.0) + (rec.saleamt_lube or 0.0)
            elif rec.line_type == 'cash_deposit':
                rec.amount = rec.deposit_id.total_amount if rec.deposit_id else 0.0
            elif rec.line_type == 'cash_withdrawal':
                rec.amount = rec.withdrawal_id.total_amount if rec.withdrawal_id else 0.0
            elif rec.line_type == 'cash_exchange':
                rec.amount = rec.exchange_id.cashout_amount if rec.exchange_id else 0.0
            elif rec.line_type == 'cash_replenish':
                rec.amount = rec.replenish_id.total_amount if rec.replenish_id else 0.0
            else:
                rec.amount = 0.0


# =============================================================================
# EXTEND CASH MODELS — เพิ่ม audit_id
# =============================================================================

class GasStationCashDepositAudit(models.Model):
    """Extend gas.station.cash.deposit — audit relationship (already exists)"""
    _inherit = 'gas.station.cash.deposit'

    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        index=True,
        ondelete='set null',
        help="Shift Audit ที่ deposit นี้อยู่ใน"
    )
    audit_shift_number = fields.Integer(
        string='Shift #',
        related='audit_id.shift_number',
        store=True,
    )
    audit_type_related = fields.Selection(
        related='audit_id.audit_type',
        string='Audit Type',
        store=True,
    )


class GasStationCashWithdrawalAudit(models.Model):
    """Extend gas.station.cash.withdrawal — เพิ่ม audit_id"""
    _inherit = 'gas.station.cash.withdrawal'

    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        index=True,
        ondelete='set null',
        help="Shift Audit ที่ withdrawal นี้อยู่ใน"
    )
    audit_shift_number = fields.Integer(
        string='Shift #',
        related='audit_id.shift_number',
        store=True,
    )


class GasStationCashExchangeAudit(models.Model):
    """Extend gas.station.cash.exchange — เพิ่ม audit_id"""
    _inherit = 'gas.station.cash.exchange'

    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        index=True,
        ondelete='set null',
        help="Shift Audit ที่ exchange นี้อยู่ใน"
    )
    audit_shift_number = fields.Integer(
        string='Shift #',
        related='audit_id.shift_number',
        store=True,
    )