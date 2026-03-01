from flask import Flask, jsonify, make_response, request
from pyzkfp import ZKFP2
import base64
import time

app = Flask(__name__)

# เก็บ fingerprint ชั่วคราวใน memory
# ภายหลังค่อยเปลี่ยนเป็นเก็บใน Odoo model / database
fingerprint_memory = {
    # "staff_001": {
    #     "template_b64": "....",
    #     "created_at": 1234567890
    # }
}


def cors_json(payload, status=200):
    resp = make_response(jsonify(payload), status)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def get_scanner():
    z = ZKFP2()
    z.Init()

    if z.GetDeviceCount() <= 0:
        raise Exception("Scanner not found.")

    z.OpenDevice(0)

    try:
        z.SetParameters(1, 1)
    except Exception:
        pass

    try:
        z.DBInit()
    except Exception:
        pass

    return z


def capture_template(timeout=30):
    """
    อ่าน fingerprint template จาก scanner แล้วคืนค่าเป็น bytes
    """
    z = None
    try:
        z = get_scanner()

        print("--- Scanner Ready (PRESS FIRMLY) ---")
        start_time = time.time()

        while time.time() - start_time < timeout:
            res = z.AcquireFingerprint()

            if res:
                quality = 0
                if hasattr(z, "GetLastImageQuality"):
                    try:
                        quality = z.GetLastImageQuality()
                    except Exception:
                        quality = 0

                print(f"Signal detected. Quality: {quality}")

                template = None

                # บาง version มี ExtractFromFingerprint
                if hasattr(z, "ExtractFromFingerprint"):
                    try:
                        template = z.ExtractFromFingerprint()
                    except Exception:
                        template = None

                # fallback: บาง version ของ pyzkfp อาจคืน tuple/list จาก AcquireFingerprint
                if not template:
                    if isinstance(res, (tuple, list)) and len(res) >= 2:
                        possible_template = res[1]
                        if possible_template:
                            template = possible_template

                if template and len(template) > 50:
                    print(f"SUCCESS! Template captured. Len={len(template)}")
                    return bytes(template)

                print("Blank/invalid image. Please reposition finger.")

            time.sleep(0.5)

        raise TimeoutError("No valid fingerprint captured within timeout.")

    finally:
        if z:
            try:
                z.CloseDevice()
            except Exception:
                pass
            try:
                z.Terminate()
            except Exception:
                pass


def match_templates(stored_template: bytes, fresh_template: bytes):
    """
    เทียบ template 2 อัน
    พยายามใช้ฟังก์ชันของ SDK ก่อน
    ถ้าใช้ไม่ได้ จะ fallback เป็น compare bytes ตรง ๆ
    """
    z = None
    try:
        z = get_scanner()

        # กรณี library มี DBMatch
        if hasattr(z, "DBMatch"):
            try:
                score = z.DBMatch(stored_template, fresh_template)
                # หลาย SDK จะคืน score / similarity
                # กำหนดเงื่อนไขเบื้องต้นไว้ก่อน
                return {
                    "matched": score > 0,
                    "score": score,
                    "method": "DBMatch"
                }
            except Exception as e:
                print(f"DBMatch failed: {e}")

        # fallback
        same = stored_template == fresh_template
        return {
            "matched": same,
            "score": 100 if same else 0,
            "method": "byte_compare_fallback"
        }

    finally:
        if z:
            try:
                z.CloseDevice()
            except Exception:
                pass
            try:
                z.Terminate()
            except Exception:
                pass


@app.route("/health", methods=["GET"])
def health():
    return cors_json({
        "status": "OK",
        "message": "Fingerprint test service is running.",
        "registered_count": len(fingerprint_memory)
    })


@app.route("/scan_fingerprint", methods=["GET"])
def scan_fingerprint():
    try:
        template = capture_template(timeout=30)
        template_b64 = base64.b64encode(template).decode("ascii")

        return cors_json({
            "status": "OK",
            "message": "Fingerprint scanned successfully.",
            "template_b64": template_b64,
            "template_size": len(template)
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/enroll_fingerprint", methods=["POST"])
def enroll_fingerprint():
    """
    body:
    {
      "user_id": "staff_001"
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        user_id = (data.get("user_id") or "").strip()

        if not user_id:
            return cors_json({
                "status": "ERROR",
                "message": "user_id is required."
            }, 400)

        template = capture_template(timeout=30)
        template_b64 = base64.b64encode(template).decode("ascii")

        fingerprint_memory[user_id] = {
            "template_b64": template_b64,
            "created_at": time.time()
        }

        return cors_json({
            "status": "OK",
            "message": f"Fingerprint enrolled for user_id={user_id}",
            "user_id": user_id,
            "template_size": len(template)
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/verify_fingerprint", methods=["POST"])
def verify_fingerprint():
    """
    body:
    {
      "user_id": "staff_001"
    }
    """
    try:
        data = request.get_json(silent=True) or {}
        user_id = (data.get("user_id") or "").strip()

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

        stored_template = base64.b64decode(stored["template_b64"])
        fresh_template = capture_template(timeout=30)

        result = match_templates(stored_template, fresh_template)

        return cors_json({
            "status": "OK",
            "user_id": user_id,
            "verified": result["matched"],
            "score": result["score"],
            "method": result["method"]
        }, 200)

    except TimeoutError as e:
        return cors_json({
            "status": "TIMEOUT",
            "message": str(e)
        }, 504)

    except Exception as e:
        return cors_json({
            "status": "ERROR",
            "message": str(e)
        }, 500)


@app.route("/list_enrolled", methods=["GET"])
def list_enrolled():
    return cors_json({
        "status": "OK",
        "users": list(fingerprint_memory.keys()),
        "count": len(fingerprint_memory)
    })


@app.route("/clear_enrolled", methods=["POST"])
def clear_enrolled():
    fingerprint_memory.clear()
    return cors_json({
        "status": "OK",
        "message": "All enrolled fingerprints cleared from memory."
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True)