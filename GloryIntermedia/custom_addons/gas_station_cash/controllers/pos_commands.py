# -*- coding: utf-8 -*-
"""
File: controllers/pos_commands.py
Description: POS Command Controller with CloseShift/EndOfDay and Collection Box handling.

CloseShift Flow:
1. POS sends POST /CloseShift with staff_id
2. Glory checks for pending transactions (deposits not sent to POS)
3. If pending transactions exist:
   - Send all pending transactions to POS first
   - Return FAILED status with "Sending pending transaction" message
4. If no pending transactions:
   - Check if close_shift_collect_cash is enabled
   - If enabled, collect cash to collection box
   - Return OK status with shift summary

EndOfDay Flow:
1. POS sends POST /EndOfDay with staff_id
2. Glory checks for pending transactions
3. If pending transactions exist:
   - Send all pending transactions to POS first
   - Return FAILED status
4. If no pending transactions:
   - Check end_of_day_collect_mode (all | except_reserve)
   - Collect cash to collection box accordingly
   - Return OK status with day summary

Collection Box Configuration (odoo.conf):
    [options]
    ; CloseShift: Whether to collect cash to box on shift close
    close_shift_collect_cash = true
    
    ; EndOfDay: How to collect cash
    ; - all: Collect all cash to box
    ; - except_reserve: Keep reserve/change amount, collect the rest
    end_of_day_collect_mode = except_reserve
    
    ; Reserve amount to keep (when except_reserve mode)
    end_of_day_reserve_amount = 5000
"""

from odoo import http, fields, tools
from odoo.http import request
import configparser
import json
import uuid
import socket
import logging
import time
import threading

_logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION READER
# =============================================================================

def _read_collection_config():
    """
    Read Collection Box settings from odoo.conf
    
    Returns:
        dict: {
            'close_shift_collect_cash': bool,
            'end_of_day_collect_mode': 'all' | 'except_reserve',
            'end_of_day_reserve_amount': float,
        }
    """
    config = tools.config
    
    # CloseShift: Whether to collect cash
    close_shift_collect = config.get('close_shift_collect_cash', 'false')
    close_shift_collect = str(close_shift_collect).lower() in ('true', '1', 'yes')
    
    # EndOfDay: Collection mode
    eod_collect_mode = config.get('end_of_day_collect_mode', 'except_reserve')
    if eod_collect_mode not in ('all', 'except_reserve'):
        eod_collect_mode = 'except_reserve'
    
    # EndOfDay: Reserve amount to keep
    try:
        eod_reserve_amount = float(config.get('end_of_day_reserve_amount', 5000))
    except (ValueError, TypeError):
        eod_reserve_amount = 5000.0
    
    return {
        'close_shift_collect_cash': close_shift_collect,
        'end_of_day_collect_mode': eod_collect_mode,
        'end_of_day_reserve_amount': eod_reserve_amount,
    }


def _read_pos_conf():
    """
    Read POS settings from odoo.conf section [pos_tcp_config]
    """
    conf_path = getattr(tools.config, "rcfile", None)
    if not conf_path:
        return {}

    parser = configparser.ConfigParser()
    parser.read(conf_path)

    if not parser.has_section("pos_tcp_config"):
        return {}

    section = parser["pos_tcp_config"]

    pos_vendor = section.get("pos_vendor", "firstpro").strip().lower()
    pos_host = section.get("pos_host", "127.0.0.1").strip()
    pos_port = section.get("pos_port", "9001").strip()
    pos_timeout = section.get("pos_timeout", "5.0").strip()

    if pos_host == "0.0.0.0":
        pos_host = "127.0.0.1"

    try:
        pos_port = int(pos_port)
    except Exception:
        pos_port = 9001

    try:
        pos_timeout = float(pos_timeout)
    except Exception:
        pos_timeout = 5.0

    return {
        "pos_vendor": pos_vendor,
        "pos_host": pos_host,
        "pos_port": pos_port,
        "pos_timeout": pos_timeout,
    }


