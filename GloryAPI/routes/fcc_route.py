#
# File: GloryAPI/routes/fcc_route.py
# Author: Pakkapon Jirachatmongkon
# Date: July 25, 2025 (Simple Monolith Structure, Updated for GetStatus and Cash-In Mapping)
# Description: Flask Blueprint for FCC (Financial Cash Controller) related API routes.
#
# License: P POWER GENERATING CO.,LTD.
#
# Usage: Registered with the main Flask app to provide FCC-related RESTful endpoints.
#
from flask import Blueprint, jsonify, request, current_app
import logging
import json
import uuid
from config import FCC_CURRENCY
from zeep.xsd.valueobjects import CompoundValue

# Import the FccSoapClient from its location in the 'services' directory
from services.fcc_soap_client import FccSoapClient
# Import the GlorySessionManager from its location in the 'services' directory
from services.glory_session_manager import GlorySessionManager
# Import Config from the root level
from config import Config
# Import the mapping functions from the 'api' directory
from api.fcc_api import map_fcc_status_response, \
                        map_cash_in_response, \
                        map_register_event_response,\
                        map_fcc_login_response, \
                        map_inventory_response

logger = logging.getLogger(__name__)

# Create a Blueprint for FCC routes with a URL prefix
fcc_bp = Blueprint('fcc', __name__, url_prefix='/fcc')

# Initialize the FCC SOAP client as a singleton.
# This client handles communication with the external FCC machine.
# It's initialized once when the blueprint is registered.
fcc_client = FccSoapClient(Config.FCC_SOAP_WSDL_URL)

# Log
session_manager = GlorySessionManager()

# routes/fcc_route.py (top-level or near the route)
RESULT_MAP = {
    "0": ("OK", 200),
    "1": ("NG (generic failure)", 502),
    "2": ("Invalid parameter", 400),
    "3": ("Unsupported / illegal state", 409),
    "4": ("Busy / already occupied / cannot lock now", 409),
    "5": ("Timeout", 504),
    "6": ("Hardware error", 502),
    "7": ("Cover open / sensor inhibit", 409),
    "8": ("Insufficient state (need idle)", 409),
    "9": ("Session conflict", 409),
    "10": ("Accepted / in progress", 202),
    "20": ("Illegal state/params for Open/Close", 409),
    # extend more from logs/docs
}

# Function
def _sum_items(items):
    return sum(int(x["value"]) * int(x["qty"]) for x in (items or []))

def _sum_payout(payout):
    return _sum_items(payout.get("notes")) + _sum_items(payout.get("coins"))

def _shape_basic_reply(op_name: str, raw: dict, session_id: str | None):
    result_attr = raw.get("result")
    status = "OK" if str(result_attr) == "0" else "FAILED"
    return {
        "status": status,
        "result_code": str(result_attr) if result_attr is not None else None,
        "session_id": session_id,
        "raw": raw,
        "operation": op_name,
    }, (200 if status == "OK" else 502)

