#
# File: GloryAPI/api/fcc_api.py
# Author: Pakkapon Jirachatmongkon
# Date: August 5, 2025
# Description: API layer for processing and mapping FCC responses.
#
# License: MIT License (Example)
#
# Usage: Provides functions to map raw FCC SOAP responses to cleaner API formats.
#
import logging
from . import getstatus_mapping_codes as Mapping_codes

logger = logging.getLogger(__name__)

def map_fcc_login_response(raw_login_data: dict) -> dict:
    """
    Maps the raw serialized Zeep LoginUser response into a cleaner, more
    user-friendly JSON format for the API.

    Args:
        raw_login_data (dict): The dictionary received from fcc_soap_client.login_user().get("data").

    Returns:
        dict: A dictionary with mapped login result information.
    """
    if raw_login_data is None:
        logger.error("No data received from FCC LoginUserOperation.")
        return {"success": False, "error": "No data received from FCC LoginUserOperation."}
    mapped_response = {
        'status': "success",
        'session_id': raw_login_data.get('Id'),
        'user': raw_login_data['User'],
        'transaction_id': raw_login_data['SeqNo'],
    }

    logger.info(f"Mapped LoginUser response: {mapped_response}")
    return mapped_response

def map_fcc_status_response(raw_status_data: dict) -> dict:
    """
    Maps the raw serialized Zeep GetStatus response into a cleaner, more
    user-friendly JSON format for the API.

    Args:
        raw_status_data (dict): The dictionary received from fcc_soap_client.get_status().get("data").

    Returns:
        dict: A dictionary with mapped status information.
    """
    mapped_data = {
        'Status': {},
        'DeviceStatus': [],
        'Id': None,
        'SeqNo': None,
        'User': None,
        'CustomId': None,
        'Cash': None,
        'RequireVerifyInfos': None,
        'result': {},
    }

    # Extract status from the raw data. The key from the SOAP response is 'Code'.
    status_code = raw_status_data.get("Status", {}).get("Code")
    mapped_data['Status'] = {
        'Code': status_code,
        'String': Mapping_codes.FCC_STATUS_CODE_MAP.get(status_code, "Unknown"),
    }

    # Extract and map the result code. The key from the SOAP response is 'result'.
    result_code = raw_status_data.get("result")
    mapped_data['result'] = {
        'Code': result_code,
        'String': Mapping_codes.FCC_GETSTATUS_RESULT_CODE.get(result_code, "Unknown"),
    }

    # Extract and map the device status list. The key from the SOAP response is 'DevStatus'.
    device_status_list = raw_status_data.get("Status", {}).get("DevStatus", [])

    # Ensure device_status_list is always a list, even if only one device is returned
    if not isinstance(device_status_list, list):
        device_status_list = [device_status_list]

    for device_status in device_status_list:
        # Access attributes of the DevStatus tag. Keys from the SOAP response are 'devid' and 'st'.
        device_id = device_status.get('devid')
        device_state_code = device_status.get('st')
        device_value = device_status.get('val')

        mapped_data['DeviceStatus'].append({
            'device_id': device_id,
            'device_type': Mapping_codes.FCC_GETSTATUS_DEVICE_ID_CODE.get(device_id, "Unknown"),
            'value': device_value,
            'device_state': Mapping_codes.FCC_GETSTATUS_DEVICE_STATE.get(device_state_code, "Unknown"),
        })

    # Populate other fields from the raw response
    mapped_data['Id'] = raw_status_data.get("Id")
    mapped_data['SeqNo'] = raw_status_data.get("SeqNo")
    mapped_data['User'] = raw_status_data.get("User")
    mapped_data['CustomId'] = raw_status_data.get("CustomId")
    mapped_data['Cash'] = raw_status_data.get("Cash")
    mapped_data['RequireVerifyInfos'] = raw_status_data.get("RequireVerifyInfos")

    logger.debug(f"Mapped FCC status data: {mapped_data}")
    return mapped_data

