# -*- coding: utf-8 -*-

import json
import logging
import requests
from datetime import datetime
from odoo import http
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








