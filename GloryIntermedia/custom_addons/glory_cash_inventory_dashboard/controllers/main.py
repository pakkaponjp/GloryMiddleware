# -*- coding: utf-8 -*-

import logging
import os
import configparser
import requests
from datetime import datetime
from odoo import http, tools
from odoo.http import request

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# THB canonical denomination lists  (output is ALWAYS in these slots)
#   unit: satang  (1 THB = 100 satang)
# ---------------------------------------------------------------------------
THB_NOTE_SLOTS = [100000, 50000, 10000, 5000, 2000]   # ฿1000 ฿500 ฿100 ฿50 ฿20
THB_COIN_SLOTS = [1000, 500, 200, 100, 50, 25]         # ฿10   ฿5   ฿2   ฿1  ฿0.50 ฿0.25

# ---------------------------------------------------------------------------
# EUR emulator → THB denomination mapping
#
# The Glory Bridge API returns value as face_value × 100 (same scale as satang):
#   €500 note → value: 50000   €2 coin → value: 200
#   €200 note → value: 20000   €1 coin → value: 100
#   €100 note → value: 10000   €0.50 coin → value: 50
#   €50  note → value: 5000
#   €20  note → value: 2000
#
# We map EUR Bridge-API value → THB satang (cassette position mapping).
# THB denominations with no EUR counterpart receive qty = 0 in output.
# EUR values with no THB equivalent are intentionally omitted.
# ---------------------------------------------------------------------------
EUR_NOTE_TO_THB: dict[int, int] = {
    50000: 50000,  # €500 note (value=50000) → ฿500  (50,000 satang)  identity
    20000: 10000,  # €200 note (value=20000) → ฿100
    10000:  5000,  # €100 note (value=10000) → ฿50
     5000:  2000,  # €50  note (value=5000)  → ฿20
    # €20 (2000), €10 (1000), €5 (500) → no THB note counterpart; qty=0 in output
}
EUR_COIN_TO_THB: dict[int, int] = {
    200: 200,  # €2   coin (value=200) → ฿2    (200 satang)  identity
    100: 100,  # €1   coin (value=100) → ฿1
     50:  50,  # €0.50 coin (value=50) → ฿0.50
    # €0.20 (20), €0.10 (10), €0.05 (5) → no THB coin counterpart; omit
}


def _filter_valid_items(items: list) -> list:
    """
    Strip entries that should never appear in cassette inventory:
      - value == 0  (malformed / Rej entries from Bridge API)
    Note: Bridge API /cash/cassette pre-filters by device type so no 'rev'
    field is present in the response — filtering by value==0 is sufficient.
    """
    return [i for i in items if int(i.get("value", 0)) != 0]


# ---------------------------------------------------------------------------
# Denomination normalisation
# ---------------------------------------------------------------------------

def _build_thb_inventory(raw_notes: list, raw_coins: list, currency: str) -> tuple[list, list]:
    """
    Always return (notes, coins) using THB denomination slots.

    - currency == "THB" : filter to known THB slots; unknown values are dropped.
    - currency == "EUR" : remap via EUR_NOTE_TO_THB / EUR_COIN_TO_THB (face value
                          mapping, notes and coins are kept separate);
                          slots with no EUR counterpart appear with qty = 0.
    - other             : passthrough (unknown emulator — log warning).

    Rej / zero-value items are stripped before processing.
    """
    # Always strip Rej and zero-value items first
    raw_notes = _filter_valid_items(raw_notes)
    raw_coins = _filter_valid_items(raw_coins)

    if currency == "THB":
        note_lookup = {int(i.get("value", 0)): i for i in raw_notes}
        coin_lookup = {int(i.get("value", 0)): i for i in raw_coins}

        notes = [note_lookup[v] for v in THB_NOTE_SLOTS if v in note_lookup]
        coins = [coin_lookup[v] for v in THB_COIN_SLOTS if v in coin_lookup]
        return notes, coins

    if currency == "EUR":
        note_lookup = {int(i.get("value", 0)): i for i in raw_notes}
        coin_lookup = {int(i.get("value", 0)): i for i in raw_coins}

        # Reverse maps: THB satang → EUR face value
        thb_to_eur_note = {v: k for k, v in EUR_NOTE_TO_THB.items()}
        thb_to_eur_coin = {v: k for k, v in EUR_COIN_TO_THB.items()}

        def _remap(slots: list, eur_lookup: dict, thb_to_eur: dict) -> list:
            result = []
            for thb_val in slots:
                eur_val  = thb_to_eur.get(thb_val)
                src_item = eur_lookup.get(eur_val, {}) if eur_val else {}
                result.append({
                    **src_item,
                    "value": thb_val,               # always output in THB satang
                    "qty":   src_item.get("qty", 0),
                })
            return result

        notes = _remap(THB_NOTE_SLOTS, note_lookup, thb_to_eur_note)
        coins = _remap(THB_COIN_SLOTS, coin_lookup, thb_to_eur_coin)
        return notes, coins

    # Unknown currency — strip Rej only, pass through as-is
    _logger.warning("_build_thb_inventory: unknown currency '%s', passing through raw data", currency)
    return raw_notes, raw_coins


