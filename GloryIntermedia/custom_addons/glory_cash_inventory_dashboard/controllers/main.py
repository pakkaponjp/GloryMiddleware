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
# ---------------------------------------------------------------------------
# THB canonical denomination slots (fv in satang — same scale FCC always uses
# regardless of configured currency).
# FCC returns fv values that identify cassette slots, not currency amounts.
# fv=5000 = slot ฿50, fv=50000 = slot ฿500, etc. — same slot number in EUR or THB.
# We simply filter the FCC response to keep only known THB slots.
# ---------------------------------------------------------------------------
THB_NOTE_SLOTS = [100000, 50000, 10000, 5000, 2000]  # ฿1000 ฿500 ฿100 ฿50 ฿20
THB_COIN_SLOTS = [1000, 500, 200, 100, 50, 25]        # ฿10  ฿5   ฿2   ฿1  ฿0.50 ฿0.25


def _build_thb_inventory(raw_notes: list, raw_coins: list, currency: str = "THB") -> tuple[list, list]:
    """
    Filter FCC inventory to known THB denomination slots.

    FCC fv values identify cassette slot positions — they are the same number
    regardless of the machine's configured currency (EUR or THB). For example,
    fv=5000 always means the ฿50 slot. We therefore do NOT remap by currency;
    we simply match fv values against THB_NOTE_SLOTS / THB_COIN_SLOTS and
    return a stable list with qty=0 for slots not present in the FCC response.

    Args:
        raw_notes: list of note items from FCC  [{"value": fv, "qty": n, ...}]
        raw_coins: list of coin items from FCC
        currency:  informational only — not used for remapping
    """
    raw_notes = [i for i in raw_notes if int(i.get("value", 0)) != 0]
    raw_coins = [i for i in raw_coins if int(i.get("value", 0)) != 0]

    note_lookup = {int(i.get("value", 0)): i for i in raw_notes}
    coin_lookup = {int(i.get("value", 0)): i for i in raw_coins}

    def _slot_list(slots: list, lookup: dict) -> list:
        result = []
        for fv in slots:
            src = lookup.get(fv, {})
            result.append({
                **src,
                "value": fv,
                "qty":   src.get("qty", 0),
            })
        return result

    notes = _slot_list(THB_NOTE_SLOTS, note_lookup)
    coins = _slot_list(THB_COIN_SLOTS, coin_lookup)

    _logger.debug(
        "_build_thb_inventory: currency=%s notes_in=%d coins_in=%d notes_out=%d coins_out=%d",
        currency, len(raw_notes), len(raw_coins), len(notes), len(coins),
    )
    return notes, coins


# ---------------------------------------------------------------------------
# odoo.conf helpers
# Reads from [fcc_config] — same section used by fcc_proxy.py.
# ---------------------------------------------------------------------------

