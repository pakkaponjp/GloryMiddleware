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

    return {
        "pos_vendor": pos_vendor,
        "pos_host": pos_host,
        "pos_port": pos_port,
        "pos_timeout": pos_timeout,
    }

class PosHttpProxy(http.Controller):

    @http.route("/gas_station_cash/pos/deposit_http", type="json", auth="user", methods=["POST"], csrf=False)
    def pos_deposit_http(self, **payload):
        """
        Forward deposit request to Flask POS receiver: POST /Deposit
        Expected payload:
          {transaction_id, staff_id, amount}
        """
        ICP = request.env["ir.config_parameter"].sudo()
        # TODO: Remove hardcoded URL
        #base_url = (ICP.get_param("gas_station_cash.pos_http_base_url") or "http://58.8.186.194:8060").rstrip("/")
        base_url_override = (ICP.get_param("gas_station_cash.pos_http_base_url") or "").strip()
        
        conf = _read_pos_conf()
        pos_vendor = conf.get("pos_vendor", "local")
        pos_host = conf.get("pos_host", "127.0.0.1")
        pos_port = conf.get("pos_port", 9001)
        pos_timeout = conf.get("pos_timeout", 3.0)
        
        if base_url_override:
            base_url = base_url_override.rstrip("/")
        else:
            base_url = f"http://{pos_host}:{pos_port}"
            
        vendor_paths = {
            "local": "/deposit",
            "firstpro": "/deposit",
            "flowco": "/POS/Deposit",
        }
        path = vendor_paths.get(pos_vendor, "/deposit")

        url = f"{base_url}{path}"

        _logger.info("[POS_HTTP] -> %s payload=%s", url, payload)

        try:
            r = requests.post(url, json=payload, timeout=pos_timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _logger.exception("[POS_HTTP] error calling POS receiver")
            return {"status": "FAILED", "description": str(e), "echo": payload}

        _logger.info("[POS_HTTP] <- %s", data)
        return data