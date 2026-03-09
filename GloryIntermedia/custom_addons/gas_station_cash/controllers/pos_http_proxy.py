import logging
import requests
import configparser

from odoo import http
from odoo.http import request
from odoo.tools import config as odoo_config

_logger = logging.getLogger(__name__)

def _read_pos_conf():
    """
    Read POS settings from odoo.conf section [pos_http_config]
    Example:
        [pos_http_config]
        pos_vendor = firstpro
        pos_host = 192.168.0.207
        pos_port = 1249
        pos_timeout = 5.0
    """
    # Find odoo.conf path
    conf_path = getattr(odoo_config, "rcfile", None)
    if not conf_path:
        _logger.warning("[POS_HTTP] No odoo.conf path found")
        return {}

    parser = configparser.ConfigParser()
    parser.read(conf_path)

    if not parser.has_section("pos_http_config"):
        _logger.warning("[POS_HTTP] Section [pos_http_config] not found in odoo.conf")
        return {}

    section = parser["pos_http_config"]

    # Read settings with defaults
    pos_vendor = section.get("pos_vendor", "local").strip().lower()
    pos_host = section.get("pos_host", "127.0.0.1").strip()
    pos_port = section.get("pos_port", "9001").strip()
    pos_timeout = section.get("pos_timeout", "5.0").strip()

    _logger.info("[POS_HTTP] Config loaded: vendor=%s, host=%s, port=%s, timeout=%s", 
                 pos_vendor, pos_host, pos_port, pos_timeout)

    # Normalize values
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

    # FlowCo multi-POS map
    # Format: flowco_pos_hosts = 1:192.168.1.10:8080,2:192.168.1.11:8080
    # Single POS: flowco_pos_hosts = 1:127.0.0.1:9003
    flowco_pos_map = {}
    raw_hosts = section.get("flowco_pos_hosts", "").strip()
    if raw_hosts:
        for entry in raw_hosts.split(","):
            parts = entry.strip().split(":")
            if len(parts) == 3:
                try:
                    flowco_pos_map[int(parts[0])] = (parts[1].strip(), int(parts[2]))
                except (ValueError, IndexError):
                    _logger.warning("[POS_HTTP] Invalid flowco_pos_hosts entry: %s", entry)

    return {
        "pos_vendor":     pos_vendor,
        "pos_host":       pos_host,
        "pos_port":       pos_port,
        "pos_timeout":    pos_timeout,
        "flowco_pos_map": flowco_pos_map,
    }

class PosHttpProxy(http.Controller):

    @http.route("/gas_station_cash/pos/deposit_http", type="json", auth="user", methods=["POST"], csrf=False)
    def pos_deposit_http(self, **payload):
        """
        HTTP-only deposit proxy. No TCP used anywhere.

        JS must send:
          transaction_id       : str
          employee_external_id : str   (staff.external_id in Odoo)
          amount               : float
          deposit_type         : 'oil' | 'engine_oil'
            oil        -> FlowCo type_id = 'F'  (Fuel)
            engine_oil -> FlowCo type_id = 'L'  (Lube)

        Routing:
          pos_vendor = firstpro -> POST /deposit
          pos_vendor = flowco   -> POST /POS/Deposit  (lookup tag_id + pos_id from DB)
        """
        conf        = _read_pos_conf()
        pos_timeout = conf.get("pos_timeout", 5.0)
        # Read vendor from Odoo UI settings (gas_station_cash.pos_vendor)
        pos_vendor  = request.env['ir.config_parameter'].sudo().get_param(
            'gas_station_cash.pos_vendor', 'firstpro'
        )

        transaction_id       = payload.get("transaction_id", "")
        employee_external_id = payload.get("employee_external_id") or payload.get("staff_id", "")
        amount               = payload.get("amount", 0)
        deposit_type         = payload.get("deposit_type", "oil")

        # ── FirstPro ──────────────────────────────────────────────────────────
        if pos_vendor == "firstpro":
            pos_host = conf.get("pos_host", "127.0.0.1")
            pos_port = conf.get("pos_port", 9001)
            url = f"http://{pos_host}:{pos_port}/deposit"
            fp_payload = {
                "transaction_id": transaction_id,
                "staff_id":       employee_external_id,
                "amount":         amount,
            }
            _logger.info("[FirstPro] -> %s  payload=%s", url, fp_payload)
            try:
                r = requests.post(url, json=fp_payload, timeout=pos_timeout)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                _logger.exception("[FirstPro] HTTP request failed")
                return {"status": "FAILED", "description": str(e)}
            _logger.info("[FirstPro] <- %s", data)
            return data

        # ── FlowCo ────────────────────────────────────────────────────────────
        if pos_vendor == "flowco":
            # Lookup staff by external_id -> tag_id (RFID) + pos_id
            staff  = request.env["gas.station.staff"].sudo().search(
                [("external_id", "=", str(employee_external_id))], limit=1
            )
            tag_id = (staff.tag_id if staff else None) or employee_external_id or "UNKNOWN"
            pos_id = int(staff.pos_id) if (staff and staff.pos_id) else 1

            # Resolve host:port from flowco_pos_map
            # Single-POS fallback: use pos_host/pos_port when flowco_pos_hosts not set
            pos_map = conf.get("flowco_pos_map", {})
            if pos_map:
                if pos_id not in pos_map:
                    _logger.warning("[FlowCo] pos_id=%s not in map, using first", pos_id)
                    pos_id = next(iter(pos_map))
                pos_host, pos_port = pos_map[pos_id]
            else:
                pos_host = conf.get("pos_host", "127.0.0.1")
                pos_port = conf.get("pos_port", 9001)

            # deposit_type -> FlowCo type_id: oil=F (Fuel), engine_oil=L (Lube)
            type_id = "F" if deposit_type == "oil" else "L"

            url = f"http://{pos_host}:{pos_port}/POS/Deposit"
            fc_payload = {
                "transaction_id": transaction_id,
                "staff_id":       tag_id,    # RFID Tag ID
                "amount":         amount,
                "type_id":        type_id,   # F=Fuel, L=Lube
                "pos_id":         pos_id,
            }
            _logger.info("[FlowCo] -> %s", url)
            _logger.info("[FlowCo]    payload: %s", fc_payload)
            try:
                r = requests.post(url, json=fc_payload, timeout=pos_timeout)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                _logger.exception("[FlowCo] HTTP request failed")
                return {"status": "FAILED", "description": str(e)}
            _logger.info("[FlowCo] <- %s", data)
            return data

        return {"status": "FAILED", "description": f"Unknown pos_vendor: {pos_vendor}"}