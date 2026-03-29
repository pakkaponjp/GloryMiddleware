"""
Odoo controller — exposes [glory_machine_config] from odoo.conf to the frontend.

Add this file to:
  custom_addons/<your_module>/controllers/glory_config_controller.py

And register it in __init__.py:
  from . import glory_config_controller

odoo.conf example:
  [glory_machine_config]
  currency = THB
  stacker_note_1000_capacity = 100
  stacker_note_500_capacity  = 100
  stacker_note_100_capacity  = 100
  stacker_note_50_capacity   = 100
  stacker_note_20_capacity   = 100
"""

from odoo import http, tools
from odoo.http import request
import configparser
import os
import logging

_logger = logging.getLogger(__name__)


class GloryConfigController(http.Controller):

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_odoo_conf(self):
        """Probe common odoo.conf locations and return the first that exists."""
        candidates = [
            tools.config.get("config_file"),
            "/etc/odoo/odoo.conf",
            "/etc/odoo.conf",
            os.path.expanduser("~/odoo.conf"),
            os.path.join(os.path.dirname(__file__), "..", "..", "odoo.conf"),
        ]
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _read_glory_section(self):
        """
        Parse odoo.conf and return the contents of [glory_machine_config]
        as a dict, or None when the file / section is missing.
        """
        config_path = tools.config.get("config_file") or self._find_odoo_conf()
        if not config_path or not os.path.exists(config_path):
            _logger.warning("_read_glory_section: odoo.conf not found at %s", config_path)
            return None, "odoo.conf not found"

        parser = configparser.ConfigParser()
        parser.read(config_path)

        if "glory_machine_config" not in parser:
            _logger.warning("_read_glory_section: [glory_machine_config] section missing")
            return None, "[glory_machine_config] section missing"

        return dict(parser["glory_machine_config"]), None

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @http.route("/api/glory/get_stacker_capacities", type="json", auth="user", methods=["POST"])
    def get_stacker_capacities(self):
        """
        Read stacker capacities from [glory_machine_config] in odoo.conf.

        Returns:
        {
            "success": true,
            "data": {
                "capacities": {
                    "stacker_note_1000_capacity": 100,
                    "stacker_note_500_capacity":  100,
                    ...
                }
            }
        }
        """
        try:
            raw, err = self._read_glory_section()
            if raw is None:
                return {"success": False, "message": err, "data": {"capacities": {}}}

            # Keep only capacity keys; coerce to int where possible
            capacities = {}
            for key, val in raw.items():
                if "capacity" in key:
                    try:
                        capacities[key] = int(val)
                    except ValueError:
                        capacities[key] = val

            return {"success": True, "data": {"capacities": capacities}}

        except Exception as e:
            _logger.exception("get_stacker_capacities error: %s", e)
            return {"success": False, "message": str(e), "data": {"capacities": {}}}

    @http.route("/api/glory/get_machine_currency", type="json", auth="public", methods=["POST"], csrf=False)
    def get_machine_currency(self):
        """
        Return fcc_currency from [fcc_config] in odoo.conf.
        Same section read by fcc_proxy.py — no extra config keys needed.

        Response:
        {
            "success": true,
            "data": { "currency": "EUR", "source": "odoo.conf" }
        }
        """
        try:
            config_path = tools.config.get("config_file") or self._find_odoo_conf()
            if not config_path or not os.path.exists(config_path):
                return {"success": True, "data": {"currency": "THB", "source": "default"}}

            parser = configparser.ConfigParser()
            parser.read(config_path)

            currency = parser.get("fcc_config", "fcc_currency", fallback="THB").strip().upper()
            return {"success": True, "data": {"currency": currency, "source": "odoo.conf"}}

        except Exception as e:
            _logger.exception("get_machine_currency error: %s", e)
            return {"success": False, "data": {"currency": "THB", "source": "default"}}

    @http.route("/api/glory/get_glory_config", type="json", auth="user", methods=["POST"])
    def get_glory_config(self):
        """
        Return the full [glory_machine_config] section as a dict.
        Useful for debugging; requires authenticated user.

        Response:
        {
            "success": true,
            "data": {
                "currency": "THB",
                "stacker_note_1000_capacity": 100,
                ...
            }
        }
        """
        try:
            raw, err = self._read_glory_section()
            if raw is None:
                return {"success": False, "message": err, "data": {}}

            # Coerce numeric strings to int
            data = {}
            for key, val in raw.items():
                try:
                    data[key] = int(val)
                except ValueError:
                    data[key] = val

            return {"success": True, "data": data}

        except Exception as e:
            _logger.exception("get_glory_config error: %s", e)
            return {"success": False, "message": str(e), "data": {}}