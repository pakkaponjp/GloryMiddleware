# -*- coding: utf-8 -*-
# File: custom_addons/gas_station_cash/models/cash_deposit.py
# Description: Models for cash management - audit deposits from Cash Recycler
#              With automatic POS sending and heartbeat monitor integration

from odoo import models, fields, api, _
import json
import socket
import logging

_logger = logging.getLogger(__name__)


class GasStationCashDeposit(models.Model):
    _name = "gas.station.cash.deposit"
    _description = "Gas Station Cash Deposit"
    _order = "date desc, name desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
        tracking=True,
    )

    staff_id = fields.Many2one("gas.station.staff", string="Staff", required=True, tracking=True)
    date = fields.Datetime(string="Date", required=True, default=fields.Datetime.now, tracking=True)

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    deposit_line_ids = fields.One2many(
        "gas.station.cash.deposit.line",
        "deposit_id",
        string="Deposit Lines",
        copy=True,
    )

    total_amount = fields.Monetary(
        string="Total Amount",
        currency_field="currency_id",
        compute="_compute_total_amount",
        store=True,
        tracking=True,
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("audited", "Audited"),
        ],
        string="Status",
        default="draft",
        readonly=True,
        tracking=True,
    )

    # ----- Deposit classification (from Cash Recycler menu buttons) -----
    deposit_type = fields.Selection(
        [
            ("oil", "Oil Sales"),
            ("engine_oil", "Engine Oil Sales"),
            ("rental", "Rental"),
            ("coffee_shop", "Coffee Shop Sales"),
            ("convenient_store", "Convenient Store Sales"),
            ("deposit_cash", "Replenish Cash"),
            ("exchange_cash", "Exchange Notes and Coins"),
        ],
        string="Deposit Type",
        default="oil",
        tracking=True,
        index=True,
    )

    product_id = fields.Many2one(
        "gas.station.cash.product",
        string="Gas Station Product",
        tracking=True,
        index=True,
    )

    is_pos_related = fields.Boolean(
        string="POS Related",
        default=False,
        index=True,
        tracking=True,
        help="If true, this deposit is linked to POS system.",
    )

    # ----- POS integration audit fields -----
    pos_transaction_id = fields.Char(string="POS Transaction ID", index=True, tracking=True)
    pos_status = fields.Selection(
        [
            ("na", "N/A"),
            ("ok", "OK"),
            ("queued", "Queued"),
            ("failed", "Failed"),
        ],
        string="POS Status",
        default="na",
        index=True,
        tracking=True,
    )
    pos_description = fields.Char(string="POS Description")
    pos_time_stamp = fields.Char(string="POS Timestamp")  # keep as string; POS sends ISO
    pos_response_json = fields.Text(string="POS Response JSON")
    pos_error = fields.Text(string="POS Error / Reason")

    # ----- Notes (Editable) -----
    notes = fields.Text(
        string="Notes",
        help="Additional notes - can be edited anytime",
    )

    # ----- Shift Audit Link -----
    audit_id = fields.Many2one(
        'gas.station.shift.audit',
        string='Shift Audit',
        readonly=True,
        index=True,
        help="Link to the shift audit that includes this deposit",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("gas.station.cash.deposit.sequence")
                    or _("New")
                )
        return super().create(vals_list)

    @api.depends("deposit_line_ids.subtotal")
    def _compute_total_amount(self):
        for rec in self:
            rec.total_amount = sum(rec.deposit_line_ids.mapped("subtotal"))

    # =========================================================================
    # POS INTEGRATION HELPERS
    # =========================================================================

    def _is_pos_related(self):
        """
        oil        → ส่ง POS เสมอ
        engine_oil → ส่ง POS เฉพาะถ้า is_pos_related = True (set โดย pos_workflow endpoints)
        อื่นๆ      → ไม่ส่ง POS
        """
        self.ensure_one()

        if self.deposit_type == 'oil':
            return True

        if self.deposit_type == 'engine_oil':
            return bool(self.is_pos_related)

        return False

    def _get_pos_staff_id(self):
        """Get staff ID for POS communication."""
        self.ensure_one()
        if self.staff_id:
            return (
                getattr(self.staff_id, 'external_id', None) or
                getattr(self.staff_id, 'employee_id', None) or
                self.staff_id.name or
                "UNKNOWN"
            )
        return "UNKNOWN"

    def _send_to_pos(self):
        """
        Send this deposit to POS via TCP.

        Returns:
            bool: True if sent successfully, False otherwise
        """
        self.ensure_one()

        if not self._is_pos_related():
            _logger.info("📤 Deposit %s is not POS-related, skipping", self.name)
            self.write({'pos_status': 'na'})
            return True

        transaction_id = self.pos_transaction_id or self.name
        staff_id = self._get_pos_staff_id()
        amount = float(self.total_amount or 0)

        _logger.info("📤 Sending deposit %s to POS (staff=%s, amount=%s)",
                     transaction_id, staff_id, amount)

        # Get POS connection settings
        ICP = self.env['ir.config_parameter'].sudo()
        host = ICP.get_param('pos.tcp.host', 'localhost')
        port = int(ICP.get_param('pos.tcp.port', '9001'))
        timeout = int(ICP.get_param('pos.tcp.timeout', '30'))

        try:
            _logger.info("📡 Connecting to POS at %s:%s...", host, port)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))

            message = json.dumps({
                "transaction_id": transaction_id,
                "staff_id": staff_id,
                "amount": amount,
            }, ensure_ascii=False) + "\n"

            _logger.info("📤 TX: %s", message.strip())
            sock.sendall(message.encode('utf-8'))

            response_data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk
                if b"\n" in response_data:
                    break

            sock.close()

            response_str = response_data.decode('utf-8').strip()
            _logger.info("📥 RX: %s", response_str)

            result = json.loads(response_str)

            if result.get('status') == 'OK':
                self.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'ok',
                    'pos_description': result.get('description', 'Deposit Success'),
                    'pos_time_stamp': result.get('time_stamp', ''),
                    'pos_response_json': json.dumps(result, ensure_ascii=False),
                    'pos_error': False,
                })
                _logger.info("✅ Deposit %s sent successfully", transaction_id)
                return True
            else:
                self.write({
                    'pos_transaction_id': transaction_id,
                    'pos_status': 'failed',
                    'pos_description': result.get('description', ''),
                    'pos_error': result.get('error', 'Unknown error'),
                    'pos_response_json': json.dumps(result, ensure_ascii=False),
                })
                _logger.warning("⚠️ Deposit %s failed: %s", transaction_id, result)
                return False

        except (socket.timeout, ConnectionRefusedError) as e:
            _logger.warning("🚫 POS connection failed for deposit %s: %s", transaction_id, e)
            self.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'queued',
                'pos_error': str(e),
            })
            self._start_heartbeat_monitor()
            return False

        except Exception as e:
            _logger.exception("❌ Failed to send deposit %s: %s", transaction_id, e)
            self.write({
                'pos_transaction_id': transaction_id,
                'pos_status': 'queued',
                'pos_error': str(e),
            })
            self._start_heartbeat_monitor()
            return False

    def _start_heartbeat_monitor(self):
        """Start the heartbeat monitor to check POS connectivity."""
        try:
            from odoo.addons.gas_station_cash.controllers.pos_commands import _heartbeat_monitor
            dbname = self.env.cr.dbname
            uid = self.env.uid
            _logger.info("💓 Starting heartbeat monitor (db=%s, uid=%s)", dbname, uid)
            _heartbeat_monitor.start_monitoring(dbname, uid)
        except Exception as e:
            _logger.exception("💓 Failed to start heartbeat monitor: %s", e)

    # =========================================================================
    # WORKFLOW ACTIONS
    # =========================================================================

    def action_confirm(self):
        """Confirm the deposit and send to POS if applicable."""
        for rec in self:
            rec.state = "confirmed"
            if rec._is_pos_related():
                _logger.info("📤 Deposit %s confirmed, sending to POS...", rec.name)
                rec._send_to_pos()
            else:
                _logger.info("📤 Deposit %s confirmed, not POS-related", rec.name)
                rec.write({'pos_status': 'na'})

    def action_audit(self):
        for rec in self:
            rec.state = "audited"

    def action_draft(self):
        for rec in self:
            rec.state = "draft"

    def action_retry_pos(self):
        """Manual action to retry sending to POS."""
        for rec in self:
            if rec.pos_status in ['queued', 'failed']:
                _logger.info("🔄 Retrying POS send for deposit %s", rec.name)
                rec._send_to_pos()


class GasStationCashDepositLine(models.Model):
    _name = "gas.station.cash.deposit.line"
    _description = "Gas Station Cash Deposit Line"

    deposit_id = fields.Many2one(
        "gas.station.cash.deposit",
        string="Cash Deposit",
        required=True,
        ondelete="cascade",
    )

    currency_id = fields.Many2one("res.currency", related="deposit_id.currency_id", readonly=True)
    company_id = fields.Many2one("res.company", related="deposit_id.company_id", readonly=True)

    currency_denomination = fields.Float(string="Denomination", required=True)
    quantity = fields.Integer(string="Quantity", required=True, default=1)

    subtotal = fields.Monetary(
        string="Subtotal",
        currency_field="currency_id",
        compute="_compute_subtotal",
        store=True,
    )

    @api.depends("currency_denomination", "quantity")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (line.currency_denomination or 0.0) * (line.quantity or 0)