# -*- coding: utf-8 -*-
"""
test_card_reader.py — ทดสอบ FEITIAN R502 CL (CCID Smartcard Reader)
                       แสดง UID ในทุก format เพื่อ compare กับ FlowCo / FirstPro

Install:
    pip install pyscard

Run:
    python test_card_reader.py

กด Ctrl+C เพื่อหยุด
"""

import sys
import time

try:
    from smartcard.System import readers
    from smartcard.util import toHexString
    from smartcard.Exceptions import NoCardException, CardConnectionException
except ImportError:
    print("[ERROR] pyscard not installed. Run: pip install pyscard")
    sys.exit(1)

# ---------------------------------------------------------------------------
# APDU Commands
# ---------------------------------------------------------------------------
APDU_GET_UID       = [0xFF, 0xCA, 0x00, 0x00, 0x00]   # ISO 14443 — GET UID
APDU_GET_ATS       = [0xFF, 0xCA, 0x01, 0x00, 0x00]   # GET ATS (card info)
APDU_GET_DATA_ALL  = [0xFF, 0xCA, 0x00, 0x00, 0x04]   # GET UID max 4 bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_reader(hint="FEITIAN"):
    """Find reader by name hint, fallback to first available."""
    available = readers()
    if not available:
        return None, available
    if hint:
        for r in available:
            if hint.lower() in str(r).lower():
                return r, available
    return available[0], available


def bytes_to_all_formats(data: list) -> dict:
    """
    Convert raw byte list to every format POS systems might use.
    Returns dict of format_name → value string.
    """
    if not data:
        return {}

    raw_bytes = bytes(data)

    # --- HEX formats ---
    hex_upper      = raw_bytes.hex().upper()                         # A1B2C3D4
    hex_upper_sp   = " ".join(f"{b:02X}" for b in raw_bytes)        # A1 B2 C3 D4
    hex_lower      = raw_bytes.hex()                                 # a1b2c3d4
    hex_colon      = ":".join(f"{b:02X}" for b in raw_bytes)        # A1:B2:C3:D4
    hex_0x         = "0x" + hex_upper                               # 0xA1B2C3D4

    # --- HEX reversed (LSB first — บาง reader/POS ส่งกลับ) ---
    rev_bytes      = raw_bytes[::-1]
    hex_rev        = rev_bytes.hex().upper()                         # D4C3B2A1
    hex_rev_sp     = " ".join(f"{b:02X}" for b in rev_bytes)        # D4 C3 B2 A1

    # --- Decimal formats ---
    dec_be         = int.from_bytes(raw_bytes, byteorder='big')      # Big-endian DEC
    dec_le         = int.from_bytes(raw_bytes, byteorder='little')   # Little-endian DEC
    dec_be_10      = str(dec_be).zfill(10)                           # 10-digit DEC (FirstPro style)
    dec_le_10      = str(dec_le).zfill(10)                           # 10-digit DEC reversed

    # --- Wiegand-style (26-bit / 34-bit) — บาง access control ใช้ ---
    # 26-bit Wiegand: facility code (byte1) + card number (byte2+3)
    wiegand_26 = None
    if len(raw_bytes) >= 3:
        facility = raw_bytes[0]
        card_num = int.from_bytes(raw_bytes[1:3], 'big')
        wiegand_26 = f"FC={facility:03d} CN={card_num:05d}"

    return {
        "raw_bytes_dec":     [b for b in raw_bytes],
        "raw_bytes_hex":     [f"{b:02X}" for b in raw_bytes],
        "byte_count":        len(raw_bytes),

        # HEX
        "HEX (no space)":    hex_upper,
        "HEX (space)":       hex_upper_sp,
        "HEX (lowercase)":   hex_lower,
        "HEX (colon)":       hex_colon,
        "HEX (0x prefix)":   hex_0x,

        # HEX reversed
        "HEX reversed":      hex_rev,
        "HEX reversed(sp)":  hex_rev_sp,

        # Decimal
        "DEC (big-endian)":  str(dec_be),
        "DEC (little-end)":  str(dec_le),
        "DEC 10-digit BE":   dec_be_10,    # ← FirstPro likely uses this
        "DEC 10-digit LE":   dec_le_10,    # ← or this

        # Wiegand
        "Wiegand-26":        wiegand_26 or "N/A (need ≥3 bytes)",
    }


