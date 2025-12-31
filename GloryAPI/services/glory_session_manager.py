#
# File: GloryAPI/services/glory_session_manager.py
# Author: Pakkapon Jirachatmongkon
# Date: Aug 2025
# Description: Manages Glory (CI-10 FCC) user sessions for gs_* users.
#

import logging
import time
from datetime import datetime
from services.fcc_soap_client import FccSoapClient
from config import Config, GLORY_USER_MAPPING

logger = logging.getLogger(__name__)

class GlorySessionManager:
    """
    Singleton manager for handling Glory FCC (CI-10) user sessions.
    Keeps gs_* users logged in and maps ERP roles -> Glory users.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GlorySessionManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.fcc_client = FccSoapClient(Config.FCC_SOAP_WSDL_URL)
        # {glory_user: {"session_id": str, "last_login": ts}}
        self.sessions = {}
        self.refresh_sessions()  # auto-refresh at startup

    def refresh_sessions(self):
        """
        Force re-login for all mapped gs_* users.
        Useful at startup or manual refresh.
        """
        logger.info("Refreshing all Glory sessions...")
        for creds in GLORY_USER_MAPPING.values():
            glory_user = creds["user"]
            password = creds["password"]
            self._login_and_store(glory_user, password)

    def _login_and_store(self, glory_user, password):
        """Helper to login and cache SessionID."""
        self.sessions[glory_user] = {
                "session_id": str(time.time()) + str(glory_user),
                "last_login": time.time()
            }
        # resp = self.fcc_client.login_user(user=glory_user, password=password)
        # if resp["success"]:
        #     session_id = resp["data"].get("SessionID")
        #     self.sessions[glory_user] = {
        #         "session_id": session_id,
        #         "last_login": time.time()
        #     }
        #     logger.info(f"Glory user '{glory_user}' logged in (SessionID={session_id})")
        #     return session_id
        # else:
        #     logger.error(f"Failed to login Glory user '{glory_user}': {resp['error']}")
        #     return None

    def get_session_for_role(self, erp_role):
        """
        Returns a valid Glory SessionID for the given ERP role.
        Auto-refreshes if missing or expired.
        """
        creds = GLORY_USER_MAPPING.get(erp_role)
        if not creds:
            raise ValueError(f"No Glory user mapping for ERP role '{erp_role}'")

        glory_user = creds["user"]
        password = creds["password"]

        session_info = self.sessions.get(glory_user)
        now = time.time()

        if session_info:
            age = now - session_info["last_login"]
            if age < Config.GLORY_SESSION_TTL:
                # Still valid -> return cached
                return session_info["session_id"]
            else:
                logger.info(f"Session for '{glory_user}' expired after {age:.1f}s. Re-login...")
        
        # If missing or expired -> re-login
        return self._login_and_store(glory_user, password)
