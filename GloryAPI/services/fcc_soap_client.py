#
# File: GloryAPI/services/fcc_soap_client.py
# Author: Pakkapon Jirachatmongkon
# Date: July 25, 2025 (Simple Monolith Structure - Fixed OpenCashIn Operation Name)
# Description: FCC SOAP client for BrueBoxService, designed to use online WSDL and explicit IP.
#
# License: P POWER GENERATING CO.,LTD.
#
# Usage: Provides methods to interact with the FCC SOAP service (e.g., GetStatus, OpenCashIn).
#
import logging
import sys
import os
import time
import threading
import json
import re
import ssl
import urllib3
from config import FCC_CURRENCY
from zeep import Client, Transport, Settings, xsd
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from requests.auth import HTTPBasicAuth # For potential authentication
from zeep.plugins import HistoryPlugin
from zeep.exceptions import Fault, TransportError # Specific SOAP fault handling
from zeep.helpers import serialize_object 

# Import configuration and utility for serialization from the correct paths
# (Adjusted for Simple Monolith structure)
from config import Config
from utils.soap_serializer import serialize_zeep_object, pretty_print_xml

logger = logging.getLogger(__name__)

# Configure Zeep specific logging to DEBUG to see raw XML requests and responses
logging.getLogger('zeep.transports').setLevel(logging.DEBUG)
logging.getLogger('zeep.client').setLevel(logging.DEBUG)

# Initialize a global history plugin instance for debugging SOAP messages
soap_history = HistoryPlugin()

# Mapping target strings to cash types
TARGET_TO_TYPE = {
    "notes": 1,
    "note": 1,
    "bills": 1,
    "coins": 2,
    "coin": 2,
    "both": 0,
    "all": 0,
    None: 0,
}

class HostnameIgnoringAdapter(HTTPAdapter):
    """Verify with CA, but skip hostname matching (pragmatic for fixed LAN devices)."""
    def __init__(self, cafile=None, *args, **kwargs):
        self._cafile = cafile
        super().__init__(*args, **kwargs)
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context(cafile=self._cafile if isinstance(self._cafile, str) else None)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        self.poolmanager = PoolManager(*args, ssl_context=ctx, assert_hostname=False, **kwargs)

class PatchedTransport(Transport):
    _NS = b'http://www.glory.co.jp/bruebox.xsd'

    def load(self, url):
        data = super().load(url)  # bytes
        # Only patch schema files for the Glory namespace
        if isinstance(data, (bytes, bytearray)) and self._NS in data:
            # If INSTALL_DATE isn’t declared, inject a simple string element before </xsd:schema>
            if b'name="INSTALL_DATE"' not in data:
                data = re.sub(
                    br'(</xsd:schema\s*>)',
                    br'  <xsd:element name="INSTALL_DATE" type="xsd:string"/>\n\1',
                    data,
                    count=1,
                    flags=re.IGNORECASE,
                )
        return data