def _find_odoo_conf() -> str | None:
    """
    Probe odoo.conf locations in priority order:
    1. Path passed via -c flag at startup (tools.config)
    2. /etc/odoo/odoo.conf — Docker / UAT environment
    3. /etc/odoo.conf — alternative system install
    4. ~/odoo.conf — local dev (venv, run without -c)
    """
    candidates = [
        "/etc/odoo/odoo.conf",                  # Docker / UAT — check first
        tools.config.get("config_file"),         # -c flag (may be None)
        "/etc/odoo.conf",
        os.path.expanduser("~/odoo.conf"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            _logger.debug("_find_odoo_conf: using %s", path)
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

            # Default — all Thai Baht denominations (satang):
            # Notes: ฿20=2000, ฿50=5000, ฿100=10000, ฿500=50000, ฿1000=100000
            _ALL_THB_DENOMS = [2000, 5000, 10000, 50000, 100000]
            return {
                "type": "response", "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": True, "allowedNotes": _ALL_THB_DENOMS},
            }
        except Exception as e:
            _logger.error("get_change_allowed_notes error: %s", e)
            return {
                "type": "response", "name": "change_allowed_notes",
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {"success": False, "message": str(e), "allowedNotes": [2000, 5000, 10000, 50000, 100000]},
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
        Fetch cash inventory for the dashboard stacker cylinders.
        Focus on Type 4 (Dispensable) and Piece count.
        """
        try:
            # 1. Extract Transaction ID
            request_data = kwargs
            if "params" in kwargs:
                request_data = kwargs["params"]
            elif len(kwargs) == 1 and not isinstance(list(kwargs.values())[0], (str, int)):
                request_data = list(kwargs.values())[0]
            
            transaction_id = request_data.get("transactionId", "")
            currency = _configured_currency()
    
            # 2. Call Bridge API
            inv_raw = self._call_bridge_api(
                "/fcc/api/v1/cash/inventory", 
                method="GET",
                data={"session_id": _session_id()},
            ) or {}
    
            # 3. Parse Type=4 (Dispensable)
            t4_notes, t4_coins = [], []
            raw_soap = inv_raw.get("raw") or {}
            
            # แก้ไข logging ให้รองรับ dict
            _logger.debug("-------------> INVENTORY RAW: %s", raw_soap)
    
            if isinstance(raw_soap, dict):
                # เข้าถึง InventoryResponse หรือใช้ตัวมันเองถ้ากระจายมาแล้ว
                inv_r = raw_soap.get("InventoryResponse") or raw_soap
                cash_blocks = inv_r.get("Cash") or []
                
                if isinstance(cash_blocks, dict):
                    cash_blocks = [cash_blocks]
    
                for blk in cash_blocks:
                    # กรองเอาเฉพาะ Type 4
                    blk_type = str(blk.get("type") if blk else "")
                    if blk_type != "4":
                        continue
                    
                    denoms = blk.get("Denomination") or []
                    if isinstance(denoms, dict):
                        denoms = [denoms]
    
                    for d in denoms:
                        fv = int(d.get("fv", 0) or 0)
                        if fv <= 0:
                            continue
                        
                        # หัวใจสำคัญ: ดึงค่า Piece (จำนวนใบ/เหรียญ)
                        # Emulator บางตัวอาจใช้ "Piece" หรือ "{http://...}Piece" ขึ้นอยู่กับการ parse
                        qty = int(d.get("Piece", 0) or 0)
                        
                        devid = int(d.get("devid", 0) or 0)
                        st = int(d.get("Status", 0) or 0)
                        cc = d.get("cc") or ""
    
                        item = {
                            "value": fv, 
                            "qty": qty, 
                            "status": st, # เก็บไว้ตามต้นฉบับ
                            "device": devid, 
                            "cc": cc
                        }
    
                        if devid == 2:
                            t4_coins.append(item)
                        else:
                            t4_notes.append(item)
    
            _logger.info("check_float processed: Type=4 notes=%d, coins=%d", len(t4_notes), len(t4_coins))
    
            # 4. Build Response
            avail_notes, avail_coins = _build_thb_inventory(t4_notes, t4_coins, currency)
            
            return {
                "type": "response",
                "name": "float_balance_report",
                "transactionId": transaction_id,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": True,
                    "message": "Current inventory retrieved.",
                    "bridgeApiInventory": inv_raw,           # เก็บไว้เผื่อ JS ใช้ข้อมูลดิบ
                    "bridgeApiAvailability": {
                        "notes": avail_notes,
                        "coins": avail_coins,
                        "currency": currency,
                    },
                },
            }
    
        except Exception as e:
            _logger.error("check_float error: %s", e, exc_info=True)
            # Fallback เพื่อให้ระบบไม่ค้างและส่ง Error กลับไปที่ UI
            return {
                "type": "response",
                "name": "float_balance_report",
                "transactionId": kwargs.get("transactionId", ""),
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "data": {
                    "success": False, 
                    "message": f"Error checking inventory: {str(e)}"
                },
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