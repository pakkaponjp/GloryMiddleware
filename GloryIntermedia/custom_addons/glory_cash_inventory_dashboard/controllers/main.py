# -*- coding: utf-8 -*-

import logging
import requests
from datetime import datetime
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Bridge API Configuration
BRIDGE_API_URL = "http://127.0.0.1:5000"
DEFAULT_SESSION_ID = "1"


class InventoryDashboardController(http.Controller):
    
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
    
    @http.route('/api/glory/get_change_allowed_notes', type='json', auth='public', methods=['POST'], csrf=False)
    def get_change_allowed_notes(self, **kwargs):
        """
        Get allowed note values for change calculation
        Returns the configured change_allowed_notes as a list
        """
        try:
            # Try to get from environment variable
            import os
            env_value = os.getenv('GLORY_CHANGE_ALLOWED_NOTES', '').strip()
            if env_value:
                values_list = [int(float(v.strip())) for v in env_value.split(',') if v.strip()]
                if values_list:
                    return {
                        "type": "response",
                        "name": "change_allowed_notes",
                        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "data": {
                            "success": True,
                            "allowedNotes": sorted(values_list)
                        }
                    }
            
            # Try to get from Odoo config parameter
            try:
                config_param = request.env['ir.config_parameter'].sudo().get_param('glory.change_allowed_notes', '')
                if config_param:
                    values_list = [int(float(v.strip())) for v in config_param.split(',') if v.strip()]
                    if values_list:
                        return {
                            "type": "response",
                            "name": "change_allowed_notes",
                            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "data": {
                                "success": True,
                                "allowedNotes": sorted(values_list)
                            }
                        }
            except Exception as e:
                _logger.debug(f"Could not read config parameter: {e}")
            
            # Default fallback
            values_list = [100, 500, 1000, 2000, 5000]
            return {
                "type": "response",
                "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": True,
                    "allowedNotes": values_list
                }
            }
        except Exception as e:
            _logger.error(f"Error getting change allowed notes: {str(e)}")
            return {
                "type": "response",
                "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": False,
                    "message": f"Error: {str(e)}",
                    "allowedNotes": [100, 500, 1000, 2000, 5000]  # Default fallback
                }
            }
    
    @http.route('/api/glory/get_branch_type', type='json', auth='public', methods=['POST'], csrf=False)
    def get_branch_type(self, **kwargs):
        """Get the configured branch type (convenience_store or gas_station)"""
        try:
            branch_type = request.env['ir.config_parameter'].sudo().get_param(
                'glory.branch_type', 'convenience_store'
            )
            return {'success': True, 'data': {'branch_type': branch_type}}
        except Exception as e:
            _logger.error(f"Error getting branch type: {str(e)}")
            return {'success': True, 'data': {'branch_type': 'convenience_store'}}

    @http.route('/api/glory/set_branch_type', type='json', auth='user', methods=['POST'], csrf=False)
    def set_branch_type(self, **kwargs):
        """Save the branch type setting"""
        try:
            branch_type = kwargs.get('branch_type', 'convenience_store')
            if branch_type not in ('convenience_store', 'gas_station'):
                return {'success': False, 'message': 'Invalid branch type'}
            request.env['ir.config_parameter'].sudo().set_param('glory.branch_type', branch_type)
            return {'success': True, 'data': {'branch_type': branch_type}}
        except Exception as e:
            _logger.error(f"Error setting branch type: {str(e)}")
            return {'success': False, 'message': str(e)}

    @http.route('/api/glory/check_float', type='json', auth='public', methods=['POST'], csrf=False)
    def check_float(self, **kwargs):
        """
        Check current inventory (simplified version for dashboard - no shift/transaction creation)
        Request: {
            "type": "command",
            "name": "check_float",
            "transactionId": "CHK-POS1-104",
            "timestamp": "2025-10-09T00:46:20Z",
            "data": {}
        }
        """
        try:
            # Extract request data
            request_data = kwargs
            if 'params' in kwargs:
                request_data = kwargs['params']
            elif len(kwargs) == 1:
                request_data = list(kwargs.values())[0]
            
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
            
            return {
                "type": "response",
                "name": "float_balance_report",
                "transactionId": transaction_id,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": True,
                    "message": "Current inventory retrieved.",
                    "bridgeApiInventory": inventory_response,
                    "bridgeApiAvailability": availability_response
                }
            }
            
        except Exception as e:
            _logger.error(f"Error in check_float: {str(e)}")
            transaction_id = ''
            try:
                request_data = kwargs
                if 'params' in kwargs:
                    request_data = kwargs['params']
                elif len(kwargs) == 1:
                    request_data = list(kwargs.values())[0]
                transaction_id = request_data.get('transactionId', '')
            except:
                pass
            
            return {
                "type": "response",
                "name": "float_balance_report",
                "transactionId": transaction_id,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": False,
                    "message": f"Error checking inventory: {str(e)}"
                }
            }

    @http.route('/api/glory/get_warning_levels', type='json', auth='public', methods=['POST'], csrf=False)
    def get_warning_levels(self, **kwargs):
        """
        Return wm_low / wm_high watermark thresholds from ir.config_parameter
        so the inventory dashboard can render watermark lines on cylinders.

        Response shape expected by JS:
        { "data": { "warningLevels": [ { "valueSatang": 100000, "warningQuantity": 20, "warningEnabled": true }, ... ] } }
        """
        # Map: (valueSatang, wmKey)
        DENOM_MAP = [
            (100000, 'note_1000'),
            ( 50000, 'note_500'),
            ( 10000, 'note_100'),
            (  5000, 'note_50'),
            (  2000, 'note_20'),
            (  1000, 'coin_10'),
            (   500, 'coin_5'),
            (   200, 'coin_2'),
            (   100, 'coin_1'),
            (    50, 'coin_050'),
            (    25, 'coin_025'),
        ]
        try:
            ICP = request.env['ir.config_parameter'].sudo()
            levels = []
            for satang, key in DENOM_MAP:
                low  = int(ICP.get_param(f'gas_station_cash.wm_low_{key}',  0) or 0)
                high = int(ICP.get_param(f'gas_station_cash.wm_high_{key}', 0) or 0)
                # warningQuantity used by legacy getWarningClass — map to wm_low
                levels.append({
                    'valueSatang':      satang,
                    'wmLow':            low,
                    'wmHigh':           high,
                    'warningQuantity':  low,
                    'warningEnabled':   low > 0 or high > 0,
                })
            return {
                'type': 'response',
                'name': 'warning_levels',
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'data': {'success': True, 'warningLevels': levels},
            }
        except Exception as e:
            _logger.error(f'get_warning_levels error: {e}')
            return {
                'type': 'response', 'name': 'warning_levels',
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'data': {'success': False, 'warningLevels': []},
            }

    @http.route('/api/glory/check_inventory_warnings', type='json', auth='public', methods=['POST'], csrf=False)
    def check_inventory_warnings(self, **kwargs):
        """
        Compare current inventory (from Bridge API) against wm_low / wm_high thresholds.
        Returns a list of warning objects for the dashboard notification system.
        """
        DENOM_MAP = [
            (100000, 'note_1000', '฿1,000'),
            ( 50000, 'note_500',  '฿500'),
            ( 10000, 'note_100',  '฿100'),
            (  5000, 'note_50',   '฿50'),
            (  2000, 'note_20',   '฿20'),
            (  1000, 'coin_10',   '฿10'),
            (   500, 'coin_5',    '฿5'),
            (   200, 'coin_2',    '฿2'),
            (   100, 'coin_1',    '฿1'),
            (    50, 'coin_050',  '฿0.50'),
            (    25, 'coin_025',  '฿0.25'),
        ]
        try:
            ICP = request.env['ir.config_parameter'].sudo()

            # Load thresholds
            thresholds = {}
            for satang, key, label in DENOM_MAP:
                thresholds[satang] = {
                    'label': label,
                    'low':  int(ICP.get_param(f'gas_station_cash.wm_low_{key}',  0) or 0),
                    'high': int(ICP.get_param(f'gas_station_cash.wm_high_{key}', 0) or 0),
                }

            # Fetch current availability from Bridge API
            avail = self._call_bridge_api(
                '/fcc/api/v1/cash/availability',
                method='GET',
                data={'session_id': DEFAULT_SESSION_ID}
            )

            warnings = []
            if avail:
                all_items = []
                if isinstance(avail, dict):
                    all_items += avail.get('notes', []) + avail.get('coins', [])

                for item in all_items:
                    satang = int(item.get('value', 0))
                    qty    = int(item.get('qty',   0))
                    t      = thresholds.get(satang)
                    if not t:
                        continue

                    if t['low'] > 0 and qty < t['low']:
                        warnings.append({
                            'valueSatang': satang,
                            'label':       t['label'],
                            'qty':         qty,
                            'threshold':   t['low'],
                            'type':        'near_empty',
                            'severity':    'critical' if qty == 0 else 'warning',
                            'message':     f"{t['label']}: qty {qty} below Near Empty threshold ({t['low']})",
                        })
                    elif t['high'] > 0 and qty > t['high']:
                        warnings.append({
                            'valueSatang': satang,
                            'label':       t['label'],
                            'qty':         qty,
                            'threshold':   t['high'],
                            'type':        'near_full',
                            'severity':    'warning',
                            'message':     f"{t['label']}: qty {qty} above Near Full threshold ({t['high']})",
                        })

            return {
                'type': 'response',
                'name': 'inventory_warnings',
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'data': {
                    'success':     True,
                    'hasWarnings': len(warnings) > 0,
                    'warnings':    warnings,
                },
            }
        except Exception as e:
            _logger.error(f'check_inventory_warnings error: {e}')
            return {
                'type': 'response', 'name': 'inventory_warnings',
                'timestamp': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                'data': {'success': False, 'hasWarnings': False, 'warnings': []},
            }