def transmit_apdu(conn, apdu: list, label: str):
    """Send APDU and return (data, sw1, sw2). Prints result."""
    try:
        data, sw1, sw2 = conn.transmit(apdu)
        status = "OK" if (sw1 == 0x90 and sw2 == 0x00) else f"SW={sw1:02X}{sw2:02X}"
        print(f"  [{label}] {status}  data={[f'{b:02X}' for b in data]}")
        return data, sw1, sw2
    except Exception as e:
        print(f"  [{label}] ERROR: {e}")
        return [], 0x00, 0x00


def print_separator(char="─", width=60):
    print(char * width)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print()
    print_separator("═")
    print("  FEITIAN R502 CL — Card UID Format Tester")
    print_separator("═")

    # List all readers
    available = readers()
    if not available:
        print("\n[ERROR] No smartcard readers found.")
        print("  - Check USB connection")
        print("  - Install FEITIAN driver")
        print("  - Run as Administrator if needed")
        sys.exit(1)

    print(f"\nAvailable readers ({len(available)}):")
    for i, r in enumerate(available):
        print(f"  [{i}] {r}")

    reader, _ = find_reader("FEITIAN")
    print(f"\nUsing: {reader}")
    print("\nReady — แตะบัตรเพื่ออ่าน UID (Ctrl+C เพื่อหยุด)\n")
    print_separator()

    last_uid = None
    read_count = 0

    try:
        while True:
            try:
                conn = reader.createConnection()
                conn.connect()

                read_count += 1
                print(f"\n{'━'*60}")
                print(f"  การอ่านครั้งที่ {read_count}  —  {time.strftime('%H:%M:%S')}")
                print(f"{'━'*60}")

                # --- APDU 1: GET UID (standard) ---
                data_uid, sw1, sw2 = transmit_apdu(conn, APDU_GET_UID, "FF CA 00 00 00 (GET UID)")

                # --- APDU 2: GET UID max 4 bytes ---
                data_4, _, _ = transmit_apdu(conn, APDU_GET_DATA_ALL, "FF CA 00 00 04 (GET UID 4B)")

                # --- APDU 3: GET ATS (card type info) ---
                data_ats, _, _ = transmit_apdu(conn, APDU_GET_ATS, "FF CA 01 00 00 (GET ATS)")

                conn.disconnect()

                # Use best UID data available
                uid_data = data_uid if (sw1 == 0x90 and data_uid) else data_4

                if not uid_data:
                    print("\n  [WARN] No UID data returned from card")
                    time.sleep(1)
                    continue

                uid_hex = "".join(f"{b:02X}" for b in uid_data)

                # Skip if same card still on reader
                if uid_hex == last_uid:
                    time.sleep(0.5)
                    continue

                last_uid = uid_hex

                # --- Print all formats ---
                formats = bytes_to_all_formats(uid_data)
                print(f"\n  Raw bytes : {formats['raw_bytes_hex']}")
                print(f"  Byte count: {formats['byte_count']}")
                print()

                # Group output
                groups = [
                    ("── HEX Formats ──────────────────────────────────────", [
                        "HEX (no space)",
                        "HEX (space)",
                        "HEX (lowercase)",
                        "HEX (colon)",
                        "HEX (0x prefix)",
                        "HEX reversed",
                        "HEX reversed(sp)",
                    ]),
                    ("── Decimal Formats ───────────────────────────────────", [
                        "DEC (big-endian)",
                        "DEC (little-end)",
                        "DEC 10-digit BE",   # FirstPro likely
                        "DEC 10-digit LE",
                    ]),
                    ("── Other ─────────────────────────────────────────────", [
                        "Wiegand-26",
                    ]),
                ]

                for title, keys in groups:
                    print(f"  {title}")
                    for k in keys:
                        v = formats.get(k, "N/A")
                        arrow = ""
                        if k == "HEX (no space)":
                            arrow = "  ← FlowCo (likely)"
                        elif k == "DEC 10-digit BE":
                            arrow = "  ← FirstPro (likely)"
                        print(f"    {k:<22}: {v}{arrow}")
                    print()

                print("  แตะบัตรใหม่ หรือ Ctrl+C เพื่อหยุด")
                print_separator()

                # Wait for card removal before next read
                time.sleep(1.5)
                last_uid = None  # reset so same card can be read again next tap

            except NoCardException:
                # No card — poll quietly
                last_uid = None
                time.sleep(0.3)
            except CardConnectionException:
                last_uid = None
                time.sleep(0.3)
            except Exception as e:
                print(f"\n[ERROR] {e}")
                time.sleep(1)

    except KeyboardInterrupt:
        print(f"\n\nหยุดทำงาน — อ่านบัตรทั้งหมด {read_count} ครั้ง")


if __name__ == "__main__":
    main()