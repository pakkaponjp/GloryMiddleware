"""
Odoo controller — exposes [glory_machine_config] from odoo.conf to the frontend.

Add this file to:
  custom_addons/<your_module>/controllers/glory_config_controller.py

And register it in __init__.py:
  from . import glory_config_controller
"""

from odoo import http
from odoo.http import request
import configparser
import os
import logging

_logger = logging.getLogger(__name__)


class GloryConfigController(http.Controller):

    @http.route("/api/glory/get_stacker_capacities", type="json", auth="user", methods=["POST"])
    def get_stacker_capacities(self):
        """
        Read stacker capacities from [glory_machine_config] section in odoo.conf.

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
            # Locate odoo.conf — Odoo stores its config path at startup
            config_path = http.root.config.get("config_file") or self._find_odoo_conf()

            if not config_path or not os.path.exists(config_path):
                _logger.warning("get_stacker_capacities: odoo.conf not found at %s", config_path)
                return {"success": False, "message": "odoo.conf not found", "data": {"capacities": {}}}

            parser = configparser.ConfigParser()
            parser.read(config_path)

            if "glory_machine_config" not in parser:
                _logger.warning("get_stacker_capacities: [glory_machine_config] section missing in odoo.conf")
                return {"success": False, "message": "[glory_machine_config] section missing", "data": {"capacities": {}}}

            # Return all keys in the section as integers (fall back to raw string if not int)
            raw = dict(parser["glory_machine_config"])
            capacities = {}
            for key, val in raw.items():
                try:
                    capacities[key] = int(val)
                except ValueError:
                    capacities[key] = val

            return {
                "success": True,
                "data": {"capacities": capacities},
            }

        except Exception as e:
            _logger.exception("get_stacker_capacities error: %s", e)
            return {"success": False, "message": str(e), "data": {"capacities": {}}}

    def _find_odoo_conf(self):
        """Fallback: try common odoo.conf locations."""
        candidates = [
            "/etc/odoo/odoo.conf",
            "/etc/odoo.conf",
            os.path.expanduser("~/odoo.conf"),
            os.path.join(os.path.dirname(__file__), "..", "..", "odoo.conf"),
        ]
        for path in candidates:
            if os.path.exists(path):
                return path
        return None