# ---------------------------------------------------------------------------
# odoo.conf helpers
# Reads from [fcc_config] — same section used by fcc_proxy.py.
# ---------------------------------------------------------------------------

def _find_odoo_conf() -> str | None:
    """Probe common odoo.conf locations and return the first that exists."""
    candidates = [
        tools.config.get("config_file"),
        "/etc/odoo/odoo.conf",
        "/etc/odoo.conf",
        os.path.expanduser("~/odoo.conf"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _read_fcc_config() -> dict:
    """
    Parse [fcc_config] section from odoo.conf.

    odoo.conf (existing — no changes needed):
        [fcc_config]
        fcc_host     = 127.0.0.1
        fcc_port     = 5000
        fcc_currency = EUR          ; EUR for emulator, THB for production machine
    """
    try:
        config_path = _find_odoo_conf()
        if not config_path:
            _logger.warning("_read_fcc_config: odoo.conf not found — using defaults")
            return {}

        parser = configparser.ConfigParser()
        parser.read(config_path)

        if "fcc_config" not in parser:
            _logger.warning("_read_fcc_config: [fcc_config] section missing — using defaults")
            return {}

        cfg = dict(parser["fcc_config"])
        _logger.debug("_read_fcc_config: loaded %s keys from %s", len(cfg), config_path)
        return cfg
    except Exception as exc:
        _logger.warning("_read_fcc_config error: %s — using defaults", exc)
        return {}


# Module-level cache — parsed once per worker lifetime
_fcc_cfg: dict | None = None


def _get_fcc_cfg() -> dict:
    global _fcc_cfg
    if _fcc_cfg is None:
        _fcc_cfg = _read_fcc_config()
    return _fcc_cfg


def _bridge_api_url() -> str:
    """Build Bridge API base URL from fcc_host + fcc_port in [fcc_config]."""
    cfg  = _get_fcc_cfg()
    host = cfg.get("fcc_host", "127.0.0.1").strip()
    port = cfg.get("fcc_port", "5000").strip()
    return f"http://{host}:{port}"


def _session_id() -> str:
    """Session ID is always 1 — middleware uses a single fixed session."""
    return "1"


def _configured_currency() -> str:
    """Read fcc_currency from [fcc_config]. Defaults to THB for production safety."""
    return _get_fcc_cfg().get("fcc_currency", "THB").strip().upper()



class InventoryDashboardController(http.Controller):

    def _call_bridge_api(self, endpoint, method="GET", data=None):
        """Call Bridge API and return response. Base URL is read from odoo.conf."""
        try:
            url = f"{_bridge_api_url()}{endpoint}"
            _logger.info("Calling Bridge API: %s %s", method, url)
            if method == "GET":
                response = requests.get(url, params=data, timeout=30)
            else:
                response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            _logger.error("Bridge API error: %s", e)
            return None

    # ------------------------------------------------------------------
    # Cassette inventory  — currency-aware denomination filtering
    # ------------------------------------------------------------------

    @http.route("/api/glory/get_cassette_inventory", type="json", auth="public", methods=["POST"], csrf=False)
    def get_cassette_inventory(self, **kwargs):
        """
        Fetch cassette inventory from Bridge API and normalise denominations
        to THB slots regardless of the machine's configured currency.

        - THB (production) : values already in satang → filter to known slots.
        - EUR (emulator)   : remap eurocent → satang via EUR_TO_THB_MAP;
                             THB slots with no EUR counterpart appear with qty=0.

        The frontend always receives the same stable structure:
          notes: [ {value: 100000, qty: N}, ... ]   (THB_NOTE_SLOTS order)
          coins: [ {value:   1000, qty: N}, ... ]   (THB_COIN_SLOTS order)
        """
        try:
            currency = _configured_currency()

            response = (
                self._call_bridge_api(
                    "/fcc/api/v1/cash/cassette",
                    method="GET",
                    data={"session_id": _session_id()},
                )
                or {}
            )

            cassette   = response.get("data", response)
            raw_notes  = cassette.get("notes", [])
            raw_coins  = cassette.get("coins", [])
            totals     = cassette.get("totals", {})

            notes, coins = _build_thb_inventory(raw_notes, raw_coins, currency)

            _logger.info(
                "get_cassette_inventory: currency=%s source_notes=%d source_coins=%d "
                "out_notes=%d out_coins=%d",
                currency, len(raw_notes), len(raw_coins), len(notes), len(coins),
            )

            return {
                "type": "response",
                "name": "cassette_inventory",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success":  True,
                    "currency": currency,
                    "cassette": {
                        "notes":  notes,
                        "coins":  coins,
                        "totals": totals,
                    },
                },
            }

        except Exception as e:
            _logger.error("get_cassette_inventory error: %s", e)
            return {
                "type": "response",
                "name": "cassette_inventory",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": False,
                    "cassette": {"notes": [], "coins": [], "totals": {}},
                },
            }

    # ------------------------------------------------------------------
    # Expose configured currency to the frontend
    # ------------------------------------------------------------------

    @http.route("/api/glory/get_currency", type="json", auth="public", methods=["POST"], csrf=False)
    def get_currency(self, **kwargs):
        """Return the configured currency from odoo.conf for frontend label formatting."""
        try:
            currency = _configured_currency()
            return {
                "type": "response",
                "name": "currency",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": True, "currency": currency},
            }
        except Exception as e:
            _logger.error("get_currency error: %s", e)
            return {
                "type": "response",
                "name": "currency",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "currency": "THB"},
            }

    # ------------------------------------------------------------------
    # Remaining endpoints (unchanged)
    # ------------------------------------------------------------------

    @http.route("/api/glory/get_cassette_capacities", type="json", auth="public", methods=["POST"], csrf=False)
    def get_cassette_capacities(self, **kwargs):
        """Return note/coin cassette max capacities from odoo.conf."""
        try:
            from odoo.tools import config as odoo_config
            note_cap = int(odoo_config.get("glory_cassette_note_capacity", 500) or 500)
            coin_cap = int(odoo_config.get("glory_cassette_coin_capacity", 1200) or 1200)
            return {
                "type": "response",
                "name": "cassette_capacities",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": True,
                    "cassette_note_capacity": note_cap,
                    "cassette_coin_capacity": coin_cap,
                },
            }
        except Exception as e:
            _logger.error("get_cassette_capacities error: %s", e)
            return {
                "type": "response",
                "name": "cassette_capacities",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "cassette_note_capacity": 500, "cassette_coin_capacity": 1200},
            }

    @http.route("/api/glory/get_change_allowed_notes", type="json", auth="public", methods=["POST"], csrf=False)
    def get_change_allowed_notes(self, **kwargs):
        """Get allowed note values for change calculation."""
        try:
            env_value = os.getenv("GLORY_CHANGE_ALLOWED_NOTES", "").strip()
            if env_value:
                values_list = [int(float(v.strip())) for v in env_value.split(",") if v.strip()]
                if values_list:
                    return {
                        "type": "response", "name": "change_allowed_notes",
                        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "data": {"success": True, "allowedNotes": sorted(values_list)},
                    }

            try:
                config_param = request.env["ir.config_parameter"].sudo().get_param("glory.change_allowed_notes", "")
                if config_param:
                    values_list = [int(float(v.strip())) for v in config_param.split(",") if v.strip()]
                    if values_list:
                        return {
                            "type": "response", "name": "change_allowed_notes",
                            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "data": {"success": True, "allowedNotes": sorted(values_list)},
                        }
            except Exception as ex:
                _logger.debug("Could not read config parameter: %s", ex)

            return {
                "type": "response", "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": True, "allowedNotes": [100, 500, 1000, 2000, 5000]},
            }
        except Exception as e:
            _logger.error("get_change_allowed_notes error: %s", e)
            return {
                "type": "response", "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "message": str(e), "allowedNotes": [100, 500, 1000, 2000, 5000]},
            }

    @http.route("/api/glory/get_branch_type", type="json", auth="public", methods=["POST"], csrf=False)
    def get_branch_type(self, **kwargs):
        """Get the configured branch type (convenience_store or gas_station)."""
        try:
            branch_type = request.env["ir.config_parameter"].sudo().get_param(
                "glory.branch_type", "convenience_store"
            )
            return {"success": True, "data": {"branch_type": branch_type}}
        except Exception as e:
            _logger.error("get_branch_type error: %s", e)
            return {"success": True, "data": {"branch_type": "convenience_store"}}

    @http.route("/api/glory/set_branch_type", type="json", auth="user", methods=["POST"], csrf=False)
    def set_branch_type(self, **kwargs):
        """Save the branch type setting."""
        try:
            branch_type = kwargs.get("branch_type", "convenience_store")
            if branch_type not in ("convenience_store", "gas_station"):
                return {"success": False, "message": "Invalid branch type"}
            request.env["ir.config_parameter"].sudo().set_param("glory.branch_type", branch_type)
            return {"success": True, "data": {"branch_type": branch_type}}
        except Exception as e:
            _logger.error("set_branch_type error: %s", e)
            return {"success": False, "message": str(e)}

    @http.route("/api/glory/check_float", type="json", auth="public", methods=["POST"], csrf=False)
    def check_float(self, **kwargs):
        """
        Check current inventory (simplified — no shift/transaction creation).
        Request:
            { "type": "command", "name": "check_float",
              "transactionId": "CHK-POS1-104", "timestamp": "...", "data": {} }
        """
        try:
            request_data = kwargs
            if "params" in kwargs:
                request_data = kwargs["params"]
            elif len(kwargs) == 1:
                request_data = list(kwargs.values())[0]
            transaction_id = request_data.get("transactionId", "")

            inventory_response = self._call_bridge_api(
                "/fcc/api/v1/cash/inventory", method="GET",
                data={"session_id": _session_id()},
            )
            availability_response = self._call_bridge_api(
                "/fcc/api/v1/cash/availability", method="GET",
                data={"session_id": _session_id()},
            )

            return {
                "type": "response", "name": "float_balance_report",
                "transactionId": transaction_id,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": True,
                    "message": "Current inventory retrieved.",
                    "bridgeApiInventory": inventory_response,
                    "bridgeApiAvailability": availability_response,
                },
            }
        except Exception as e:
            _logger.error("check_float error: %s", e)
            transaction_id = ""
            try:
                rd = kwargs
                if "params" in kwargs:
                    rd = kwargs["params"]
                elif len(kwargs) == 1:
                    rd = list(kwargs.values())[0]
                transaction_id = rd.get("transactionId", "")
            except Exception:
                pass
            return {
                "type": "response", "name": "float_balance_report",
                "transactionId": transaction_id,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "message": f"Error checking inventory: {e}"},
            }

    @http.route("/api/glory/get_warning_levels", type="json", auth="public", methods=["POST"], csrf=False)
    def get_warning_levels(self, **kwargs):
        """
        Return wm_low / wm_high watermark thresholds from ir.config_parameter.
        Shape: { "data": { "warningLevels": [ { "valueSatang": 100000, ... } ] } }
        """
        DENOM_MAP = [
            (100000, "note_1000"),
            ( 50000, "note_500"),
            ( 10000, "note_100"),
            (  5000, "note_50"),
            (  2000, "note_20"),
            (  1000, "coin_10"),
            (   500, "coin_5"),
            (   200, "coin_2"),
            (   100, "coin_1"),
            (    50, "coin_050"),
            (    25, "coin_025"),
        ]
        try:
            ICP = request.env["ir.config_parameter"].sudo()
            levels = []
            for satang, key in DENOM_MAP:
                low  = int(ICP.get_param(f"gas_station_cash.wm_low_{key}",  0) or 0)
                high = int(ICP.get_param(f"gas_station_cash.wm_high_{key}", 0) or 0)
                levels.append({
                    "valueSatang":     satang,
                    "wmLow":           low,
                    "wmHigh":          high,
                    "warningQuantity": low,
                    "warningEnabled":  low > 0 or high > 0,
                })
            return {
                "type": "response", "name": "warning_levels",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": True, "warningLevels": levels},
            }
        except Exception as e:
            _logger.error("get_warning_levels error: %s", e)
            return {
                "type": "response", "name": "warning_levels",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "warningLevels": []},
            }

    @http.route("/api/glory/check_inventory_warnings", type="json", auth="public", methods=["POST"], csrf=False)
    def check_inventory_warnings(self, **kwargs):
        """
        Compare current inventory (Bridge API) against wm_low / wm_high thresholds.
        Returns warning objects for the dashboard notification system.
        """
        DENOM_MAP = [
            (100000, "note_1000", "฿1,000"),
            ( 50000, "note_500",  "฿500"),
            ( 10000, "note_100",  "฿100"),
            (  5000, "note_50",   "฿50"),
            (  2000, "note_20",   "฿20"),
            (  1000, "coin_10",   "฿10"),
            (   500, "coin_5",    "฿5"),
            (   200, "coin_2",    "฿2"),
            (   100, "coin_1",    "฿1"),
            (    50, "coin_050",  "฿0.50"),
            (    25, "coin_025",  "฿0.25"),
        ]
        try:
            ICP = request.env["ir.config_parameter"].sudo()
            thresholds = {}
            for satang, key, label in DENOM_MAP:
                thresholds[satang] = {
                    "label": label,
                    "low":  int(ICP.get_param(f"gas_station_cash.wm_low_{key}",  0) or 0),
                    "high": int(ICP.get_param(f"gas_station_cash.wm_high_{key}", 0) or 0),
                }

            avail = self._call_bridge_api(
                "/fcc/api/v1/cash/availability", method="GET",
                data={"session_id": _session_id()},
            )

            warnings = []
            if avail:
                all_items = []
                if isinstance(avail, dict):
                    all_items += avail.get("notes", []) + avail.get("coins", [])

                for item in all_items:
                    satang = int(item.get("value", 0))
                    qty    = int(item.get("qty",   0))
                    t      = thresholds.get(satang)
                    if not t:
                        continue
                    if t["low"] > 0 and qty < t["low"]:
                        warnings.append({
                            "valueSatang": satang,
                            "label":       t["label"],
                            "qty":         qty,
                            "threshold":   t["low"],
                            "type":        "near_empty",
                            "severity":    "critical" if qty == 0 else "warning",
                            "message":     f"{t['label']}: qty {qty} below Near Empty threshold ({t['low']})",
                        })
                    elif t["high"] > 0 and qty > t["high"]:
                        warnings.append({
                            "valueSatang": satang,
                            "label":       t["label"],
                            "qty":         qty,
                            "threshold":   t["high"],
                            "type":        "near_full",
                            "severity":    "warning",
                            "message":     f"{t['label']}: qty {qty} above Near Full threshold ({t['high']})",
                        })

            return {
                "type": "response", "name": "inventory_warnings",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success":     True,
                    "hasWarnings": len(warnings) > 0,
                    "warnings":    warnings,
                },
            }
        except Exception as e:
            _logger.error("check_inventory_warnings error: %s", e)
            return {
                "type": "response", "name": "inventory_warnings",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "hasWarnings": False, "warnings": []},
            }