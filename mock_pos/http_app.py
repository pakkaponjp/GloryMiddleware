#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock POS Server - FlowCo Vendor
================================

FlowCo POS API Specification:
- Communication: RESTful API (HTTP)
- All endpoints prefixed with /POS/

Endpoints (Glory -> POS):
    POST /POS/Deposit       - Receive deposit from Glory
    
Endpoints (POS -> Glory):
    POST /POS/CloseShift    - Close shift (forward to Odoo)
    POST /POS/EndOfDay      - End of day (forward to Odoo)
    POST /POS/HeartBeat     - Heartbeat check

Request/Response Formats:
-------------------------

1. Deposit (Glory -> POS):
   Request:
   {
       "transaction_id": "TXN-20250926-12345",
       "staff_id": "CASHIER-0007",
       "amount": 4000
   }
   
   Response:
   {
       "transaction_id": "TXN-20250926-12345",
       "status": "OK",
       "discription": "Deposit Success",
       "time_stamp": "2025-09-26T17:45:00+07:00"
   }

2. CloseShift (POS -> Glory):
   Request:
   {
       "staff_id": "CASHIER-0007",
       "shift_number": "1",
       "timestamp": "2025-09-26T17:46:00+07:00"
   }
   
   Response:
   {
       "shift_id": "SHIFT-20251002-AM-01",
       "status": "OK",
       "total_cash_amount": 100000.00,
       "discription": "Deposit Success",
       "time_stamp": "2025-09-26T17:45:00+07:00"
   }

3. EndOfDay (POS -> Glory):
   Request:
   {
       "staff_id": "CASHIER-0007",
       "shift_number": "1",
       "timestamp": "2025-09-26T17:46:00+07:00"
   }
   
   Response:
   {
       "shift_id": "SHIFT-20251002-AM-01",
       "status": "OK",
       "total_cash_amount": 100000.00,
       "discription": "Deposit Success",
       "time_stamp": "2025-09-26T17:45:00+07:00"
   }

Usage:
    python mock_pos_flowco.py [port]
    
    Default port: 9002
    
