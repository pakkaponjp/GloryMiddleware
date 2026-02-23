# -*- coding: utf-8 -*-
#
# File: custom_addons/gas_station_cash/controllers/main.py
# Author: Pakkapon Jirachatmongkon
# Date: August 5, 2025
# Description: Odoo controller to proxy requests to the GloryAPI Flask server.
#
# License: P POWER GENERATING CO.,LTD.

import json
import logging
import requests
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# The URL of the local Flask API server
# NOTE: This assumes the Flask server is running on the same machine
# or is accessible at this address from the Odoo server.
GLORY_API_BASE_URL = "http://localhost:5000"

def _json_body():
    """Read JSON body for type='http' routes safely."""
    try:
        raw = request.httprequest.get_data(cache=False, as_text=True)  # str or ''
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

def _http_json_response(resp: requests.Response):
    """Pass-through HTTP response with JSON body."""
    # If Flask returns JSON text, forward it as-is with original status.
    return request.make_response(
        resp.text,
        headers=[('Content-Type', 'application/json')],
        status=resp.status_code,
    )


class GloryApiController(http.Controller):
    """
    Odoo Controller to handle requests from the front-end and forward them to the
    GloryAPI Flask server. This acts as a proxy to bypass cross-origin issues
    and ensure the front-end can communicate with the local API.
    """

    ########################## NEW API PROXY ROUTES ##########################
    # --- General STATUS (GET) - for heartbeat ---
    @http.route("/gas_station_cash/fcc/status", type="json", auth="user", csrf=False)
    def fcc_status_proxy(self):
        logging.info(">>>>>>>>>>>>>>>>>>>>>>>>Received request for /gas_station_cash/fcc/status")
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/status"
        logging.info("Forwarding request to GloryAPI at %s", url)
        try:
            _logger.info("Proxying request to GloryAPI /fcc/status")
            response = requests.get(url, params={"session_id": "1", "verify": "true"}) # NOTE: Add timeout parameter on porduction Ex. timeout=10
            response.raise_for_status()
        
            return response.json()
        
        except requests.exceptions.RequestException as e:
            _logger.error("Error connecting to GloryAPI at %s: %s", url, e)
            return request.make_response(
                json.dumps({"error": "Failed to connect to the GloryAPI server.", "details": str(e)}),
                status=500,
                headers=[('Content-Type', 'application/json')]
            )
    
    # --- Detailed STATUS - for Status button with human-readable message ---
    @http.route("/gas_station_cash/fcc/status-detailed", type="json", auth="user", csrf=False)
    def fcc_status_detailed_proxy(self):
        """Proxy to GloryAPI /fcc/api/v1/status-detailed for Status button."""
        _logger.info("Received request for /gas_station_cash/fcc/status-detailed")
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/status-detailed"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("Error connecting to GloryAPI at %s: %s", url, e)
            return {"status": "FAILED", "message": f"Connection error: {str(e)}"}
        
    # --- Cash-in START (accepts POST JSON from UI) ---
    @http.route([
        "/gas_station_cash/fcc/cash-in/start",
        "/gas_station_cash/fcc/cash_in/start",
    ], type="json", auth="user", methods=["POST"], csrf=False)
    def fcc_cashin_start_proxy(self, **kw):
        #payload = request.jsonrequest or {}
        raw = request.httprequest.data or b"{}"
        payload = json.loads(raw.decode("utf-8"))
        # Provide sane defaults if UI didn't send them
        payload.setdefault("user", "gs_cashier")
        payload.setdefault("session_id", "1")
        _logger.info("cash-in/start payload: %s", payload)

        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-in/start"
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()  # type="json" => return python object
        except requests.RequestException as e:
            _logger.error("cash-in/start proxy error: %s", e)
            return {"error": "Failed to reach GloryAPI", "details": str(e)}

    # # --- Cash-in STATUS (UI POST -> Flask GET) ---
    # @http.route('/gas_station_cash/fcc/cash_in/status', type='json', auth='user', methods=['POST'], csrf=False)
    # def fcc_cashin_status_proxy(self, **kw):
    #     """
    #     Proxy to Flask: GET /fcc/api/v1/cash-in/status
    #     UI posts empty JSON; we translate to GET with ?session_id=...
    #     """
    #     body = _json_body()
    #     sid  = body.get("session_id", "1")
    #     url  = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-in/status"
    #     _logger.info("Proxy cash-in/status -> %s (sid=%s)", url, sid)
    #     try:
    #         resp = requests.get(url, params={"session_id": sid}, timeout=10)
    #         resp.raise_for_status()
    #         return _http_json_response(resp)
    #     except requests.RequestException as e:
    #         _logger.error("cash-in/status proxy error: %s", e)
    #         return request.make_response(
    #             json.dumps({"error": "Failed to reach GloryAPI", "details": str(e)}),
    #             headers=[('Content-Type', 'application/json')],
    #             status=502,
    #         )

    # --- Cash-in STATUS (UI POST -> Flask GET) ---
    @http.route("/gas_station_cash/fcc/cash_in/status", type="json", auth="user", methods=["POST"], csrf=False)
    def fcc_cashin_status_proxy(self, **kw):
        # Read raw JSON body safely
        raw = request.httprequest.data or b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}

        sid = body.get("session_id", "1")
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-in/status"
        _logger.info("Proxy cash-in/status -> %s (sid=%s)", url, sid)
        try:
            resp = requests.get(url, params={"session_id": sid}, timeout=10)
            resp.raise_for_status()
            # IMPORTANT: type="json" expects a Python object, so return resp.json()
            return resp.json()
        except requests.RequestException as e:
            _logger.error("cash-in/status proxy error: %s", e)
            # Return a plain dict so Odoo serializes it as JSON-RPC
            return {"error": "Failed to reach GloryAPI", "details": str(e)}

    # --- Cash-in END (POST -> POST) ---
    @http.route('/gas_station_cash/fcc/cash_in/end', type='json', auth='user', methods=['POST'], csrf=False)
    def fcc_cashin_end_proxy(self, **kw):
        """
        Proxy to Flask: POST /fcc/api/v1/cash-in/end
        Body: {"session_id": "..."} (optional; default used if absent)
        """
        body = _json_body()
        sid  = body.get("session_id", "1")
        user = body.get("user", "gs_cashier")
        url  = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-in/end"
        _logger.info("Proxy cash-in/end -> %s (sid=%s, user=%s)", url, sid, user)
        try:
            resp = requests.post(url, json={"session_id": sid, "user": user}, timeout=15)
            resp.raise_for_status()
            return _http_json_response(resp)
        except requests.RequestException as e:
            _logger.error("cash-in/end proxy error: %s", e)
            return request.make_response(
                json.dumps({"error": "Failed to reach GloryAPI", "details": str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=502,
            )

    # --- Cash-in CANCEL (UI POSTs empty; proxy fills SID) ---
    @http.route([
        "/gas_station_cash/fcc/cash-in/cancel",
        "/gas_station_cash/fcc/cash_in/cancel",
    ], type="json", auth="user", methods=["POST"], csrf=False)
    def fcc_cashin_cancel_proxy(self, **kw):
        #body = request.jsonrequest or {}
        raw = request.httprequest.data or b"{}"
        payload = json.loads(raw.decode("utf-8"))
        payload.setdefault("session_id", "1")
        #payload = {"session_id": body.get("session_id", "1")}
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-in/cancel"
        try:
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error("cash-in/cancel proxy error: %s", e)
            return {"error": "Failed to reach GloryAPI", "details": str(e)}

    # --- Cash-out EXECUTE (POST -> POST) ---
    @http.route("/gas_station_cash/fcc/cash_out/execute", type="json", auth="user", methods=["POST"], csrf=False)
    def fcc_cashout_execute_proxy(self, **kw):
        """
        Proxy to Flask: POST /fcc/api/v1/cash-out/execute
        Body: {session_id, currency, notes:[{value, qty}], coins:[{value, qty}]}
        
        Note: type="json" means Odoo parses JSON and passes as kwargs, 
              not in request.httprequest.data
        """
        # Build payload from kwargs (Odoo already parsed JSON)
        payload = {
            "session_id": kw.get("session_id", "1"),
            "currency": kw.get("currency", "THB"),
            "amount": kw.get("amount", 0),
            "notes": kw.get("notes", []),
            "coins": kw.get("coins", []),
        }
        _logger.info("cash-out/execute payload: %s", payload)

        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-out/execute"
        try:
            resp = requests.post(url, json=payload, timeout=60)  # Increased timeout for cash-out
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            _logger.error("cash-out/execute proxy error: %s", e)
            return {"error": "Failed to reach GloryAPI", "details": str(e), "status": "FAILED"}

    # ==========================================================================
    # WITHDRAWAL / CASH AVAILABILITY ROUTES
    # ==========================================================================

    # --- Cash Availability (GET - for withdrawal screen) ---
    @http.route('/gas_station_cash/fcc/cash/availability',
                type='http', auth='user', methods=['GET'], csrf=False)
    def fcc_cash_availability_proxy(self, **kw):
        """
        Proxy to Flask: GET /fcc/api/v1/cash/availability
        Returns available denominations for withdrawal.
        Currency is optional - if not specified, auto-detect from machine.
        """
        sid = kw.get("session_id", "1")
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash/availability"
        
        # Build params - only include currency if explicitly specified
        params = {"session_id": sid}
        if kw.get("currency"):
            params["currency"] = kw.get("currency")
        
        _logger.info("Proxy cash/availability -> %s params=%s", url, params)
        
        try:
            resp = requests.get(url, params=params, timeout=15)
            
            _logger.info("cash/availability response status=%s body=%s", 
                        resp.status_code, resp.text[:300] if resp.text else "")
            
            return request.make_response(
                resp.text,
                headers=[('Content-Type', 'application/json')],
                status=resp.status_code,
            )
        except requests.RequestException as e:
            _logger.error("cash/availability proxy error: %s", e)
            return request.make_response(
                json.dumps({"error": "Failed to reach GloryAPI", "details": str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=502,
            )

    # --- Cash Inventory (GET - detailed inventory) ---
    @http.route('/gas_station_cash/fcc/cash/inventory',
                type='http', auth='user', methods=['GET'], csrf=False)
    def fcc_cash_inventory_proxy(self, **kw):
        """
        Proxy to Flask: GET /fcc/api/v1/cash/inventory
        Returns full inventory details including stock counts.
        """
        sid = kw.get("session_id", "1")
        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash/inventory"
        
        _logger.info("Proxy cash/inventory -> %s (sid=%s)", url, sid)
        
        try:
            resp = requests.get(url, params={"session_id": sid}, timeout=15)
            
            _logger.info("cash/inventory response status=%s", resp.status_code)
            
            return request.make_response(
                resp.text,
                headers=[('Content-Type', 'application/json')],
                status=resp.status_code,
            )
        except requests.RequestException as e:
            _logger.error("cash/inventory proxy error: %s", e)
            return request.make_response(
                json.dumps({"error": "Failed to reach GloryAPI", "details": str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=502,
            )

    # --- Middleware READY ---
    @http.route("/gas_station_cash/middleware/ready", type="json", auth="user", methods=["POST"], csrf=False)
    def middleware_ready(self, terminal_id=None, **kw):
        """
        Mark the middleware as ready for a given terminal.
        """
        _logger.info("Middleware marked as READY for terminal: %s", terminal_id)
        # TODO: Store this state somewhere if needed
        return {"status": "ok", "terminal_id": terminal_id}

    # --- Middleware NOT READY ---
    @http.route("/gas_station_cash/middleware/not_ready", type="json", auth="user", methods=["POST"], csrf=False)
    def middleware_not_ready(self, terminal_id=None, **kw):
        """
        Mark the middleware as NOT READY for a given terminal.
        """
        _logger.info("Middleware marked as NOT READY for terminal: %s", terminal_id)
        # TODO: Store this state somewhere if needed
        return {"status": "ok", "terminal_id": terminal_id}

    # --- Glory Heartbeat ---
    @http.route('/gas_station_cash/glory/status', type='http', auth='user', methods=['GET'], csrf=False)
    def glory_heartbeat_status(self):
        """
        Check the connection status to the Glory API for the heartbeat icon.
        Returns: {"overall_status": "connected" | "disconnected"}
        """
        try:
            url = f"{GLORY_API_BASE_URL}/fcc/api/v1/status"
            response = requests.get(url, timeout=5)
            if response.ok:
                return request.make_response(
                    json.dumps({"overall_status": "connected"}),
                    headers=[('Content-Type', 'application/json')]
                )
            else:
                return request.make_response(
                    json.dumps({"overall_status": "disconnected"}),
                    headers=[('Content-Type', 'application/json')]
                )
        except requests.exceptions.RequestException as e:
            _logger.error("Error connecting to GloryAPI for heartbeat: %s", e)
            return request.make_response(
                json.dumps({"overall_status": "disconnected"}),
                status=500,
                headers=[('Content-Type', 'application/json')]
            )

    @http.route('/gas_station_cash/get_staff_by_deposit_type', type='json', auth='user', methods=['POST'])
    def get_staff_by_deposit_type(self, deposit_type=None):
        """
        Returns a list of staff members based on the deposit type mapping to roles.
        
        Supported deposit_type values:
        - oil, engine_oil: attendant role
        - rental: tenant role
        - coffee_shop: coffee_shop_staff role
        - convenient_store: convenient_store_staff role
        - deposit_cash: cashier role
        - exchange_cash: all active staff (no role filter)
        - withdrawal: manager, supervisor, or cashier roles (multiple roles)
        """
        logging.info("Fetching staff for deposit type: %s", deposit_type)
        
        # Map deposit types to roles
        # False = no role filter (all active staff)
        # List = multiple roles allowed
        role_map = {
            'oil': 'attendant',
            'engine_oil': 'attendant',
            'rental': 'tenant',
            'coffee_shop': 'coffee_shop_staff',
            'convenient_store': 'convenient_store_staff',
            'deposit_cash': 'cashier',
            'exchange_cash': False,  # All staff can exchange
            'withdrawal': ['manager', 'supervisor', 'cashier', 'attendant'],  # Only these roles can withdraw. TODO: need to confirm roles and put in config
        }
        
        role = role_map.get(deposit_type)
        logging.info("Mapped role for deposit type '%s': %s", deposit_type, role)

        if role is None and deposit_type not in ['exchange', 'exchange_cash']:
            logging.error("Invalid deposit type: %s", deposit_type)
            return {'staff_list': [], 'error': 'Invalid deposit type'}

        domain = [('active', '=', True)]
        
        # Handle different role filter scenarios
        if role:
            if isinstance(role, list):
                # Multiple roles allowed (e.g., withdrawal)
                domain.append(('role', 'in', role))
            else:
                # Single role
                domain.append(('role', '=', role))
        # If role is False, no role filter (all active staff)

        staff = request.env['gas.station.staff'].sudo().search(domain)
        logging.debug(staff)

        # Corrected line: call read() directly on the staff recordset
        staff_list = staff.read(['id', 'name', 'role', 'external_id', 'nickname', 'employee_id', 'pin'])
    
        return {'staff_list': staff_list}

    @http.route('/gas_station_cash/verify_pin', type='json', auth='user', methods=['POST'])
    def verify_pin(self, staff_id=None, pin=None):
        """
        Verifies a staff member's PIN securely.
        """
        logging.debug("Verifying PIN for staff: ", request.env['gas.station.staff'])
        staff = request.env['gas.station.staff'].sudo().browse(staff_id)
        
        if not staff.exists():
            return {'success': False, 'message': 'Staff not found'}

        if staff.check_pin(pin):
            return {
                'success': True,
                'message': 'PIN verified successfully',
                'employee_details': {
                    'employee_id': staff.employee_id,
                    'external_id': staff.external_id,
                    'role': staff.role,  # or use label with dict(...).get(...)
                    'name': staff.name,  # Added name for display
                }
            }
        else:
            return {'success': False, 'message': 'Invalid PIN'}
    
    @http.route('/gas_station_cash/cashin/open', type='http', auth='user', methods=['POST'], csrf=False)
    def open_cashin(self):
        try:
            api_url = f"{GLORY_API_BASE_URL}/fcc/cashin/open"

            payload = {
                "amount": 1000,
                "currency_code": "JPY",
                "account_id": "ACC001"
            }
            headers = {'Content-Type': 'application/json'}
            response = requests.post(api_url, data=json.dumps(payload), headers=headers, timeout=20)

            # Check if the external API call was successful
            if response.status_code == 200:
                # Return the JSON response from the external API directly
                return request.make_response(
                    response.text,
                    headers={'Content-Type': 'application/json'}
                )
            else:
                # If the API call failed, return a structured error response
                error_data = {
                    'success': False,
                    'details': f'External API error: {response.status_code} - {response.text}'
                }
                return request.make_response(
                    json.dumps(error_data),
                    headers={'Content-Type': 'application/json'},
                    status=response.status_code
                )
        except Exception as e:
            # Handle any exceptions and return an error response
            error_data = {
                'success': False,
                'details': str(e)
            }
            return request.make_response(
                json.dumps(error_data),
                headers={'Content-Type': 'application/json'},
                status=500
            )

    # This route handles the request to close the cash-in port.
    @http.route('/gas_station_cash/cashin/close', type='http', auth='user', methods=['POST'], csrf=False)
    def close_cashin(self):
        try:
            # Add logic here to close the cash-in port on the device
            response_data = {
                'success': True,
                'details': 'Cash-in port closed successfully.'
            }
            return request.make_response(
                json.dumps(response_data),
                headers={'Content-Type': 'application/json'}
            )
        except Exception as e:
            error_data = {
                'success': False,
                'details': str(e)
            }
            return request.make_response(
                json.dumps(error_data),
                headers={'Content-Type': 'application/json'},
                status=500
            )

    # ---------------- OLD CHANGE OPERATION ---------------- #
    @http.route('/gas_station_cash/change', type='http', auth='public', methods=['POST'], csrf=False)
    def change_operation(self):
        _logger.debug(">>> /gas_station_cash/change called")
        try:
            data = json.loads(request.httprequest.data.decode("utf-8"))
            _logger.debug("Payload received: %s", data)

            api_url = f"{GLORY_API_BASE_URL}/fcc/change_operation"
            headers = {'Content-Type': 'application/json'}
            response = requests.post(api_url, data=json.dumps(data), headers=headers, timeout=30)

            return request.make_response(
                response.text,
                headers={'Content-Type': 'application/json'},
                status=response.status_code
            )
        except Exception as e:
            return request.make_response(
                json.dumps({'success': False, 'details': str(e)}),
                headers={'Content-Type': 'application/json'},
                status=500
            )