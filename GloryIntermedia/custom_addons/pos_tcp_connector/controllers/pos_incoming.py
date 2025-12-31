# custom_addons/pos_tcp_connector/controllers/pos_incoming.py
# -*- coding: utf-8 -*-
import logging
import json
from datetime import datetime

from odoo import http, fields
from odoo.http import request

_logger = logging.getLogger(__name__)


class PosIncomingController(http.Controller):
    """Incoming JSON endpoints called by POS (FirstPro / FlowCo).

    Implements:
      - POST /CloseShift
      - POST /EndOfDay
    """

    # ------------------------------------------------------------------
    # Helper: time utilities
    # ------------------------------------------------------------------
    def _now_iso(self):
        """Return current datetime in ISO format with timezone, for time_stamp."""
        dt = fields.Datetime.context_timestamp(
            request.env.user,
            fields.Datetime.now()
        )
        return dt.isoformat()

    def _today(self):
        """Return today's date (context aware)."""
        return fields.Date.context_today(request.env.user)

    # ------------------------------------------------------------------
    # Helper: compute totals from gas.station.cash.deposit
    # ------------------------------------------------------------------
    def _compute_shift_total_for_staff(self, staff_external_id):
        """
        Sum total_amount of audited deposits for today,
        for the given staff external_id (e.g. 'CASHIER-0007').

        Returns a float.
        """
        env = request.env
        Deposit = env["gas.station.cash.deposit"].sudo()
        Staff = env["gas.station.staff"].sudo()

        today = self._today()
        domain = [
            ("state", "=", "audited"),
            ("date", "=", today),
        ]

        staff_rec = None
        if staff_external_id:
            staff_rec = Staff.search([
                "|",
                ("external_id", "=", staff_external_id),
                ("employee_id", "=", staff_external_id),
            ], limit=1)

        if staff_rec:
            domain.append(("staff_id", "=", staff_rec.id))

        # Use read_group for better performance and a clean sum
        grouped = Deposit.read_group(
            domain,
            ["total_amount:sum"],
            []
        )
        if grouped:
            return grouped[0].get("total_amount_sum") or 0.0
        return 0.0

    def _compute_eod_total(self):
        """
        Sum total_amount of all audited deposits for today (all staff).
        Returns a float.
        """
        env = request.env
        Deposit = env["gas.station.cash.deposit"].sudo()
        today = self._today()

        domain = [
            ("state", "=", "audited"),
            ("date", "=", today),
        ]
        grouped = Deposit.read_group(
            domain,
            ["total_amount:sum"],
            []
        )
        if grouped:
            return grouped[0].get("total_amount_sum") or 0.0
        return 0.0

    # ================== INTERNAL HELPERS FOR POS TOTALS ==================
    # ------------------------------------------------------------------
    # Helpers for POS totals
    # ------------------------------------------------------------------
    def _compute_pos_total_for_shift(self):
        """
        Compute today's total audited POS-related deposits
        (all staff, only is_pos_related=True).
        """
        env = request.env
        Deposit = env["gas.station.cash.deposit"].sudo()
        today = fields.Date.context_today(env.user) or fields.Date.today()

        domain = [
            ("state", "=", "audited"),
            ("is_pos_related", "=", True),
            ("date", "=", today),
        ]
        deposits = Deposit.search(domain)
        total = sum(deposits.mapped("total_amount")) or 0.0

        _logger.info(
            "CloseShift total for today=%s (all staff, POS-related only): %s from %s deposit(s)",
            today,
            total,
            len(deposits),
        )
        return float(total)

    def _compute_pos_total_since_last_eod(self):
        """
        Compute total audited POS-related deposits from the last EOD date
        (exclusive) up to today (inclusive), and update the last EOD date.

        Returns (total, last_eod, today).
        """
        env = request.env
        Deposit = env["gas.station.cash.deposit"].sudo()
        cfg = env["ir.config_parameter"].sudo()

        today = fields.Date.context_today(env.user) or fields.Date.today()

        last_eod_str = cfg.get_param("gas_station_cash.last_eod_date")
        last_eod = None
        if last_eod_str:
            try:
                last_eod = fields.Date.from_string(last_eod_str)
            except Exception:
                last_eod = None

        domain = [
            ("state", "=", "audited"),
            ("is_pos_related", "=", True),
            ("date", "<=", today),
        ]
        if last_eod:
            domain.append(("date", ">", last_eod))

        deposits = Deposit.search(domain)
        total = sum(deposits.mapped("total_amount")) or 0.0

        _logger.info(
            "EndOfDay total from %s to %s (POS-related only): %s from %s deposit(s)",
            last_eod or "(beginning)",
            today,
            total,
            len(deposits),
        )

        # update last EOD date to today
        cfg.set_param("gas_station_cash.last_eod_date", fields.Date.to_string(today))

        return float(total), last_eod, today

    # ------------------------------------------------------------------
    # TODO hook: perform collect in FCC
    # ------------------------------------------------------------------
    def _maybe_collect_cash_after_close(self, staff_id, total_cash_amount):
        """
        Placeholder to trigger FCC CollectOperation if config says so.

        Later we will:
          - read a config parameter like 'gas_station_cash.collect_on_close_shift'
          - call your FCC API (Flask / GloryAPI) to perform collect
          - handle success/failure and maybe log or include info in response
        """
        env = request.env
        cfg = env["ir.config_parameter"].sudo()
        collect_flag = cfg.get_param("gas_station_cash.collect_on_close_shift") or "false"
        collect_enabled = str(collect_flag).lower() in ("1", "true", "yes", "y")

        if not collect_enabled:
            _logger.info(
                "CloseShift: collect_on_close_shift is disabled; skipping collect. staff_id=%s total=%s",
                staff_id,
                total_cash_amount,
            )
            return

        # Here we will later call the real FCC collect API.
        # For now, just log so we can see it in the logs.
        _logger.info(
            "CloseShift: would perform FCC collect now (staff_id=%s, total=%s)",
            staff_id,
            total_cash_amount,
        )

    # ------------------------------------------------------------------
    # /CloseShift
    # ------------------------------------------------------------------
    @http.route(
        ["/CloseShift", "/api/pos/CloseShift"],
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def close_shift(self, **kwargs):
        """
        POS -> GloryIntermedia:
          POST /CloseShift
          { "staff_id": "CASHIER-0007" }

        We ignore staff when summing – we send today's POS-related total
        (all staff) back to POS.
        """
        # Raw body for safety (POS may not send urlencoded form)
        try:
            raw_body = request.httprequest.get_data(as_text=True) or "{}"
            payload = json.loads(raw_body)
        except Exception:
            payload = {}

        staff_id = payload.get("staff_id") or kwargs.get("staff_id")
        if not staff_id:
            resp = {
                "status": "FAILED",
                "message": "Missing staff_id in request.",
            }
            _logger.warning("CloseShift missing staff_id: body=%s kwargs=%s", payload, kwargs)
            return request.make_json_response(resp, status=400)

        _logger.info("POS CloseShift received: %s", payload)

        # Compute total for today's audited POS-related deposits
        total_cash_amount = self._compute_pos_total_for_shift()

        # Optionally trigger FCC collect (depending on config)
        self._maybe_collect_cash_after_close(staff_id, total_cash_amount)

        # Build SHIFT id based on today's date and staff_id
        today = fields.Date.context_today(request.env.user) or fields.Date.today()
        today_str = today.strftime("%Y%m%d")
        shift_id = f"SHIFT-{today_str}-{staff_id}"

        now_iso = self._now_iso()

        resp = {
            "shift_id": shift_id,
            "status": "OK",
            "total_cash_amount": total_cash_amount,
            "discription": "Close shift accepted.",
            "time_stamp": now_iso,
        }

        _logger.info("POS CloseShift response: %s", resp)
        return request.make_json_response(resp)

    # ------------------------------------------------------------------
    # /EndOfDay
    # ------------------------------------------------------------------
    @http.route(
        ["/EndOfDay", "/api/pos/EndOfDay"],
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def end_of_day(self, **kwargs):
        """
        POS -> GloryIntermedia:
          POST /EndOfDay
          { "staff_id": "CASHIER-0007" }

        Meaning (business rule):
          - EndOfDay total = sum of POS-related, audited deposits
            that happened AFTER the last EndOfDay.

        GloryIntermedia -> POS:
          {
            "shift_id": "EOD-YYYYMMDD-<staff_id>",
            "status": "OK",
            "total_cash_amount": <float>,
            "discription": "End of day accepted.",
            "time_stamp": "<ISO datetime>"
          }
        """
        # Parse JSON body
        try:
            payload = request.get_json_data()
        except Exception:
            payload = request.jsonrequest or {}

        payload = payload or {}
        _logger.info("POS EndOfDay received: %s", payload)

        staff_id = payload.get("staff_id") or "UNKNOWN"

        # Compute total since last EOD (POS-related, audited only)
        total_cash_amount, last_eod, today = self._compute_pos_total_since_last_eod()

        # Build shift_id prefix for EOD
        shift_id = f"EOD-{today.strftime('%Y%m%d')}-{staff_id}"

        resp = {
            "shift_id": shift_id,
            "status": "OK",
            "total_cash_amount": total_cash_amount,
            "discription": "End of day accepted.",
            "time_stamp": self._now_iso(),
        }

        _logger.info("POS EndOfDay response: %s", resp)
        return request.make_json_response(resp)
