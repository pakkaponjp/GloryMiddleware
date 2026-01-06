# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import json
import uuid
import logging

class PosCommandController(http.Controller):

    def _create_command(self, action_key: str, staff_id: str):
        Command = request.env["gas.station.pos_command"].sudo()
        internal_req_id = uuid.uuid4().hex

        # terminal_id ไม่อยู่ใน schema -> ใช้ค่า default ภายใน (TERM-01)
        terminal_id = "TERM-01"

        cmd = Command.create({
            "name": f"{action_key} / {internal_req_id}",
            "action": action_key,
            "request_id": internal_req_id,
            "pos_terminal_id": terminal_id,
            "staff_external_id": staff_id,
            "status": "processing",
            "message": "กำลังดำเนินการ...",
            "started_at": fields.Datetime.now(),
            "payload_in": json.dumps({"staff_id": staff_id}, ensure_ascii=False),
        })
        return cmd

    def _json_response(self, payload: dict, status=200):
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status
        )

    @http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True) or "{}"
        try:
            data = json.loads(raw)
        except Exception:
            return self._json_response({"status": "FAILED", "discription": "Invalid JSON"}, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            return self._json_response({"status": "FAILED", "discription": "Missing staff_id"}, status=400)

        cmd = self._create_command("close_shift", staff_id)

        logging.getLogger(__name__).debug(f"Created CloseShift command ID={cmd.id} for staff_id={staff_id}")
        cmd.push_overlay()
        
        logging.getLogger(__name__).debug(f"Pushed overlay for CloseShift command ID={cmd.id}")
        resp = {
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-AUTO-01",
            "status": "OK",
            "total_cash_amount": 0.00,
            "discription": "Processing CloseShift",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        return self._json_response(resp, status=200)

    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True) or "{}"
        try:
            data = json.loads(raw)
        except Exception:
            return self._json_response({"status": "FAILED", "discription": "Invalid JSON"}, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            return self._json_response({"status": "FAILED", "discription": "Missing staff_id"}, status=400)

        cmd = self._create_command("end_of_day", staff_id)

        # ✅ Trigger overlay
        cmd.push_overlay()

        resp = {
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-AUTO-01",
            "status": "OK",
            "total_cash_amount": 0.00,
            "discription": "Processing EndOfDay",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        return self._json_response(resp, status=200)
