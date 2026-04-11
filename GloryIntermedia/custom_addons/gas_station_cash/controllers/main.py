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
from odoo import http, fields
from odoo.http import request
import configparser
import os
from odoo.tools import config as odoo_config

_logger = logging.getLogger(__name__)

# Read GloryAPI URL from odoo.conf [fcc_config] section
def _read_glory_api_url():
    conf_path = odoo_config.rcfile
    if not conf_path or not os.path.exists(conf_path):
        _logger.warning("fcc_host: odoo.conf not found, defaulting to localhost:5000")
        return "http://localhost:5000"
    parser = configparser.ConfigParser()
    parser.read(conf_path)
    host = parser.get("fcc_config", "fcc_host", fallback="localhost").strip()
    port = parser.get("fcc_config", "fcc_port", fallback="5000").strip()
    url = f"http://{host}:{port}"
    _logger.info("GloryAPI URL read from odoo.conf: %s", url)
    return url

GLORY_API_BASE_URL = _read_glory_api_url()

# Read fcc_currency from [fcc_config] section of odoo.conf.
# odoo.tools.config only exposes [options], so we use configparser directly.
def _read_fcc_currency():
    conf_path = odoo_config.rcfile  # path to the running odoo.conf
    if not conf_path or not os.path.exists(conf_path):
        _logger.warning("fcc_currency: odoo.conf not found, defaulting to THB")
        return "THB"
    parser = configparser.ConfigParser()
    parser.read(conf_path)
    currency = parser.get("fcc_config", "fcc_currency", fallback="THB").strip()
    _logger.info("fcc_currency read from odoo.conf: %s", currency)
    return currency

FCC_CURRENCY = _read_fcc_currency()

def _read_printer_config():
    conf_path = odoo_config.rcfile
    if not conf_path or not os.path.exists(conf_path):
        return None
    parser = configparser.ConfigParser()
    parser.read(conf_path)
    in_use = parser.get("options", "printer_in_use", fallback="false").strip().lower()
    if in_use not in ("true", "1", "yes"):
        return None
    host = parser.get("options", "ip_printer_api_host", fallback="localhost").strip()
    port = parser.get("options", "port_printer_api", fallback="5006").strip()
    return f"http://{host}:{port}"

PRINT_SERVICE_URL = _read_printer_config()
_logger.info("Print service URL: %s", PRINT_SERVICE_URL or "disabled")

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

