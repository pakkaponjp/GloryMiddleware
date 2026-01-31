# GloryAPI/config.py
import os

class Config:
    """
    Switch between 'vm' and 'physical' with FCC_MODE env var.
    Defaults to 'vm'.
      - vm       : plain HTTP to the VM FCC (IP)
      - physical : HTTPS to the real machine (custom CA, hostname 'glory')
    """

    FCC_MODE = os.environ.get("FCC_MODE", "vm").strip().lower()  # 'vm' | 'physical'

    # Common defaults
    FCC_MACHINE_IP      = os.environ.get('FCC_MACHINE_IP', '192.168.0.25')
    GLORY_API_IP_FOR_EVENTS = os.environ.get('GLORY_API_IP_FOR_EVENTS', '0.0.0.0')
    FCC_EVENT_LISTENER_PORT = int(os.environ.get('FCC_EVENT_LISTENER_PORT', 55561))
    
    # Set timeout for SOAP requests to the FCC device
    FCC_CONNECT_TIMEOUT   = int(os.environ.get("FCC_CONNECT_TIMEOUT", 3))   # for initial WSDL connect
    FCC_OPERATION_TIMEOUT = int(os.environ.get("FCC_OPERATION_TIMEOUT", 5)) # for SOAP ops

    # Flask app
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() in ('true', '1', 't')
    HOST  = os.environ.get('FLASK_HOST', '0.0.0.0')
    PORT  = int(os.environ.get('FLASK_PORT', 5000))

    # Mode-specific settings
    if FCC_MODE == "physical":
        # Physical Glory machine (self-signed cert: CN=glory, no SAN)
        FCC_MACHINE_HOST   = os.environ.get('FCC_MACHINE_HOST', 'glory')  # used in URL if resolvable
        FCC_SOAP_SCHEME    = "https"
        FCC_SOAP_PORT      = 443
        FCC_SOAP_VERIFY    = os.environ.get('FCC_SOAP_VERIFY', '/usr/local/share/ca-certificates/fcc.crt')  # cafile
    else:
        # Local VM FCC (typically plain HTTP)
        FCC_MACHINE_HOST   = os.environ.get('FCC_MACHINE_HOST', None) or os.environ.get('FCC_MACHINE_IP', '192.168.0.25')
        FCC_SOAP_SCHEME    = "http"
        FCC_SOAP_PORT      = int(os.environ.get('FCC_SOAP_PORT', 80))
        FCC_SOAP_VERIFY    = os.environ.get('FCC_SOAP_VERIFY', 'False')
        # Normalize boolean-ish strings to actual bool False for requests
        if isinstance(FCC_SOAP_VERIFY, str) and FCC_SOAP_VERIFY.lower() in ("false", "0", "no"):
            FCC_SOAP_VERIFY = False

    # Build WSDL URL host part.
    # For physical: prefer hostname 'glory' but the client will auto-fallback to the IP if DNS fails.
    _WSDL_HOST = FCC_MACHINE_HOST or FCC_MACHINE_IP
    FCC_SOAP_WSDL_URL = f"{FCC_SOAP_SCHEME}://{_WSDL_HOST}:{FCC_SOAP_PORT}/axis2/services/BrueBoxService?wsdl"

    # GloryIntermedia (forwarding) – leave as-is
    GLORY_INTERMEDIA_EVENT_FORWARD_URL = os.environ.get(
        'GLORY_INTERMEDIA_EVENT_FORWARD_URL', 'http://localhost:9999/fcc-events'
    )
#Glory FCC
# Production settings currency THB
#FCC_CURRENCY = 'THB'
# Development settings currency by FCC setting
FCC_CURRENCY = 'EUR'

# Glory FCC Users / mappings
ROLE_TO_GLORY_USER = {
    "attendant": "gs_user",
    "coffee_shop_staff": "gs_user",
    "convenient_store_staff": "gs_user",
    "tenant": "gs_user",
    "cashier": "gs_cashier",
    "supervisor": "gs_manager",
    "manager": "gs_manager",
    "cit": "gs_cit",
    "service": "gs_service",
    "admin": "gs_service",
}

GLORY_SESSION_TTL = 300

GLORY_USER_MAPPING = {
    "attendant": {"user": "gs_user", "password": "password"},
    "coffee_shop_staff": {"user": "gs_user", "password": "password"},
    "convenient_store_staff": {"user": "gs_user", "password": "password"},
    "tenant": {"user": "gs_user", "password": "password"},
    "cashier": {"user": "gs_cashier", "password": "password"},
    "supervisor": {"user": "gs_manager", "password": "password"},
    "manager": {"user": "gs_manager", "password": "password"},
    "cit": {"user": "gs_cit", "password": "cit_pass"},
    "service": {"user": "gs_service", "password": "password"},
    "admin": {"user": "gs_service", "password": "password"},
}
