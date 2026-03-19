# -*- coding: utf-8 -*-

import json
import logging
import requests
import configparser
import os
from datetime import datetime
from odoo import http, tools
from odoo.http import request

_logger = logging.getLogger(__name__)

DEFAULT_SESSION_ID = "1"


def _read_bridge_api_url():
    """Read GloryAPI URL from odoo.conf [fcc_config] section."""
    try:
        conf_path = tools.config.rcfile
        if conf_path and os.path.exists(conf_path):
            parser = configparser.ConfigParser()
            parser.read(conf_path)
            host = parser.get('fcc_config', 'fcc_host', fallback='localhost').strip()
            port = parser.get('fcc_config', 'fcc_port', fallback='5000').strip()
            url = f"http://{host}:{port}"
            _logger.info("GloryAPI Bridge URL from odoo.conf: %s", url)
            return url
    except Exception as e:
        _logger.warning("Failed to read fcc_config from odoo.conf: %s", e)
    return "http://localhost:5000"


BRIDGE_API_URL = _read_bridge_api_url()


class MachineControlController(http.Controller):
    
    def _call_bridge_api(self, endpoint, method='GET', data=None):
        """Call Bridge API and return response"""
        try:
            url = f"{BRIDGE_API_URL}{endpoint}"
            _logger.info(f"Calling Bridge API: {method} {url}")
            
            if method == 'GET':
                response = requests.get(url, params=data, timeout=30)
            else:
                response = requests.post(url, json=data, timeout=30)
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Bridge API error: {str(e)}")
            return None

    def _call_collect_api(self, payload):
        """
        Call /fcc/api/v1/collect with Idempotency-Key header.
        Auto-retry once on result=11 (occupied by other) after 2s.
        """
        import time
        import uuid

        url = f"{BRIDGE_API_URL}/fcc/api/v1/collect"
        headers = {
            'Content-Type': 'application/json',
            'Idempotency-Key': str(uuid.uuid4()),
        }

        try:
            _logger.info(f"Calling collect API: POST {url} payload={payload}")
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            resp.raise_for_status()
            result = resp.json()
        except requests.exceptions.RequestException as e:
            _logger.error(f"Collect API error: {e}")
            return None

        # result=11 = occupied by other (verify step just completed, machine briefly busy)
        try:
            result_code = int(result.get('data', {}).get('result', -1))
        except Exception:
            result_code = -1

        if result_code == 11:
            _logger.warning('collect_cash: result=11 (occupied), retrying in 2s...')
            time.sleep(2)
            headers['Idempotency-Key'] = str(uuid.uuid4())
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                resp.raise_for_status()
                result = resp.json()
                _logger.info(f"collect_cash: retry result={result.get('data', {}).get('result')}")
            except requests.exceptions.RequestException as e:
                _logger.error(f"Collect API retry error: {e}")
                return None

        return result
    
    def _extract_request_data(self, kwargs):
        """Extract transaction data from kwargs (handles Odoo JSON-RPC format)"""
        # Method 0: Check if kwargs has 'params' (JSON-RPC format)
        if 'params' in kwargs:
            params = kwargs['params']
            if isinstance(params, dict):
                return params
        
        # Method 1: Direct kwargs
        if kwargs and ('transactionId' in kwargs or 'data' in kwargs or 'type' in kwargs or 'name' in kwargs):
            return kwargs
        
        # Method 2: Single dict parameter
        if len(kwargs) == 1:
            body = list(kwargs.values())[0]
            if isinstance(body, dict):
                if 'params' in body:
                    return body['params']
                return body
        
        # Method 3: Try request.jsonrequest
        try:
            json_body = request.jsonrequest
            if json_body and isinstance(json_body, dict):
                return json_body
        except AttributeError:
            pass
        
        return kwargs if kwargs else {}
    
    def _create_response(self, name, transaction_id, data, status_code=200):
        """Create standardized API response"""
        return {
            "type": "response",
            "name": name,
            "transactionId": transaction_id,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": status_code,
            "data": data
        }
    
    @http.route('/api/glory/cash_sale_start', type='json', auth='public', methods=['POST'], csrf=False)
    def cash_sale_start(self, **kwargs):
        """
        Start cash-in operation (simplified - just calls Bridge API)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            command_data = request_data.get('data', {})
            amount_to_pay = command_data.get('amountToPay', 0.0)
            transaction_id = request_data.get('transactionId', f'CS-{datetime.now().strftime("%Y%m%d%H%M%S")}')
            
            # Call Bridge API: Start Cash-in
            cashin_start = self._call_bridge_api(
                '/fcc/api/v1/cash-in/start',
                method='POST',
                data={
                    'user': 'gs_cashier',
                    'session_id': DEFAULT_SESSION_ID
                }
            )
            
            if not cashin_start:
                return self._create_response(
                    'cash_sale_start',
                    transaction_id,
                    {
                        "success": False,
                        "message": "Failed to start cash-in on Bridge API"
                    },
                    status_code=502
                )
            
            return self._create_response(
                'cash_sale_start',
                transaction_id,
                {
                    "success": True,
                    "message": f"Cash-in started. Please insert {amount_to_pay} THB.",
                    "transactionId": transaction_id,
                    "amountToPay": amount_to_pay,
                    "bridgeApiResponse": cashin_start
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in cash_sale_start: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'cash_sale_start',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error starting cash-in: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/cash_sale_status', type='json', auth='public', methods=['POST'], csrf=False)
    def cash_sale_status(self, **kwargs):
        """
        Get cash-in status (simplified - just calls Bridge API)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Call Bridge API: Get Cash-in Status
            cashin_status = self._call_bridge_api(
                '/fcc/api/v1/cash-in/status',
                method='GET',
                data={'session_id': DEFAULT_SESSION_ID}
            )
            
            if not cashin_status:
                return self._create_response(
                    'cash_sale_status',
                    transaction_id,
                    {
                        "success": False,
                        "message": "Failed to get cash-in status from Bridge API",
                        "transactionCompleted": False
                    },
                    status_code=502
                )
            
            # Extract counted amount if available
            counted_amount = 0.0
            state = cashin_status.get('state', 0)
            
            # Try to extract amount from response
            try:
                if 'counted' in cashin_status and 'thb' in cashin_status['counted']:
                    counted_amount = float(cashin_status['counted']['thb'])
            except (KeyError, ValueError, TypeError):
                pass
            
            return self._create_response(
                'cash_sale_status',
                transaction_id,
                {
                    "success": True,
                    "message": "Cash-in status retrieved successfully.",
                    "transactionCompleted": state == 3,
                    "countedAmount": counted_amount,
                    "bridgeApiStatus": cashin_status
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in cash_sale_status: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'cash_sale_status',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error getting cash-in status: {str(e)}",
                    "transactionCompleted": False
                },
                status_code=500
            )
    
    @http.route('/api/glory/payout', type='json', auth='public', methods=['POST'], csrf=False)
    def payout(self, **kwargs):
        """
        Execute cash-out/payout (simplified - just calls Bridge API)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            command_data = request_data.get('data', {})
            transaction_id = request_data.get('transactionId', f'PO-{datetime.now().strftime("%Y%m%d%H%M%S")}')
            
            amount = command_data.get('amount', 0.0)
            notes = command_data.get('notes', [])
            coins = command_data.get('coins', [])
            
            # Prepare denominations for Bridge API
            # Bridge API expects denominations in specific format
            # For simplicity, we'll call cash-out/execute with basic parameters
            # Note: Full implementation would require proper denomination mapping
            
            payout_response = self._call_bridge_api(
                '/fcc/api/v1/cash-out/execute',
                method='POST',
                data={
                    'session_id': DEFAULT_SESSION_ID,
                    'amount': amount * 100  # Convert to satang
                }
            )
            
            if not payout_response:
                return self._create_response(
                    'payout',
                    transaction_id,
                    {
                        "success": False,
                        "message": "Failed to execute payout on Bridge API"
                    },
                    status_code=502
                )
            
            return self._create_response(
                'payout',
                transaction_id,
                {
                    "success": True,
                    "message": f"Payout executed for {amount} THB.",
                    "bridgeApiResponse": payout_response
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in payout: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'payout',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error executing payout: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/check_float', type='json', auth='public', methods=['POST'], csrf=False)
    def check_float(self, **kwargs):
        """
        Check current inventory (simplified version)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Call Bridge API: Get Inventory
            inventory_response = self._call_bridge_api(
                '/fcc/api/v1/cash/inventory',
                method='GET',
                data={'session_id': DEFAULT_SESSION_ID}
            )
            
            # Call Bridge API: Get Availability
            availability_response = self._call_bridge_api(
                '/fcc/api/v1/cash/availability',
                method='GET',
                data={'session_id': DEFAULT_SESSION_ID}
            )
            
            return self._create_response(
                'float_balance_report',
                transaction_id,
                {
                    "success": True,
                    "message": "Current inventory retrieved.",
                    "bridgeApiInventory": inventory_response,
                    "bridgeApiAvailability": availability_response
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in check_float: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'float_balance_report',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error checking inventory: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/lock_units', type='json', auth='public', methods=['POST'], csrf=False)
    def lock_units(self, **kwargs):
        """
        Lock units (simplified - placeholder for Bridge API call)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Note: This is a placeholder - actual implementation would call Bridge API
            # Bridge API endpoint for locking units would need to be determined
            
            return self._create_response(
                'lock_units',
                transaction_id,
                {
                    "success": True,
                    "message": "Lock units command sent (placeholder - Bridge API endpoint needed)"
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in lock_units: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'lock_units',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error locking units: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/unlock_units', type='json', auth='public', methods=['POST'], csrf=False)
    def unlock_units(self, **kwargs):
        """
        Unlock units (simplified - placeholder for Bridge API call)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Note: This is a placeholder - actual implementation would call Bridge API
            # Bridge API endpoint for unlocking units would need to be determined
            
            return self._create_response(
                'unlock_units',
                transaction_id,
                {
                    "success": True,
                    "message": "Unlock units command sent (placeholder - Bridge API endpoint needed)"
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in unlock_units: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'unlock_units',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error unlocking units: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/reboot', type='json', auth='public', methods=['POST'], csrf=False)
    def reboot(self, **kwargs):
        """
        Reboot device (simplified - placeholder for Bridge API call)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Note: This is a placeholder - actual implementation would call Bridge API
            # Bridge API endpoint for rebooting would need to be determined
            
            return self._create_response(
                'reboot',
                transaction_id,
                {
                    "success": True,
                    "message": "Reboot command sent (placeholder - Bridge API endpoint needed)"
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in reboot: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'reboot',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error rebooting device: {str(e)}"
                },
                status_code=500
            )
    
    @http.route('/api/glory/shutdown', type='json', auth='public', methods=['POST'], csrf=False)
    def shutdown(self, **kwargs):
        """
        Shutdown device (simplified - placeholder for Bridge API call)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            
            # Note: This is a placeholder - actual implementation would call Bridge API
            # Bridge API endpoint for shutdown would need to be determined
            
            return self._create_response(
                'shutdown',
                transaction_id,
                {
                    "success": True,
                    "message": "Shutdown command sent (placeholder - Bridge API endpoint needed)"
                }
            )
            
        except Exception as e:
            _logger.error(f"Error in shutdown: {str(e)}")
            transaction_id = request_data.get('transactionId', '') if 'request_data' in locals() else ''
            return self._create_response(
                'shutdown',
                transaction_id,
                {
                    "success": False,
                    "message": f"Error shutting down device: {str(e)}"
                },
                status_code=500
            )

    # ──────────────────────────────────────────────────────────
    # Machine Control Routes — Wire to Glory Bridge API
    # ──────────────────────────────────────────────────────────

    @http.route('/api/glory/lock_unit', type='json', auth='public', methods=['POST'], csrf=False)
    def lock_unit(self, **kwargs):
        """Lock a specific unit (notes or coins) → /fcc/api/v1/unit/lock"""
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            command_data = request_data.get('data', {})
            target = command_data.get('target')          # "notes" | "coins"

            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/unit/lock',
                method='POST',
                data={
                    'session_id': DEFAULT_SESSION_ID,
                    'target': target,
                }
            )

            if bridge_resp is None:
                return self._create_response('lock_unit', transaction_id,
                    {"success": False, "message": "Bridge API unreachable"}, status_code=502)

            ok = str(bridge_resp.get('result', bridge_resp.get('result_code', '99'))) == '0'
            return self._create_response('lock_unit', transaction_id, {
                "success": ok,
                "message": f"Lock {target} {'succeeded' if ok else 'failed'}",
                "target": target,
                "bridgeApiResponse": bridge_resp,
            })

        except Exception as e:
            _logger.error(f"Error in lock_unit: {e}")
            return self._create_response('lock_unit', '',
                {"success": False, "message": str(e)}, status_code=500)

    @http.route('/api/glory/unlock_unit', type='json', auth='public', methods=['POST'], csrf=False)
    def unlock_unit(self, **kwargs):
        """Unlock a specific unit (notes or coins) → /fcc/api/v1/unit/unlock"""
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')
            command_data = request_data.get('data', {})
            target = command_data.get('target')          # "notes" | "coins"

            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/unit/unlock',
                method='POST',
                data={
                    'session_id': DEFAULT_SESSION_ID,
                    'target': target,
                }
            )

            if bridge_resp is None:
                return self._create_response('unlock_unit', transaction_id,
                    {"success": False, "message": "Bridge API unreachable"}, status_code=502)

            ok = str(bridge_resp.get('result', bridge_resp.get('result_code', '99'))) == '0'
            return self._create_response('unlock_unit', transaction_id, {
                "success": ok,
                "message": f"Unlock {target} {'succeeded' if ok else 'failed'}",
                "target": target,
                "bridgeApiResponse": bridge_resp,
            })

        except Exception as e:
            _logger.error(f"Error in unlock_unit: {e}")
            return self._create_response('unlock_unit', '',
                {"success": False, "message": str(e)}, status_code=500)

    @http.route('/api/glory/collect_all', type='json', auth='public', methods=['POST'], csrf=False)
    def collect_all(self, **kwargs):
        """Collect ALL cash → /fcc/api/v1/collect with plan=full.
        plan=full tells SOAP client to send Cash.type=0 (collect everything, no denomination list needed).
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')

            # plan=leave_float with empty target_float (keep 0 of everything)
            # Cash type=1 + explicit qty → machine physically moves cash
            # plan=full sends Cash type=0 which machine acknowledges but doesn't move
            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/collect',
                method='POST',
                data={
                    'session_id': DEFAULT_SESSION_ID,
                    'scope': 'all',
                    'plan': 'leave_float',
                    'target_float': {'denoms': []},
                }
            )

            if bridge_resp is None:
                return self._create_response('collect_all', transaction_id,
                    {'success': False, 'message': 'Bridge API unreachable'}, status_code=502)

            ok = bridge_resp.get('status') == 'OK'
            return self._create_response('collect_all', transaction_id, {
                'success': ok,
                'message': 'All cash sent to collection box' if ok else 'Collect failed',
                'bridgeApiResponse': bridge_resp,
            })

        except Exception as e:
            _logger.error(f'Error in collect_all: {e}')
            return self._create_response('collect_all', '',
                {'success': False, 'message': str(e)}, status_code=500)

    @http.route('/api/glory/collect_cash', type='json', auth='public', methods=['POST'], csrf=False)
    def collect_cash(self, **kwargs):
        """Collect cash with leave float logic.

        Algorithm:
          IF leave_float == OFF:
            → blocked (JS should not call this, but guard here)

          ELSE (leave_float == ON):
            Step 1: Read fcc_currency from odoo.conf [fcc_config]
            Step 2: Read float settings (setting_float_amount, setting denoms)
            Step 3: Get inventory from FCC
            Step 4: Compare inventory_amount vs setting_float_amount
              IF inventory_amount <= setting_float_amount:
                → collect NONE (insufficient cash)
                   float_difference = inventory_amount - setting_float_amount (negative)
              ELSE:
                Step 5: Check denomination match
                  IF all inventory_qty[denom] >= setting_qty[denom]:
                    → collect with min_qty (original logic)
                  ELSE:
                    → collect with greedy algorithm
                       (calculate keep Piece per denomination from float_amount)
        """
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')

            # ── Step 1: safety-check Leave Float setting ─────────────────────
            try:
                sICP = request.env['ir.config_parameter'].sudo()
                val = sICP.get_param('gas_station_cash.leave_float', 'False')
                leave_float = val in ('True', '1', 'true')
                _logger.info(f'collect_cash: leave_float={leave_float}')
            except Exception as _ex:
                leave_float = False
                _logger.warning(f'collect_cash: leave_float check failed ({_ex})')

            if not leave_float:
                _logger.warning('collect_cash: leave_float=False, blocked')
                return self._create_response('collect_cash', transaction_id, {
                    'success': False,
                    'message': 'Leave Float is disabled. Enable it after replenishment.',
                })

            # ── Step 2: read fcc_currency from odoo.conf [fcc_config] ────────
            try:
                _parser = configparser.ConfigParser()
                _conf_path = tools.config.rcfile
                if _conf_path:
                    _parser.read(_conf_path)
                cc = _parser.get('fcc_config', 'fcc_currency', fallback='THB').strip().upper()
            except Exception:
                cc = 'THB'
            _logger.info(f'collect_cash: using cc={cc} from odoo.conf [fcc_config]')

            # ── Step 3: read float settings from ir.config_parameter ─────────
            DENOM_PARAMS = [
                ('float_note_1000', 100000, 1),
                ('float_note_500',   50000, 1),
                ('float_note_100',   10000, 1),
                ('float_note_50',     5000, 1),
                ('float_note_20',     2000, 1),
                ('float_coin_10',     1000, 2),
                ('float_coin_5',       500, 2),
                ('float_coin_2',       200, 2),
                ('float_coin_1',       100, 2),
                ('float_coin_050',      50, 2),
                ('float_coin_025',      25, 2),
            ]
            IrConfig = request.env['ir.config_parameter'].sudo()
            setting_denoms = []
            for param_suffix, fv, devid in DENOM_PARAMS:
                qty = int(IrConfig.get_param(f'gas_station_cash.{param_suffix}', 0) or 0)
                if qty > 0:
                    setting_denoms.append({
                        'devid':   devid,
                        'cc':      cc,
                        'fv':      fv,
                        'min_qty': qty,
                    })

            if not setting_denoms:
                return self._create_response('collect_cash', transaction_id, {
                    'success': False,
                    'message': 'No float denominations configured. Please replenish first.',
                })

            # setting_float_amount in satang
            setting_float_amount = sum(d['fv'] * d['min_qty'] for d in setting_denoms)
            _logger.info(f'collect_cash: setting_float_amount={setting_float_amount} satang ({setting_float_amount/100:.2f} THB)')

            # ── Step 4: get inventory from FCC ───────────────────────────────
            # Use cash/availability (same as EOD in pos_commands.py)
            # Returns only dispensable (type=4) denominations as notes/coins arrays
            inv_resp = self._call_bridge_api(
                '/fcc/api/v1/cash/availability',
                method='GET',
                data={'session_id': DEFAULT_SESSION_ID}
            )
            if inv_resp is None:
                return self._create_response('collect_cash', transaction_id,
                    {'success': False, 'message': 'Cannot get inventory from FCC'}, status_code=502)

            # Parse availability — notes/coins format:
            # {"notes": [{"value": fv_satang, "qty": n, "device": devid}, ...],
            #  "coins": [{"value": fv_satang, "qty": n, "device": devid}, ...]}
            inventory_map = {}
            inventory_amount = 0  # satang

            try:
                notes = inv_resp.get('notes', [])
                coins = inv_resp.get('coins', [])
                _logger.info(f'collect_cash: availability notes={len(notes)}, coins={len(coins)}')
                for item in notes + coins:
                    fv    = int(item.get('value',  0) or 0)
                    qty   = int(item.get('qty',    0) or 0)
                    devid = int(item.get('device', 1) or 1)
                    if fv > 0 and qty > 0:
                        key = (devid, fv)
                        inventory_map[key] = inventory_map.get(key, 0) + qty
                        inventory_amount += fv * qty
                        _logger.debug(f'collect_cash: devid={devid} fv={fv} qty={qty}')
            except Exception as parse_err:
                _logger.warning(f'collect_cash: availability parse error: {parse_err}')

            _logger.info(f'collect_cash: inventory_amount={inventory_amount} satang, map={inventory_map}')

            # ── Step 5: compare inventory vs float setting ───────────────────
            if inventory_amount <= setting_float_amount:
                # Not enough cash — collect nothing
                float_difference = inventory_amount - setting_float_amount  # negative
                _logger.info(
                    f'collect_cash: inventory ({inventory_amount}) <= float ({setting_float_amount}), '
                    f'collect NONE, float_difference={float_difference}'
                )
                js_float = {
                    'notes': [{'value': d['fv'], 'qty': inventory_map.get((d['devid'], d['fv']), 0)}
                              for d in setting_denoms if d['devid'] == 1],
                    'coins': [{'value': d['fv'], 'qty': inventory_map.get((d['devid'], d['fv']), 0)}
                              for d in setting_denoms if d['devid'] == 2],
                }
                return self._create_response('collect_cash', transaction_id, {
                    'success': True,
                    'message': 'Insufficient cash for collection. Float kept as-is.',
                    'collect_none': True,
                    'float_difference': float_difference / 100.0,  # THB
                    'reserve_kept': inventory_amount / 100.0,
                    'target_float': js_float,
                    'bridgeApiResponse': None,
                })

            # ── Step 6: check denomination match ─────────────────────────────
            all_matched = all(
                inventory_map.get((d['devid'], d['fv']), 0) >= d['min_qty']
                for d in setting_denoms
            )
            _logger.info(f'collect_cash: all_matched={all_matched}')

            if all_matched:
                # ── Case A: matched — use original min_qty logic ──────────────
                _logger.info('collect_cash: using min_qty logic (all denominations matched)')
                target_float = {'denoms': setting_denoms}
                bridge_resp = self._call_collect_api({
                    'session_id': DEFAULT_SESSION_ID,
                    'scope': 'all',
                    'plan': 'leave_float',
                    'target_float': target_float,
                })
                if bridge_resp is None:
                    return self._create_response('collect_cash', transaction_id,
                        {'success': False, 'message': 'Bridge API unreachable'}, status_code=502)

                ok = bridge_resp.get('status') == 'OK'
                js_float = {
                    'notes': [{'value': d['fv'], 'qty': d['min_qty']} for d in setting_denoms if d['devid'] == 1],
                    'coins': [{'value': d['fv'], 'qty': d['min_qty']} for d in setting_denoms if d['devid'] == 2],
                }
                return self._create_response('collect_cash', transaction_id, {
                    'success': ok,
                    'message': 'Cash collected (float kept by denomination)' if ok else 'Collect failed',
                    'collect_mode': 'min_qty',
                    'float_difference': 0,
                    'target_float': js_float,
                    'bridgeApiResponse': bridge_resp,
                })

            else:
                # ── Case B: not matched — use greedy algorithm ────────────────
                _logger.info('collect_cash: using greedy algorithm (denomination mismatch)')

                # Greedy: keep up to setting_float_amount using largest denominations first
                # sorted by fv descending
                sorted_inv = sorted(
                    [
                        {'devid': devid, 'fv': fv, 'cc': cc, 'available': qty}
                        for (devid, fv), qty in inventory_map.items()
                    ],
                    key=lambda x: x['fv'],
                    reverse=True
                )

                remaining_satang = setting_float_amount
                greedy_keep = []  # denoms to keep (Piece = keep qty)

                for item in sorted_inv:
                    if remaining_satang <= 0:
                        break
                    fv        = item['fv']
                    available = item['available']
                    keep_qty  = min(available, remaining_satang // fv)
                    if keep_qty > 0:
                        greedy_keep.append({
                            'devid':   item['devid'],
                            'cc':      cc,
                            'fv':      fv,
                            'min_qty': keep_qty,
                        })
                        remaining_satang -= fv * keep_qty

                actual_kept_satang = setting_float_amount - remaining_satang
                _logger.info(
                    f'collect_cash: greedy keep={greedy_keep}, '
                    f'kept={actual_kept_satang} satang, remaining={remaining_satang}'
                )

                if not greedy_keep:
                    return self._create_response('collect_cash', transaction_id, {
                        'success': False,
                        'message': 'Greedy algorithm produced no result. Check inventory.',
                    })

                target_float = {'denoms': greedy_keep}
                bridge_resp = self._call_collect_api({
                    'session_id': DEFAULT_SESSION_ID,
                    'scope': 'all',
                    'plan': 'leave_float',
                    'target_float': target_float,
                })
                if bridge_resp is None:
                    return self._create_response('collect_cash', transaction_id,
                        {'success': False, 'message': 'Bridge API unreachable'}, status_code=502)

                ok = bridge_resp.get('status') == 'OK'
                js_float = {
                    'notes': [{'value': d['fv'], 'qty': d['min_qty']} for d in greedy_keep if d['devid'] == 1],
                    'coins': [{'value': d['fv'], 'qty': d['min_qty']} for d in greedy_keep if d['devid'] == 2],
                }
                return self._create_response('collect_cash', transaction_id, {
                    'success': ok,
                    'message': 'Cash collected (float kept by greedy algorithm)' if ok else 'Collect failed',
                    'collect_mode': 'greedy',
                    'float_difference': 0,
                    'target_float': js_float,
                    'bridgeApiResponse': bridge_resp,
                })

        except Exception as e:
            _logger.error(f'Error in collect_cash: {e}')
            return self._create_response('collect_cash', '',
                {'success': False, 'message': str(e)}, status_code=500)


    @http.route('/api/glory/open_exit_cover', type='json', auth='public', methods=['POST'], csrf=False)
    def open_exit_cover(self, **kwargs):
        """Open the exit note cover shutter → /fcc/api/v1/device/exit-cover/open"""
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')

            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/device/exit-cover/open',
                method='POST',
                data={'session_id': DEFAULT_SESSION_ID}
            )

            if bridge_resp is None:
                return self._create_response('open_exit_cover', transaction_id,
                    {"success": False, "message": "Bridge API unreachable"}, status_code=502)

            ok = bridge_resp.get('status') == 'OK'
            return self._create_response('open_exit_cover', transaction_id, {
                "success": ok,
                "message": "Exit cover opened" if ok else "Open exit cover failed",
                "bridgeApiResponse": bridge_resp,
            })

        except Exception as e:
            _logger.error(f"Error in open_exit_cover: {e}")
            return self._create_response('open_exit_cover', '',
                {"success": False, "message": str(e)}, status_code=500)

    @http.route('/api/glory/close_exit_cover', type='json', auth='public', methods=['POST'], csrf=False)
    def close_exit_cover(self, **kwargs):
        """Close the exit note cover shutter → /fcc/api/v1/device/exit-cover/close"""
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')

            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/device/exit-cover/close',
                method='POST',
                data={'session_id': DEFAULT_SESSION_ID}
            )

            if bridge_resp is None:
                return self._create_response('close_exit_cover', transaction_id,
                    {"success": False, "message": "Bridge API unreachable"}, status_code=502)

            ok = bridge_resp.get('status') == 'OK'
            return self._create_response('close_exit_cover', transaction_id, {
                "success": ok,
                "message": "Exit cover closed" if ok else "Close exit cover failed",
                "bridgeApiResponse": bridge_resp,
            })

        except Exception as e:
            _logger.error(f"Error in close_exit_cover: {e}")
            return self._create_response('close_exit_cover', '',
                {"success": False, "message": str(e)}, status_code=500)

    @http.route('/api/glory/reset', type='json', auth='public', methods=['POST'], csrf=False)
    def reset(self, **kwargs):
        """Soft reset machine → /fcc/api/v1/device/reset"""
        try:
            request_data = self._extract_request_data(kwargs)
            transaction_id = request_data.get('transactionId', '')

            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/device/reset',
                method='POST',
                data={'session_id': DEFAULT_SESSION_ID}
            )

            if bridge_resp is None:
                return self._create_response('reset', transaction_id,
                    {"success": False, "message": "Bridge API unreachable"}, status_code=502)

            ok = bridge_resp.get('status') == 'OK'
            return self._create_response('reset', transaction_id, {
                "success": ok,
                "message": "Machine reset successfully" if ok else "Reset failed",
                "bridgeApiResponse": bridge_resp,
            })

        except Exception as e:
            _logger.error(f"Error in reset: {e}")
            return self._create_response('reset', '',
                {"success": False, "message": str(e)}, status_code=500)