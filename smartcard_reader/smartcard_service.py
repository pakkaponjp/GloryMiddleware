# -*- coding: utf-8 -*-
"""
smartcard_service.py — Flask service สำหรับ FEITIAN R502 CL (CCID Smartcard Reader)
                        อ่าน card UID ผ่าน PC/SC (WinSCard) บน Windows

Install:
    pip install flask pyscard

Run:
    python smartcard_service.py

Endpoints:
    GET  /api/v1/smartcard/status   — health check + reader status
    POST /api/v1/smartcard/read     — blocking read UID (timeout configurable)
    POST /api/v1/smartcard/abort    — cancel ongoing read
"""

import logging
import threading
import time
from flask import Flask, jsonify, request

# pyscard — PC/SC wrapper (pip install pyscard)
from smartcard.System import readers
from smartcard.util import toHexString
from smartcard.Exceptions import NoCardException, CardConnectionException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
READER_NAME_HINT = "FEITIAN"        # substring match — ถ้าเป็น None จะใช้ reader ตัวแรก
DEFAULT_TIMEOUT  = 30               # วินาที — ถ้า frontend ไม่ส่ง timeout มา
POLL_INTERVAL    = 0.3              # วินาที — ความถี่ในการ poll reader

# GET UID APDU command (ISO 14443 — ใช้ได้กับ MIFARE, Ultralight, ISO14443 A/B)
# FF CA 00 00 00 = Get Data (UID)
APDU_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]

# ---------------------------------------------------------------------------
# Abort flag — shared between read thread and abort endpoint
# ---------------------------------------------------------------------------
_abort_event = threading.Event()
_read_lock   = threading.Lock()     # ป้องกัน concurrent read requests


# ---------------------------------------------------------------------------
# Helper: find target reader
# ---------------------------------------------------------------------------
def _find_reader():
    """
    Return the first reader whose name contains READER_NAME_HINT (case-insensitive).
    If READER_NAME_HINT is None or no match, return the first available reader.
    Returns None if no readers found.
    """
    available = readers()
    if not available:
        return None

    if READER_NAME_HINT:
        hint = READER_NAME_HINT.lower()
        for r in available:
            if hint in str(r).lower():
                logger.info("Using reader: %s", r)
                return r
        logger.warning(
            "Hint '%s' not matched. Available: %s. Using first reader.",
            READER_NAME_HINT, [str(r) for r in available]
        )

    return available[0]


def _read_uid_once(reader):
    """
    Try to read UID from a card on the reader.

    Returns:
        str: UID hex string (e.g. "A1 B2 C3 D4") on success
        None: no card present or error
    """
    try:
        conn = reader.createConnection()
        conn.connect()
        data, sw1, sw2 = conn.transmit(APDU_GET_UID)
        conn.disconnect()

        if sw1 == 0x90 and sw2 == 0x00 and data:
            uid = toHexString(data).replace(" ", "").upper()
            logger.info("Card UID read: %s", uid)
            return uid
        else:
            logger.debug("APDU response: SW1=%02X SW2=%02X data=%s", sw1, sw2, data)
            return None

    except NoCardException:
        return None
    except CardConnectionException:
        return None
    except Exception as e:
        logger.debug("UID read error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/v1/smartcard/status", methods=["GET", "POST"])
def status():
    """
    Health check + reader availability.

    Response:
        {
            "connected": true/false,
            "reader":    "FEITIAN R502 CL 0",   // reader name if found
            "message":   "Ready"
        }
    """
    reader = _find_reader()
    if reader is None:
        return jsonify({
            "connected": False,
            "reader":    None,
            "message":   "No smartcard reader found",
        })

    return jsonify({
        "connected": True,
        "reader":    str(reader),
        "message":   "Ready",
    })


@app.route("/api/v1/smartcard/read", methods=["POST"])
def read_card():
    """
    Blocking read — polls until a card is presented or timeout/abort.

    Body (JSON, all optional):
        { "timeout": 30 }   // seconds

    Response (success):
        { "status": "OK",      "uid": "A1B2C3D4" }

    Response (timeout):
        { "status": "TIMEOUT", "uid": null }

    Response (aborted):
        { "status": "ABORTED", "uid": null }

    Response (no reader):
        { "status": "ERROR",   "message": "No reader found" }
    """
    if not _read_lock.acquire(blocking=False):
        return jsonify({"status": "ERROR", "message": "Read already in progress"}), 409

    try:
        body    = request.get_json(silent=True) or {}
        timeout = float(body.get("timeout", DEFAULT_TIMEOUT))

        _abort_event.clear()

        reader = _find_reader()
        if reader is None:
            return jsonify({"status": "ERROR", "message": "No smartcard reader found"})

        logger.info("Waiting for card (timeout=%ss, reader=%s)...", timeout, reader)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if _abort_event.is_set():
                logger.info("Card read aborted")
                return jsonify({"status": "ABORTED", "uid": None})

            uid = _read_uid_once(reader)
            if uid:
                return jsonify({"status": "OK", "uid": uid})

            time.sleep(POLL_INTERVAL)

        logger.info("Card read timed out after %ss", timeout)
        return jsonify({"status": "TIMEOUT", "uid": None})

    finally:
        _read_lock.release()


@app.route("/api/v1/smartcard/abort", methods=["POST"])
def abort():
    """
    Cancel an ongoing /read request.
    Safe to call even if no read is in progress.
    """
    _abort_event.set()
    logger.info("Abort signal sent")
    return jsonify({"status": "OK", "message": "Abort signal sent"})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Smartcard Service starting on port 5007...")
    logger.info("APDU GET UID: %s", APDU_GET_UID)

    # Quick self-check
    r = _find_reader()
    if r:
        logger.info("Reader found: %s", r)
    else:
        logger.warning("No reader found on startup — will retry on each request")

    app.run(host="0.0.0.0", port=5007, debug=False)