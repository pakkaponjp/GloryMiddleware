# custom_addons/pos_tcp_connector/models/pos_connector_mixin.py
import json
import socket
import logging

from odoo import models, api, fields, _
from odoo.http import request
from odoo.tools import config

_logger = logging.getLogger(__name__)


class PosConnectorMixin(models.AbstractModel):
    _name = 'pos.connector.mixin'
    _description = 'POS TCP Connector Mixin'

    # ------------------------------------------------------------------
    # Low-level: resolve vendor + endpoint from odoo.conf
    # ------------------------------------------------------------------
    def _get_pos_vendor(self) -> str:
        """Return 'firstpro' or 'flowco' based on odoo.conf (pos_vendor)."""
        vendor = (config.get('pos_vendor') or 'firstpro').strip().lower()
        if vendor not in ('firstpro', 'flowco'):
            vendor = 'firstpro'
        return vendor

    def _get_pos_endpoint(self, terminal_id=None):
        """
        Return (vendor, host, port, timeout) for current POS vendor.
        terminal_id is kept for future use (per-terminal config if needed).
        """
        vendor = self._get_pos_vendor()
        timeout = float(config.get('pos_tcp_timeout', 3.0))

        if vendor == 'firstpro':
            host = config.get('pos_firstpro_host', '127.0.0.1')
            port = int(config.get('pos_firstpro_port', 9001))
        else:  # flowco
            host = config.get('pos_flowco_host', '127.0.0.1')
            port = int(config.get('pos_flowco_port', 9100))

        return vendor, host, port, timeout

    # ------------------------------------------------------------------
    # Core send: write job, try TCP, update job state
    # ------------------------------------------------------------------
    @api.model
    def _pos_tcp_send(self, payload: dict, message_type: str,
                      terminal_id: str = None,
                      direction: str = 'glory_to_pos') -> dict:
        """
        Send JSON over TCP to POS, and (optionally) create a pos.tcp.job on failure.

        Context flags:
          - no_pos_retry=True  -> do NOT create a job even if sending fails
                                 (used for heartbeat/status checks)

        Returns:
          {
            'ok': True/False,
            'vendor': 'firstpro' | 'flowco',
            'job_id': int or False,
            'response': {...}  # when ok
            'error': '...'     # when not ok
          }
        """
        Job = self.env['pos.tcp.job'].sudo()

        # Resolve endpoint from config / odoo.conf
        vendor, host, port, timeout = self._get_pos_endpoint(terminal_id)
        json_body = json.dumps(payload, ensure_ascii=False)

        job = None
        job_id = False  # default: no job unless we queue on failure

        try:
            data = (json_body + '\n').encode('utf-8')
            _logger.info(
                "POS TCP send [%s] to %s:%s payload=%s",
                vendor, host, port, json_body,
            )

            # Open TCP connection and send
            with socket.create_connection((host, port), timeout=timeout) as sock:
                sock.sendall(data)
                sock.settimeout(timeout)

                # Read until newline or EOF
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if b'\n' in chunk:
                        break

            raw_resp = b''.join(chunks).strip()
            if raw_resp:
                try:
                    resp = json.loads(raw_resp.decode('utf-8'))
                except Exception:
                    resp = {'raw': raw_resp.decode('utf-8', errors='replace')}
            else:
                resp = {}

            # SUCCESS: we do NOT create a job here – no retry needed
            return {
                'ok': True,
                'vendor': vendor,
                'job_id': False,
                'response': resp,
            }

        except Exception as e:
            msg = str(e)
            _logger.warning(
                "POS TCP send FAILED [%s] to %s:%s: %s",
                vendor, host, port, msg,
            )

            # Only create a job if we *do* want retry (i.e. normal business message)
            # Heartbeat etc. should call this with context no_pos_retry=True
            if not self.env.context.get('no_pos_retry'):
                vals = {
                    'vendor': vendor,
                    'terminal_id': terminal_id or payload.get('pos_terminal_id'),
                    'message_type': message_type,
                    'direction': direction,
                    'payload_json': json_body,
                    'state': 'error',
                    'error_message': msg,
                }
                job = Job.create(vals)
                job_id = job.id

            return {
                'ok': False,
                'vendor': vendor,
                'job_id': job_id,
                'error': msg,
            }

    # ------------------------------------------------------------------
    # Middleware readiness flag
    # ------------------------------------------------------------------
    @api.model
    def is_middleware_ready(self) -> bool:
        """Return True if Gas Station Cash middleware is 'ready'."""
        cfg = self.env['ir.config_parameter'].sudo()
        return cfg.get_param('gas_station_cash.mw_ready') == 'true'

    # ------------------------------------------------------------------
    # Guard: ensure middleware is ready, or return HTTP JSON response
    # ------------------------------------------------------------------
    @api.model
    def _ensure_middleware_ready_or_fail(self, staff_id=None, terminal_id=None):
        cfg = self.env["ir.config_parameter"].sudo()
        flag = cfg.get_param("gas_station_cash.mw_ready")
        is_ready = str(flag).lower() in ("true", "1", "yes", "y")

        if not is_ready:
            _logger.warning(
                "POS request rejected: middleware not ready "
                "(staff_id=%s, terminal_id=%s)",
                staff_id,
                terminal_id,
            )
            # POS expects a JSON body; 503 for "service not ready"
            from odoo.http import request as http_request
            return http_request.make_json_response(
                {"status": "FAILED", "msg": "Middleware is not ready."},
                status=503,
            )
        return None

    # ------------------------------------------------------------------
    # High-level: heartbeat + readiness helper
    # ------------------------------------------------------------------
    @api.model
    def pos_send_heartbeat(self, terminal_id: str, staff_id: str | None = None) -> dict:
        """
        Called by Gas Station Cash (or other app) when a user logs in / opens the cash screen.

        JSON matches FirstPro HeartBeat spec (Glory is the source):
        {
          "source_system": "GloryIntermedia",
          "pos_terminal_id": "TERM-01",
          "status": "OK",
          "timestamp": "...",
          "staff_id": "CASHIER-0007"   # optional extra
        }
        """
        from datetime import datetime
        import pytz

        tz = pytz.timezone(self.env.user.tz or 'Asia/Bangkok')
        now = datetime.now(tz)
        timestamp = now.isoformat()

        payload = {
            "source_system": "GloryIntermedia",      # our side
            "pos_terminal_id": terminal_id,
            "status": "OK",
            "timestamp": timestamp,
        }
        if staff_id:
            payload["staff_id"] = staff_id

        result = self.with_context(no_pos_retry=True)._pos_tcp_send(
            payload=payload,
            message_type='heartbeat',
            terminal_id=terminal_id,
        )

        ready = False
        message = "Gas station cash is not ready."

        if result.get('ok'):
            resp = result.get('response') or {}
            status = str(resp.get('status', '')).lower()
            # FirstPro response spec:
            # { "status": "acknowledged", "pos_terminal_id": "...", "timestamp": "..." }
            if status in ('acknowledged', 'ok', 'ready'):
                ready = True
                message = "Gas station cash is ready."
            else:
                message = f"Gas station cash is not ready (POS status: {resp.get('status')!r})."
        else:
            message = f"Gas station cash is not ready (POS offline: {result.get('error')})."

        pos_result_clean = dict(result or {})
        pos_result_clean.pop('vendor', None)

        return {
            "ready": ready,
            "message": message,
            "pos_result": pos_result_clean,
        }

    # ------------------------------------------------------------------
    # High-level: deposit + other helpers
    # ------------------------------------------------------------------
    @api.model
    def pos_send_deposit(self,
                         *,
                         transaction_id: str,
                         staff_id: str,
                         amount,
                         terminal_id: str | None = None) -> dict:
        """
        Send a Deposit request to POS over TCP.

        JSON spec (request):

            POST /Deposit
            {
              "transaction_id": "TXN-20250926-12345",
              "staff_id": "CASHIER-0007",
              "amount": 4000
            }

        POS response (example):

            {
              "transaction_id": "TXN-20250926-12345",
              "status": "OK",
              "discription": "Deposit Success",
              "time_stamp": "2025-09-26T17:45:00+07:00"
            }

        Returns a normalized dict:

            {
              "ok": True/False,
              "job_id": int or False,
              "pos_result": {
                  "raw_response": {...},   # whatever POS sent
                  "status": "...",         # POS status if present
                  "description": "...",    # mapped from 'discription' or 'description'
                  "time_stamp": "..."      # if present
              },
              "message": "human readable summary"
            }
        """

        # Normalize amount (POS expects numeric, spec shows plain 4000)
        try:
            amt = float(amount)
        except Exception:
            raise ValueError(f"Invalid amount for POS deposit: {amount!r}")

        # Build request payload exactly as agreed with FirstPro
        payload = {
            "transaction_id": str(transaction_id),
            "staff_id": str(staff_id),
            "amount": amt,
        }

        # Use our TCP core; we DO want retry/jobs if offline → no `no_pos_retry` in context
        send_res = self._pos_tcp_send(
            payload=payload,
            message_type="deposit",
            terminal_id=terminal_id,
            direction="glory_to_pos",
        )

        # Build friendly wrapper for UI / callers
        pos_resp = send_res.get("response") if send_res.get("ok") else {}
        status = (pos_resp or {}).get("status")
        # FirstPro uses *discription* (typo); be robust:
        description = (pos_resp or {}).get("discription") or (pos_resp or {}).get("description")
        ts = (pos_resp or {}).get("time_stamp")

        if send_res["ok"]:
            msg = description or f"Deposit sent to POS successfully (status={status})."
            return {
                "ok": True,
                "job_id": False,
                "pos_result": {
                    "raw_response": pos_resp,
                    "status": status,
                    "description": description,
                    "time_stamp": ts,
                },
                "message": msg,
            }
        else:
            # Offline / error: job_id will be set by _pos_tcp_send
            err = send_res.get("error") or "Unknown POS error"
            msg = f"POS deposit failed ({err})."
            if send_res.get("job_id"):
                msg += f" Job #{send_res['job_id']} queued for later sync."

            return {
                "ok": False,
                "job_id": send_res.get("job_id") or False,
                "pos_result": {
                    "raw_response": pos_resp,
                    "status": status,
                    "description": description,
                    "time_stamp": ts,
                },
                "message": msg,
            }