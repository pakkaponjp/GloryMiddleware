#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock POS Server - HTTP Version
Supports both FirstPro and FlowCo URL patterns

FirstPro endpoints:
    POST /deposit
    POST /CloseShift
    POST /EndOfDay
    POST /HeartBeat

FlowCo endpoints:
    POST /pos/deposit
    POST /pos/CloseShift
    POST /pos/EndOfDay
    POST /pos/HeartBeat

Usage:
    python mock_pos_http.py [port]
    
    Default port: 9001
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime
import os
import sys
import requests

# Configuration
HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9003

# Track transactions for testing
transactions  = []
shifts_closed = 0
end_of_days   = 0
heartbeats    = 0

# ===============================
# ODOO TARGET (POS -> ODOO)
# ===============================
# Default: Odoo รัน local 8069
ODOO_BASE_URL = os.getenv("ODOO_BASE_URL", "http://127.0.0.1:8069").rstrip("/")
ODOO_TIMEOUT = float(os.getenv("ODOO_TIMEOUT", "5.0"))

class MockPOSHandler(BaseHTTPRequestHandler):
    
    def _send_json_response(self, data, status=200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps(data, ensure_ascii=False)
        self.wfile.write(response.encode('utf-8'))
        print(f"📤 TX [{status}]: {data}")
    
    def _read_json_body(self):
        """Read and parse JSON body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            try:
                return json.loads(body.decode('utf-8'))
            except:
                return {}
        return {}
    
    def _normalize_odoo_path(self, raw_path: str) -> str:
        """
        Convert path to Odoo routes with correct case.
        Accepts both lowercase and uppercase from caller.
        """
        p = raw_path.split("?")[0]  # ตัด query string
        lower = p.lower()

        mapping = {
            "/closeshift": "/CloseShift",
            "/pos/closeshift": "/POS/CloseShift",
            "/endofday": "/EndOfDay",
            "/pos/endofday": "/POS/EndOfDay",
        }
        return mapping.get(lower, p)

    def _forward_to_odoo(self, path: str, payload: dict):
        """
        Forward request to Odoo and return (status_code, json_response)
        """
        url = f"{ODOO_BASE_URL}{path}"
        print(f"➡️ Forwarding to Odoo: {url}")
        print(f"➡️ Payload: {payload}")

        try:
            r = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=ODOO_TIMEOUT
            )

            # Odoo บางทีตอบเป็น JSON string / หรือ dict
            try:
                data = r.json()
            except Exception:
                data = {"raw": r.text}

            print(f"⬅️ Odoo response [{r.status_code}]: {data}")
            return r.status_code, data

        except Exception as e:
            print(f"❌ Forward to Odoo failed: {e}")
            return 503, {
                "status": "ERROR",
                "description": f"Cannot reach Odoo: {e}",
                "offline": True,
                "time_stamp": datetime.now().isoformat(),
            }
    
    def do_POST(self):
        """Handle POST requests"""
        path = self.path.lower()
        body = self._read_json_body()
        
        print(f"\n{'='*60}")
        print(f"📥 RX [{self.command}] {self.path}  (matched as: {self.path.lower().split('?')[0]})")
        print(f"📥 Body: {body}")
        
        # Route to appropriate handler — compare lowercase to handle both vendors
        if path in ['/deposit', '/pos/deposit']:
            self._handle_deposit(body)
        elif path in ['/closeshift', '/pos/closeshift']:
            self._handle_close_shift(body)
        elif path in ['/endofday', '/pos/endofday']:
            self._handle_end_of_day(body)
        elif path in ['/heartbeat', '/pos/heartbeat']:
            self._handle_heartbeat(body)
        else:
            self._send_json_response({
                "status": "ERROR",
                "description": f"Unknown endpoint: {self.path}"
            }, 404)
    
    def do_GET(self):
        """Handle GET requests - for status check"""
        if self.path == '/status':
            self._send_json_response({
                "status": "OK",
                "transactions_received": len(transactions),
                "shifts_closed": shifts_closed,
                "end_of_days": end_of_days,
                "heartbeats": heartbeats,
                "odoo_target": ODOO_BASE_URL,
                "server_time": datetime.now().isoformat(),
            })
        else:
            self._send_json_response({"status": "OK", "message": "Mock POS Server"})
    
    def _handle_deposit(self, body):
        """Handle deposit request"""
        global transactions
        
        transaction_id = body.get('transaction_id', 'UNKNOWN')
        staff_id = body.get('staff_id', 'UNKNOWN')
        amount = body.get('amount', 0)
        type_id = body.get('type_id', '-')   # FlowCo: F=Fuel, L=Lube
        pos_id  = body.get('pos_id', '-')    # FlowCo: POS terminal number
        
        # Store transaction
        transactions.append({
            'transaction_id': transaction_id,
            'staff_id': staff_id,
            'amount': amount,
            'type_id': type_id,
            'pos_id': pos_id,
            'timestamp': datetime.now().isoformat(),
        })
        
        print(f"✅ Deposit: tx={transaction_id}, staff={staff_id}, amount={amount}, type={type_id}, pos={pos_id}")
        print(f"   Total transactions: {len(transactions)}")
        
        self._send_json_response({
            "transaction_id": transaction_id,
            "status": "OK",
            "discription": "Deposit Success",  # Note: POS uses "discription" (typo)
            "description": "Deposit Success",
            "time_stamp": datetime.now().isoformat(),
        })
    
        
    #     staff_id = body.get('staff_id', 'UNKNOWN')
    #     shifts_closed += 1
        
    #     # Calculate total from transactions
    #     total = sum(t.get('amount', 0) for t in transactions)
        
    #     print(f"✅ CloseShift: staff={staff_id}, total={total}, shift_count={shifts_closed}")
        
    #     self._send_json_response({
    #         "shift_id": f"SHIFT-{datetime.now().strftime('%Y%m%d')}-{shifts_closed:02d}",
    #         "status": "OK",
    #         "total_cash_amount": total,
    #         "discription": "Deposit Success",
    #         "description": "Deposit Success",
    #         "time_stamp": datetime.now().isoformat(),
    #     })
    def _handle_close_shift(self, body):
        """
        Forward CloseShift to Odoo.

        FirstPro: body contains product_amount = engine oil amount for Odoo to reconcile
        FlowCo:   body contains shift data array (saleamt_fuel, dropamt_fuel, etc.)
        """
        global shifts_closed
        shifts_closed += 1

        vendor = "flowco" if self.path.lower().startswith("/pos/") else "firstpro"
        path = self._normalize_odoo_path(self.path)

        if vendor == "firstpro":
            product_amount = body.get("product_amount")
            print(f"🔄 [FirstPro] CloseShift: staff={body.get('staff_id')} "
                  f"shiftid={body.get('shiftid')} product_amount={product_amount}")
            print(f"   ℹ️  product_amount = engine oil reconcile amount → Odoo")
        else:
            print(f"🔄 [FlowCo] CloseShift: shift={body.get('shift_number')} "
                  f"pos={body.get('pos_id')} entries={len(body.get('data', []))}")

        status, data = self._forward_to_odoo(path, body)
        self._send_json_response(data, status=status)
    
        
    #     staff_id = body.get('staff_id', 'UNKNOWN')
    #     end_of_days += 1
        
    #     # Calculate total from transactions
    #     total = sum(t.get('amount', 0) for t in transactions)
        
    #     print(f"✅ EndOfDay: staff={staff_id}, total={total}, transactions={len(transactions)}")
        
    #     # Clear transactions for new day
    #     transactions = []
        
    #     self._send_json_response({
    #         "shift_id": f"SHIFT-{datetime.now().strftime('%Y%m%d')}-EOD",
    #         "status": "OK",
    #         "total_cash_amount": total,
    #         "discription": "Deposit Success",
    #         "description": "Deposit Success",
    #         "time_stamp": datetime.now().isoformat(),
    #     })
    def _handle_end_of_day(self, body):
        """
        Forward EndOfDay to Odoo.

        FirstPro: body contains product_amount = engine oil amount for Odoo to reconcile
        FlowCo:   body contains EOD shift data
        """
        global end_of_days, transactions
        end_of_days += 1

        vendor = "flowco" if self.path.lower().startswith("/pos/") else "firstpro"
        path = self._normalize_odoo_path(self.path)

        if vendor == "firstpro":
            product_amount = body.get("product_amount")
            print(f"🔄 [FirstPro] EndOfDay: staff={body.get('staff_id')} "
                  f"shiftid={body.get('shiftid')} product_amount={product_amount}")
            print(f"   ℹ️  product_amount = engine oil reconcile amount → Odoo")
        else:
            print(f"🔄 [FlowCo] EndOfDay: shift={body.get('shift_number')} "
                  f"pos={body.get('pos_id')} entries={len(body.get('data', []))}")

        status, data = self._forward_to_odoo(path, body)

        # Clear transactions after successful EOD
        if status == 200 and (data or {}).get("status") == "OK":
            print(f"🧹 Cleared {len(transactions)} stored transactions after EOD")
            transactions = []

        self._send_json_response(data, status=status)
    
    def _handle_heartbeat(self, body):
        """Handle heartbeat request — responds to Odoo HeartbeatWorker"""
        global heartbeats
        heartbeats += 1

        source      = body.get('source_system', 'UNKNOWN')
        terminal_id = body.get('pos_terminal_id', 'TERM-01')
        status_val  = body.get('status', 'OK')

        print(f"💓 Heartbeat #{heartbeats}: source={source}, terminal={terminal_id}, status={status_val}")

        self._send_json_response({
            "status": "acknowledged",
            "pos_terminal_id": terminal_id,
            "timestamp": datetime.now().isoformat(),
        })
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass


def main():
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           MOCK POS SERVER (HTTP)                             ║
╠══════════════════════════════════════════════════════════════╣
║  Host: {HOST}                                               ║
║  Port: {PORT}                                                  ║
╠══════════════════════════════════════════════════════════════╣
║  Supported Endpoints:                                        ║
║                                                              ║
║  FirstPro Pattern:                                           ║
║    POST /deposit      - Receive deposit                      ║
║    POST /CloseShift   - Close shift                          ║
║    POST /EndOfDay     - End of day                           ║
║    POST /HeartBeat    - Heartbeat check                      ║
║                                                              ║
║  FlowCo Pattern:                                             ║
║    POST /POS/Deposit      - Receive deposit                  ║
║    POST /POS/CloseShift   - Close shift                      ║
║    POST /POS/EndOfDay     - End of day                       ║
║    POST /POS/HeartBeat    - Heartbeat check                  ║
║                                                              ║
║  Status:                                                     ║
║    GET  /status       - Get server status                    ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    server = HTTPServer((HOST, PORT), MockPOSHandler)
    print(f"🚀 Server started at http://{HOST}:{PORT}")
    print(f"   Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        print(f"   Total transactions received: {len(transactions)}")
        print(f"   Total shifts closed:         {shifts_closed}")
        print(f"   Total end of days:           {end_of_days}")
        print(f"   Total heartbeats received:   {heartbeats}")


if __name__ == "__main__":
    main()