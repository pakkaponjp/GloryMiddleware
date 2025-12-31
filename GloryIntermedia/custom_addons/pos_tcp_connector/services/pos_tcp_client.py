# custom_addons/pos_tcp_connector/services/pos_tcp_client.py
import json
import socket
import logging
from typing import Any, Dict

_logger = logging.getLogger(__name__)


class PosTcpClient:
    """
    Simple TCP(JSON) client for POS.

    - Connects to host:port
    - Sends 1 JSON line
    - Reads 1 JSON line as response
    """

    def __init__(self, host: str, port: int, timeout: float = 3.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)

    def send_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False) + "\n"
        _logger.info("POS TCP → %s:%s payload=%s", self.host, self.port, payload)

        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(data.encode("utf-8"))

            buf = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\n" in buf:
                    line, _rest = buf.split(b"\n", 1)
                    break
            else:
                line = buf

        text = line.decode("utf-8").strip()
        _logger.info("POS TCP ← %s:%s raw=%r", self.host, self.port, text)
        if not text:
            raise RuntimeError("Empty response from POS")

        return json.loads(text)
