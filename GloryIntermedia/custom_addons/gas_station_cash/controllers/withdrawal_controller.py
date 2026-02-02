# -*- coding: utf-8 -*-
"""
File: controllers/withdrawal_controller.py
Description: Backend controller for cash withdrawal audit operations

Endpoints:
    POST /gas_station_cash/withdrawal/finalize - Create withdrawal audit record
    POST /gas_station_cash/withdrawal/update_status - Update Glory status
    POST /gas_station_cash/withdrawal/history - Get withdrawal history
"""

from odoo import http, fields
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)


class WithdrawalController(http.Controller):

    # =========================================================================
    # FINALIZE WITHDRAWAL (Create Audit Record)
    # =========================================================================

    @http.route('/gas_station_cash/withdrawal/finalize', type='json', auth='user', methods=['POST'], csrf=False)
    def withdrawal_finalize(self, **kw):
        """
        Finalize a withdrawal transaction and create audit record.
        
        Expected payload:
        {
            "transaction_id": "WDR-123456",
            "staff_id": "EMP001",           # staff external_id
            "amount": 1000,                  # total amount in THB
            "withdrawal_type": "general",    # general|change|expense|transfer
            "reason": "Optional reason",
            "currency": "THB",
            "breakdown": {
                "notes": [{"value": 1000, "qty": 1}, {"value": 500, "qty": 2}],
                "coins": [{"value": 10, "qty": 5}]
            },
            "glory_session_id": "1",
            "glory_response": {}             # raw Glory response (optional)
        }
        
        Returns:
        {
            "status": "OK" | "FAILED",
            "message": "...",
            "withdrawal_id": 123,
            "reference": "WDR00001"
        }
        """
        _logger.info("=" * 60)
        _logger.info("📤 WITHDRAWAL FINALIZE REQUEST")
        _logger.info("Payload: %s", kw)
        
        try:
            # Extract fields from payload
            transaction_id = kw.get("transaction_id")
            staff_external_id = kw.get("staff_id")
            amount = kw.get("amount", 0)
            withdrawal_type = kw.get("withdrawal_type", "general")
            reason = kw.get("reason", "")
            currency = kw.get("currency", "THB")
            breakdown = kw.get("breakdown", {})
            glory_session_id = kw.get("glory_session_id")
            glory_response = kw.get("glory_response", {})
            
            # Validate required fields
            if not staff_external_id:
                _logger.error("❌ Missing staff_id")
                return {
                    "status": "FAILED",
                    "message": "Missing staff_id",
                }
            
            if amount <= 0:
                _logger.error("❌ Invalid amount: %s", amount)
                return {
                    "status": "FAILED",
                    "message": "Invalid amount",
                }
            
            # Validate withdrawal_type
            valid_types = ["general", "change", "expense", "transfer"]
            if withdrawal_type not in valid_types:
                withdrawal_type = "general"
            
            # Find staff by external_id
            Staff = request.env["gas.station.staff"].sudo()
            staff = Staff.search([("external_id", "=", staff_external_id)], limit=1)
            
            if not staff:
                # Try by employee_id
                staff = Staff.search([("employee_id", "=", staff_external_id)], limit=1)
            
            if not staff:
                _logger.error("❌ Staff not found: %s", staff_external_id)
                return {
                    "status": "FAILED",
                    "message": f"Staff not found: {staff_external_id}",
                }
            
            _logger.info("✅ Staff found: %s (id=%s)", staff.name, staff.id)
            
            # Prepare withdrawal lines from breakdown
            withdrawal_lines = []
            notes = breakdown.get("notes", [])
            coins = breakdown.get("coins", [])
            
            for note in notes:
                qty = note.get("qty", 0)
                value = note.get("value", 0)
                if qty > 0 and value > 0:
                    withdrawal_lines.append((0, 0, {
                        "denomination_type": "note",
                        "currency_denomination": value,
                        "quantity": qty,
                    }))
            
            for coin in coins:
                qty = coin.get("qty", 0)
                value = coin.get("value", 0)
                if qty > 0 and value > 0:
                    withdrawal_lines.append((0, 0, {
                        "denomination_type": "coin",
                        "currency_denomination": value,
                        "quantity": qty,
                    }))
            
            # If no breakdown lines, create single line with total amount
            if not withdrawal_lines:
                withdrawal_lines.append((0, 0, {
                    "denomination_type": "note",
                    "currency_denomination": amount,
                    "quantity": 1,
                }))
            
            # Create withdrawal record
            Withdrawal = request.env["gas.station.cash.withdrawal"].sudo()
            
            withdrawal_vals = {
                "staff_id": staff.id,
                "date": fields.Datetime.now(),
                "withdrawal_type": withdrawal_type,
                "reason": reason or f"Withdrawal via Cash Recycler",
                "glory_session_id": glory_session_id,
                "glory_transaction_id": transaction_id,
                "glory_status": "collected",  # User finished flow = cash collected
                "glory_response_json": json.dumps(glory_response, ensure_ascii=False) if glory_response else "",
                "withdrawal_line_ids": withdrawal_lines,
                "state": "confirmed",  # Auto-confirm since it came from machine
            }
            
            withdrawal = Withdrawal.create(withdrawal_vals)
            
            _logger.info("✅ Withdrawal audit created: %s (id=%s, amount=%s)", 
                        withdrawal.name, withdrawal.id, withdrawal.total_amount)
            _logger.info("=" * 60)
            
            return {
                "status": "OK",
                "message": "Withdrawal recorded successfully",
                "withdrawal_id": withdrawal.id,
                "reference": withdrawal.name,
            }
            
        except Exception as e:
            _logger.exception("❌ Withdrawal finalize error: %s", e)
            return {
                "status": "FAILED",
                "message": str(e),
            }

    # =========================================================================
    # UPDATE GLORY STATUS
    # =========================================================================

    @http.route('/gas_station_cash/withdrawal/update_status', type='json', auth='user', methods=['POST'], csrf=False)
    def withdrawal_update_status(self, **kw):
        """
        Update Glory status for a withdrawal record.
        
        Expected payload:
        {
            "withdrawal_id": 123,
            "glory_status": "collected",  # pending|dispensed|collected|failed
            "glory_response": {}
        }
        """
        _logger.info("📤 WITHDRAWAL STATUS UPDATE: %s", kw)
        
        try:
            withdrawal_id = kw.get("withdrawal_id")
            glory_status = kw.get("glory_status")
            glory_response = kw.get("glory_response", {})
            
            if not withdrawal_id:
                return {"status": "FAILED", "message": "Missing withdrawal_id"}
            
            # Validate glory_status
            valid_statuses = ["pending", "dispensed", "collected", "failed"]
            if glory_status and glory_status not in valid_statuses:
                return {"status": "FAILED", "message": f"Invalid glory_status: {glory_status}"}
            
            Withdrawal = request.env["gas.station.cash.withdrawal"].sudo()
            withdrawal = Withdrawal.browse(int(withdrawal_id))
            
            if not withdrawal.exists():
                return {"status": "FAILED", "message": "Withdrawal not found"}
            
            update_vals = {}
            if glory_status:
                update_vals["glory_status"] = glory_status
            if glory_response:
                update_vals["glory_response_json"] = json.dumps(glory_response, ensure_ascii=False)
            
            if update_vals:
                withdrawal.write(update_vals)
                _logger.info("✅ Withdrawal %s status updated to: %s", withdrawal.name, glory_status)
            
            return {
                "status": "OK",
                "message": "Status updated",
                "withdrawal_id": withdrawal.id,
                "reference": withdrawal.name,
            }
            
        except Exception as e:
            _logger.exception("❌ Withdrawal status update error: %s", e)
            return {"status": "FAILED", "message": str(e)}

    # =========================================================================
    # WITHDRAWAL HISTORY
    # =========================================================================

    @http.route("/gas_station_cash/withdrawal/history", type="json", auth="user", methods=["POST"])
    def get_withdrawal_history(self, limit=50, staff_id=None, date_from=None, date_to=None, **kwargs):
        """
        Get withdrawal history.
        
        Request:
        {
            "limit": 50,
            "staff_id": "CASHIER-001",  // optional - filter by staff external_id
            "date_from": "2026-01-01",  // optional
            "date_to": "2026-01-31"     // optional
        }
        
        Response:
        {
            "status": "OK",
            "count": 10,
            "withdrawals": [
                {
                    "id": 1,
                    "reference": "WDR00001",
                    "staff_name": "John Doe",
                    "amount": 5000,
                    "withdrawal_type": "general",
                    "date": "2026-01-22 10:30:00",
                    "state": "confirmed",
                    "glory_status": "collected"
                }
            ]
        }
        """
        _logger.info("📋 Getting withdrawal history (limit=%s, staff=%s)", limit, staff_id)
        
        try:
            Withdrawal = request.env["gas.station.cash.withdrawal"].sudo()
            
            domain = []
            
            # Filter by staff
            if staff_id:
                Staff = request.env["gas.station.staff"].sudo()
                staff = Staff.search([
                    "|",
                    ("external_id", "=", staff_id),
                    ("employee_id", "=", staff_id),
                ], limit=1)
                if staff:
                    domain.append(("staff_id", "=", staff.id))
            
            # Filter by date range
            if date_from:
                domain.append(("date", ">=", date_from))
            if date_to:
                domain.append(("date", "<=", date_to))
            
            # Query records
            records = Withdrawal.search(domain, limit=int(limit), order="date desc")
            
            withdrawals = []
            for rec in records:
                withdrawals.append({
                    "id": rec.id,
                    "reference": rec.name,
                    "staff_id": rec.staff_id.id,
                    "staff_name": rec.staff_id.name,
                    "staff_external_id": rec.staff_id.external_id,
                    "amount": rec.total_amount,
                    "withdrawal_type": rec.withdrawal_type,
                    "reason": rec.reason or "",
                    "date": rec.date.isoformat() if rec.date else "",
                    "state": rec.state,
                    "glory_status": rec.glory_status,
                    "glory_transaction_id": rec.glory_transaction_id or "",
                })
            
            return {
                "status": "OK",
                "count": len(withdrawals),
                "withdrawals": withdrawals,
            }
            
        except Exception as e:
            _logger.exception("❌ Withdrawal history error: %s", e)
            return {"status": "FAILED", "message": str(e), "withdrawals": []}

    # =========================================================================
    # LEGACY ENDPOINT (for backward compatibility)
    # =========================================================================

    @http.route("/gas_station_cash/withdrawal/process", type="json", auth="user", methods=["POST"])
    def process_withdrawal(self, staff_id=None, staff_name=None, amount=None, **kwargs):
        """
        Legacy endpoint - redirects to finalize.
        Kept for backward compatibility.
        """
        _logger.info("📤 Legacy withdrawal/process called, redirecting to finalize")
        
        return self.withdrawal_finalize(
            transaction_id=f"WDR-{fields.Datetime.now().strftime('%Y%m%d%H%M%S')}",
            staff_id=staff_id,
            amount=amount or 0,
            withdrawal_type="general",
            reason=f"Withdrawal by {staff_name or staff_id}",
            **kwargs
        )