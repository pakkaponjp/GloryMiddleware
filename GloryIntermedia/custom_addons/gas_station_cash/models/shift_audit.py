# -*- coding: utf-8 -*-
"""
Shift Audit Model - สำหรับบันทึก Close Shift และ End of Day

รวม Close Shift และ End-of-Day ไว้ใน model เดียว:
- Close Shift = ปิดกะปกติ (Shift #1, #2, #3, ...)
- End of Day = Shift สุดท้ายของวัน (is_last_shift=True)
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
    # STAFF & TERMINAL INFO
    # =====================================================================
    staff_id = fields.Many2one(
        'res.users',
        string='Staff (Odoo User)',
        readonly=True,
        help="Odoo user ที่ทำ shift นี้ (ถ้า map ได้)"
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
        help="ชื่อพนักงานจาก POS"
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
        help="Shift ID จาก POS system"
    )
    
    # =====================================================================
    # TIME PERIOD
    # =====================================================================
    shift_start_time = fields.Datetime(
        string='Shift Start Time',
        readonly=True,
        help="เวลาเริ่ม shift"
    )
    close_time = fields.Datetime(
        string='Close Time',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
        readonly=True
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
        readonly=True,
        help="ยอดน้ำมันที่ส่งไป POS ใน shift นี้"
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
        help="ยอดที่ POS รายงานมา"
    )
    pos_difference = fields.Monetary(
        string='POS Difference',
        compute='_compute_pos_difference',
        store=True,
        currency_field='currency_id'
    )
    
    # =====================================================================
    # POS PRODUCT AMOUNT RECONCILIATION (ยอดขายจาก POS เทียบกับเงินที่ collect)
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
        help="ส่วนต่างระหว่างยอด POS กับยอด Glory (POS - Glory)"
    )
    cash_difference_percent = fields.Float(
        string='Difference %',
        compute='_compute_cash_difference',
        store=True,
        digits=(5, 2),
        help="เปอร์เซ็นต์ส่วนต่าง"
    )
    reconciliation_status = fields.Selection([
        ('pending', 'Pending'),
        ('matched', 'Matched'),
        ('over', 'Over'),
        ('short', 'Short'),
    ], string='Reconciliation Status',
        compute='_compute_cash_difference',
        store=True,
        help="สถานะการ reconcile: matched=ตรงกัน, over=เงินเกิน, short=เงินขาด"
    )
    
    # =====================================================================
    # DEPOSIT TOTALS BY TYPE (ยอดทั้งหมดใน shift นี้)
    # =====================================================================
    total_oil = fields.Monetary(
        string='Total Oil',
        currency_field='currency_id',
        readonly=True
    )
    total_engine_oil = fields.Monetary(
        string='Total Engine Oil',
        currency_field='currency_id',
        readonly=True
    )
    total_coffee_shop = fields.Monetary(
        string='Total Coffee Shop',
        currency_field='currency_id',
        readonly=True
    )
    total_convenient_store = fields.Monetary(
        string='Total Convenient Store',
        currency_field='currency_id',
        readonly=True
    )
    total_rental = fields.Monetary(
        string='Total Rental',
        currency_field='currency_id',
        readonly=True
    )
    total_deposit_cash = fields.Monetary(
        string='Total Deposit Cash',
        currency_field='currency_id',
        readonly=True
    )
    total_exchange_cash = fields.Monetary(
        string='Total Exchange Cash',
        currency_field='currency_id',
        readonly=True
    )
    total_other = fields.Monetary(
        string='Total Other',
        currency_field='currency_id',
        readonly=True
    )
    total_all_deposits = fields.Monetary(
        string='Total All Deposits',
        currency_field='currency_id',
        readonly=True
    )
    
    # =====================================================================
    # EOD CUMULATIVE TOTALS (ยอดรวมตั้งแต่ EOD ก่อนหน้า)
    # =====================================================================
    eod_total_oil = fields.Monetary(
        string='EOD Total Oil',
        currency_field='currency_id',
        readonly=True,
        help="ยอดน้ำมันรวมตั้งแต่ EOD ก่อนหน้า"
    )
    eod_total_engine_oil = fields.Monetary(
        string='EOD Total Engine Oil',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_coffee_shop = fields.Monetary(
        string='EOD Total Coffee Shop',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_convenient_store = fields.Monetary(
        string='EOD Total Convenient Store',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_rental = fields.Monetary(
        string='EOD Total Rental',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_deposit_cash = fields.Monetary(
        string='EOD Total Deposit Cash',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_exchange_cash = fields.Monetary(
        string='EOD Total Exchange Cash',
        currency_field='currency_id',
        readonly=True
    )
    eod_total_other = fields.Monetary(
        string='EOD Total Other',
        currency_field='currency_id',
        readonly=True
    )
    eod_grand_total = fields.Monetary(
        string='EOD Grand Total',
        currency_field='currency_id',
        readonly=True,
        help="ยอดรวมทั้งหมดตั้งแต่ EOD ก่อนหน้า"
    )
    eod_pos_total = fields.Monetary(
        string='EOD POS Total',
        currency_field='currency_id',
        readonly=True,
        help="ยอด POS รวมตั้งแต่ EOD ก่อนหน้า"
    )
    
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
    # RELATED DEPOSITS
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
    
    # Shifts in this EOD period (for EOD audit)
    shift_audit_ids = fields.One2many(
        'gas.station.shift.audit',
        'parent_eod_id',
        string='Shifts in Period',
        readonly=True,
        help="รายการ shift ทั้งหมดในรอบ EOD นี้"
    )
    parent_eod_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Parent EOD',
        readonly=True,
        help="EOD ที่ shift นี้อยู่ใน period"
    )
    shift_count_in_period = fields.Integer(
        string='Shifts in Period',
        compute='_compute_shift_count',
        store=True
    )
    
    # =====================================================================
    # NOTES & METADATA (Notes สามารถแก้ไขได้)
    # =====================================================================
    notes = fields.Text(string='Notes')  # Editable
    reconciliation_notes = fields.Text(string='Reconciliation Notes')  # Editable
    
    # =====================================================================
    # FLOWCO RAW DATA  (populated only when pos_vendor = flowco)
    # =====================================================================
    flowco_shift_number = fields.Char(
        string='FlowCo Shift Number',
        readonly=True,
        help="shift_number จาก FlowCo CloseShift payload"
    )
    flowco_pos_id = fields.Integer(
        string='FlowCo POS ID',
        readonly=True,
        help="pos_id จาก FlowCo CloseShift payload"
    )
    flowco_timestamp = fields.Datetime(
        string='FlowCo Timestamp',
        readonly=True,
        help="timestamp จาก FlowCo CloseShift payload (แปลงจาก ISO 8601)"
    )
    pos_data_raw = fields.Text(
        string='POS Data (Raw JSON)',
        readonly=True,
        help="raw JSON ของ data[] array จาก FlowCo CloseShift payload — ใช้สำหรับ debug/audit trail"
    )
    pos_data_line_ids = fields.One2many(
        'gas.station.shift.audit.line',
        'audit_id',
        string='POS Staff Lines',
        readonly=True,
        help="รายการ per-staff ที่ FlowCo ส่งมาตอน CloseShift"
    )
    
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        readonly=True,
        default=lambda self: self.env.company.currency_id
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        readonly=True,
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
            if record.pos_reported_total:
                record.pos_difference = record.pos_total_amount - record.pos_reported_total
            else:
                record.pos_difference = 0
    
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
    
    @api.depends('pos_product_amount', 'glory_collected_amount', 'total_all_deposits')
    def _compute_cash_difference(self):
        """
        คำนวณส่วนต่างระหว่างยอด POS กับยอดเงินที่ Glory เก็บได้
        
        Reconciliation Logic:
        - matched: ยอดตรงกัน (difference = 0 หรือต่างไม่เกิน threshold)
        - over: เงินเกิน (Glory > POS) - อาจเป็นเงินทอน หรือ deposit อื่น
        - short: เงินขาด (Glory < POS) - อาจมีการทอนเงิน หรือ missing deposit
        """
        TOLERANCE = 0.01  # ค่า tolerance สำหรับการเปรียบเทียบ
        
        for record in self:
            pos_amount = record.pos_product_amount or 0.0
            # ใช้ glory_collected_amount ถ้ามี หรือใช้ total_all_deposits
            glory_amount = record.glory_collected_amount or record.total_all_deposits or 0.0
            
            # คำนวณส่วนต่าง: Glory - POS
            # บวก = Glory เก็บได้มากกว่า POS report (over)
            # ลบ = Glory เก็บได้น้อยกว่า POS report (short)
            difference = glory_amount - pos_amount
            record.cash_difference = difference
            
            # คำนวณเปอร์เซ็นต์
            if pos_amount > 0:
                record.cash_difference_percent = (difference / pos_amount) * 100
            else:
                record.cash_difference_percent = 0.0
            
            # กำหนด reconciliation status
            if pos_amount == 0 and glory_amount == 0:
                record.reconciliation_status = 'pending'
            elif abs(difference) <= TOLERANCE:
                record.reconciliation_status = 'matched'
            elif difference > TOLERANCE:
                record.reconciliation_status = 'over'
            else:
                record.reconciliation_status = 'short'
    
    @api.depends('shift_audit_ids')
    def _compute_shift_count(self):
        for record in self:
            record.shift_count_in_period = len(record.shift_audit_ids)
    
    # =====================================================================
    # CRUD METHODS
    # =====================================================================
    
    def _generate_reference(self, audit_type, shift_number, close_time):
        """
        Generate reference in format: SHIFT-YYMMDDXX or EOD-YYMMDDXX
        XX = shift_number (2 digits)
        """
        if not close_time:
            close_time = fields.Datetime.now()
        
        date_str = close_time.strftime('%y%m%d')
        shift_str = str(shift_number).zfill(2)
        
        if audit_type == 'end_of_day':
            return f"EOD-{date_str}{shift_str}"
        else:
            return f"SHIFT-{date_str}{shift_str}"
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Get shift number first
            if not vals.get('shift_number'):
                vals['shift_number'] = self._get_next_shift_number()
            
            # Generate reference name
            if vals.get('name', _('New')) == _('New'):
                audit_type = vals.get('audit_type', 'close_shift')
                if vals.get('is_last_shift'):
                    audit_type = 'end_of_day'
                
                close_time = vals.get('close_time') or fields.Datetime.now()
                if isinstance(close_time, str):
                    close_time = fields.Datetime.from_string(close_time)
                
                vals['name'] = self._generate_reference(
                    audit_type, 
                    vals['shift_number'], 
                    close_time
                )
            
            if not vals.get('previous_eod_id'):
                vals['previous_eod_id'] = self._get_previous_eod_id()
        
        records = super().create(vals_list)
        
        for record in records:
            if record.audit_type == 'end_of_day':
                record._link_shifts_to_eod()
        
        return records
    
    def _get_next_shift_number(self):
        """หา shift number ถัดไป (นับจาก EOD ก่อนหน้า)"""
        previous_eod = self._get_previous_eod()
        
        if previous_eod:
            shifts_after_eod = self.search_count([
                ('close_time', '>', previous_eod.close_time),
                ('audit_type', '=', 'close_shift'),
                ('id', '!=', self.id if self.id else 0),
            ])
            return shifts_after_eod + 1
        else:
            return self.search_count([
                ('audit_type', '=', 'close_shift'),
            ]) + 1
    
    def _get_previous_eod(self):
        """หา EOD ก่อนหน้า"""
        return self.search([
            ('audit_type', '=', 'end_of_day'),
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
    # BUSINESS METHODS - สำหรับ pos_commands.py เรียกใช้
    # =====================================================================
    
    @api.model
    def create_from_shift_close(self, command, deposits, shift_start=None, product_amount=None, flowco_data=None):
        """
        สร้าง Shift Audit จาก Close Shift command
        
        Args:
            command: gas.station.pos_command record หรือ dict-like object
            deposits: recordset ของ gas.station.cash.deposit
            shift_start: datetime เวลาเริ่ม shift
            product_amount: float ยอดขายสินค้าจาก POS (สำหรับ reconciliation)
            flowco_data: dict — parsed FlowCo CloseShift payload (optional)
                         keys: shift_number, pos_id, timestamp, data (list of per-staff rows)
        
        Returns:
            gas.station.shift.audit record ที่สร้างใหม่
        """
        _logger.info("=" * 60)
        _logger.info("Creating Shift Audit from CLOSE SHIFT...")
        _logger.info("Command: %s, Deposits: %d, POS Product Amount: %s", 
                    command, len(deposits) if deposits else 0, product_amount)
        
        # คำนวณ totals
        totals = self._calculate_deposit_totals(deposits)
        _logger.info("Calculated totals: %s", totals)
        
        # Get command info safely
        staff_external_id = None
        pos_terminal_id = None
        pos_shift_id = None
        
        if command:
            staff_external_id = getattr(command, 'staff_external_id', None)
            pos_terminal_id = getattr(command, 'pos_terminal_id', None)
            pos_shift_id = getattr(command, 'pos_shift_id', None)
        
        # ── Parse FlowCo metadata ────────────────────────────────────────
        flowco_shift_number = None
        flowco_pos_id = 0
        flowco_timestamp = None
        pos_data_raw = None
        staff_lines = []

        if flowco_data and isinstance(flowco_data, dict):
            flowco_shift_number = str(flowco_data.get('shift_number', '') or '')
            try:
                flowco_pos_id = int(flowco_data.get('pos_id') or 0)
            except (TypeError, ValueError):
                flowco_pos_id = 0

            # Parse ISO 8601 timestamp (e.g. "2025-09-26T17:46:00+07:00")
            ts_raw = flowco_data.get('timestamp')
            if ts_raw:
                try:
                    from dateutil import parser as dtparser
                    dt = dtparser.parse(ts_raw)
                    # Store as UTC-naive for Odoo Datetime field
                    import pytz
                    if dt.tzinfo:
                        dt = dt.astimezone(pytz.utc).replace(tzinfo=None)
                    flowco_timestamp = dt
                except Exception as ts_err:
                    _logger.warning("Could not parse FlowCo timestamp '%s': %s", ts_raw, ts_err)

            raw_lines = flowco_data.get('data') or []
            if raw_lines:
                pos_data_raw = json.dumps(raw_lines, ensure_ascii=False)
                for row in raw_lines:
                    staff_lines.append({
                        'staff_external_id': str(row.get('staff_id', '') or ''),
                        'saleamt_fuel':  float(row.get('saleamt_fuel')  or 0),
                        'dropamt_fuel':  float(row.get('dropamt_fuel')  or 0),
                        'saleamt_lube':  float(row.get('saleamt_lube')  or 0),
                        'dropamt_lube':  float(row.get('dropamt_lube')  or 0),
                        'pos_line_status': str(row.get('status', '') or ''),
                    })

            _logger.info("[FlowCo] shift_number=%s pos_id=%s ts=%s lines=%d",
                         flowco_shift_number, flowco_pos_id, flowco_timestamp, len(staff_lines))

        vals = {
            'audit_type': 'close_shift',
            'is_last_shift': False,
            'shift_start_time': shift_start,
            'close_time': fields.Datetime.now(),
            
            # Staff & Terminal
            'staff_external_id': staff_external_id,
            'pos_terminal_id': pos_terminal_id,
            'pos_shift_id': pos_shift_id,
            
            # POS Totals (ยอดที่ส่งไป POS)
            'pos_oil_total': totals['pos_oil'],
            'pos_engine_oil_total': totals['pos_engine_oil'],
            'pos_other_total': totals['pos_other'],
            'pos_transaction_count': totals['pos_count'],
            
            # POS Product Amount Reconciliation
            'pos_product_amount': product_amount or 0.0,
            'glory_collected_amount': totals['total_all'],
            
            # Deposit Totals (ยอดทั้งหมด)
            'total_oil': totals['total_oil'],
            'total_engine_oil': totals['total_engine_oil'],
            'total_coffee_shop': totals['total_coffee_shop'],
            'total_convenient_store': totals['total_convenient_store'],
            'total_rental': totals['total_rental'],
            'total_deposit_cash': totals['total_deposit_cash'],
            'total_exchange_cash': totals['total_exchange_cash'],
            'total_other': totals['total_other'],
            'total_all_deposits': totals['total_all'],

            # FlowCo metadata
            'flowco_shift_number': flowco_shift_number or False,
            'flowco_pos_id':       flowco_pos_id or 0,
            'flowco_timestamp':    flowco_timestamp or False,
            'pos_data_raw':        pos_data_raw or False,
        }
        
        _logger.info("Creating audit with vals: %s", vals)
        audit = self.create(vals)
        
        # ── Create per-staff lines ────────────────────────────────────────
        if staff_lines:
            AuditLine = self.env['gas.station.shift.audit.line'].sudo()
            for line_vals in staff_lines:
                line_vals['audit_id'] = audit.id
                AuditLine.create(line_vals)
            _logger.info("Created %d staff lines for audit %s", len(staff_lines), audit.name)

        # Link deposits to audit
        if deposits:
            deposits.write({'audit_id': audit.id})
            _logger.info("Linked %d deposits to audit %s", len(deposits), audit.name)
        
        _logger.info("✅ Created Shift Audit: %s (type=close_shift, shift_number=%d, product_amount=%.2f, glory_amount=%.2f)", 
                    audit.name, audit.shift_number, product_amount or 0, totals['total_all'])
        _logger.info("=" * 60)
        
        return audit
    
    @api.model
    def create_from_end_of_day(self, command, deposits, collection_result=None, shift_start=None, product_amount=None):
        """
        สร้าง Shift Audit จาก End of Day command (Last Shift)
        
        Args:
            command: gas.station.pos_command record หรือ dict-like object
            deposits: recordset ของ gas.station.cash.deposit
            collection_result: dict ผลลัพธ์จาก collection
            shift_start: datetime เวลาเริ่ม shift
            product_amount: float ยอดขายสินค้าจาก POS (สำหรับ reconciliation)
        
        Returns:
            gas.station.shift.audit record ที่สร้างใหม่
        """
        _logger.info("=" * 60)
        _logger.info("🌙 Creating Shift Audit from END OF DAY (Last Shift)...")
        _logger.info("Command: %s, Deposits: %d, POS Product Amount: %s", 
                    command, len(deposits) if deposits else 0, product_amount)
        
        collection_result = collection_result or {}
        
        # คำนวณ totals
        totals = self._calculate_deposit_totals(deposits)
        _logger.info("Calculated totals: %s", totals)
        
        # คำนวณ EOD totals (รวมจาก shifts ก่อนหน้าใน period)
        eod_totals = self._calculate_eod_totals(totals)
        _logger.info("EOD totals: %s", eod_totals)
        
        # Get command info safely
        staff_external_id = None
        pos_terminal_id = None
        pos_shift_id = None
        
        if command:
            staff_external_id = getattr(command, 'staff_external_id', None)
            pos_terminal_id = getattr(command, 'pos_terminal_id', None)
            pos_shift_id = getattr(command, 'pos_shift_id', None)
        
        vals = {
            'audit_type': 'end_of_day',
            'is_last_shift': True,
            'shift_start_time': shift_start,
            'close_time': fields.Datetime.now(),
            
            # Staff & Terminal
            'staff_external_id': staff_external_id,
            'pos_terminal_id': pos_terminal_id,
            'pos_shift_id': pos_shift_id,
            
            # POS Totals (ยอดที่ส่งไป POS - shift นี้)
            'pos_oil_total': totals['pos_oil'],
            'pos_engine_oil_total': totals['pos_engine_oil'],
            'pos_other_total': totals['pos_other'],
            'pos_transaction_count': totals['pos_count'],
            
            # Deposit Totals (ยอดทั้งหมด - shift นี้)
            'total_oil': totals['total_oil'],
            'total_engine_oil': totals['total_engine_oil'],
            'total_coffee_shop': totals['total_coffee_shop'],
            'total_convenient_store': totals['total_convenient_store'],
            'total_rental': totals['total_rental'],
            'total_deposit_cash': totals['total_deposit_cash'],
            'total_exchange_cash': totals['total_exchange_cash'],
            'total_other': totals['total_other'],
            'total_all_deposits': totals['total_all'],
            
            # POS Product Amount Reconciliation
            'pos_product_amount': product_amount or 0.0,
            'glory_collected_amount': totals['total_all'],
            
            # EOD Totals (ยอดรวมทั้งวัน)
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
            
            # Collection
            'collected_amount': collection_result.get('collected_amount', 0.0),
            'reserve_kept': collection_result.get('reserve_kept', 0.0),
            'collection_breakdown': json.dumps(
                collection_result.get('collected_breakdown', {}),
                ensure_ascii=False
            ) if collection_result.get('collected_breakdown') else None,
        }
        
        _logger.info("Creating audit with vals...")
        audit = self.create(vals)
        
        # Link deposits to audit
        if deposits:
            deposits.write({'audit_id': audit.id})
            _logger.info("Linked %d deposits to audit %s", len(deposits), audit.name)
        
        _logger.info("🌙 ✅ Created END OF DAY Audit: %s (product_amount=%.2f, glory_amount=%.2f, collected=%.2f)", 
                    audit.name, 
                    product_amount or 0,
                    totals['total_all'],
                    collection_result.get('collected_amount', 0))
        _logger.info("=" * 60)
        
        return audit
    
    def _calculate_deposit_totals(self, deposits):
        """
        คำนวณยอดรวมจาก deposits แยกตาม type
        
        Returns:
            dict: {
                'pos_oil', 'pos_engine_oil', 'pos_other', 'pos_count',
                'total_oil', 'total_engine_oil', ..., 'total_all'
            }
        """
        result = {
            'pos_oil': 0.0,
            'pos_engine_oil': 0.0,
            'pos_other': 0.0,
            'pos_count': 0,
            'total_oil': 0.0,
            'total_engine_oil': 0.0,
            'total_coffee_shop': 0.0,
            'total_convenient_store': 0.0,
            'total_rental': 0.0,
            'total_deposit_cash': 0.0,
            'total_exchange_cash': 0.0,
            'total_other': 0.0,
            'total_all': 0.0,
        }
        
        if not deposits:
            return result
        
        for deposit in deposits:
            amount = deposit.total_amount or 0.0
            dtype = deposit.deposit_type
            
            # Total by type
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
            
            # POS-related (เฉพาะที่ส่งไป POS สำเร็จ)
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
        """
        คำนวณ EOD totals (รวมจาก shifts ก่อนหน้า + shift ปัจจุบัน)
        
        Args:
            current_shift_totals: dict totals ของ shift ปัจจุบัน
        
        Returns:
            dict: EOD totals
        """
        # หา shifts ก่อนหน้าที่ยังไม่มี parent_eod
        previous_eod = self._get_previous_eod()
        
        domain = [
            ('audit_type', '=', 'close_shift'),
            ('parent_eod_id', '=', False),
        ]
        if previous_eod:
            domain.append(('close_time', '>', previous_eod.close_time))
        
        previous_shifts = self.search(domain)
        
        # รวมยอดจาก shifts ก่อนหน้า + shift ปัจจุบัน
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


class GasStationShiftAuditLine(models.Model):
    """
    Per-staff breakdown sent by FlowCo in the CloseShift data[] array.

    Each row in FlowCo's payload looks like:
        {
            "staff_id":      "7B8U005B",
            "saleamt_fuel":  12000,
            "dropamt_fuel":  12000,
            "saleamt_lube":  0,
            "dropamt_lube":  0,
            "status":        "OK"
        }
    One record per staff entry per shift audit.
    """
    _name        = 'gas.station.shift.audit.line'
    _description = 'Shift Audit Line — FlowCo per-staff data'
    _order       = 'audit_id, staff_external_id'

    # ── Relationship ──────────────────────────────────────────────────────
    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Staff identification ──────────────────────────────────────────────
    staff_external_id = fields.Char(
        string='Staff ID (RFID)',
        required=True,
        index=True,
        help="staff_id จาก FlowCo payload (RFID tag UID)"
    )
    staff_record_id = fields.Many2one(
        'gas.station.staff',
        string='Staff Record',
        compute='_compute_staff_record',
        store=True,
        help="Odoo staff record ที่ match กับ staff_external_id (tag_id)"
    )

    # ── FlowCo amounts (สตางค์หรือบาทตาม POS config) ─────────────────────
    # FlowCo ส่ง raw integer (เช่น 12000 = 120.00 บาทถ้าเป็น satang, หรือ 12000.00 บาท)
    # เก็บ as-is และแปลงตาม currency_id ของ audit
    saleamt_fuel = fields.Monetary(
        string='Sale Fuel',
        currency_field='currency_id',
        default=0.0,
        help="saleamt_fuel จาก FlowCo"
    )
    dropamt_fuel = fields.Monetary(
        string='Drop Fuel',
        currency_field='currency_id',
        default=0.0,
        help="dropamt_fuel จาก FlowCo"
    )
    saleamt_lube = fields.Monetary(
        string='Sale Lube',
        currency_field='currency_id',
        default=0.0,
        help="saleamt_lube จาก FlowCo"
    )
    dropamt_lube = fields.Monetary(
        string='Drop Lube',
        currency_field='currency_id',
        default=0.0,
        help="dropamt_lube จาก FlowCo"
    )

    # ── Status ───────────────────────────────────────────────────────────
    pos_line_status = fields.Char(
        string='POS Status',
        help="status จาก FlowCo: 'OK' หรือ 'ERROR'"
    )
    is_error = fields.Boolean(
        string='Has Error',
        compute='_compute_is_error',
        store=True,
        help="True ถ้า pos_line_status != 'OK'"
    )

    # ── Drop discrepancy ─────────────────────────────────────────────────
    fuel_diff = fields.Monetary(
        string='Fuel Diff (Sale - Drop)',
        currency_field='currency_id',
        compute='_compute_diff',
        store=True,
        help="saleamt_fuel - dropamt_fuel — ส่วนต่างที่ยังไม่ได้ drop"
    )
    lube_diff = fields.Monetary(
        string='Lube Diff (Sale - Drop)',
        currency_field='currency_id',
        compute='_compute_diff',
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

    @api.depends('staff_external_id')
    def _compute_staff_record(self):
        """Lookup gas.station.staff by tag_id (RFID UID) matching staff_external_id."""
        Staff = self.env['gas.station.staff'].sudo()
        for rec in self:
            if rec.staff_external_id:
                staff = Staff.search(
                    [('tag_id', '=', rec.staff_external_id)], limit=1
                )
                rec.staff_record_id = staff.id if staff else False
            else:
                rec.staff_record_id = False

    @api.depends('pos_line_status')
    def _compute_is_error(self):
        for rec in self:
            rec.is_error = (rec.pos_line_status or '').upper() != 'OK'

    @api.depends('saleamt_fuel', 'dropamt_fuel', 'saleamt_lube', 'dropamt_lube')
    def _compute_diff(self):
        for rec in self:
            rec.fuel_diff = (rec.saleamt_fuel or 0.0) - (rec.dropamt_fuel or 0.0)
            rec.lube_diff = (rec.saleamt_lube or 0.0) - (rec.dropamt_lube or 0.0)