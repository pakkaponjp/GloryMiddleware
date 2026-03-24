#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FirstPro POS Mock Console + HTTP Server

HTTP Server (background):
    รับ request จาก Odoo เช่น deposit callback
    POST /deposit      - รับ deposit จาก Odoo
    POST /HeartBeat    - Heartbeat
    GET  /status       - Server status

Interactive Console (foreground):
    เมนูส่ง CloseShift / EndOfDay ไปยัง Odoo

Usage:
    python app.py [http_port]
    Default HTTP port: 9003

Environment variables:
    ODOO_BASE_URL   Odoo URL (default: http://127.0.0.1:8069)
    ODOO_TIMEOUT    Request timeout in seconds (default: 120)
"""

import json
import os
import sys
import threading
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

# ──────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────
ODOO_BASE_URL = os.getenv("ODOO_BASE_URL", "http://127.0.0.1:8069").rstrip("/")
ODOO_TIMEOUT  = float(os.getenv("ODOO_TIMEOUT", "120"))
HTTP_HOST     = "0.0.0.0"
HTTP_PORT     = int(sys.argv[1]) if len(sys.argv) > 1 else 9003

# Shared state
transactions  = []
shifts_closed = 0
end_of_days   = 0
_print_lock   = threading.Lock()
_reprint_menu = threading.Event()  # set by HTTP thread → main loop reprints menu

# ──────────────────────────────────────────────────────────
# Thread-safe print
# ──────────────────────────────────────────────────────────
def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

# ──────────────────────────────────────────────────────────
# HTTP Server — รับ request จาก Odoo
# ──────────────────────────────────────────────────────────
class MockPOSHandler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        tprint(f"📤 TX [{status}]: {data}")
        _reprint_menu.set()  # signal main loop to reprint menu

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            try:
                return json.loads(self.rfile.read(length).decode())
            except Exception:
                return {}
        return {}

    def do_POST(self):
        global transactions
        path = self.path.lower().split("?")[0]
        body = self._read_json()

        tprint(f"\n{'='*60}")
        tprint(f"📥 RX [POST] {self.path}")
        tprint(f"📥 Body: {body}")

        if path in ("/deposit", "/pos/deposit"):
            tx_id    = body.get("transaction_id", "UNKNOWN")
            staff_id = body.get("staff_id", "UNKNOWN")
            amount   = body.get("amount", 0)
            type_id  = body.get("type_id", "-")
            pos_id   = body.get("pos_id", "-")

            transactions.append({
                "transaction_id": tx_id,
                "staff_id": staff_id,
                "amount": amount,
                "type_id": type_id,
                "pos_id": pos_id,
                "timestamp": datetime.now().isoformat(),
            })
            tprint(f"✅ Deposit: tx={tx_id}, staff={staff_id}, amount={amount}, "
                   f"type={type_id}, pos={pos_id}")
            tprint(f"   Total transactions: {len(transactions)}")

            self._send_json({
                "transaction_id": tx_id,
                "status": "OK",
                "discription": "Deposit Success",
                "description": "Deposit Success",
                "time_stamp": datetime.now().isoformat(),
            })

        elif path in ("/heartbeat", "/pos/heartbeat"):
            tprint(f"💓 Heartbeat from {body.get('source_system', 'UNKNOWN')}")
            self._send_json({
                "status": "acknowledged",
                "timestamp": datetime.now().isoformat(),
            })

        else:
            tprint(f"❓ Unknown endpoint: {self.path}")
            self._send_json({"status": "ERROR", "description": f"Unknown: {self.path}"}, 404)

    def do_GET(self):
        if self.path == "/status":
            self._send_json({
                "status": "OK",
                "transactions_received": len(transactions),
                "shifts_closed": shifts_closed,
                "end_of_days": end_of_days,
                "odoo_target": ODOO_BASE_URL,
                "server_time": datetime.now().isoformat(),
            })
        else:
            self._send_json({"status": "OK", "message": "Mock POS Server"})

    def log_message(self, format, *args):
        pass  # suppress default logs


def start_http_server():
    server = HTTPServer((HTTP_HOST, HTTP_PORT), MockPOSHandler)
    tprint(f"🌐 HTTP server listening on {HTTP_HOST}:{HTTP_PORT}")
    server.serve_forever()


# ──────────────────────────────────────────────────────────
# Console Helpers
# ──────────────────────────────────────────────────────────
def print_separator(char="─", width=60):
    tprint(char * width)

def print_header(title):
    print_separator("═")
    tprint(f"  {title}")
    print_separator("═")

def print_section(title):
    tprint()
    print_separator()
    tprint(f"  {title}")
    print_separator()

def ask(prompt, default=None):
    display = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    try:
        value = input(display).strip()
        return value if value else (str(default) if default is not None else "")
    except EOFError:
        return str(default) if default is not None else ""

def ask_float(prompt, default=0.0):
    while True:
        raw = ask(prompt, default)
        try:
            return float(raw)
        except ValueError:
            tprint("  ⚠️  กรุณากรอกตัวเลข (เช่น 0, 1500.50)")

def ask_int(prompt, default=1):
    while True:
        raw = ask(prompt, default)
        try:
            return int(raw)
        except ValueError:
            tprint("  ⚠️  กรุณากรอกตัวเลขจำนวนเต็ม (เช่น 1, 2)")

def send_to_odoo(path, payload):
    url = f"{ODOO_BASE_URL}{path}"
    tprint(f"\n  ➡️  Forwarding to Odoo: {url}")
    tprint(f"  ➡️  Payload: {payload}")
    try:
        r = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=ODOO_TIMEOUT,
        )
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
        tprint(f"  ⬅️  Odoo response [{r.status_code}]: {data}")
        return r.status_code, data
    except requests.Timeout:
        tprint(f"  ⏰ Timeout ({ODOO_TIMEOUT}s)")
        return 504, {"status": "ERROR", "description": "Request timed out"}
    except requests.ConnectionError as e:
        tprint(f"  ❌ Cannot connect to Odoo: {e}")
        return 503, {"status": "ERROR", "description": str(e)}
    except Exception as e:
        tprint(f"  ❌ Unexpected error: {e}")
        return 500, {"status": "ERROR", "description": str(e)}

def print_response(status_code, data):
    ok   = status_code == 200 and data.get("status") == "OK"
    icon = "✅" if ok else "❌"
    tprint(f"\n  {icon} Response [{status_code}]:")
    tprint(f"  {json.dumps(data, ensure_ascii=False, indent=4)}")

# ──────────────────────────────────────────────────────────
# Console Handlers
# ──────────────────────────────────────────────────────────
def handle_close_shift():
    global shifts_closed
    print_section("Close Shift — FirstPro")
    tprint("  กรอกข้อมูลสำหรับ CloseShift (กด Enter เพื่อใช้ค่า default)")
    tprint()

    staff_id       = ask("  Staff ID", default="4401")
    shiftid        = ask_int("  Shift Number", default=1)
    product_amount = ask_float("  Product Amount (engine oil)", default=0.0)

    payload = {
        "staff_id":       staff_id,
        "shiftid":        shiftid,
        "product_amount": product_amount,
    }

    tprint(f"\n🔄 [FirstPro] CloseShift: staff={staff_id} "
           f"shiftid={shiftid} product_amount={product_amount}")
    tprint(f"   ℹ️  product_amount = engine oil reconcile amount → Odoo")

    confirm = ask("\n  ยืนยันส่ง CloseShift? (y/n)", default="y").lower()
    if confirm not in ("y", "yes", ""):
        tprint("  ยกเลิก")
        return

    shifts_closed += 1
    status, data = send_to_odoo("/CloseShift", payload)
    print_response(status, data)


def handle_end_of_day():
    global end_of_days
    print_section("End of Day — FirstPro")
    tprint("  กรอกข้อมูลสำหรับ EndOfDay (กด Enter เพื่อใช้ค่า default)")
    tprint()

    staff_id       = ask("  Staff ID", default="4401")
    shiftid        = ask_int("  Shift Number", default=1)
    product_amount = ask_float("  Product Amount (engine oil)", default=0.0)

    payload = {
        "staff_id":       staff_id,
        "shiftid":        shiftid,
        "product_amount": product_amount,
    }

    tprint(f"\n🔄 [FirstPro] EndOfDay: staff={staff_id} "
           f"shiftid={shiftid} product_amount={product_amount}")
    tprint(f"   ℹ️  product_amount = engine oil reconcile amount → Odoo")

    confirm = ask("\n  ยืนยันส่ง EndOfDay? (y/n)", default="y").lower()
    if confirm not in ("y", "yes", ""):
        tprint("  ยกเลิก")
        return

    end_of_days += 1
    status, data = send_to_odoo("/EndOfDay", payload)
    print_response(status, data)


def handle_heartbeat():
    print_section("Heartbeat")
    payload = {
        "source_system":   "MockPOS",
        "pos_terminal_id": "TERM-01",
        "timestamp":       datetime.now().isoformat(),
    }
    status, data = send_to_odoo("/HeartBeat", payload)
    print_response(status, data)


def show_status():
    print_section("Status")
    tprint(f"  Odoo URL     : {ODOO_BASE_URL}")
    tprint(f"  Timeout      : {ODOO_TIMEOUT}s")
    tprint(f"  HTTP port    : {HTTP_PORT}")
    tprint(f"  Transactions : {len(transactions)}")
    tprint(f"  Shifts closed: {shifts_closed}")
    tprint(f"  End of days  : {end_of_days}")
    tprint(f"  Time         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    tprint()
    try:
        r = requests.get(f"{ODOO_BASE_URL}/web/health", timeout=5)
        tprint(f"  Odoo ping    : ✅ OK ({r.status_code})")
    except Exception as e:
        tprint(f"  Odoo ping    : ❌ {e}")


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────
MENU = """
  ┌─────────────────────────────────┐
  │   FirstPro POS Mock Console     │
  ├─────────────────────────────────┤
  │  1. Close Shift                 │
  │  2. End of Day                  │
  │  3. Heartbeat                   │
  │  4. Status                      │
  │  0. Exit  (หรือ Ctrl+C)          │
  └─────────────────────────────────┘
"""

def main():
    print_header("FirstPro POS Mock")
    tprint(f"  Odoo URL  : {ODOO_BASE_URL}")
    tprint(f"  HTTP port : {HTTP_PORT}  (รับ deposit/heartbeat จาก Odoo)")
    tprint(f"  Timeout   : {ODOO_TIMEOUT}s")
    tprint()
    tprint("  กด Ctrl+C เพื่อออกจากโปรแกรมได้ตลอดเวลา")

    # Start HTTP server in background thread
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()

    while True:
        try:
            tprint(MENU)
            _reprint_menu.clear()
            choice = ask("  เลือก", default="").strip()

            # If HTTP thread printed something while user was typing, reprint menu
            if _reprint_menu.is_set():
                _reprint_menu.clear()
                continue

            if choice == "1":
                handle_close_shift()
            elif choice == "2":
                handle_end_of_day()
            elif choice == "3":
                handle_heartbeat()
            elif choice == "4":
                show_status()
            elif choice in ("0", "q", "exit", "quit"):
                tprint("\n  👋 ออกจากโปรแกรม\n")
                sys.exit(0)
            elif choice == "":
                continue
            else:
                tprint(f"  ⚠️  ไม่รู้จักคำสั่ง '{choice}' กรุณาเลือก 0–4")

        except KeyboardInterrupt:
            tprint(f"\n\n  👋 ออกจากโปรแกรม (Ctrl+C)")
            tprint(f"     Transactions : {len(transactions)}")
            tprint(f"     Shifts closed: {shifts_closed}")
            tprint(f"     End of days  : {end_of_days}\n")
            sys.exit(0)


if __name__ == "__main__":
    main()