# In api/fcc_api.py

def map_inventory_response(raw_data: dict) -> dict:
    """
    Parses the raw response from an InventoryOperation and creates a simple
    summary of available notes and coins.
    """
    inventory = {
        "notes": {},
        "coins": {},
        "total_value": 0.0
    }

    # The detailed breakdown is in the 'CashUnits' list 
    cash_units = raw_data.get('CashUnits')
    if not cash_units:
        return inventory

    for unit in cash_units:
        # device ID 1 is typically the note recycler, 2 is the coin recycler
        device_id = unit.get('devid')
        denominations = unit.get('CashUnit', [])[0].get('Denomination', [])

        for denom in denominations:
            value = denom.get('fv', 0)
            count = denom.get('Piece', 0)

            if value > 0 and count > 0:
                target_dict = inventory["notes"] if device_id == 1 else inventory["coins"]
                
                # Add to existing count for this denomination
                current_count = target_dict.get(value, 0)
                target_dict[value] = current_count + count

    # Calculate total value and format the output
    notes_list = []
    for value, count in inventory["notes"].items():
        notes_list.append({"value": value, "count": count})
        inventory["total_value"] += value * count
    
    coins_list = []
    for value, count in inventory["coins"].items():
        coins_list.append({"value": value, "count": count})
        inventory["total_value"] += value * count

    return {
        "notes": sorted(notes_list, key=lambda x: x['value'], reverse=True),
        "coins": sorted(coins_list, key=lambda x: x['value'], reverse=True),
        "total_value": inventory["total_value"]
    }

def map_register_event_response(raw_event_data: dict) -> dict:
    """
    Maps the raw serialized Zeep RegisterEventOperation response into a cleaner,
    more user-friendly JSON format for the API.

    Args:
        raw_event_data (dict): The dictionary received from fcc_soap_client.get_register_event().get("data").

    Returns:
        dict: A dictionary with mapped event registration information.
    """

    if raw_event_data is None:
        logger.error("No data received from FCC RegisterEventOperation.")
        return {"code": None, "result": {}}
    
    status_code = raw_event_data.get("Status", {}).get("Code")

    mapped_data = {
        "code": status_code,
        "result": {},
    }

    if not raw_event_data:
        logger.error("No data received from FCC RegisterEventOperation.")
        return mapped_data

    # Map result code
    mapped_data['result'] = {
        'result': raw_event_data.get("Result"),
    }

def map_cash_in_response(raw_cash_in_data: dict) -> dict:
    """
    Maps the raw serialized Zeep OpenCashIn response into a cleaner, more
    user-friendly JSON format for the API.

    Args:
        raw_cash_in_data (dict): The dictionary received from fcc_soap_client.open_cash_in().get("data").

    Returns:
        dict: A dictionary with mapped cash-in result information.
    """
    # This function remains unchanged as the request was only for the GetStatus mapping.
    mapped_data = {
        "transaction_id": raw_cash_in_data.get("Id"),
        "sequence_number": raw_cash_in_data.get("SeqNo"),
        "session_id": raw_cash_in_data.get("SessionID"),
        "result": raw_cash_in_data.get("Result"),
        "status": raw_cash_in_data.get("Status", {}).get("StatusCode"),
        "device_status": raw_cash_in_data.get("Status", {}).get("DeviceStatusList", {}).get("DeviceStatus"),
        "cash_in_amounts": [],
    }

    # Handle the CashInAmountList which might be a single item or a list
    cash_in_list = raw_cash_in_data.get("CashInAmountList", {}).get("CashInAmount", [])
    if not isinstance(cash_in_list, list):
        cash_in_list = [cash_in_list]

    for cash_in in cash_in_list:
        mapped_data["cash_in_amounts"].append({
            "currency_code": cash_in.get("CurrencyCode"),
            "amount": cash_in.get("Amount"),
        })

    logger.debug(f"Mapped FCC cash-in data: {mapped_data}")
    return mapped_data