class FccSoapClient:
    _instance = None  # Class-level variable to hold the singleton instance

    def __new__(cls, wsdl_url):
        """
        Singleton: create one instance, but DON'T connect here.
        """
        if cls._instance is None:
            cls._instance = super(FccSoapClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, wsdl_url):
        """
        Idempotent initializer: configure only once, no network calls.
        """
        if getattr(self, "_initialized", False):
            return

        self._initialize(wsdl_url)
        self._initialized = True

    def _initialize(self, wsdl_url):
        """
        Internal initialization method for the FccSoapClient instance.
        Sets up the WSDL URL and internal state, but DOES NOT connect yet.
        """
        logger.info(f"Configuring FccSoapClient (lazy) with WSDL: {wsdl_url}")
        self.wsdl_url = wsdl_url
        self.client = None
        self.service_proxy = None  # Holds the bound service object (e.g., client.service)
        self.session = None        # requests.Session for persistent connections
        self.transport = None      # Zeep Transport using the requests.Session
        self._seq_no = 0           # Sequence number for Glory FCC request (auto increment)
        self._seq_lock = threading.Lock()

    def _next_seq_no(self) -> str:
        """
        Generate the next unique sequence number as a string.
        Thread-safe to avoid collisions.
        """
        with self._seq_lock:
            self._seq_no += 1
            return str(self._seq_no)

    def _connect_client(self):
        scheme = getattr(Config, "FCC_SOAP_SCHEME", "http")
        port   = int(getattr(Config, "FCC_SOAP_PORT", 80))
        host_pref = getattr(Config, "FCC_MACHINE_HOST", None)
        ip_fallback = getattr(Config, "FCC_MACHINE_IP", None)
        verify_cfg = getattr(Config, "FCC_SOAP_VERIFY", False)

        # Build endpoint URL using configured host (hostname or IP)
        def endpoint_for(host):
            return f"{scheme}://{host}:{port}/axis2/services/BrueBoxService"
        def wsdl_for(host):
            return f"{scheme}://{host}:{port}/axis2/services/BrueBoxService?wsdl"

        # 1) session + verify
        if self.session is None:
            self.session = Session()
            self.session.verify = verify_cfg
            if scheme == "https":
                # keep CA verification but ignore hostname (CN=glory, no SAN)
                self.session.mount("https://", HostnameIgnoringAdapter(cafile=verify_cfg))
                
            #self.transport = PatchedTransport(session=self.session, timeout=10)
            self.transport = PatchedTransport(
                session=self.session,
                timeout=Config.FCC_OPERATION_TIMEOUT,            # HTTP timeout
                operation_timeout=Config.FCC_OPERATION_TIMEOUT,  # zeep operation timeout
            )

        # 2) zeep settings
        settings = Settings(strict=False, xml_huge_tree=True)

        # 3) Try preferred host first; if it fails (DNS, etc), retry IP fallback
        tried = []
        for host_candidate in [h for h in [host_pref, ip_fallback] if h]:
            wsdl = wsdl_for(host_candidate)
            try:
                self.client = Client(wsdl=wsdl, transport=self.transport, settings=settings, plugins=[soap_history])
                logger.info(f"Loaded WSDL from {wsdl}")
                # Bind service explicitly
                binding_name = '{http://www.glory.co.jp/bruebox.wsdl}BrueBoxSoapBinding'
                self.service_proxy = self.client.create_service(binding_name, endpoint_for(host_candidate))
                logger.info(f"Service bound to {endpoint_for(host_candidate)}")
                # list ops (optional)
                try:
                    ops = sorted(self.client.service._operations)
                    logger.info("Available SOAP operations: %s", ops)
                except Exception:
                    pass
                return
            except Exception as e:
                tried.append(f"{wsdl} -> {e}")

        # all attempts failed
        self.client = None
        self.service_proxy = None
        if self.session:
            try: self.session.close()
            except Exception: pass
        self.session = None
        self.transport = None
        raise RuntimeError("Failed to connect/load WSDL:\n  " + "\n  ".join(tried))


    def get_service_instance(self):
        if self.service_proxy is None:
            logger.warning("FCC SOAP service proxy not available. Attempting to (re)connect...")
            try:
                self._connect_client()
            except Exception as exc:
                logger.exception("Unable to connect to FCC SOAP service")
                raise RuntimeError("FCC SOAP service is not available") from exc
        return self.service_proxy
    
    def _log_wsdl_operations(self):
        try:
            c = self.client
            if not c:
                return
            for bname, binding in c.wsdl.bindings.items():
                try:
                    ops = sorted(binding._operations.keys())
                except Exception:
                    ops = []
                logger.info("FCC WSDL binding %s ops: %s", bname, ops)
        except Exception as e:
            logger.warning("Failed to enumerate WSDL operations: %s", e)

    def _call_first_available(self, svc, op_names: list[str], **req):
        """
        Try several SOAP operation names until one exists/calls successfully.
        Returns zeep object or raises the last exception.
        """
        last_err = None
        for name in op_names:
            try:
                op = getattr(svc, name, None)
                if not op:
                    continue
                logger.info("Calling %s with payload: %s", name, req)
                return op(**req)
            except Exception as e:
                last_err = e
                logger.warning("Operation %s failed: %s", name, e)
        if last_err:
            raise last_err
        raise AttributeError(f"None of operations available: {op_names}")   

    # ------------- SOAP Operations ----------------
    ######################## NEW OPERATIONS ########################
    ### 1. Status Check: GetStatus (Option=1) for quick heartbeat.
    def get_status(self, session_id: str | None = None, require_verification: bool = False) -> dict:
        """
        Quick heartbeat using GetStatus (Option=1).
        """
        svc = self.get_service_instance()

        req = {
            "Id": "",
            "SeqNo": "",
            "Option": {"type": 1},  # Option=1 = quick status
        }
        if session_id:
            req["SessionID"] = str(session_id)
        if require_verification:
            req["RequireVerification"] = {"type": 1}

        try:
            resp = svc.GetStatus(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("GetStatus SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    ### 2. Change Request: Start transaction to Deposit & Dispense cash.
    def change_operation(self, amount, denominations):
        """
        Calls the FCC SOAP ChangeOperation.
        Args:
            amount (int): total amount requested.
            denominations (list): list of dictionaries, e.g.,
                                  [{"value": 1000, "qty": 1, "currency": "EUR"}]
                                  - "value" corresponds to bru:fv
                                  - "qty" corresponds to bru:Piece
                                  - "currency" corresponds to bru:cc
        Returns:
            dict: parsed SOAP response
        """
        # Build the SOAP request body based on the XML structure
        denom_items = []
        for d in denominations:
            denom_items.append({
                'cc': FCC_CURRENCY,
                'fv': d["value"],
                'devid': 1,
                'Piece': d["qty"],
                'Status': 6,
            })

        request_data = {
            "Id": str(0), # Cast to string
            "SeqNo": "",
            "SessionID": "abc",
            "Amount": str(amount), # Cast to string
            "Option": {
                'type': 1,
            },
            "Cash": {
                'type': 6,
                # The Denomination list is nested under the 'Cash' key.
                "Denomination": denom_items,
            },
        }

        # Use json.dumps for robust and readable logging of the dictionary
        logger.info("Sending ChangeOperation SOAP request: %s", json.dumps(request_data))

        service = self.get_service_instance()
        if (service is None):
            logger.error("SOAP Cannot connect")
            return "Cannot connect SOAP"
        try:
            # The user's log indicates the method is ChangeOperation.
            response = service.ChangeOperation(**request_data)
            safe_response = serialize_zeep_object(response)
            logger.info("SOAP response: %s", safe_response)
            return safe_response
        except Exception as e:
            logger.error("SOAP ChangeOperation failed: %s", e)
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
        
    ### 3. Change Cancel Request: Cancel transaction to Deposit & Dispense cash.

    ### 4. Start Cash in Request: OpenCashInOperation to start deposit transaction.
    def start_cashin(self, session_id: str) -> dict:
        svc = self.get_service_instance()
        req = {
            "Id": "1",
            "SeqNo": "1",
            "SessionID": str(session_id),
            "Option": {"type": 0},
        }
        
        try:
            resp = svc.StartCashinOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("GetStatus SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    ### 5. End Cash in Request: CloseCashInOperation to end deposit transaction.
    def end_cashin(self, session_id: str) -> dict:
        svc = self.get_service_instance()
        req = {
            "Id": "1",
            "SeqNo": "1",
            "SessionID": str(session_id),
            "Option": {"type": 1},   # <- required by WSDL
        }
        
        try:
            resp = svc.EndCashinOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("GetStatus SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
    
    ### 6. Cancel Cash in Request: CancelCashInOperation to cancel deposit transaction.
    def cancel_cashin(self, session_id: str, option_type: int = 0) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
    
        # Build request (mirrors your working calls)
        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(option_type)},
        }
    
        # Gather all callable operation names from the bound service
        try:
            ops = []
            cl = self.client
            for binding in cl.wsdl.bindings.values():
                try:
                    ops.extend(binding._operations.keys())
                except Exception:
                    pass
            ops = sorted(set(ops))
            logger.info("SOAP ops available: %s", ops)
        except Exception:
            ops = []
    
        # Ranked candidates by common vendor naming
        preferred = [
            "CancelCashinOperation",
            "AbortCashinOperation",
            "CancelDepositOperation",
            "CashinCancelOperation",
            "AbortDepositOperation",
            "CancelOperation",     # generic
            "AbortOperation",      # generic
        ]
    
        # Try exact preferred names if present
        tried = []
        for name in preferred:
            if name in ops and hasattr(svc, name):
                try:
                    logger.info("Calling %s with req: %s", name, req)
                    resp = getattr(svc, name)(**req)
                    return serialize_zeep_object(resp)
                except Exception as e:
                    tried.append((name, str(e)))
                    logger.warning("%s failed: %s", name, e)
    
        # Heuristic: any op that contains 'cancel' and ('cashin' or 'deposit')
        lowered = [o for o in ops]
        for name in lowered:
            ln = name.lower()
            if "cancel" in ln and ("cashin" in ln or "deposit" in ln):
                try:
                    logger.info("Calling %s (heuristic) with req: %s", name, req)
                    resp = getattr(svc, name)(**req)
                    return serialize_zeep_object(resp)
                except Exception as e:
                    tried.append((name, str(e)))
                    logger.warning("%s failed: %s", name, e)
    
        # Fallback: some stacks use EndCashinOperation to terminate the session
        if "EndCashinOperation" in ops and hasattr(svc, "EndCashinOperation"):
            try:
                logger.info("Fallback to EndCashinOperation with req: %s", req)
                resp = svc.EndCashinOperation(**req)
                return serialize_zeep_object(resp)
            except Exception as e:
                tried.append(("EndCashinOperation", str(e)))
                logger.warning("EndCashinOperation fallback failed: %s", e)
    
        # Nothing worked
        if tried:
            logger.error("No cancel op succeeded. Tried: %s", tried)
        raise RuntimeError("No cancel cash-in operation available on FCC service")

    # 7. Cash out Request: CashoutOperation to dispense cash (exact denominations).
    def cashout_execute_by_denoms(
        self,
        session_id: str,
        currency: str,
        denominations_list: list,
        note_dest: str = "exit",
        coin_dest: str = "exit",
    ) -> dict:
        """
        Execute CashoutOperation with explicit denominations.
    
        denominations_list: list of dicts like:
            {
              "cc": "THB",
              "fv": 100,
              "devid": 2,      # 1 = notes, 2 = coins
              "Piece": 1,
              "Status": 0,
            }
        """
        logger.info("Attempting cash-out by explicit denominations for SID %s", session_id)
    
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
    
        # Normalize / validate denominations
        safe_denoms = []
        for i, d in enumerate(denominations_list or []):
            try:
                fv = int(d.get("fv"))
                qty = int(d.get("Piece"))
            except Exception:
                raise ValueError(f"Invalid denomination at index {i}: require integer 'fv' and 'Piece'") from None
    
            if fv <= 0 or qty <= 0:
                raise ValueError(f"Invalid denomination at index {i}: fv/Piece must be positive")
    
            cc = (d.get("cc") or currency or "").upper()
            devid = int(d.get("devid", 1))
            status = int(d.get("Status", 0))
    
            if devid not in (1, 2):
                raise ValueError(f"Invalid devid at index {i}: must be 1 (notes) or 2 (coins)")
    
            safe_denoms.append({
                "cc": cc,        # attribute
                "fv": fv,        # attribute
                "devid": devid,  # attribute
                "Piece": qty,    # element
                "Status": status # element
            })
    
        if not safe_denoms:
            raise ValueError("denominations_list must contain at least one item")
    
        # Build <Cash> payload exactly as the box expects
        cash_payload = {
            "type": 2,                # 2 = cash-out by denomination
            "Denomination": safe_denoms,
        }
        if note_dest:
            cash_payload["note_destination"] = note_dest
        if coin_dest:
            cash_payload["coin_destination"] = coin_dest
    
        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Cash": cash_payload,
        }
    
        logger.info("CashoutOperation request payload: %s", req)
    
        # Call SOAP and always return a plain dict
        raw = svc.CashoutOperation(**req)
        try:
            return serialize_object(raw, dict)
        except Exception:
            return serialize_object(raw)

    # 8. Inventory Request: InventoryOperation to get current cash inventory.
    def inventory(self, session_id: str) -> dict:
        """
        Call InventoryOperation and return a zeep-serialized dict.
        Matches sample: empty Id/SeqNo and Option type=0.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",                 # empty per your sample
            "SeqNo": "",              # empty per your sample
            "SessionID": str(session_id),
            "Option": {"type": 0},    # Option d2p1:type="0"
        }
        
        try:
            logger.info("InventoryOperation req: %s", req)
            resp = svc.InventoryOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("GetStatus SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 9. Collect Request: Start collect transaction
    def collect(self, session_id, scope="all", plan="full", target_float=None) -> dict:
        """
        Collect cash from the machine.
          scope: "all" | "notes" | "coins"
          plan : "full" | "leave_float"
          target_float: {"denoms":[{"devid":1|2,"cc":"EUR","fv":50,"min_qty":4}, ...]}
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        # helper
        def scope_ok(dv: int) -> bool:
            return (
                scope == "all" or
                (scope == "notes" and dv == 1) or
                (scope == "coins" and dv == 2)
            )

        # For FULL plan we don't need to build denoms at all — let the FCC do it.
        # Just send Cash.type=0 and we're done.
        if plan == "full":
            OPTION_DEFAULT = {"type": 0} # placeholder; device requires Option present
            req = {
                "Id": "",
                "SeqNo": "",
                "SessionID": str(session_id),
                "Option": OPTION_DEFAULT,      # <-- REQUIRED
                "Cash": {
                    "type": 0,                 # FULL collect, no Denomination list
                },
            }
            logger.info("CollectOperation req (FULL): %s", req)
            resp = svc.CollectOperation(**req)
            out = serialize_zeep_object(resp)
            out["planned_cash"] = {"Denomination": []}
            return out

        # Otherwise we need inventory to compute deltas for leave_float
        inv = self.inventory(session_id)
        raw = inv.get("raw") if isinstance(inv, dict) else None
        raw = raw or inv  # tolerate already-flattened shapes

        # Normalize Cash blocks (list or dict) and flatten all denominations
        cash_blocks = []
        if isinstance(raw, dict):
            cb = raw.get("Cash")
            if cb:
                cash_blocks = cb if isinstance(cb, list) else [cb]
        elif isinstance(raw, list):
            # extremely defensive: some serializers might return a list of sections
            for item in raw:
                if isinstance(item, dict) and "Cash" in item:
                    c = item["Cash"]
                    cash_blocks.extend(c if isinstance(c, list) else [c])

        denoms = []
        for cb in cash_blocks:
            dlist = cb.get("Denomination") if isinstance(cb, dict) else None
            if dlist:
                dlist = dlist if isinstance(dlist, list) else [dlist]
                for d in dlist:
                    if not isinstance(d, dict):
                        continue
                    try:
                        devid = int(d.get("devid", 0) or 0)
                        if not scope_ok(devid):
                            continue
                        denoms.append({
                            "cc": str(d.get("cc") or ""),
                            "fv": int(d.get("fv", 0) or 0),
                            "devid": devid,
                            "Piece": int(d.get("Piece", 0) or 0),
                            "Status": int(d.get("Status", 0) or 0),
                        })
                    except Exception:
                        # ignore malformed denomination entries
                        continue

        to_collect = []
        if plan == "leave_float":
            # keep minimum quantities per denom, collect the rest
            keep_map = {}
            if isinstance(target_float, dict) and isinstance(target_float.get("denoms"), list):
                for e in target_float["denoms"]:
                    k = (
                        int(e.get("devid", 0) or 0),
                        str(e.get("cc") or ""),
                        int(e.get("fv", 0) or 0),
                    )
                    keep_map[k] = int(e.get("min_qty", 0) or 0)

            for d in denoms:
                devid = d["devid"]
                cc = d["cc"]
                fv = d["fv"]
                qty = int(d.get("Piece", 0) or 0)
                keep = keep_map.get((devid, cc, fv), 0)
                collect_qty = max(qty - keep, 0)
                if collect_qty > 0:
                    to_collect.append({
                        "cc": cc,
                        "fv": fv,
                        "devid": devid,
                        "Piece": collect_qty,
                        "Status": 0
                    })
        else:
            raise ValueError(f"Unsupported plan: {plan}")

        if not to_collect:
            return {"result": 0, "message": "Nothing to collect", "planned_cash": {"Denomination": []}}

        OPTION_DEFAULT = {"type": 0}  # placeholder; device requires Option present
        # For partial/leave_float with explicit denominations the FCC expects type=1
        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": OPTION_DEFAULT,
            "Cash": {
                "type": 1,
                "Denomination": to_collect
            }
        }
        logger.info("CollectOperation req (LEAVE_FLOAT): %s", req)
        resp = svc.CollectOperation(**req)
        out = serialize_zeep_object(resp)
        out["planned_cash"] = {"Denomination": to_collect}
        return out

    # 10. Reset Request: ResetOperation to reset the Glory device.
    def device_reset(self, session_id: str) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        # ResetRequestType signature: Id, SeqNo, SessionID (all strings)
        req = {
            "Id": "",                 # empty is fine per your other requests
            "SeqNo": "",
            "SessionID": str(session_id),
        }
        
        try:
            logger.info("ResetOperation req: %s", req)
            resp = svc.ResetOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("ResetOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 11 Counter Clear Request
    def device_counter_clear(self, session_id: str, option_type: int = 0) -> dict:
        """
        CounterClearOperation: clears device counters.
        Default Option.type=0 (works on most firmwares).
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(option_type)},  # keep configurable
        }
        
        try:
            logger.info("CounterClearOperation req: %s", req)
            resp = svc.CounterClearOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("CounterClearOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 12. Register Event Request: RegisterEventOperation to register for event notifications.
    def register_event(self, *, url: str, port: int, destination_type: int = 0,
                       require_events: list[int] | None = None, session_id: str | None = None) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            return {"success": False, "error": "FCC SOAP service is not available"}

        if not require_events:
            require_events = list(range(1, 97))  # 1..96 inclusive

        req = {
            "Id": "1",
            "SeqNo": "1",
            "SessionID": str(session_id or "1"),
            "Url": str(url),
            "Port": int(port),
            "DestinationType": {"type": int(destination_type)},  # matches d2p1:type="0"
            "RequireEventList": {
                "RequireEvent": [{"eventno": int(e)} for e in require_events]
            },
        }

        try:
            logger.info("RegisterEventOperation req: %s", req)
            resp = svc.RegisterEventOperation(**req)
            return {"success": True, "data": serialize_zeep_object(resp)}
        except Exception as e:
            avail = [a for a in dir(svc) if not a.startswith("_")]
            logger.exception("RegisterEventOperation failed")
            self.client = None
            self.service_proxy = None
            return {"success": False, "error": f"{type(e).__name__}: {e}. Available ops: {avail}"}

    # 13. Unregister Event Request: UnRegisterEventOperation to unregister event notifications.
    def unregister_event(self, *, session_id: str | None = None) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            return {"success": False, "error": "FCC SOAP service is not available"}
        req = {"Id": "1", "SeqNo": "1", "SessionID": str(session_id or "1")}
        try:
            resp = svc.UnRegisterEventOperation(**req)
            return {"success": True, "data": serialize_zeep_object(resp)}
        except Exception as e:
            logger.exception("UnRegisterEventOperation failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
        
    #15. User Login Request
    def login_user(self, user: str, password: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        WSDL: LoginUserOperation(Id, SeqNo, User, UserPwd)
        Returns result only; many firmwares do NOT return SessionID here.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": id_value or "",
            "SeqNo": seqno_value or "",
            "User": user or "",
            "UserPwd": password or "",
        }
        try:
            logger.info("LoginUserOperation req: %s", req)
            resp = svc.LoginUserOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("LoginUserOperation SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
        
    # 20 Device Open Request
    def device_open(
        self,
        user: str,
        password: str,
        device_name: str,
        custom_id: str = "",
        id_value: str = "",
        seqno_value: str = "",
    ) -> dict:
        """
        WSDL: OpenOperation(Id, SeqNo, User, UserPwd, DeviceName, CustomId)
        Returns response containing SessionID when successful.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": id_value or "",
            "SeqNo": seqno_value or "",
            "User": user or "",
            "UserPwd": password or "",
            "DeviceName": device_name or "",
            "CustomId": custom_id or "",
        }
        try:
            logger.info("OpenOperation req: %s", req)
            resp = svc.OpenOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("OpenOperation SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 21 Device Close Request
    def device_close(self, session_id: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        WSDL: CloseOperation(Id, SeqNo, SessionID)
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": id_value or "",
            "SeqNo": seqno_value or "",
            "SessionID": str(session_id),
        }
        try:
            logger.info("CloseOperation req: %s", req)
            resp = svc.CloseOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("CloseOperation SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
        
    # 25 Manual Cashin Request
    def manual_cashin_update_total(
        self,
        *,
        session_id: str,
        amount: int | str,
        deposit_currency: list[dict] | None = None,
        foreign_amount: dict | None = None,  # {"cc": "EUR", "amount": 12345}
        id_value: str = "",
        seqno_value: str = ""
    ) -> dict:
        """
        UpdateManualDepositTotal:
          - amount: integer cents (e.g., EUR 61.50 => 6150), per spec (€1 = 100)
          - deposit_currency: optional list of {"type": int, "cc": str, "fv": int, "piece": int}
              type: 1=note, 2=coin, 3=total? (use values your device expects)
          - foreign_amount: optional {"cc": "...", "amount": int}
        Spec: UpdateManualDepositTotalRequest with Amount, optional ForeignAmount, DepositCurrency.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        # Build request body
        req = {
            "Id": str(id_value),
            "SeqNo": str(seqno_value),
            "SessionID": str(session_id),
            "Amount": str(int(amount)),  # spec uses integer minor units (e.g., 6150)  (€1=100)
        }

        if foreign_amount and foreign_amount.get("cc") and foreign_amount.get("amount") is not None:
            # Some firmwares expose ForeignAmount as a complex element {cc, Amount}
            req["ForeignAmount"] = {
                "cc": str(foreign_amount["cc"]),
                "Amount": str(int(foreign_amount["amount"])),
            }

        if deposit_currency:
            # Expecting a list of dicts with keys: type, cc, fv, piece
            # -> <DepositCurrency><Currency type=".." cc=".." fv=".." piece=".."/></DepositCurrency>
            req["DepositCurrency"] = {
                "Currency": [
                    {
                        "type": int(row["type"]),
                        "cc": str(row["cc"]),
                        "fv": int(row["fv"]),
                        "piece": int(row["piece"]),
                    }
                    for row in deposit_currency
                ]
            }

        # Try likely operation names from vendor stacks
        op_candidates = [
            "UpdateManualDepositTotal",
            "UpdateManualDepositTotalOperation",
            "ManualCashinUpdateTotal",
            "ManualCashin",
        ]

        try:
            logger.info("ManualCashinUpdateTotal req: %s", req)
            resp = self._call_first_available(svc, op_candidates, **req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("ManualCashinUpdateTotal SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 29 Power control Request
    def control_power(self, session_id: str, action: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        Request device power control.
          action: "shutdown" | "reboot"
        Prefers dedicated ops if present; otherwise falls back to a generic power-control op
        with Option.type mapped per action.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
    
        action_norm = (action or "").strip().lower()
        if action_norm not in ("shutdown", "reboot"):
            raise ValueError("action must be 'shutdown' or 'reboot'")

        # Map to Option.type when using a generic operation
        opt_type = 1 if action_norm == "shutdown" else 2
    
        req = {
            "Id": str(id_value),
            "SeqNo": str(seqno_value),
            "SessionID": str(session_id),
            "Option": {"type": int(opt_type)},
        }
        logger.info("ControlPower(%s) req: %s", action_norm, req)
    
        # Enumerate available ops
        try:
            ops = []
            cl = self.client
            for binding in cl.wsdl.bindings.values():
                try:
                    ops.extend(binding._operations.keys())
                except Exception:
                    pass
            ops = sorted(set(ops))
            logger.info("SOAP ops available: %s", ops)
        except Exception:
            ops = []
    
        # Prefer explicit action-specific operations if present
        if action_norm == "shutdown":
            specific = [
                "ShutdownOperation",
                "PowerOffOperation",
                "DeviceShutdown",
                "ShutdownRequest",
            ]
        else:  # reboot
            specific = [
                "RebootOperation",
                "RestartOperation",
                "PowerRestartOperation",
                "ResetPowerOperation",
            ]
    
        # Generic fallbacks seen on some firmwares
        generic = [
            "ControlPowerOperation",
            "PowerControlOperation",
            "RequestPowerControl",
            "SystemControlOperation",
        ]
    
        candidates = [name for name in specific + generic if name in ops]
        if not candidates:
            raise AttributeError(f"No power-control operation found for '{action_norm}'. Available ops: {ops}")
    
        # Call the first available op
        return serialize_zeep_object(self._call_first_available(svc, candidates, **req))

    # 31 Lock Unit Request
    def lock_unit(self, session_id: str, target: str | None = None, units: list[dict] | None = None) -> dict:
        """Lock notes/coins via Option.type. units are ignored (for WSDL compliance)."""
        t = (target or "").strip().lower() or None
        opt_type = TARGET_TO_TYPE.get(t, 0)

        if units:
            logger.info("LockUnit requested units (ignored by SOAP): %s", units)

        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(opt_type)},
        }
        
        try:
            logger.info("LockUnitOperation req: %s", req)
            resp = svc.LockUnitOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("LockUnitOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 32 Unlock Unit Request
    def unlock_unit(self, session_id: str, target: str | None = None, units: list[dict] | None = None) -> dict:
        """Unlock notes/coins via Option.type. units are ignored (for WSDL compliance)."""
        t = (target or "").strip().lower() or None
        opt_type = TARGET_TO_TYPE.get(t, 0)

        if units:
            logger.info("UnLockUnit requested units (ignored by SOAP): %s", units)

        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(opt_type)},
        }
        
        try:
            logger.info("UnLockUnitOperation req: %s", req)
            resp = svc.UnLockUnitOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("UnLockUnitOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
    
    # 35 OpenExitCoverOperation: Opens the exit cover.
    def exit_cover_open(self, session_id: str) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {"Id": "", "SeqNo": "", "SessionID": str(session_id)}
        
        try:
            logger.info("OpenExitCoverOperation req: %s", req)
            resp = svc.OpenExitCoverOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("OpenExitCoverOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 36 CloseExitCoverOperation : Closes the exit cover.
    def exit_cover_close(self, session_id: str) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {"Id": "", "SeqNo": "", "SessionID": str(session_id)}
        
        try:
            logger.info("CloseExitCoverOperation req: %s", req)
            resp = svc.CloseExitCoverOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("CloseExitCoverOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # 37 Start Replenishment From Entrance Request
    def start_replenish_entrance(self, session_id: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        Start Replenishment From Entrance.
        WSDL shape is minimal: { Id, SeqNo, SessionID } (no Option, no Cash).
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": str(id_value),
            "SeqNo": str(seqno_value),
            "SessionID": str(session_id),
        }
        logger.info("StartReplenishmentFromEntrance req: %s", req)

        # Try common vendor method names (firmware variants)
        op_candidates = [
            "StartReplenishmentFromEntrance",        # most common
            "StartReplenishmentFromEntranceOperation",
            "StartReplenishFromEntrance",
            "ReplenishmentFromEntranceStart",
        ]
        
        try:
            logger.info("StartReplenishmentFromEntrance req: %s", req)
            resp = self._call_first_available(svc, op_candidates, **req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("StartReplenishmentFromEntrance SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
    
    # 38 End Replenishment From Entrance Request
    def end_replenish_entrance(self, session_id: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        End (commit) Replenishment From Entrance.
        Spec requires only { Id, SeqNo, SessionID } — no Option/Cash.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": str(id_value),
            "SeqNo": str(seqno_value),
            "SessionID": str(session_id),
        }
        logger.info("EndReplenishmentFromEntrance req: %s", req)

        op_candidates = [
            "EndReplenishmentFromEntrance",              # common
            "EndReplenishmentFromEntranceOperation",
            "EndReplenishFromEntrance",
            "ReplenishmentFromEntranceEnd",
        ]
        
        try:
            logger.info("EndReplenishmentFromEntrance req: %s", req)
            resp = self._call_first_available(svc, op_candidates, **req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("EndReplenishmentFromEntrance SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    #39 Replenishment From Entrance Cancel Request
    def cancel_replenish_entrance(self, session_id: str, id_value: str = "", seqno_value: str = "") -> dict:
        """
        Cancel (abort) Replenishment From Entrance.
        Minimal body: { Id, SeqNo, SessionID } — no Option/Cash.
        Heuristics: find any op with 'cancel' + ('replenish' or 'entrance'), else try generic cancels.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {"Id": str(id_value), "SeqNo": str(seqno_value), "SessionID": str(session_id)}
        logger.info("CancelReplenishmentFromEntrance (adaptive) req: %s", req)

        # 1) enumerate available ops
        try:
            ops = []
            cl = self.client
            for binding in cl.wsdl.bindings.values():
                try:
                    ops.extend(binding._operations.keys())
                except Exception:
                    pass
            ops = sorted(set(ops))
            logger.info("SOAP ops available: %s", ops)
        except Exception:
            ops = []

        # 2) dynamic matches first
        dyn = []
        for name in ops:
            ln = name.lower()
            if "cancel" in ln and ("replenish" in ln or "entrance" in ln):
                dyn.append(name)

        # 3) static fallbacks by vendor patterns
        fallbacks = [
            "CancelReplenishmentFromEntrance",
            "CancelReplenishmentFromEntranceOperation",
            "CancelReplenishFromEntrance",
            "ReplenishmentFromEntranceCancel",
            "AbortReplenishmentFromEntrance",
            # generic
            "CancelOperation",
            "AbortOperation",
        ]

        candidates = dyn + [n for n in fallbacks if n in ops]

        # 4) try candidates
        if candidates:
            return serialize_zeep_object(self._call_first_available(svc, candidates, **req))

        # 5) as a last resort, if the firmware does not have a true "cancel", many stacks accept "End..."
        # as a safe termination (commit/close) when no cash was loaded yet. Only do this if the op exists.
        end_names = [n for n in ops if "endreplenishment" in n.lower() and "entrance" in n.lower()]
        if end_names:
            logger.warning("No explicit cancel op found; falling back to %s", end_names[0])
            return serialize_zeep_object(getattr(svc, end_names[0])(**req))

        # 6) nothing usable
        raise AttributeError(f"No cancel-like operation found. Available ops: {ops}")


#-------------------------------

    ### CounterClearOperation: Clears transaction counters.
    def device_counter_clear(self, session_id: str) -> dict:
        """
        Call CounterClearOperation to clear device counters.
        This model's WSDL requires Option; use type=0.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
    
        req = {
            "Id": "",                 # keep empty like other ops
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": 0},    # <-- REQUIRED by your WSDL
        }
        
        try:
            logger.info("CounterClearOperation req: %s", req)
            resp = svc.CounterClearOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("CounterClearOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    ### OccupyOperation: Locks the FCC for exclusive use by a session.
    # def occupy(self, session_id: str) -> dict:
    #     """
    #     Occupy (lock) the FCC for the given session.
    #     WSDL: OccupyOperation(Id, SeqNo, SessionID)
    #     """
    #     svc = self.get_service_instance()
    #     if svc is None:
    #         raise RuntimeError("FCC SOAP service is not available")
    #     req = {"Id": "", "SeqNo": "", "SessionID": str(session_id)}
    #     logger.info("OccupyOperation req: %s", req)
    #     resp = svc.OccupyOperation(**req)
    #     return serialize_zeep_object(resp)
    def verify_collection_container(self, session_id: str, devid: int) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "devid": int(devid),
        }
        logger.info("VerifyCollectionContainerOperation req: %s", req)
        resp = svc.VerifyCollectionContainerOperation(**req)
        return serialize_zeep_object(resp)


    ### ReleaseOperation: Unlocks the FCC from a session.
    def release(self, session_id: str) -> dict:
        """
        Release (unlock) the FCC for the given session.
        WSDL: ReleaseOperation(Id, SeqNo, SessionID)
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {"Id": "", "SeqNo": "", "SessionID": str(session_id)}
        
        try:
            logger.info("ReleaseOperation req: %s", req)
            resp = svc.ReleaseOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("ReleaseOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e
        
    ### GetStatus: Retrieves the current operational status of the FCC machine.
    def status_request(self, session_id: str | None = None, *, with_cash: bool = True, with_verify: bool = True) -> dict:
        """
        Calls GetStatus (this binding doesn't expose 'StatusRequest').
        Sends a StatusRequestType-shaped body:
          Option.type = 1 (include cash info)
          RequireVerification.type = 1 (include verification details)
        """
        svc = self.get_service_instance()
        if svc is None:
            return {"success": False, "error": "FCC SOAP service is not available"}

        req = {
            "Id": "1",
            "SeqNo": "1",
            "SessionID": str(session_id or ""),       # your sample showed blanks are fine
            "Option": {"type": 1 if with_cash else 0},
            "RequireVerification": {"type": 1 if with_verify else 0},
        }

        try:
            # This binding uses GetStatus (not StatusRequest)
            resp = svc.GetStatus(**req)
            data = serialize_zeep_object(resp)

            # Build a simple counted summary for your UI
            counted_by_fv, counted_total = {}, 0
            cash = (data or {}).get("Cash") or {}
            denoms = cash.get("Denomination") or []
            for d in denoms:
                fv = int(d.get("fv", 0) or 0)
                pc = int(d.get("Piece", 0) or 0)
                if fv > 0 and pc > 0:
                    counted_by_fv[str(fv)] = counted_by_fv.get(str(fv), 0) + pc
                    counted_total += fv * pc

            return {
                "success": True,
                "raw": data,
                "state": (data.get("Status") or {}).get("Code"),
                "counted": {"by_fv": counted_by_fv, "thb": counted_total},
            }

        except Exception as e:
            logger.exception("GetStatus failed")
            return {"success": False, "error": f"{type(e).__name__}: {e}"}

    ### CheckInventory: Get current cash inventory.
    # def get_inventory(self, session_id: str) -> dict:
    #     """
    #     Calls the InventoryOperation to get a detailed list of cash in the machine.
    #     """
    #     service = self.get_service_instance()
    #     if service is None:
    #         return {"success": False, "error": "FCC SOAP service is not available."}

    #     try:
    #         logger.info(f"Requesting inventory for SessionID: {session_id}")
    #         # The WSDL requires an 'Option' type for this operation.
    #         # Type '1' typically requests a detailed inventory.
    #         payload = {
    #             'Id': str(int(time.time())),
    #             'SeqNo': self._next_seq_no(),
    #             'SessionID': session_id,
    #             'Option': {'type': 0}
    #         }
            
    #         response = service.InventoryOperation(**payload)
    #         serialized_data = serialize_zeep_object(response)

    #         if response and response.result == 0:
    #             logger.info("InventoryOperation successful.")
    #             return {"success": True, "data": serialized_data}
    #         else:
    #             error_msg = f"Glory InventoryOperation failed. Result: {serialized_data.get('result', 'N/A')}"
    #             return {"success": False, "error": error_msg, "data": serialized_data}

    #     except Exception as e:
    #         logger.error(f"Error calling InventoryOperation: {e}")
    #         return {"success": False, "error": str(e)}


    ### CashoutOperation: Dispense cash.
    def cashout_execute(self,
                        session_id: str,
                        currency: str,
                        denominations_list: list[dict],
                        *,
                        note_destination: str | None = None,
                        coin_destination: str | None = None,
                        coin_values: set[int] | None = None,
                        id_value: str = "",
                        seqno_value: str = "") -> dict:
        """
        CashoutOperation: dispense exact denominations.

        Args:
          session_id        : Glory SessionID (e.g. "1")
          currency          : e.g. "THB" (or "EUR" as in your sample)
          denominations_list: list of dicts. Each item must contain:
                              - value (int), qty (int)
                              - OPTIONAL device (1=notes, 2=coins)
          note_destination  : optional site-specific destination string (if required)
          coin_destination  : optional site-specific destination string (if required)
          coin_values       : set of integers to infer coins when 'device' not provided
                              default {1,2,5,10} (THB typical). Override for your site.
          id_value          : value for <Id>; default empty string to match your sample
          seqno_value       : value for <SeqNo>; default empty string to match your sample

        Returns:
          dict: zeep-serialized CashoutResponse
        """
        logger.info(f"Attempting to execute cash-out for SID {session_id}.")

        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        # Default coin inference for THB. Override for other currencies/sites.
        if coin_values is None:
            coin_values = {1, 2, 5, 10}

        # Build <Denomination> list
        denoms = []
        for i, d in enumerate(denominations_list or []):
            try:
                fv = int(d["value"])
                qty = int(d["qty"])
            except Exception:
                raise ValueError(f"Invalid denomination at index {i}: require integer 'value' and 'qty'") from None
            if fv <= 0 or qty <= 0:
                raise ValueError(f"Invalid denomination at index {i}: value/qty must be positive")

            # Prefer explicit 'device' if given, else infer
            if "device" in d:
                devid = int(d["device"])
                if devid not in (1, 2):
                    raise ValueError(f"Invalid device at index {i}: must be 1 (notes) or 2 (coins)")
            else:
                devid = 2 if fv in coin_values else 1

            denoms.append({
                "cc": str(currency).upper(),
                "fv": fv,
                "devid": devid,
                "Piece": qty,
                "Status": 0,  # payout item
            })

        # Build <Cash> with type="2" to match your sample
        cash_obj = {
            "type": 2,                 # IMPORTANT: matches your sample (d2p1:type="2")
            "Denomination": denoms,
        }
        if note_destination:
            cash_obj["note_destination"] = note_destination
        if coin_destination:
            cash_obj["coin_destination"] = coin_destination

        req = {
            "Id": str(id_value),       # "" to match sample; or "1" if you prefer
            "SeqNo": str(seqno_value), # "" to match sample; or "1"
            "SessionID": str(session_id),
            "Cash": cash_obj,
        }

        try:
            logger.info(f"Calling CashoutOperation with payload: {req}")
            resp = svc.CashoutOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("CashoutOperation SOAP call failed")
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    def cash_availability(self, session_id: str, currency: str | None = None) -> dict:
        """
        Return per-denomination availability booleans for fast UI toggling.
        'available' = has stock (Piece > 0) AND status indicates usable.
        """
        inv = self.inventory(session_id)
        raw = inv.get("raw") or inv  # support both wrapped and bare responses

        # Normalize Cash blocks (type=3 = stock snapshot)
        cash_blocks = raw.get("Cash")
        if not cash_blocks:
            return {"currency": currency, "notes": [], "coins": [], "raw": raw}

        # If 'Cash' is a single dict, wrap as list
        if isinstance(cash_blocks, dict):
            cash_blocks = [cash_blocks]

        # Pick type=3 as the live inventory snapshot
        snap = next((c for c in cash_blocks if c.get("type") == 3), None)
        if not snap:
            # Fallback: use the first block if type info missing
            snap = cash_blocks[0]

        denoms = snap.get("Denomination") or []
        if isinstance(denoms, dict):
            denoms = [denoms]

        # Build a quick lookup for max capacity from CashUnits (optional)
        units = raw.get("CashUnits") or []
        if isinstance(units, dict):
            units = [units]
        unit_by_dev_value = {}  # (devid, fv) -> max
        for cu in units:
            devid = cu.get("devid")
            for slot in cu.get("CashUnit") or []:
                # Some CashUnit entries carry a single Denomination or a list
                dlist = slot.get("Denomination") or []
                if isinstance(dlist, dict):
                    dlist = [dlist]
                for d in dlist:
                    fv = d.get("fv")
                    unit_by_dev_value[(devid, fv)] = slot.get("max")

        def ok_status(st: int | None) -> bool:
            # Observed meanings (from device traces):
            # 2 = normal/available, 1 = available but attention, 0 = disabled/empty
            return st in (1, 2)

        out_notes, out_coins = [], []
        for d in denoms:
            cc   = d.get("cc")
            fv   = int(d.get("fv", 0) or 0)
            dev  = int(d.get("devid", 0) or 0)  # 1=notes, 2=coins (per your logs)
            qty  = int(d.get("Piece", 0) or 0)
            st   = int(d.get("Status", 0) or 0)
            if currency and cc and cc.upper() != currency.upper():
                continue

            max_cap = unit_by_dev_value.get((dev, fv))
            available = (qty > 0) and ok_status(st)

            reason = []
            if qty <= 0:
                reason.append("empty")
            if not ok_status(st):
                reason.append("disabled")

            row = {
                "cc": cc, "device": dev, "value": fv,
                "qty": qty, "status": st,
                "max": max_cap,
                "available": bool(available),
                "reason": reason or None,
            }
            (out_coins if dev == 2 else out_notes).append(row)

        return {
            "currency": (currency or (denoms[0].get("cc") if denoms else None)),
            "notes": sorted(out_notes, key=lambda r: r["value"]),
            "coins": sorted(out_coins, key=lambda r: r["value"]),
            "raw": raw,
        }
    
    def log_read(self, session_id: str, **filters) -> dict:
        """
        Read device logs for a time window/types.
        filters may include: from_ts, to_ts, categories/types, cursor, limit...
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            # TODO: Map your filters into the actual WSDL shape:
            # e.g. "Period": {"From": "...", "To": "..."},
            # "Option": {"type": 0}, "Category": {...}, "Cursor": "...", etc.
        }
        
        try:
            logger.info("LogReadOperation req: %s", req)
            resp = svc.LogReadOperation(**req)  # name per WSDL
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("LogReadOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    # def cashout_execute(self, session_id, currency, denominations_list, request_id):
    #     """
    #     CashoutOperation: Dispense cash.

    #     Args:
    #         session_id (str): Glory session ID (e.g., "1")
    #         currency (str): ISO currency code (e.g., "THB")
    #         denominations_list (list[dict]): final list of denoms, each {"value": int, "qty": int}
    #         request_id (str|int): caller-supplied id (for logging/trace only)

    #     Returns:
    #         dict: {"success": bool, "data": <serialized_response>} on OK,
    #               {"success": False, "error": str, "data": <serialized_response_or_none>} on failure
    #     """
    #     logger.info(f"Attempting to execute cash-out for SID {session_id}. req_id={request_id}")

    #     svc = self.get_service_instance()
    #     if svc is None:
    #         err = "FCC SOAP service is not available"
    #         logger.error(err)
    #         return {"success": False, "error": err}

    #     try:
    #         # Typical THB coin face values; adjust mapping if needed for your installation.
    #         COIN_VALUES = {1, 2, 5, 10}

    #         # Build Denomination[] with required fields
    #         denoms = []
    #         for idx, denom in enumerate(denominations_list or []):
    #             try:
    #                 fv = int(denom["value"])
    #                 qty = int(denom["qty"])
    #             except Exception:
    #                 msg = f"Invalid denomination at index {idx}: requires integer 'value' and 'qty'"
    #                 logger.error(msg)
    #                 return {"success": False, "error": msg}

    #             if fv <= 0 or qty <= 0:
    #                 msg = f"Invalid denomination at index {idx}: value/qty must be positive"
    #                 logger.error(msg)
    #                 return {"success": False, "error": msg}

    #             devid = 2 if fv in COIN_VALUES else 1  # 2=coins, 1=notes (common mapping)
    #             denoms.append({
    #                 "cc": str(currency).upper(),
    #                 "fv": fv,
    #                 "devid": devid,
    #                 "Piece": qty,
    #                 "Status": 0,   # payout item
    #             })

    #         # Build the SOAP payload.  IMPORTANT: Cash.type is a plain integer field.
    #         payload = {
    #             "Id": "1",
    #             "SeqNo": "1",
    #             "SessionID": str(session_id),
    #             "Cash": {
    #                 "type": 6,                  # 6 = payout list (works across common firmware)
    #                 "Denomination": denoms,
    #                 # "note_destination": "...",  # Optional, only if your site uses it
    #                 # "coin_destination": "..."
    #             },
    #         }

    #         logger.info(f"Calling CashoutOperation with payload: {payload}")
    #         resp = svc.CashoutOperation(**payload)

    #         # Normalize Zeep object to plain dict for logging / API response
    #         safe = serialize_zeep_object(resp)

    #         # Result attribute can appear as int/string; treat "0" as success
    #         result_attr = (
    #             safe.get("result")
    #             or (safe.get("_attr", {}).get("result") if isinstance(safe.get("_attr"), dict) else None)
    #             or safe.get("@result")
    #         )

    #         ok = str(result_attr) == "0"
    #         if ok:
    #             logger.info("CashoutOperation succeeded (result=0).")
    #             return {"success": True, "data": safe}
    #         else:
    #             msg = f"Glory CashoutOperation NG (result={result_attr})"
    #             logger.warning(msg)
    #             return {"success": False, "error": msg, "data": safe}

    #     except Exception as e:
    #         logger.error(f"Error calling CashoutOperation: {e}", exc_info=True)
    #         return {"success": False, "error": str(e)}

    # ### OccupyOperation: Lock/occupy the unit for exclusive control.
    # def occupy(self, session_id: str) -> dict:
    #     """
    #     Lock/occupy the unit for exclusive control.
    #     """
    #     svc = self.get_service_instance()
    #     if svc is None:
    #         raise RuntimeError("FCC SOAP service is not available")
    #     req = {"Id": "1", "SeqNo": "1", "SessionID": str(session_id)}
    #     logger.info("OccupyOperation req: %s", req)
    #     try:
    #         resp = svc.OccupyOperation(**req)
    #         return serialize_zeep_object(resp)
    #     except Exception as e:
    #         logger.error("OccupyOperation failed: %s", e, exc_info=True)
    #         raise

    # def release(self, session_id: str) -> dict:
    #     """
    #     Release the unit after operations complete.
    #     """
    #     svc = self.get_service_instance()
    #     if svc is None:
    #         raise RuntimeError("FCC SOAP service is not available")
    #     req = {"Id": "1", "SeqNo": "1", "SessionID": str(session_id)}
    #     logger.info("ReleaseOperation req: %s", req)
    #     try:
    #         resp = svc.ReleaseOperation(**req)
    #         return serialize_zeep_object(resp)
    #     except Exception as e:
    #         logger.error("ReleaseOperation failed: %s", e, exc_info=True)
    #         raise

    # def open_exit_cover(self, session_id: str) -> dict:
    #     """
    #     Open the exit cover (some sites require it before payout).
    #     """
    #     svc = self.get_service_instance()
    #     if svc is None:
    #         raise RuntimeError("FCC SOAP service is not available")
    #     req = {"Id": "1", "SeqNo": "1", "SessionID": str(session_id)}
    #     logger.info("OpenExitCoverOperation req: %s", req)
    #     try:
    #         resp = svc.OpenExitCoverOperation(**req)
    #         return serialize_zeep_object(resp)
    #     except Exception as e:
    #         logger.error("OpenExitCoverOperation failed: %s", e, exc_info=True)
    #         raise

    # def close_exit_cover(self, session_id: str) -> dict:
    #     """
    #     Close the exit cover after payout.
    #     """
    #     svc = self.get_service_instance()
    #     if svc is None:
    #         raise RuntimeError("FCC SOAP service is not available")
    #     req = {"Id": "1", "SeqNo": "1", "SessionID": str(session_id)}
    #     logger.info("CloseExitCoverOperation req: %s", req)
    #     try:
    #         resp = svc.CloseExitCoverOperation(**req)
    #         return serialize_zeep_object(resp)
    #     except Exception as e:
    #         logger.error("CloseExitCoverOperation failed: %s", e, exc_info=True)
    #         raise


    ### Temporary method for compatibility with older code samples
    def tmp_register_event(self, *, url: str, port: int, amount_thb: int, destination_type: int = 0, require_events: list[int] | None = None, session_id: str | None = None) -> dict:
        """
        RegisterEventRequestType: tell the FCC where to push events.
        - url: your callback IP (e.g., '192.168.0.1')
        - port: your listener port (e.g., 55562)
        - destination_type: 0 matches your sample (usually TCP)
        - require_events: list of ints; defaults to 1..96
        - session_id: some stacks ignore it; your sample uses '1'
        """
        svc = self.get_service_instance()
        if svc is None:
            return {"success": False, "error": "FCC SOAP service is not available"}

        if not require_events:
            require_events = list(range(1, 97))  # 1..96 inclusive

        uniq = str(int(time.time() * 1000) % 10**9)
        req = {
            "Id": uniq,
            "SeqNo": "1",
            "SessionID": str(session_id or "1"),  # your sample used "1"
            "Url": str(url),
            "Port": int(port),
            "Amount": str(int(amount_thb)),          # REST edge uses THB as integer
            "DestinationType": {"type": int(destination_type)},
            "RequireEventList": {
                "RequireEvent": [{"eventno": int(e)} for e in require_events]
            },
        }

        # Try common method names for Register Event
        candidates = ["RegisterEvent", "RegisterEventRequest", "GetRegisterEvent", "EventRegister"]
        last_err = None
        for name in candidates:
            if not hasattr(svc, name):
                continue
            try:
                logger.info("Calling %s with %s", name, req)
                resp = getattr(svc, name)(**req)
                data = serialize_zeep_object(resp)
                return {"success": True, "data": data}
            except (Fault, TransportError, Exception) as e:
                logger.exception("RegisterEvent via %s failed", name)
                last_err = str(e)

        avail = [a for a in dir(svc) if not a.startswith("_")]
        return {"success": False, "error": f"RegisterEvent not found or failed: {last_err}. Available ops: {avail}"}

    def lock_unit(self, session_id: str, target: str | None = None, units: list[dict] | None = None) -> dict:
        """Lock notes/coins via Option.type. units are ignored (for WSDL compliance)."""
        t = (target or "").strip().lower() or None
        opt_type = TARGET_TO_TYPE.get(t, 0)

        if units:
            logger.info("LockUnit requested units (ignored by SOAP): %s", units)

        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(opt_type)},
        }
        logger.info("LockUnitOperation req: %s", req)
        resp = svc.LockUnitOperation(**req)
        return serialize_zeep_object(resp)

    def unlock_unit(self, session_id: str, target: str | None = None, units: list[dict] | None = None) -> dict:
        """Unlock notes/coins via Option.type. units are ignored (for WSDL compliance)."""
        t = (target or "").strip().lower() or None
        opt_type = TARGET_TO_TYPE.get(t, 0)

        if units:
            logger.info("UnLockUnit requested units (ignored by SOAP): %s", units)

        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "Option": {"type": int(opt_type)},
        }
        
        try:
            logger.info("UnLockUnitOperation req: %s", req)
            resp = svc.UnLockUnitOperation(**req)
            return serialize_zeep_object(resp)
        except Exception as e:
            logger.exception("UnLockUnitOperation SOAP call failed")
            # Invalidate client so next call will try to reconnect
            self.client = None
            self.service_proxy = None
            raise RuntimeError("FCC SOAP service is not available") from e

    ######################## OLD OPERATIONS ########################
    # LoginUserOperation: Authenticates a user with the FCC machine.
    def login_user(self, user: str) -> dict:
        """
        Calls the 'LoginUserOperation' to authenticate a user with the FCC machine.
        
        Args:
            user (str): The Glory username (e.g., gs_cashier).
            password (str): The corresponding Glory password.

        Returns:
            dict: { "success": bool, "data": { "SessionID": "...", ... } } or { "error": str }
        """
        service = self.get_service_instance()
        if service is None:
            logger.error("FCC SOAP service is not available. Cannot perform login.")
            return {"success": False, "error": "FCC SOAP service is not available."}

        try:
            logger.info(f"Attempting to log in Glory user '{user}'.")

            # Build SOAP request payload (adjust keys if WSDL differs)
            response = service.LoginUserOperation(
                User=user,
                Id=str(int(time.time())),   # Unique transaction id
                SeqNo=self._next_seq_no(),  # Sequence number (auto increment)
            )

            serialized = serialize_zeep_object(response)
            session_id = serialized.get("SessionID")

            if not session_id:
                logger.warning(f"Login for user '{user}' returned no SessionID.")
                return {"success": False, "error": "No SessionID returned by Glory."}

            logger.info(f"Login successful for '{user}' → SessionID={session_id}")
            return {"success": True, "data": serialized}

        except Fault as fault:
            logger.error(f"SOAP Fault calling LoginUserOperation for user '{user}': {fault.message}")
            return {"success": False, "error": f"SOAP Fault: {fault.message}"}
        except Exception as e:
            logger.exception(f"Error calling LoginUserOperation for user '{user}': {e}")
            return {"success": False, "error": str(e)}

    # GetStatus: Retrieves the current operational status of the FCC machine.
    # def get_status(self, session_id="GasERP"):
    #     """
    #     Calls the 'GetStatus' operation on the FCC BrueBoxService.
    #     This operation retrieves the current operational status of the FCC machine.

    #     Returns:
    #         dict: A dictionary containing 'success' status and 'data' (serialized response)
    #               or 'error' message.
    #     """
    #     service = self.get_service_instance()
    #     if service is None:
    #         return {"success": False, "error": "FCC SOAP service is not available."}
    #     try:
    #         logger.info("Sending GetStatus request to FCC.")

    #         # Parameters for StatusRequest, based on WSDL and previous successful interactions.
    #         # 'Id', 'SeqNo', 'SessionID' are typically strings.
    #         # 'Option' and 'RequireVerification' are typically integers (0 for default/no option).
    #         response = service.GetStatus(
    #             Id=str(int(time.time())),
    #             SeqNo=self._next_seq_no(),
    #             SessionID=session_id, # Example SessionID
    #             Option=0,
    #             RequireVerification=0
    #         )

    #         logger.info("GetStatus successful.")
    #         # Serialize the Zeep response object for easier use in Flask's JSON response
    #         # NOTE: Need to comment out debug logs for production
    #         logger.debug("Serialized GetStatus response:") # Comment for production
    #         logger.debug(serialize_zeep_object(response)) # Comment for production

    #         return {"success": True, "data": serialize_zeep_object(response)}
    #     except Fault as fault:
    #         # Catch specific SOAP Faults (errors returned by the SOAP service itself)
    #         logger.error(f"SOAP Fault calling GetStatus: {fault.message}")
    #         return {"success": False, "error": f"SOAP Fault: {fault.message}"}
    #     except Exception as e:
    #         # Catch any other unexpected exceptions during the SOAP call
    #         logger.error(f"Error calling GetStatus: {e}")
    #         return {"success": False, "error": str(e)}

    # RegisterEvent: Checks connectivity and operational status of the FCC machine.
    def get_register_event(self):
        """
        Calls the 'RegisterEventOperation' operation on the FCC BrueBoxService.
        This operation checks the connectivity and operational status of the FCC machine.
        Returns:
            dict: A dictionary containing 'success' status and 'data' (serialized response)
                    or 'error' message.
        """
        service = self.get_service_instance()
        if service is None:
            return {"success": False, "error": "FCC SOAP service is not available."}
        try:
            logger.info("Sending GetHeartbeat request to FCC.")
            # Parameters for HeartbeatRequest, based on WSDL and previous successful interactions.
            response = service.RegisterEventOperation( 
                Id='0',            # Example transaction ID
                SeqNo='',         # Example sequence number
                SessionID='ABC123', # Example session ID
                Port='0', # Port is typically an integer, 0 for default
                DestinationType='1', # DestinationType is typically an integer, 0 for default
                Encryption='1', # EncryptionType is typically an integer, 0 for default
                RquireEventList={'RequireEvent': ['1, 2, 3, 48, 50']} # Example event list, adjust as needed
            )
            logger.info("GetStatus successful.")
            # Serialize the Zeep response object for easier use in Flask's JSON response
            # NOTE: Need to comment out debug logs for production
            logger.debug("Serialized GetStatus response:") # Comment for production
            logger.debug(serialize_zeep_object(response)) # Comment for production
            return {"success": True, "data": serialize_zeep_object(response)}
        except Fault as fault:
            # Catch specific SOAP Faults (errors returned by the SOAP service itself)
            logger.error(f"SOAP Fault calling GetHeartbeat: {fault.message}")
            return {"success": False, "error": f"SOAP Fault: {fault.message}"}
        except Exception as e:
            # Catch any other unexpected exceptions during the SOAP call
            logger.error(f"Error calling GetHeartbeat: {e}")
            return {"success": False, "error": str(e)}

    # OpenCashIn: Initiates a cash-in transaction with the specified amount, currency, and account ID.
    def open_cash_in(self, amount: str, currency_code: str, account_id: str):
        """
        Calls the 'StartCashinOperation' operation on the FCC BrueBoxService.
        Initiates a cash-in transaction with the specified amount, currency, and account ID.

        Args:
            amount (str): The amount for the cash-in operation (as a string).
            currency_code (str): The currency code (e.g., "JPY", "USD").
            account_id (str): The account identifier for the transaction.
                              Note: 'AccountID' is not a direct parameter for StartCashinOperation
                              based on the WSDL. It might be used in a later step (e.g., EndCashin)
                              or for internal tracking. We'll include it in the log for now.

        Returns:
            dict: A dictionary containing 'success' status and 'data' (serialized response)
                  or 'error' message.
        """
        service = self.get_service_instance()
        if service is None:
            return {"success": False, "error": "FCC SOAP service is not available."}
        try:
            logger.info(f"Sending StartCashinOperation request for Amount: {amount}, Currency: {currency_code}, Account: {account_id}.")

            # Parameters for StartCashinOperation.
            # Based on the WSDL, StartCashinRequestType includes:
            # Id (optional), SeqNo (required), SessionID (optional), Option (optional), ForeignCurrency (optional)
            # The 'Amount', 'CurrencyCode', 'AccountID' you provided are not direct parameters
            # for StartCashinOperation based on the WSDL structure.
            # You might need to adjust your API's input or the SOAP call if these are required
            # for this specific operation. For now, we'll use generic values.
            response = service.StartCashinOperation( # CORRECTED OPERATION NAME HERE
                Id='10',            # Example transaction ID
                SeqNo='11',         # Example sequence number
                SessionID='XYZ456', # Example session ID
                # Option=0, # If you have a specific CashinOptionType to pass
                # ForeignCurrency={'Rate': '1.0', 'cc': 'USD'} # If foreign currency is applicable
            )

            logger.info("StartCashinOperation successful.")
            return {"success": True, "data": serialize_zeep_object(response)}
        except Fault as fault:
            logger.error(f"SOAP Fault calling StartCashinOperation: {fault.message}")
            return {"success": False, "error": f"SOAP Fault: {fault.message}"}
        except Exception as e:
            logger.error(f"Error calling StartCashinOperation: {e}")
            return {"success": False, "error": str(e)}
        
    def verify_collection_container(self, session_id: str, devid: int = 1, serial: str | None = None, val: int = 1) -> dict:
        """
        Satisfy RequireVerifyCollectionContainerInfos. devid: 1=notes, 2=coins.
        """
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")

        req = {
            "Id": "",
            "SeqNo": "",
            "SessionID": str(session_id),
            "CollectionContainer": {
                "devid": int(devid),
                "val": int(val),                # 1 = verify / present
            }
        }
        if serial is not None:
            req["CollectionContainer"]["SerialNo"] = str(serial)

        # Try common vendor op names
        return serialize_zeep_object(
            self._call_first_available(
                svc,
                [
                    "VerifyCollectionContainerOperation",
                    "CollectionContainerVerifyOperation",
                    "VerifyCollectionContainer",
                    "CollectionContainerVerificationOperation",
                ],
                **req
            )
        )

    def verify_mix_stacker(self, session_id: str, devid: int = 1, val: int = 0) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {"Id":"", "SeqNo":"", "SessionID": str(session_id), "MixStacker": {"devid": int(devid), "val": int(val)}}
        return serialize_zeep_object(
            self._call_first_available(
                svc,
                ["VerifyMixStackerOperation", "MixStackerVerifyOperation", "VerifyMixStacker"],
                **req
            )
        )

    def verify_denomination(self, session_id: str, devid: int = 1, cash: dict | None = None, val: int = 0) -> dict:
        svc = self.get_service_instance()
        if svc is None:
            raise RuntimeError("FCC SOAP service is not available")
        req = {"Id":"", "SeqNo":"", "SessionID": str(session_id), "DenominationVerify": {"devid": int(devid), "val": int(val)}}
        if cash:
            req["DenominationVerify"]["Cash"] = cash   # optional, only if WSDL wants it
        return serialize_zeep_object(
            self._call_first_available(
                svc,
                ["VerifyDenominationOperation", "DenominationVerifyOperation", "VerifyDenomination"],
                **req
            )
        )

    #-------------------------------------------------------------
        
        ##############
        
        # """
        # Calls the FCC SOAP ChangeOperation.
        # Args:
        #     amount (int): total amount requested.
        #     denominations (list): list of {"value": int, "qty": int}.
        # Returns:
        #     dict: parsed SOAP response
        # """

        # # Build the SOAP request body
        # denom_items = []
        # # for d in denominations:
        # #     denom_items.append({
        # #         "fv": d["value"],
        # #         "cc": d["qty"]
        # #     })

        # for d in denominations:
        #     denom_items.append({
        #         '_attributes': {
        #             'cc': 'EUR', # NOTE: THB for Production.
        #             'fv': d["value"],
        #         },
        #         'Piece': int(d["qty"]),
        #         'Status': 6,
        #     })

        # # request_data = {
        # #     "Amount": amount,
        # #     "CurrencyCode": "EUR",   # NOTE: Need to change this to THB for Production.
        # #     "Denomination": denom_items,
        # # }
        # request_data = {
        #     "Id": 0,
        #     "SeqNo": "",
        #     "SessionID": "abc",
        #     "Amount": amount,
        #     "Option": {
        #         'type': 1,
        #     },
        #     "Cash": {
        #         'type':6,
        #         # The Denomination list is nested under the 'Cash' key.
        #         "Denomination": denom_items,
        #     },
        # }

        # logger.info("Sending ChangeOperation SOAP request: %s", request_data)

        # try:
        #     response = self.client.service.ChangeOperation(**request_data)
        #     logger.info("SOAP response: %s", response)
        #     return response
        # except Exception as e:
        #     logger.error("SOAP ChangeOperation failed: %s", e)
        #     raise

