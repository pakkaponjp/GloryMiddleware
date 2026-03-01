import time
import base64

from pyzkfp import ZKFP2

fingerprint_memory = {}


def get_scanner():
    z = ZKFP2()
    z.Init()

    count = z.GetDeviceCount()
    print(f"Device count: {count}")
    if count <= 0:
        raise Exception("No fingerprint scanner found.")

    z.OpenDevice(0)

    try:
        z.DBInit()
        print("DBInit OK")
    except Exception as e:
        print("DBInit warning:", e)

    print("SetParameters skipped for now")
    return z

def capture_template(timeout=20):
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

            print("AcquireFingerprint raw result:", type(res), res)

            template = None
            image_data = None

            if isinstance(res, (tuple, list)) and len(res) >= 2:
                # จากผล debug ของคุณ:
                # item[0] = template (System.Byte[]) len=2048
                # item[1] = image bytes len=120000
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
                print("Captured template length:", len(template_bytes))
                return template_bytes

            print("Fingerprint detected but template not extracted yet.")
            time.sleep(0.2)

        raise TimeoutError("Timeout waiting for fingerprint.")

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

def enroll(user_id):
    template = capture_template()
    fingerprint_memory[user_id] = template
    print(f"Enroll OK for {user_id}, size={len(template)}")

def verify(user_id):
    if user_id not in fingerprint_memory:
        print(f"No enrolled fingerprint for {user_id}")
        return False

    stored = fingerprint_memory[user_id]
    fresh = capture_template()

    print("Stored length:", len(stored))
    print("Fresh length:", len(fresh))

    # กันพลาดก่อนเรียก native DBMatch
    if len(stored) != 2048 or len(fresh) != 2048:
        raise ValueError(
            f"Invalid template size for DBMatch: stored={len(stored)}, fresh={len(fresh)}"
        )

    z = None
    try:
        z = get_scanner()
        score = z.DBMatch(stored, fresh)
        print("DBMatch score:", score)

        matched = score > 0
        print("Verify result:", matched)
        return matched

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

def menu():
    while True:
        print("\n=== Fingerprint Console Test ===")
        print("1) Enroll fingerprint")
        print("2) Verify fingerprint")
        print("3) List enrolled users")
        print("4) Exit")

        choice = input("Select: ").strip()

        if choice == "1":
            user_id = input("Enter user_id: ").strip()
            if user_id:
                try:
                    enroll(user_id)
                except Exception as e:
                    print("Enroll error:", type(e).__name__, str(e))

        elif choice == "2":
            user_id = input("Enter user_id: ").strip()
            if user_id:
                try:
                    result = verify(user_id)
                    print("FINAL VERIFY =", result)
                except Exception as e:
                    print("Verify error:", type(e).__name__, str(e))

        elif choice == "3":
            print("Enrolled users:", list(fingerprint_memory.keys()))

        elif choice == "4":
            print("Bye")
            break

        else:
            print("Invalid choice")


if __name__ == "__main__":
    menu()