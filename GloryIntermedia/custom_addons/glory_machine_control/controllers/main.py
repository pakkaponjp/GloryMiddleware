# -*- coding: utf-8 -*-

import json
import logging
import requests
import configparser
from datetime import datetime
from odoo import http, tools
from odoo.http import request

_logger = logging.getLogger(__name__)

# Bridge API Configuration
BRIDGE_API_URL = "http://127.0.0.1:5000"
DEFAULT_SESSION_ID = "1"


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
        """Collect cash while leaving float → /fcc/api/v1/collect with plan=leave_float.

        Flow:
          1. Read gas_leave_float from res.config.settings — safety check (button should
             already be disabled in JS when false, but we guard here too).
          2. Read fcc_currency from odoo.conf (tools.config) — same value the Flask SOAP
             client uses, so cc always matches what the device returns in inventory.
          3. Read min_qty per denomination from ir.config_parameter
             (gas_station_cash.float_note_* / float_coin_*).
          4. Build target_float.denoms directly from settings — no inventory call needed.
          5. POST to /fcc/api/v1/collect with plan=leave_float.
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
                leave_float = True  # field not found → bypass (TODO: fix settings model)
                _logger.warning(f'collect_cash: leave_float check failed ({_ex}), bypassing')

            if not leave_float:
                _logger.warning('collect_cash: leave_float=False, blocked')
                return self._create_response('collect_cash', transaction_id, {
                    'success': False,
                    'message': 'Leave Float is disabled in settings. Enable it before collecting with float.',
                })

            # ── Step 2: read fcc_currency from odoo.conf [fcc_config] section ─
            # Flask SOAP client reads from the same section → cc always matches
            # what the device returns in inventory (e.g. EUR on emulator, THB on production).
            try:
                _parser = configparser.ConfigParser()
                _conf_path = tools.config.rcfile
                if _conf_path:
                    _parser.read(_conf_path)
                cc = _parser.get('fcc_config', 'fcc_currency', fallback='THB').strip().upper()
            except Exception:
                cc = 'THB'
            _logger.info(f'collect_cash: using cc={cc} from odoo.conf [fcc_config]')

            # ── Step 3: read float qty settings from Odoo UI ─────────────────
            # ir.config_parameter keys mirror the res.config.settings fields.
            # devid: 1 = notes recycler, 2 = coins recycler
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
            denoms = []
            for param_suffix, fv, devid in DENOM_PARAMS:
                qty = int(IrConfig.get_param(f'gas_station_cash.{param_suffix}', 0) or 0)
                if qty > 0:
                    denoms.append({
                        'devid':   devid,
                        'cc':      cc,
                        'fv':      fv,
                        'min_qty': qty,
                    })

            if not denoms:
                return self._create_response('collect_cash', transaction_id, {
                    'success': False,
                    'message': 'No float denominations configured. Please set float quantities in Settings.',
                })

            target_float = {'denoms': denoms}
            _logger.info(f'collect_cash: cc={cc}, target_float={target_float}')

            # ── Step 4: call bridge API ──────────────────────────────────────
            bridge_resp = self._call_bridge_api(
                '/fcc/api/v1/collect',
                method='POST',
                data={
                    'session_id': DEFAULT_SESSION_ID,
                    'scope': 'all',
                    'plan': 'leave_float',
                    'target_float': target_float,
                }
            )

            if bridge_resp is None:
                return self._create_response('collect_cash', transaction_id,
                    {'success': False, 'message': 'Bridge API unreachable'}, status_code=502)

            ok = bridge_resp.get('status') == 'OK'

            # Build notes/coins shape for JS float notification: "Float kept: ฿X"
            js_float = {
                'notes': [{'value': d['fv'], 'qty': d['min_qty']} for d in denoms if d['devid'] == 1],
                'coins': [{'value': d['fv'], 'qty': d['min_qty']} for d in denoms if d['devid'] == 2],
            }

            return self._create_response('collect_cash', transaction_id, {
                'success': ok,
                'message': 'Cash collected (float kept)' if ok else 'Collect failed',
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