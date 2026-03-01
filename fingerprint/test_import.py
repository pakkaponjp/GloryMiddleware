print("Step 1: importing pyzkfp...")

try:
    from pyzkfp import ZKFP2
    print("OK: import pyzkfp success")
    print("ZKFP2 =", ZKFP2)
except Exception as e:
    print("ERROR: import failed")
    print(type(e).__name__, str(e))
    raise