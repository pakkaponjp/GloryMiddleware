from pyzkfp import ZKFP2
import time

def get_scanner():
    z = ZKFP2()
    z.Init()

    count = z.GetDeviceCount()
    print(f"Device count: {count}")
    if count <= 0:
        raise Exception("No fingerprint scanner found.")

    z.OpenDevice(0)
    z.DBInit()
    print("Scanner ready")
    return z

z = None
try:
    z = get_scanner()

    print("Place finger on scanner...")
    start = time.time()

    while time.time() - start < 20:
        res = z.AcquireFingerprint()
        if not res:
            time.sleep(0.2)
            continue

        print("==== RAW RESULT ====")
        print("type(res):", type(res))
        print("res:", res)

        if isinstance(res, (tuple, list)):
            print("len(res):", len(res))
            for i, item in enumerate(res):
                try:
                    l = len(item)
                except Exception:
                    l = "no len"
                print(f"item[{i}] type={type(item)} len={l}")

        break

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