class PosCommandController(http.Controller):

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_command(self, action_key: str, staff_id: str, extra_payload: dict = None, pos_shift_id: str = None):
        """Create a POS command record for tracking and overlay display."""
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
            "pos_shift_id": pos_shift_id,  # Store POS shift ID
            "status": "processing",
            "message": "processing...",
            "started_at": fields.Datetime.now(),
            "payload_in": json.dumps(payload, ensure_ascii=False),
        })
        return cmd

    def _get_terminal_id(self):
        """Get the POS terminal ID from configuration or default."""
        return tools.config.get('pos_terminal_id', 'TERM-01')

    def _get_default_staff_id(self):
        """Get default staff_id when not provided in request."""
        # Try from odoo.conf
        staff_id = tools.config.get('pos_default_staff_id')
        if staff_id:
            return staff_id
        
        # Try from request headers
        staff_id = request.httprequest.headers.get('X-Staff-ID')
        if staff_id:
            return staff_id
        
        return "DEFAULT-STAFF"

    def _json_response(self, payload: dict, status=200):
        """Create a JSON HTTP response."""
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status
        )

    # =========================================================================
    # COLLECTION BOX FUNCTIONS
    # =========================================================================

    def _collect_to_box(self, env, mode: str, staff_id: str = None, reserve_amount: float = 0):
        """
        Collect cash to collection box via Glory Cash Recycler.
        
        This is the central function for collecting cash, used by both
        CloseShift and EndOfDay processes.
        
        Args:
            env: Odoo environment
            mode: Collection mode
                - 'all': Collect all cash to box
                - 'except_reserve': Keep reserve amount, collect the rest
            staff_id: Staff ID performing the collection (for logging)
            reserve_amount: Amount to keep when mode='except_reserve'
            
        Returns:
            dict: {
                'success': bool,
                'collected_amount': float,
                'reserve_kept': float,
                'error': str or None,
                'glory_response': dict,
            }
        
        TODO: Implement actual Glory API call for collection
        """
        _logger.info("=" * 60)
        _logger.info("📦 COLLECTION BOX - Starting collection")
        _logger.info("   Mode: %s", mode)
        _logger.info("   Staff: %s", staff_id)
        _logger.info("   Reserve Amount: %.2f", reserve_amount)
        
        result = {
            'success': False,
            'collected_amount': 0.0,
            'reserve_kept': 0.0,
            'error': None,
            'glory_response': {},
        }
        
        try:
            # TODO: Step 1 - Get current cash inventory from Glory
            # glory_inventory = self._glory_get_inventory(env)
            # current_cash = glory_inventory.get('total_amount', 0)
            current_cash = 0.0  # Placeholder
            
            _logger.info("   Current Cash: %.2f (TODO: Get from Glory)", current_cash)
            
            # TODO: Step 2 - Calculate amount to collect
            if mode == 'all':
                # Collect everything
                collect_amount = current_cash
                keep_amount = 0.0
            elif mode == 'except_reserve':
                # Keep reserve, collect the rest
                keep_amount = min(reserve_amount, current_cash)
                collect_amount = max(0, current_cash - reserve_amount)
            else:
                _logger.warning("   Unknown mode: %s, defaulting to 'all'", mode)
                collect_amount = current_cash
                keep_amount = 0.0
            
            _logger.info("   Amount to Collect: %.2f", collect_amount)
            _logger.info("   Amount to Keep: %.2f", keep_amount)
            
            if collect_amount <= 0:
                _logger.info("   No cash to collect, skipping Glory API call")
                result['success'] = True
                result['collected_amount'] = 0.0
                result['reserve_kept'] = keep_amount
                return result
            
            # TODO: Step 3 - Send collection command to Glory
            # glory_response = self._glory_collect_to_box(env, collect_amount)
            glory_response = {
                'status': 'OK',
                'collected': collect_amount,
                'message': 'TODO: Implement Glory collection API',
            }
            
            _logger.info("   Glory Response: %s (TODO: Implement)", glory_response)
            
            # TODO: Step 4 - Create collection record in Odoo
            # self._create_collection_record(env, staff_id, collect_amount, mode)
            
            result['success'] = True
            result['collected_amount'] = collect_amount
            result['reserve_kept'] = keep_amount
            result['glory_response'] = glory_response
            
            _logger.info("📦 COLLECTION BOX - Success!")
            _logger.info("   Collected: %.2f", collect_amount)
            _logger.info("   Reserved: %.2f", keep_amount)
            
        except Exception as e:
            _logger.exception("📦 COLLECTION BOX - Error: %s", e)
            result['error'] = str(e)
        
        _logger.info("=" * 60)
        return result

    def _glory_get_inventory(self, env):
        """
        Get current cash inventory from Glory Cash Recycler.
        
        TODO: Implement actual Glory API call
        
        Returns:
            dict: {
                'total_amount': float,
                'denominations': [
                    {'value': 1000, 'count': 10},
                    {'value': 500, 'count': 20},
                    ...
                ]
            }
        """
        _logger.info("TODO: _glory_get_inventory - Get inventory from Glory")
        
        # TODO: Call Glory API endpoint
        # Example: POST /api/inventory or similar
        
        return {
            'total_amount': 0.0,
            'denominations': [],
        }

    def _glory_collect_to_box(self, env, amount: float):
        """
        Send collection command to Glory Cash Recycler.
        
        This tells the Glory machine to move cash from the recycler
        to the collection box.
        
        TODO: Implement actual Glory API call
        
        Args:
            env: Odoo environment
            amount: Amount to collect (or 'all' for everything)
            
        Returns:
            dict: Glory response
        """
        _logger.info("TODO: _glory_collect_to_box - Send collection command to Glory")
        _logger.info("   Amount: %.2f", amount)
        
        # TODO: Call Glory API endpoint
        # Example: POST /api/collect_to_box
        # Body: {"amount": amount} or {"mode": "all"}
        
        return {
            'status': 'OK',
            'collected': amount,
            'timestamp': fields.Datetime.now().isoformat(),
        }

    def _create_collection_record(self, env, staff_id: str, amount: float, mode: str):
        """
        Create a collection record in Odoo for audit trail.
        
        TODO: Create model gas.station.cash.collection if needed
        
        Args:
            env: Odoo environment
            staff_id: Staff who performed collection
            amount: Amount collected
            mode: Collection mode ('all' or 'except_reserve')
        """
        _logger.info("TODO: _create_collection_record - Create audit record")
        _logger.info("   Staff: %s, Amount: %.2f, Mode: %s", staff_id, amount, mode)
        
        # TODO: Create record in gas.station.cash.collection or similar model
        # CollectionRecord = env['gas.station.cash.collection'].sudo()
        # CollectionRecord.create({
        #     'staff_id': staff_id,
        #     'amount': amount,
        #     'mode': mode,
        #     'timestamp': fields.Datetime.now(),
        # })
        pass

    # =========================================================================
    # PENDING TRANSACTION HANDLING
    # =========================================================================

    def _is_deposit_pos_related(self, deposit):
        """Check if a deposit should be sent to POS."""
        if deposit.deposit_type in ['oil', 'engine_oil']:
            return True
        if deposit.product_id and deposit.product_id.is_pos_related:
            return True
        if deposit.is_pos_related:
            return True
        return False

    def _get_last_end_of_day(self, env=None):
        """Get the last successful EndOfDay command timestamp."""
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        last_eod = PosCommand.search([
            ('action', '=', 'end_of_day'),
            ('status', '=', 'done'),
        ], order='started_at desc', limit=1)
        
        if last_eod:
            eod_time = getattr(last_eod, 'finished_at', None) or last_eod.started_at
            _logger.info("📅 Last EndOfDay: %s (ID: %s)", eod_time, last_eod.id)
            return eod_time
        
        _logger.info("📅 No EndOfDay found - this is the first day")
        return None

    def _get_last_close_shift(self, env=None, after_timestamp=None):
        """Get the last successful CloseShift command timestamp."""
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        domain = [
            ('action', '=', 'close_shift'),
            ('status', '=', 'done'),
        ]
        
        if after_timestamp:
            domain.append(('started_at', '>', after_timestamp))
        
        last_shift = PosCommand.search(domain, order='started_at desc', limit=1)
        
        if last_shift:
            shift_time = getattr(last_shift, 'finished_at', None) or last_shift.started_at
            _logger.info("📅 Last CloseShift: %s (ID: %s)", shift_time, last_shift.id)
            return shift_time
        
        _logger.info("📅 No CloseShift found after %s", after_timestamp)
        return None

    def _get_shift_start_time(self, env=None):
        """Get the start time of the current shift."""
        if env is None:
            env = request.env
        
        last_eod = self._get_last_end_of_day(env)
        last_close_shift = self._get_last_close_shift(env, after_timestamp=last_eod)
        
        if last_close_shift:
            shift_start = last_close_shift
            _logger.info("📅 Shift starts from last CloseShift: %s", shift_start)
        elif last_eod:
            shift_start = last_eod
            _logger.info("📅 Shift starts from last EndOfDay: %s", shift_start)
        else:
            shift_start = None
            _logger.info("📅 No shift history found - will include ALL transactions")
        
        return shift_start

    def _get_pending_transactions(self):
        """Get pending transactions within the current shift."""
        pending = []
        
        shift_start = self._get_shift_start_time()
        _logger.info("📅 Shift start time: %s", shift_start)
        
        CashDeposit = request.env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', 'in', ['queued', 'failed']),
        ]
        
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        pending_deposits = CashDeposit.search(domain)
        
        for deposit in pending_deposits:
            if self._is_deposit_pos_related(deposit):
                pending.append(deposit)
        
        _logger.info("Found %d pending POS-related transactions", len(pending))
        
        return pending

    def _calculate_shift_pos_total(self, env, staff_id=None):
        """Calculate total of POS deposits within current shift."""
        shift_start = self._get_shift_start_time(env)
        
        CashDeposit = env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', '=', 'ok'),
        ]
        
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        successful_deposits = CashDeposit.search(domain)
        
        total_cash = 0.0
        pos_related_deposits = []
        
        for deposit in successful_deposits:
            if self._is_deposit_pos_related(deposit):
                total_cash += deposit.total_amount or 0.0
                pos_related_deposits.append(deposit.name)
        
        _logger.info("💰 Shift POS totals: %d deposits, %.2f total", 
                    len(pos_related_deposits), total_cash)
        
        return {
            'total_cash': total_cash,
            'count': len(pos_related_deposits),
            'deposits': pos_related_deposits,
            'shift_start': shift_start.isoformat() if shift_start else None,
        }

    def _send_pending_transactions_async(self, dbname, uid, pending_ids, pending_model, cmd_id):
        """Background thread to send pending transactions to POS."""
        try:
            _logger.info("📤 Starting to send %d pending transactions...", len(pending_ids))
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                success_count = 0
                fail_count = 0
                
                for record_id in pending_ids:
                    try:
                        if pending_model == "gas.station.cash.deposit":
                            deposit = env[pending_model].sudo().browse(record_id)
                            if deposit.exists():
                                if self._send_deposit_to_pos(env, deposit):
                                    success_count += 1
                                else:
                                    fail_count += 1
                    except Exception as e:
                        _logger.error("❌ Failed to send pending transaction %s: %s", record_id, e)
                        fail_count += 1
                
                if cmd.exists():
                    result = {
                        "pending_sent": success_count,
                        "pending_failed": fail_count,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.write({
                        "status": "done" if fail_count == 0 else "partial",
                        "message": f"Sent {success_count} pending, {fail_count} failed",
                        "payload_out": json.dumps(result, ensure_ascii=False),
                        "finished_at": fields.Datetime.now(),
                    })
                    cmd.push_overlay()
                    
                _logger.info("✅ Pending transactions: %d success, %d failed", 
                            success_count, fail_count)
                            
        except Exception as e:
            _logger.exception("❌ Failed to process pending transactions: %s", e)

    def _send_deposit_to_pos(self, env, deposit):
        """Send a single deposit to POS."""
        transaction_id = deposit.pos_transaction_id or deposit.name
        
        staff_id = "UNKNOWN"
        if deposit.staff_id:
            staff = deposit.staff_id
            staff_id = (
                getattr(staff, 'external_id', None) or
                getattr(staff, 'employee_id', None) or
                staff.name or
                "UNKNOWN"
            )
        
        amount = float(deposit.total_amount or 0)
        
        _logger.info("📤 Sending deposit %s to POS (staff=%s, amount=%s)", 
                    transaction_id, staff_id, amount)
        
        try:
            gateway = env['pos.gateway'].sudo()
            result = gateway.send_deposit(transaction_id, staff_id, amount)
            
            if result.get('success'):
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'ok',
                    'pos_description': result.get('description', 'Deposit Success'),
                    'pos_time_stamp': result.get('time_stamp', ''),
                    'pos_response_json': json.dumps(result.get('raw', {}), ensure_ascii=False),
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
                })
                _logger.warning("⚠️ Deposit %s failed: %s", transaction_id, result.get('error'))
                return False
                
        except Exception as e:
            _logger.exception("❌ Failed to send deposit %s: %s", transaction_id, e)
            deposit.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'queued',
                'pos_error': str(e),
            })
            return False

    # =========================================================================
    # CLOSE SHIFT - ASYNC PROCESSING
    # =========================================================================

    def _process_close_shift_async(self, dbname, uid, cmd_id, has_pending: bool):
        """
        Background thread to process close shift.
        
        Steps:
        1. Wait for processing delay
        2. Check if collection is enabled
        3. If enabled, collect cash to box
        4. Mark command as done
        """
        try:
            delay = 2
            _logger.info("⏰ CloseShift processing started, waiting %d seconds...", delay)
            time.sleep(delay)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    return
                
                # Read collection config
                config = _read_collection_config()
                collect_enabled = config['close_shift_collect_cash']
                
                _logger.info("📦 CloseShift collection enabled: %s", collect_enabled)
                
                collection_result = {}
                
                if collect_enabled:
                    # Collect ALL cash on CloseShift (no reserve)
                    collection_result = self._collect_to_box(
                        env, 
                        mode='all',
                        staff_id=cmd.staff_external_id,
                        reserve_amount=0
                    )
                    _logger.info("📦 Collection result: %s", collection_result)
                
                # Calculate shift totals
                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                
                result = {
                    "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{cmd.staff_external_id or 'AUTO'}-01",
                    "total_cash": shift_totals.get('total_cash', 0.0),
                    "total_transactions": shift_totals.get('count', 0),
                    "collection_enabled": collect_enabled,
                    "collection_result": collection_result,
                    "completed_at": fields.Datetime.now().isoformat()
                }
                
                cmd.mark_done(result)
                _logger.info("✅ CloseShift command %s marked as DONE", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process close shift async: %s", e)

    # =========================================================================
    # END OF DAY - ASYNC PROCESSING
    # =========================================================================

    def _process_end_of_day_async(self, dbname, uid, cmd_id):
        """
        Background thread to process end of day.
        
        Steps:
        1. Wait for processing delay
        2. Read collection mode from config
        3. Collect cash to box (all or except reserve)
        4. Mark command as done
        """
        try:
            delay = 2
            _logger.info("⏰ EndOfDay processing started, waiting %d seconds...", delay)
            time.sleep(delay)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    return
                
                # Read collection config
                config = _read_collection_config()
                collect_mode = config['end_of_day_collect_mode']
                reserve_amount = config['end_of_day_reserve_amount']
                
                _logger.info("📦 EndOfDay collection mode: %s", collect_mode)
                _logger.info("📦 EndOfDay reserve amount: %.2f", reserve_amount)
                
                # Always collect on EndOfDay
                collection_result = self._collect_to_box(
                    env,
                    mode=collect_mode,
                    staff_id=cmd.staff_external_id,
                    reserve_amount=reserve_amount if collect_mode == 'except_reserve' else 0
                )
                _logger.info("📦 Collection result: %s", collection_result)
                
                # Calculate shift totals
                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                
                result = {
                    "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                    "final_shift_cash": shift_totals.get('total_cash', 0.0),
                    "final_shift_transactions": shift_totals.get('count', 0),
                    "collection_mode": collect_mode,
                    "collection_result": collection_result,
                    "completed_at": fields.Datetime.now().isoformat()
                }
                
                cmd.mark_done(result)
                _logger.info("✅ EndOfDay command %s marked as DONE", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process end of day async: %s", e)

    # =========================================================================
    # CLOSE SHIFT ENDPOINT
    # =========================================================================

    def _handle_close_shift(self, **kwargs):
        """Handle CloseShift request from POS."""
        _logger.info("=" * 80)
        _logger.info("📥 CLOSE SHIFT REQUEST RECEIVED")
        _logger.info("🌐 PATH: %s", request.httprequest.path)
        
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

        # Get staff_id - use default if not provided
        staff_id = data.get("staff_id")
        if not staff_id:
            staff_id = self._get_default_staff_id()
            _logger.info("⚠️ staff_id not provided, using default: %s", staff_id)
        
        # Get shiftid from POS request (store as text for flexibility)
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)
            _logger.info("📋 POS Shift ID received: %s", pos_shift_id)
        
        _logger.info("Staff ID: %s", staff_id)
        
        # Check for pending transactions
        _logger.info("🔍 Checking for pending transactions...")
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            _logger.warning("⚠️ Found %d pending transactions", pending_count)
            
            cmd = self._create_command("close_shift", staff_id, {
                "pending_count": pending_count,
                "is_pending_mode": True,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("❌ Failed to push overlay: %s", e)
            
            dbname = request.env.cr.dbname
            uid = request.env.uid
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
        
        # No pending - process normally
        _logger.info("✅ No pending transactions, proceeding with CloseShift")
        
        cmd = self._create_command("close_shift", staff_id, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)
        
        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        # Start background processing (includes collection)
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_close_shift_async, 
            args=(dbname, uid, cmd.id, False)
        )
        thread.daemon = True
        thread.start()
        
        shift_id = f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-01"
        
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
    
    @http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift(self, **kwargs):
        return self._handle_close_shift(**kwargs)

    @http.route("/POS/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift_pos_prefix(self, **kwargs):
        return self._handle_close_shift(**kwargs)

    # =========================================================================
    # END OF DAY ENDPOINT
    # =========================================================================

    def _handle_end_of_day(self, **kwargs):
        """Handle EndOfDay request from POS."""
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
            staff_id = self._get_default_staff_id()
            _logger.info("⚠️ staff_id not provided, using default: %s", staff_id)
        
        # Get shiftid from POS request (store as text for flexibility)
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)
            _logger.info("📋 POS Shift ID received: %s", pos_shift_id)
        
        _logger.info("Staff ID: %s", staff_id)
        
        # Check for pending transactions
        _logger.info("🔍 Checking for pending transactions...")
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            _logger.warning("⚠️ Found %d pending transactions", pending_count)
            
            cmd = self._create_command("end_of_day", staff_id, {
                "pending_count": pending_count,
                "is_pending_mode": True,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("❌ Failed to push overlay: %s", e)
            
            dbname = request.env.cr.dbname
            uid = request.env.uid
            deposit_ids = [p.id for p in pending_transactions]
            
            if deposit_ids:
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
        
        # No pending - process normally
        _logger.info("✅ No pending transactions, proceeding with EndOfDay")
        
        cmd = self._create_command("end_of_day", staff_id, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)

        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        # Start background processing (includes collection)
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_end_of_day_async, 
            args=(dbname, uid, cmd.id)
        )
        thread.daemon = True
        thread.start()

        shift_id = f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-EOD"
        
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
    
    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    @http.route("/POS/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day_pos_prefix(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    # =========================================================================
    # HEARTBEAT ENDPOINT
    # =========================================================================

    def _handle_heartbeat(self, **kwargs):
        """Handle HeartBeat request."""
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
    
    @http.route("/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat(self, **kwargs):
        return self._handle_heartbeat(**kwargs)

    @http.route("/POS/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat_pos_prefix(self, **kwargs):
        return self._handle_heartbeat(**kwargs)