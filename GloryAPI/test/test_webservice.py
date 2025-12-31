# test_soap_with_requests.py
import requests
import xml.etree.ElementTree as ET # For basic XML parsing of response
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def call_get_status_basic_soap():
    # --- Configuration ---
    # The actual IP of your FCC simulator
    FCC_MACHINE_IP = '192.168.0.25'
    
    # The full endpoint URL where the SOAP requests will be sent
    # We are directly using the IP here, NOT service.bruebox.com
    SOAP_ENDPOINT = f"http://{FCC_MACHINE_IP}/axis2/services/BrueBoxService"
    
    # The namespace URI for the BrueBox schema
    BRUEBOX_NS = "http://www.glory.co.jp/bruebox.xsd"
    
    # The SOAPAction header for the GetStatus operation
    # This is often the target namespace + operation name
    SOAP_ACTION = f"{BRUEBOX_NS}/GetStatus"

    # --- Construct the SOAP XML Payload ---
    # Using f-strings and multi-line strings for readability
    soap_request_xml = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:bru="http://www.glory.co.jp/bruebox.xsd">
   <soapenv:Header/>
   <soapenv:Body>
      <bru:StatusRequest>
         <!--Optional:-->
         <bru:SeqNo>?</bru:SeqNo>
         <!--Optional:-->
         <bru:SessionID>?</bru:SessionID>
         <Option bru:type="?"/>
         <!--Optional:-->
         <RequireVerification bru:type="?"/>
      </bru:StatusRequest>
   </soapenv:Body>
</soapenv:Envelope>"""

    # --- Set HTTP Headers ---
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        'SOAPAction': SOAP_ACTION # Crucial for SOAP services
    }

    logger.info(f"Sending SOAP request to: {SOAP_ENDPOINT}")
    logger.info(f"Request Headers: {headers}")
    logger.info(f"Request Body:\n{soap_request_xml}")

    try:
        # --- Send the Request ---
        response = requests.post(SOAP_ENDPOINT, headers=headers, data=soap_request_xml, timeout=10) # Added timeout

        # --- Process the Response ---
        logger.info(f"Received Response Status Code: {response.status_code}")
        logger.info(f"Received Response Headers: {response.headers}")
        logger.info(f"Received Response Body:\n{response.text}")

        # Basic error handling for HTTP status
        if response.status_code == 200:
            logger.info("SOAP request successful (HTTP 200 OK).")
            # You might want to parse the XML response here for specific data
            try:
                # Basic XML parsing to check for SOAP Fault or specific elements
                root = ET.fromstring(response.text)
                # Check for SOAP Faults (common in SOAP error responses)
                soap_fault_ns = "{http://schemas.xmlsoap.org/soap/envelope/}Fault"
                if root.find(f'.//{soap_fault_ns}') is not None:
                    logger.error("Received SOAP Fault in response.")
                    # You can extract fault details here
                    return {"success": False, "error": "SOAP Fault received", "response_xml": response.text}
                else:
                    logger.info("No SOAP Fault detected. Response looks like a normal response.")
                    return {"success": True, "response_xml": response.text}

            except ET.ParseError as pe:
                logger.error(f"Error parsing XML response: {pe}")
                return {"success": False, "error": "Failed to parse XML response", "response_xml": response.text}
        else:
            logger.error(f"SOAP request failed with HTTP Status: {response.status_code}")
            return {"success": False, "error": f"HTTP Error {response.status_code}", "response_xml": response.text}

    except requests.exceptions.ConnectionError as ce:
        logger.error(f"Connection Error: Could not connect to {SOAP_ENDPOINT}. Ensure FCC simulator is running and IP is correct. Error: {ce}")
        return {"success": False, "error": f"Connection Error: {ce}"}
    except requests.exceptions.Timeout as te:
        logger.error(f"Timeout Error: Request to {SOAP_ENDPOINT} timed out. Error: {te}")
        return {"success": False, "error": f"Timeout Error: {te}"}
    except requests.exceptions.RequestException as e:
        logger.error(f"An unexpected requests error occurred: {e}")
        return {"success": False, "error": f"Requests Error: {e}"}
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return {"success": False, "error": f"Unexpected Error: {e}"}

if __name__ == "__main__":
    print("--- Running Basic SOAP GetStatus Test with Requests ---")
    result = call_get_status_basic_soap()
    print("\n--- Test Result Summary ---")
    print(result)