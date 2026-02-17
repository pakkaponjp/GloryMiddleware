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

