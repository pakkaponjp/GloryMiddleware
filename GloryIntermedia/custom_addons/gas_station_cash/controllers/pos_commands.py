# -*- coding: utf-8 -*-
"""
File: controllers/pos_commands.py
Description: POS Command Controller with CloseShift/EndOfDay and Collection Box handling.

Updated: Added status polling until Glory returns to IDLE state
"""

from odoo import http, fields, tools
from odoo.http import request
import configparser
import json
import uuid
import socket
import logging
import time
import threading
import requests

_logger = logging.getLogger(__name__)

# Glory API Configuration
def _read_glory_api_base_url():
    """Read GloryAPI base URL from odoo.conf [fcc_config] section."""
    _logger.info("Reading Glory API base URL from configuration...")
    try:
        conf_path = getattr(tools.config, "rcfile", None)
        if conf_path:
            parser = configparser.ConfigParser()
            parser.read(conf_path)
            host = parser.get('fcc_config', 'fcc_host', fallback='localhost').strip()
            port = parser.get('fcc_config', 'fcc_port', fallback='5000').strip()
            return f"http://{host}:{port}"
    except Exception as e:
        _logger.warning("Failed to read fcc_config from odoo.conf: %s", e)
    return "http://localhost:5000"


GLORY_API_BASE_URL = _read_glory_api_base_url()
GLORY_API_TIMEOUT = 120  # seconds (collection can take time)
GLORY_SESSION_ID = "1"   # Default session ID

# Polling Configuration
GLORY_POLL_INTERVAL = 2  # seconds between status checks
GLORY_POLL_MAX_ATTEMPTS = 60  # max attempts (60 * 2 = 120 seconds max wait)


# =============================================================================
# CONFIGURATION READER
# =============================================================================



def _read_print_service_url():
    """Read print service URL from odoo.conf [options]."""
    conf_path = getattr(tools.config, "rcfile", None)
    if not conf_path:
        return None
    try:
        parser = configparser.ConfigParser()
        parser.read(conf_path)
        in_use = parser.get("options", "printer_in_use", fallback="false").strip().lower()
        if in_use not in ("true", "1", "yes"):
            return None
        host = parser.get("options", "ip_printer_api_host", fallback="localhost").strip()
        port = parser.get("options", "port_printer_api", fallback="5006").strip()
        return f"http://{host}:{port}"
    except Exception:
        return None


def _send_print_receipt(endpoint: str, payload: dict):
    """Send print request to print service (non-critical)."""
    try:
        url = _read_print_service_url()
        if not url:
            return
        import requests as _req
        _req.post(f"{url}/{endpoint}", json=payload, timeout=10)
        _logger.info("Print sent: %s", endpoint)
    except Exception as e:
        _logger.warning("Print failed (non-critical): %s", e)

def _read_collection_config(env=None):
    """
    Read Collection Box settings from ir.config_parameter (Settings UI).
    Pass env explicitly when called from async threads (request is not bound).

    Returns:
        dict with keys:
        - close_shift_collect_cash:  bool
        - end_of_day_collect_cash:   bool
        - leave_float:               bool
        - end_of_day_collect_mode:   str ('all' | 'except_reserve')
        - end_of_day_keep_reserve:   bool
        - end_of_day_reserve_amount: float
        - end_of_day_reserve_denoms: list[dict] or None
        - glory_api_base_url:        str
    """
    if env is None:
        env = request.env
    ICP = env['ir.config_parameter'].sudo()

    def _get_bool(key, default=False):
        val = ICP.get_param(key)
        if val is False:
            return default
        return str(val).lower() in ('true', '1', 'yes')

    def _get_float(key, default=0.0):
        try:
            val = ICP.get_param(key)
            return float(val) if val not in (False, None, '') else default
        except (ValueError, TypeError):
            return default

    def _get_int(key, default=0):
        try:
            val = ICP.get_param(key)
            return int(val) if val not in (False, None, '') else default
        except (ValueError, TypeError):
            return default

    # --- Collection toggles ---
    close_shift_collect = _get_bool('gas_station_cash.collect_on_close_shift', False)
    eod_collect_cash    = _get_bool('gas_station_cash.collect_on_end_of_day',  False)
    leave_float         = _get_bool('gas_station_cash.leave_float',             False)

    # --- End-of-Day mode ---
    eod_collect_mode = ICP.get_param('gas_station_cash.eod_collect_mode') or 'except_reserve'
    if eod_collect_mode not in ('all', 'except_reserve'):
        eod_collect_mode = 'except_reserve'

    eod_keep_reserve   = leave_float
    eod_reserve_amount = _get_float('gas_station_cash.eod_reserve_amount', 0.0)

    # --- Float denominations → reserve_denoms list for Glory API ---
    FLOAT_DENOMS = [
        ('gas_station_cash.float_note_1000', 100000),
        ('gas_station_cash.float_note_500',   50000),
        ('gas_station_cash.float_note_100',   10000),
        ('gas_station_cash.float_note_50',     5000),
        ('gas_station_cash.float_note_20',     2000),
        ('gas_station_cash.float_coin_10',     1000),
        ('gas_station_cash.float_coin_5',       500),
        ('gas_station_cash.float_coin_2',       200),
        ('gas_station_cash.float_coin_1',       100),
        ('gas_station_cash.float_coin_050',      50),
        ('gas_station_cash.float_coin_025',      25),
    ]
    eod_reserve_denoms = None
    if leave_float:
        # device=1 = notes (satang >= 2000), device=2 = coins (satang <= 1000)
        denoms = []
        for k, satang in FLOAT_DENOMS:
            qty = _get_int(k, 0)
            if qty > 0:
                denoms.append({
                    "fv":     satang,
                    "qty":    qty,
                    "device": 1 if satang >= 2000 else 2,
                })
        eod_reserve_denoms = denoms if denoms else None

    glory_api_url = ICP.get_param('gas_station_cash.glory_api_url') or GLORY_API_BASE_URL

    return {
        'close_shift_collect_cash':  close_shift_collect,
        'end_of_day_collect_cash':   eod_collect_cash,
        'leave_float':               leave_float,
        'end_of_day_collect_mode':   eod_collect_mode,
        'end_of_day_keep_reserve':   eod_keep_reserve,
        'end_of_day_reserve_amount': eod_reserve_amount,
        'end_of_day_reserve_denoms': eod_reserve_denoms,
        'glory_api_base_url':        glory_api_url,
    }


def _read_pos_conf():
    """
    Read POS settings from odoo.conf section [pos_tcp_config]
    """
    conf_path = getattr(tools.config, "rcfile", None)
    if not conf_path:
        return {}

    parser = configparser.ConfigParser()
    parser.read(conf_path)

    # Support both section names
    if parser.has_section("pos_http_config"):
        section = parser["pos_http_config"]
    elif parser.has_section("pos_tcp_config"):
        section = parser["pos_tcp_config"]
    else:
        return {}

    # pos_vendor is now read from Odoo UI settings (ir.config_parameter)
    # NOT from odoo.conf — see gas_station_cash.pos_vendor
    pos_host = section.get("pos_host", "127.0.0.1").strip()
    pos_port = section.get("pos_port", "9001").strip()
    pos_timeout = section.get("pos_timeout", "5.0").strip()
    pos_heartbeat_interval = section.get("pos_heartbeat_interval", "60").strip()

    if pos_host == "0.0.0.0":
        pos_host = "127.0.0.1"

    try:
        pos_port = int(pos_port)
    except Exception:
        pos_port = 9001

    try:
        pos_timeout = float(pos_timeout)
    except Exception:
        pos_timeout = 5.0

    # FlowCo multi-POS map
    # Format: flowco_pos_hosts = 1:192.168.1.10:8080,2:192.168.1.11:8080
    # Works with single POS too: flowco_pos_hosts = 1:127.0.0.1:9003
    flowco_pos_map = {}  # {pos_id(int): (host, port)}
    raw_hosts = section.get("flowco_pos_hosts", "").strip()
    if raw_hosts:
        for entry in raw_hosts.split(","):
            entry = entry.strip()
            parts = entry.split(":")
            if len(parts) == 3:
                try:
                    pid  = int(parts[0].strip())
                    host = parts[1].strip()
                    port = int(parts[2].strip())
                    flowco_pos_map[pid] = (host, port)
                except (ValueError, IndexError):
                    _logger.warning("[POS_CONF] Invalid flowco_pos_hosts entry: %s", entry)

    try:
        pos_heartbeat_interval = int(pos_heartbeat_interval)
    except Exception:
        pos_heartbeat_interval = 60

    # offline mode availability
    raw_offline = section.get("pos_offline_mode_availability", "false").strip().lower()
    pos_offline_mode_availability = raw_offline in ("true", "1", "yes")

    return {
        "pos_host":                    pos_host,
        "pos_port":                    pos_port,
        "pos_timeout":                 pos_timeout,
        "pos_heartbeat_interval":      pos_heartbeat_interval,
        "flowco_pos_map":              flowco_pos_map,
        "pos_offline_mode_availability": pos_offline_mode_availability,
    }




# ──────────────────────────────────────────────────────────────────────────────
# Heartbeat + Retry Worker
# Runs as a daemon thread — calls POS heartbeat every N seconds (from odoo.conf)
# If POS is alive → retry failed deposits in current Odoo shift
# ──────────────────────────────────────────────────────────────────────────────

