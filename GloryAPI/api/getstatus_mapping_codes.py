#
# File: GloryAPI/api/getstatus_mapping_codes.py
# Author: Pakkapon Jirachatmongkon
# Date: August 5, 2025
# Description: Centralized dictionaries for mapping FCC status codes and result codes to descriptive strings.
#
# License: MIT License (Example)
#
# Usage: Imported by other modules (e.g., fcc_api.py) to provide human-readable status and result messages.
#

# GetStatus response code mapping for FCC machine.
# Dictionary to map FCC device status codes (integers) to their descriptive strings.
FCC_STATUS_CODE_MAP = {
    0: "Initializing",
    1: "Idle",
    2: "At Starting change",
    3: "Waiting insertion of cash",
    4: "Counting",
    5: "Dispensing",
    6: "Waiting removal of cash in reject",
    7: "Waiting removal of cash out",
    8: "Resetting",
    9: "Canceling of Change operation",
    10: "Calculating Change amount",
    11: "Canceling Deposit",
    12: "Collecting",
    13: "Error",
    14: "Upload firmware",
    15: "Reading log",
    16: "Waiting Replenishment",
    17: "Counting Replenishment",
    18: "Unlocking",
    19: "Waiting inventory",
    20: "Fixed deposit amount",
    21: "Fixed dispense amount",
    23: "Waiting change cancel",
    24: "Counted category2 note",
    25: "Waiting deposit end",
    26: "Waiting removal of COFT",
    27: "Sealing",
    30: "Waiting for Error recovery",
}

# Dictionary to map the result codes from a GetStatus operation.
FCC_GETSTATUS_RESULT_CODE = {
    0: "success",
    21: "invalid session",
    22: "session timeout",
    98: "parameter error (type error)",
    99: "program inner error",
}

# Dictionary to map FCC device IDs to their model names.
FCC_GETSTATUS_DEVICE_ID_CODE = {
    1: "RBW-200",
    2: "RCW-200",
}

# Dictionary to map the device status/state codes to descriptive strings.
FCC_GETSTATUS_DEVICE_STATE = {
    0: "STATE_INITIALIZE",
    1000: "STATE_IDLE",
    1500: "STATE_IDLE_OCCUPY",
    2000: "STATE_DEPOSIT_BUSY",
    2050: "STATE_DEPOSIT_COUNTING",
    2055: "STATE_DEPOSIT_END",
    2100: "STATE_WAIT_STORE",
    2200: "STATE_STORE_BUSY",
    2300: "STATE_STORE_END",
    2500: "STATE_WAIT_RETURN",
    2600: "STATE_COUNT_BUSY",
    2610: "STATE_COUNT_COUNTING",
    2700: "STATE_REPLENISH_BUSY",
    3000: "STATE_DISPENSE_BUSY",
    3100: "STATE_WAIT_DISPENSE",
    4000: "STATE_REFILL",
    4050: "STATE_REFILL_COUNTING",
    4055: "STATE_REFILL_END",
    5000: "STATE_RESET",
    6000: "STATE_COLLECT_BUSY",
    6500: "STATE_VERIFY_BUSY",
    6600: "STATE_VERIFYCOLLECT_BUSY",
    7000: "STATE_INVENTORY_CLEAR",
    7100: "STATE_INVENTORY_ADJUST",
    8000: "STATE_DOWNLOAD_BUSY",
    8100: "STATE_LOG_READ_BUSY",
    9100: "STATE_BUSY",
    9200: "STATE_ERROR",
    9300: "STATE_COM_ERROR",
    9400: "STATE_WAIT_FOR_RESET",
    9500: "STATE_CONFIG_ERROR",
    50000: "STATE_LOCKED_BY_OTHER_SESSION",
}