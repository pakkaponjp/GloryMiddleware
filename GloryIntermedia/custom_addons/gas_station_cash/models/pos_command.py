# -*- coding: utf-8 -*-
from odoo import fields, models
import json
import logging

_logger = logging.getLogger(__name__)

class GasStationPosCommand(models.Model):
    _name = "gas.station.pos_command"
    _description = "POS Command (Close Shift / End of Day)"
    _order = "create_date desc"

    name = fields.Char(required=True)
    action = fields.Selection([
        ("close_shift", "Close Shift"),
        ("end_of_day", "End Of Day"),
    ], required=True, index=True)

    request_id = fields.Char(required=True, index=True)
    pos_terminal_id = fields.Char(required=True, index=True)
    staff_external_id = fields.Char(index=True)

    status = fields.Selection([
        ("received", "Received"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("failed", "Failed"),
    ], required=True, default="received", index=True)

    message = fields.Char()
    payload_in = fields.Text()
    payload_out = fields.Text()
    error_code = fields.Char()
    error_message = fields.Text()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()

    _sql_constraints = [
        ("uniq_pos_cmd", "unique(action, request_id, pos_terminal_id)",
         "Duplicate POS command for same action/request_id/terminal"),
    ]

    def _bus_channel(self, terminal_id: str):
        return (self.env.cr.dbname, f"gas_station_cash:{terminal_id}")

    def _payload(self):
        self.ensure_one()
        return {
            "command_id": self.id,
            # ให้ action เป็นตัวเดียวกับที่ UI โชว์
            "action": "CloseShift" if self.action == "close_shift" else "EndOfDay",
            "request_id": self.request_id,
            "status": self.status,
            "message": self.message or "",
        }

    def push_overlay(self):
        """Push overlay event to the terminal UI."""
        Bus = self.env["bus.bus"].sudo()
    
        for rec in self:
            try:
                payload = rec._payload()
                channel = rec._bus_channel(rec.pos_terminal_id)
    
                # debug
                _logger.info("PUSH OVERLAY channel=%s event=%s payload=%s", channel, "pos_command", payload)
    
                # ✅ Odoo signature: _sendone(channel, notification_type, message)
                Bus._sendone(channel, "pos_command", payload)
    
            except Exception:
                _logger.exception("Failed to send bus overlay for pos_command id=%s", rec.id)

    def mark_processing(self, message: str):
        for rec in self:
            rec.write({"status": "processing", "message": message})
            rec.push_overlay()

    def mark_done(self, result: dict):
        for rec in self:
            rec.write({
                "status": "done",
                "message": "Success",
                "finished_at": fields.Datetime.now(),
                "payload_out": json.dumps(result, ensure_ascii=False),
            })
            rec.push_overlay()

    def mark_failed(self, code: str, msg: str):
        for rec in self:
            rec.write({
                "status": "failed",
                "message": "Failed",
                "error_code": code,
                "error_message": msg,
                "finished_at": fields.Datetime.now(),
            })
            rec.push_overlay()
