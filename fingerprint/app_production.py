import os
import time
import json
import base64
import uuid
import threading
from functools import wraps
from flask import Flask, jsonify, make_response, request, g, has_request_context
from pyzkfp import ZKFP2

app = Flask(__name__)

# =========================================================
# Configuration
# =========================================================
PORT = int(os.getenv("FP_PORT", "5005"))
HOST = os.getenv("FP_HOST", "0.0.0.0")
DEBUG = os.getenv("FP_DEBUG", "true").lower() == "true"

# API key is OPTIONAL by default
REQUIRE_API_KEY = os.getenv("FP_REQUIRE_API_KEY", "false").lower() == "true"
API_KEY = os.getenv("FP_API_KEY", "")

MATCH_THRESHOLD = int(os.getenv("FP_MATCH_THRESHOLD", "50"))
CAPTURE_TIMEOUT = int(os.getenv("FP_CAPTURE_TIMEOUT", "20"))
CAPTURE_RETRIES = int(os.getenv("FP_CAPTURE_RETRIES", "3"))

# In-memory storage for test endpoints only
fingerprint_memory = {}

# Prevent concurrent access to scanner
scanner_lock = threading.Lock()


# =========================================================
# Logging
# =========================================================
def log_event(level, message, **kwargs):
    in_request = has_request_context()

    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "level": level,
        "message": message,
        "request_id": getattr(g, "request_id", None) if in_request else None,
        "path": request.path if in_request else None,
        "method": request.method if in_request else None,
    }
    payload.update(kwargs)
    print(json.dumps(payload, ensure_ascii=False, default=str))


