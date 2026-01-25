# -*- coding: utf-8 -*-
"""
File: controllers/withdrawal_controller.py
Description: Backend controller for cash withdrawal operations

Endpoints:
    POST /gas_station_cash/withdrawal/process - Process a withdrawal
    GET  /gas_station_cash/withdrawal/history - Get withdrawal history
"""

from odoo import http, fields
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)


class WithdrawalController(http.Controller):

    @http.route("/gas_station_cash/withdrawal/process", type="json", auth="user", methods=["POST"])
    def process_withdrawal(self, staff_id=None, staff_name=None, amount=None, **kwargs):
        """
        Process a cash withdrawal request.
        
        Request:
            {
                "staff_id": "CASHIER-001",
                "staff_name": "John Doe",
                "amount": 5000
            }
        
        Response (Success):
            {
                "status": "ok",
                "withdrawal_id": 123,
                "transaction_id": "WD-20260122-001",
                "amount": 5000,
                "message": "Withdrawal successful"
            }
        
        Response (Failed):
            {
                "status": "failed",
                "message": "Insufficient funds"
            }
        """
        _logger.info("=" * 60)
        _logger.info("💵 WITHDRAWAL REQUEST RECEIVED")
        _logger.info("   Staff ID: %s", staff_id)
        _logger.info("   Staff Name: %s", staff_name)
        _logger.info("   Amount: %s", amount)
        
        # Validate inputs
        if not staff_id:
            _logger.warning("❌ Missing staff_id")
            return {"status": "failed", "message": "Missing staff_id"}
        
        if not amount or float(amount) <= 0:
            _logger.warning("❌ Invalid amount: %s", amount)
            return {"status": "failed", "message": "Invalid amount"}
        
        amount = float(amount)
        
        try:
            # TODO: Step 1 - Check available cash in Glory
            # glory_balance = self._get_glory_balance()
            # if glory_balance < amount:
            #     return {"status": "failed", "message": "Insufficient funds"}
            
            # TODO: Step 2 - Send withdrawal command to Glory Cash Recycler
            # glory_result = self._glory_dispense(amount)
            # if not glory_result.get('success'):
            #     return {"status": "failed", "message": glory_result.get('error')}
            
            # TODO: Step 3 - Create withdrawal record in Odoo
            withdrawal_record = self._create_withdrawal_record(
                staff_id=staff_id,
                staff_name=staff_name,
                amount=amount,
            )
            
            _logger.info("✅ Withdrawal processed successfully")
            _logger.info("   Withdrawal ID: %s", withdrawal_record.get('id'))
            _logger.info("   Transaction ID: %s", withdrawal_record.get('transaction_id'))
            
            return {
                "status": "ok",
                "withdrawal_id": withdrawal_record.get('id'),
                "transaction_id": withdrawal_record.get('transaction_id'),
                "amount": amount,
                "message": "Withdrawal successful",
            }
            
        except Exception as e:
            _logger.exception("❌ Withdrawal failed: %s", e)
            return {"status": "failed", "message": str(e)}
        
        finally:
            _logger.info("=" * 60)

    def _create_withdrawal_record(self, staff_id, staff_name, amount):
        """
        Create a withdrawal record in Odoo.
        
        TODO: Create proper model gas.station.cash.withdrawal
        For now, we just return a mock record.
        """
        _logger.info("📝 Creating withdrawal record...")
        
        # Generate transaction ID
        transaction_id = f"WD-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # TODO: Create actual record in Odoo
        # Withdrawal = request.env['gas.station.cash.withdrawal'].sudo()
        # record = Withdrawal.create({
        #     'name': transaction_id,
        #     'staff_external_id': staff_id,
        #     'staff_name': staff_name,
        #     'amount': amount,
        #     'state': 'done',
        #     'date': fields.Datetime.now(),
        # })
        
        # Mock response for now
        return {
            'id': 1,  # TODO: return actual record ID
            'transaction_id': transaction_id,
        }

    def _get_glory_balance(self):
        """
        Get current cash balance from Glory Cash Recycler.
        
        TODO: Implement actual Glory API call
        """
        _logger.info("TODO: _get_glory_balance - Get balance from Glory")
        return 100000.0  # Mock balance

    def _glory_dispense(self, amount):
        """
        Send dispense command to Glory Cash Recycler.
        
        TODO: Implement actual Glory API call
        
        Args:
            amount: Amount to dispense
            
        Returns:
            dict: {success: bool, dispensed: float, error: str}
        """
        _logger.info("TODO: _glory_dispense - Dispense %.2f from Glory", amount)
        
        # TODO: Call Glory API endpoint
        # Example: POST /api/dispense
        # Body: {"amount": amount}
        
        return {
            'success': True,
            'dispensed': amount,
            'error': None,
        }

    @http.route("/gas_station_cash/withdrawal/history", type="json", auth="user", methods=["POST"])
    def get_withdrawal_history(self, limit=50, staff_id=None, **kwargs):
        """
        Get withdrawal history.
        
        Request:
            {
                "limit": 50,
                "staff_id": "CASHIER-001"  // optional
            }
        
        Response:
            {
                "status": "ok",
                "withdrawals": [
                    {
                        "id": 1,
                        "transaction_id": "WD-20260122-001",
                        "staff_id": "CASHIER-001",
                        "staff_name": "John Doe",
                        "amount": 5000,
                        "date": "2026-01-22 10:30:00",
                        "state": "done"
                    }
                ]
            }
        """
        _logger.info("📋 Getting withdrawal history (limit=%s, staff=%s)", limit, staff_id)
        
        # TODO: Query actual records from Odoo
        # Withdrawal = request.env['gas.station.cash.withdrawal'].sudo()
        # domain = []
        # if staff_id:
        #     domain.append(('staff_external_id', '=', staff_id))
        # records = Withdrawal.search(domain, limit=limit, order='date desc')
        
        # Mock response for now
        return {
            "status": "ok",
            "withdrawals": [],
        }