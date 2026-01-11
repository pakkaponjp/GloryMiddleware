# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request
import json
import uuid
import logging
import time
import threading

_logger = logging.getLogger(__name__)

class PosCommandController(http.Controller):

    def _create_command(self, action_key: str, staff_id: str):
        Command = request.env["gas.station.pos_command"].sudo()
        internal_req_id = uuid.uuid4().hex

        terminal_id = "TERM-01"

        cmd = Command.create({
            "name": f"{action_key} / {internal_req_id}",
            "action": action_key,
            "request_id": internal_req_id,
            "pos_terminal_id": terminal_id,
            "staff_external_id": staff_id,
            "status": "processing",
            "message": "processing...",
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

    def _process_close_shift_async(self, dbname, uid, cmd_id):
        """
        Background thread to simulate close shift processing
        After delay, mark as done
        """
        try:
            # Simulate processing time (5 seconds)
            _logger.info("⏰ CloseShift processing started, waiting 5 seconds...")
            time.sleep(5)
            
            # Get registry and create new environment
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if cmd.exists():
                    _logger.info("✅ CloseShift delay complete, marking as DONE...")
                    # Mark as done
                    result = {
                        "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-AUTO-01",
                        "total_cash": 12500.00,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    _logger.info("✅ CloseShift command %s marked as DONE", cmd_id)
                else:
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process close shift async: %s", e)

    @http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift(self, **kwargs):
        _logger.info("=" * 80)
        _logger.info("📥 CLOSE SHIFT REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("Raw request body: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in CloseShift request: %s", e)
            return self._json_response({"status": "FAILED", "discription": "Invalid JSON"}, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            _logger.warning("⚠️ Missing staff_id in CloseShift request")
            return self._json_response({"status": "FAILED", "discription": "Missing staff_id"}, status=400)

        _logger.info("Staff ID: %s", staff_id)
        _logger.info("Creating CloseShift command...")
        
        cmd = self._create_command("close_shift", staff_id)
        
        _logger.info("✅ Command created successfully")
        _logger.info("   - Command ID: %s", cmd.id)
        _logger.info("   - Request ID: %s", cmd.request_id)
        
        _logger.info("📤 Pushing initial overlay (processing)...")
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)
        
        # Start background processing with proper context
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        _logger.info("🔄 Starting background processing thread...")
        thread = threading.Thread(
            target=self._process_close_shift_async, 
            args=(dbname, uid, cmd.id)
        )
        thread.daemon = True
        thread.start()
        
        resp = {
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-AUTO-01",
            "status": "OK",
            "total_cash_amount": 0.00,
            "discription": "Processing CloseShift",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        
        _logger.info("📤 Sending response: %s", resp)
        _logger.info("=" * 80)
        
        return self._json_response(resp, status=200)

    def _process_end_of_day_async(self, dbname, uid, cmd_id):
        """
        Background thread to simulate end of day processing
        """
        try:
            # Simulate processing time (7 seconds)
            _logger.info("⏰ EndOfDay processing started, waiting 7 seconds...")
            time.sleep(7)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if cmd.exists():
                    _logger.info("✅ EndOfDay delay complete, marking as DONE...")
                    result = {
                        "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                        "total_shifts": 3,
                        "total_cash": 45000.00,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    _logger.info("✅ EndOfDay command %s marked as DONE", cmd_id)
                else:
                    _logger.warning("⚠️ Command %s not found", cmd_id)
                    
        except Exception as e:
            _logger.exception("❌ Failed to process end of day async: %s", e)

    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        _logger.info("=" * 80)
        _logger.info("📥 END OF DAY REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("Raw request body: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            _logger.error("❌ Invalid JSON in EndOfDay request: %s", e)
            return self._json_response({"status": "FAILED", "discription": "Invalid JSON"}, status=400)

        staff_id = data.get("staff_id")
        if not staff_id:
            _logger.warning("⚠️ Missing staff_id in EndOfDay request")
            return self._json_response({"status": "FAILED", "discription": "Missing staff_id"}, status=400)

        _logger.info("Staff ID: %s", staff_id)
        _logger.info("Creating EndOfDay command...")
        
        cmd = self._create_command("end_of_day", staff_id)
        
        _logger.info("✅ Command created successfully")
        _logger.info("   - Command ID: %s", cmd.id)
        
        _logger.info("📤 Pushing initial overlay (processing)...")
        try:
            cmd.push_overlay()
            _logger.info("✅ Overlay pushed successfully")
        except Exception as e:
            _logger.exception("❌ Failed to push overlay: %s", e)

        # Start background processing with proper context
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        _logger.info("🔄 Starting background processing thread...")
        thread = threading.Thread(
            target=self._process_end_of_day_async, 
            args=(dbname, uid, cmd.id)
        )
        thread.daemon = True
        thread.start()

        resp = {
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-AUTO-01",
            "status": "OK",
            "total_cash_amount": 0.00,
            "discription": "Processing EndOfDay",
            "time_stamp": fields.Datetime.now().isoformat(),
        }
        
        _logger.info("📤 Sending response: %s", resp)
        _logger.info("=" * 80)
        
        return self._json_response(resp, status=200)