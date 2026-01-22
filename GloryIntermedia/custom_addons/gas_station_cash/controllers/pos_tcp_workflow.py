# -*- coding: utf-8 -*-
import json
import socket
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

def _tcp_send_json_line(host: str, port: int, payload: dict, timeout: float = 3.0) -> dict:
    """
    Send 1 JSON line to POS TCP and wait for 1 JSON line response.
    Protocol: JSON + '\n'
    """
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    buf = b""

    _logger.debug("debug: TCP send to %s:%s data=%s", host, port, data)
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(data)

        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").strip()
                try:
                    return json.loads(text)
                except Exception:
                    return {"status": "error", "description": "invalid json response", "raw": text}

    return {"status": "error", "description": "no response"}


# class GasStationCashPosTcpWorkflow(http.Controller):
#     @http.route("/gas_station_cash/pos/deposit_tcp", type="json", auth="user", methods=["POST"])
#     def pos_deposit_tcp(self, transaction_id, staff_id, amount, **kwargs):
#         """
#         Called by OWL (OilDeposit) -> Odoo -> TCP to POS
#         Request format (to POS):
#           {
#             "transaction_id": "...",
#             "staff_id": "...",
#             "amount": 4000
#           }
#         """
#         # TODO: Need to read host/port from config parameter
#         host = request.env["ir.config_parameter"].sudo().get_param("pos_tcp.host", "127.0.0.1")
#         port = int(request.env["ir.config_parameter"].sudo().get_param("pos_tcp.port", "9001"))

#         payload = {
#             "transaction_id": transaction_id,
#             "staff_id": staff_id,
#             "amount": amount,
#         }

#         try:
#             _logger.info("POS TCP send -> %s:%s payload=%s", host, port, payload)
#             resp = _tcp_send_json_line(host, port, payload, timeout=3.0)
#             _logger.info("POS TCP resp <- %s", resp)

#             return {
#                 "transaction_id": transaction_id,
#                 "status": resp.get("status") or "error",
#                 "description": resp.get("description") or resp.get("discription") or "",
#                 "time_stamp": resp.get("time_stamp") or "",
#                 "raw": resp,
#             }
#         except Exception as e:
#             return {
#                 "transaction_id": transaction_id,
#                 "status": "error",
#                 "description": f"tcp_error: {e}",
#                 "time_stamp": "",
#                 "raw": {},
#             }
class GasStationCashPosTcpWorkflow(http.Controller):
    @http.route("/gas_station_cash/pos/deposit_tcp", type="json", auth="user", methods=["POST"])
    def pos_deposit_tcp(self, transaction_id, staff_id, amount, **kwargs):
        host = request.env["ir.config_parameter"].sudo().get_param("pos_tcp.host", "58.8.186.194/deposit")
        port = int(request.env["ir.config_parameter"].sudo().get_param("pos_tcp.port", "8060"))

        payload = {
            "transaction_id": transaction_id,
            "staff_id": staff_id,
            "amount": amount,
        }

        try:
            
            _logger.debug("debug: POS TCP send -> %s:%s payload=%s", host, port, payload)
            
            resp = _tcp_send_json_line(host, port, payload, timeout=3.0)
            _logger.debug("debug: POS TCP resp <- %s", resp)
        except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as e:
            raise UserError(f"POS TCP unreachable ({host}:{port}): {e}")

        status = str(resp.get("status") or "").upper()
        return {
            "transaction_id": transaction_id,
            "status": status or "ERROR",
            "description": resp.get("description") or resp.get("discription") or "",
            "time_stamp": resp.get("time_stamp") or "",
            "raw": resp,
        }