########################## DEBUG ROUTES ##########################
@fcc_bp.get("/api/v1/_debug/soap-ops")
def debug_list_ops():
    try:
        svc = fcc_client.get_service_instance()
        ops = []
        c = fcc_client.client
        if c and c.wsdl and c.wsdl.bindings:
            for bname, binding in c.wsdl.bindings.items():
                try:
                    names = sorted(binding._operations.keys())
                except Exception:
                    names = []
                ops.append({"binding": str(bname), "operations": names})
        return jsonify({"ok": True, "ops": ops}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 502
    
@fcc_bp.route("/api/v1/_debug/soap-signature")
def debug_soap_signature():
    op_name = request.args.get("op")
    try:
        c = fcc_client.client
        if not c:
            return jsonify({"ok": False, "error": "SOAP client not ready"}), 500

        # assume single binding (your device shows one)
        binding = next(iter(c.wsdl.bindings.values()))
        op = binding._operations.get(op_name)
        if not op:
            return jsonify({"ok": False, "error": f"Operation '{op_name}' not found"}), 404

        # Safely introspect input parts/elements (works across Zeep versions)
        input_msg = op.input
        body_type = getattr(getattr(input_msg, "body", None), "type", None)

        elements = []
        skeleton = {}

        if body_type and hasattr(body_type, "elements"):
            for qname, element in body_type.elements:
                name = qname.localname if hasattr(qname, "localname") else str(qname)
                typ  = getattr(element.type, "qname", None)
                typ  = f"{typ.namespace}:{typ.localname}" if getattr(typ, "namespace", None) else str(getattr(element.type, "name", element.type))
                elements.append({"name": name, "type": typ})
                # sensible defaults for request skeleton
                if name.lower() in ("id", "seqno", "sessionid"):
                    skeleton[name] = ""
                elif name.lower() in ("option", "requireverification", "destinationtype"):
                    skeleton[name] = {"type": 0}
                elif name.lower() == "cash":
                    skeleton[name] = {"type": 0}
                else:
                    skeleton[name] = None
        else:
            # Fallback: try signature() without kwargs for a human string
            try:
                sig_str = input_msg.signature()
            except Exception:
                sig_str = None
            return jsonify({"ok": True, "operation": op_name, "signature_str": sig_str}), 200

        return jsonify({
            "ok": True,
            "operation": op_name,
            "elements": elements,
            "example_kwargs": skeleton
        }), 200

    except Exception as e:
        return jsonify({"ok": False, "error": f"{type(e).__name__}: {e}"}), 500

######################## # FCC Routes ##########################
# 1. Status Request: Heartbeat and status check
@fcc_bp.route("/api/v1/status", methods=["GET"])
def fcc_status():
    """
    Quick heartbeat. Calls GetStatus with Option=1.
    Query params:
      - session_id (optional)
      - verify=true|false (optional; adds RequireVerification)
    """
    sid = request.args.get("session_id") or "1"
    verify = (request.args.get("verify", "false").lower() == "true")
    logger.info(f"Received GET request for status with SID: {sid}, verify: {verify}")
    try:
        raw = fcc_client.get_status(session_id=sid, require_verification=verify)

        # Normalize result
        result_attr = raw.get("result")
        # Sometimes zeep flattens to int; normalize to string for consistency
        result_str = str(result_attr) if result_attr is not None else None

        status = "OK" if result_str == "0" else "FAILED"
        http_code = 200 if status == "OK" else 502

        out = {
            "status": status,           # OK | FAILED
            "code": result_str,         # raw result code from Glory (e.g., "0","10","99")
            "session_id": sid,
            "verify": verify,
            "raw": raw,                 # full payload for diagnostics
        }
        return jsonify(out), http_code

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("GetStatus failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

# 2. Change Request: Change operation
@fcc_bp.route("/api/v1/change_operation", methods=["POST"])
def change_operation():
    """
    Handles a change operation request from Odoo.
    Expects JSON payload:
    {
        "amount": 1000,
        "denominations": [ {"value": 500, "qty": 2}, {"value": 100, "qty": 5} ]
    }
    """
    try:
        data = request.get_json(force=True)
        amount = data.get("amount")
        denominations = data.get("denominations", [])

        if not amount or not denominations:
            return jsonify({"success": False, "details": "Invalid request: amount or denominations missing"}), 400

        # Call SOAP client
        soap_result = fcc_client.change_operation(amount, denominations)

        logger.debug("Change operation response: " + json.dumps(soap_result, indent=4))

        return jsonify({"success": True, "data": soap_result}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        return jsonify({"success": False, "details": str(e)}), 500

# 4. Start Cash in Request: Start deposit transaction
@fcc_bp.route("/api/v1/cash-in/start", methods=["POST"])
def cashin_start():
    """
    API endpoint to start a cash-in (deposit) transaction on the FCC machine.
    Body:
    {
      "user": "gs_cashier",        // required
      "session_id": "1"            // optional; if not provided, will login
    }
    """
    # data = request.get_json() # Get JSON data from the request body
    # if not data:
    #     return jsonify({"error": "Request body must be JSON."}), 400

    logger.info("Received POST request to start cash-in.")
    body = request.get_json(force=True) or {}
    logger.info(f"Request body: {body}")
    user = body.get("user")
    logger.info(f"User: {user}")
    sid = body.get("session_id")
    logger.info(f"Session ID: {sid}")

    if not user:
        return jsonify({"error": "user is required"}), 400

    if not sid:
        login_attempt = fcc_client.open_session(user, "PPower")

        if not login_attempt.get("success"):
            return jsonify({"error": f"login failed: {login_attempt.get('error')}"}), 502
        
        # Reuse your existing login helper through the client
        login = fcc_client.login_user(user)
        if not login.get("success"):
            return jsonify({"error": f"login failed: {login.get('error')}"}), 502
        sid = login.get("session_id") or login.get("data", {}).get("SessionID")

    logger.info(f"Using session_id: {sid} for user: {user}")

    try:
        logger.info("Calling start_cashin on FCC client")
        response = fcc_client.start_cashin(session_id=sid)
        return jsonify({"session_id": sid, "result": response}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("start_cashin failed")
        return jsonify({"error": f"upstream: {e}"}), 502
    
# 5. End Cash in Request: End deposit transaction
@fcc_bp.route("/api/v1/cash-in/end", methods=["POST"])
def cashin_end():
    """
    API endpoint to end a cash-in (deposit) transaction on the FCC machine.
    Body:
    {
      "user": "gs_cashier",        // required
        "session_id": "1"            // required
    }
    """
    body = request.get_json(force=True) or {}
    user = body.get("user")
    sid = body.get("session_id")

    if not user or not sid:
        return jsonify({"error": "user and session_id are required"}), 400

    try:
        resp = fcc_client.end_cashin(session_id=sid)
        return jsonify({"session_id": sid, "result": resp}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("end_cashin failed")
        return jsonify({"error": f"upstream: {e}"}), 502

# 6. Cancel Cash in Request: Cancel deposit transaction
@fcc_bp.route("/api/v1/cash-in/cancel", methods=["POST"])
def cashin_cancel():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")

    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        raw = fcc_client.cancel_cashin(session_id=sid) or {}

        # Normalize result code from various possible places
        def _get_result(o: dict):
            if not isinstance(o, dict):
                return None
            if "result" in o and o.get("result") is not None:
                return o.get("result")
            # some zeep serializations place attributes under _attr / _attributes
            attr = o.get("_attr") or o.get("_attributes") or {}
            return attr.get("result")

        rc = _get_result(raw)
        # result may be int or string - normalize to string for consistency
        rc_str = str(rc) if rc is not None else None

        status = "OK" if rc_str == "0" else "FAILED"
        http_code = 200 if status == "OK" else 502

        return jsonify({
            "session_id": str(sid),
            "status": status,
            "result_code": rc_str,
            "raw": raw
        }), http_code

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("cashin_cancel failed")
        return jsonify({"error": f"upstream: {e}"}), 502
    
# 7. Cash out Request: Execute dispense operation (Cash-out/widraw)
@fcc_bp.route("/api/v1/cash-out/execute", methods=["POST"])
def api_cash_out_execute():
    try:
        payload = request.get_json(force=True) or {}
        session_id = str(payload.get("session_id", "1"))
        currency   = payload.get("currency", FCC_CURRENCY)

        notes = payload.get("notes", [])
        coins = payload.get("coins", [])

        denominations = []
        for n in notes:
            denominations.append({
                "cc":     currency,
                "fv":     int(n["value"]),
                "devid":  1,
                "Piece":  int(n["qty"]),
                "Status": 0,
            })
        for c in coins:
            denominations.append({
                "cc":     currency,
                "fv":     int(c["value"]),
                "devid":  2,
                "Piece":  int(c["qty"]),
                "Status": 0,
            })

        raw = fcc_client.cashout_execute_by_denoms(
            session_id=session_id,
            currency=currency,
            denominations_list=denominations,
            note_dest="exit",
            coin_dest="exit",
        )

        # Normalize result
        result_code = str((raw or {}).get("result")) if (raw and "result" in raw) else None
        ok_codes = {"0", "10"}  # treat "10" as accepted/in-progress OK
        status = "OK" if result_code in ok_codes else "FAILED"
        http = 200 if status == "OK" else 502

        return jsonify({
            "status": status,
            "result_code": result_code,
            "session_id": session_id,
            "raw": raw,
        }), http

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        current_app.logger.exception("cash_out/execute failed")
        return jsonify({
            "error": f"{type(e).__name__}: {e}",
            "status": "FAILED",
        }), 502

# 8. Inventory Request: Get current cash inventory
@fcc_bp.route("/api/v1/cash/inventory", methods=["GET"])
def cash_inventory():
    """
    GET /fcc/api/v1/cash/inventory?session_id=...
    Returns current stock of notes & coins and raw machine sections.
    """
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        raw = fcc_client.inventory(session_id=sid)

        # The serialized shape usually contains either:
        #   { "InventoryResponse": {...} }
        # or fields promoted to the top-level by your serializer.
        # Normalize to a single container 'R' to read from.
        R = raw.get("InventoryResponse") if isinstance(raw, dict) else None
        R = R or raw  # fall back to raw if already flat

        # result code (string or int)
        result_code = str(R.get("result")) if isinstance(R.get("result"), (str, int)) else None

        # Collect all <Cash> blocks; some firmwares return multiple (type=3,4,...)
        cash_blocks = R.get("Cash")
        if isinstance(cash_blocks, dict):
            cash_blocks = [cash_blocks]
        cash_blocks = cash_blocks or []

        notes, coins = [], []
        currency = None

        def push_item(d):
            nonlocal currency
            value  = int(d.get("fv", 0) or 0)
            qty    = int(d.get("Piece", 0) or 0)
            devid  = int(d.get("devid", 0) or 0)
            cc     = d.get("cc")
            if cc and not currency:
                currency = cc
            item = {
                "cc": cc,
                "value": value,
                "qty": qty,
                "amount": value * qty,
                "device": devid,                 # 1=notes, 2=coins
                "status": int(d.get("Status", 0) or 0),
                "rev": int(d.get("rev", 0) or 0),
            }
            (coins if devid == 2 else notes).append(item)

        for cb in cash_blocks:
            denoms = cb.get("Denomination") or []
            # Denomination can be dict or list
            if isinstance(denoms, dict):
                denoms = [denoms]
            for d in denoms:
                push_item(d)

        total_notes = sum(x["amount"] for x in notes)
        total_coins = sum(x["amount"] for x in coins)

        # Also surface CashUnits (per-cassette/hopper info) if present
        cash_units = R.get("CashUnits")
        if isinstance(cash_units, dict):
            cash_units = [cash_units]  # unify to list
        cash_units = cash_units or []

        response = {
            "result_code": result_code,      # "0" for OK in your sample
            "currency": currency,
            "notes": notes,
            "coins": coins,
            "totals": {
                "notes": total_notes,
                "coins": total_coins,
                "grand": total_notes + total_coins,
            },
            "units": cash_units,             # raw per-device unit summary (as-is)
            "raw": raw                       # keep full raw for troubleshooting
        }

        # Return 200 for OK (0), 207 Multi-Status for non-zero with data
        code = 200 if result_code in (None, "0") else 207
        return jsonify(response), code

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("cash_inventory failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

# 9. Collect Request: Start collect transaction
# @fcc_bp.route("/api/v1/cash/collect", methods=["POST"])
# def cash_collect():
#     body = request.get_json(force=True, silent=True) or {}
#     sid = str(body.get("session_id", "")).strip()
#     if not sid:
#         return jsonify({"error": "session_id is required"}), 400

#     scope = body.get("scope", "all")
#     plan = body.get("plan", "full")
#     target_float = body.get("target_float")  # optional

#     try:
#         data = fcc_client.collect(session_id=sid, scope=scope, plan=plan, target_float=target_float)
#         result = str(data.get("result"))
#         status = "OK" if result == "0" or data.get("result") == 0 else "FAILED"
#         return jsonify({
#             "session_id": sid,
#             "scope": scope,
#             "plan": plan,
#             "status": status,
#             "result_code": result,
#             "raw": data
#         }), (200 if status == "OK" else 502)
#     except Exception as e:
#         logger.exception("cash_collect failed")
#         return jsonify({"error": f"upstream: {e}"}), 502
@fcc_bp.route("/api/v1/collect", methods=["POST"])
def collect_api():
    body = request.get_json(force=True) or {}
    sid   = body.get("session_id")
    scope = (body.get("scope") or "all").lower()        # "all" | "notes" | "coins"
    plan  = (body.get("plan")  or "full").lower()       # "full" | "leave_float"
    target_float = body.get("target_float")             # optional

    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        client = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        data = client.collect(session_id=sid, scope=scope, plan=plan, target_float=target_float)
        return jsonify({"status": "OK", "data": data}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502
    
# 10. Reset Request
@fcc_bp.route("/api/v1/device/reset", methods=["POST"])
def device_reset():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        resp = fcc_client.device_reset(session_id=str(sid))  # implement on the client (below)
        # Expecting zeep-serialized dict with 'result' like other ops
        code = str((resp or {}).get("result", "99"))
        return jsonify({
            "operation": "device_reset",
            "session_id": str(sid),
            "status": "OK" if code == "0" else "FAILED",
            "result_code": code,
            "raw": resp,
        }), 200 if code == "0" else 502
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("device_reset failed")
        return jsonify({"error": f"upstream: {e}"}), 502

# 11. Counter Clear Request
@fcc_bp.post("/api/v1/counter/clear")
def counter_clear():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.device_counter_clear(session_id=session_id)  # <-- no option_type
        return jsonify(out), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("counter/clear failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502

# 12. Register Event Request: Register the receiver of the event notification.
@fcc_bp.route("/api/v1/events/register", methods=["POST"])
def events_register():
    """
    Register the callback endpoint on the FCC for events/notifications.
    Body:
    {
      "url": "192.168.0.1",        // your listener host/IP
      "port": 55562,               // your listener port
      "destination_type": 0,       // matches sample
      "events": [1,2,...]          // optional; defaults to 1..96
      "session_id": "1"            // optional; default "1"
    }
    """
    body = request.get_json(force=True) or {}
    url = body.get("url")
    port = body.get("port")
    dest = int(body.get("destination_type", 0))
    events = body.get("events")
    sid = body.get("session_id")  # optional

    if not url or not port:
        return jsonify({"error": "url and port are required"}), 400

    try:
        resp = fcc_client.register_event(
            url=url, port=int(port), destination_type=dest, require_events=events, session_id=sid
        )
        if not resp.get("success"):
            return jsonify({"error": resp.get("error")}), 502
        return jsonify({"success": True, "data": resp.get("data")}), 200
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("events_register failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

# 13. Unregister Event Request: UnRegisterEventOperation to unregister event notifications.

# 15. User Login Request: Login user to get session_id
@fcc_bp.route("/api/v1/login", methods=["POST"])
def login_user_route():
    """
    Body:
    {
      "user": "gs_cashier",
      "password": "PPower",
      "id": "",
      "seqno": "",
      "open_session": false,          // optional; if true, do OpenOperation after login
      "device_name": "CI-10",         // required if open_session=true
      "custom_id": ""                 // optional for open
    }
    """
    body = request.get_json(force=True) or {}
    user     = (body.get("user") or "").strip()
    password = (body.get("password") or "").strip()
    idv      = body.get("id", "")
    seqno    = body.get("seqno", "")
    open_sess = bool(body.get("open_session", False))
    device_name = body.get("device_name") or getattr(Config, "FCC_DEVICE_NAME", "CI-10")
    custom_id   = body.get("custom_id", "")

    if not user or not password:
        return jsonify({"success": False, "error": "user and password are required"}), 400

    try:
        login_raw = fcc_client.login_user(user=user, password=password, id_value=idv, seqno_value=seqno)
        login_rc  = str((login_raw or {}).get("result"))
        if login_rc != "0":
            return jsonify({"success": False, "error": f"login failed (result={login_rc})", "raw": login_raw}), 502

        # Optionally open and return SessionID in one call
        if open_sess:
            if not device_name:
                return jsonify({"success": False, "error": "device_name required when open_session=true"}), 400
            open_raw = fcc_client.device_open(
                user=user, password=password, device_name=device_name,
                custom_id=custom_id, id_value=idv, seqno_value=seqno
            )
            open_rc = str((open_raw or {}).get("result"))
            if open_rc != "0":
                return jsonify({
                    "success": False, "error": f"open failed (result={open_rc})",
                    "login": {"result": login_rc, "raw": login_raw},
                    "open": {"result": open_rc, "raw": open_raw}
                }), 502

            return jsonify({
                "success": True,
                "result": "0",
                "session_id": (open_raw or {}).get("SessionID"),
                "login_raw": login_raw,
                "open_raw": open_raw
            }), 200

        # Plain login success (no session yet)
        return jsonify({"success": True, "result": "0", "raw": login_raw}), 200

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("login failed")
        return jsonify({"success": False, "error": f"upstream: {type(e).__name__}: {e}"}), 502

# 20. Device Open Request  
@fcc_bp.route("/api/v1/device/open", methods=["POST"])
def device_open():
    body = request.get_json(force=True) or {}

    # Accept explicit credentials or fall back to Config.*
    user        = body.get("user")        or getattr(Config, "FCC_USER", "")
    password    = body.get("password")    or getattr(Config, "FCC_PASSWORD", "")
    device_name = body.get("device_name") or getattr(Config, "FCC_DEVICE_NAME", "CI-10")
    custom_id   = body.get("custom_id", "")
    idv         = body.get("id", "")
    seqno       = body.get("seqno", "")

    # Guard: do NOT accept session_id here; OpenOperation does not take it.
    if body.get("session_id"):
        return jsonify({"error": "session_id is not used by OpenOperation; pass user/password/device_name instead"}), 400

    if not user or not password or not device_name:
        return jsonify({"error": "user, password, and device_name are required (or set in Config)"}), 400

    try:
        raw = fcc_client.device_open(
            user=user,
            password=password,
            device_name=device_name,
            custom_id=custom_id,
            id_value=idv,
            seqno_value=seqno,
        )
        result = (raw or {}).get("result")
        # SessionID is usually present on success
        session_id = (raw or {}).get("SessionID")

        return jsonify({
            "operation": "open",
            "status": "OK" if str(result) == "0" else "FAILED",
            "result_code": None if result is None else str(result),
            "session_id": session_id,
            "raw": raw,
        }), 200 if str(result) == "0" else 502
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("device open failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

# 21. Device Close Request
@fcc_bp.route("/api/v1/device/close", methods=["POST"])
def device_close():
    body = request.get_json(force=True) or {}
    sid   = body.get("session_id")
    idv   = body.get("id", "")
    seqno = body.get("seqno", "")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.device_close(session_id=str(sid), id_value=idv, seqno_value=seqno)
        result = (raw or {}).get("result")
        return jsonify({
            "operation": "close",
            "session_id": str(sid),
            "status": "OK" if str(result) == "0" else "FAILED",
            "result_code": None if result is None else str(result),
            "raw": raw,
        }), 200 if str(result) == "0" else 502
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("device close failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502
    
# 25 Manual Cashin Request
@fcc_bp.post("/api/v1/cashin/manual")
def cashin_manual_update_total():
    """
    Body:
    {
      "session_id": "1",
      "amount": 6150,
      "id": "",
      "seqno": "",
      "deposit_currency": [
        {"type": 3, "cc": "EUR", "fv": 2100, "piece": 1},
        {"type": 1, "cc": "EUR", "fv": 50,   "piece": 1},
        {"type": 1, "cc": "EUR", "fv": 100,  "piece": 10},
        {"type": 2, "cc": "EUR", "fv": 1000, "piece": 3}
      ],
      "foreign_amount": {"cc":"USD","amount":1234}  // optional
    }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        session_id = str(data.get("session_id", ""))
        amount = data.get("amount")
        id_value = str(data.get("id", ""))
        seqno = str(data.get("seqno", ""))
        deposit_currency = data.get("deposit_currency")
        foreign_amount = data.get("foreign_amount")

        if session_id == "" or amount is None:
            return jsonify({"status": "FAILED", "error": "session_id and amount are required"}), 400

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.manual_cashin_update_total(
            session_id=session_id,
            amount=amount,
            deposit_currency=deposit_currency,
            foreign_amount=foreign_amount,
            id_value=id_value,
            seqno_value=seqno
        )
        return jsonify({"status": "OK", "data": out})
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("cashin/manual failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502


# 29 Power control request: Shutdown or Reboot the FCC machine
@fcc_bp.post("/api/v1/power/control")
def power_control():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        action     = str(body.get("action", ""))   # "shutdown" | "reboot"
        id_value   = str(body.get("id", ""))
        seqno      = str(body.get("seqno", ""))

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.control_power(session_id=session_id, action=action, id_value=id_value, seqno_value=seqno)
        return jsonify(out), 200

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("power/control failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502
    
# 31 Unit Lock Request: Lock specified units
@fcc_bp.post("/api/v1/unit/lock")
def unit_lock():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        target     = body.get("target")   # "notes" | "coins" | "all"/"both" | None
        units      = body.get("units")    # optional, ignored by SOAP but accepted

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.lock_unit(session_id=session_id, target=target, units=units)
        return jsonify(out), 200
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("unit/lock failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502
    
# 32 Unit Unlock Request: Unlock specified units
@fcc_bp.post("/api/v1/unit/unlock")
def unit_unlock():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        target     = body.get("target")   # "notes" | "coins" | "all"/"both" | None
        units      = body.get("units")    # optional, ignored by SOAP but accepted

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.unlock_unit(session_id=session_id, target=target, units=units)
        return jsonify(out), 200
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("unit/unlock failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502
    
# 35 Open Exit Door Request
@fcc_bp.route("/api/v1/device/exit-cover/open", methods=["POST"])
def device_exit_cover_open():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.exit_cover_open(session_id=str(sid))
        return jsonify({
            "operation": "exit_cover_open",
            "session_id": str(sid),
            "status": "OK" if (raw or {}).get("result") in (0, "0") else "FAILED",
            "result_code": str((raw or {}).get("result")),
            "raw": raw
        })
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("exit-cover open failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

# 36 Close Exit Door Request
@fcc_bp.route("/api/v1/device/exit-cover/close", methods=["POST"])
def device_exit_cover_close():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.exit_cover_close(session_id=str(sid))
        return jsonify({
            "operation": "exit_cover_close",
            "session_id": str(sid),
            "status": "OK" if (raw or {}).get("result") in (0, "0") else "FAILED",
            "result_code": str((raw or {}).get("result")),
            "raw": raw
        })
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("exit-cover close failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

# 37 Replenish Entrance Start Request 
@fcc_bp.post("/api/v1/replenish/entrance/start")
def replenish_entrance_start():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        id_value   = str(body.get("id", ""))
        seqno      = str(body.get("seqno", ""))

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.start_replenish_entrance(session_id=session_id, id_value=id_value, seqno_value=seqno)
        return jsonify(out), 200
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("replenish/entrance/start failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502

# 38 Replenish Entrance End Request
@fcc_bp.post("/api/v1/replenish/entrance/end")
def replenish_entrance_end():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        id_value   = str(body.get("id", ""))
        seqno      = str(body.get("seqno", ""))

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.end_replenish_entrance(session_id=session_id, id_value=id_value, seqno_value=seqno)
        return jsonify(out), 200

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("replenish/entrance/end failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502

#39 Replenish Entrance Cancel Request
@fcc_bp.post("/api/v1/replenish/entrance/cancel")
def replenish_entrance_cancel():
    try:
        body = request.get_json(force=True) or {}
        session_id = str(body.get("session_id", ""))
        id_value   = str(body.get("id", ""))
        seqno      = str(body.get("seqno", ""))

        fcc = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        out = fcc.cancel_replenish_entrance(session_id=session_id, id_value=id_value, seqno_value=seqno)
        return jsonify(out), 200

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("replenish/entrance/cancel failed")
        return jsonify({"status": "FAILED", "error": f"{type(e).__name__}: {e}"}), 502


#----------------------------------------------------------------------------

# Inventory route   
# @fcc_bp.route("/api/v1/inventory", methods=["GET"])
# def get_inventory():
#     """
#     API endpoint to get the current cash inventory from the FCC machine.
#     Requires a valid session_id.
#     """
#     session_id = request.args.get("session_id")
#     if not session_id:
#         return jsonify({"error": "session_id query parameter is required"}), 400

#     logger.info(f"Received GET request for inventory with SID: {session_id}")
    
#     response = fcc_client.get_inventory(session_id)

#     if response and response.get("success"):
#         # Map the raw data to a clean, simple format
#         mapped_inventory = map_inventory_response(response.get("data"))
#         return jsonify(mapped_inventory), 200
#     else:
#         error_msg = response.get("error", "Unknown error fetching inventory.")
#         logger.error(f"Error fetching inventory: {error_msg}")
#         return jsonify({"error": error_msg}), 


@fcc_bp.route("/api/v1/device/counter-clear", methods=["POST"])
def device_counter_clear():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        raw = fcc_client.device_counter_clear(session_id=str(sid))
        result_code = str((raw or {}).get("result"))
        status = "OK" if result_code in ("0", 0) else "FAILED"
        http = 200 if status == "OK" else 502

        return jsonify({
            "operation": "counter_clear",
            "session_id": str(sid),
            "status": status,
            "result_code": result_code,
            "raw": raw,
        }), http

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("counter_clear failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502
    
@fcc_bp.post("/api/v1/verify/collection-container")
def verify_collection_container():
    body = request.get_json(force=True) or {}
    sid   = (body.get("session_id") or "").strip()
    devid = int(body.get("devid", 1))
    serial = body.get("serial")  # optional
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.verify_collection_container(session_id=sid, devid=devid, serial=serial, val=1)
        code = str((raw or {}).get("result"))
        return jsonify({"status": "OK" if code == "0" else "FAILED", "result_code": code, "raw": raw}), 200 if code == "0" else 409
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("verify collection container failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

# @fcc_bp.route("/api/v1/device/occupy", methods=["POST"])
# @fcc_bp.route("/api/v1/device/occupy", methods=["POST"])
# def device_occupy():
#     body = request.get_json(force=True) or {}
#     sid = (body.get("session_id") or "").strip()
#     if not sid:
#         return jsonify({"error": "session_id is required"}), 400
#     try:
#         raw = fcc_client.occupy(session_id=sid)
#         code = str((raw or {}).get("result"))
#         msg, http = RESULT_MAP.get(code, (f"Unknown result {code}", 502))
#         return jsonify({
#             "operation": "occupy",
#             "session_id": sid,
#             "status": "OK" if code == "0" else "FAILED",
#             "result_code": code,
#             "reason": msg,
#             "raw": raw,
#         }), http
#     except Exception as e:
#         logger.exception("device occupy failed")
#         return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502
@fcc_bp.route("/api/v1/device/verify/collection-container", methods=["POST"])
def device_verify_collection_container():
    body = request.get_json(force=True) or {}
    sid = (body.get("session_id") or "").strip()
    devid = int(body.get("devid", 1))  # 1=notes, 2=coins
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.verify_collection_container(session_id=sid, devid=devid)
        code = str((raw or {}).get("result"))
        return jsonify({
            "operation": "verify_collection_container",
            "session_id": sid,
            "devid": devid,
            "status": "OK" if code == "0" else "FAILED",
            "result_code": code,
            "raw": raw,
        }), 200 if code == "0" else 502
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("verify_collection_container failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502


@fcc_bp.route("/api/v1/device/release", methods=["POST"])
def device_release():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    try:
        raw = fcc_client.occupy(session_id=str(sid))
        code = str((raw or {}).get("result"))
        
        status_text = "FAILED"
        http_code = 502
        details = {}
        
        if code == "0":
            status_text = "OK"
            http_code = 200
        else:
            if code == "4":
                # Ask the machine what is blocking us
                st = fcc_client.get_status(session_id=str(sid), require_verification=True)
                rv = (st or {}).get("RequireVerifyInfos") or {}
                # summarize likely blockers
                blockers = []
        
                # Collection container verify
                cc_infos = ((rv.get("RequireVerifyCollectionContainerInfos") or {})
                            .get("RequireVerifyCollectionContainer") or [])
                for c in cc_infos:
                    if (c or {}).get("val") == 1:
                        blockers.append({
                            "type": "collection_container",
                            "devid": (c or {}).get("devid"),
                            "serial": (c or {}).get("SerialNo")
                        })
        
                # Denomination verify
                den_infos = ((rv.get("RequireVerifyDenominationInfos") or {})
                             .get("RequireVerifyDenomination") or [])
                for d in den_infos:
                    if (d or {}).get("val") == 1:
                        blockers.append({"type": "denomination", "devid": (d or {}).get("devid")})
        
                # Mix/stacker verify
                mix_infos = ((rv.get("RequireVerifyMixStackerInfos") or {})
                             .get("RequireVerifyMixStacker") or [])
                for m in mix_infos:
                    if (m or {}).get("val") == 1:
                        blockers.append({"type": "mix_stacker", "devid": (m or {}).get("devid")})
        
                details = {"blocked_by": blockers, "raw_status": st}
                status_text = "BLOCKED"
                http_code = 409  # Conflict
            # else keep FAILED 502 for other codes
        
        return jsonify({
            "operation": "occupy",
            "session_id": str(sid),
            "status": status_text,
            "result_code": code,
            "details": details if details else None,
            "raw": raw,
        }), http_code
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("device release failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

@fcc_bp.route("/api/v1/cash/limits", methods=["GET"])
def cash_limits():
    """
    Returns per-denomination min/max thresholds (and warning bands) to drive UI.
    Sources:
      - Machine capacity from InventoryOperation (CashUnits[].CashUnit[].max and denomination mapping)
      - Optional app-config overrides (FCC_LIMITS_OVERRIDES)
    Query:
      - session_id: required (string)
      - currency: optional (defaults to whatever inventory reports)
      - include_raw: optional bool (default false) -> include inventory raw in response
    Response:
      {
        "currency": "EUR",
        "notes": [ {cc,value,device,min,max,warn_low,warn_high,capacity}... ],
        "coins": [ ... ],
        "raw": { ... }   # only if include_raw=true
      }
    """
    from math import ceil

    sid = request.args.get("session_id")
    cur = (request.args.get("currency") or "").upper().strip() or None
    include_raw = str(request.args.get("include_raw", "false")).lower() in ("1","true","yes","y")

    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        inv = fcc_client.inventory(session_id=sid)
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("inventory fetch failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

    # Grab config
    defaults = current_app.config.get("FCC_LIMITS_DEFAULTS", {})
    warn_low_pct  = float(defaults.get("warn_low_pct", 0.10))
    warn_high_pct = float(defaults.get("warn_high_pct", 0.90))
    overrides = current_app.config.get("FCC_LIMITS_OVERRIDES", {})

    # Build capacity map: (currency, value, device) -> total_max_capacity
    # Inventory.raw.CashUnits is a list grouped by device: {devid, CashUnit: [...]}
    raw = inv.get("raw") or {}
    cash_units = raw.get("CashUnits") or []
    capacity = {}

    for dev_group in cash_units:
        devid = int(dev_group.get("devid", 0) or 0)
        for unit in dev_group.get("CashUnit", []) or []:
            max_cap = int(unit.get("max", 0) or 0)
            # Each unit may specify which denomination(s) it holds.
            denoms = unit.get("Denomination") or []
            # If device reports a single denom per unit (typical), use that.
            # If multiple, add capacity to each (machine-specific; safe sum).
            for d in (denoms if isinstance(denoms, list) else [denoms]):
                cc = d.get("cc") or inv.get("currency")  # fallback
                fv = d.get("fv")
                if cc is None or fv is None:
                    continue
                key = (str(cc), int(fv), int(devid))
                capacity[key] = capacity.get(key, 0) + max_cap

    # If caller passed currency, filter; otherwise infer from inv/capacity
    # Use inventory endpoint’s currency field if present
    inv_currency = inv.get("currency")
    if not cur:
        cur = inv_currency or next(iter({k[0] for k in capacity.keys()}), None)

    # Materialize denom list from capacity (only those with capacity>0 are useful for UI)
    limits_notes, limits_coins = [], []

    def add_limit(cc, fv, devid, cap):
        # Compute defaults
        # Min is often 0; you can also set non-zero minimum stock policy here if needed.
        min_default = 0
        max_default = cap
        warn_low_default = ceil(cap * warn_low_pct) if cap else 0
        warn_high_default = ceil(cap * warn_high_pct) if cap else 0

        # Apply overrides if present
        o = overrides.get((cc, fv, devid), {})
        item = {
            "cc": cc,
            "value": fv,
            "device": devid,       # 1=notes, 2=coins in your setup
            "capacity": cap,
            "min": int(o.get("min", min_default)),
            "max": int(o.get("max", max_default)),
            "warn_low": int(o.get("warn_low", warn_low_default)),
            "warn_high": int(o.get("warn_high", warn_high_default)),
        }
        if devid == 2:
            limits_coins.append(item)
        else:
            limits_notes.append(item)

    for (cc, fv, devid), cap in capacity.items():
        if cur and cc != cur:
            continue
        add_limit(cc, fv, devid, int(cap or 0))

    # Sort by value ascending for UI niceness
    limits_notes.sort(key=lambda x: x["value"])
    limits_coins.sort(key=lambda x: x["value"])

    out = {
        "currency": cur,
        "notes": limits_notes,
        "coins": limits_coins,
    }
    if include_raw:
        out["raw"] = raw

    return jsonify(out), 200
    
# def tmp_cashin_start():
#     body = request.get_json(force=True) or {}
#     user = body.get("user")
#     sid = body.get("session_id")

#     if not user:
#         return jsonify({"error": "user is required"}), 400

#     if not sid:
#         # Reuse your existing login helper through the client
#         login = fcc_client.login_user(user)
#         if not login.get("success"):
#             return jsonify({"error": f"login failed: {login.get('error')}"}), 502
#         sid = login.get("session_id") or login.get("data", {}).get("SessionID")

#     try:
#         resp = fcc_client.start_cashin(session_id=sid)
#         return jsonify({"session_id": sid, "result": resp}), 200
#     except Exception as e:
#         logger.exception("start_cashin failed")
#         return jsonify({"error": f"upstream: {e}"}), 502

@fcc_bp.route("/api/v1/cash-in/status", methods=["GET"])
def cashin_status():
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    try:
        resp = fcc_client.status_request(session_id=sid, with_cash=True, with_verify=True)
        return jsonify({
            "state": resp.get("state"),
            "counted": resp.get("counted"),   # {"by_fv": {"100":3,...}, "thb": 500}
        }), 200
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("status failed")
        return jsonify({"error": f"upstream: {e}"}), 502

@fcc_bp.route("/api/v1/cash-out/execute2", methods=["POST"])
def cashout_execute():
    body = request.get_json(force=True) or {}
    sid        = body.get("session_id")
    amount     = body.get("amount")  # only for validation/info
    currency   = (body.get("currency") or "THB").upper()

    # accept both styles
    payout_obj = body.get("payout") or {}
    notes_in = payout_obj.get("notes") if "payout" in body else body.get("notes")
    coins_in = payout_obj.get("coins") if "payout" in body else body.get("coins")
    notes = notes_in or []
    coins = coins_in or []

    # NEW: optional destinations
    note_dest = body.get("note_destination")
    coin_dest = body.get("coin_destination")

    # basic validation
    if not sid:
        return jsonify({"error": "session_id is required"}), 400
    if not (notes or coins):
        return jsonify({"error": "at least one of 'notes' or 'coins' must be provided"}), 400

    def _coerce(lst, kind):
        out = []
        for i, d in enumerate(lst):
            try:
                v = int(d["value"]); q = int(d["qty"])
            except Exception:
                return None, f"invalid {kind} at index {i}: need integer 'value' and 'qty'"
            if v <= 0 or q <= 0:
                return None, f"invalid {kind} at index {i}: value/qty must be positive"
            # allow optional explicit device
            rec = {"value": v, "qty": q}
            if "device" in d:
                dev = int(d["device"])
                if dev not in (1,2):
                    return None, f"invalid {kind} at index {i}: device must be 1 or 2"
                rec["device"] = dev
            out.append(rec)
        return out, None

    notes, err = _coerce(notes, "note")
    if err:
        return jsonify({"error": err}), 400
    coins, err = _coerce(coins, "coin")
    if err:
        return jsonify({"error": err}), 400

    intended_amount = sum(n["value"]*n["qty"] for n in notes) + sum(c["value"]*c["qty"] for c in coins)

    try:
        # build merged denom list for client
        denoms = notes + coins

        raw = fcc_client.cashout_execute(
            session_id=sid,
            currency=currency,
            denominations_list=denoms,
            note_destination=note_dest,
            coin_destination=coin_dest,
            # id/seq left empty to mirror your sample
            id_value="",
            seqno_value="",
        )

        safe = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw or {}
        cash = (safe or {}).get("Cash") or {}
        douts = cash.get("Denomination") or []

        out_notes, out_coins = [], []
        for d in douts:
            rec = {
                "cc": d.get("cc"),
                "value": int(d.get("fv", 0) or 0),
                "qty": int(d.get("Piece", 0) or 0),
                "device": int(d.get("devid", 0) or 0),
                "status": int(d.get("Status", 0) or 0),
            }
            (out_coins if rec["device"] == 2 else out_notes).append(rec)

        dispensed_amount = sum(x["value"]*x["qty"] for x in out_notes + out_coins)
        result_attr = (
            safe.get("result")
            or (safe.get("_attr", {}).get("result") if isinstance(safe.get("_attr"), dict) else None)
            or safe.get("@result")
        )
        # status = "OK" if str(result_attr) == "0" else "FAILED"
        # code = 200 if status == "OK" else 502
        ok_codes = {"0", "99"}
        ra = str(result_attr) if result_attr is not None else None

        if (ra in ok_codes) or dispensed_amount > 0:
            status, http_code = "OK", 200
        else:
            status, http_code = "FAILED", 502
        code = http_code

        return jsonify({
            "status": status,
            "result_code": str(result_attr) if result_attr is not None else None,
            "intended_amount": intended_amount,
            "dispensed": {
                "notes": out_notes,
                "coins": out_coins,
                "amount": dispensed_amount
            },
            "raw": raw
        }), code

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("cashout_execute failed")
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

    
@fcc_bp.route("/api/v1/cash/availability", methods=["GET"])
def cash_availability():
    """
    GET /fcc/api/v1/cash/availability?session_id=...&currency=...
    
    Returns available denominations for withdrawal.
    Currency: auto-detect from machine if not specified, fallback to FCC_CURRENCY config.
    """
    session_id = request.args.get("session_id")
    # Currency is optional - if not specified, auto-detect from machine
    currency_param = request.args.get("currency")
    if currency_param:
        currency_param = currency_param.upper()

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    try:
        inv = fcc_client.inventory(session_id=session_id) or {}
        cash_blocks = inv.get("Cash") or []

        # Normalize to a list (some responses use a single dict)
        if isinstance(cash_blocks, dict):
            cash_blocks = [cash_blocks]

        # We’ll merge type=3 (stock) and type=4 (dispensable) by fv/device
        # status semantics from your dumps: 0=NG, 1=Warn/Limited, 2=OK.
        best = {}
        detected_currency = None
        
        for block in cash_blocks:
            if (block or {}).get("type") not in (3, 4):
                continue
            denoms = block.get("Denomination") or []
            # normalize list
            if isinstance(denoms, dict):
                denoms = [denoms]
            for d in denoms:
                try:
                    cc   = (d.get("cc") or "").upper()
                    fv   = int(d.get("fv", 0) or 0)
                    dev  = int(d.get("devid", 0) or 0)  # 1=notes,2=coins
                    qty  = int(d.get("Piece", 0) or 0)
                    st   = int(d.get("Status", 0) or 0)
                except Exception:
                    continue
                
                # Auto-detect currency from first denomination found
                if cc and not detected_currency:
                    detected_currency = cc
                
                # Filter: only if currency_param explicitly specified
                if currency_param and cc != currency_param:
                    continue
                    
                key = (dev, fv)
                prev = best.get(key)
                # prefer block type=4 (dispensable) over type=3 if both exist
                rank = 2 if (block.get("type") == 4) else 1
                prev_rank = prev["rank"] if prev else -1
                if rank >= prev_rank:
                    best[key] = {"qty": qty, "status": st, "rank": rank}

        # Determine final currency: param > detected > config
        final_currency = currency_param or detected_currency or FCC_CURRENCY
        
        # Build output
        out = {
            "currency": final_currency,
            "notes": [],
            "coins": [],
        }
        for (dev, fv), meta in sorted(best.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            qty = meta["qty"]
            st  = meta["status"]
            available = (qty > 0) and (st in (1, 2))
            rec = {"value": fv, "qty": qty, "status": st, "available": available}
            (out["coins"] if dev == 2 else out["notes"]).append(rec)

        out["raw"] = {"result": inv.get("result"), "result_code": str(inv.get("result")) if inv.get("result") is not None else None}
        logger.info(f"cash/availability: currency={final_currency} (param={currency_param}, detected={detected_currency}), notes={len(out['notes'])}, coins={len(out['coins'])}")
        return jsonify(out), 200

    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("cash/availability failed")
        return jsonify({"error": f"upstream: {type(e).__name__}: {e}"}), 502

@fcc_bp.route("/api/v1//reports/logs", methods=["GET"])
def reports_logs():
    sid = request.args.get("session_id")
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    filters = {
        "from_ts": request.args.get("from"),
        "to_ts": request.args.get("to"),
        "types": request.args.get("types"),     # comma list
        "cursor": request.args.get("cursor"),
        "limit": request.args.get("limit", type=int),
    }
    try:
        data = fcc_client.log_read(session_id=sid, **filters)
        # TODO: transform raw logs to a normalized list and aggregates
        return jsonify({"session_id": sid, "raw": data}), 200
    
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("reports_logs failed")
        return jsonify({"error": f"upstream: {e}"}), 502


@fcc_bp.route("/api/v1/shift/close", methods=["POST"])
def shift_close():
    body = request.get_json(force=True, silent=True) or {}
    sid = str(body.get("session_id", "")).strip()
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    include_inventory = bool(body.get("include_inventory", True))
    frm = body.get("from")
    to  = body.get("to")
    shift_id = body.get("shift_id")

    try:
        inventory_end = None
        if include_inventory:
            inventory_end = fcc_client.inventory(session_id=sid)

        logs = fcc_client.log_read(session_id=sid, from_ts=frm, to_ts=to)
        # TODO aggregate log totals by type/denom

        return jsonify({
            "session_id": sid,
            "shift_id": shift_id,
            "window": {"from": frm, "to": to},
            "inventory_end": inventory_end,
            "logs": logs,
            # "totals": {...}  # after you implement aggregation
        }), 200
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("shift_close failed")
        return jsonify({"error": f"upstream: {e}"}), 502


@fcc_bp.route("/api/v1/day/close", methods=["POST"])
def day_close():
    body = request.get_json(force=True, silent=True) or {}
    sid = str(body.get("session_id", "")).strip()
    if not sid:
        return jsonify({"error": "session_id is required"}), 400

    biz_date = body.get("business_date")
    day_from = body.get("day_from")
    day_to   = body.get("day_to")
    collect  = body.get("collect", "full")          # "full" | "target_float" | "none"
    target_float = body.get("target_float")
    clear_counters = bool(body.get("clear_counters", True))

    try:
        inv_before = fcc_client.inventory(session_id=sid)

        logs = fcc_client.log_read(session_id=sid, from_ts=day_from, to_ts=day_to)
        # TODO aggregate totals

        collect_result = None
        if collect in ("full", "target_float"):
            collect_result = fcc_client.collect(session_id=sid, scope="all",
                                                plan=collect, target_float=target_float)

        inv_after = fcc_client.inventory(session_id=sid)

        cc_result = None
        if clear_counters:
            cc_result = fcc_client.counter_clear(session_id=sid, option_type=0)  # reuse your existing wrapper

        return jsonify({
            "session_id": sid,
            "business_date": biz_date,
            "window": {"from": day_from, "to": day_to},
            "inventory_before": inv_before,
            "logs": logs,
            "collect": collect_result,
            "inventory_after": inv_after,
            "counter_clear": cc_result,
            # "totals": {...}
        }), 200
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        logger.exception("day_close failed")
        return jsonify({"error": f"upstream: {e}"}), 502

@fcc_bp.route("/api/v1/device/unit/lock", methods=["POST"])
def device_unit_lock():
    payload = request.get_json(force=True, silent=True) or {}
    sid    = payload.get("session_id")
    target = payload.get("target")      # "notes" | "coins" | "all"/"both" | None(default all)
    units  = payload.get("units") or None  # ignored by SOAP, just logged

    try:
        data = fcc_client.lock_unit(
            session_id=sid, target=target, units=units
        )
        result_code = str(data.get("result"))
        return jsonify({
            "operation": "lock_unit",
            "session_id": str(sid) if sid is not None else None,
            "target": target or "all",
            "raw": data,
            "result_code": result_code,
            "status": "OK" if result_code == "0" else "FAILED"
        })
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"upstream: {e}"}), 502

@fcc_bp.route("/api/v1/device/unit/unlock", methods=["POST"])
def device_unit_unlock():
    payload = request.get_json(force=True, silent=True) or {}
    sid    = payload.get("session_id")
    target = payload.get("target")
    units  = payload.get("units") or None

    try:
        data = fcc_client.unlock_unit(
            session_id=sid, target=target, units=units
        )
        result_code = str(data.get("result"))
        return jsonify({
            "operation": "unlock_unit",
            "session_id": str(sid) if sid is not None else None,
            "target": target or "all",
            "raw": data,
            "result_code": result_code,
            "status": "OK" if result_code == "0" else "FAILED"
        })
        
    except RuntimeError as e:
        return jsonify({"status": "FAILED", "error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"upstream: {e}"}), 502

########################## OLD ROUTES ##########################
# @fcc_bp.route('/login', methods=['POST'])
# def login_user():
#     """
#     API endpoint to log in a user with the FCC SOAP service.
#     Expects a JSON body with 'user' and 'password'.
#     """
#     data = request.get_json()
#     if not data or 'user' not in data:
#         return jsonify({"error": "Missing user or password in request body"}), 400

#     user = data['user']

#     # Call the SOAP client's login method
#     response = fcc_client.login_user(user=user)

#     if response["success"]:
#         # Map the raw SOAP response to a cleaner JSON format
#         mapped_data = map_fcc_login_response(response["data"])
#         return jsonify({"success": True, "data": mapped_data}), 200
#     else:
#         return jsonify({"success": False, "error": response["error"]}), 500

@fcc_bp.route('/status', methods=['GET'])
def get_fcc_status_route():
    """
    API endpoint to get the current operational status of the FCC machine.
    Returns JSON data representing the FCC's status, mapped to a cleaner format.
    """
    logger.info("Received GET request for FCC status.")
    response = fcc_client.get_status() # Call the SOAP client's method

    if response and response.get("success"):
        raw_data = response.get("data")
        # Use the mapping function from fcc_api.py
        mapped_status = map_fcc_status_response(raw_data)
        return jsonify(mapped_status), 200
    else:
        # Provide a more generic error if internal error occurred
        error_msg = response.get("error", "Unknown error fetching FCC status.") if response else "FCC SOAP client not initialized."
        logger.error(f"Error fetching FCC status: {error_msg}")
        return jsonify({"error": error_msg}), 500

@fcc_bp.route('/register_event', methods=['POST'])
def register_event_route():
    """
    API endpoint to register for events on the FCC machine.
    """
    logger.info("Received POST request to register events.")
    
    # Call the SOAP client's get_register_event method
    response = fcc_client.get_register_event()

    if response and response.get("success"):
        raw_data = response.get("data")
        # Use the mapping function from fcc_api.py
        mapped_event_result = map_register_event_response(raw_data)
        return jsonify(mapped_event_result), 200
    else:
        error_msg = response.get("error", "Unknown error registering events.") if response else "FCC SOAP client not initialized."
        logger.error(f"Error registering events: {error_msg}")
        return jsonify({"error": error_msg}), 500
    
@fcc_bp.route('/cashin/open', methods=['POST'])
def open_cash_in_route():
    """
    API endpoint to initiate an 'OpenCashIn' operation on the FCC machine.
    """
    data = request.get_json() # Get JSON data from the request body
    if not data:
        return jsonify({"error": "Request body must be JSON."}), 400

    # Extract required parameters from the JSON payload
    amount = data.get('amount')
    currency_code = data.get('currency_code')
    account_id = data.get('account_id')

    # Validate that all required parameters are present
    if not all([amount, currency_code, account_id]):
        return jsonify({"error": "Missing 'amount', 'currency_code', or 'account_id' in request"}), 400

    logger.info(f"Received POST request to open cash-in for {amount} {currency_code} for account {account_id}.")

    # Call the SOAP client's open_cash_in method
    response = fcc_client.open_cash_in(amount=str(amount), currency_code=str(currency_code), account_id=str(account_id))

    if response and response.get("success"):
        raw_data = response.get("data")
        # Use the new mapping function from fcc_api.py
        mapped_cash_in_result = map_cash_in_response(raw_data)
        return jsonify(mapped_cash_in_result), 200
    else:
        error_msg = response.get("error", "Unknown error initiating cash-in.")
        logger.error(f"Error initiating cash-in: {error_msg}")
        return jsonify({"error": error_msg}), 500

@fcc_bp.route('/exchange/start', methods=['POST'])
def start_exchange():
    data = request.get_json()
    erp_role = data.get("erp_role")   # cashier, manager, etc.
    amount = data.get("amount")

    session_id = session_manager.get_session_for_role(erp_role)
    if not session_id:
        return jsonify({"error": "Failed to get Glory session"}), 500

    response = fcc_client.start_exchange(session_id=session_id, amount=amount)

    return jsonify(response), 200



# Helper function to convert Zeep objects to a Python dictionary
# def zeep_to_dict(zeep_obj):
#     """
#     Recursively converts a Zeep object to a Python dictionary.
#     """
#     result = {}
#     if zeep_obj is None:
#         return None
#     for key, value in zeep_obj:
#         if isinstance(value, CompoundValue):
#             result[key] = zeep_to_dict(value)
#         elif isinstance(value, list):
#             result[key] = [zeep_to_dict(item) if isinstance(item, CompoundValue) else item for item in value]
#         else:
#             result[key] = value
#     return result

# @fcc_bp.route('/change_operation', methods=['POST'])
# def change_operation():
#     """
#     Handles the change operation request.
#     """
#     try:
#         data = request.get_json()
#         amount = data.get('amount')
#         denominations = data.get('denominations')

#         # Call the SOAP client's change_operation method
#         soap_response = fcc_client.change_operation(amount, denominations)
        
#         # Convert the entire SOAP response object to a dictionary
#         response_dict = zeep_to_dict(soap_response)

#         # Correctly check for the success and status code
#         is_successful = response_dict.get('result') == 10
#         status_code = response_dict.get('Status', {}).get('Code')

#         # Find the Cash object with denominations (it's the first element)
#         dispensed_cash = next((cash for cash in response_dict.get('Cash', []) if cash.get('type') == 1), None)
        
#         dispensed_denominations = []
#         if dispensed_cash:
#             dispensed_denominations = dispensed_cash.get('Denomination', [])

#         # Build the final response payload
#         response_payload = {
#             "success": is_successful,
#             "details": f"Status Code: {status_code}",
#             "data": {
#                 "Change": {
#                     "Amount": response_dict.get('Amount'),
#                     "Cash": {
#                         "Denomination": dispensed_denominations
#                     }
#                 }
#             }
#         }
        
#         # Flask's jsonify can now handle this standard dictionary
#         return jsonify(response_payload), 200

#     except Exception as e:
#         print(f"Error in change_operation: {e}")
#         return jsonify({
#             "success": False,
#             "details": str(e)
#         }), 500