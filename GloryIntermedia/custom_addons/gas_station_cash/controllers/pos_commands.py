# -*- coding: utf-8 -*-
"""
File: controllers/pos_commands.py
Description: POS Command Controller with CloseShift/EndOfDay and Collection Box handling.

Updated: Added status polling until Glory returns to IDLE state
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

# Polling Configuration
GLORY_POLL_INTERVAL = 2  # seconds between status checks
GLORY_POLL_MAX_ATTEMPTS = 60  # max attempts (60 * 2 = 120 seconds max wait)


# =============================================================================
# CONFIGURATION READER
# =============================================================================

def _read_collection_config():
    """
    Read Collection Box settings from odoo.conf
    
    Returns:
        dict with keys:
        - close_shift_collect_cash: bool
        - end_of_day_collect_mode: str ('all' | 'except_reserve')
        - end_of_day_keep_reserve: bool (NEW - master switch)
        - end_of_day_reserve_amount: float
        - end_of_day_reserve_denoms: list[dict] or None (NEW - denomination breakdown)
        - glory_api_base_url: str
    """
    config = tools.config
    
    # Close Shift settings
    close_shift_collect = config.get('close_shift_collect_cash', 'false')
    close_shift_collect = str(close_shift_collect).lower() in ('true', '1', 'yes')
    
    # End of Day mode
    eod_collect_mode = config.get('end_of_day_collect_mode', 'except_reserve')
    if eod_collect_mode not in ('all', 'except_reserve'):
        eod_collect_mode = 'except_reserve'
    
    # Master switch for keeping reserve
    eod_keep_reserve = config.get('end_of_day_keep_reserve', 'true')
    eod_keep_reserve = str(eod_keep_reserve).lower() in ('true', '1', 'yes')
    
    # Fallback reserve amount
    try:
        eod_reserve_amount = float(config.get('end_of_day_reserve_amount', 5000))
    except (ValueError, TypeError):
        eod_reserve_amount = 5000.0
    
    # Reserve denominations (JSON array)
    eod_reserve_denoms = None
    denoms_str = config.get('end_of_day_reserve_denoms', '')
    if denoms_str:
        try:
            eod_reserve_denoms = json.loads(denoms_str)
            if not isinstance(eod_reserve_denoms, list):
                _logger.warning("end_of_day_reserve_denoms is not a list, ignoring")
                eod_reserve_denoms = None
        except json.JSONDecodeError as e:
            _logger.warning("Failed to parse end_of_day_reserve_denoms: %s", e)
            eod_reserve_denoms = None
    
    glory_api_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
    
    return {
        'close_shift_collect_cash': close_shift_collect,
        'end_of_day_collect_mode': eod_collect_mode,
        'end_of_day_keep_reserve': eod_keep_reserve,
        'end_of_day_reserve_amount': eod_reserve_amount,
        'end_of_day_reserve_denoms': eod_reserve_denoms,
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
            "pos_shift_id": pos_shift_id,
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
        staff_id = tools.config.get('pos_default_staff_id')
        if staff_id:
            return staff_id
        
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

    def _glory_get_status(self):
        """
        Get Glory machine status.
        
        Calls: GET /fcc/api/v1/status?session_id=1
        
        Returns:
            dict: {
                'success': bool,
                'is_idle': bool,
                'status_code': str,
                'raw_response': dict,
                'error': str or None,
            }
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        result = {
            'success': False,
            'is_idle': False,
            'status_code': None,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/status"
            resp = requests.get(url, params={"session_id": GLORY_SESSION_ID}, timeout=10)
            
            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                return result
            
            data = resp.json()
            result['raw_response'] = data
            result['status_code'] = data.get('code')
            
            # Check if status is OK (code "0" means IDLE/ready)
            if data.get('status') == 'OK' and data.get('code') == '0':
                result['success'] = True
                result['is_idle'] = True
            else:
                result['success'] = True
                result['is_idle'] = False
            
        except requests.Timeout:
            result['error'] = "Glory API timeout"
        except requests.RequestException as e:
            result['error'] = f"Glory API connection error: {str(e)}"
        except Exception as e:
            result['error'] = f"Error checking Glory status: {str(e)}"
        
        return result

    def _glory_wait_for_idle(self, max_attempts=GLORY_POLL_MAX_ATTEMPTS, interval=GLORY_POLL_INTERVAL):
        """
        Poll Glory status until it returns to IDLE state.
        
        Args:
            max_attempts: Maximum number of polling attempts
            interval: Seconds between each poll
            
        Returns:
            dict: {
                'success': bool,
                'attempts': int,
                'final_status': str,
                'error': str or None,
            }
        """
        _logger.info("⏳ Waiting for Glory to return to IDLE state...")
        
        result = {
            'success': False,
            'attempts': 0,
            'final_status': None,
            'error': None,
        }
        
        for attempt in range(1, max_attempts + 1):
            result['attempts'] = attempt
            
            _logger.info("   Poll attempt %d/%d...", attempt, max_attempts)
            
            status = self._glory_get_status()
            
            if not status['success']:
                _logger.warning("   Status check failed: %s", status.get('error'))
                time.sleep(interval)
                continue
            
            result['final_status'] = status.get('status_code')
            
            if status['is_idle']:
                _logger.info("    Glory is IDLE (attempt %d)", attempt)
                result['success'] = True
                return result
            
            _logger.info("   Glory not IDLE yet (code=%s), waiting %ds...", 
                        status.get('status_code'), interval)
            time.sleep(interval)
        
        result['error'] = f"Glory did not return to IDLE after {max_attempts} attempts"
        _logger.warning("    %s", result['error'])
        return result

    def _glory_get_inventory(self, env):
        """
        Get current cash inventory from Glory Cash Recycler.
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info(" Getting inventory from Glory API...")
        
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
            
            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                _logger.error("    %s", result['error'])
                return result
            
            data = resp.json()
            result['raw_response'] = data
            
            UNIT_DIVISOR = 100
            total = 0.0
            
            notes = data.get('notes', [])
            coins = data.get('coins', [])
            
            parsed_notes = []
            for note in notes:
                fv = note.get('value', 0)
                qty = note.get('qty', 0)
                available = note.get('available', False)
                if qty > 0 and available:
                    value_thb = fv / UNIT_DIVISOR
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
            
            _logger.info("    Total in machine: %.2f", total)
            
        except Exception as e:
            result['error'] = f"Error: {str(e)}"
            _logger.exception("    %s", result['error'])
        
        return result

    def _collect_to_box(self, env, mode: str, staff_id: str = None, reserve_amount: float = 0):
        """
        Collect cash to collection box via Glory Cash Recycler.
        
        FIXED: ส่ง target_float ในรูปแบบที่ถูกต้อง (denoms array)
        """
        _logger.info("=" * 60)
        _logger.info("COLLECTION BOX - Starting collection")
        _logger.info("   Mode: %s", mode)
        _logger.info("   Staff: %s", staff_id)
        _logger.info("   Reserve Amount: %.2f", reserve_amount)
        
        # อ่าน config
        config = _read_collection_config()
        reserve_denoms = config.get('end_of_day_reserve_denoms')
        
        _logger.info("   Reserve Denoms from config: %s", reserve_denoms)
        
        result = {
            'success': False,
            'collected_amount': 0.0,
            'reserve_kept': 0.0,
            'current_cash': 0.0,
            'required_reserve': reserve_amount,
            'insufficient_reserve': False,
            'error': None,
            'glory_response': {},
            'collected_breakdown': {},
        }
        
        try:
            # Step 1 - Get current cash inventory
            inventory = self._glory_get_inventory(env)
            
            if not inventory['success']:
                result['error'] = inventory.get('error', 'Failed to get inventory')
                _logger.error("   %s", result['error'])
                _logger.info("=" * 60)
                return result
            
            current_cash = inventory['total_amount']
            result['current_cash'] = current_cash
            _logger.info("   Current Cash: %.2f", current_cash)
            
            # Step 2 - Determine glory_mode and target_float
            glory_mode = "full"
            target_float = None
            keep_amount = 0.0
            
            if mode == 'all':
                # Collect ALL
                glory_mode = "full"
                keep_amount = 0.0
                _logger.info("   Mode: Collect ALL (no reserve)")
                
            elif mode == 'except_reserve':
                # Check if we have denomination config
                if reserve_denoms and len(reserve_denoms) > 0:
                    # ============================================
                    # ใช้ denomination-based reserve (แนะนำ)
                    # ============================================
                    _logger.info("   Mode: Leave Float (by denomination)")
                    
                    # คำนวณ total reserve จาก denoms
                    UNIT_DIVISOR = 100
                    total_reserve = 0.0
                    target_float_denoms = []
                    
                    for d in reserve_denoms:
                        fv = int(d.get('fv', 0))
                        qty = int(d.get('qty', 0))
                        device = int(d.get('device', 1))
                        
                        if fv > 0 and qty > 0:
                            value = (fv / UNIT_DIVISOR) * qty
                            total_reserve += value
                            
                            # สร้าง format ที่ fcc_soap_client.py ต้องการ
                            target_float_denoms.append({
                                "devid": device,
                                "cc": "THB",  # TODO: อ่านจาก config
                                "fv": fv,
                                "min_qty": qty,
                            })
                            
                            _logger.info("      Keep: fv=%d, qty=%d, device=%d (%.2f)", 
                                        fv, qty, device, value)
                    
                    keep_amount = total_reserve
                    _logger.info("   Total Reserve to Keep: %.2f", keep_amount)
                    
                    # Check if we have enough cash
                    if current_cash < total_reserve:
                        _logger.info("   INSUFFICIENT CASH FOR RESERVE!")
                        _logger.info("      Current: %.2f, Required: %.2f", current_cash, total_reserve)
                        
                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['required_reserve'] = total_reserve
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash
                        _logger.info("=" * 60)
                        return result
                    
                    # ตั้งค่า target_float ในรูปแบบที่ถูกต้อง!
                    glory_mode = "leave_float"
                    target_float = {"denoms": target_float_denoms}
                    
                    _logger.info("   target_float = %s", target_float)
                    
                else:
                    # ============================================
                    # Fallback: amount-based (No denom config)
                    # ============================================
                    _logger.info("   Mode: Leave Float (by amount - NO DENOM CONFIG)")
                    _logger.warning("   WARNING: No reserve_denoms configured, will collect ALL!")
                    
                    # if there is no reserve_denoms. It will collect all.
                    # Read reserve_float amount from config (end_of_day_reserve_amount)
                    
                    if current_cash < reserve_amount:
                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash
                        _logger.info("=" * 60)
                        return result
                    
                    # Fallback to collecting all since we don't have proper denomination config
                    glory_mode = "full"
                    keep_amount = 0.0
            
            _logger.info("   Glory Mode: %s", glory_mode)
            _logger.info("   Target Float: %s", target_float)
            
            # Step 3 - Send collection command
            collection_result = self._glory_collect_to_box(env, mode=glory_mode, target_float=target_float)
            
            if not collection_result['success']:
                result['error'] = collection_result.get('error', 'Collection failed')
                result['glory_response'] = collection_result.get('raw_response', {})
                _logger.info("=" * 60)
                return result
            
            result['success'] = True
            result['collected_amount'] = collection_result['collected_amount']
            result['reserve_kept'] = keep_amount
            result['glory_response'] = collection_result.get('raw_response', {})
            result['collected_breakdown'] = collection_result.get('collected_breakdown', {})
            
            _logger.info("COLLECTION BOX - Success!")
            _logger.info("   Collected: %.2f", result['collected_amount'])
            _logger.info("   Reserved: %.2f", result['reserve_kept'])
            
        except Exception as e:
            _logger.exception("COLLECTION BOX - Error: %s", e)
            result['error'] = str(e)
        
        _logger.info("=" * 60)
        return result

    def _glory_unlock_unit(self, target: str):
        """
        Unlock a specific unit (notes or coins).
        
        Args:
            target: 'notes' or 'coins'
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info(" Unlocking %s unit...", target)
        
        result = {
            'success': False,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/device/unit/unlock"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "target": target,
            }
            
            _logger.info("   URL: %s", url)
            _logger.info("   Payload: %s", payload)
            
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Response: %s", data)
            
            if data.get('status') == 'OK':
                result['success'] = True
                _logger.info("    %s unlocked!", target.capitalize())
            else:
                result['error'] = f"Unlock failed (code: {data.get('result_code')})"
                _logger.error("    %s", result['error'])
                
        except Exception as e:
            result['error'] = str(e)
            _logger.exception("    Error: %s", e)
        
        return result
    
    def _glory_lock_unit(self, target: str):
        """
        Lock a specific unit (notes or coins).
        
        Args:
            target: 'notes' or 'coins'
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info(" Locking %s unit...", target)
        
        result = {
            'success': False,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/device/unit/lock"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "target": target,
            }
            
            _logger.info("   URL: %s", url)
            _logger.info("   Payload: %s", payload)
            
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Response: %s", data)
            
            if data.get('status') == 'OK':
                result['success'] = True
                _logger.info("    %s locked!", target.capitalize())
            else:
                result['error'] = f"Lock failed (code: {data.get('result_code')})"
                _logger.error("    %s", result['error'])
                
        except Exception as e:
            result['error'] = str(e)
            _logger.exception("    Error: %s", e)
        
        return result

    # =========================================================================
    # COLLECTION BOX FUNCTIONS
    # =========================================================================
    
    def _glory_collect_with_reserve(self, env, reserve_denoms: list = None):
        """
        Collect cash to collection box, keeping specified denominations as reserve.

        Args:
            env: Odoo environment
            reserve_denoms: List of denominations to KEEP (not collect)
                           Format: [{"fv": 10000, "qty": 5, "device": 1}, ...]
                           - fv: face value in smallest unit (satang/cents)
                           - qty: quantity to keep
                           - device: 1=notes, 2=coins

        Returns:
            dict with collection results
        """
        config = _read_collection_config()
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)

        _logger.info("💰 Collecting cash with reserve...")
        _logger.info("   Reserve denoms: %s", reserve_denoms)

        result = {
            'success': False,
            'collected_amount': 0.0,
            'collected_breakdown': {'notes': [], 'coins': []},
            'reserve_kept': {'notes': [], 'coins': [], 'total': 0.0},
            'raw_response': {},
            'error': None,
        }

        try:
            # Build target_float for Glory API
            # target_float format: {"denoms": [{"devid": 1, "cc": "EUR", "fv": 5000, "min_qty": 10}, ...]}
            target_float = None
            if reserve_denoms and len(reserve_denoms) > 0:
                target_float = {"denoms": []}

                # Calculate reserve total for logging
                reserve_total = 0.0
                UNIT_DIVISOR = 100

                for denom in reserve_denoms:
                    fv = int(denom.get('fv', 0))
                    qty = int(denom.get('qty', 0))
                    device = int(denom.get('device', 1))

                    if fv > 0 and qty > 0:
                        target_float["denoms"].append({
                            "devid": device,
                            "cc": "THB",  # TODO: Get from config
                            "fv": fv,
                            "min_qty": qty,
                        })

                        value = (fv / UNIT_DIVISOR) * qty
                        reserve_total += value

                        if device == 1:
                            result['reserve_kept']['notes'].append({
                                'fv': fv, 'qty': qty, 'value': fv / UNIT_DIVISOR
                            })
                        else:
                            result['reserve_kept']['coins'].append({
                                'fv': fv, 'qty': qty, 'value': fv / UNIT_DIVISOR
                            })

                result['reserve_kept']['total'] = reserve_total
                _logger.info("   Reserve to keep: %.2f", reserve_total)

            # Call Glory collect API
            url = f"{base_url}/fcc/api/v1/collect"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "scope": "all",
                "plan": "leave_float" if target_float else "full",
            }

            if target_float:
                payload["target_float"] = target_float

            _logger.info("   Collect request: %s", payload)

            resp = requests.post(url, json=payload, timeout=GLORY_API_TIMEOUT)

            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                _logger.error("   %s", result['error'])
                return result

            data = resp.json()
            result['raw_response'] = data

            if data.get('status') != 'OK':
                result['error'] = data.get('error', 'Collection failed')
                _logger.error("   Collection failed: %s", result['error'])
                return result

            # Parse collected cash from response
            UNIT_DIVISOR = 100
            collected_total = 0.0

            inner_data = data.get('data', {})
            denominations = []

            # Try different response structures
            if isinstance(inner_data.get('Cash'), list):
                for cash_block in inner_data['Cash']:
                    if isinstance(cash_block.get('Denomination'), list):
                        denominations.extend(cash_block['Denomination'])
            elif isinstance(inner_data.get('Cash'), dict):
                if isinstance(inner_data['Cash'].get('Denomination'), list):
                    denominations = inner_data['Cash']['Denomination']

            # If still empty, try planned_cash
            if not denominations and isinstance(inner_data.get('planned_cash'), dict):
                if isinstance(inner_data['planned_cash'].get('Denomination'), list):
                    denominations = inner_data['planned_cash']['Denomination']

            for d in denominations:
                if not isinstance(d, dict):
                    continue
                
                try:
                    fv = int(d.get('fv', 0) or 0)
                    qty = int(d.get('Piece', 0) or 0)
                    devid = int(d.get('devid', 0) or 0)
                    cc = d.get('cc', '')

                    if qty > 0:
                        value = fv / UNIT_DIVISOR
                        collected_total += value * qty

                        item = {'fv': fv, 'qty': qty, 'value': value, 'cc': cc}
                        if devid == 2:
                            result['collected_breakdown']['coins'].append(item)
                        else:
                            result['collected_breakdown']['notes'].append(item)
                except Exception as e:
                    _logger.warning("   Error parsing denomination: %s", e)
                    continue
                
            result['success'] = True
            result['collected_amount'] = collected_total

            _logger.info("   ✅ Collection successful!")
            _logger.info("   Collected: %.2f", collected_total)
            _logger.info("   Reserved: %.2f", result['reserve_kept']['total'])

        except Exception as e:
            result['error'] = str(e)
            _logger.exception("   Collection error: %s", e)

        return result

    def _collect_to_box(self, env, mode: str, staff_id: str = None, reserve_amount: float = 0):
        """
        Collect cash to collection box via Glory Cash Recycler.

        UPDATED: Support for denomination-based reserve configuration.
        """
        config = _read_collection_config()
        keep_reserve = config.get('end_of_day_keep_reserve', True)
        reserve_denoms = config.get('end_of_day_reserve_denoms')

        _logger.info("=" * 60)
        _logger.info("COLLECTION BOX - Starting collection")
        _logger.info("   Mode: %s", mode)
        _logger.info("   Staff: %s", staff_id)
        _logger.info("   Keep Reserve: %s", keep_reserve)
        _logger.info("   Reserve Amount: %.2f", reserve_amount)
        _logger.info("   Reserve Denoms: %s", "configured" if reserve_denoms else "not configured")

        result = {
            'success': False,
            'collected_amount': 0.0,
            'reserve_kept': 0.0,
            'current_cash': 0.0,
            'required_reserve': reserve_amount,
            'insufficient_reserve': False,
            'error': None,
            'glory_response': {},
            'collected_breakdown': {},
            'reserve_breakdown': {},
        }

        try:
            # Step 1 - Get current cash inventory
            inventory = self._glory_get_inventory(env)

            if not inventory['success']:
                result['error'] = inventory.get('error', 'Failed to get inventory')
                _logger.error("   %s", result['error'])
                _logger.info("=" * 60)
                return result

            current_cash = inventory['total_amount']
            result['current_cash'] = current_cash
            _logger.info("   Current Cash: %.2f", current_cash)

            # Step 2 - Determine if we're keeping reserve
            if mode == 'all' or not keep_reserve:
                # Collect ALL - no reserve
                _logger.info("   Mode: Collect ALL (no reserve)")
                collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)

            elif mode == 'except_reserve':
                # Collect with reserve

                # Check if we have denomination breakdown
                if reserve_denoms and len(reserve_denoms) > 0:
                    _logger.info("   Mode: Leave Reserve (by denomination)")

                    # Calculate total reserve from denominations
                    UNIT_DIVISOR = 100
                    total_reserve = sum(
                        (d.get('fv', 0) / UNIT_DIVISOR) * d.get('qty', 0)
                        for d in reserve_denoms
                    )

                    # Check if we have enough cash for reserve
                    if current_cash < total_reserve:
                        _logger.info("   INSUFFICIENT CASH FOR RESERVE!")
                        _logger.info("      Current Cash: %.2f", current_cash)
                        _logger.info("      Required Reserve: %.2f", total_reserve)

                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['required_reserve'] = total_reserve
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash

                        _logger.info("   Skipping collection - insufficient cash")
                        _logger.info("=" * 60)
                        return result

                    collection_result = self._glory_collect_with_reserve(env, reserve_denoms=reserve_denoms)

                else:
                    # Fallback to amount-based reserve
                    _logger.info("   Mode: Leave Reserve (by amount: %.2f)", reserve_amount)

                    # Check if we have enough
                    if current_cash < reserve_amount:
                        _logger.info("   INSUFFICIENT CASH FOR RESERVE!")
                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash
                        _logger.info("=" * 60)
                        return result

                    # Use amount-based - collect without specific denoms
                    collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)
            else:
                # Unknown mode - collect all
                collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)

            # Step 3 - Process collection result
            if not collection_result['success']:
                result['error'] = collection_result.get('error', 'Collection failed')
                result['glory_response'] = collection_result.get('raw_response', {})
                _logger.info("=" * 60)
                return result

            result['success'] = True
            result['collected_amount'] = collection_result['collected_amount']
            result['reserve_kept'] = collection_result.get('reserve_kept', {}).get('total', 0.0)
            result['glory_response'] = collection_result.get('raw_response', {})
            result['collected_breakdown'] = collection_result.get('collected_breakdown', {})
            result['reserve_breakdown'] = collection_result.get('reserve_kept', {})

            _logger.info("COLLECTION BOX - Success!")
            _logger.info("   Collected: %.2f", result['collected_amount'])
            _logger.info("   Reserved: %.2f", result['reserve_kept'])

        except Exception as e:
            _logger.exception("COLLECTION BOX - Error: %s", e)
            result['error'] = str(e)

        _logger.info("=" * 60)
        return result

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
            _logger.info(" Last EndOfDay: %s (ID: %s)", eod_time, last_eod.id)
            return eod_time
        
        _logger.info(" No EndOfDay found")
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
            _logger.info(" Last CloseShift: %s (ID: %s)", shift_time, last_shift.id)
            return shift_time
        
        return None

    def _get_shift_start_time(self, env=None):
        """Get the start time of the current shift."""
        if env is None:
            env = request.env
        
        last_eod = self._get_last_end_of_day(env)
        last_close_shift = self._get_last_close_shift(env, after_timestamp=last_eod)
        
        if last_close_shift:
            return last_close_shift
        elif last_eod:
            return last_eod
        
        return None

    def _get_pending_transactions(self):
        """Get pending transactions within the current shift."""
        pending = []
        
        shift_start = self._get_shift_start_time()
        
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
        
        _logger.info(" Shift POS totals: %d deposits, %.2f total", 
                    len(pos_related_deposits), total_cash)
        
        return {
            'total_cash': total_cash,
            'count': len(pos_related_deposits),
            'deposits': pos_related_deposits,
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
                        _logger.error(" Failed to send pending transaction %s: %s", record_id, e)
                        fail_count += 1
                
                if cmd.exists():
                    result = {
                        "pending_sent": success_count,
                        "pending_failed": fail_count,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    
        except Exception as e:
            _logger.exception(" Failed to send pending transactions: %s", e)

    def _send_deposit_to_pos(self, env, deposit):
        """Send a single deposit to POS."""
        try:
            pos_conf = _read_pos_conf()
            pos_host = pos_conf.get('pos_host', '127.0.0.1')
            pos_port = pos_conf.get('pos_port', 9001)
            pos_timeout = pos_conf.get('pos_timeout', 5.0)
            pos_vendor = pos_conf.get('pos_vendor', 'local')
            
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
            
            resp = requests.post(url, json=payload, timeout=pos_timeout)
            result = resp.json() if resp.ok else {"status": "FAILED"}
            
            if result.get('status') == 'OK':
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'ok',
                })
                return True
            else:
                deposit.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'failed',
                })
                return False
                
        except Exception as e:
            _logger.exception(" Failed to send deposit: %s", e)
            return False

    # =========================================================================
    # SHIFT AUDIT HELPERS
    # =========================================================================

    def _get_shift_deposits(self, env, shift_start=None):
        """Get all deposits within the current shift period for audit."""
        CashDeposit = env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('audit_id', '=', False),
        ]
        
        if shift_start:
            domain.append(('date', '>=', shift_start))
        
        deposits = CashDeposit.search(domain, order='date asc')
        _logger.info("Found %d deposits for shift audit", len(deposits))
        
        return deposits

    def _create_shift_audit(self, env, cmd, audit_type, collection_result=None):
        """Create a shift audit record."""
        try:
            ShiftAudit = env["gas.station.shift.audit"].sudo()
            
            shift_start = self._get_shift_start_time(env)
            _logger.info("Shift start time for audit: %s", shift_start)
            
            deposits = self._get_shift_deposits(env, shift_start)
            _logger.info("Found %d deposits for audit", len(deposits))
            
            if audit_type == 'end_of_day':
                audit = ShiftAudit.create_from_end_of_day(
                    command=cmd,
                    deposits=deposits,
                    collection_result=collection_result,
                    shift_start=shift_start
                )
            else:
                audit = ShiftAudit.create_from_shift_close(
                    command=cmd,
                    deposits=deposits,
                    shift_start=shift_start
                )
            
            _logger.info("✅ Created shift audit: %s (type=%s, deposits=%d)", 
                        audit.name, audit_type, len(deposits))
            
            return audit
            
        except Exception as e:
            _logger.exception("❌ Failed to create shift audit: %s", e)
            return None

    # =========================================================================
    # CLOSE SHIFT - ASYNC PROCESSING
    # =========================================================================

    def _process_close_shift_async(self, dbname, uid, cmd_id, has_pending: bool):
        """Background thread to process close shift."""
        try:
            time.sleep(2)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    return
                
                config = _read_collection_config()
                collect_enabled = config['close_shift_collect_cash']
                
                collection_result = {}
                
                if collect_enabled:
                    collection_result = self._collect_to_box(
                        env, 
                        mode='all',
                        staff_id=cmd.staff_external_id,
                        reserve_amount=0
                    )
                
                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                
                # Create Shift Audit Record
                _logger.info("Creating shift audit for CloseShift...")
                audit = self._create_shift_audit(env, cmd, 'close_shift')
                audit_id = audit.id if audit else None
                
                result = {
                    "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{cmd.staff_external_id or 'AUTO'}-01",
                    "total_cash": shift_totals.get('total_cash', 0.0),
                    "collection_result": collection_result,
                    "completed_at": fields.Datetime.now().isoformat(),
                    "audit_id": audit_id,
                }
                
                cmd.mark_done(result)
                _logger.info("CloseShift completed, audit_id=%s", audit_id)
                    
        except Exception as e:
            _logger.exception(" Failed to process close shift: %s", e)

    # =========================================================================
    # END OF DAY - ASYNC PROCESSING (UPDATED WITH STATUS POLLING)
    # =========================================================================

    def _process_end_of_day_async(self, dbname, uid, cmd_id):
        """
        Background thread to process end of day.
        
        Steps:
        1. Wait for processing delay
        2. Read collection mode from config
        3. Check inventory and collect (if sufficient reserve)
        4. If insufficient reserve: notify and complete (no unlock popup)
        5. If normal: Poll Glory status until IDLE, show unlock popup
        6. Mark command as done
        """
        try:
            delay = 2
            _logger.info("EndOfDay processing started, waiting %d seconds...", delay)
            time.sleep(delay)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    _logger.warning("Command %s not found", cmd_id)
                    return
                
                # Step 1: Read collection config
                config = _read_collection_config()
                collect_mode = config['end_of_day_collect_mode']
                reserve_amount = config['end_of_day_reserve_amount']
                
                _logger.info("EndOfDay collection mode: %s", collect_mode)
                _logger.info("EndOfDay reserve amount: %.2f", reserve_amount)
                
                # Step 2: Update overlay message - Checking inventory
                cmd.update_overlay_message("Checking cash inventory...")
                
                # Step 3: Collect cash (with insufficient reserve check)
                collection_result = self._collect_to_box(
                    env,
                    mode=collect_mode,
                    staff_id=cmd.staff_external_id,
                    reserve_amount=reserve_amount if collect_mode == 'except_reserve' else 0
                )
                _logger.info("Collection result: %s", collection_result)
                
                # Step 4: Check if insufficient reserve
                if collection_result.get('insufficient_reserve', False):
                    _logger.info("Insufficient reserve - notifying user")
                    
                    current_cash = collection_result.get('current_cash', 0.0)
                    required_reserve = collection_result.get('required_reserve', 0.0)
                    shortfall = required_reserve - current_cash
                    
                    # Calculate shift totals
                    shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                    
                    # Create Shift Audit Record
                    _logger.info("Creating shift audit for EndOfDay (insufficient reserve)...")
                    audit = self._create_shift_audit(env, cmd, 'end_of_day', collection_result)
                    
                    result = {
                        "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                        "final_shift_cash": shift_totals.get('total_cash', 0.0),
                        "final_shift_transactions": shift_totals.get('count', 0),
                        "collection_mode": collect_mode,
                        "collection_result": collection_result,
                        "completed_at": fields.Datetime.now().isoformat(),
                        # Insufficient reserve data
                        "insufficient_reserve": True,
                        "current_cash": current_cash,
                        "required_reserve": required_reserve,
                        "shortfall": shortfall,
                        # No unlock popup needed - no collection happened
                        "show_unlock_popup": False,
                        "collected_amount": 0.0,
                        "collected_breakdown": {},
                        "audit_id": audit.id if audit else None,
                    }
                    
                    # Mark as done with insufficient_reserve status
                    cmd.mark_insufficient_reserve(result)
                    _logger.info("EndOfDay command %s - completed (insufficient reserve), audit=%s", cmd_id, audit.name if audit else None)
                    return
                
                # Step 5: Normal flow - Update overlay and poll Glory status
                cmd.update_overlay_message("Collecting cash to Collection Box...")
                
                poll_result = self._glory_wait_for_idle()
                _logger.info("Poll result: %s", poll_result)
                
                # Step 6: Calculate shift totals
                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)
                
                # Create Shift Audit Record
                _logger.info("Creating shift audit for EndOfDay...")
                audit = self._create_shift_audit(env, cmd, 'end_of_day', collection_result)
                
                # Step 7: Prepare result with collection data for frontend
                result = {
                    "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                    "final_shift_cash": shift_totals.get('total_cash', 0.0),
                    "final_shift_transactions": shift_totals.get('count', 0),
                    "collection_mode": collect_mode,
                    "collection_result": collection_result,
                    "poll_result": poll_result,
                    "completed_at": fields.Datetime.now().isoformat(),
                    # Data for unlock popup
                    "show_unlock_popup": True,
                    "collected_amount": collection_result.get('collected_amount', 0.0),
                    "collected_breakdown": collection_result.get('collected_breakdown', {}),
                    "audit_id": audit.id if audit else None,
                }
                
                # Step 8: Mark as done with collection_complete status
                # This will update the overlay to show unlock popup
                cmd.mark_collection_complete(result)
                _logger.info("EndOfDay command %s - collection complete, audit=%s", cmd_id, audit.name if audit else None)
                    
        except Exception as e:
            _logger.exception("Failed to process end of day async: %s", e)
            # Try to mark as failed
            try:
                import odoo
                registry = odoo.registry(dbname)
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, uid, {})
                    cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                    if cmd.exists():
                        cmd.mark_failed(str(e))
            except:
                pass

    # =========================================================================
    # UNIT LOCK/UNLOCK ENDPOINTS (Step-by-Step)
    # =========================================================================

    @http.route("/gas_station_cash/unlock_unit", type="json", auth="user", methods=["POST"])
    def unlock_unit(self, **kwargs):
        """
        API endpoint to unlock a specific unit (notes or coins).
        """
        command_id = kwargs.get('command_id')
        target = kwargs.get('target', 'notes')  # 'notes' or 'coins'
        
        _logger.info(" Unlock %s request received (command_id=%s)", target, command_id)
        
        result = {
            'success': False,
            'message': '',
            'error': None,
        }
        
        try:
            unlock_result = self._glory_unlock_unit(target=target)
            
            if unlock_result['success']:
                result['success'] = True
                result['message'] = f'{target.capitalize()} box unlocked'
            else:
                result['error'] = unlock_result.get('error', 'Unlock failed')
                
        except Exception as e:
            _logger.exception(" Failed to unlock %s: %s", target, e)
            result['error'] = str(e)
        
        return result

    @http.route("/gas_station_cash/lock_unit", type="json", auth="user", methods=["POST"])
    def lock_unit(self, **kwargs):
        """
        API endpoint to lock a specific unit (notes or coins).
        """
        command_id = kwargs.get('command_id')
        target = kwargs.get('target', 'notes')  # 'notes' or 'coins'
        
        _logger.info(" Lock %s request received (command_id=%s)", target, command_id)
        
        result = {
            'success': False,
            'message': '',
            'error': None,
        }
        
        try:
            lock_result = self._glory_lock_unit(target=target)
            
            if lock_result['success']:
                result['success'] = True
                result['message'] = f'{target.capitalize()} box locked'
            else:
                result['error'] = lock_result.get('error', 'Lock failed')
                
        except Exception as e:
            _logger.exception(" Failed to lock %s: %s", target, e)
            result['error'] = str(e)
        
        return result

    @http.route("/gas_station_cash/complete_collection", type="json", auth="user", methods=["POST"])
    def complete_collection(self, **kwargs):
        """
        API endpoint to mark collection as complete after all boxes replaced.
        """
        command_id = kwargs.get('command_id')
        coins_completed = kwargs.get('coins_completed', False)
        notes_completed = kwargs.get('notes_completed', False)
        
        _logger.info(" Complete collection request (command_id=%s, coins=%s, notes=%s)",
                     command_id, coins_completed, notes_completed)
        
        result = {
            'success': True,
            'message': 'Collection completed',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "completed_at": fields.Datetime.now().isoformat(),
                        "coins_box_replaced": coins_completed,
                        "notes_box_replaced": notes_completed,
                    })
        except Exception as e:
            _logger.exception(" Failed to complete collection: %s", e)
            # Still return success - the boxes are replaced
        
        return result

    @http.route("/gas_station_cash/skip_unlock", type="json", auth="user", methods=["POST"])
    def skip_unlock(self, **kwargs):
        """
        API endpoint to skip unlocking and close the overlay.
        Called from frontend when user clicks "Skip" button.
        """
        _logger.info("Skip unlock request received")
        
        command_id = kwargs.get('command_id')
        current_step = kwargs.get('current_step', 1)
        coins_completed = kwargs.get('coins_completed', False)
        notes_completed = kwargs.get('notes_completed', False)
        
        result = {
            'success': True,
            'message': 'Unlock skipped',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "unlock_skipped": True,
                        "skipped_at": fields.Datetime.now().isoformat(),
                        "skipped_at_step": current_step,
                        "coins_box_replaced": coins_completed,
                        "notes_box_replaced": notes_completed,
                    })
        except Exception as e:
            _logger.exception("Failed to skip unlock: %s", e)
        
        return result

    @http.route("/gas_station_cash/close_insufficient_reserve", type="json", auth="user", methods=["POST"])
    def close_insufficient_reserve(self, **kwargs):
        """
        API endpoint to close the insufficient reserve overlay.
        Called from frontend when user acknowledges the insufficient reserve warning.
        """
        _logger.info("Close insufficient reserve request received")
        
        command_id = kwargs.get('command_id')
        
        result = {
            'success': True,
            'message': 'Insufficient reserve acknowledged',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "acknowledged_at": fields.Datetime.now().isoformat(),
                        "acknowledged_insufficient_reserve": True,
                    })
        except Exception as e:
            _logger.exception("Failed to close insufficient reserve: %s", e)
        
        return result

    # =========================================================================
    # CLOSE SHIFT ENDPOINT
    # =========================================================================

    def _handle_close_shift(self, **kwargs):
        """Handle CloseShift request from POS."""
        _logger.info("=" * 80)
        _logger.info("📥 CLOSE SHIFT REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        
        try:
            data = json.loads(raw)
        except Exception as e:
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        staff_id = data.get("staff_id") or self._get_default_staff_id()
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)
        
        # Check for pending transactions
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            cmd = self._create_command("close_shift", staff_id, {
                "pending_count": pending_count,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("Failed to push overlay: %s", e)
            
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
            
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
            })
        
        # No pending - process normally
        cmd = self._create_command("close_shift", staff_id, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
        except Exception as e:
            _logger.exception("Failed to push overlay: %s", e)
        
        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_close_shift_async, 
            args=(dbname, uid, cmd.id, False)
        )
        thread.daemon = True
        thread.start()
        
        return self._json_response({
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-01",
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "discription": "Deposit Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        })
    
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
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        
        try:
            data = json.loads(raw)
        except Exception as e:
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        staff_id = data.get("staff_id") or self._get_default_staff_id()
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)
        
        # Check for pending transactions
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            cmd = self._create_command("end_of_day", staff_id, {
                "pending_count": pending_count,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("Failed to push overlay: %s", e)
            
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
            
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
            })
        
        # No pending - process normally
        cmd = self._create_command("end_of_day", staff_id, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
        except Exception as e:
            _logger.exception("Failed to push overlay: %s", e)

        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_end_of_day_async, 
            args=(dbname, uid, cmd.id)
        )
        thread.daemon = True
        thread.start()

        return self._json_response({
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-EOD",
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "discription": "Deposit Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        })
    
    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    @http.route("/POS/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day_pos_prefix(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    # =========================================================================
    # HEARTBEAT ENDPOINT
    # =========================================================================

    @http.route("/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat(self, **kwargs):
        return self._json_response({
            "status": "acknowledged",
            "timestamp": fields.Datetime.now().isoformat(),
        })

    @http.route("/POS/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat_pos_prefix(self, **kwargs):
        return self._json_response({
            "status": "acknowledged",
            "timestamp": fields.Datetime.now().isoformat(),
        })