# --- Independent Test Block (for direct execution of this file) ---
if __name__ == '__main__':

    print("--- Running FccSoapClient Independent Test ---")

    # Ensure Config and utils are accessible for standalone testing
    # Adjust paths if running this file directly from services/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..')) # Go up one level to GloryAPI
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from config import Config
    from utils.soap_serializer import pretty_print_xml # Only for test block

    fcc_client = FccSoapClient(Config.FCC_SOAP_WSDL_URL)

    # Test GetStatus operation
    print("\n--- Testing GetStatus Operation ---")
    status_response = fcc_client.get_status()
    print(f"GetStatus Test Result: {status_response}")

    # Test OpenCashIn operation (now calls StartCashinOperation)
    print("\n--- Testing OpenCashIn (now StartCashinOperation) ---")
    # Note: Amount, CurrencyCode, AccountID are not direct parameters for StartCashinOperation
    # based on the WSDL. They are included here for consistency with the method signature,
    # but might not be used in the actual SOAP call depending on the WSDL definition.
    cash_in_response = fcc_client.open_cash_in(amount='1000', currency_code='JPY', account_id='ACC001')
    print(f"OpenCashIn Test Result: {cash_in_response}") # Fixed typo: cash_in_in_response -> cash_in_response

    # Display last sent and received XML for debugging
    if soap_history.last_sent:
        print("\n--- Last Sent XML Request (from history) ---")
        print(pretty_print_xml(soap_history.last_sent['envelope']))
    if soap_history.last_received:
        print("\n--- Last Received XML Response (from history) ---")
        print(pretty_print_xml(soap_history.last_received['envelope']))
