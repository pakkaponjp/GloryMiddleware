import time

print("Step 2: importing pyzkfp...")
from pyzkfp import ZKFP2

z = None

try:
    print("Step 3: create ZKFP2 object")
    z = ZKFP2()

    print("Step 4: Init()")
    z.Init()
    print("Init OK")

    print("Step 5: GetDeviceCount()")
    count = z.GetDeviceCount()
    print("Device count =", count)

    if count <= 0:
        raise Exception("No fingerprint scanner found.")

    print("Step 6: OpenDevice(0)")
    z.OpenDevice(0)
    print("OpenDevice OK")

    try:
        print("Step 7: DBInit()")
        z.DBInit()
        print("DBInit OK")
    except Exception as e:
        print("DBInit warning:", e)

    try:
        print("Step 8: SetParameters skipped")
    except Exception:
        pass

    print("SUCCESS: Scanner is ready")

except Exception as e:
    print("ERROR:", type(e).__name__, str(e))
    raise

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