class _PosHeartbeatWorker:
    """Singleton background worker for POS heartbeat and failed-deposit retry."""

    _instance = None
    _lock = threading.Lock()
    OFFLINE_THRESHOLD = 3  # consecutive failures before declaring POS offline

    def __init__(self):
        self._thread            = None
        self._stop              = threading.Event()
        self._consecutive_fails = 0

    @classmethod
    def start(cls):
        with cls._lock:
            if cls._instance and cls._instance._thread and cls._instance._thread.is_alive():
                return  # already running
            cls._instance = cls()
            t = threading.Thread(target=cls._instance._run, daemon=True, name="pos_heartbeat")
            cls._instance._thread = t
            t.start()
            _logger.info("[HeartbeatWorker] Started")

    def _run(self):
        """Main loop — runs indefinitely until process exits."""
        while not self._stop.is_set():
            try:
                pos_conf = _read_pos_conf()
                interval = pos_conf.get("pos_heartbeat_interval", 60)
            except Exception:
                interval = 60

            self._stop.wait(interval)
            if self._stop.is_set():
                break

            try:
                self._tick()
            except Exception as e:
                _logger.warning("[HeartbeatWorker] Tick error: %s", e)

    def _set_pos_connected(self, connected: bool):
        """Update ICP gas_station_cash.pos_connected — called from background thread."""
        try:
            import odoo
            dbname = odoo.tools.config.get("db_name")
            if not dbname:
                return
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, 1, {})
                ICP = env["ir.config_parameter"].sudo()
                current = ICP.get_param("gas_station_cash.pos_connected", "true")
                new_val = "true" if connected else "false"
                if current != new_val:
                    ICP.set_param("gas_station_cash.pos_connected", new_val)
                    _logger.info("[HeartbeatWorker] pos_connected → %s", new_val)
        except Exception as e:
            _logger.warning("[HeartbeatWorker] _set_pos_connected error: %s", e)

    def _increment_fail_count(self) -> int:
        """Increment ICP failure counter (shared across worker processes). Returns new count."""
        try:
            import odoo
            dbname = odoo.tools.config.get("db_name")
            if not dbname:
                return 1
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, 1, {})
                ICP = env["ir.config_parameter"].sudo()
                current = int(ICP.get_param("gas_station_cash.pos_fail_count", "0") or "0")
                new_count = current + 1
                ICP.set_param("gas_station_cash.pos_fail_count", str(new_count))
                return new_count
        except Exception as e:
            _logger.warning("[HeartbeatWorker] _increment_fail_count error: %s", e)
            return 1

    def _reset_fail_count(self) -> int:
        """Reset ICP failure counter. Returns previous count."""
        try:
            import odoo
            dbname = odoo.tools.config.get("db_name")
            if not dbname:
                return 0
            registry = odoo.registry(dbname)
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, 1, {})
                ICP = env["ir.config_parameter"].sudo()
                prev = int(ICP.get_param("gas_station_cash.pos_fail_count", "0") or "0")
                ICP.set_param("gas_station_cash.pos_fail_count", "0")
                return prev
        except Exception as e:
            _logger.warning("[HeartbeatWorker] _reset_fail_count error: %s", e)
            return 0

    def _tick(self):
        """One heartbeat cycle: ping POS → retry failed deposits if alive."""
        pos_conf = _read_pos_conf()
        host     = pos_conf.get("pos_host", "127.0.0.1")
        port     = pos_conf.get("pos_port", 9003)
        timeout  = pos_conf.get("pos_timeout", 5.0)
        url      = f"http://{host}:{port}/HeartBeat"

        # ── Ping POS ─────────────────────────────────────────────────────────
        try:
            resp = requests.post(
                url,
                json={"source_system": "Odoo", "pos_terminal_id": "TERM-01"},
                timeout=timeout,
            )
            alive = resp.ok and resp.json().get("status") in ("OK", "acknowledged")
        except Exception as e:
            _logger.debug("[HeartbeatWorker] POS unreachable: %s", e)
            alive = False

        if not alive:
            # Use ICP counter — shared across all worker processes
            count = self._increment_fail_count()
            _logger.debug("[HeartbeatWorker] POS heartbeat failed (%d/%d)",
                          count, self.OFFLINE_THRESHOLD)
            if count >= self.OFFLINE_THRESHOLD:
                self._set_pos_connected(False)
            return

        # POS alive — reset ICP counter and mark connected
        prev = self._reset_fail_count()
        if prev > 0:
            _logger.info("[HeartbeatWorker] POS back online after %d failure(s)", prev)
        self._set_pos_connected(True)
        _logger.debug("[HeartbeatWorker] POS alive — checking failed deposits")

        # ── Find failed deposits in current Odoo shift ────────────────────────
        import odoo
        dbname = odoo.tools.config.get("db_name")
        if not dbname:
            return

        try:
            registry = odoo.registry(dbname)
        except Exception as e:
            _logger.warning("[HeartbeatWorker] Cannot get registry: %s", e)
            return

        with registry.cursor() as cr:
            env = odoo.api.Environment(cr, 1, {})  # uid=1 (admin)

            # Current shift start = last done close_shift or end_of_day
            PosCmd    = env["gas.station.pos_command"].sudo()
            last_done = PosCmd.search([
                ("action", "in", ("close_shift", "end_of_day")),
                ("status", "=", "done"),
            ], order="started_at desc", limit=1)
            shift_start = (
                getattr(last_done, "finished_at", None) or last_done.started_at
                if last_done else None
            )

            # Query failed deposits in this shift
            domain = [("pos_status", "in", ("queued", "failed"))]
            if shift_start:
                domain.append(("date", ">", shift_start))

            deposits = env["gas.station.cash.deposit"].sudo().search(domain)
            if not deposits:
                return

            _logger.info("[HeartbeatWorker] Retrying %d failed deposit(s) in current shift",
                         len(deposits))

            pos_vendor = env["ir.config_parameter"].sudo().get_param(
                "gas_station_cash.pos_vendor", "firstpro"
            )

            # Re-use controller's send methods (instantiate without request context)
            ctrl = PosCommandController()
            for deposit in deposits:
                try:
                    if pos_vendor == "firstpro":
                        ok = ctrl._send_deposit_to_firstpro(pos_conf, deposit)
                    else:
                        ok = ctrl._send_deposit_to_flowco(pos_conf, deposit)

                    _logger.info(
                        "[HeartbeatWorker] Deposit id=%s %s",
                        deposit.id, "✅ OK" if ok else "❌ still failed",
                    )
                except Exception as dep_err:
                    _logger.warning("[HeartbeatWorker] Error retrying deposit %s: %s",
                                    deposit.id, dep_err)


# Do NOT start at module load time — Odoo forks worker processes after import,
# and fork()-after-thread causes deadlocks. Instead, start lazily on first request
# via _ensure_heartbeat_worker() called from the CloseShift/EndOfDay handlers.

def _ensure_heartbeat_worker():
    """Start heartbeat worker on first call (after Odoo has forked workers)."""
    _PosHeartbeatWorker.start()


