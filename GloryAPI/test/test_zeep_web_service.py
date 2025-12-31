from zeep import Client, Settings
from zeep.plugins import HistoryPlugin
from zeep.exceptions import Fault
from zeep.helpers import serialize_object
from lxml import etree

# === Config ===
WSDL_URL = 'http://192.168.0.25/axis2/services/BrueBoxService?wsdl'
ACTUAL_ENDPOINT = 'http://192.168.0.25/axis2/services/BrueBoxService'

# Enable logging of XML history
history = HistoryPlugin()
settings = Settings(strict=False, xml_huge_tree=True)

# === Create Client ===
try:
    client = Client(wsdl=WSDL_URL, settings=settings, plugins=[history])
    print("✅ WSDL loaded successfully.")
except Exception as e:
    print(f"❌ Failed to load WSDL: {e}")
    exit()

# === Correct binding from WSDL ===
binding_name = '{http://www.glory.co.jp/bruebox.wsdl}BrueBoxSoapBinding'

try:
    service = client.create_service(binding_name, ACTUAL_ENDPOINT)
    print("✅ Service bound to endpoint.")
except Exception as e:
    print(f"❌ Failed to bind service endpoint: {e}")
    exit()

# === Call Operation ===
try:
    print("\n🚀 Calling GetStatus operation...")

    response = service.GetStatus(
        Id='0',
        SeqNo='1',
        SessionID='ABC123',
        Option=0,  # Assuming this is xsd:integer
        RequireVerification=0  # Assuming this is xsd:integer
    )

    print("\n✅ Response:")
    print(serialize_object(response))

    print("\n📤 Request XML:")
    print(etree.tostring(history.last_sent['envelope'], pretty_print=True).decode())

    print("\n📥 Response XML:")
    print(etree.tostring(history.last_received['envelope'], pretty_print=True).decode())

except Fault as fault:
    print(f"\n❌ SOAP Fault: {fault}")
except Exception as e:
    print(f"\n❌ Error calling SOAP service: {e}")
