# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime, timedelta


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
    ], string='Status', default='draft', tracking=True)
    
    # =====================================================================
    # SHIFT TYPE & SEQUENCE
    # =====================================================================
    audit_type = fields.Selection([
        ('close_shift', 'Close Shift'),
        ('end_of_day', 'End of Day'),
    ], string='Audit Type', default='close_shift', required=True, tracking=True)
    
    is_last_shift = fields.Boolean(
        string='Last Shift (EOD)',
        default=False,
        help="ถ้า True = เป็น shift สุดท้ายของวัน (End of Day)"
    )
    
    shift_number = fields.Integer(
        string='Shift Number',
        default=1,
        help="ลำดับ shift ในรอบ EOD (1, 2, 3, ... reset หลัง EOD)"
    )
    
    previous_eod_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Previous EOD',
        help="อ้างอิงถึง End of Day ก่อนหน้า"
    )
    
    # =====================================================================
    # STAFF & TERMINAL INFO
    # =====================================================================
    staff_id = fields.Many2one(
        'res.users',
        string='Staff (Odoo User)',
        help="Odoo user ที่ทำ shift นี้ (ถ้า map ได้)"
    )
    staff_external_id = fields.Char(
        string='Staff ID (External)',
        index=True,
        help="Staff ID จาก POS/Glory"
    )
    staff_name = fields.Char(
        string='Staff Name',
        help="ชื่อพนักงานจาก POS"
    )
    
    pos_terminal_id = fields.Char(
        string='POS Terminal ID',
        index=True
    )
    pos_shift_id = fields.Char(
        string='POS Shift ID',
        index=True,
        help="Shift ID จาก POS system"
    )
    
    # NOTE: pos_command_id จะเพิ่มทีหลังเมื่อสร้าง gas.station.pos.command model
    # pos_command_id = fields.Many2one(
    #     'gas.station.pos.command',
    #     string='POS Command',
    #     help="คำสั่งจาก POS ที่ trigger audit นี้"
    # )
    
    # =====================================================================
    # TIME PERIOD
    # =====================================================================
    shift_start_time = fields.Datetime(
        string='Shift Start Time',
        help="เวลาเริ่ม shift"
    )
    close_time = fields.Datetime(
        string='Close Time',
        default=fields.Datetime.now,
        required=True,
        tracking=True
    )
    
    # Period for EOD calculation
    period_start = fields.Datetime(
        string='Period Start',
        compute='_compute_period',
        store=True,
        help="จุดเริ่มต้นของ period (EOD ก่อนหน้า หรือ shift start)"
    )
    period_end = fields.Datetime(
        string='Period End',
        compute='_compute_period',
        store=True,
        help="จุดสิ้นสุดของ period (close_time)"
    )
    
    # =====================================================================
    # POS TOTALS (ยอดที่ส่งไป POS - เฉพาะ shift นี้)
    # =====================================================================
    pos_oil_total = fields.Monetary(
        string='POS Oil Total',
        currency_field='currency_id',
        help="ยอดน้ำมันที่ส่งไป POS ใน shift นี้"
    )
    pos_engine_oil_total = fields.Monetary(
        string='POS Engine Oil Total',
        currency_field='currency_id'
    )
    pos_other_total = fields.Monetary(
        string='POS Other Total',
        currency_field='currency_id'
    )
    pos_total_amount = fields.Monetary(
        string='POS Total Amount',
        compute='_compute_pos_totals',
        store=True,
        currency_field='currency_id'
    )
    pos_transaction_count = fields.Integer(
        string='POS Transaction Count'
    )
    
    # POS Reconciliation
    pos_reported_total = fields.Monetary(
        string='POS Reported Total',
        currency_field='currency_id',
        help="ยอดที่ POS รายงานมา"
    )
    pos_difference = fields.Monetary(
        string='POS Difference',
        compute='_compute_pos_difference',
        store=True,
        currency_field='currency_id'
    )
    
    # =====================================================================
    # DEPOSIT TOTALS BY TYPE (ยอดทั้งหมดใน period)
    # =====================================================================
    total_oil = fields.Monetary(
        string='Total Oil',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_engine_oil = fields.Monetary(
        string='Total Engine Oil',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_coffee_shop = fields.Monetary(
        string='Total Coffee Shop',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_convenient_store = fields.Monetary(
        string='Total Convenient Store',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_rental = fields.Monetary(
        string='Total Rental',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_deposit_cash = fields.Monetary(
        string='Total Deposit Cash',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_exchange_cash = fields.Monetary(
        string='Total Exchange Cash',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_other = fields.Monetary(
        string='Total Other',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    total_all_deposits = fields.Monetary(
        string='Total All Deposits',
        compute='_compute_deposit_totals',
        store=True,
        currency_field='currency_id'
    )
    
    # =====================================================================
    # EOD CUMULATIVE TOTALS (ยอดรวมตั้งแต่ EOD ก่อนหน้า)
    # =====================================================================
    eod_total_oil = fields.Monetary(
        string='EOD Total Oil',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id',
        help="ยอดน้ำมันรวมตั้งแต่ EOD ก่อนหน้า"
    )
    eod_total_engine_oil = fields.Monetary(
        string='EOD Total Engine Oil',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_coffee_shop = fields.Monetary(
        string='EOD Total Coffee Shop',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_convenient_store = fields.Monetary(
        string='EOD Total Convenient Store',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_rental = fields.Monetary(
        string='EOD Total Rental',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_deposit_cash = fields.Monetary(
        string='EOD Total Deposit Cash',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_exchange_cash = fields.Monetary(
        string='EOD Total Exchange Cash',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_total_other = fields.Monetary(
        string='EOD Total Other',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id'
    )
    eod_grand_total = fields.Monetary(
        string='EOD Grand Total',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id',
        help="ยอดรวมทั้งหมดตั้งแต่ EOD ก่อนหน้า"
    )
    eod_pos_total = fields.Monetary(
        string='EOD POS Total',
        compute='_compute_eod_totals',
        store=True,
        currency_field='currency_id',
        help="ยอด POS รวมตั้งแต่ EOD ก่อนหน้า"
    )
    
    # =====================================================================
    # COLLECTION BOX (End of Day)
    # =====================================================================
    collected_amount = fields.Monetary(
        string='Collected Amount',
        currency_field='currency_id',
        help="จำนวนเงินที่เก็บจาก Collection Box"
    )
    reserve_kept = fields.Monetary(
        string='Reserve Kept',
        currency_field='currency_id',
        help="เงินสำรองที่เก็บไว้ในตู้"
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
        help="รายละเอียดธนบัตร/เหรียญ"
    )
    
    # =====================================================================
    # RELATED DEPOSITS
    # =====================================================================
    deposit_ids = fields.One2many(
        'gas.station.cash.deposit',
        'audit_id',
        string='Related Deposits'
    )
    total_deposit_count = fields.Integer(
        string='Deposit Count',
        compute='_compute_deposit_count',
        store=True
    )
    
    # Shifts in this EOD period (for EOD audit)
    shift_audit_ids = fields.One2many(
        'gas.station.shift.audit',
        'parent_eod_id',
        string='Shifts in Period',
        help="รายการ shift ทั้งหมดในรอบ EOD นี้"
    )
    parent_eod_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Parent EOD',
        help="EOD ที่ shift นี้อยู่ใน period"
    )
    shift_count_in_period = fields.Integer(
        string='Shifts in Period',
        compute='_compute_shift_count',
        store=True
    )
    
    # =====================================================================
    # NOTES & METADATA
    # =====================================================================
    notes = fields.Text(string='Notes')
    reconciliation_notes = fields.Text(string='Reconciliation Notes')
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company
    )
    
    # =====================================================================
    # COMPUTED METHODS
    # =====================================================================
    
    @api.depends('previous_eod_id', 'close_time', 'shift_start_time', 'audit_type')
    def _compute_period(self):
        """คำนวณ period start/end"""
        for record in self:
            record.period_end = record.close_time
            
            if record.audit_type == 'end_of_day':
                # EOD: period start = EOD ก่อนหน้า
                if record.previous_eod_id:
                    record.period_start = record.previous_eod_id.close_time
                else:
                    # ไม่มี EOD ก่อนหน้า - ใช้ shift start หรือ 7 วันก่อน
                    record.period_start = record.shift_start_time or (
                        record.close_time - timedelta(days=7) if record.close_time else False
                    )
            else:
                # Close Shift: period = เฉพาะ shift นี้
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
            if record.pos_reported_total:
                record.pos_difference = record.pos_total_amount - record.pos_reported_total
            else:
                record.pos_difference = 0
    
    @api.depends('deposit_ids', 'deposit_ids.total_amount', 'deposit_ids.deposit_type', 'deposit_ids.state')
    def _compute_deposit_totals(self):
        """คำนวณยอด deposit แยกตาม type (เฉพาะ shift นี้)"""
        for record in self:
            deposits = record.deposit_ids.filtered(lambda d: d.state != 'cancelled')
            
            record.total_oil = sum(deposits.filtered(lambda d: d.deposit_type == 'oil').mapped('total_amount'))
            record.total_engine_oil = sum(deposits.filtered(lambda d: d.deposit_type == 'engine_oil').mapped('total_amount'))
            record.total_coffee_shop = sum(deposits.filtered(lambda d: d.deposit_type == 'coffee_shop').mapped('total_amount'))
            record.total_convenient_store = sum(deposits.filtered(lambda d: d.deposit_type == 'convenient_store').mapped('total_amount'))
            record.total_rental = sum(deposits.filtered(lambda d: d.deposit_type == 'rental').mapped('total_amount'))
            record.total_deposit_cash = sum(deposits.filtered(lambda d: d.deposit_type == 'deposit_cash').mapped('total_amount'))
            record.total_exchange_cash = sum(deposits.filtered(lambda d: d.deposit_type == 'exchange_cash').mapped('total_amount'))
            record.total_other = sum(deposits.filtered(lambda d: d.deposit_type == 'other').mapped('total_amount'))
            
            record.total_all_deposits = sum(deposits.mapped('total_amount'))
    
    @api.depends('shift_audit_ids', 'shift_audit_ids.total_all_deposits', 
                 'total_all_deposits', 'pos_total_amount', 'audit_type')
    def _compute_eod_totals(self):
        """คำนวณยอดรวมตั้งแต่ EOD ก่อนหน้า (สำหรับ EOD audit)"""
        for record in self:
            if record.audit_type == 'end_of_day':
                # รวมยอดจากทุก shift ใน period + ยอดของ EOD เอง
                shifts = record.shift_audit_ids.filtered(lambda s: s.state != 'cancelled')
                
                record.eod_total_oil = sum(shifts.mapped('total_oil')) + (record.total_oil or 0)
                record.eod_total_engine_oil = sum(shifts.mapped('total_engine_oil')) + (record.total_engine_oil or 0)
                record.eod_total_coffee_shop = sum(shifts.mapped('total_coffee_shop')) + (record.total_coffee_shop or 0)
                record.eod_total_convenient_store = sum(shifts.mapped('total_convenient_store')) + (record.total_convenient_store or 0)
                record.eod_total_rental = sum(shifts.mapped('total_rental')) + (record.total_rental or 0)
                record.eod_total_deposit_cash = sum(shifts.mapped('total_deposit_cash')) + (record.total_deposit_cash or 0)
                record.eod_total_exchange_cash = sum(shifts.mapped('total_exchange_cash')) + (record.total_exchange_cash or 0)
                record.eod_total_other = sum(shifts.mapped('total_other')) + (record.total_other or 0)
                
                record.eod_grand_total = sum(shifts.mapped('total_all_deposits')) + (record.total_all_deposits or 0)
                record.eod_pos_total = sum(shifts.mapped('pos_total_amount')) + (record.pos_total_amount or 0)
            else:
                # Close Shift - ไม่ใช้ EOD totals
                record.eod_total_oil = 0
                record.eod_total_engine_oil = 0
                record.eod_total_coffee_shop = 0
                record.eod_total_convenient_store = 0
                record.eod_total_rental = 0
                record.eod_total_deposit_cash = 0
                record.eod_total_exchange_cash = 0
                record.eod_total_other = 0
                record.eod_grand_total = 0
                record.eod_pos_total = 0
    
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
    
    @api.depends('deposit_ids')
    def _compute_deposit_count(self):
        for record in self:
            record.total_deposit_count = len(record.deposit_ids)
    
    @api.depends('shift_audit_ids')
    def _compute_shift_count(self):
        for record in self:
            record.shift_count_in_period = len(record.shift_audit_ids)
    
    # =====================================================================
    # CRUD METHODS
    # =====================================================================
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                # Generate sequence based on type
                if vals.get('audit_type') == 'end_of_day' or vals.get('is_last_shift'):
                    vals['name'] = self.env['ir.sequence'].next_by_code('gas.station.shift.audit.eod') or \
                                   self.env['ir.sequence'].next_by_code('gas.station.shift.audit') or _('New')
                else:
                    vals['name'] = self.env['ir.sequence'].next_by_code('gas.station.shift.audit') or _('New')
            
            # Auto-set shift number และ previous_eod
            if not vals.get('shift_number'):
                vals['shift_number'] = self._get_next_shift_number()
            
            if not vals.get('previous_eod_id'):
                vals['previous_eod_id'] = self._get_previous_eod_id()
        
        records = super().create(vals_list)
        
        # Link shifts to parent EOD
        for record in records:
            if record.audit_type == 'end_of_day':
                record._link_shifts_to_eod()
        
        return records
    
    def _get_next_shift_number(self):
        """หา shift number ถัดไป (นับจาก EOD ก่อนหน้า)"""
        previous_eod = self._get_previous_eod()
        
        if previous_eod:
            # นับ shift หลัง EOD ก่อนหน้า
            shifts_after_eod = self.search_count([
                ('close_time', '>', previous_eod.close_time),
                ('audit_type', '=', 'close_shift'),
                ('id', '!=', self.id if self.id else 0),
            ])
            return shifts_after_eod + 1
        else:
            # ไม่มี EOD ก่อนหน้า - นับทั้งหมด
            return self.search_count([
                ('audit_type', '=', 'close_shift'),
            ]) + 1
    
    def _get_previous_eod(self):
        """หา EOD ก่อนหน้า"""
        return self.search([
            ('audit_type', '=', 'end_of_day'),
            ('state', '!=', 'cancelled'),
        ], order='close_time desc', limit=1)
    
    def _get_previous_eod_id(self):
        """หา ID ของ EOD ก่อนหน้า"""
        previous_eod = self._get_previous_eod()
        return previous_eod.id if previous_eod else False
    
    def _link_shifts_to_eod(self):
        """Link ทุก shift ที่อยู่ใน period ของ EOD นี้"""
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
        
        shifts = self.search(domain)
        shifts.write({'parent_eod_id': self.id})
    
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
            
            # Check for discrepancy
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
        """Mark shift as End of Day (Last Shift)"""
        for record in self:
            if record.audit_type != 'close_shift':
                raise UserError(_('Only Close Shift can be marked as End of Day.'))
            
            record.write({
                'audit_type': 'end_of_day',
                'is_last_shift': True,
            })
            record._link_shifts_to_eod()
    
    # =====================================================================
    # BUSINESS METHODS
    # =====================================================================
    
    @api.model
    def create_from_pos_command(self, command_data):
        """สร้าง Shift Audit จากคำสั่ง POS
        
        Args:
            command_data: dict containing:
                - command_type: 'close_shift' or 'end_of_day'
                - staff_id: Staff ID from POS
                - staff_name: Staff name
                - terminal_id: POS Terminal ID
                - shift_id: POS Shift ID
                - shift_start_time: datetime
                - close_time: datetime
                - pos_totals: dict of totals
                - deposits: list of deposit data
        """
        is_eod = command_data.get('command_type') == 'end_of_day'
        
        vals = {
            'audit_type': 'end_of_day' if is_eod else 'close_shift',
            'is_last_shift': is_eod,
            'staff_external_id': command_data.get('staff_id'),
            'staff_name': command_data.get('staff_name'),
            'pos_terminal_id': command_data.get('terminal_id'),
            'pos_shift_id': command_data.get('shift_id'),
            'shift_start_time': command_data.get('shift_start_time'),
            'close_time': command_data.get('close_time') or fields.Datetime.now(),
        }
        
        # POS totals
        pos_totals = command_data.get('pos_totals', {})
        vals.update({
            'pos_oil_total': pos_totals.get('oil', 0),
            'pos_engine_oil_total': pos_totals.get('engine_oil', 0),
            'pos_other_total': pos_totals.get('other', 0),
            'pos_transaction_count': pos_totals.get('transaction_count', 0),
            'pos_reported_total': pos_totals.get('reported_total', 0),
        })
        
        # Collection data (for EOD)
        if is_eod:
            vals.update({
                'collected_amount': command_data.get('collected_amount', 0),
                'reserve_kept': command_data.get('reserve_kept', 0),
                'collection_breakdown': command_data.get('collection_breakdown', ''),
            })
        
        audit = self.create(vals)
        
        # Link existing deposits
        if command_data.get('deposit_ids'):
            self.env['gas.station.cash.deposit'].browse(
                command_data['deposit_ids']
            ).write({'audit_id': audit.id})
        
        return audit
    
    def get_eod_summary(self):
        """Get summary for EOD report"""
        self.ensure_one()
        
        if self.audit_type != 'end_of_day':
            raise UserError(_('This method is only for End of Day audits.'))
        
        return {
            'name': self.name,
            'close_time': self.close_time,
            'shift_count': self.shift_count_in_period,
            'shifts': [{
                'name': s.name,
                'shift_number': s.shift_number,
                'staff': s.staff_external_id,
                'total': s.total_all_deposits,
                'pos_total': s.pos_total_amount,
            } for s in self.shift_audit_ids],
            'totals': {
                'oil': self.eod_total_oil,
                'engine_oil': self.eod_total_engine_oil,
                'coffee_shop': self.eod_total_coffee_shop,
                'convenient_store': self.eod_total_convenient_store,
                'rental': self.eod_total_rental,
                'deposit_cash': self.eod_total_deposit_cash,
                'exchange_cash': self.eod_total_exchange_cash,
                'other': self.eod_total_other,
                'grand_total': self.eod_grand_total,
                'pos_total': self.eod_pos_total,
            },
            'collection': {
                'collected': self.collected_amount,
                'reserve': self.reserve_kept,
                'expected': self.collection_expected,
                'difference': self.collection_difference,
            },
            'state': self.state,
        }


class GasStationCashDepositAudit(models.Model):
    """Extend gas.station.cash.deposit to add audit relationship"""
    _inherit = 'gas.station.cash.deposit'

    # =====================================================================
    # AUDIT RELATIONSHIP
    # =====================================================================
    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        index=True,
        ondelete='set null',
        help="Shift Audit ที่ deposit นี้อยู่ใน"
    )
    
    # Quick reference fields
    audit_shift_number = fields.Integer(
        string='Shift #',
        related='audit_id.shift_number',
        store=True
    )
    audit_type_related = fields.Selection(
        related='audit_id.audit_type',
        string='Audit Type',
        store=True
    )