class PosCommandController(http.Controller):

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def _create_command(self, action_key: str, staff_id: str, extra_payload: dict = None, pos_shift_id: str = None):
        """Create a POS command record for tracking and overlay display."""
        Command = request.env["gas.station.pos_command"].sudo()
        internal_req_id = uuid.uuid4().hex
        terminal_id = self._get_terminal_id()

        payload = {"staff_id": staff_id}
        if extra_payload:
            payload.update(extra_payload)

        cmd = Command.create({
            "name": f"{action_key} / {internal_req_id}",
            "action": action_key,
            "request_id": internal_req_id,
            "pos_terminal_id": terminal_id,
            "staff_external_id": staff_id,
            "pos_shift_id": pos_shift_id,
            "status": "processing",
            "message": "processing...",
            "started_at": fields.Datetime.now(),
            "payload_in": json.dumps(payload, ensure_ascii=False),
        })
        return cmd

    def _get_terminal_id(self):
        """Get the POS terminal ID from configuration or default."""
        return tools.config.get('pos_terminal_id', 'TERM-01')

    def _get_default_staff_id(self):
        """Get default staff_id when not provided in request."""
        staff_id = tools.config.get('pos_default_staff_id')
        if staff_id:
            return staff_id
        
        staff_id = request.httprequest.headers.get('X-Staff-ID')
        if staff_id:
            return staff_id
        
        return "DEFAULT-STAFF"

    def _json_response(self, payload: dict, status=200):
        """Create a JSON HTTP response."""
        return request.make_response(
            json.dumps(payload, ensure_ascii=False),
            headers=[("Content-Type", "application/json")],
            status=status
        )

    # =========================================================================
    # GLORY API FUNCTIONS
    # =========================================================================

    def _glory_get_status(self, env=None):
        """
        Get Glory machine status.
        
        Calls: GET /fcc/api/v1/status?session_id=1
        
        Returns:
            dict: {
                'success': bool,
                'is_idle': bool,
                'status_code': str,
                'raw_response': dict,
                'error': str or None,
            }
        """
        config = _read_collection_config(env=env)
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        result = {
            'success': False,
            'is_idle': False,
            'status_code': None,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/status"
            resp = requests.get(url, params={"session_id": GLORY_SESSION_ID}, timeout=10)
            
            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                return result
            
            data = resp.json()
            result['raw_response'] = data
            result['status_code'] = data.get('code')
            
            # Check if status is OK (code "0" means IDLE/ready)
            if data.get('status') == 'OK' and data.get('code') == '0':
                result['success'] = True
                result['is_idle'] = True
            else:
                result['success'] = True
                result['is_idle'] = False
            
        except requests.Timeout:
            result['error'] = "Glory API timeout"
        except requests.RequestException as e:
            result['error'] = f"Glory API connection error: {str(e)}"
        except Exception as e:
            result['error'] = f"Error checking Glory status: {str(e)}"
        
        return result

    def _glory_wait_for_idle(self, env=None, max_attempts=GLORY_POLL_MAX_ATTEMPTS, interval=GLORY_POLL_INTERVAL):
        """
        Poll Glory status until it returns to IDLE state.
        
        Args:
            max_attempts: Maximum number of polling attempts
            interval: Seconds between each poll
            
        Returns:
            dict: {
                'success': bool,
                'attempts': int,
                'final_status': str,
                'error': str or None,
            }
        """
        _logger.info("⏳ Waiting for Glory to return to IDLE state...")
        
        result = {
            'success': False,
            'attempts': 0,
            'final_status': None,
            'error': None,
        }
        
        for attempt in range(1, max_attempts + 1):
            result['attempts'] = attempt
            
            _logger.info("   Poll attempt %d/%d...", attempt, max_attempts)
            
            status = self._glory_get_status(env=env)
            
            if not status['success']:
                _logger.warning("   Status check failed: %s", status.get('error'))
                time.sleep(interval)
                continue
            
            result['final_status'] = status.get('status_code')
            
            if status['is_idle']:
                _logger.info("    Glory is IDLE (attempt %d)", attempt)
                result['success'] = True
                return result
            
            _logger.info("   Glory not IDLE yet (code=%s), waiting %ds...", 
                        status.get('status_code'), interval)
            time.sleep(interval)
        
        result['error'] = f"Glory did not return to IDLE after {max_attempts} attempts"
        _logger.warning("    %s", result['error'])
        return result

    def _collect_largest_first(self, all_inv: list, target_keep_satang: int) -> dict:
        """
        Determine which denominations to KEEP in machine after collection.

        Strategy: collect largest denominations first until
        collected_amount = total - target_keep. Keep everything else.

        This is simpler and more reliable than two-pass keep-smallest:
        - Skips denominations too large for remaining collect amount
        - No backtracking needed
        - Naturally keeps small denominations for change

        Args:
            all_inv            : list of {fv, qty, device}
            target_keep_satang : amount to keep in machine (satang)

        Returns:
            {
                'keep_denoms'  : list of {fv, qty, device},
                'kept_total'   : actual kept (satang),
                'shortfall'    : 0 = exact, >0 = partial,
                'insufficient' : True if machine total < target,
            }
        """
        all_inv_sorted = sorted(
            [i for i in all_inv if i.get('qty', 0) > 0],
            key=lambda x: x['fv']
        )
        total_available = sum(i['fv'] * i['qty'] for i in all_inv_sorted)

        if total_available < target_keep_satang:
            _logger.warning(
                "_collect_largest_first: INSUFFICIENT — machine=%.2f < target=%.2f THB",
                total_available / 100.0, target_keep_satang / 100.0
            )
            return {
                'keep_denoms': [],
                'kept_total': total_available,
                'shortfall': target_keep_satang - total_available,
                'insufficient': True,
            }

        collect_target = total_available - target_keep_satang

        # Collect largest denominations first
        remaining = collect_target
        collect_map = {}
        for item in sorted(all_inv_sorted, key=lambda x: -x['fv']):
            if remaining <= 0:
                break
            fv, avail, dev = item['fv'], item['qty'], item['device']
            if fv > remaining:
                continue  # skip — too large, move to smaller denomination
            collect_qty = min(avail, remaining // fv)
            if collect_qty > 0:
                collect_map[(dev, fv)] = collect_qty
                remaining -= fv * collect_qty

        if remaining > 0:
            # Physical limitation — cannot collect exact amount
            collected_so_far = collect_target - remaining
            _logger.warning(
                "_collect_largest_first: PARTIAL — collected=%.2f shortfall=%.2f THB",
                collected_so_far / 100.0, remaining / 100.0
            )
            # Build keep from what's not collected
            final_denoms = []
            for item in all_inv_sorted:
                fv, avail, dev = item['fv'], item['qty'], item['device']
                collected = collect_map.get((dev, fv), 0)
                keep_qty = avail - collected
                if keep_qty > 0:
                    final_denoms.append({'fv': fv, 'qty': keep_qty, 'device': dev})
            kept_total = sum(d['fv'] * d['qty'] for d in final_denoms)
            return {
                'keep_denoms': sorted(final_denoms, key=lambda x: x['fv']),
                'kept_total': kept_total,
                'shortfall': remaining,
                'insufficient': False,
            }

        # Build keep = inventory minus collected
        final_denoms = []
        for item in all_inv_sorted:
            fv, avail, dev = item['fv'], item['qty'], item['device']
            collected = collect_map.get((dev, fv), 0)
            keep_qty = avail - collected
            if keep_qty > 0:
                final_denoms.append({'fv': fv, 'qty': keep_qty, 'device': dev})

        kept_total = sum(d['fv'] * d['qty'] for d in final_denoms)
        _logger.info(
            "_collect_largest_first: EXACT — kept=%.2f THB",
            kept_total / 100.0
        )
        return {
            'keep_denoms': sorted(final_denoms, key=lambda x: x['fv']),
            'kept_total': kept_total,
            'shortfall': 0,
            'insufficient': False,
        }


    def _glory_get_inventory(self, env):
        """
        Get dispensable cash from Glory Cash Recycler.
        Uses /cash/availability (Cash type=4 — dispensable only).
        """
        config = _read_collection_config(env=env)
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)

        _logger.info("Getting dispensable inventory from Glory API (type=4)...")

        result = {
            'success': False,
            'total_amount': 0.0,
            'notes': [],
            'coins': [],
            'raw_response': {},
            'error': None,
        }

        try:
            url = f"{base_url}/fcc/api/v1/cash/availability"
            resp = requests.get(url, params={"session_id": GLORY_SESSION_ID}, timeout=30)

            if not resp.ok:
                result['error'] = f"Glory API returned HTTP {resp.status_code}"
                _logger.error("   %s", result['error'])
                return result

            data = resp.json()
            result['raw_response'] = data

            UNIT_DIVISOR = 100
            total = 0.0

            notes = data.get('notes', [])
            coins = data.get('coins', [])

            parsed_notes = []
            for note in notes:
                fv  = int(note.get('value', note.get('fv', 0)) or 0)
                qty = int(note.get('qty', 0) or 0)
                if fv > 0 and qty > 0:
                    value_thb = fv / UNIT_DIVISOR
                    parsed_notes.append({'value': value_thb, 'qty': qty, 'fv': fv, 'device': 1})
                    total += value_thb * qty

            parsed_coins = []
            for coin in coins:
                fv  = int(coin.get('value', coin.get('fv', 0)) or 0)
                qty = int(coin.get('qty', 0) or 0)
                if fv > 0 and qty > 0:
                    value_thb = fv / UNIT_DIVISOR
                    parsed_coins.append({'value': value_thb, 'qty': qty, 'fv': fv, 'device': 2})
                    total += value_thb * qty

            result['success'] = True
            result['total_amount'] = total
            result['notes'] = parsed_notes
            result['coins'] = parsed_coins

            _logger.info(
                "   Inventory: notes=%d denominations, coins=%d denominations, total=%.2f",
                len(parsed_notes), len(parsed_coins), total,
            )

        except Exception as e:
            result['error'] = f"Error: {str(e)}"
            _logger.exception("   %s", result['error'])

        return result

    def _glory_unlock_unit(self, target: str, env=None):
        """
        Unlock a specific unit (notes or coins).
        
        Args:
            target: 'notes' or 'coins'
        """
        config = _read_collection_config(env=env)
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info(" Unlocking %s unit...", target)
        
        result = {
            'success': False,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/device/unit/unlock"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "target": target,
            }
            
            _logger.info("   URL: %s", url)
            _logger.info("   Payload: %s", payload)
            
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Response: %s", data)
            
            if data.get('status') == 'OK':
                result['success'] = True
                _logger.info("    %s unlocked!", target.capitalize())
            else:
                result['error'] = f"Unlock failed (code: {data.get('result_code')})"
                _logger.error("    %s", result['error'])
                
        except Exception as e:
            result['error'] = str(e)
            _logger.exception("    Error: %s", e)
        
        return result
    
    def _glory_lock_unit(self, target: str, env=None):
        """
        Lock a specific unit (notes or coins).
        
        Args:
            target: 'notes' or 'coins'
        """
        config = _read_collection_config(env=env)
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)
        
        _logger.info(" Locking %s unit...", target)
        
        result = {
            'success': False,
            'raw_response': {},
            'error': None,
        }
        
        try:
            url = f"{base_url}/fcc/api/v1/device/unit/lock"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "target": target,
            }
            
            _logger.info("   URL: %s", url)
            _logger.info("   Payload: %s", payload)
            
            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()
            result['raw_response'] = data
            
            _logger.info("   Response: %s", data)
            
            if data.get('status') == 'OK':
                result['success'] = True
                _logger.info("    %s locked!", target.capitalize())
            else:
                result['error'] = f"Lock failed (code: {data.get('result_code')})"
                _logger.error("    %s", result['error'])
                
        except Exception as e:
            result['error'] = str(e)
            _logger.exception("    Error: %s", e)
        
        return result

    # =========================================================================
    # COLLECTION BOX FUNCTIONS
    # =========================================================================
    
    def _glory_collect_with_reserve(self, env, reserve_denoms: list = None):
        """
        Collect cash to collection box, keeping specified denominations as reserve.

        Args:
            env: Odoo environment
            reserve_denoms: List of denominations to KEEP (not collect)
                           Format: [{"fv": 10000, "qty": 5, "device": 1}, ...]
                           - fv: face value in smallest unit (satang/cents)
                           - qty: quantity to keep
                           - device: 1=notes, 2=coins

        Returns:
            dict with collection results
        """
        config = _read_collection_config(env=env)
        base_url = config.get('glory_api_base_url', GLORY_API_BASE_URL)

        _logger.info("💰 Collecting cash with reserve...")
        _logger.info("   Reserve denoms: %s", reserve_denoms)

        result = {
            'success': False,
            'collected_amount': 0.0,
            'collected_breakdown': {'notes': [], 'coins': []},
            'reserve_kept': {'notes': [], 'coins': [], 'total': 0.0},
            'raw_response': {},
            'error': None,
        }

        try:
            # Build target_float for Glory API
            # target_float format: {"denoms": [{"devid": 1, "cc": "EUR", "fv": 5000, "min_qty": 10}, ...]}
            target_float = None
            if reserve_denoms and len(reserve_denoms) > 0:
                target_float = {"denoms": []}

                # Calculate reserve total for logging
                reserve_total = 0.0
                UNIT_DIVISOR = 100

                for denom in reserve_denoms:
                    fv = int(denom.get('fv', 0))
                    qty = int(denom.get('qty', 0))
                    device = int(denom.get('device', 1))

                    if fv > 0 and qty > 0:
                        target_float["denoms"].append({
                            "devid": device,
                            "cc": "THB",  # TODO: Get from config
                            "fv": fv,
                            "min_qty": qty,
                        })

                        value = (fv / UNIT_DIVISOR) * qty
                        reserve_total += value

                        if device == 1:
                            result['reserve_kept']['notes'].append({
                                'fv': fv, 'qty': qty, 'value': fv / UNIT_DIVISOR
                            })
                        else:
                            result['reserve_kept']['coins'].append({
                                'fv': fv, 'qty': qty, 'value': fv / UNIT_DIVISOR
                            })

                result['reserve_kept']['total'] = reserve_total
                _logger.info("   Reserve to keep: %.2f", reserve_total)

            # Call Glory collect API
            # Always use leave_float — plan=full sends Cash type=0 which machine
            # acknowledges but does not physically move cash.
            # leave_float with empty denoms = collect everything.
            url = f"{base_url}/fcc/api/v1/collect"
            payload = {
                "session_id": GLORY_SESSION_ID,
                "scope": "all",
                "plan": "leave_float",
                "target_float": target_float if target_float else {"denoms": []},
            }

            _logger.info("   Collect request: %s", payload)

            # Send collect with Idempotency-Key header + retry on result=11
            def _do_post():
                headers = {
                    'Content-Type': 'application/json',
                    'Idempotency-Key': str(uuid.uuid4()),
                }
                r = requests.post(url, json=payload, headers=headers, timeout=GLORY_API_TIMEOUT)
                r.raise_for_status()
                return r

            resp = _do_post()
            data = resp.json()

            # result=11 = occupied by other (verify step just completed) — retry once
            try:
                if int(data.get('data', {}).get('result', -1)) == 11:
                    _logger.warning("   result=11 (occupied), retrying in 2s...")
                    time.sleep(2)
                    resp = _do_post()
                    data = resp.json()
                    _logger.info("   retry result=%s", data.get('data', {}).get('result'))
            except Exception:
                pass
            result['raw_response'] = data

            if data.get('status') != 'OK':
                result['error'] = data.get('error', 'Collection failed')
                _logger.error("   Collection failed: %s", result['error'])
                return result

            # Parse collected cash from response
            UNIT_DIVISOR = 100
            collected_total = 0.0

            inner_data = data.get('data', {})
            denominations = []

            # Try different response structures
            if isinstance(inner_data.get('Cash'), list):
                for cash_block in inner_data['Cash']:
                    if isinstance(cash_block.get('Denomination'), list):
                        denominations.extend(cash_block['Denomination'])
            elif isinstance(inner_data.get('Cash'), dict):
                if isinstance(inner_data['Cash'].get('Denomination'), list):
                    denominations = inner_data['Cash']['Denomination']

            # If still empty, try planned_cash
            if not denominations and isinstance(inner_data.get('planned_cash'), dict):
                if isinstance(inner_data['planned_cash'].get('Denomination'), list):
                    denominations = inner_data['planned_cash']['Denomination']

            for d in denominations:
                if not isinstance(d, dict):
                    continue
                
                try:
                    fv = int(d.get('fv', 0) or 0)
                    qty = int(d.get('Piece', 0) or 0)
                    devid = int(d.get('devid', 0) or 0)
                    cc = d.get('cc', '')

                    if qty > 0:
                        value = fv / UNIT_DIVISOR
                        collected_total += value * qty

                        item = {'fv': fv, 'qty': qty, 'value': value, 'cc': cc}
                        if devid == 2:
                            result['collected_breakdown']['coins'].append(item)
                        else:
                            result['collected_breakdown']['notes'].append(item)
                except Exception as e:
                    _logger.warning("   Error parsing denomination: %s", e)
                    continue
                
            result['success'] = True
            result['collected_amount'] = collected_total

            _logger.info("   ✅ Collection successful!")
            _logger.info("   Collected: %.2f", collected_total)
            _logger.info("   Reserved: %.2f", result['reserve_kept']['total'])

        except Exception as e:
            result['error'] = str(e)
            _logger.exception("   Collection error: %s", e)

        return result

    def _collect_to_box(self, env, mode: str, staff_id: str = None, reserve_amount: float = 0):
        """
        Collect cash to collection box via Glory Cash Recycler.

        UPDATED: Support for denomination-based reserve configuration.
        """
        config = _read_collection_config(env=env)
        keep_reserve = config.get('end_of_day_keep_reserve', True)
        reserve_denoms = config.get('end_of_day_reserve_denoms')

        _logger.info("=" * 60)
        _logger.info("COLLECTION BOX - Starting collection")
        _logger.info("   Mode: %s", mode)
        _logger.info("   Staff: %s", staff_id)
        _logger.info("   Keep Reserve: %s", keep_reserve)
        _logger.info("   Reserve Amount: %.2f", reserve_amount)
        _logger.info("   Reserve Denoms: %s", "configured" if reserve_denoms else "not configured")

        result = {
            'success': False,
            'collected_amount': 0.0,
            'reserve_kept': 0.0,
            'current_cash': 0.0,
            'required_reserve': reserve_amount,
            'insufficient_reserve': False,
            'error': None,
            'glory_response': {},
            'collected_breakdown': {},
            'reserve_breakdown': {},
        }

        try:
            # Step 1 - Get current cash inventory (type 4 - dispensable only)
            inventory = self._glory_get_inventory(env)

            if not inventory['success']:
                result['error'] = inventory.get('error', 'Failed to get inventory')
                _logger.error("   %s", result['error'])
                _logger.info("=" * 60)
                return result

            current_cash = inventory['total_amount']
            result['current_cash'] = current_cash
            _logger.info("   Current Cash: %.2f", current_cash)

            # Step 2 - Determine if we're keeping reserve
            if mode == 'all' or not keep_reserve:
                # Collect ALL - no reserve
                _logger.info("   Mode: Collect ALL (no reserve)")
                collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)

            elif mode == 'except_reserve':
                # Collect with reserve

                # Check if we have denomination breakdown
                if reserve_denoms and len(reserve_denoms) > 0:
                    _logger.info("   Mode: Leave Reserve (by denomination)")

                    UNIT_DIVISOR = 100
                    setting_float_satang = sum(
                        int(d.get('fv', 0)) * int(d.get('qty', 0))
                        for d in reserve_denoms
                    )
                    inventory_satang = int(current_cash * 100)

                    # Check if we have enough cash for reserve
                    if inventory_satang < setting_float_satang:
                        _logger.info("   INSUFFICIENT CASH FOR RESERVE!")
                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['required_reserve'] = setting_float_satang / 100.0
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash
                        result['float_difference'] = (inventory_satang - setting_float_satang) / 100.0
                        _logger.info("=" * 60)
                        return result

                    # Check denomination match
                    inv_notes = inventory.get('notes', [])
                    inv_coins = inventory.get('coins', [])
                    inv_map = {}
                    for item in inv_notes + inv_coins:
                        fv  = int(item.get('fv', item.get('value', 0)))
                        qty = int(item.get('qty', 0))
                        dev = int(item.get('device', item.get('devid', 1)))
                        if fv > 0 and qty > 0:
                            inv_map[(dev, fv)] = inv_map.get((dev, fv), 0) + qty

                    all_matched = all(
                        inv_map.get((int(d.get('device', 1)), int(d.get('fv', 0))), 0)
                        >= int(d.get('qty', 0))
                        for d in reserve_denoms
                        if int(d.get('fv', 0)) > 0 and int(d.get('qty', 0)) > 0
                    )

                    if all_matched:
                        # min_qty logic
                        _logger.info("   Using min_qty logic (denominations matched)")
                        collection_result = self._glory_collect_with_reserve(env, reserve_denoms=reserve_denoms)
                    else:
                        # ── Collect largest first algorithm ───────────────────
                        # Collect largest denominations first, keep remainder.
                        # Simpler and more reliable than two-pass backtracking.
                        _logger.info("   Using collect-largest-first algorithm")

                        all_inv_for_algo = [
                            {'fv': int(item.get('fv', item.get('value', 0))),
                             'qty': int(item.get('qty', 0)),
                             'device': int(item.get('device', item.get('devid', 1)))}
                            for item in inv_notes + inv_coins
                            if item.get('qty', 0) > 0
                        ]

                        cl_result = self._collect_largest_first(
                            all_inv_for_algo, setting_float_satang
                        )

                        if cl_result['insufficient']:
                            _logger.warning("   Collect-largest: insufficient cash for float target")
                            result['success'] = True
                            result['insufficient_reserve'] = True
                            result['required_reserve'] = setting_float_satang / 100.0
                            result['collected_amount'] = 0.0
                            result['reserve_kept'] = cl_result['kept_total'] / 100.0
                            return result

                        final_keep_denoms = cl_result['keep_denoms']
                        _logger.info("   Collect-largest keep denoms: %s", final_keep_denoms)
                        collection_result = self._glory_collect_with_reserve(
                            env, reserve_denoms=final_keep_denoms
                        )

                        # ── OLD greedy algorithm (kept for reference) ──────────
                        # all_inv = sorted(
                        #     [{'fv': int(item.get('fv', item.get('value', 0))),
                        #       'qty': int(item.get('qty', 0)),
                        #       'device': int(item.get('device', item.get('devid', 1)))}
                        #      for item in inv_notes + inv_coins
                        #      if item.get('qty', 0) > 0],
                        #     key=lambda x: x['fv']
                        # )
                        # remaining = setting_float_satang
                        # greedy_denoms = []
                        # for item in all_inv:
                        #     if remaining <= 0:
                        #         break
                        #     fv, avail, dev = item['fv'], item['qty'], item['device']
                        #     if fv <= 0:
                        #         continue
                        #     keep_qty = min(avail, remaining // fv)
                        #     if keep_qty > 0:
                        #         greedy_denoms.append({'fv': fv, 'qty': keep_qty, 'device': dev})
                        #         remaining -= fv * keep_qty
                        # if remaining > 0:
                        #     _logger.warning("Greedy shortfall=%.2f THB", remaining / 100.0)
                        # collection_result = self._glory_collect_with_reserve(
                        #     env, reserve_denoms=greedy_denoms
                        # )

                else:
                    # Fallback to amount-based reserve
                    _logger.info("   Mode: Leave Reserve (by amount: %.2f)", reserve_amount)

                    # Check if we have enough
                    if current_cash < reserve_amount:
                        _logger.info("   INSUFFICIENT CASH FOR RESERVE!")
                        result['success'] = True
                        result['insufficient_reserve'] = True
                        result['collected_amount'] = 0.0
                        result['reserve_kept'] = current_cash
                        _logger.info("=" * 60)
                        return result

                    # Use amount-based - collect without specific denoms
                    collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)
            else:
                # Unknown mode - collect all
                collection_result = self._glory_collect_with_reserve(env, reserve_denoms=None)

            # Step 3 - Process collection result
            if not collection_result['success']:
                result['error'] = collection_result.get('error', 'Collection failed')
                result['glory_response'] = collection_result.get('raw_response', {})
                _logger.info("=" * 60)
                return result

            result['success'] = True
            result['collected_amount'] = collection_result['collected_amount']
            result['reserve_kept'] = collection_result.get('reserve_kept', {}).get('total', 0.0)
            result['glory_response'] = collection_result.get('raw_response', {})
            result['collected_breakdown'] = collection_result.get('collected_breakdown', {})
            result['reserve_breakdown'] = collection_result.get('reserve_kept', {})

            _logger.info("COLLECTION BOX - Success!")
            _logger.info("   Collected: %.2f", result['collected_amount'])
            _logger.info("   Reserved: %.2f", result['reserve_kept'])

        except Exception as e:
            _logger.exception("COLLECTION BOX - Error: %s", e)
            result['error'] = str(e)

        _logger.info("=" * 60)
        return result

    # =========================================================================
    # PENDING TRANSACTION HANDLING
    # =========================================================================

    def _is_deposit_pos_related(self, deposit):
        """Check if a deposit should be sent to POS."""
        if deposit.deposit_type in ['oil', 'engine_oil']:
            return True
        if deposit.product_id and deposit.product_id.is_pos_related:
            return True
        if deposit.is_pos_related:
            return True
        return False

    def _get_last_end_of_day(self, env=None):
        """Get the last successful EndOfDay command timestamp."""
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        last_eod = PosCommand.search([
            ('action', '=', 'end_of_day'),
            ('status', '=', 'done'),
        ], order='started_at desc', limit=1)
        
        if last_eod:
            eod_time = getattr(last_eod, 'finished_at', None) or last_eod.started_at
            _logger.info(" Last EndOfDay: %s (ID: %s)", eod_time, last_eod.id)
            return eod_time
        
        _logger.info(" No EndOfDay found")
        return None

    def _get_last_close_shift(self, env=None, after_timestamp=None):
        """Get the last successful CloseShift command timestamp."""
        if env is None:
            env = request.env
            
        PosCommand = env["gas.station.pos_command"].sudo()
        
        domain = [
            ('action', '=', 'close_shift'),
            ('status', '=', 'done'),
        ]
        
        if after_timestamp:
            domain.append(('started_at', '>', after_timestamp))
        
        last_shift = PosCommand.search(domain, order='started_at desc', limit=1)
        
        if last_shift:
            shift_time = getattr(last_shift, 'finished_at', None) or last_shift.started_at
            _logger.info(" Last CloseShift: %s (ID: %s)", shift_time, last_shift.id)
            return shift_time
        
        return None

    def _get_shift_start_time(self, env=None):
        """Get the start time of the current shift."""
        if env is None:
            env = request.env
        
        last_eod = self._get_last_end_of_day(env)
        last_close_shift = self._get_last_close_shift(env, after_timestamp=last_eod)
        
        if last_close_shift:
            return last_close_shift
        elif last_eod:
            return last_eod
        
        return None

    def _get_pending_transactions(self):
        """Get pending transactions within the current shift."""
        pending = []
        
        shift_start = self._get_shift_start_time()
        
        CashDeposit = request.env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', 'in', ['queued', 'failed']),
        ]
        
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        pending_deposits = CashDeposit.search(domain)
        
        for deposit in pending_deposits:
            if self._is_deposit_pos_related(deposit):
                pending.append(deposit)
        
        _logger.info("Found %d pending POS-related transactions", len(pending))
        
        return pending

    def _calculate_shift_pos_total(self, env, staff_id=None):
        """Calculate total of POS deposits within current shift."""
        shift_start = self._get_shift_start_time(env)
        
        CashDeposit = env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('pos_status', '=', 'ok'),
        ]
        
        if shift_start:
            domain.append(('date', '>', shift_start))
        
        successful_deposits = CashDeposit.search(domain)
        
        total_cash = 0.0
        pos_related_deposits = []
        
        for deposit in successful_deposits:
            if self._is_deposit_pos_related(deposit):
                total_cash += deposit.total_amount or 0.0
                pos_related_deposits.append(deposit.name)
        
        _logger.info(" Shift POS totals: %d deposits, %.2f total", 
                    len(pos_related_deposits), total_cash)
        
        return {
            'total_cash': total_cash,
            'count': len(pos_related_deposits),
            'deposits': pos_related_deposits,
        }

    def _send_pending_transactions_async(self, dbname, uid, pending_ids, pending_model, cmd_id):
        """Background thread to send pending transactions to POS."""
        try:
            _logger.info("📤 Starting to send %d pending transactions...", len(pending_ids))
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                success_count = 0
                fail_count = 0
                
                for record_id in pending_ids:
                    try:
                        if pending_model == "gas.station.cash.deposit":
                            deposit = env[pending_model].sudo().browse(record_id)
                            if deposit.exists():
                                if self._send_deposit_to_pos(env, deposit):
                                    success_count += 1
                                else:
                                    fail_count += 1
                    except Exception as e:
                        _logger.error(" Failed to send pending transaction %s: %s", record_id, e)
                        fail_count += 1
                
                if cmd.exists():
                    result = {
                        "pending_sent": success_count,
                        "pending_failed": fail_count,
                        "completed_at": fields.Datetime.now().isoformat()
                    }
                    cmd.mark_done(result)
                    
        except Exception as e:
            _logger.exception(" Failed to send pending transactions: %s", e)

    def _send_deposit_to_pos(self, env, deposit):
        """Route deposit to vendor-specific handler based on Odoo UI pos_vendor setting."""
        pos_conf = _read_pos_conf()
        # Read vendor from Odoo UI settings (gas_station_cash.pos_vendor)
        pos_vendor = env['ir.config_parameter'].sudo().get_param(
            'gas_station_cash.pos_vendor', 'firstpro'
        )
        _logger.info("[POS] Routing deposit id=%s type=%s to vendor=%s",
                     deposit.id, deposit.deposit_type, pos_vendor)
        if pos_vendor == 'flowco':
            return self._send_deposit_to_flowco(pos_conf, deposit)
        return self._send_deposit_to_firstpro(pos_conf, deposit)

    def _send_deposit_to_firstpro(self, pos_conf, deposit):
        """
        Send deposit to FirstPro POS.

        Routing rules:
          oil        → POST /deposit  (cash amount, FirstPro reconciles on their side)
          engine_oil → SKIP           (FirstPro sends product_amount to us at CloseShift/EndOfDay)
        """
        # engine_oil is NOT sent to FirstPro — they push product_amount to us instead
        if deposit.deposit_type == 'engine_oil':
            _logger.info("[FirstPro] Skipping engine_oil deposit id=%s (FirstPro sends product_amount to us)",
                         deposit.id)
            deposit.write({'pos_status': 'skipped'})
            return True  # not an error — intentional skip

        try:
            pos_host    = pos_conf.get('pos_host', '127.0.0.1')
            pos_port    = pos_conf.get('pos_port', 9003)
            pos_timeout = pos_conf.get('pos_timeout', 5.0)
            url = f"http://{pos_host}:{pos_port}/deposit"

            transaction_id = deposit.pos_transaction_id or f"TXN-{deposit.id}"
            staff_ext_id = (deposit.staff_id.external_id if deposit.staff_id else None) or "UNKNOWN"
            _logger.debug("[FirstPro] Deposit details: staff_id=%s, amount=%.2f", staff_ext_id, deposit.total_amount or 0.0)
            payload = {
                "transaction_id": transaction_id,
                "staff_id":       staff_ext_id,
                "amount":         deposit.total_amount or 0.0,
            }

            _logger.info("[FirstPro] -> %s  payload=%s", url, payload)
            resp   = requests.post(url, json=payload, timeout=pos_timeout)
            result = resp.json() if resp.ok else {"status": "FAILED"}
            _logger.info("[FirstPro] <- %s", result)

            ok = result.get('status') == 'OK'
            deposit.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'ok' if ok else 'failed',
            })
            return ok
        except Exception as e:
            _logger.exception("[FirstPro] Failed to send deposit: %s", e)
            return False

    def _send_deposit_to_flowco(self, pos_conf, deposit):
        """
        Send deposit to FlowCo POS.
        Payload differences vs FirstPro:
          staff_id → staff.tag_id  (RFID card UID)
          type_id  → 'F' (oil) or 'L' (engine_oil)
          pos_id   → staff.pos_id  (POS terminal number)
        """
        try:
            pos_timeout = pos_conf.get('pos_timeout', 5.0)
            pos_map     = pos_conf.get('flowco_pos_map', {})

            # Resolve POS host/port from staff.pos_id via flowco_pos_map
            # Falls back to pos_host/pos_port if map is empty (single-POS setup)
            staff  = deposit.staff_id
            pos_id = int(staff.pos_id) if (staff and staff.pos_id) else 1

            if pos_map:
                if pos_id not in pos_map:
                    _logger.warning("[FlowCo] pos_id=%s not in flowco_pos_map, using first entry", pos_id)
                    pos_id = next(iter(pos_map))
                pos_host, pos_port = pos_map[pos_id]
            else:
                # Single-POS fallback (no flowco_pos_hosts configured)
                pos_host = pos_conf.get('pos_host', '127.0.0.1')
                pos_port = pos_conf.get('pos_port', 9003)

            url = f"http://{pos_host}:{pos_port}/POS/Deposit"

            transaction_id = deposit.pos_transaction_id or f"TXN-{deposit.id}"

            # type_id: oil → F (Fuel), engine_oil → L (Lube)
            type_id = 'F' if deposit.deposit_type == 'oil' else 'L'

            # tag_id from staff RFID card
            tag_id = (staff.tag_id if staff else None) or deposit.staff_external_id or "UNKNOWN"

            payload = {
                "transaction_id": transaction_id,
                "staff_id":       tag_id,
                "amount":         deposit.total_amount or 0.0,
                "type_id":        type_id,
                "pos_id":         pos_id,
            }

            _logger.info("[FlowCo] -> %s", url)
            _logger.info("[FlowCo]    payload: %s", payload)
            resp   = requests.post(url, json=payload, timeout=pos_timeout)
            result = resp.json() if resp.ok else {"status": "FAILED"}
            _logger.info("[FlowCo] <- %s", result)

            ok = result.get('status') == 'OK'
            deposit.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'ok' if ok else 'failed',
            })
            return ok
        except Exception as e:
            _logger.exception("[FlowCo] Failed to send deposit: %s", e)
            return False

    # =========================================================================
    # SHIFT AUDIT HELPERS
    # =========================================================================

    def _get_shift_deposits(self, env, shift_start=None):
        """Get all deposits within the current shift period for audit."""
        CashDeposit = env["gas.station.cash.deposit"].sudo()
        
        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('audit_id', '=', False),
        ]
        
        if shift_start:
            domain.append(('date', '>=', shift_start))
        
        deposits = CashDeposit.search(domain, order='date asc')
        _logger.info("Found %d deposits for shift audit", len(deposits))
        
        return deposits

    def _get_shift_withdrawals(self, env, shift_start=None):
        """Get all withdrawals within the current shift period for audit."""
        CashWithdrawal = env["gas.station.cash.withdrawal"].sudo()

        domain = [
            ('state', 'in', ['confirmed', 'audited']),
            ('audit_id', '=', False),
        ]

        if shift_start:
            domain.append(('date', '>=', shift_start))

        withdrawals = CashWithdrawal.search(domain, order='date asc')
        _logger.info("Found %d withdrawals for shift audit", len(withdrawals))

        return withdrawals
    
    def _get_shift_exchanges(self, env, shift_start=None):
        """Get all cash exchanges within the current shift period for audit."""
        CashExchange = env["gas.station.cash.exchange"].sudo()

        domain = [
            ('audit_id', '=', False),
        ]

        if shift_start:
            domain.append(('exchange_time', '>=', shift_start))

        exchanges = CashExchange.search(domain, order='exchange_time asc')
        _logger.info("Found %d exchanges for shift audit", len(exchanges))

        return exchanges

    def _get_shift_replenishments(self, env, shift_start=None):
        """Get all replenishments within the current shift period for audit."""
        Replenish = env["gas.station.cash.replenish"].sudo()

        domain = [('audit_id', '=', False)]
        if shift_start:
            domain.append(('replenish_date', '>=', shift_start))

        replenishments = Replenish.search(domain, order='replenish_date asc')
        _logger.info("Found %d replenishments for shift audit", len(replenishments))

        return replenishments

    def _create_shift_audit(self, env, cmd, audit_type, collection_result=None, product_amount=None, flowco_data=None, current_cash=None):
        """
        Create a shift audit record.
        
        Args:
            env: Odoo environment
            cmd: pos_command record
            audit_type: 'close_shift' or 'end_of_day'
            collection_result: dict with collection info (for EOD)
            product_amount: float ยอดขายสินค้าจาก POS (for reconciliation)
            flowco_data: dict — parsed FlowCo CloseShift payload (close_shift only)
            current_cash: float actual dispensable cash in machine at close time
        """
        try:
            ShiftAudit = env["gas.station.shift.audit"].sudo()

            # Read float_target BEFORE any ICP updates (prevents timing issue)
            float_target_snapshot = float(
                env['ir.config_parameter'].sudo().get_param(
                    'gas_station_cash.float_amount', 0
                ) or 0
            )
            
            shift_start = self._get_shift_start_time(env)
            _logger.info("Shift start time for audit: %s", shift_start)
            
            deposits = self._get_shift_deposits(env, shift_start)
            _logger.info("Found %d deposits for audit, product_amount=%s", len(deposits), product_amount)

            withdrawals = self._get_shift_withdrawals(env, shift_start)
            _logger.info("Found %d withdrawals for audit", len(withdrawals))

            exchanges = self._get_shift_exchanges(env, shift_start)
            _logger.info("Found %d exchanges for audit", len(exchanges))

            replenishments = self._get_shift_replenishments(env, shift_start)
            _logger.info("Found %d replenishments for audit", len(replenishments))
            
            if audit_type == 'end_of_day':
                audit = ShiftAudit.create_from_end_of_day(
                    command=cmd,
                    deposits=deposits,
                    collection_result=collection_result,
                    shift_start=shift_start,
                    product_amount=product_amount,
                    withdrawals=withdrawals,
                    exchanges=exchanges,
                    current_cash=current_cash,
                    replenishments=replenishments,
                )
            else:
                audit = ShiftAudit.create_from_shift_close(
                    command=cmd,
                    deposits=deposits,
                    shift_start=shift_start,
                    product_amount=product_amount,
                    flowco_data=flowco_data,
                    withdrawals=withdrawals,
                    exchanges=exchanges,
                    current_cash=current_cash,
                    float_target=float_target_snapshot,
                    replenishments=replenishments,
                )

            # Update float_amount + denomination settings to reflect actual dispensable cash
            if current_cash is not None:
                ICP = env['ir.config_parameter'].sudo()

                # Read target BEFORE overwriting (for float_target in audit)
                float_target_before = float(ICP.get_param('gas_station_cash.float_amount', 0) or 0)

                # 1. Update total float amount
                ICP.set_param('gas_station_cash.float_amount', str(current_cash))
                _logger.info("Updated float_amount setting to %.2f (target was %.2f)", current_cash, float_target_before)

                # 2. Query Glory for actual denomination breakdown
                inventory = self._glory_get_inventory(env)
                if inventory.get('success'):
                    # fv (satang) → ICP key mapping
                    FV_TO_KEY = {
                        100000: 'gas_station_cash.float_note_1000',
                        50000:  'gas_station_cash.float_note_500',
                        10000:  'gas_station_cash.float_note_100',
                        5000:   'gas_station_cash.float_note_50',
                        2000:   'gas_station_cash.float_note_20',
                        1000:   'gas_station_cash.float_coin_10',
                        500:    'gas_station_cash.float_coin_5',
                        200:    'gas_station_cash.float_coin_2',
                        100:    'gas_station_cash.float_coin_1',
                        50:     'gas_station_cash.float_coin_050',
                        25:     'gas_station_cash.float_coin_025',
                    }
                    # Reset all to 0 first
                    for key in FV_TO_KEY.values():
                        ICP.set_param(key, '0')
                    # Set actual quantities
                    for item in inventory.get('notes', []) + inventory.get('coins', []):
                        fv  = int(item.get('fv', 0) or 0)
                        qty = int(item.get('qty', 0) or 0)
                        if fv in FV_TO_KEY and qty > 0:
                            ICP.set_param(FV_TO_KEY[fv], str(qty))
                    _logger.info("Updated float denomination settings from Glory inventory")

                # 3. Update audit float_target with the pre-update value
                if audit and float_target_before != current_cash:
                    audit.write({'float_target': float_target_before})
                    _logger.info("Updated audit float_target to %.2f", float_target_before)
            
            _logger.info("✅ Created shift audit: %s (type=%s, deposits=%d, withdrawals=%d, product_amount=%.2f, current_cash=%.2f)", 
                        audit.name, audit_type, len(deposits), len(withdrawals), product_amount or 0, current_cash or 0)
            
            return audit
            
        except Exception as e:
            _logger.exception("❌ Failed to create shift audit: %s", e)
            return None

    # =========================================================================
    # CLOSE SHIFT - ASYNC PROCESSING
    # =========================================================================

    def _process_close_shift_async(self, dbname, uid, cmd_id, has_pending: bool, product_amount: float = None, flowco_data: dict = None):
        """Background thread to process close shift."""
        _logger.info("Processing close shift asynchronously...")
        try:
            time.sleep(2)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    return
                
                config = _read_collection_config(env=env)
                collect_enabled = config['close_shift_collect_cash']
                leave_float     = config['leave_float']
                reserve_denoms  = config['end_of_day_reserve_denoms']

                _logger.info("CloseShift collect_on_close_shift: %s leave_float: %s", collect_enabled, leave_float)

                collection_result = {}

                if collect_enabled:
                    collection_result = self._collect_to_box(
                        env,
                        mode='except_reserve' if leave_float else 'all',
                        staff_id=cmd.staff_external_id,
                        reserve_amount=float(
                            env['ir.config_parameter'].sudo().get_param(
                                'gas_station_cash.float_amount', 0
                            ) or 0
                        ) if leave_float else 0,
                    )

                    # Insufficient reserve: skip collection, notify user to acknowledge
                    if collection_result.get('insufficient_reserve', False):
                        _logger.info("CloseShift: insufficient reserve — skipping, notifying user")
                        current_cash    = collection_result.get('current_cash', 0.0)
                        required_reserve = collection_result.get('required_reserve', 0.0)

                        audit = self._create_shift_audit(
                            env, cmd, 'close_shift',
                            product_amount=product_amount,
                            flowco_data=flowco_data,
                            current_cash=current_cash,
                        )
                        result = {
                            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{cmd.staff_external_id or 'AUTO'}-01",
                            "total_cash": current_cash,
                            "collection_result": collection_result,
                            "completed_at": fields.Datetime.now().isoformat(),
                            "audit_id": audit.id if audit else None,
                            "product_amount": product_amount,
                            "insufficient_reserve": True,
                            "current_cash": current_cash,
                            "required_reserve": required_reserve,
                            "shortfall": required_reserve - current_cash,
                            "show_unlock_popup": False,
                            "collected_amount": 0.0,
                            "collected_breakdown": {},
                        }
                        cmd.mark_insufficient_reserve(result)
                        _logger.info("CloseShift command %s — insufficient reserve, audit=%s",
                                     cmd_id, audit.name if audit else "None")
                        return

                    # Check collection actually succeeded — inside collect_enabled block only
                    if not collection_result.get('success', False):
                        err = collection_result.get('error', 'Unknown collection error')
                        _logger.error("CloseShift: collection failed — %s", err)
                        cmd.mark_failed(f"Collection failed: {err}")
                        return

                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)

                # Derive current_cash from collection result or query Glory
                if collect_enabled and collection_result:
                    current_cash = collection_result.get('reserve_kept', 0.0)
                else:
                    inv = self._glory_get_inventory(env)
                    current_cash = inv.get('total_amount', 0.0) if inv.get('success') else 0.0

                # Create Shift Audit Record
                _logger.info("Creating shift audit for CloseShift (product_amount=%.2f, flowco_lines=%d, current_cash=%.2f)...",
                             product_amount or 0, len((flowco_data or {}).get('data', [])), current_cash)
                audit = self._create_shift_audit(
                    env, cmd, 'close_shift',
                    product_amount=product_amount,
                    flowco_data=flowco_data,
                    current_cash=current_cash,
                )
                audit_id = audit.id if audit else None

                result = {
                    "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{cmd.staff_external_id or 'AUTO'}-01",
                    "total_cash": shift_totals.get('total_cash', 0.0),
                    "collection_result": collection_result,
                    "completed_at": fields.Datetime.now().isoformat(),
                    "audit_id": audit_id,
                    "product_amount": product_amount,
                }

                # Print close shift receipt (non-critical)
                if audit:
                    try:
                        company = env['res.company'].sudo().search([], limit=1)
                        ICP = env['ir.config_parameter'].sudo()
                        from datetime import timedelta
                        close_local = fields.Datetime.now() + timedelta(hours=7)
                        _send_print_receipt("print/close_shift", {
                            "company_name":      company.name or "",
                            "branch_name":       ICP.get_param("gas_station_cash.branch_name", ""),
                            "address":           company.street or "",
                            "phone":             company.phone or "",
                            "reference":         audit.name or "",
                            "shift_number":      audit.shift_number or "",
                            "staff_name":        cmd.staff_external_id or "",
                            "datetime_str":      close_local.strftime("%d/%m/%Y %H:%M:%S"),
                            "total_deposits":    int((audit.total_all_deposits or 0) * 100),
                            "total_withdrawals": int((audit.total_withdrawals or 0) * 100),
                            "shift_net_total":   int((audit.shift_net_total or 0) * 100),
                            "pos_total":         int((audit.pos_reported_sale_total or 0) * 100),
                            "recon_status":      audit.reconciliation_status or "pending",
                        })
                    except Exception as pe:
                        _logger.warning("CloseShift print failed: %s", pe)

                cmd.mark_done(result)
                _logger.info("CloseShift completed, audit_id=%s, product_amount=%.2f", audit_id, product_amount or 0)
                    
        except Exception as e:
            _logger.exception(" Failed to process close shift: %s", e)
            try:
                import odoo
                registry = odoo.registry(dbname)
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, uid, {})
                    cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                    if cmd.exists():
                        cmd.mark_failed(f"CloseShift error: {str(e)}")
            except Exception as mark_err:
                _logger.error("Failed to mark CloseShift command as failed: %s", mark_err)

    # =========================================================================
    # END OF DAY - ASYNC PROCESSING (UPDATED WITH STATUS POLLING)
    # =========================================================================

    def _process_end_of_day_async(self, dbname, uid, cmd_id, product_amount: float = None):
        """
        Background thread to process end of day.
        
        Args:
            dbname: Database name
            uid: User ID
            cmd_id: Command ID
            product_amount: float ยอดขายสินค้าจาก POS (for reconciliation)

        FlowCo EOD flow (is_flowco_eod_marker=True in cmd.payload):
            - ไม่ create audit ใหม่
            - หา last close_shift audit → mark เป็น end_of_day ผ่าน action_mark_as_eod()
            - สร้าง Daily Report จาก audit นั้น

        Steps:
        1. Wait for processing delay
        2. Read collection mode from config
        3. Check inventory and collect (if sufficient reserve)
        4. If insufficient reserve: notify and complete (no unlock popup)
        5. If normal: Poll Glory status until IDLE, show unlock popup
        6. Mark command as done
        """
        try:
            delay = 2
            _logger.info("EndOfDay processing started (product_amount=%.2f), waiting %d seconds...", 
                        product_amount or 0, delay)
            time.sleep(delay)
            
            import odoo
            registry = odoo.registry(dbname)
            
            with registry.cursor() as cr:
                env = odoo.api.Environment(cr, uid, {})
                cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                
                if not cmd.exists():
                    _logger.warning("Command %s not found", cmd_id)
                    return

                # ── FlowCo EOD: mark last close_shift audit as EOD ────────────
                try:
                    payload = json.loads(cmd.payload_in or '{}')
                except Exception:
                    payload = {}
                if payload.get('is_flowco_eod_marker'):
                    _logger.info("[FlowCo] EOD marker received — finding last close_shift audit to mark as EOD")
                    ShiftAudit = env["gas.station.shift.audit"].sudo()
                    last_shift = ShiftAudit.search(
                        [('audit_type', '=', 'close_shift')],
                        order='close_time desc', limit=1
                    )
                    if last_shift:
                        _logger.info("[FlowCo] Marking audit %s as end_of_day", last_shift.name)
                        last_shift.action_mark_as_eod()
                        cmd.mark_done({
                            "flowco_eod": True,
                            "marked_audit": last_shift.name,
                            "audit_id": last_shift.id,
                        })
                        # Create Daily Report
                        try:
                            _logger.info("📊 Creating Daily Report from FlowCo EOD audit: %s", last_shift.name)
                            DailyReport = env["gas.station.daily.report"].sudo()
                            daily_report = DailyReport.create_from_eod(
                                eod_audit=last_shift,
                                inventory_before_collection=None
                            )
                            _logger.info("📊 ✅ Created Daily Report: %s", daily_report.name)
                        except Exception as e:
                            _logger.exception("📊 ❌ Failed to create Daily Report: %s", e)
                        cmd.dismiss_overlay()
                    else:
                        _logger.warning("[FlowCo] No close_shift audit found to mark as EOD")
                        cmd.mark_done({"flowco_eod": True, "marked_audit": None})
                    return
                # ─────────────────────────────────────────────────────────────

                # Step 1: Read collection config
                config = _read_collection_config(env=env)
                collect_enabled  = config['end_of_day_collect_cash']   # honour the toggle
                collect_mode     = config['end_of_day_collect_mode']
                reserve_amount   = config['end_of_day_reserve_amount']
                leave_float      = config['leave_float']

                _logger.info(
                    "EndOfDay: collect_enabled=%s mode=%s reserve=%.2f leave_float=%s",
                    collect_enabled, collect_mode, reserve_amount, leave_float,
                )

                # Step 2: Update overlay message - Checking inventory
                cmd.update_overlay_message("Checking cash inventory...")

                # Step 3: Collect cash only when toggle is enabled
                if not collect_enabled:
                    _logger.info("EndOfDay: collection disabled by toggle — skipping collect")
                    collection_result = {
                        'success': True,
                        'collected_amount': 0.0,
                        'reserve_kept': 0.0,
                        'collected_breakdown': {},
                        'reserve_breakdown': {},
                        'skipped': True,
                    }
                else:
                    collection_result = self._collect_to_box(
                        env,
                        mode=collect_mode,
                        staff_id=cmd.staff_external_id,
                        reserve_amount=reserve_amount if collect_mode == 'except_reserve' else 0
                    )
                    _logger.info("Collection result: %s", collection_result)

                    # Step 4: Check if insufficient reserve
                    if collection_result.get('insufficient_reserve', False):
                        _logger.info("Insufficient reserve - notifying user")

                        current_cash     = collection_result.get('current_cash', 0.0)
                        required_reserve = collection_result.get('required_reserve', 0.0)
                        shortfall        = required_reserve - current_cash

                        shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)

                        _logger.info("Creating shift audit for EndOfDay (insufficient reserve)...")
                        audit = self._create_shift_audit(env, cmd, 'end_of_day', collection_result, product_amount,
                                                         current_cash=current_cash)

                        result = {
                            "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                            "final_shift_cash": shift_totals.get('total_cash', 0.0),
                            "final_shift_transactions": shift_totals.get('count', 0),
                            "collection_mode": collect_mode,
                            "collection_result": collection_result,
                            "completed_at": fields.Datetime.now().isoformat(),
                            "insufficient_reserve": True,
                            "current_cash": current_cash,
                            "required_reserve": required_reserve,
                            "shortfall": shortfall,
                            "show_unlock_popup": False,
                            "collected_amount": 0.0,
                            "collected_breakdown": {},
                            "audit_id": audit.id if audit else None,
                        }

                        cmd.mark_insufficient_reserve(result)
                        _logger.info(
                            "EndOfDay command %s - completed (insufficient reserve), audit=%s",
                            cmd_id, audit.name if audit else None,
                        )

                        if audit:
                            try:
                                _logger.info("Creating Daily Report from EOD audit (insufficient reserve): %s", audit.name)
                                DailyReport = env["gas.station.daily.report"].sudo()
                                daily_report = DailyReport.create_from_eod(
                                    eod_audit=audit,
                                    inventory_before_collection=None,
                                )
                                _logger.info("Created Daily Report: %s", daily_report.name)
                            except Exception as e:
                                _logger.exception("Failed to create Daily Report: %s", e)
                        return

                    # Check collection actually succeeded
                    if not collection_result.get('success', False):
                        err = collection_result.get('error', 'Unknown collection error')
                        _logger.error("EOD: collection failed — %s", err)
                        cmd.mark_failed(f"Collection failed: {err}")
                        return

                # Step 5: Normal flow - Update overlay and poll Glory status
                cmd.update_overlay_message("Collecting cash to Collection Box...")
                
                poll_result = self._glory_wait_for_idle(env=env)
                _logger.info("Poll result: %s", poll_result)

                # Check Glory actually returned to IDLE
                if not poll_result.get('success', False):
                    poll_err = poll_result.get('error', 'Glory did not return to IDLE')
                    _logger.error("EOD: Glory not idle after collection — %s", poll_err)
                    cmd.mark_failed(f"Glory not idle after collection: {poll_err}")
                    return
                
                # Step 6: Calculate shift totals
                shift_totals = self._calculate_shift_pos_total(env, cmd.staff_external_id)

                # Derive current_cash from collection result
                if collection_result:
                    current_cash = collection_result.get('reserve_kept', 0.0)
                else:
                    inv = self._glory_get_inventory(env)
                    current_cash = inv.get('total_amount', 0.0) if inv.get('success') else 0.0

                # Create Shift Audit Record
                _logger.info("Creating shift audit for EndOfDay (product_amount=%.2f, current_cash=%.2f)...",
                             product_amount or 0, current_cash)
                audit = self._create_shift_audit(env, cmd, 'end_of_day', collection_result, product_amount,
                                                 current_cash=current_cash)
                
                # Step 7: Prepare result with collection data for frontend
                result = {
                    "day_summary": f"EOD-{fields.Datetime.now().strftime('%Y%m%d')}",
                    "final_shift_cash": shift_totals.get('total_cash', 0.0),
                    "final_shift_transactions": shift_totals.get('count', 0),
                    "collection_mode": collect_mode,
                    "collection_result": collection_result,
                    "poll_result": poll_result,
                    "completed_at": fields.Datetime.now().isoformat(),
                    # Data for unlock popup
                    "show_unlock_popup": True,
                    "collected_amount": collection_result.get('collected_amount', 0.0),
                    "collected_breakdown": collection_result.get('collected_breakdown', {}),
                    "audit_id": audit.id if audit else None,
                }
                
                # Step 8: Mark as done with collection_complete status
                # This will update the overlay to show unlock popup
                cmd.mark_collection_complete(result)
                _logger.info("EndOfDay command %s - collection complete, audit=%s", cmd_id, audit.name if audit else None)
                
                # Step 9: Create Daily Report
                if audit:
                    try:
                        _logger.info("📊 Creating Daily Report from EOD audit: %s", audit.name)
                        DailyReport = env["gas.station.daily.report"].sudo()
                        
                        # Get inventory before collection (from collection_result)
                        inventory_before = None
                        if collection_result:
                            inventory_before = collection_result.get('inventory_before_collection')
                        
                        daily_report = DailyReport.create_from_eod(
                            eod_audit=audit,
                            inventory_before_collection=inventory_before
                        )
                        _logger.info("📊 ✅ Created Daily Report: %s", daily_report.name)

                        # Print EOD receipt (non-critical)
                        try:
                            company = env['res.company'].sudo().search([], limit=1)
                            ICP = env['ir.config_parameter'].sudo()
                            from datetime import timedelta
                            close_local = fields.Datetime.now() + timedelta(hours=7)
                            _send_print_receipt("print/eod", {
                                "company_name":           company.name or "",
                                "branch_name":            ICP.get_param("gas_station_cash.branch_name", ""),
                                "address":                company.street or "",
                                "phone":                  company.phone or "",
                                "reference":              audit.name or "",
                                "datetime_str":           close_local.strftime("%d/%m/%Y %H:%M:%S"),
                                "shift_count":            audit.shift_count_in_period or 0,
                                "total_oil":              int((audit.eod_total_oil or 0) * 100),
                                "total_engine_oil":       int((audit.eod_total_engine_oil or 0) * 100),
                                "total_coffee_shop":      int((audit.eod_total_coffee_shop or 0) * 100),
                                "total_convenient_store": int((audit.eod_total_convenient_store or 0) * 100),
                                "total_rental":           int((audit.eod_total_rental or 0) * 100),
                                "total_other":            int((audit.eod_total_other or 0) * 100),
                                "eod_grand_total":        int((audit.eod_grand_total or 0) * 100),
                                "collected_amount":       int((audit.collected_amount or 0) * 100),
                                "reserve_kept":           int((audit.reserve_kept or 0) * 100),
                            })
                        except Exception as pe:
                            _logger.warning("EOD print failed: %s", pe)

                    except Exception as e:
                        _logger.exception("📊 ❌ Failed to create Daily Report: %s", e)
                        # Don't fail the EOD process if report creation fails
                    
        except Exception as e:
            _logger.exception("Failed to process end of day async: %s", e)
            try:
                import odoo
                registry = odoo.registry(dbname)
                with registry.cursor() as cr:
                    env = odoo.api.Environment(cr, uid, {})
                    cmd = env["gas.station.pos_command"].sudo().browse(cmd_id)
                    if cmd.exists():
                        cmd.mark_failed(f"EOD error: {str(e)}")
            except Exception as mark_err:
                _logger.error("Failed to mark EOD command as failed: %s", mark_err)

    # =========================================================================
    # UNIT LOCK/UNLOCK ENDPOINTS (Step-by-Step)
    # =========================================================================

    @http.route("/gas_station_cash/unlock_unit", type="json", auth="user", methods=["POST"])
    def unlock_unit(self, **kwargs):
        """
        API endpoint to unlock a specific unit (notes or coins).
        """
        command_id = kwargs.get('command_id')
        target = kwargs.get('target', 'notes')  # 'notes' or 'coins'
        
        _logger.info(" Unlock %s request received (command_id=%s)", target, command_id)
        
        result = {
            'success': False,
            'message': '',
            'error': None,
        }
        
        try:
            unlock_result = self._glory_unlock_unit(target=target)
            
            if unlock_result['success']:
                result['success'] = True
                result['message'] = f'{target.capitalize()} box unlocked'
            else:
                result['error'] = unlock_result.get('error', 'Unlock failed')
                
        except Exception as e:
            _logger.exception(" Failed to unlock %s: %s", target, e)
            result['error'] = str(e)
        
        return result

    @http.route("/gas_station_cash/lock_unit", type="json", auth="user", methods=["POST"])
    def lock_unit(self, **kwargs):
        """
        API endpoint to lock a specific unit (notes or coins).
        """
        command_id = kwargs.get('command_id')
        target = kwargs.get('target', 'notes')  # 'notes' or 'coins'
        
        _logger.info(" Lock %s request received (command_id=%s)", target, command_id)
        
        result = {
            'success': False,
            'message': '',
            'error': None,
        }
        
        try:
            lock_result = self._glory_lock_unit(target=target)
            
            if lock_result['success']:
                result['success'] = True
                result['message'] = f'{target.capitalize()} box locked'
            else:
                result['error'] = lock_result.get('error', 'Lock failed')
                
        except Exception as e:
            _logger.exception(" Failed to lock %s: %s", target, e)
            result['error'] = str(e)
        
        return result

    @http.route("/gas_station_cash/complete_collection", type="json", auth="user", methods=["POST"])
    def complete_collection(self, **kwargs):
        """
        API endpoint to mark collection as complete after all boxes replaced.
        """
        command_id = kwargs.get('command_id')
        coins_completed = kwargs.get('coins_completed', False)
        notes_completed = kwargs.get('notes_completed', False)
        
        _logger.info(" Complete collection request (command_id=%s, coins=%s, notes=%s)",
                     command_id, coins_completed, notes_completed)
        
        result = {
            'success': True,
            'message': 'Collection completed',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "completed_at": fields.Datetime.now().isoformat(),
                        "coins_box_replaced": coins_completed,
                        "notes_box_replaced": notes_completed,
                    })
        except Exception as e:
            _logger.exception(" Failed to complete collection: %s", e)
            # Still return success - the boxes are replaced
        
        return result

    @http.route("/gas_station_cash/skip_unlock", type="json", auth="user", methods=["POST"])
    def skip_unlock(self, **kwargs):
        """
        API endpoint to skip unlocking and close the overlay.
        Called from frontend when user clicks "Skip" button.
        """
        _logger.info("Skip unlock request received")
        
        command_id = kwargs.get('command_id')
        current_step = kwargs.get('current_step', 1)
        coins_completed = kwargs.get('coins_completed', False)
        notes_completed = kwargs.get('notes_completed', False)
        
        result = {
            'success': True,
            'message': 'Unlock skipped',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "unlock_skipped": True,
                        "skipped_at": fields.Datetime.now().isoformat(),
                        "skipped_at_step": current_step,
                        "coins_box_replaced": coins_completed,
                        "notes_box_replaced": notes_completed,
                    })
        except Exception as e:
            _logger.exception("Failed to skip unlock: %s", e)
        
        return result

    @http.route("/gas_station_cash/close_insufficient_reserve", type="json", auth="user", methods=["POST"])
    def close_insufficient_reserve(self, **kwargs):
        """
        API endpoint to close the insufficient reserve overlay.
        Called from frontend when user acknowledges the insufficient reserve warning.
        """
        _logger.info("Close insufficient reserve request received")
        
        command_id = kwargs.get('command_id')
        
        result = {
            'success': True,
            'message': 'Insufficient reserve acknowledged',
        }
        
        try:
            if command_id:
                cmd = request.env["gas.station.pos_command"].sudo().browse(command_id)
                if cmd.exists():
                    cmd.mark_done({
                        "acknowledged_at": fields.Datetime.now().isoformat(),
                        "acknowledged_insufficient_reserve": True,
                    })
        except Exception as e:
            _logger.exception("Failed to close insufficient reserve: %s", e)
        
        return result

    # =========================================================================
    # CLOSE SHIFT ENDPOINT
    # =========================================================================

    def _handle_close_shift(self, **kwargs):
        """Handle CloseShift request from POS."""
        _ensure_heartbeat_worker()  # start after fork, safe here
        _logger.info("=" * 80)
        _logger.info("📥 CLOSE SHIFT REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"

        # ── DEBUG: log the exact message FlowCo sent ─────────────────────
        _logger.debug("[FlowCo CloseShift] RAW REQUEST BODY:\n%s", raw)
        _logger.info("[FlowCo CloseShift] Raw: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        _logger.info("[FlowCo CloseShift] shift_number=%s pos_id=%s entries=%s",
                     data.get('shift_number'), data.get('pos_id'), len(data.get('data', [])))
        for e in data.get('data', []):
            _logger.info("[FlowCo CloseShift]   staff=%s fuel_sale=%s fuel_drop=%s lube_sale=%s lube_drop=%s status=%s",
                         e.get('staff_id'), e.get('saleamt_fuel'), e.get('dropamt_fuel'),
                         e.get('saleamt_lube'), e.get('dropamt_lube'), e.get('status'))
            
        # Extract fields from request
        staff_id = data.get("staff_id") or self._get_default_staff_id()
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)

        # ── Build flowco_data dict to pass through to audit creation ─────
        # Carry shift_number, pos_id, timestamp, and the full data[] array
        flowco_data = {
            'shift_number': data.get('shift_number'),
            'pos_id':       data.get('pos_id'),
            'timestamp':    data.get('timestamp'),
            'data':         data.get('data') or [],
        }
        _logger.debug("[FlowCo CloseShift] flowco_data to persist: %s", flowco_data)
        
        # Extract product_amount:
        #   FirstPro → engine oil reconciliation amount (they send to us)
        #   FlowCo   → generic product amount from POS
        pos_vendor = request.env['ir.config_parameter'].sudo().get_param(
            'gas_station_cash.pos_vendor', 'firstpro'
        )

        # Validate: URL must match configured vendor
        vendor_from_url = 'flowco' if request.httprequest.path.lower().startswith('/pos/') else 'firstpro'
        if vendor_from_url != pos_vendor:
            _logger.warning(
                "Vendor mismatch: request from %s but configured for %s — rejected",
                vendor_from_url, pos_vendor
            )
            return self._json_response({
                "status": "ERROR",
                "description": f"Vendor mismatch: system is configured for {pos_vendor}",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        product_amount = None
        engine_oil_amount = None  # FirstPro only
        if "product_amount" in data:
            try:
                product_amount = float(data.get("product_amount", 0))
                if pos_vendor == 'firstpro':
                    engine_oil_amount = product_amount
                    _logger.info("[FirstPro] CloseShift engine_oil_amount=%.2f", engine_oil_amount)
            except (ValueError, TypeError):
                product_amount = 0.0

        _logger.info("CloseShift data: vendor=%s staff_id=%s pos_shift_id=%s product_amount=%s engine_oil_amount=%s",
                    pos_vendor, staff_id, pos_shift_id, product_amount, engine_oil_amount)
        
        # Check for pending transactions
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            cmd = self._create_command("close_shift", staff_id, {
                "pending_count": pending_count,
                "product_amount": product_amount,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("Failed to push overlay: %s", e)
            
            dbname = request.env.cr.dbname
            uid = request.env.uid
            deposit_ids = [p.id for p in pending_transactions]
            
            if deposit_ids:
                thread = threading.Thread(
                    target=self._send_pending_transactions_async,
                    args=(dbname, uid, deposit_ids, "gas.station.cash.deposit", cmd.id)
                )
                thread.daemon = True
                thread.start()
            
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
            })
        
        # No pending - process normally
        cmd = self._create_command("close_shift", staff_id, {
            "product_amount": product_amount,
        }, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
        except Exception as e:
            _logger.exception("Failed to push overlay: %s", e)
        
        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_close_shift_async, 
            args=(dbname, uid, cmd.id, False, product_amount, flowco_data)
        )
        thread.daemon = True
        thread.start()
        
        return self._json_response({
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-01",
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "product_amount": product_amount,
            "discription": "Close Shift Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        })
    
    @http.route("/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift(self, **kwargs):
        return self._handle_close_shift(**kwargs)

    @http.route("/POS/CloseShift", type="http", auth="public", methods=["POST"], csrf=False)
    def close_shift_pos_prefix(self, **kwargs):
        _logger.info("Processing POS CloseShift request... (URL: %s)", request.httprequest.path)
        return self._handle_close_shift(**kwargs)

    # =========================================================================
    # END OF DAY ENDPOINT
    # =========================================================================

    def _handle_end_of_day(self, **kwargs):
        """Handle EndOfDay request from POS."""
        _ensure_heartbeat_worker()  # start after fork, safe here
        _logger.info("=" * 80)
        _logger.info("📥 END OF DAY REQUEST RECEIVED")
        
        raw = request.httprequest.get_data(as_text=True) or "{}"
        _logger.info("[FlowCo EndOfDay] Raw: %s", raw)
        
        try:
            data = json.loads(raw)
        except Exception as e:
            return self._json_response({
                "shift_id": "",
                "status": "FAILED", 
                "discription": "Invalid JSON",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        _logger.info("[FlowCo EndOfDay] shift_number=%s pos_id=%s entries=%s",
                     data.get('shift_number'), data.get('pos_id'), len(data.get('data', [])))

        staff_id = data.get("staff_id") or self._get_default_staff_id()
        pos_shift_id = data.get("shiftid")
        if pos_shift_id is not None:
            pos_shift_id = str(pos_shift_id)
        
        # Extract product_amount:
        #   FirstPro → engine oil reconciliation amount (they send to us)
        #   FlowCo   → generic product amount from POS
        pos_vendor = request.env['ir.config_parameter'].sudo().get_param(
            'gas_station_cash.pos_vendor', 'firstpro'
        )

        # Validate: URL must match configured vendor
        vendor_from_url = 'flowco' if request.httprequest.path.lower().startswith('/pos/') else 'firstpro'
        if vendor_from_url != pos_vendor:
            _logger.warning(
                "Vendor mismatch: request from %s but configured for %s — rejected",
                vendor_from_url, pos_vendor
            )
            return self._json_response({
                "status": "ERROR",
                "description": f"Vendor mismatch: system is configured for {pos_vendor}",
                "time_stamp": fields.Datetime.now().isoformat(),
            }, status=400)

        product_amount = None
        engine_oil_amount = None  # FirstPro only
        if "product_amount" in data:
            try:
                product_amount = float(data.get("product_amount", 0))
                if pos_vendor == 'firstpro':
                    engine_oil_amount = product_amount
                    _logger.info("[FirstPro] EndOfDay engine_oil_amount=%.2f", engine_oil_amount)
            except (ValueError, TypeError):
                product_amount = 0.0

        _logger.info("EndOfDay data: vendor=%s staff_id=%s pos_shift_id=%s product_amount=%s engine_oil_amount=%s",
                    pos_vendor, staff_id, pos_shift_id, product_amount, engine_oil_amount)
        
        # Check for pending transactions
        pending_transactions = self._get_pending_transactions()
        pending_count = len(pending_transactions)
        
        if pending_count > 0:
            cmd = self._create_command("end_of_day", staff_id, {
                "pending_count": pending_count,
                "product_amount": product_amount,
            }, pos_shift_id=pos_shift_id)
            
            try:
                cmd.push_overlay()
            except Exception as e:
                _logger.exception("Failed to push overlay: %s", e)
            
            dbname = request.env.cr.dbname
            uid = request.env.uid
            deposit_ids = [p.id for p in pending_transactions]
            
            if deposit_ids:
                thread = threading.Thread(
                    target=self._send_pending_transactions_async,
                    args=(dbname, uid, deposit_ids, "gas.station.cash.deposit", cmd.id)
                )
                thread.daemon = True
                thread.start()
            
            return self._json_response({
                "shift_id": "",
                "status": "FAILED",
                "discription": "Sending pending transaction",
                "time_stamp": fields.Datetime.now().isoformat(),
            })
        
        # No pending - process normally
        cmd = self._create_command("end_of_day", staff_id, {
            "product_amount": product_amount,
        }, pos_shift_id=pos_shift_id)
        
        try:
            cmd.push_overlay()
        except Exception as e:
            _logger.exception("Failed to push overlay: %s", e)

        shift_totals = self._calculate_shift_pos_total(request.env, staff_id)
        
        dbname = request.env.cr.dbname
        uid = request.env.uid
        
        thread = threading.Thread(
            target=self._process_end_of_day_async, 
            args=(dbname, uid, cmd.id, product_amount)
        )
        thread.daemon = True
        thread.start()

        return self._json_response({
            "shift_id": f"SHIFT-{fields.Datetime.now().strftime('%Y%m%d')}-{staff_id}-EOD",
            "status": "OK",
            "total_cash_amount": shift_totals.get('total_cash', 0.0),
            "product_amount": product_amount,
            "discription": "Deposit Success",
            "time_stamp": fields.Datetime.now().isoformat(),
        })
    
    @http.route("/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    @http.route("/POS/EndOfDay", type="http", auth="public", methods=["POST"], csrf=False)
    def end_of_day_pos_prefix(self, **kwargs):
        return self._handle_end_of_day(**kwargs)

    # =========================================================================
    # HEARTBEAT ENDPOINT
    # =========================================================================

    @http.route("/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat(self, **kwargs):
        return self._json_response({
            "status": "acknowledged",
            "timestamp": fields.Datetime.now().isoformat(),
        })

    @http.route("/POS/HeartBeat", type="http", auth="public", methods=["POST"], csrf=False)
    def heartbeat_pos_prefix(self, **kwargs):
        return self._json_response({
            "status": "acknowledged",
            "timestamp": fields.Datetime.now().isoformat(),
        })
    # =========================================================================
    # OFFLINE MODE ENDPOINTS
    # =========================================================================

    @http.route("/gas_station_cash/pos/connection_status", type="json", auth="user", methods=["POST"], csrf=False)
    def pos_connection_status(self, **kwargs):
        """Return POS connection status and offline mode state for frontend polling."""
        _PosHeartbeatWorker.start()

        ICP = request.env["ir.config_parameter"].sudo()
        pos_connected  = ICP.get_param("gas_station_cash.pos_connected", "true") in ("true", "True", "1")
        offline_mode   = ICP.get_param("gas_station_cash.offline_mode_active", "false") in ("true", "True", "1")

        # Read offline availability from [options] section in odoo.conf
        # pos_offline_mode_availability is in [options], NOT [pos_http_config]
        try:
            conf_path = getattr(tools.config, "rcfile", None)
            if conf_path:
                import configparser as _cp
                _parser = _cp.ConfigParser()
                _parser.read(conf_path)
                raw = _parser.get("options", "pos_offline_mode_availability", fallback="false")
                offline_available = raw.strip().lower() in ("true", "1", "yes")
            else:
                offline_available = False   # default OFF if conf not found
        except Exception:
            offline_available = False       # default OFF on error

        return {
            "pos_connected":       pos_connected,
            "offline_mode_active": offline_mode,
            "offline_available":   offline_available,
        }

    @http.route("/gas_station_cash/offline/activate", type="json", auth="user", methods=["POST"], csrf=False)
    def activate_offline_mode(self, **kwargs):
        """User manually activates offline mode."""
        ICP = request.env["ir.config_parameter"].sudo()
        ICP.set_param("gas_station_cash.offline_mode_active", "true")
        _logger.info("[OfflineMode] Activated by user")
        return {"status": "ok", "offline_mode_active": True}

    @http.route("/gas_station_cash/offline/deactivate", type="json", auth="user", methods=["POST"], csrf=False)
    def deactivate_offline_mode(self, **kwargs):
        """Deactivate offline mode — called when POS reconnects or user manually exits."""
        ICP = request.env["ir.config_parameter"].sudo()
        ICP.set_param("gas_station_cash.offline_mode_active", "false")
        _logger.info("[OfflineMode] Deactivated")
        return {"status": "ok", "offline_mode_active": False}