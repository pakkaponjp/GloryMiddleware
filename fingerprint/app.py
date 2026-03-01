from flask import Flask, jsonify, make_response, request
from pyzkfp import ZKFP2
import time

app = Flask(__name__)

# เก็บ fingerprint ชั่วคราวใน memory
# ภายหลังค่อยย้ายไป database / Odoo model
fingerprint_memory = {}

MATCH_THRESHOLD = 50


def cors_json(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


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
        "registered_users": list(fingerprint_memory.keys())
    })


def get_scanner():
    z = ZKFP2()
    z.Init()

    count = z.GetDeviceCount()
    print(f"Device count: {count}")

    if count <= 0:
        raise Exception("No fingerprint scanner found.")

    z.OpenDevice(0)
    print("OpenDevice OK")

    z.DBInit()
    print("DBInit OK")

    # skip SetParameters for now
    print("SetParameters skipped for now")

    return z


def capture_fingerprint(timeout=20):
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
        print("Please place your finger on the scanner...")

        start = time.time()
        while time.time() - start < timeout:
            res = z.AcquireFingerprint()

            if not res:
                time.sleep(0.2)
                continue

            template = None
            image_data = None

            if isinstance(res, (tuple, list)) and len(res) >= 2:
                # Verified from your test:
                # res[0] = template (System.Byte[]) len=2048
                # res[1] = image bytes len=120000
                template = res[0]
                image_data = res[1]

                try:
                    print("Template len:", len(template) if template is not None else None)
                except Exception:
                    print("Template len: unknown")

                try:
                    print("Image len:", len(image_data) if image_data is not None else None)
                except Exception:
                    print("Image len: unknown")

            if template is not None:
                template_bytes = bytes(template)

                if len(template_bytes) != 2048:
                    raise ValueError(
                        f"Invalid template size: {len(template_bytes)}. Expected 2048 bytes."
                    )

                print("Captured template length:", len(template_bytes))

                return {
                    "template": template_bytes,
                    "image": image_data
                }

            print("Fingerprint detected but template not extracted yet.")
            time.sleep(0.2)

        raise TimeoutError("Timeout waiting for fingerprint.")

    finally:
        if z:
            try:
                z.CloseDevice()
                print("CloseDevice OK")
            except Exception as e:
                print("CloseDevice warning:", e)

            try:
                z.Terminate()
                print("Terminate OK")
            except Exception as e:
                print("Terminate warning:", e)


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
        print("DBMatch score:", score)
        return score
    finally:
        if z:
            try:
                z.CloseDevice()
                print("CloseDevice OK")
            except Exception as e:
                print("CloseDevice warning:", e)

            try:
                z.Terminate()
                print("Terminate OK")
            except Exception as e:
                print("Terminate warning:", e)


@app.route("/scan_fingerprint", methods=["GET"])
def scan_fingerprint():
    """
    Capture one fingerprint and return only metadata.
    Useful for quick scanner test.
    """
    try:
        result = capture_fingerprint(timeout=20)

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
        print("System Error:", e)
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/enroll_fingerprint", methods=["POST", "OPTIONS"])
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

        result = capture_fingerprint(timeout=20)

        fingerprint_memory[user_id] = {
            "template": result["template"],
            "created_at": time.time()
        }

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
        print("Enroll Error:", e)
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/verify_fingerprint", methods=["POST", "OPTIONS"])
def verify_fingerprint():
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

        stored = fingerprint_memory.get(user_id)
        if not stored:
            return cors_json({
                "status": "ERROR",
                "message": f"No fingerprint enrolled for user_id={user_id}"
            }, 404)

        fresh = capture_fingerprint(timeout=20)
        stored_template = stored["template"]
        fresh_template = fresh["template"]

        score = match_templates(stored_template, fresh_template)
        verified = score >= MATCH_THRESHOLD

        return cors_json({
            "status": "OK",
            "user_id": user_id,
            "verified": verified,
            "score": score,
            "threshold": MATCH_THRESHOLD
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        print("Verify Error:", e)
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/list_enrolled", methods=["GET"])
def list_enrolled():
    return cors_json({
        "status": "OK",
        "count": len(fingerprint_memory),
        "users": list(fingerprint_memory.keys())
    })


@app.route("/delete_enrolled/<user_id>", methods=["DELETE", "OPTIONS"])
def delete_enrolled(user_id):
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    if user_id in fingerprint_memory:
        del fingerprint_memory[user_id]
        return cors_json({
            "status": "OK",
            "message": f"Deleted enrolled fingerprint for user_id={user_id}"
        })

    return cors_json({
        "status": "ERROR",
        "message": f"user_id={user_id} not found"
    }, 404)


@app.route("/clear_enrolled", methods=["POST", "OPTIONS"])
def clear_enrolled():
    if request.method == "OPTIONS":
        return cors_json({"status": "OK"})

    fingerprint_memory.clear()
    return cors_json({
        "status": "OK",
        "message": "All enrolled fingerprints cleared."
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)