########################## FINGERPRINT PROXY ROUTE ##########################
class GloryApiController(http.Controller):
    """
    Odoo Controller to handle requests from the front-end and forward them to the
    GloryAPI Flask server. This acts as a proxy to bypass cross-origin issues
    and ensure the front-end can communicate with the local API.
    """

    @http.route('/gas_station_cash/fingerprint/health', type='json', auth='none', methods=['POST'], csrf=False)
    def fingerprint_health(self, **kwargs):
        """
        Check fingerprint scanner health.
        1. If fingerprint_in_use=false in odoo.conf → skip, return not_configured.
        2. If fingerprint_in_use=true → proxy to Flask /api/v1/fingerprint/status.
        """
        in_use = str(odoo_config.get('fingerprint_in_use', 'false')).strip().lower() in ('true', '1', 'yes')
        if not in_use:
            return {"connected": False, "message": "Fingerprint not configured (fingerprint_in_use=false)."}

        host    = odoo_config.get('ip_fingerprint_enroll_api_host', '127.0.0.1')
        port    = odoo_config.get('port_fingerprint_enroll_api', '5005')
        timeout = int(odoo_config.get('fingerprint_health_timeout', 3))
        fp_url  = f"http://{host}:{port}"

        try:
            resp = requests.get(f"{fp_url}/api/v1/fingerprint/status", timeout=timeout)
            return resp.json()
        except requests.exceptions.Timeout:
            return {"connected": False, "message": "Fingerprint service timeout."}
        except Exception as e:
            return {"connected": False, "message": str(e)}

    @http.route('/gas_station_cash/fingerprint/identify', type='json', auth='user', methods=['POST'], csrf=False)
    def fingerprint_identify(self, candidates=None, threshold=50, **kwargs):
        """
        Proxy fingerprint identify request to the fingerprint service.
        Reads service URL from odoo.conf:
            ip_fingerprint_enroll_api_host
            port_fingerprint_enroll_api
        """
        host    = odoo_config.get('ip_fingerprint_enroll_api_host', '127.0.0.1')
        port    = odoo_config.get('port_fingerprint_enroll_api', '5005')
        timeout = int(odoo_config.get('timeout_fingerprint_enroll_api', 5))
        fp_url  = f"http://{host}:{port}"

        if not candidates:
            return {"status": "ERROR", "message": "candidates is required"}

        try:
            resp = requests.post(
                f"{fp_url}/api/v1/fingerprint/identify",
                json={"threshold": threshold, "candidates": candidates},
                timeout=timeout,
            )
            return resp.json()
        except requests.exceptions.Timeout:
            return {"status": "TIMEOUT", "message": "Scanner timed out"}
        except requests.exceptions.ConnectionError:
            return {"status": "ERROR", "message": f"Cannot reach fingerprint service at {fp_url}"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    @http.route('/gas_station_cash/fingerprint/abort', type='json', auth='user', methods=['POST'], csrf=False)
    def fingerprint_abort(self, **kwargs):
        """
        Abort an in-progress fingerprint scan on the scanner hardware.
        Called by JS when user navigates away from PIN entry screen.
        Non-critical — if scanner is already idle this is a no-op.
        """
        host   = odoo_config.get('ip_fingerprint_enroll_api_host', '127.0.0.1')
        port   = odoo_config.get('port_fingerprint_enroll_api', '5005')
        fp_url = f"http://{host}:{port}"

        try:
            resp = requests.post(f"{fp_url}/api/v1/fingerprint/abort", json={}, timeout=3)
            return resp.json()
        except Exception as e:
            _logger.debug("fingerprint/abort: %s (non-critical)", e)
            return {"status": "OK", "message": "abort sent (or scanner already idle)"}

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
            # Return parsed JSON so breakdown is accessible in JS via payload.result
            return resp.json()
        except requests.RequestException as e:
            _logger.error("cash-in/end proxy error: %s", e)
            return {"error": "Failed to reach GloryAPI", "details": str(e)}

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

    # --- Config endpoint: exposes read-only settings from odoo.conf to the frontend ---
    @http.route("/gas_station_cash/config", type="json", auth="user", methods=["POST"], csrf=False)
    def get_config(self, **kw):
        return {
            "currency": FCC_CURRENCY,
        }

    # --- Cash-out EXECUTE (POST -> POST) ---
    @http.route("/gas_station_cash/fcc/cash_out/execute", type="http", auth="user", methods=["POST"], csrf=False)
    def fcc_cashout_execute_proxy(self, **kw):
        """
        Proxy to Flask: POST /fcc/api/v1/cash-out/execute
        Body: {session_id, currency, notes:[{value, qty}], coins:[{value, qty}]}

        Using type="http" + manual body parsing because the frontend sends a
        plain JSON body (not Odoo JSON-RPC envelope).  With type="json" Odoo
        expects {"jsonrpc":"2.0","params":{...}} so **kw would be empty and
        notes/coins would silently default to [] causing a 400 from Flask.
        """
        raw = request.httprequest.get_data(cache=False, as_text=True)
        try:
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {}

        # Forward only the fields Flask expects -- do NOT include 'amount'
        payload = {
            "session_id": data.get("session_id", "1"),
            "currency":   FCC_CURRENCY,   # always use currency from odoo.conf [fcc_config] fcc_currency
            "notes":      data.get("notes", []),
            "coins":      data.get("coins", []),
        }
        _logger.info("cash-out/execute payload: %s", payload)

        url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-out/execute"
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            return request.make_response(
                resp.text,
                headers=[("Content-Type", "application/json")],
                status=resp.status_code,
            )
        except requests.RequestException as e:
            _logger.error("cash-out/execute proxy error: %s", e)
            return request.make_response(
                json.dumps({"error": "Failed to reach GloryAPI", "details": str(e), "status": "FAILED"}),
                headers=[("Content-Type", "application/json")],
                status=502,
            )

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
            
            #_logger.info("cash/availability response status=%s body=%s", 
            #            resp.status_code, resp.text[:300] if resp.text else "")
            
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

    @http.route('/gas_station_cash/print/deposit', type='json', auth='user', methods=['POST'], csrf=False)
    def print_deposit_receipt(self, **kw):
        """Print deposit receipt — breakdown from JS (Glory cash-in/end response)."""
        if not PRINT_SERVICE_URL:
            return {"status": "skipped"}
        try:
            total_satang = int((kw.get("amount") or 0) * 100)
            breakdown    = kw.get("breakdown") or {}
            deposit_id   = kw.get("deposit_id")
            if deposit_id and not breakdown:
                try:
                    dep = request.env['gas.station.cash.deposit'].sudo().browse(int(deposit_id))
                    if dep.exists():
                        total_satang = int((dep.total_amount or 0) * 100) or total_satang
                except Exception as e:
                    _logger.warning("deposit lookup: %s", e)
            company = request.env['res.company'].sudo().search([], limit=1)
            ICP     = request.env['ir.config_parameter'].sudo()
            payload = {
                "company_name": company.name or "",
                "branch_name":  ICP.get_param("gas_station_cash.branch_name", ""),
                "address":      company.street or "",
                "phone":        company.phone or "",
                "reference":    kw.get("reference", ""),
                "deposit_type": kw.get("deposit_type", ""),
                "staff_name":   kw.get("staff_name", ""),
                "datetime_str": kw.get("datetime_str", ""),
                "breakdown":    breakdown,
                "total_satang": total_satang,
            }
            r = requests.post(f"{PRINT_SERVICE_URL}/print/deposit", json=payload, timeout=10)
            _logger.info("Print deposit: status=%s ref=%s", r.status_code, kw.get("reference"))
            return {"status": "OK"}
        except Exception as e:
            _logger.error("print_deposit_receipt: %s", e)
            return {"status": "FAILED", "error": str(e)}

    @http.route('/gas_station_cash/print/deposit_with_amount', type='json', auth='user', methods=['POST'], csrf=False)
    def print_deposit_with_amount_receipt(self, **kw):
        """Print deposit_with_amount receipt — no breakdown (coffee_shop, convenient_store, rental)."""
        if not PRINT_SERVICE_URL:
            return {"status": "skipped"}
        try:
            total_satang = int((kw.get("total_satang") or kw.get("amount") or 0))
            deposit_id   = kw.get("deposit_id")
            product_name = kw.get("product_name") or ""
            if deposit_id and not product_name:
                try:
                    dep = request.env['gas.station.cash.deposit'].sudo().browse(int(deposit_id))
                    if dep.exists() and dep.product_id:
                        product_name = dep.product_id.name or ""
                except Exception as e:
                    _logger.warning("deposit_with_amount product lookup: %s", e)
            company = request.env['res.company'].sudo().search([], limit=1)
            ICP     = request.env['ir.config_parameter'].sudo()
            payload = {
                "company_name": company.name or "",
                "branch_name":  ICP.get_param("gas_station_cash.branch_name", ""),
                "address":      company.street or "",
                "phone":        company.phone or "",
                "reference":    kw.get("reference", ""),
                "deposit_type": kw.get("deposit_type", ""),
                "staff_name":   kw.get("staff_name", ""),
                "datetime_str": kw.get("datetime_str", ""),
                "product_name": product_name,
                "total_satang": total_satang,
            }
            r = requests.post(f"{PRINT_SERVICE_URL}/print/deposit_with_amount", json=payload, timeout=10)
            _logger.info("Print deposit_with_amount: status=%s ref=%s", r.status_code, kw.get("reference"))
            return {"status": "OK"}
        except Exception as e:
            _logger.error("print_deposit_with_amount_receipt: %s", e)
            return {"status": "FAILED", "error": str(e)}

    @http.route('/gas_station_cash/print/withdrawal', type='json', auth='user', methods=['POST'], csrf=False)
    def print_withdrawal_receipt(self, **kw):
        """Print withdrawal receipt.
        NOTE: withdrawal_screen.js sends breakdown values in THB (not satang).
              Convert THB -> satang here before forwarding to receipt builder.
        """
        if not PRINT_SERVICE_URL:
            return {"status": "skipped"}
        try:
            company = request.env['res.company'].sudo().search([], limit=1)
            ICP     = request.env['ir.config_parameter'].sudo()

            # Convert breakdown THB -> satang
            # withdrawal_screen.js sends value in THB (e.g. 20.0 = ฿20)
            # receipt_builder2.py expects satang (e.g. 2000 = ฿20)
            raw_breakdown = kw.get("breakdown") or {}
            def to_satang(items):
                result = []
                for item in (items or []):
                    val = float(item.get("value", 0) or 0)
                    qty = int(item.get("qty", 0) or 0)
                    if qty > 0:
                        satang = int(round(val * 100))  # withdrawal always sends THB
                        result.append({"value": satang, "qty": qty})
                return result

            breakdown_satang = {
                "notes": to_satang(raw_breakdown.get("notes", [])),
                "coins": to_satang(raw_breakdown.get("coins", [])),
            }

            payload = {
                "company_name":    company.name or "",
                "branch_name":     ICP.get_param("gas_station_cash.branch_name", ""),
                "address":         company.street or "",
                "phone":           company.phone or "",
                "reference":       kw.get("reference", ""),
                "staff_name":      kw.get("staff_name", ""),
                "datetime_str":    kw.get("datetime_str", ""),
                "withdrawal_type": kw.get("withdrawal_type", ""),
                "total_satang":    int(kw.get("total_satang") or 0),
                "breakdown":       breakdown_satang,
                "notes":           kw.get("notes", ""),
            }
            r = requests.post(f"{PRINT_SERVICE_URL}/print/withdrawal", json=payload, timeout=10)
            _logger.info("Print withdrawal: status=%s ref=%s", r.status_code, kw.get("reference"))
            return {"status": "OK"}
        except Exception as e:
            _logger.error("print_withdrawal_receipt: %s", e)
            return {"status": "FAILED", "error": str(e)}

    @http.route('/gas_station_cash/print/replenish', type='json', auth='user', methods=['POST'], csrf=False)
    def print_replenish_receipt(self, **kw):
        """Print replenish receipt."""
        if not PRINT_SERVICE_URL:
            return {"status": "skipped"}
        try:
            company = request.env['res.company'].sudo().search([], limit=1)
            ICP     = request.env['ir.config_parameter'].sudo()
            payload = {
                "company_name": company.name or "",
                "branch_name":  ICP.get_param("gas_station_cash.branch_name", ""),
                "address":      company.street or "",
                "phone":        company.phone or "",
                "reference":    kw.get("reference", ""),
                "staff_name":   kw.get("staff_name", ""),
                "datetime_str": kw.get("datetime_str", ""),
                "total_satang": int(kw.get("total_satang") or 0),
                "breakdown":    kw.get("breakdown") or {},
            }
            r = requests.post(f"{PRINT_SERVICE_URL}/print/replenish", json=payload, timeout=10)
            _logger.info("Print replenish: status=%s ref=%s", r.status_code, kw.get("reference"))
            return {"status": "OK"}
        except Exception as e:
            _logger.error("print_replenish_receipt: %s", e)
            return {"status": "FAILED", "error": str(e)}

    @http.route('/gas_station_cash/print/collect_cash', type='json', auth='user', methods=['POST'], csrf=False)
    def print_collect_cash_receipt(self, **kw):
        """Print collect cash receipt from Machine Control."""
        if not PRINT_SERVICE_URL:
            return {"status": "skipped"}
        try:
            company = request.env['res.company'].sudo().search([], limit=1)
            ICP     = request.env['ir.config_parameter'].sudo()
            payload = {
                "company_name":     company.name or "",
                "branch_name":      ICP.get_param("gas_station_cash.branch_name", ""),
                "address":          company.street or "",
                "phone":            company.phone or "",
                "reference":        kw.get("reference", ""),
                "staff_name":       kw.get("staff_name", ""),
                "datetime_str":     kw.get("datetime_str", ""),
                "collect_type":     kw.get("collect_type", "all"),
                "collected_amount": int(kw.get("collected_amount") or 0),
                "reserve_kept":     int(kw.get("reserve_kept") or 0),
                "breakdown":        kw.get("breakdown") or {},
            }
            r = requests.post(f"{PRINT_SERVICE_URL}/print/collect_cash", json=payload, timeout=10)
            _logger.info("Print collect_cash: status=%s ref=%s", r.status_code, kw.get("reference"))
            return {"status": "OK"}
        except Exception as e:
            _logger.error("print_collect_cash_receipt: %s", e)
            return {"status": "FAILED", "error": str(e)}

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
            'exit_fullscreen': 'has_odoo_user',  # Only staff with Related Odoo User
            'withdrawal': ['manager', 'supervisor', 'cashier', 'attendant'],  # Only these roles can withdraw. TODO: need to confirm roles and put in config
        }
        
        role = role_map.get(deposit_type)
        logging.info("Mapped role for deposit type '%s': %s", deposit_type, role)

        if role is None and deposit_type not in ['exchange', 'exchange_cash', 'exit_fullscreen']:
            logging.error("Invalid deposit type: %s", deposit_type)
            return {'staff_list': [], 'error': 'Invalid deposit type'}

        domain = [('active', '=', True)]

        # exit_fullscreen: only staff that have a Related Odoo User (user_id is set)
        if deposit_type == 'exit_fullscreen':
            domain.append(('user_id', '!=', False))
            staff = request.env['gas.station.staff'].sudo().search(domain)
            staff_list = [{
                'id':                       s.id,
                'name':                     s.name,
                'nickname':                 s.nickname or False,
                'employee_id':              s.employee_id,
                'external_id':              s.external_id or False,
                'role':                     s.role,
                'fingerprint_template_b64': s.fingerprint_template_b64 or False,
            } for s in staff]
            return {'staff_list': staff_list}

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
        # Build staff list manually to include fingerprint_template_b64
        # (protected field) and remove the virtual PIN field.
        staff_list = []
        for s in staff:
            staff_list.append({
                'id':                       s.id,
                'name':                     s.name,
                'nickname':                 s.nickname or False,
                'employee_id':              s.employee_id,
                'external_id':              s.external_id or False,
                'role':                     s.role,
                # Template needed for 1:N fingerprint identify on POS side
                'fingerprint_template_b64': s.fingerprint_template_b64 or False,
            })

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

    # ── Deposit with Change (coffee_shop / convenient_store / rental) ─────────
    # User enters exact deposit amount → Glory accepts cash ≥ amount → dispenses change
    @http.route('/gas_station_cash/deposit_with_change', type='json', auth='user', methods=['POST'], csrf=False)
    def deposit_with_change(self, deposit_type=None, amount_satang=0,
                            staff_external_id=None, employee_id=None, **kwargs):
        """
        Process deposit with exact amount via Glory ChangeOperation.
        1. Call /fcc/api/v1/change_operation (Glory accepts cash, dispenses change)
        2. Create gas.station.cash.deposit audit record
        """
        if not deposit_type:
            return {"success": False, "message": "deposit_type is required"}
        if not amount_satang or amount_satang <= 0:
            return {"success": False, "message": "amount must be greater than 0"}

        amount_thb = amount_satang / 100.0

        # ── Step 1: Call Glory change_operation via Flask Bridge ──────────────
        try:
            change_url = f"{GLORY_API_BASE_URL}/fcc/api/v1/change_operation"
            change_payload = {
                "amount":       amount_satang,
                "denominations": [],   # empty = machine decides denominations for change
            }
            _logger.info("[DepositWithChange] Calling change_operation amount=%s satang", amount_satang)

            resp = requests.post(change_url, json=change_payload, timeout=180)
            result = resp.json() if resp.ok else {}

            _logger.info("[DepositWithChange] change_operation response: %s", result)

            if not resp.ok or not result.get("success", False):
                err = result.get("details") or result.get("error") or f"HTTP {resp.status_code}"
                _logger.error("[DepositWithChange] change_operation failed: %s", err)

                # ── Cannot dispense change — return deposited cash to customer ──
                if result.get("cannot_dispense") or str(result.get("result_code", "")) == "10":
                    # Extract deposited denominations from Cash type=1
                    soap_data = result.get("data") or {}
                    notes, coins = [], []
                    for cash_item in (soap_data.get("Cash") or []):
                        denoms = cash_item.get("Denomination") or []
                        for d in denoms:
                            if int(d.get("Piece", 0)) <= 0:
                                continue
                            # Include "device" field — required by cash-out/execute
                            entry = {
                                "value":  int(d.get("fv", 0)),
                                "qty":    int(d.get("Piece", 0)),
                                "device": int(d.get("devid", 1)),
                            }
                            if cash_item.get("type") == 1:
                                notes.append(entry)   # deposited notes
                            elif cash_item.get("type") == 2:
                                coins.append(entry)   # deposited coins

                    _logger.info("[DepositWithChange] Returning cash — notes=%s coins=%s", notes, coins)

                    return_ok = False

                    # Step 1: Try ChangeCancelOperation first
                    try:
                        cancel_url = f"{GLORY_API_BASE_URL}/fcc/api/v1/change/cancel"
                        cancel_resp = requests.post(cancel_url, json={}, timeout=30)
                        cancel_result = cancel_resp.json() if cancel_resp.ok else {}
                        return_ok = cancel_result.get("success", False)
                        _logger.info("[DepositWithChange] change/cancel result: %s", cancel_result)
                    except Exception as ce:
                        _logger.error("[DepositWithChange] change/cancel failed: %s", ce)

                    # Step 2: If ChangeCancelOperation failed (result=11) → fallback to cash-out/execute
                    # The deposited note is now in the stacker — dispense it back to customer
                    if not return_ok and (notes or coins):
                        _logger.info("[DepositWithChange] ChangeCancelOperation failed — fallback to cash-out/execute")
                        try:
                            cashout_url = f"{GLORY_API_BASE_URL}/fcc/api/v1/cash-out/execute"
                            cashout_resp = requests.post(cashout_url, json={
                                "session_id": "1",
                                "currency":   FCC_CURRENCY,   # from odoo.conf fcc_currency
                                "notes":      notes,
                                "coins":      coins,
                            }, timeout=30)
                            cashout_result = cashout_resp.json() if cashout_resp.ok else {}
                            return_ok = cashout_result.get("status") == "OK"
                            _logger.info("[DepositWithChange] cash-out/execute result: %s", cashout_result)
                        except Exception as ce2:
                            _logger.error("[DepositWithChange] cash-out/execute failed: %s", ce2)

                    return {
                        "success":         False,
                        "cannot_dispense": True,
                        "return_ok":       return_ok,
                        "deposited_notes": notes,
                        "deposited_coins": coins,
                        "message": (
                            "Cannot dispense change. Please collect your cash from the exit slot."
                            if return_ok else
                            "Cannot dispense change. Please contact staff to collect your cash."
                        ),
                    }

                return {"success": False, "message": f"Machine error: {err}"}

        except requests.Timeout:
            return {"success": False, "message": "Machine timeout. Please try again."}
        except Exception as e:
            _logger.exception("[DepositWithChange] exception: %s", e)
            return {"success": False, "message": str(e)}

        # ── Step 2: Create deposit audit ──────────────────────────────────────
        try:
            env = request.env
            staff = None
            if staff_external_id:
                staff = env["gas.station.staff"].sudo().search(
                    [("external_id", "=", staff_external_id)], limit=1
                )
            if not staff and employee_id:
                staff = env["gas.station.staff"].sudo().search(
                    [("employee_id", "=", employee_id)], limit=1
                )

            if not staff:
                _logger.warning("[DepositWithChange] Staff not found — skipping audit")
            else:
                txn_id = f"TXN-{int(fields.Datetime.now().timestamp() * 1000)}"

                # oil → always POS related
                # engine_oil → only if product has is_pos_related = True
                # others (coffee_shop, rental, convenient_store) → never POS related
                is_pos_related = False
                if deposit_type == "oil":
                    is_pos_related = True
                elif deposit_type == "engine_oil" and product_id:
                    product = env["gas.station.cash.product"].sudo().browse(product_id)
                    is_pos_related = bool(product.is_pos_related)

                deposit = env["gas.station.cash.deposit"].sudo().create({
                    "name":           txn_id,
                    "deposit_type":   deposit_type,
                    "staff_id":       staff.id,
                    "state":          "confirmed",
                    "is_pos_related": is_pos_related,
                    "notes":          f"Deposit with change via ChangeOperation (฿{amount_thb:,.2f})",
                    "deposit_line_ids": [(0, 0, {
                        "currency_denomination": amount_thb,
                        "quantity":              1,
                    })],
                })
                _logger.info("[DepositWithChange] Created deposit audit id=%s amount=%.2f type=%s pos_related=%s",
                             deposit.id, deposit.total_amount, deposit_type, is_pos_related)

        except Exception as e:
            _logger.error("[DepositWithChange] Failed to create audit: %s", e)
            # Non-critical — machine already accepted cash, don't fail the response

        # Extract inserted amount and change from ChangeOperation response
        # Cash type=1 = deposited by customer, type=2 = change dispensed
        soap_data = result.get("data") or {}
        inserted_satang = 0
        change_satang   = 0
        for cash_item in (soap_data.get("Cash") or []):
            for d in (cash_item.get("Denomination") or []):
                fv  = int(d.get("fv", 0))
                qty = int(d.get("Piece", 0))
                if cash_item.get("type") == 1:
                    inserted_satang += fv * qty   # cash deposited by customer
                elif cash_item.get("type") == 2:
                    change_satang   += fv * qty   # change dispensed to customer

        _logger.info("[DepositWithChange] inserted=%s satang change=%s satang", inserted_satang, change_satang)

        return {
            "success":         True,
            "amount_thb":      amount_thb,
            "deposit_type":    deposit_type,
            "inserted_satang": inserted_satang,
            "change_satang":   change_satang,
            "message":         f"Deposit of ฿{amount_thb:,.2f} completed successfully.",
        }

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
    # ── /api/glory/check_float ─────────────────────────────────────────────
    # Called by cash_recycler_app.js and machine_control.js _loadAlerts()
    # Fetches both availability + inventory from Bridge API and returns combined.
    @http.route('/api/glory/check_float', type='json', auth='user', methods=['POST'], csrf=False)
    def api_check_float(self, **kw):
        """
        Combined availability + inventory endpoint for the frontend alert system.
        Returns:
        {
            "data": {
                "success": true,
                "bridgeApiAvailability": { "notes": [...], "coins": [...] },
                "bridgeApiInventory":    { "notes": [...], "coins": [...] }
            }
        }
        """
        try:
            sid = "1"
            base = GLORY_API_BASE_URL

            # Fetch availability (qty available for dispensing)
            avail_resp = requests.get(
                f"{base}/fcc/api/v1/cash/availability",
                params={"session_id": sid}, timeout=15
            )
            avail_data = avail_resp.json() if avail_resp.ok else {}

            # Fetch full inventory (current stacker counts)
            inv_resp = requests.get(
                f"{base}/fcc/api/v1/cash/inventory",
                params={"session_id": sid}, timeout=15
            )
            inv_data = inv_resp.json() if inv_resp.ok else {}

            return {
                "data": {
                    "success": True,
                    "bridgeApiAvailability": avail_data,
                    "bridgeApiInventory": inv_data,
                }
            }
        except Exception as e:
            _logger.error("api_check_float error: %s", e)
            return {
                "data": {
                    "success": False,
                    "message": str(e),
                    "bridgeApiAvailability": {},
                    "bridgeApiInventory": {},
                }
            }
            
    @http.route('/gas_station_cash/collect/save', type='json', auth='user', methods=['POST'], csrf=False)
    def save_collect_audit(self, **kw):
        """
        บันทึก Manual Collect Cash audit record
        Called by machine_control.js หลัง collect สำเร็จ

        Body (JSON):
            collect_type:      "all" | "leave_float"
            collected_amount:  int (satang)
            reserve_kept:      int (satang)
            breakdown:         {"notes": [...], "coins": [...]}
            staff_external_id: str (optional)
            datetime_str:      str (optional)
        """
        try:
            collect_type      = kw.get('collect_type', 'all')
            collected_satang  = int(kw.get('collected_amount') or 0)
            reserve_satang    = int(kw.get('reserve_kept') or 0)
            breakdown         = kw.get('breakdown') or {}
            staff_external_id = kw.get('staff_external_id') or ''

            record = request.env['gas.station.cash.collect'].sudo().create({
                'collect_type':      collect_type,
                'collected_amount':  collected_satang / 100.0,
                'reserve_kept':      reserve_satang / 100.0,
                'collection_breakdown': json.dumps(breakdown),
                'staff_external_id': staff_external_id,
            })

            _logger.info(
                "Manual collect audit saved: id=%s ref=%s type=%s amount=%.2f",
                record.id, record.name, collect_type, collected_satang / 100.0
            )
            return {'status': 'ok', 'id': record.id, 'name': record.name}

        except Exception as e:
            _logger.error("save_collect_audit error: %s", e)
            return {'status': 'error', 'message': str(e)}

    @http.route('/gas_station_cash/float/set_replenished', type='json', auth='user', methods=['POST'], csrf=False)
    def set_float_replenished(self, **kw):
        """
        Called after a successful replenishment (cash-in).
        - First replenish (leave_float=OFF): SET denomination quantities, enable leave_float.
        - Subsequent replenish (leave_float=ON): ADD to existing denomination quantities.
        """
        try:
            ICP = request.env['ir.config_parameter'].sudo()

            # Check if leave_float is already ON (subsequent replenishment)
            is_already_on = ICP.get_param('gas_station_cash.leave_float', 'False') in ('True', '1', 'true')

            # Mark as replenished and enable leave float
            ICP.set_param('gas_station_cash.float_replenished', 'True')
            ICP.set_param('gas_station_cash.leave_float', 'True')

            # Denomination map: key → (param, face_value_satang)
            denomination_new = kw.get('denomination', {})
            denom_map = {
                'note_1000': ('gas_station_cash.float_note_1000', 100000),
                'note_500':  ('gas_station_cash.float_note_500',   50000),
                'note_100':  ('gas_station_cash.float_note_100',   10000),
                'note_50':   ('gas_station_cash.float_note_50',     5000),
                'note_20':   ('gas_station_cash.float_note_20',     2000),
                'coin_10':   ('gas_station_cash.float_coin_10',     1000),
                'coin_5':    ('gas_station_cash.float_coin_5',       500),
                'coin_2':    ('gas_station_cash.float_coin_2',       200),
                'coin_1':    ('gas_station_cash.float_coin_1',       100),
                'coin_050':  ('gas_station_cash.float_coin_050',      50),
                'coin_025':  ('gas_station_cash.float_coin_025',      25),
            }

            total_satang = 0
            for key, (param, fv) in denom_map.items():
                new_qty = int(denomination_new.get(key, 0) or 0)

                if is_already_on:
                    # ADD to existing — top-up scenario
                    existing_qty = int(ICP.get_param(param, 0) or 0)
                    final_qty = existing_qty + new_qty
                    _logger.info(
                        "set_float_replenished: top-up %s: %d + %d = %d",
                        key, existing_qty, new_qty, final_qty
                    )
                else:
                    # SET new value — first replenishment
                    final_qty = new_qty

                ICP.set_param(param, str(final_qty))
                total_satang += final_qty * fv

            # Save float amount
            ICP.set_param('gas_station_cash.float_amount', str(total_satang / 100.0))

            mode = 'top_up' if is_already_on else 'set'
            total_thb = total_satang / 100.0

            # Sanity check: denomination total ต้องตรงกับ deposited_thb ที่ frontend ส่งมา
            # ถ้า mismatch → LiveCashInScreen ส่ง machine stock แทน deposited breakdown
            deposited_thb = float(kw.get('deposited_thb') or 0)
            new_qty_satang = sum(
                int(denomination_new.get(k, 0) or 0) * fv
                for k, (_p, fv) in denom_map.items()
            )
            new_qty_thb = new_qty_satang / 100.0
            if deposited_thb and abs(new_qty_thb - deposited_thb) > 0.01:
                _logger.warning(
                    "set_float_replenished (%s): MISMATCH — "
                    "denomination total=%.2f  deposited_thb=%.2f  diff=%.2f. "
                    "LiveCashInScreen may be sending machine stock instead of deposited breakdown! "
                    "denomination_new=%s",
                    mode, new_qty_thb, deposited_thb, abs(new_qty_thb - deposited_thb), denomination_new
                )
            else:
                _logger.info(
                    "set_float_replenished (%s): denomination=%.2f OK  float_total=%.2f  denomination=%s",
                    mode, new_qty_thb, total_thb, denomination_new
                )

            # ── Create replenish audit record (non-critical) ──────────────
            # THB value per denomination key
            denom_thb = {
                'note_1000': 1000.0, 'note_500': 500.0, 'note_100': 100.0,
                'note_50': 50.0,     'note_20': 20.0,
                'coin_10': 10.0,     'coin_5': 5.0,   'coin_2': 2.0,
                'coin_1': 1.0,       'coin_050': 0.5, 'coin_025': 0.25,
            }
            try:
                # Only create lines for denominations that were actually added (new_qty > 0)
                replenish_lines = [
                    {
                        'currency_denomination': denom_thb.get(key, fv / 100.0),
                        'quantity': int(denomination_new.get(key, 0) or 0),
                    }
                    for key, (_param, fv) in denom_map.items()
                    if int(denomination_new.get(key, 0) or 0) > 0
                ]

                staff_external_id = kw.get('staff_id') or kw.get('staff_external_id')
                staff = None
                if staff_external_id:
                    staff = request.env['gas.station.staff'].sudo().search(
                        [('external_id', '=', str(staff_external_id))], limit=1
                    )

                # Look up current active shift audit (state='draft' = shift in progress)
                # shift_audit states: draft=in progress, confirmed=closed, reconciled/discrepancy=audited
                current_shift = request.env['gas.station.shift.audit'].sudo().search(
                    [('state', '=', 'draft')],
                    order='id desc',
                    limit=1,
                )

                replenish_vals = {
                    'mode': mode,
                    'state': 'confirmed',
                    'notes': f"Replenish ({mode}) — ฿{sum(l['currency_denomination'] * l['quantity'] for l in replenish_lines):,.2f}",
                }
                if current_shift:
                    replenish_vals['audit_id'] = current_shift.id
                    _logger.info(
                        "set_float_replenished: linked to shift audit %s (shift_number=%s)",
                        current_shift.name, current_shift.shift_number
                    )
                else:
                    _logger.warning("set_float_replenished: no open shift audit found — Shift # will be 0")
                if staff:
                    replenish_vals['staff_id'] = staff.id
                if replenish_lines:
                    replenish_vals['replenish_line_ids'] = [
                        (0, 0, {'currency_denomination': l['currency_denomination'],
                                'quantity': l['quantity']})
                        for l in replenish_lines
                    ]

                replenish = request.env['gas.station.cash.replenish'].sudo().create(replenish_vals)
                _logger.info(
                    "set_float_replenished: created replenish audit %s amount=%.2f mode=%s",
                    replenish.name, replenish.total_amount, mode
                )
            except Exception as audit_err:
                # Non-critical — ICP already updated, don't fail the response
                _logger.error("set_float_replenished: failed to create replenish audit: %s", audit_err)

            return {
                'status': 'ok',
                'mode': mode,
                'float_amount': total_thb,
            }

        except Exception as e:
            _logger.error("set_float_replenished error: %s", e)
            return {'status': 'error', 'message': str(e)}