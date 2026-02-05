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
    
    ; Glory API Base URL (Flask middleware)
    glory_api_base_url = http://localhost:5000
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
import requests

_logger = logging.getLogger(__name__)

# Glory API Configuration
GLORY_API_BASE_URL = "http://localhost:5000"
GLORY_API_TIMEOUT = 120  # seconds (collection can take time)
GLORY_SESSION_ID = "1"   # Default session ID


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
            'glory_api_base_url': str,
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
    
    # Glory API Base URL
    glory_api_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
    
    return {
        'close_shift_collect_cash': close_shift_collect,
        'end_of_day_collect_mode': eod_collect_mode,
        'end_of_day_reserve_amount': eod_reserve_amount,
        'glory_api_base_url': glory_api_url,
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
    # GLORY API FUNCTIONS
    # =========================================================================

    def _glory_get_inventory(self, env):
        """
        Get current cash inventory from Glory Cash Recycler.
        
        Calls: GET /fcc/api/v1/cash/availability?session_id=1
        
        Returns:
            dict: {
                'success': bool,
                'total_amount': float (in THB),
                'notes': [{'value': 1000, 'qty': 10}, ...],
                'coins': [{'value': 10, 'qty': 50}, ...],
                'raw_response': dict,
                'error': str or None,
            }
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info("📊 Getting inventory from Glory API...")
        _logger.info("   URL: %s/fcc/api/v1/cash/availability", base_url)
        
        result = {
            'success': False,
            'total_amount': 0.0,
            'notes': [],
            'coins': [],
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/cash/availability"
            resp = requests.get(url, params={"session_id": GLORY_SESSION_ID}, timeout=30)
            
            _logger.info("   HTTP Status: %s", resp.status_code)
            
            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                _logger.error("   ❌ %s", result['error'])
                return result
            
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Glory Response received")
            
            # Parse notes and coins from availability response
            # Values from Glory are in satang (1/100 of THB)
            UNIT_DIVISOR = 100
            total = 0.0
            
            notes = data.get('notes', [])
            coins = data.get('coins', [])
            
            parsed_notes = []
            for note in notes:
                fv = note.get('value', 0)  # fv is already in satang
                qty = note.get('qty', 0)
                available = note.get('available', False)
                if qty > 0 and available:
                    value_thb = fv / UNIT_DIVISOR  # Convert satang to THB
                    parsed_notes.append({'value': value_thb, 'qty': qty, 'fv': fv})
                    total += value_thb * qty
            
            parsed_coins = []
            for coin in coins:
                fv = coin.get('value', 0)
                qty = coin.get('qty', 0)
                available = coin.get('available', False)
                if qty > 0 and available:
                    value_thb = fv / UNIT_DIVISOR
                    parsed_coins.append({'value': value_thb, 'qty': qty, 'fv': fv})
                    total += value_thb * qty
            
            result['success'] = True
            result['total_amount'] = total
            result['notes'] = parsed_notes
            result['coins'] = parsed_coins
            
            _logger.info("   ✅ Inventory loaded successfully")
            _logger.info("   Total in machine: ฿%.2f", total)
            _logger.info("   Notes: %d denominations", len(parsed_notes))
            _logger.info("   Coins: %d denominations", len(parsed_coins))
            
        except requests.Timeout:
            result['error'] = "Glory API timeout"
            _logger.error("   ❌ %s", result['error'])
        except requests.RequestException as e:
            result['error'] = f"Glory API connection error: {str(e)}"
            _logger.error("   ❌ %s", result['error'])
        except Exception as e:
            result['error'] = f"Error parsing Glory response: {str(e)}"
            _logger.exception("   ❌ %s", result['error'])
        
        return result

    def _glory_collect_to_box(self, env, mode: str = "full", target_float: dict = None):
        """
        Send collection command to Glory Cash Recycler.
        
        Calls: POST /fcc/api/v1/collect
        
        Args:
            env: Odoo environment
            mode: 'full' or 'leave_float'
            target_float: dict with denominations to keep (for leave_float mode)
            
        Returns:
            dict: {
                'success': bool,
                'collected_amount': float,
                'collected_breakdown': {'notes': [], 'coins': []},
                'raw_response': dict,
                'error': str or None,
            }
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info("📦 Sending collection command to Glory API...")
        _logger.info("   URL: %s/fcc/api/v1/collect", base_url)
        _logger.info("   Mode: %s", mode)
        
        result = {
            'success': False,
            'collected_amount': 0.0,
            'collected_breakdown': {'notes': [], 'coins': []},
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/collect"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "scope": "all",
                "plan": mode,  # "full" or "leave_float"
            }
            
            if target_float and mode == "leave_float":
                payload["target_float"] = target_float
            
            _logger.info("   Payload: %s", payload)
            
            resp = requests.post(url, json=payload, timeout=GLORY_API_TIMEOUT)
            
            _logger.info("   HTTP Status: %s", resp.status_code)
            
            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                _logger.error("   ❌ %s", result['error'])
                return result
            
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Glory Response: %s", json.dumps(data, indent=2))
            
            # Check response status
            if data.get('status') != 'OK':
                result['error'] = data.get('error', 'Collection failed')
                _logger.error("   ❌ Collection failed: %s", result['error'])
                return result
            
            # Parse collected cash from response
            # Response format: { "status": "OK", "data": { "Cash": { "Denomination": [...] } } }
            UNIT_DIVISOR = 100
            collected_total = 0.0
            notes = []
            coins = []
            
            cash_data = data.get('data', {}).get('Cash', {})
            denominations = cash_data.get('Denomination', [])
            
            if not isinstance(denominations, list):
                denominations = [denominations] if denominations else []
            
            for d in denominations:
                if not d:
                    continue
                try:
                    fv = int(d.get('fv', 0))
                    qty = int(d.get('Piece', 0))
                    devid = int(d.get('devid', 1))
                    
                    if qty > 0:
                        value_thb = fv / UNIT_DIVISOR
                        collected_total += value_thb * qty
                        
                        item = {'value': value_thb, 'qty': qty, 'fv': fv}
                        if devid == 2:  # Coin
                            coins.append(item)
                        else:  # Note (devid=1)
                            notes.append(item)
                except Exception as e:
                    _logger.warning("   Error parsing denomination: %s", e)
                    continue
            
            result['success'] = True
            result['collected_amount'] = collected_total
            result['collected_breakdown'] = {'notes': notes, 'coins': coins}
            
            _logger.info("   ✅ Collection successful!")
            _logger.info("   Collected: ฿%.2f", collected_total)
            _logger.info("   Notes: %s", notes)
            _logger.info("   Coins: %s", coins)
            
        except requests.Timeout:
            result['error'] = "Glory API timeout (collection may still be in progress)"
            _logger.error("   ❌ %s", result['error'])
        except requests.RequestException as e:
            result['error'] = f"Glory API connection error: {str(e)}"
            _logger.error("   ❌ %s", result['error'])
        except Exception as e:
            result['error'] = f"Error processing collection: {str(e)}"
            _logger.exception("   ❌ %s", result['error'])
        
        return result

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
            # Step 1 - Get current cash inventory from Glory
            inventory = self._glory_get_inventory(env)
            
            if not inventory['success']:
                result['error'] = inventory.get('error', 'Failed to get inventory')
                _logger.error("   ❌ Failed to get inventory: %s", result['error'])
                return result
            
            current_cash = inventory['total_amount']
            _logger.info("   Current Cash in Machine: ฿%.2f", current_cash)
            
            # Step 2 - Calculate amount to collect
            if mode == 'all':
                # Collect everything
                collect_amount = current_cash
                keep_amount = 0.0
                glory_mode = "full"
            elif mode == 'except_reserve':
                # Keep reserve, collect the rest
                keep_amount = min(reserve_amount, current_cash)
                collect_amount = max(0, current_cash - reserve_amount)
                glory_mode = "leave_float" if keep_amount > 0 else "full"
            else:
                _logger.warning("   Unknown mode: %s, defaulting to 'all'", mode)
                collect_amount = current_cash
                keep_amount = 0.0
                glory_mode = "full"
            
            _logger.info("   Amount to Collect: ฿%.2f", collect_amount)
            _logger.info("   Amount to Keep: ฿%.2f", keep_amount)
            
            if collect_amount <= 0:
                _logger.info("   No cash to collect, skipping Glory API call")
                result['success'] = True
                result['collected_amount'] = 0.0
                result['reserve_kept'] = keep_amount
                return result
            
            # Step 3 - Send collection command to Glory
            target_float = None
            if glory_mode == "leave_float" and keep_amount > 0:
                # For leave_float mode, specify the amount to keep
                target_float = {
                    "amount": int(keep_amount * 100),  # Convert to satang
                }
            
            collection_result = self._glory_collect_to_box(env, mode=glory_mode, target_float=target_float)
            
            if not collection_result['success']:
                result['error'] = collection_result.get('error', 'Collection failed')
                result['glory_response'] = collection_result.get('raw_response', {})
                _logger.error("   ❌ Collection failed: %s", result['error'])
                return result
            
            # Step 4 - Create collection record in Odoo (optional - for audit)
            try:
                self._create_collection_record(
                    env, 
                    staff_id, 
                    collection_result['collected_amount'],
                    collection_result['collected_breakdown'],
                    mode,
                    collection_result.get('raw_response', {})
                )
            except Exception as e:
                _logger.warning("   ⚠️ Failed to create collection record: %s", e)
                # Don't fail the whole operation, just log it
            
            result['success'] = True
            result['collected_amount'] = collection_result['collected_amount']
            result['reserve_kept'] = keep_amount
            result['glory_response'] = collection_result.get('raw_response', {})
            
            _logger.info("📦 COLLECTION BOX - Success!")
            _logger.info("   Collected: ฿%.2f", result['collected_amount'])
            _logger.info("   Reserved: ฿%.2f", result['reserve_kept'])
            
        except Exception as e:
            _logger.exception("📦 COLLECTION BOX - Error: %s", e)
            result['error'] = str(e)
        
        _logger.info("📦 Collection result: %s", result)
        _logger.info("=" * 60)
        return result

    def _create_collection_record(self, env, staff_id: str, amount: float, breakdown: dict, mode: str, glory_response: dict = None):
        """
        Create a collection record in Odoo for audit trail.
        
        Args:
            env: Odoo environment
            staff_id: Staff who performed collection
            amount: Amount collected
            breakdown: {'notes': [...], 'coins': [...]}
            mode: Collection mode ('all' or 'except_reserve')
            glory_response: Raw Glory API response
        """
        _logger.info("📝 Creating collection record in Odoo...")
        _logger.info("   Staff: %s, Amount: %.2f, Mode: %s", staff_id, amount, mode)
        
        try:
            # Check if gas.station.cash.collection model exists
            if 'gas.station.cash.collection' not in env:
                _logger.warning("   Model gas.station.cash.collection not found, skipping record creation")
                return
            
            # Find staff
            Staff = env["gas.station.staff"].sudo()
            staff = Staff.search([
                "|",
                ("external_id", "=", staff_id),
                ("employee_id", "=", staff_id),
            ], limit=1)
            
            if not staff:
                _logger.warning("   Staff not found: %s", staff_id)
            
            # Prepare collection lines if model has line support
            collection_lines = []
            
            for note in breakdown.get('notes', []):
                qty = note.get('qty', 0)
                value = note.get('value', 0)
                if qty > 0 and value > 0:
                    collection_lines.append((0, 0, {
                        "denomination_type": "note",
                        "currency_denomination": value,
                        "quantity": qty,
                    }))
            
            for coin in breakdown.get('coins', []):
                qty = coin.get('qty', 0)
                value = coin.get('value', 0)
                if qty > 0 and value > 0:
                    collection_lines.append((0, 0, {
                        "denomination_type": "coin",
                        "currency_denomination": value,
                        "quantity": qty,
                    }))
            
            # Map mode to collection_type
            collection_type = "end_of_day" if mode == 'all' or mode == 'except_reserve' else "shift_change"
            
            # Create collection record
            Collection = env["gas.station.cash.collection"].sudo()
            
            collection_vals = {
                "date": fields.Datetime.now(),
                "collection_type": collection_type,
                "notes": f"Auto collection ({mode})",
                "glory_session_id": GLORY_SESSION_ID,
                "glory_transaction_id": f"COL-{int(time.time())}",
                "glory_status": "completed",
                "state": "confirmed",
            }
            
            # Add staff if found
            if staff:
                collection_vals["staff_id"] = staff.id
            
            # Add lines if supported
            if collection_lines:
                collection_vals["collection_line_ids"] = collection_lines
            
            # Add glory response if supported
            if glory_response:
                collection_vals["glory_response_json"] = json.dumps(glory_response, ensure_ascii=False)
            
            collection = Collection.create(collection_vals)
            _logger.info("   ✅ Collection record created: ID=%s", collection.id)
            
        except Exception as e:
            _logger.exception("   ❌ Failed to create collection record: %s", e)
            # Don't re-raise - we don't want this to fail the main collection

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
                    cmd.mark_done(result)
                    _logger.info("✅ Pending transactions processed: %d success, %d failed", 
                                success_count, fail_count)
                    
        except Exception as e:
            _logger.exception("❌ Failed to send pending transactions: %s", e)

    def _send_deposit_to_pos(self, env, deposit):
        """Send a single deposit to POS."""
        try:
            pos_conf = _read_pos_conf()
            pos_host = pos_conf.get('pos_host', '127.0.0.1')
            pos_port = pos_conf.get('pos_port', 9001)
            pos_timeout = pos_conf.get('pos_timeout', 5.0)
            pos_vendor = pos_conf.get('pos_vendor', 'local')
            
            # Build URL based on vendor
            vendor_paths = {
                "local": "/deposit",
                "firstpro": "/deposit",
                "flowco": "/POS/Deposit",
            }
            path = vendor_paths.get(pos_vendor, "/deposit")
            url = f"http://{pos_host}:{pos_port}{path}"
            
            transaction_id = deposit.transaction_id or f"TXN-{deposit.id}"
            
            payload = {
                "transaction_id": transaction_id,
                "staff_id": deposit.staff_external_id or "UNKNOWN",
                "amount": deposit.total_amount or 0.0,
            }
            
            _logger.info("📤 Sending deposit %s to POS: %s", transaction_id, url)
            
            resp = requests.post(url, json=payload, timeout=pos_timeout)
            result = resp.json() if resp.ok else {"status": "FAILED", "error": f"HTTP {resp.status_code}"}
            
            _logger.info("📥 POS Response: %s", result)
            
            if result.get('status') == 'OK':
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'ok',
                    'pos_description': result.get('description', ''),
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
            _logger.exception("❌ Failed to send deposit %s: %s", deposit.id, e)
            deposit.write({
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

        staff_id = data.get("staff_id")
        if not staff_id:
            staff_id = self._get_default_staff_id()
            _logger.info("⚠️ staff_id not provided, using default: %s", staff_id)
        
        # Get shiftid from POS request
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