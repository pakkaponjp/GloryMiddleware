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
import sys

# Configuration
HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9001

# Track transactions for testing
transactions = []
shifts_closed = 0
end_of_days = 0


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
    
    def do_POST(self):
        """Handle POST requests"""
        path = self.path.lower()
        body = self._read_json_body()
        
        print(f"\n{'='*60}")
        print(f"📥 RX [{self.command}] {self.path}")
        print(f"📥 Body: {body}")
        
        # Route to appropriate handler
        # Support both FirstPro (/deposit) and FlowCo (/pos/deposit) patterns
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
        
        # Store transaction
        transactions.append({
            'transaction_id': transaction_id,
            'staff_id': staff_id,
            'amount': amount,
            'timestamp': datetime.now().isoformat(),
        })
        
        print(f"✅ Deposit: tx={transaction_id}, staff={staff_id}, amount={amount}")
        print(f"   Total transactions: {len(transactions)}")
        
        self._send_json_response({
            "transaction_id": transaction_id,
            "status": "OK",
            "discription": "Deposit Success",  # Note: POS uses "discription" (typo)
            "description": "Deposit Success",
            "time_stamp": datetime.now().isoformat(),
        })
    
    def _handle_close_shift(self, body):
        """Handle close shift request"""
        global shifts_closed
        
        staff_id = body.get('staff_id', 'UNKNOWN')
        shifts_closed += 1
        
        # Calculate total from transactions
        total = sum(t.get('amount', 0) for t in transactions)
        
        print(f"✅ CloseShift: staff={staff_id}, total={total}, shift_count={shifts_closed}")
        
        self._send_json_response({
            "shift_id": f"SHIFT-{datetime.now().strftime('%Y%m%d')}-{shifts_closed:02d}",
            "status": "OK",
            "total_cash_amount": total,
            "discription": "Deposit Success",
            "description": "Deposit Success",
            "time_stamp": datetime.now().isoformat(),
        })
    
    def _handle_end_of_day(self, body):
        """Handle end of day request"""
        global end_of_days, transactions
        
        staff_id = body.get('staff_id', 'UNKNOWN')
        end_of_days += 1
        
        # Calculate total from transactions
        total = sum(t.get('amount', 0) for t in transactions)
        
        print(f"✅ EndOfDay: staff={staff_id}, total={total}, transactions={len(transactions)}")
        
        # Clear transactions for new day
        transactions = []
        
        self._send_json_response({
            "shift_id": f"SHIFT-{datetime.now().strftime('%Y%m%d')}-EOD",
            "status": "OK",
            "total_cash_amount": total,
            "discription": "Deposit Success",
            "description": "Deposit Success",
            "time_stamp": datetime.now().isoformat(),
        })
    
    def _handle_heartbeat(self, body):
        """Handle heartbeat request"""
        source = body.get('source_system', 'UNKNOWN')
        terminal_id = body.get('pos_terminal_id', 'TERM-01')
        
        print(f"💓 Heartbeat: source={source}, terminal={terminal_id}")
        
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
║    POST /pos/deposit      - Receive deposit                  ║
║    POST /pos/CloseShift   - Close shift                      ║
║    POST /pos/EndOfDay     - End of day                       ║
║    POST /pos/HeartBeat    - Heartbeat check                  ║
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
        print(f"   Total shifts closed: {shifts_closed}")
        print(f"   Total end of days: {end_of_days}")


if __name__ == "__main__":
    main()
