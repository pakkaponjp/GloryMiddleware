# -*- coding: utf-8 -*-
"""
File: models/pos_connector_mixin.py
Description: Mixin for POS TCP communication with queuing support.

This mixin provides methods to:
1. Send deposits to POS over TCP/HTTP
2. Queue transactions when POS is offline
3. Retry failed transactions
"""

from odoo import api, fields, models, _
import json
import logging
import socket
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)


class PosConnectorMixin(models.AbstractModel):
    _name = 'pos.connector.mixin'
    _description = 'POS TCP Connector Mixin'

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    def _get_pos_config(self):
        """
        Get POS connection configuration.
        Override this in your implementation to get from system parameters.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        
        return {
            'host': ICP.get_param('pos.tcp.host', 'localhost'),
            'port': int(ICP.get_param('pos.tcp.port', 9000)),
            'timeout': int(ICP.get_param('pos.tcp.timeout', 30)),
            'use_http': ICP.get_param('pos.tcp.use_http', 'true').lower() == 'true',
            'http_base_url': ICP.get_param('pos.tcp.http_base_url', 'http://localhost:9000'),
        }

    # =========================================================================
    # POS COMMUNICATION
    # =========================================================================

    def _send_tcp_message(self, message: str, config: dict = None):
        """
        Send a message over TCP socket.
        
        Args:
            message: JSON string to send
            config: Connection config dict
            
        Returns:
            dict: Response from POS or error dict
        """
        if config is None:
            config = self._get_pos_config()
        
        host = config.get('host', 'localhost')
        port = config.get('port', 9000)
        timeout = config.get('timeout', 30)
        
        try:
            _logger.info("📡 Connecting to POS at %s:%s...", host, port)
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            
            # Send message
            _logger.info("📤 Sending: %s", message[:200])
            sock.sendall(message.encode('utf-8'))
            
            # Receive response
            response_data = b''
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                # Check for complete JSON (simple check)
                try:
                    json.loads(response_data.decode('utf-8'))
                    break
                except json.JSONDecodeError:
                    continue
            
            sock.close()
            
            response_str = response_data.decode('utf-8')
            _logger.info("📥 Received: %s", response_str[:200])
            
            return json.loads(response_str)
            
        except socket.timeout:
            _logger.warning("⏰ TCP connection timeout to POS")
            return {'ok': False, 'error': 'Connection timeout', 'offline': True}
        except ConnectionRefusedError:
            _logger.warning("🚫 POS connection refused at %s:%s", host, port)
            return {'ok': False, 'error': 'Connection refused', 'offline': True}
        except Exception as e:
            _logger.exception("❌ TCP communication error: %s", e)
            return {'ok': False, 'error': str(e), 'offline': True}

    def _send_http_message(self, endpoint: str, payload: dict, config: dict = None):
        """
        Send a message over HTTP.
        
        Args:
            endpoint: API endpoint (e.g., '/Deposit')
            payload: Dictionary to send as JSON
            config: Connection config dict
            
        Returns:
            dict: Response from POS or error dict
        """
        if config is None:
            config = self._get_pos_config()
        
        base_url = config.get('http_base_url', 'http://localhost:9000')
        timeout = config.get('timeout', 30)
        url = f"{base_url.rstrip('/')}{endpoint}"
        
        try:
            _logger.info("📡 Sending HTTP POST to %s...", url)
            _logger.info("📤 Payload: %s", json.dumps(payload, ensure_ascii=False)[:200])
            
            response = requests.post(
                url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=timeout
            )
            
            _logger.info("📥 Response status: %s", response.status_code)
            _logger.info("📥 Response body: %s", response.text[:200])
            
            if response.status_code == 200:
                data = response.json()
                data['ok'] = data.get('status', '').upper() == 'OK'
                return data
            else:
                return {
                    'ok': False,
                    'error': f'HTTP {response.status_code}: {response.text}',
                    'offline': False
                }
                
        except requests.exceptions.Timeout:
            _logger.warning("⏰ HTTP timeout to POS at %s", url)
            return {'ok': False, 'error': 'Request timeout', 'offline': True}
        except requests.exceptions.ConnectionError:
            _logger.warning("🚫 POS HTTP connection error at %s", url)
            return {'ok': False, 'error': 'Connection error', 'offline': True}
        except Exception as e:
            _logger.exception("❌ HTTP communication error: %s", e)
            return {'ok': False, 'error': str(e), 'offline': True}

    # =========================================================================
    # DEPOSIT API
    # =========================================================================

    def pos_send_deposit(self, transaction_id: str, staff_id: str, amount: float, 
                         terminal_id: str = None):
        """
        Send a deposit transaction to POS.
        
        Request format (to POS):
            {
                "transaction_id": "TXN-20250926-12345",
                "staff_id": "CASHIER-0007",
                "amount": 4000
            }
        
        Expected response:
            {
                "transaction_id": "TXN-20250926-12345",
                "status": "OK",
                "discription": "Deposit Success",
                "time_stamp": "2025-09-26T17:45:00+07:00"
            }
        
        Returns:
            dict: Response with 'ok' boolean indicating success
        """
        config = self._get_pos_config()
        
        payload = {
            "transaction_id": transaction_id,
            "staff_id": staff_id,
            "amount": float(amount),
        }
        
        if terminal_id:
            payload["terminal_id"] = terminal_id
        
        _logger.info("💰 Sending Deposit to POS: txn=%s, staff=%s, amount=%s",
                    transaction_id, staff_id, amount)
        
        if config.get('use_http', True):
            result = self._send_http_message('/Deposit', payload, config)
        else:
            message = json.dumps({
                "command": "Deposit",
                "data": payload
            }, ensure_ascii=False)
            result = self._send_tcp_message(message, config)
        
        # Handle offline case - queue for later
        if result.get('offline'):
            job = self._create_offline_job('deposit', payload)
            result['job_id'] = job.id if job else None
            result['message'] = 'POS offline - transaction queued'
        else:
            result['message'] = result.get('discription', result.get('description', ''))
        
        return result

    # =========================================================================
    # CLOSE SHIFT API
    # =========================================================================

    def pos_send_close_shift(self, staff_id: str, terminal_id: str = None):
        """
        Send close shift notification to POS.
        
        Note: This is typically called FROM POS, so this method is for
        acknowledgment or when Glory initiates shift close.
        """
        config = self._get_pos_config()
        
        payload = {
            "staff_id": staff_id,
        }
        
        if terminal_id:
            payload["terminal_id"] = terminal_id
        
        _logger.info("🔒 Sending CloseShift to POS: staff=%s", staff_id)
        
        if config.get('use_http', True):
            return self._send_http_message('/CloseShift', payload, config)
        else:
            message = json.dumps({
                "command": "CloseShift",
                "data": payload
            }, ensure_ascii=False)
            return self._send_tcp_message(message, config)

    # =========================================================================
    # HEARTBEAT API
    # =========================================================================

    def pos_send_heartbeat(self, terminal_id: str = None):
        """
        Send heartbeat to POS to check connectivity.
        """
        config = self._get_pos_config()
        
        payload = {
            "source_system": "Glory",
            "pos_terminal_id": terminal_id or "TERM-01",
            "status": "OK",
            "timestamp": datetime.now().isoformat(),
        }
        
        _logger.info("💓 Sending HeartBeat to POS")
        
        if config.get('use_http', True):
            return self._send_http_message('/HeartBeat', payload, config)
        else:
            message = json.dumps({
                "command": "HeartBeat",
                "data": payload
            }, ensure_ascii=False)
            return self._send_tcp_message(message, config)

    # =========================================================================
    # OFFLINE QUEUE
    # =========================================================================

    def _create_offline_job(self, job_type: str, payload: dict):
        """
        Create a queued job for when POS is offline.
        
        Args:
            job_type: Type of job (deposit, close_shift, etc.)
            payload: Data to send when POS is back online
            
        Returns:
            pos.tcp.job record or None
        """
        try:
            Job = self.env['pos.tcp.job'].sudo()
            
            job = Job.create({
                'name': f"{job_type.upper()}-{payload.get('transaction_id', datetime.now().strftime('%Y%m%d%H%M%S'))}",
                'job_type': job_type,
                'payload': json.dumps(payload, ensure_ascii=False),
                'status': 'pending',
                'retry_count': 0,
                'created_at': fields.Datetime.now(),
            })
            
            _logger.info("📝 Created offline job: %s (ID: %s)", job.name, job.id)
            return job
            
        except Exception as e:
            _logger.error("❌ Failed to create offline job: %s", e)
            return None

    def pos_process_pending_jobs(self, limit: int = 100):
        """
        Process pending jobs from the offline queue.
        
        This should be called by a cron job or manually to retry
        failed/queued transactions.
        """
        try:
            Job = self.env['pos.tcp.job'].sudo()
            
            pending_jobs = Job.search([
                ('status', 'in', ['pending', 'retry']),
                ('retry_count', '<', 5),
            ], limit=limit, order='created_at asc')
            
            _logger.info("📋 Processing %d pending jobs...", len(pending_jobs))
            
            success_count = 0
            fail_count = 0
            
            for job in pending_jobs:
                try:
                    payload = json.loads(job.payload)
                    
                    if job.job_type == 'deposit':
                        result = self.pos_send_deposit(
                            transaction_id=payload.get('transaction_id'),
                            staff_id=payload.get('staff_id'),
                            amount=payload.get('amount', 0),
                            terminal_id=payload.get('terminal_id'),
                        )
                    else:
                        _logger.warning("Unknown job type: %s", job.job_type)
                        continue
                    
                    if result.get('ok'):
                        job.write({
                            'status': 'done',
                            'completed_at': fields.Datetime.now(),
                            'response': json.dumps(result, ensure_ascii=False),
                        })
                        success_count += 1
                    elif not result.get('offline'):
                        # POS is online but rejected - mark as failed
                        job.write({
                            'status': 'failed',
                            'error': result.get('error', 'Unknown error'),
                            'response': json.dumps(result, ensure_ascii=False),
                        })
                        fail_count += 1
                    else:
                        # Still offline - increment retry count
                        job.write({
                            'status': 'retry',
                            'retry_count': job.retry_count + 1,
                            'last_retry_at': fields.Datetime.now(),
                        })
                        
                except Exception as e:
                    _logger.exception("❌ Failed to process job %s: %s", job.id, e)
                    job.write({
                        'status': 'retry',
                        'retry_count': job.retry_count + 1,
                        'error': str(e),
                    })
                    fail_count += 1
            
            _logger.info("✅ Job processing complete: %d success, %d failed", 
                        success_count, fail_count)
            
            return {
                'processed': len(pending_jobs),
                'success': success_count,
                'failed': fail_count,
            }
            
        except Exception as e:
            _logger.exception("❌ Failed to process pending jobs: %s", e)
            return {'error': str(e)}


class PosTcpJob(models.Model):
    """
    Model to store offline POS jobs for retry.
    """
    _name = 'pos.tcp.job'
    _description = 'POS TCP Job Queue'
    _order = 'created_at desc'

    name = fields.Char(string='Reference', required=True, index=True)
    job_type = fields.Selection([
        ('deposit', 'Deposit'),
        ('close_shift', 'Close Shift'),
        ('end_of_day', 'End of Day'),
    ], string='Job Type', required=True, index=True)
    
    payload = fields.Text(string='Payload (JSON)', required=True)
    response = fields.Text(string='Response (JSON)')
    error = fields.Text(string='Error Message')
    
    status = fields.Selection([
        ('pending', 'Pending'),
        ('retry', 'Retry'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='Status', default='pending', index=True)
    
    retry_count = fields.Integer(string='Retry Count', default=0)
    max_retries = fields.Integer(string='Max Retries', default=5)
    
    created_at = fields.Datetime(string='Created At', default=fields.Datetime.now)
    last_retry_at = fields.Datetime(string='Last Retry At')
    completed_at = fields.Datetime(string='Completed At')
    
    # Link to related records
    deposit_id = fields.Many2one('gas.station.cash.deposit', string='Related Deposit')
    audit_id = fields.Many2one('gas.station.cash.audit', string='Related Audit')