# =========================================================
# Helpers
# =========================================================
def cors_json(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Request-ID"
    return resp


@app.before_request
def before_request():
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    log_event("INFO", "request_started")


@app.after_request
def after_request(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, X-Request-ID"
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    log_event(
        "INFO",
        "request_finished",
        status_code=response.status_code,
    )
    return response


def require_api_key_if_enabled(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not REQUIRE_API_KEY:
            return fn(*args, **kwargs)

        incoming_key = request.headers.get("X-API-Key", "").strip()
        if not API_KEY or incoming_key != API_KEY:
            return cors_json({
                "status": "ERROR",
                "message": "Unauthorized"
            }, 401)

        return fn(*args, **kwargs)
    return wrapper


def decode_template_b64(template_b64: str) -> bytes:
    try:
        raw = base64.b64decode(template_b64)
        if len(raw) != 2048:
            raise ValueError(f"Decoded template size is {len(raw)}, expected 2048")
        return raw
    except Exception as e:
        raise ValueError(f"Invalid template_b64: {e}")


def encode_template_b64(template_bytes: bytes) -> str:
    return base64.b64encode(template_bytes).decode("ascii")


def get_scanner():
    z = ZKFP2()
    z.Init()

    count = z.GetDeviceCount()
    log_event("INFO", "scanner_init", device_count=count)

    if count <= 0:
        raise Exception("No fingerprint scanner found.")

    z.OpenDevice(0)
    log_event("INFO", "scanner_opened")

    z.DBInit()
    log_event("INFO", "scanner_db_initialized")

    # Intentionally skipped due to wrapper incompatibility
    log_event("INFO", "scanner_set_parameters_skipped")

    return z


def close_scanner(z):
    if not z:
        return

    try:
        z.CloseDevice()
        log_event("INFO", "scanner_closed")
    except Exception as e:
        log_event("WARNING", "scanner_close_warning", error=str(e))

    try:
        z.Terminate()
        log_event("INFO", "scanner_terminated")
    except Exception as e:
        log_event("WARNING", "scanner_terminate_warning", error=str(e))


def capture_once(timeout=20):
    """
    Returns:
        {
            "template": bytes(2048),
            "image": bytes(...)
        }
    """
    z = None
    try:
        z = get_scanner()
        log_event("INFO", "capture_started", timeout=timeout)

        start = time.time()
        while time.time() - start < timeout:
            res = z.AcquireFingerprint()

            if not res:
                time.sleep(0.2)
                continue

            template = None
            image_data = None

            if isinstance(res, (tuple, list)) and len(res) >= 2:
                # Verified from real test:
                # res[0] = template (System.Byte[]) len=2048
                # res[1] = image bytes len=120000
                template = res[0]
                image_data = res[1]

            if template is not None:
                template_bytes = bytes(template)

                if len(template_bytes) != 2048:
                    raise ValueError(
                        f"Invalid template size: {len(template_bytes)}. Expected 2048 bytes."
                    )

                log_event(
                    "INFO",
                    "capture_success",
                    template_size=len(template_bytes),
                    image_size=(len(image_data) if image_data else None)
                )

                return {
                    "template": template_bytes,
                    "image": image_data
                }

            time.sleep(0.2)

        raise TimeoutError("Timeout waiting for fingerprint.")

    finally:
        close_scanner(z)


def capture_with_retry(timeout=CAPTURE_TIMEOUT, retries=CAPTURE_RETRIES):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            log_event("INFO", "capture_attempt", attempt=attempt, retries=retries)
            return capture_once(timeout=timeout)
        except Exception as e:
            last_error = e
            log_event("WARNING", "capture_attempt_failed", attempt=attempt, error=str(e))
            if attempt < retries:
                time.sleep(0.5)

    raise last_error


def match_templates(stored_template: bytes, fresh_template: bytes) -> int:
    if len(stored_template) != 2048 or len(fresh_template) != 2048:
        raise ValueError(
            f"Invalid template size for DBMatch: "
            f"stored={len(stored_template)}, fresh={len(fresh_template)}"
        )

    z = None
    try:
        z = get_scanner()
        score = z.DBMatch(stored_template, fresh_template)
        log_event("INFO", "dbmatch_success", score=score)
        return score
    finally:
        close_scanner(z)


def compare_templates(template1: bytes, template2: bytes, threshold: int = None):
    threshold = threshold if threshold is not None else MATCH_THRESHOLD
    score = match_templates(template1, template2)
    verified = score >= threshold
    return {
        "verified": verified,
        "score": score,
        "threshold": threshold
    }
    
    
def identify_from_candidates(fresh_template: bytes, candidates: list, threshold: int = None):
    threshold = threshold if threshold is not None else MATCH_THRESHOLD

    matches = []

    for candidate in candidates:
        employee_id = str(candidate.get("employee_id", "")).strip() or None
        employee_name = str(candidate.get("employee_name", "")).strip() or None
        template_b64 = candidate.get("template_b64")

        if not template_b64:
            continue

        try:
            candidate_template = decode_template_b64(template_b64)
            score = match_templates(candidate_template, fresh_template)

            if score >= threshold:
                matches.append({
                    "employee_id": employee_id,
                    "employee_name": employee_name,
                    "score": score
                })

        except Exception as e:
            log_event(
                "WARNING",
                "identify_candidate_failed",
                employee_id=employee_id,
                error=str(e)
            )

    # sort by highest score first
    matches.sort(key=lambda x: x["score"], reverse=True)

    if len(matches) == 0:
        return {
            "result": "NOT_FOUND",
            "matched_count": 0,
            "matches": []
        }

    if len(matches) == 1:
        return {
            "result": "SUCCESS",
            "matched_count": 1,
            "match": matches[0],
            "matches": matches
        }

    return {
        "result": "DUPLICATE",
        "matched_count": len(matches),
        "matches": matches,
        "message": "Multiple matched fingerprints found. Please scan again."
    }


def with_scanner_lock(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        acquired = scanner_lock.acquire(timeout=60)
        if not acquired:
            return cors_json({
                "status": "ERROR",
                "message": "Scanner is busy. Please try again."
            }, 423)

        try:
            return fn(*args, **kwargs)
        finally:
            scanner_lock.release()
    return wrapper


# =========================================================
# Error Handlers
# =========================================================
@app.errorhandler(404)
def not_found(_e):
    return cors_json({
        "status": "ERROR",
        "message": "Endpoint not found"
    }, 404)


@app.errorhandler(500)
def internal_error(e):
    log_event("ERROR", "internal_server_error", error=str(e))
    return cors_json({
        "status": "ERROR",
        "message": "Internal server error"
    }, 500)


# =========================================================
# Basic Endpoints
# =========================================================
@app.route("/", methods=["GET"])
def index():
    return cors_json({
        "status": "OK",
        "message": "Fingerprint service is running."
    })


@app.route("/health", methods=["GET"])
def health():
    return cors_json({
        "status": "OK",
        "message": "Fingerprint service is healthy.",
        "registered_count": len(fingerprint_memory),
        "registered_users": list(fingerprint_memory.keys()),
        "config": {
            "require_api_key": REQUIRE_API_KEY,
            "match_threshold": MATCH_THRESHOLD,
            "capture_timeout": CAPTURE_TIMEOUT,
            "capture_retries": CAPTURE_RETRIES,
        }
    })

@app.route("/api/v1/fingerprint/status", methods=["GET"])
def scanner_status():
    """
    Check if the physical fingerprint scanner is connected.
    Returns connected=true/false without opening the device for capture.
    """
    try:
        z = ZKFP2()
        z.Init()
        count = z.GetDeviceCount()
        connected = count > 0
        try:
            z.Terminate()
        except Exception:
            pass
        return cors_json({
            "connected": connected,
            "device_count": count,
            "busy": scanner_lock.locked(),
            "message": "Scanner ready." if connected else "Scanner not found."
        })
    except Exception as e:
        return cors_json({
            "connected": False,
            "device_count": 0,
            "busy": scanner_lock.locked(),
            "message": str(e)
        })


@app.route("/api/v1/fingerprint/config", methods=["GET"])
def get_config():
    return cors_json({
        "status": "OK",
        "require_api_key": REQUIRE_API_KEY,
        "match_threshold": MATCH_THRESHOLD,
        "capture_timeout": CAPTURE_TIMEOUT,
        "capture_retries": CAPTURE_RETRIES
    })


# =========================================================
# Legacy Test Endpoints (keep for test / logic)
# =========================================================
@app.route("/scan_fingerprint", methods=["GET", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def scan_fingerprint():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        result = capture_with_retry()

        return cors_json({
            "status": "OK",
            "message": "Fingerprint scanned successfully.",
            "template_size": len(result["template"]),
            "image_size": len(result["image"]) if result["image"] else None
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "scan_fingerprint_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/enroll_fingerprint", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def enroll_fingerprint():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id", "")).strip()

        if not user_id:
            return cors_json({
                "status": "ERROR",
                "message": "user_id is required."
            }, 400)

        result = capture_with_retry()

        fingerprint_memory[user_id] = {
            "template": result["template"],
            "created_at": time.time()
        }

        log_event("INFO", "enroll_success", user_id=user_id)

        return cors_json({
            "status": "OK",
            "message": f"Fingerprint enrolled successfully for user_id={user_id}",
            "user_id": user_id,
            "template_size": len(result["template"])
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "enroll_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/verify_fingerprint", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def verify_fingerprint():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id", "")).strip()
        threshold = int(data.get("threshold", MATCH_THRESHOLD))

        if not user_id:
            return cors_json({
                "status": "ERROR",
                "message": "user_id is required."
            }, 400)

        stored = fingerprint_memory.get(user_id)
        if not stored:
            return cors_json({
                "status": "ERROR",
                "message": f"No fingerprint enrolled for user_id={user_id}"
            }, 404)

        fresh = capture_with_retry()
        result = compare_templates(stored["template"], fresh["template"], threshold=threshold)

        log_event("INFO", "verify_success", user_id=user_id, score=result["score"], verified=result["verified"])

        return cors_json({
            "status": "OK",
            "user_id": user_id,
            "verified": result["verified"],
            "score": result["score"],
            "threshold": result["threshold"]
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "verify_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/list_enrolled", methods=["GET"])
@require_api_key_if_enabled
def list_enrolled():
    return cors_json({
        "status": "OK",
        "count": len(fingerprint_memory),
        "users": list(fingerprint_memory.keys())
    })


@app.route("/delete_enrolled/<user_id>", methods=["DELETE", "OPTIONS"])
@require_api_key_if_enabled
def delete_enrolled(user_id):
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    if user_id in fingerprint_memory:
        del fingerprint_memory[user_id]
        log_event("INFO", "delete_enrolled_success", user_id=user_id)
        return cors_json({
            "status": "OK",
            "message": f"Deleted enrolled fingerprint for user_id={user_id}"
        })

    return cors_json({
        "status": "ERROR",
        "message": f"user_id={user_id} not found"
    }, 404)


@app.route("/clear_enrolled", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
def clear_enrolled():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    fingerprint_memory.clear()
    log_event("INFO", "clear_enrolled_success")
    return cors_json({
        "status": "OK",
        "message": "All enrolled fingerprints cleared."
    })


# =========================================================
# New Odoo-Friendly Endpoints
# Odoo stores fingerprint template itself.
# =========================================================
@app.route("/api/v1/fingerprint/capture", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def api_capture_fingerprint():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        employee_id = str(data.get("employee_id", "")).strip() or None

        result = capture_with_retry()
        template_b64 = encode_template_b64(result["template"])

        log_event("INFO", "api_capture_success", employee_id=employee_id)

        return cors_json({
            "status": "OK",
            "message": "Fingerprint captured successfully.",
            "employee_id": employee_id,
            "template_b64": template_b64,
            "template_size": len(result["template"]),
            "image_size": len(result["image"]) if result["image"] else None
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "api_capture_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/api/v1/fingerprint/verify_template", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def api_verify_template():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        employee_id = str(data.get("employee_id", "")).strip() or None
        template_b64 = data.get("template_b64")
        threshold = int(data.get("threshold", MATCH_THRESHOLD))

        if not template_b64:
            return cors_json({
                "status": "ERROR",
                "message": "template_b64 is required."
            }, 400)

        stored_template = decode_template_b64(template_b64)
        fresh = capture_with_retry()

        result = compare_templates(stored_template, fresh["template"], threshold=threshold)

        log_event(
            "INFO",
            "api_verify_template_success",
            employee_id=employee_id,
            score=result["score"],
            verified=result["verified"]
        )

        return cors_json({
            "status": "OK",
            "employee_id": employee_id,
            "verified": result["verified"],
            "score": result["score"],
            "threshold": result["threshold"]
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "api_verify_template_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/api/v1/fingerprint/compare_templates", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
def api_compare_templates():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        template1_b64 = data.get("template1_b64")
        template2_b64 = data.get("template2_b64")
        threshold = int(data.get("threshold", MATCH_THRESHOLD))

        if not template1_b64 or not template2_b64:
            return cors_json({
                "status": "ERROR",
                "message": "template1_b64 and template2_b64 are required."
            }, 400)

        template1 = decode_template_b64(template1_b64)
        template2 = decode_template_b64(template2_b64)

        with scanner_lock:
            result = compare_templates(template1, template2, threshold=threshold)

        log_event("INFO", "api_compare_templates_success", score=result["score"], verified=result["verified"])

        return cors_json({
            "status": "OK",
            "verified": result["verified"],
            "score": result["score"],
            "threshold": result["threshold"]
        }, 200)

    except Exception as e:
        log_event("ERROR", "api_compare_templates_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/api/v1/fingerprint/identify", methods=["POST", "OPTIONS"])
@require_api_key_if_enabled
@with_scanner_lock
def api_identify_fingerprint():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    try:
        data = request.get_json(silent=True) or {}
        threshold = int(data.get("threshold", MATCH_THRESHOLD))
        candidates = data.get("candidates", [])

        if not isinstance(candidates, list) or len(candidates) == 0:
            return cors_json({
                "status": "ERROR",
                "message": "candidates must be a non-empty list."
            }, 400)

        fresh = capture_with_retry()
        identify_result = identify_from_candidates(
            fresh_template=fresh["template"],
            candidates=candidates,
            threshold=threshold
        )

        log_event(
            "INFO",
            "api_identify_success",
            result=identify_result["result"],
            matched_count=identify_result["matched_count"],
            threshold=threshold
        )

        response = {
            "status": "OK",
            "result": identify_result["result"],
            "matched_count": identify_result["matched_count"],
            "threshold": threshold
        }

        if identify_result["result"] == "SUCCESS":
            response["match"] = identify_result["match"]
            response["matches"] = identify_result["matches"]

        elif identify_result["result"] == "DUPLICATE":
            response["matches"] = identify_result["matches"]
            response["message"] = identify_result["message"]

        else:
            response["matches"] = []

        return cors_json(response, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        log_event("ERROR", "api_identify_failed", error=str(e))
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)

if __name__ == "__main__":
    log_event(
        "INFO",
        "service_starting",
        host=HOST,
        port=PORT,
        debug=DEBUG,
        require_api_key=REQUIRE_API_KEY,
        match_threshold=MATCH_THRESHOLD,
        capture_timeout=CAPTURE_TIMEOUT,
        capture_retries=CAPTURE_RETRIES
    )
    app.run(host=HOST, port=PORT, debug=DEBUG)