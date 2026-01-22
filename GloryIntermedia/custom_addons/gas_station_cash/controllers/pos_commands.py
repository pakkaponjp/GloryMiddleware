# -*- coding: utf-8 -*-
"""
File: controllers/pos_commands.py
Description: POS Command Controller with CloseShift pending transaction handling.

CloseShift Flow:
1. POS sends POST /CloseShift with staff_id
2. Glory checks for pending transactions (deposits not sent to POS)
3. If pending transactions exist:
   - Send all pending transactions to POS first
   - Return FAILED status with "Sending pending transaction" message
4. If no pending transactions:
   - Process close shift normally
   - Return OK status with shift summary
"""

from odoo import http, fields
from odoo.http import request
import json
import uuid
import socket
import logging
import time
import threading

_logger = logging.getLogger(__name__)


class PosCommandController(http.Controller):

    def _create_command(self, action_key: str, staff_id: str, extra_payload: dict = None):
        """
        Create a POS command record for tracking and overlay display.
        """
        Command = request.env["gas.station.pos_command"].sudo()
        internal_req_id = uuid.uuid4().hex
        terminal_id = self._get_terminal_id()

        payload = {"staff_id": staff_id}
        if extra_payload:
            payload.update(extra_payload)

        cmd = Command.create({
            "name": f"{action_key} / {internal_req_id}",
            "action": action_key,
            "request_id": internal_req_id,
            "pos_terminal_id": terminal_id,
            "staff_external_id": staff_id,
            "status": "processing",
            "message": "processing...",
            "started_at": fields.Datetime.now(),
            "payload_in": json.dumps(payload, ensure_ascii=False),
        })
        return cmd

    def _get_terminal_id(self):
        """Get the POS terminal ID from configuration or default."""
        # TODO: Get from configuration or request headers
        return "TERM-01"

    def _json_response(self, payload: dict, status=200):
        """Create a JSON HTTP response."""
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status
        )

    # =========================================================================
    # PENDING TRANSACTION HANDLING
    # =========================================================================

    def _is_deposit_pos_related(self, deposit):
        """
        Check if a deposit should be sent to POS.
        
        POS-related deposits are:
        1. Oil Sales (deposit_type = 'oil')
        2. Engine Oil Sales (deposit_type = 'engine_oil')
        3. Any deposit with a product that has is_pos_related = True
        4. Any deposit with is_pos_related = True flag
        
        Args:
            deposit: gas.station.cash.deposit record
            
        Returns:
            bool: True if deposit should be sent to POS
        """
        # Check deposit type (oil and engine_oil are always POS-related)
        if deposit.deposit_type in ['oil', 'engine_oil']:
            return True
        
        # Check product's is_pos_related flag
        if deposit.product_id and deposit.product_id.is_pos_related:
            return True
        
        # Check deposit's own is_pos_related flag
        if deposit.is_pos_related:
            return True
        
        return False

    def _get_last_end_of_day(self, env=None):
        """
        Get the last successful EndOfDay command timestamp.
        
        Args:
            env: Odoo environment (optional, uses request.env if not provided)
            
        Returns:
            datetime or None: Timestamp of last EndOfDay, or None if never run
        """
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        last_eod = PosCommand.search([
            ('action', '=', 'end_of_day'),
            ('status', '=', 'done'),
        ], order='started_at desc', limit=1)
        
        if last_eod:
            # Use completed_at if available, otherwise started_at
            # Use getattr for safety in case completed_at field doesn't exist
            eod_time = getattr(last_eod, 'completed_at', None) or last_eod.started_at
            _logger.info("📅 Last EndOfDay: %s (ID: %s)", eod_time, last_eod.id)
            return eod_time
        
        _logger.info("📅 No EndOfDay found - this is the first day")
        return None

    def _get_last_close_shift(self, env=None, after_timestamp=None):
        """
        Get the last successful CloseShift command timestamp.
        
        Args:
            env: Odoo environment (optional, uses request.env if not provided)
            after_timestamp: Only look for CloseShift after this timestamp
            
        Returns:
            datetime or None: Timestamp of last CloseShift, or None if none found
        """
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        domain = [
            ('action', '=', 'close_shift'),
            ('status', '=', 'done'),
        ]
        
        # Only look for CloseShift after the given timestamp (usually last EndOfDay)
        if after_timestamp:
            domain.append(('started_at', '>', after_timestamp))
        
        last_shift = PosCommand.search(domain, order='started_at desc', limit=1)
        
        if last_shift:
            # Use completed_at if available, otherwise started_at
            # Use getattr for safety in case completed_at field doesn't exist
            shift_time = getattr(last_shift, 'completed_at', None) or last_shift.started_at
            _logger.info("📅 Last CloseShift: %s (ID: %s)", shift_time, last_shift.id)
            return shift_time
        
        _logger.info("📅 No CloseShift found after %s", after_timestamp)
        return None

    def _get_shift_start_time(self, env=None):
        """
        Get the start time of the current shift.
        
        Logic:
        1. Find the last EndOfDay (EOD) - this is the daily reset point
        2. Find the last CloseShift AFTER that EOD
        3. If CloseShift exists after EOD → shift starts from that CloseShift
        4. If no CloseShift after EOD → shift starts from EOD
        5. If no EOD ever → shift includes all transactions (first run)
        
        This supports overnight shifts (shifts that cross midnight).
        
        Args:
            env: Odoo environment (optional)
            
        Returns:
            datetime or None: Start time of current shift, None means all transactions
        """
        if env is None:
            env = request.env
        
        # Step 1: Find last EndOfDay
        last_eod = self._get_last_end_of_day(env)
        
        # Step 2: Find last CloseShift after that EndOfDay
        last_close_shift = self._get_last_close_shift(env, after_timestamp=last_eod)
        
        # Step 3: Determine shift start
        if last_close_shift:
            # There was a CloseShift after the last EOD - shift starts from there
            shift_start = last_close_shift
            _logger.info("📅 Shift starts from last CloseShift: %s", shift_start)
        elif last_eod:
            # No CloseShift after EOD - shift starts from EOD
            shift_start = last_eod
            _logger.info("📅 Shift starts from last EndOfDay: %s", shift_start)
        else:
            # No EOD ever - this is the first run, include all transactions
            shift_start = None
            _logger.info("📅 No shift history found - will include ALL transactions")
        
        return shift_start

    def _get_pending_transactions(self):
        """
        Get pending transactions within the current shift that need to be sent to POS.
        
        Pending transactions are deposits that:
        - Were created during the current shift (since last CloseShift or EndOfDay)
        - Are POS-related (oil, engine_oil, or has POS-related product/flag)
        - Have pos_status = 'queued' or 'failed' (meaning they were attempted but not successful)
        
        Note: pos_status = 'na' means NOT applicable (not POS related)
              pos_status = 'ok' means already sent successfully
        
        Returns:
            list: List of pending transaction records
        """
        pending = []
        
        shift_start = self._get_shift_start_time()
        _logger.info("📅 Shift start time: %s", shift_start)
        
        # Check Cash Deposits with queued or failed status within current shift
        CashDeposit = request.env["gas.station.cash.deposit"].sudo()
        
        # Build domain
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', 'in', ['queued', 'failed']),
        ]
        
        # Add shift start filter if we have a shift start time
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        # Get deposits that failed or are queued within this shift
        pending_deposits = CashDeposit.search(domain)
        
        # Filter to only POS-related deposits
        for deposit in pending_deposits:
            if self._is_deposit_pos_related(deposit):
                pending.append(deposit)
        
        _logger.info("Found %d pending deposits out of %d queued/failed (shift start: %s)", 
                    len(pending), len(pending_deposits), shift_start or "ALL TIME")
        
        return pending

    def _calculate_shift_pos_total(self, env, staff_id=None):
        """
        Calculate the total cash amount of POS-related deposits that have been 
        successfully sent to POS within the current shift.
        
        Args:
            env: Odoo environment
            staff_id: Optional staff ID to filter by (not used currently)
            
        Returns:
            dict: {
                'total_cash': Total amount sent to POS,
                'count': Number of successful transactions,
                'deposits': List of deposit references,
                'shift_start': When the shift started
            }
        """
        shift_start = self._get_shift_start_time(env)
        
        CashDeposit = env["gas.station.cash.deposit"].sudo()
        
        # Build domain
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', '=', 'ok'),  # Successfully sent to POS
        ]
        
        # Add shift start filter if we have a shift start time
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        # Get all deposits successfully sent to POS within this shift
        successful_deposits = CashDeposit.search(domain)
        
        # Filter to only POS-related deposits and sum amounts
        total_cash = 0.0
        pos_related_deposits = []
        
        for deposit in successful_deposits:
            if self._is_deposit_pos_related(deposit):
                total_cash += deposit.total_amount or 0.0
                pos_related_deposits.append(deposit.name)
        
        _logger.info("💰 Shift POS totals: %d deposits, %.2f total (since %s)", 
                    len(pos_related_deposits), total_cash, shift_start or "ALL TIME")
        _logger.debug("   Deposits: %s", pos_related_deposits)
        
        return {
            'total_cash': total_cash,
            'count': len(pos_related_deposits),
            'deposits': pos_related_deposits,
            'shift_start': shift_start.isoformat() if shift_start else None,
        }

    def _send_pending_transactions_async(self, dbname, uid, pending_ids, pending_model, cmd_id):
        """
        Background thread to send pending transactions to POS.
        
        Args:
            dbname: Database name
            uid: User ID
            pending_ids: List of pending record IDs
            pending_model: Model name of pending records
            cmd_id: Command ID for tracking
        """
        try:
            _logger.info("📤 Starting to send %d pending transactions...", len(pending_ids))
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                
                # Get the command record
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                # Process each pending transaction
                success_count = 0
                fail_count = 0
                
                for record_id in pending_ids:
                    try:
                        if pending_model == "gas.station.cash.deposit":
                            deposit = env[pending_model].sudo().browse(record_id)
                            if deposit.exists():
                                self._send_deposit_to_pos(env, deposit)
                                success_count += 1
                        elif pending_model == "gas.station.cash.audit":
                            audit = env[pending_model].sudo().browse(record_id)
                            if audit.exists():
                                audit.action_send_pos_deposit()
                                success_count += 1
                    except Exception as e:
                        _logger.error("❌ Failed to send pending transaction %s: %s", record_id, e)
                        fail_count += 1
                
                # Update command with results
                if cmd.exists():
                    result = {
                        "pending_sent": success_count,
                        "pending_failed": fail_count,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.write({
                        "status": "done" if fail_count == 0 else "partial",
                        "message": f"Sent {success_count} pending transactions, {fail_count} failed",
                        "payload_out": json.dumps(result, ensure_ascii=False),
                    })
                    cmd.push_overlay()
                    
                _logger.info("✅ Pending transactions processed: %d success, %d failed", 
                            success_count, fail_count)
                            
        except Exception as e:
            _logger.exception("❌ Failed to process pending transactions: %s", e)

    def _send_deposit_to_pos(self, env, deposit):
        """
        Send a single deposit to POS via TCP.
        
        Args:
            env: Odoo environment
            deposit: gas.station.cash.deposit record
            
        JSON format to POS:
        {
            "transaction_id": "TXN-1768137597...",
            "staff_id": "CASHIER-0007",
            "amount": 4000
        }
        """
        transaction_id = deposit.pos_transaction_id or deposit.name
        
        # Get staff external_id properly
        staff_id = "UNKNOWN"
        if deposit.staff_id:
            staff = deposit.staff_id
            # Try different field names for external ID
            staff_id = (
                getattr(staff, 'external_id', None) or
                getattr(staff, 'employee_id', None) or
                staff.name or
                "UNKNOWN"
            )
        
        amount = float(deposit.total_amount or 0)
        terminal_id = "TERM-01"
        
        _logger.info("📤 Sending deposit %s to POS (staff=%s, amount=%s)", 
                    transaction_id, staff_id, amount)
        
        # Send via TCP to POS
        try:
            result = self._send_tcp_to_pos(env, {
                "transaction_id": transaction_id,
                "staff_id": staff_id,
                "amount": amount,
            })
            logging.debug("message: Sent deposit to POS: %s", { "transaction_id": transaction_id, "staff_id": staff_id, "amount": amount })
            logging.debug("debug: POS response: %s", result)
            
            
            # Update deposit with POS response
            if result.get('status') == 'OK':
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'ok',
                    'pos_description': result.get('description', 'Deposit Success'),
                    'pos_time_stamp': result.get('time_stamp', ''),
                    'pos_response_json': json.dumps(result, ensure_ascii=False),
                    'pos_error': False,
                })
                _logger.info("✅ Deposit %s sent successfully", transaction_id)
                return True
            else:
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'failed',
                    'pos_description': result.get('description', ''),
                    'pos_error': result.get('error', 'Unknown error'),
                    'pos_response_json': json.dumps(result, ensure_ascii=False),
                })
                _logger.warning("⚠️ Deposit %s failed: %s", transaction_id, result)
                return False
                
        except Exception as e:
            _logger.exception("❌ Failed to send deposit %s: %s", transaction_id, e)
            deposit.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'queued',  # Queue for retry
                'pos_error': str(e),
            })
            return False

    def _send_tcp_to_pos(self, env, payload: dict):
        """
        Send JSON payload to POS via TCP socket.
        
        Args:
            env: Odoo environment
            payload: Dictionary to send as JSON
            
        Returns:
            dict: Response from POS
        """
        import socket
        
        # Get POS connection settings from system parameters
        ICP = env['ir.config_parameter'].sudo()
        host = ICP.get_param('pos.tcp.host', 'localhost')
        port = int(ICP.get_param('pos.tcp.port', '9001'))
        timeout = int(ICP.get_param('pos.tcp.timeout', '30'))
        
        _logger.info("📡 Connecting to POS at %s:%s...", host, port)
        
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            
            # Send JSON with newline (as expected by mock POS)
            message = json.dumps(payload, ensure_ascii=False) + "\n"
            _logger.info("📤 TX: %s", message.strip())
            sock.sendall(message.encode('utf-8'))
            
            # Receive response
            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break
            
            sock.close()
            
            response_str = response_data.decode('utf-8').strip()
            _logger.info("📥 RX: %s", response_str)
            
            return json.loads(response_str)
            
        except socket.timeout:
            _logger.warning("⏰ TCP timeout to POS at %s:%s", host, port)
            return {'status': 'error', 'error': 'Connection timeout', 'offline': True}
        except ConnectionRefusedError:
            _logger.warning("🚫 POS connection refused at %s:%s", host, port)
            return {'status': 'error', 'error': 'Connection refused', 'offline': True}
        except Exception as e:
            _logger.exception("❌ TCP error: %s", e)
            return {'status': 'error', 'error': str(e), 'offline': True}

    # =========================================================================
    # CLOSE SHIFT ENDPOINT
    # =========================================================================

    def _process_close_shift_async(self, dbname, uid, cmd_id, has_pending: bool):
        """
        Background thread to process close shift.
        
        If there were pending transactions, they have already been queued for sending.
        This marks the command as done after processing delay.
        """
        try:
            # Simulate processing time
            delay = 7 if has_pending else 5
            _logger.info("⏰ CloseShift processing started, waiting %d seconds...", delay)
            time.sleep(delay)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if cmd.exists():
                    _logger.info("✅ CloseShift delay complete, marking as DONE...")
                    
                    # Calculate shift POS totals
                    shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                    
                    result = {
                        "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{cmd.staff_external_id or 'AUTO'}-01",
                        "total_cash": shift_totals.get('total_cash', 0.0),
                        "total_transactions": shift_totals.get('count', 0),
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    _logger.info("✅ CloseShift command %s marked as DONE", cmd_id)
                else:
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process close shift async: %s", e)

    def _calculate_shift_totals(self, env, staff_id):
        """
        DEPRECATED: Use _calculate_shift_pos_total instead.
        Kept for backward compatibility.
        """
        return self._calculate_shift_pos_total(env, staff_id)

    #@http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    #def close_shift(self, **kwargs):
    def _handle_close_shift(self, **kwargs):
        """
        Handle CloseShift request from POS.
        
        Request:
            POST /CloseShift
            {
                "staff_id": "CASHIER-0007"
            }
        
        Response (Success - no pending transactions):
            {
                "shift_id": "SHIFT-20251002-AM-01",
                "status": "OK",
                "total_cash_amount": 100000.00,
                "discription": "Deposit Success",
                "time_stamp": "2025-09-26T17:45:00+07:00"
            }
        
        Response (Failed - pending transactions exist):
            {
                "shift_id": "",
                "status": "FAILED",
                "total_cash_amount": 0.00,
                "discription": "Sending pending transaction",
                "time_stamp": "2025-09-26T17:45:00+07:00",
                "pending_count": 5
            }
        """
        _logger.info("=" * 80)
        _logger.info("📥 CLOSE SHIFT REQUEST RECEIVED")
        _logger.info("🌐 PATH: %s", request.httprequest.path)
        
        # Parse request body
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("Raw request body: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in CloseShift request: %s", e)
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "total_cash_amount": 0.00,
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            _logger.warning("⚠️ Missing staff_id in CloseShift request")
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "total_cash_amount": 0.00,
                "discription": "Missing staff_id",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        _logger.info("Staff ID: %s", staff_id)
        
        # =====================================================================
        # CHECK FOR PENDING TRANSACTIONS
        # =====================================================================
        _logger.info("🔍 Checking for pending transactions...")
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            _logger.warning("⚠️ Found %d pending transactions", pending_count)
            
            # Create command to track pending transaction processing
            # Use "close_shift" action (valid selection value) with pending info in payload
            cmd = self._create_command("close_shift", staff_id, {
                "pending_count": pending_count,
                "is_pending_mode": True,
                "action_detail": "sending_pending"
            })
            
            # Push overlay to show "Sending pending transactions"
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("❌ Failed to push overlay: %s", e)
            
            # Start background thread to send pending transactions
            dbname = request.env.cr.dbname
            uid = request.env.uid
            
            # All pending are deposits (we filtered in _get_pending_transactions)
            deposit_ids = [p.id for p in pending_transactions]
            
            if deposit_ids:
                _logger.info("🚀 Starting async thread to send %d pending deposits...", len(deposit_ids))
                thread = threading.Thread(
                    target=self._send_pending_transactions_async,
                    args=(dbname, uid, deposit_ids, "gas.station.cash.deposit", cmd.id)
                )
                thread.daemon = True
                thread.start()
            
            # Return FAILED response with pending transaction message
            resp = {
                "shift_id": "",
                "status": "FAILED",
                "total_cash_amount": 0.00,
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
                "pending_count": pending_count,
            }
            
            _logger.info("📤 Sending response (FAILED - pending): %s", resp)
            _logger.info("=" * 80)
            
            return self._json_response(resp, status=200)
        
        # =====================================================================
        # NO PENDING TRANSACTIONS - PROCESS CLOSE SHIFT NORMALLY
        # =====================================================================
        _logger.info("✅ No pending transactions, proceeding with CloseShift")
        
        cmd = self._create_command("close_shift", staff_id)
        
        _logger.info("✅ Command created successfully")
        _logger.info("   - Command ID: %s", cmd.id)
        _logger.info("   - Request ID: %s", cmd.request_id)
        
        # Push initial overlay (processing)
        _logger.info("📤 Pushing initial overlay (processing)...")
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)
        
        # Calculate shift POS totals (only POS-related deposits with pos_status='ok')
        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        # Start background processing
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        _logger.info("🔄 Starting background processing thread...")
        thread = threading.Thread(
            target=self._process_close_shift_async, 
            args=(dbname, uid, cmd.id, False)
        )
        thread.daemon = True
        thread.start()
        
        # Build success response
        shift_id = f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id or 'AUTO'}-01"
        
        resp = {
            "shift_id": shift_id,
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "discription": "Deposit Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        
        _logger.info("📤 Sending response: %s", resp)
        _logger.info("=" * 80)
        
        return self._json_response(resp, status=200)
    
    # FirstPro route: /CloseShift
    @http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift(self, **kwargs):
        return self._handle_close_shift(**kwargs)


    # FlowCo route: /pos/CloseShift
    @http.route("/pos/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift_pos_prefix(self, **kwargs):
        return self._handle_close_shift(**kwargs)

    # =========================================================================
    # END OF DAY ENDPOINT
    # =========================================================================

    def _process_end_of_day_async(self, dbname, uid, cmd_id):
        """
        Background thread to process end of day.
        Calculates the final shift total and marks the command as done.
        """
        try:
            _logger.info("⏰ EndOfDay processing started, waiting 7 seconds...")
            time.sleep(7)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if cmd.exists():
                    _logger.info("✅ EndOfDay delay complete, marking as DONE...")
                    
                    # Calculate shift POS totals for the final shift
                    shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                    
                    # Count total shifts today (CloseShift commands since last EOD)
                    last_eod = self._get_last_end_of_day(env)
                    PosCommand = env["gas.station.pos_command"].sudo()
                    
                    shift_domain = [
                        ('action', '=', 'close_shift'),
                        ('status', '=', 'done'),
                    ]
                    if last_eod:
                        shift_domain.append(('started_at', '>', last_eod))
                    
                    total_shifts_today = PosCommand.search_count(shift_domain)
                    
                    result = {
                        "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                        "total_shifts": total_shifts_today + 1,  # +1 for this final shift
                        "final_shift_cash": shift_totals.get('total_cash', 0.0),
                        "final_shift_transactions": shift_totals.get('count', 0),
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    _logger.info("✅ EndOfDay command %s marked as DONE", cmd_id)
                    _logger.info("   Final shift: %d transactions, %.2f total", 
                                shift_totals.get('count', 0), shift_totals.get('total_cash', 0.0))
                else:
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process end of day async: %s", e)

    #@http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    #def end_of_day(self, **kwargs):
    def _handle_end_of_day(self, **kwargs):
        """
        Handle EndOfDay request from POS.
        
        Similar to CloseShift but for end of day reconciliation.
        Also checks for pending transactions first.
        """
        _logger.info("=" * 80)
        _logger.info("📥 END OF DAY REQUEST RECEIVED")
        _logger.info("🌐 PATH: %s", request.httprequest.path)
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("Raw request body: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in EndOfDay request: %s", e)
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "total_cash_amount": 0.00,
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            _logger.warning("⚠️ Missing staff_id in EndOfDay request")
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "total_cash_amount": 0.00,
                "discription": "Missing staff_id",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        _logger.info("Staff ID: %s", staff_id)
        
        # Check for pending transactions (same as CloseShift)
        _logger.info("🔍 Checking for pending transactions...")
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            _logger.warning("⚠️ Found %d pending transactions", pending_count)
            
            # Use "end_of_day" action (valid selection value) with pending info in payload
            cmd = self._create_command("end_of_day", staff_id, {
                "pending_count": pending_count,
                "is_pending_mode": True,
                "action_detail": "sending_pending"
            })
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("❌ Failed to push overlay: %s", e)
            
            # Send pending transactions in background
            dbname = request.env.cr.dbname
            uid = request.env.uid
            
            # All pending are deposits
            deposit_ids = [p.id for p in pending_transactions]
            
            if deposit_ids:
                _logger.info("🚀 Starting async thread to send %d pending deposits...", len(deposit_ids))
                thread = threading.Thread(
                    target=self._send_pending_transactions_async,
                    args=(dbname, uid, deposit_ids, "gas.station.cash.deposit", cmd.id)
                )
                thread.daemon = True
                thread.start()
            
            resp = {
                "shift_id": "",
                "status": "FAILED",
                "total_cash_amount": 0.00,
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
                "pending_count": pending_count,
            }
            
            _logger.info("📤 Sending response (FAILED - pending): %s", resp)
            _logger.info("=" * 80)
            
            return self._json_response(resp, status=200)
        
        # No pending transactions - process EndOfDay normally
        _logger.info("✅ No pending transactions, proceeding with EndOfDay")
        
        cmd = self._create_command("end_of_day", staff_id)
        
        _logger.info("✅ Command created successfully")
        _logger.info("   - Command ID: %s", cmd.id)
        
        _logger.info("📤 Pushing initial overlay (processing)...")
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)

        # Calculate the final shift total (from last CloseShift to now)
        # This is the same as CloseShift - it counts the current shift's POS deposits
        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        # Start background processing
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        _logger.info("🔄 Starting background processing thread...")
        thread = threading.Thread(
            target=self._process_end_of_day_async, 
            args=(dbname, uid, cmd.id)
        )
        thread.daemon = True
        thread.start()

        # Build success response with shift total
        shift_id = f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id or 'AUTO'}-EOD"
        
        resp = {
            "shift_id": shift_id,
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "discription": "Deposit Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        
        _logger.info("📤 Sending response: %s", resp)
        _logger.info("=" * 80)
        
        return self._json_response(resp, status=200)
    
    # FirstPro route: /EndOfDay
    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        return self._handle_end_of_day(**kwargs)
    
    
    # FlowCo route: /pos/EndOfDay
    @http.route("/pos/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day_pos_prefix(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    # =========================================================================
    # DEPOSIT ENDPOINT (Glory -> POS)
    # =========================================================================

    @http.route("/Deposit", type="http", auth="public", methods=["POST"], csrf=False)
    def deposit(self, **kwargs):
        """
        Handle Deposit request from Glory Cash Recycler.
        
        Request (from Glory):
            POST /Deposit
            {
                "transaction_id": "TXN-20250926-12345",
                "staff_id": "CASHIER-0007",
                "amount": 4000
            }
        
        Response:
            {
                "transaction_id": "TXN-20250926-12345",
                "status": "OK",
                "discription": "Deposit Success",
                "time_stamp": "2025-09-26T17:45:00+07:00"
            }
        """
        _logger.info("=" * 80)
        _logger.info("📥 DEPOSIT REQUEST RECEIVED (from Glory)")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("Raw request body: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in Deposit request: %s", e)
            return self._json_response({
                "transaction_id": "",
                "status": "FAILED", 
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        transaction_id = data.get("transaction_id")
        staff_id = data.get("staff_id")
        amount = data.get("amount", 0)
        
        if not transaction_id:
            return self._json_response({
                "transaction_id": "",
                "status": "FAILED",
                "discription": "Missing transaction_id",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)
        
        if not staff_id:
            return self._json_response({
                "transaction_id": transaction_id,
                "status": "FAILED",
                "discription": "Missing staff_id",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)
        
        _logger.info("Transaction ID: %s", transaction_id)
        _logger.info("Staff ID: %s", staff_id)
        _logger.info("Amount: %s", amount)
        
        # Forward deposit to POS
        try:
            connector = request.env['pos.connector.mixin'].sudo()
            res = connector.pos_send_deposit(
                transaction_id=transaction_id,
                staff_id=staff_id,
                amount=amount,
                terminal_id=self._get_terminal_id(),
            )
            
            if res.get('ok'):
                resp = {
                    "transaction_id": transaction_id,
                    "status": "OK",
                    "discription": "Deposit Success",
                    "time_stamp": fields.Datetime.now().isoformat(),
                }
            else:
                resp = {
                    "transaction_id": transaction_id,
                    "status": "FAILED",
                    "discription": res.get('message', 'POS communication error'),
                    "time_stamp": fields.Datetime.now().isoformat(),
                }
        except Exception as e:
            _logger.exception("❌ Failed to send deposit to POS: %s", e)
            resp = {
                "transaction_id": transaction_id,
                "status": "FAILED",
                "discription": str(e),
                "time_stamp": fields.Datetime.now().isoformat(),
            }
        
        _logger.info("📤 Sending response: %s", resp)
        _logger.info("=" * 80)
        
        return self._json_response(resp, status=200)

    # =========================================================================
    # HEARTBEAT ENDPOINT
    # =========================================================================

    #@http.route("/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    #def heartbeat(self, **kwargs):
    def _handle_heartbeat(self, **kwargs):
        """
        Handle HeartBeat request (bidirectional between Glory and POS).
        
        Request:
            POST /HeartBeat
            {
                "source_system": "POS",
                "pos_terminal_id": "TERM-01",
                "status": "OK",
                "timestamp": "2025-09-26T17:46:00+07:00"
            }
        
        Response:
            {
                "status": "acknowledged",
                "pos_terminal_id": "TERM-01",
                "timestamp": "2025-09-26T17:46:01+07:00"
            }
        """
        _logger.info("💓 HEARTBEAT REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in HeartBeat request: %s", e)
            return self._json_response({
                "status": "error",
                "timestamp": fields.Datetime.now().isoformat(),
            }, status=400)

        source_system = data.get("source_system", "UNKNOWN")
        terminal_id = data.get("pos_terminal_id", self._get_terminal_id())
        
        _logger.info("HeartBeat from: %s (terminal: %s)", source_system, terminal_id)
        
        resp = {
            "status": "acknowledged",
            "pos_terminal_id": terminal_id,
            "timestamp": fields.Datetime.now().isoformat(),
        }
        
        return self._json_response(resp, status=200)
    
    # FirstPro route: /HeartBeat
    @http.route("/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat(self, **kwargs):
        return self._handle_heartbeat(**kwargs)


    # FlowCo route: /pos/HeartBeat
    @http.route("/pos/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat_pos_prefix(self, **kwargs):
        return self._handle_heartbeat(**kwargs)