# -*- coding: utf-8 -*-
#
# File: gas_station_cash/models/gas_station_audit_pos.py
# Author: Pakkapon Jirachatmongkon
# Description: POS TCP Deposit integration from audit records.
#
from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class GasStationCashAudit(models.Model):
    _inherit = 'gas.station.cash.audit'   # <-- adjust if your audit model name is different

    # POS linkage / status
    pos_terminal_id = fields.Char(
        string="POS Terminal ID",
        help="External POS terminal ID, e.g. TERM-01."
    )
    pos_transaction_id = fields.Char(
        string="POS Transaction ID",
        help="Transaction ID sent to POS. Defaults to audit name if not set."
    )
    pos_status = fields.Selection(
        [
            ('not_sent', 'Not Sent'),
            ('sent', 'Sent to POS'),
            ('queued', 'Queued (POS Offline)'),
            ('failed', 'Failed'),
        ],
        string="POS Status",
        default='not_sent',
        readonly=True,
    )
    pos_job_id = fields.Many2one(
        'pos.tcp.job',
        string="POS TCP Job",
        readonly=True,
        help="Background job created when POS is offline."
    )
    pos_message = fields.Char(
        string="POS Message",
        readonly=True,
    )

    def _get_pos_staff_id(self):
        """
        Helper: map this audit's staff to POS staff_id.
        Adjust depending on your existing fields.
        """
        self.ensure_one()
        # Example mapping:
        # - If you have a Many2one to gas.station.staff:
        #   staff = self.staff_id
        #   return staff.external_id or staff.employee_id or staff.name
        staff = getattr(self, 'staff_id', False)
        if staff:
            # Try external_id, then employee_id, else name
            return (
                getattr(staff, 'external_id', False)
                or getattr(staff, 'employee_id', False)
                or staff.name
            )
        return "UNKNOWN"

    def _get_pos_terminal_id(self):
        """
        Helper: resolve terminal_id to send to POS.
        You can later map this from configuration or station.
        """
        self.ensure_one()
        return self.pos_terminal_id or "TERM-01"

    def _get_pos_transaction_id(self):
        """
        Helper: pick a stable transaction_id for POS.
        Prefer a sequence/name if available.
        """
        self.ensure_one()
        if self.pos_transaction_id:
            return self.pos_transaction_id
        # Fallback: use audit name or build from ID
        if getattr(self, 'name', False):
            return self.name
        return f"TXN-AUDIT-{self.id}"

    def _get_deposit_amount_for_pos(self):
        """
        Helper: choose which amount is sent as deposit.
        Adjust to your actual field name.
        """
        self.ensure_one()
        # Examples: self.amount_total, self.amount_cash, self.amount_deposit, etc.
        if hasattr(self, 'amount_total'):
            return self.amount_total
        if hasattr(self, 'amount_cash'):
            return self.amount_cash
        if hasattr(self, 'amount'):
            return self.amount
        raise ValueError("No amount field found on gas.station.cash.audit for POS deposit.")

    def action_send_pos_deposit(self):
        """
        Send this audit as a Deposit to POS over TCP.

        Uses JSON spec agreed with FirstPro:

        Request:
            POST /Deposit
            {
              "transaction_id": "TXN-20250926-12345",
              "staff_id": "CASHIER-0007",
              "amount": 4000
            }

        Response (example):
            {
              "transaction_id": "TXN-20250926-12345",
              "status": "OK",
              "discription": "Deposit Success",
              "time_stamp": "2025-09-26T17:45:00+07:00"
            }
        """
        for audit in self:
            connector = audit.env['pos.connector.mixin']

            transaction_id = audit._get_pos_transaction_id()
            staff_id = audit._get_pos_staff_id()
            amount = audit._get_deposit_amount_for_pos()
            terminal_id = audit._get_pos_terminal_id()

            _logger.info(
                "Sending POS Deposit from audit %s (txn=%s, staff=%s, amount=%s, terminal=%s)",
                audit.id, transaction_id, staff_id, amount, terminal_id,
            )

            res = connector.pos_send_deposit(
                transaction_id=transaction_id,
                staff_id=staff_id,
                amount=amount,
                terminal_id=terminal_id,
            )

            # Normalize write values
            vals = {
                'pos_transaction_id': transaction_id,
                'pos_message': res.get('message'),
            }

            if res.get('ok'):
                vals['pos_status'] = 'sent'
                vals['pos_job_id'] = False
            else:
                # Offline / error: queued for batch
                vals['pos_status'] = 'queued' if res.get('job_id') else 'failed'
                if res.get('job_id'):
                    vals['pos_job_id'] = res['job_id']

            audit.write(vals)

        return True