Environment Variables:
    ODOO_BASE_URL   - Odoo URL for forwarding (default: http://127.0.0.1:8069)
    ODOO_TIMEOUT    - Request timeout in seconds (default: 5.0)
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime
import os
import sys
import requests

# =============================================================================
# CONFIGURATION
# =============================================================================

HOST = "0.0.0.0"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9002

# Odoo target for POS -> Glory forwarding
ODOO_BASE_URL = os.getenv("ODOO_BASE_URL", "http://127.0.0.1:8069").rstrip("/")
ODOO_TIMEOUT = float(os.getenv("ODOO_TIMEOUT", "5.0"))

# =============================================================================
# IN-MEMORY STORAGE (for testing)
# =============================================================================

transactions = []      # Store received deposits
shifts_closed = 0      # Counter for closed shifts
end_of_days = 0        # Counter for EOD operations
current_shift = "1"    # Current shift number


# =============================================================================
# FLOWCO MOCK POS HANDLER
# =============================================================================

class FlowCoPOSHandler(BaseHTTPRequestHandler):
    """
    HTTP Handler for FlowCo POS Mock Server
    
    Implements FlowCo-specific URL patterns and payload formats.
    """
    
    def _send_json_response(self, data, status=200):
        """Send JSON response with proper headers"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        response = json.dumps(data, ensure_ascii=False, indent=2)
        self.wfile.write(response.encode('utf-8'))
        print(f"📤 Response [{status}]: {json.dumps(data, ensure_ascii=False)}")
    
    def _read_json_body(self):
        """Read and parse JSON request body"""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > 0:
            body = self.rfile.read(content_length)
            try:
                return json.loads(body.decode('utf-8'))
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON parse error: {e}")
                return {}
        return {}
    
    def _forward_to_odoo(self, path: str, payload: dict):
        """
        Forward request to Odoo (Glory middleware)
        
        Args:
            path: API path (e.g., /POS/CloseShift)
            payload: Request payload
            
        Returns:
            tuple: (status_code, response_dict)
        """
        url = f"{ODOO_BASE_URL}/gas_station_cash{path}"
        print(f"➡️ Forwarding to Odoo: {url}")
        print(f"➡️ Payload: {json.dumps(payload, ensure_ascii=False)}")
        
        try:
            response = requests.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=ODOO_TIMEOUT
            )
            
            try:
                data = response.json()
                # Handle Odoo's JSON-RPC wrapper if present
                if 'result' in data:
                    data = data['result']
            except Exception:
                data = {"raw": response.text}
            
            print(f"⬅️ Odoo response [{response.status_code}]: {data}")
            return response.status_code, data
            
        except requests.exceptions.Timeout:
            print(f"❌ Odoo timeout after {ODOO_TIMEOUT}s")
            return 504, {
                "status": "ERROR",
                "discription": "Gateway Timeout - Odoo not responding",
                "time_stamp": datetime.now().isoformat(),
            }
        except requests.exceptions.ConnectionError as e:
            print(f"❌ Cannot connect to Odoo: {e}")
            return 503, {
                "status": "ERROR",
                "discription": f"Service Unavailable - Cannot reach Odoo",
                "time_stamp": datetime.now().isoformat(),
            }
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return 500, {
                "status": "ERROR",
                "discription": f"Internal Error: {str(e)}",
                "time_stamp": datetime.now().isoformat(),
            }
    
    def do_OPTIONS(self):
        """Handle CORS preflight"""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests - status endpoints"""
        path = self.path.lower()
        
        if path in ['/status', '/pos/status']:
            self._send_json_response({
                "server": "FlowCo Mock POS",
                "status": "OK",
                "statistics": {
                    "transactions_received": len(transactions),
                    "shifts_closed": shifts_closed,
                    "end_of_days": end_of_days,
                    "current_shift": current_shift,
                },
                "server_time": datetime.now().isoformat(),
            })
        elif path == '/transactions':
            # Debug endpoint to view all transactions
            self._send_json_response({
                "count": len(transactions),
                "transactions": transactions[-50:],  # Last 50
            })
        else:
            self._send_json_response({
                "server": "FlowCo Mock POS",
                "status": "OK",
                "message": "Use POST endpoints for operations",
            })
    
    def do_POST(self):
        """Handle POST requests - main API endpoints"""
        # Normalize path for case-insensitive matching
        path = self.path
        path_lower = path.lower()
        body = self._read_json_body()
        
        print(f"\n{'='*70}")
        print(f"📥 [{datetime.now().strftime('%H:%M:%S')}] {self.command} {path}")
        print(f"📥 Body: {json.dumps(body, ensure_ascii=False)}")
        print(f"{'='*70}")
        
        # Route to appropriate handler based on FlowCo URL patterns
        if path_lower == '/pos/deposit':
            self._handle_deposit(body)
        elif path_lower == '/pos/closeshift':
            self._handle_close_shift(body)
        elif path_lower == '/pos/endofday':  # Matches both EndOfDay and EndofDay
            self._handle_end_of_day(body)
        elif path_lower == '/pos/heartbeat':
            self._handle_heartbeat(body)
        else:
            print(f"❓ Unknown endpoint: {path}")
            self._send_json_response({
                "status": "ERROR",
                "discription": f"Unknown endpoint: {path}",
                "valid_endpoints": [
                    "/POS/Deposit",
                    "/POS/CloseShift", 
                    "/POS/EndOfDay",
                    "/POS/HeartBeat"
                ],
                "time_stamp": datetime.now().isoformat(),
            }, 404)
    
    # =========================================================================
    # ENDPOINT HANDLERS
    # =========================================================================
    
    def _handle_deposit(self, body):
        """
        Handle deposit request (Glory -> POS)
        
        This simulates the POS receiving a deposit notification from Glory.
        The POS stores the transaction and responds with OK.
        """
        global transactions
        
        transaction_id = body.get('transaction_id', f'TXN-{datetime.now().strftime("%Y%m%d%H%M%S")}')
        staff_id = body.get('staff_id', 'UNKNOWN')
        amount = body.get('amount', 0)
        
        # Validate required fields
        if not transaction_id:
            self._send_json_response({
                "transaction_id": transaction_id,
                "status": "ERROR",
                "discription": "Missing transaction_id",
                "time_stamp": datetime.now().isoformat(),
            }, 400)
            return
        
        if amount <= 0:
            self._send_json_response({
                "transaction_id": transaction_id,
                "status": "ERROR", 
                "discription": "Invalid amount (must be > 0)",
                "time_stamp": datetime.now().isoformat(),
            }, 400)
            return
        
        # Store transaction
        tx = {
            'transaction_id': transaction_id,
            'staff_id': staff_id,
            'amount': amount,
            'shift_number': current_shift,
            'received_at': datetime.now().isoformat(),
        }
        transactions.append(tx)
        
        print(f"✅ Deposit received:")
        print(f"   Transaction ID: {transaction_id}")
        print(f"   Staff ID: {staff_id}")
        print(f"   Amount: {amount:,.2f}")
        print(f"   Shift: {current_shift}")
        print(f"   Total transactions this session: {len(transactions)}")
        
        # FlowCo response format
        self._send_json_response({
            "transaction_id": transaction_id,
            "status": "OK",
            "discription": "Deposit Success",  # Note: FlowCo uses "discription"
            "time_stamp": datetime.now().isoformat(),
        })
    
    def _handle_close_shift(self, body):
        """
        Handle CloseShift request (POS -> Glory)
        
        FlowCo-specific: Requires shift_number and timestamp in request.
        This forwards the request to Odoo for processing.
        """
        global shifts_closed, current_shift
        
        staff_id = body.get('staff_id', 'UNKNOWN')
        shift_number = body.get('shift_number', current_shift)
        timestamp = body.get('timestamp', datetime.now().isoformat())
        
        print(f"🔄 CloseShift request:")
        print(f"   Staff ID: {staff_id}")
        print(f"   Shift Number: {shift_number}")
        print(f"   Timestamp: {timestamp}")
        
        # Calculate shift total from stored transactions
        shift_transactions = [t for t in transactions if t.get('shift_number') == shift_number]
        shift_total = sum(t.get('amount', 0) for t in shift_transactions)
        
        print(f"   Shift transactions: {len(shift_transactions)}")
        print(f"   Shift total: {shift_total:,.2f}")
        
        # Forward to Odoo
        status_code, odoo_response = self._forward_to_odoo('/POS/CloseShift', {
            'staff_id': staff_id,
            'shift_number': shift_number,
            'timestamp': timestamp,
        })
        
        if status_code == 200 and odoo_response.get('status') == 'OK':
            shifts_closed += 1
            # Increment shift number for next shift
            try:
                current_shift = str(int(current_shift) + 1)
            except:
                current_shift = "1"
            
            print(f"✅ Shift {shift_number} closed successfully")
            print(f"   Next shift will be: {current_shift}")
        
        # Return Odoo's response (or our calculated one if Odoo unavailable)
        if status_code >= 400:
            # Odoo unavailable - return mock response
            self._send_json_response({
                "shift_id": f"SHIFT-{datetime.now().strftime('%Y%m%d')}-{shift_number}",
                "status": "OK",
                "total_cash_amount": shift_total,
                "discription": "CloseShift Success (Odoo offline - local calculation)",
                "time_stamp": datetime.now().isoformat(),
            })
        else:
            self._send_json_response(odoo_response, status_code)
    
    def _handle_end_of_day(self, body):
        """
        Handle EndOfDay request (POS -> Glory)
        
        FlowCo-specific: Requires shift_number and timestamp in request.
        This forwards the request to Odoo for processing.
        """
        global end_of_days, transactions, current_shift
        
        staff_id = body.get('staff_id', 'UNKNOWN')
        shift_number = body.get('shift_number', current_shift)
        timestamp = body.get('timestamp', datetime.now().isoformat())
        
        print(f"🌙 EndOfDay request:")
        print(f"   Staff ID: {staff_id}")
        print(f"   Shift Number: {shift_number}")
        print(f"   Timestamp: {timestamp}")
        
        # Calculate day total from all transactions
        day_total = sum(t.get('amount', 0) for t in transactions)
        
        print(f"   Total transactions today: {len(transactions)}")
        print(f"   Day total: {day_total:,.2f}")
        
        # Forward to Odoo
        status_code, odoo_response = self._forward_to_odoo('/POS/EndOfDay', {
            'staff_id': staff_id,
            'shift_number': shift_number,
            'timestamp': timestamp,
        })
        
        if status_code == 200 and odoo_response.get('status') == 'OK':
            end_of_days += 1
            # Clear transactions for new day
            old_count = len(transactions)
            transactions = []
            current_shift = "1"
            
            print(f"✅ End of Day completed")
            print(f"   Cleared {old_count} transactions")
            print(f"   Reset shift to: {current_shift}")
        
        # Return Odoo's response (or our calculated one if Odoo unavailable)
        if status_code >= 400:
            # Odoo unavailable - return mock response
            self._send_json_response({
                "shift_id": f"EOD-{datetime.now().strftime('%Y%m%d')}",
                "status": "OK",
                "total_cash_amount": day_total,
                "discription": "EndOfDay Success (Odoo offline - local calculation)",
                "time_stamp": datetime.now().isoformat(),
            })
        else:
            self._send_json_response(odoo_response, status_code)
    
    def _handle_heartbeat(self, body):
        """
        Handle Heartbeat request (bidirectional)
        
        Used to verify connectivity between systems.
        """
        source_system = body.get('source_system', 'UNKNOWN')
        terminal_id = body.get('pos_terminal_id', 'TERM-01')
        
        print(f"💓 Heartbeat:")
        print(f"   Source: {source_system}")
        print(f"   Terminal: {terminal_id}")
        
        self._send_json_response({
            "status": "acknowledged",
            "pos_terminal_id": terminal_id,
            "timestamp": datetime.now().isoformat(),
        })
    
    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass


# =============================================================================
# MAIN
# =============================================================================

def main():
    banner = f"""
╔══════════════════════════════════════════════════════════════════════╗
║                    FLOWCO MOCK POS SERVER                            ║
╠══════════════════════════════════════════════════════════════════════╣
║  Host: {HOST:<15}                                               ║
║  Port: {PORT:<15}                                               ║
║  Odoo: {ODOO_BASE_URL:<30}                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  FlowCo API Endpoints:                                               ║
║                                                                      ║
║  Glory -> POS (this server receives):                                ║
║    POST /POS/Deposit      - Receive cash deposit                     ║
║                                                                      ║
║  POS -> Glory (this server forwards to Odoo):                        ║
║    POST /POS/CloseShift   - Close shift                              ║
║    POST /POS/EndOfDay     - End of day                               ║
║    POST /POS/HeartBeat    - Heartbeat                                ║
║                                                                      ║
║  Status/Debug:                                                       ║
║    GET  /status           - Server status                            ║
║    GET  /transactions     - View stored transactions                 ║
╚══════════════════════════════════════════════════════════════════════╝
    """
    print(banner)
    
    server = HTTPServer((HOST, PORT), FlowCoPOSHandler)
    print(f"🚀 FlowCo Mock POS Server started at http://{HOST}:{PORT}")
    print(f"   Press Ctrl+C to stop\n")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n")
        print("="*70)
        print("🛑 Server stopped")
        print(f"   Session Statistics:")
        print(f"   - Transactions received: {len(transactions)}")
        print(f"   - Shifts closed: {shifts_closed}")
        print(f"   - End of days: {end_of_days}")
        print("="*70)


if __name__ == "__main__":
    main()