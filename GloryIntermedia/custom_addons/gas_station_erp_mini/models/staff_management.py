# -*- coding: utf-8 -*-

import hashlib
import hmac
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class GasStationStaff(models.Model):
    _name = 'gas.station.staff'
    _description = 'Gas Station Staff'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _sql_constraints = [
        ('employee_id_unique', 'UNIQUE(employee_id)', 'Employee ID must be unique.'),
    ]

    first_name = fields.Char(string='First Name', required=True, tracking=True)
    last_name = fields.Char(string='Last Name', required=True, tracking=True)
    nickname = fields.Char(string='Nickname')
    address1 = fields.Text(string='Address1')
    address2 = fields.Text(string='Address2')
    phone = fields.Char(string='Telephone Number')

    name = fields.Char(
        string='Staff Name',
        compute='_compute_full_name',
        store=True,
        tracking=True,
    )

    employee_id = fields.Char(
        string='Employee ID',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        tracking=True,
    )
    external_id = fields.Char(string='External ID', help='ID used for external systems', tracking=True)

    user_id = fields.Many2one(
        'res.users',
        string='Related Odoo User',
        ondelete='set null',
        help="Odoo user linked to this staff profile. Used for syncing roles and access.",
        tracking=True,
    )

    role = fields.Selection([
        ('ppower', 'P Power'),
        ('owner', 'Owner'),
        ('manager', 'Manager'),
        ('supervisor', 'Supervisor'),
        ('cashier', 'Cashier'),
        ('attendant', 'Attendant'),
        ('coffee_shop_staff', 'Coffee Shop Staff'),
        ('convenient_store_staff', 'Convenient Store Staff'),
        ('tenant', 'Tenant'),
    ], string='Role', default='attendant', required=True, tracking=True)

    # -------------------------
    # PIN
    # -------------------------
    pin_state = fields.Selection([
        ('not_set', 'Not Set'),
        ('set', 'Set'),
    ], string='PIN Status', compute='_compute_auth_status', store=True, tracking=True)

    pin_hash = fields.Char(string='PIN Hash', readonly=True, copy=False)
    pin = fields.Char(
        string='PIN',
        size=4,
        help="4-digit PIN for quick access/authentication.",
        store=False,
        tracking=False,
    )

    # -------------------------
    # Fingerprint
    # -------------------------
    fingerprint_state = fields.Selection([
        ('not_enrolled', 'Not Enrolled'),
        ('enrolled', 'Enrolled'),
    ], string='Fingerprint Status', compute='_compute_auth_status', store=True, tracking=True)

    fingerprint_template_b64 = fields.Text(
        string='Fingerprint Template',
        groups="gas_station_erp_mini.group_gas_station_manager",
        copy=False,
    )
    fingerprint_enrolled_at = fields.Datetime(string='Fingerprint Enrolled At', readonly=True, copy=False)

    # Keep only if you still need legacy/external reference
    fingerprint_id = fields.Char(
        string='Fingerprint ID',
        help="Legacy or external fingerprint reference ID.",
        tracking=True,
    )

    # -------------------------
    # FlowCo POS Integration
    # -------------------------
    tag_id = fields.Char(
        string='RFID Tag ID',
        help='RFID card UID used for FlowCo POS staff identification.',
        tracking=True,
        copy=False,
    )
    pos_id = fields.Char(
        string='POS ID',
        help='POS terminal number this staff is assigned to (e.g. 1, 2).',
        tracking=True,
    )

    active = fields.Boolean(default=True, tracking=True)

    @api.depends('first_name', 'last_name')
    def _compute_full_name(self):
        for record in self:
            record.name = f"{record.first_name or ''} {record.last_name or ''}".strip()

    @api.depends('pin_hash', 'fingerprint_template_b64')
    def _compute_auth_status(self):
        for rec in self:
            rec.pin_state = 'set' if rec.pin_hash else 'not_set'
            rec.fingerprint_state = 'enrolled' if rec.fingerprint_template_b64 else 'not_enrolled'

    def _validate_raw_pin(self, raw_pin):
        if not raw_pin:
            raise ValidationError(_("PIN is required for every staff record."))
        raw_pin = str(raw_pin).strip()
        if not raw_pin.isdigit() or len(raw_pin) != 4:
            raise ValidationError(_("PIN must be exactly 4 digits."))
        return raw_pin

    def _hash_pin(self, raw_pin):
        salt = self.env['ir.config_parameter'].sudo().get_param(
            'gas_station_pin_salt',
            'default_salt'
        )
        return hashlib.sha256((raw_pin + salt).encode()).hexdigest()

    def set_pin(self, raw_pin):
        raw_pin = self._validate_raw_pin(raw_pin)
        hashed = self._hash_pin(raw_pin)
        for rec in self:
            super(GasStationStaff, rec).write({'pin_hash': hashed})
        return True

    def check_pin(self, raw_pin):
        if not raw_pin:
            return False
        hashed = self._hash_pin(str(raw_pin).strip())
        return hmac.compare_digest(hashed, self.pin_hash or "")

    @api.model
    def create(self, vals):
        # Enforce single P Power staff
        if vals.get('role') == 'ppower' and self.search([('role', '=', 'ppower')], limit=1):
            raise ValidationError(_("Only one P Power staff is allowed in the system."))

        emp_id = vals.get('employee_id', '')
        if not emp_id or emp_id in ('New', _('New')):
            # Retry up to 10 times in case sequence is out of sync with DB
            for attempt in range(10):
                candidate = self.env['ir.sequence'].next_by_code('gas.station.staff')
                if not self.search([('employee_id', '=', candidate)], limit=1):
                    vals['employee_id'] = candidate
                    break
            else:
                raise ValidationError(_("Could not generate a unique Employee ID. Please contact the system administrator."))

        raw_pin = vals.pop('pin', None)
        raw_pin = self._validate_raw_pin(raw_pin)

        staff = super().create(vals)
        staff.set_pin(raw_pin)
        return staff

    def write(self, vals):
        # Prevent changing role TO ppower if one already exists (other than self)
        if vals.get('role') == 'ppower':
            existing = self.search([('role', '=', 'ppower'), ('id', 'not in', self.ids)], limit=1)
            if existing:
                raise ValidationError(_("Only one P Power staff is allowed in the system."))

        raw_pin = vals.pop('pin', None)

        res = super().write(vals)

        if raw_pin:
            self.set_pin(raw_pin)

        for rec in self:
            if not rec.pin_hash:
                raise ValidationError(_("PIN is required for every staff record."))

        return res

    def unlink(self):
        if self.filtered(lambda r: r.role == 'ppower'):
            raise ValidationError(_("P Power staff cannot be deleted."))
        return super().unlink()

        if raw_pin:
            self.set_pin(raw_pin)

        for rec in self:
            if not rec.pin_hash:
                raise ValidationError(_("PIN is required for every staff record."))

        return res

    # ---------------------------------------------------------
    # Fingerprint button actions
    # ---------------------------------------------------------

    def _open_enroll_wizard(self, is_reenroll=False):
        """Open the fingerprint enrollment wizard for this staff record."""
        self.ensure_one()
        wizard = self.env["fingerprint.enroll.wizard"].create({
            "staff_id":    self.id,
            "is_reenroll": is_reenroll,
        })
        return {
            "type":      "ir.actions.act_window",
            "name":      _("Re-Enroll Fingerprint") if is_reenroll else _("Enroll Fingerprint"),
            "res_model": "fingerprint.enroll.wizard",
            "res_id":    wizard.id,
            "view_mode": "form",
            "target":    "new",
        }

    def action_enroll_fingerprint(self):
        """Open enrollment wizard (staff has no fingerprint yet)."""
        self.ensure_one()
        return self._open_enroll_wizard(is_reenroll=False)

    def action_reenroll_fingerprint(self):
        """Open enrollment wizard to replace existing fingerprint."""
        self.ensure_one()
        return self._open_enroll_wizard(is_reenroll=True)

    def action_test_verify_fingerprint(self):
        """
        Quick verify test: capture fresh scan and compare against stored template.
        Shows a notification with score and result.
        """
        self.ensure_one()
        import requests as _req
        from odoo.tools import config as odoo_config

        host   = odoo_config.get('ip_fingerprint_enroll_api_host', '127.0.0.1')
        port   = odoo_config.get('port_fingerprint_enroll_api', '5005')
        FP_URL = f"http://{host}:{port}"

        if not self.fingerprint_template_b64:
            raise ValidationError(_("No fingerprint enrolled for this staff member."))

        try:
            resp = _req.post(
                f"{FP_URL}/api/v1/fingerprint/verify_template",
                json={
                    "employee_id":  self.employee_id,
                    "template_b64": self.fingerprint_template_b64,
                },
                timeout=30,
            )
            data = resp.json()
        except _req.exceptions.Timeout:
            raise ValidationError(_("Scanner timed out. Place finger firmly and try again."))
        except _req.exceptions.ConnectionError:
            raise ValidationError(_(
                "Cannot reach fingerprint service at %s.\n"
                "Make sure app_production.py is running."
            ) % FP_URL)

        if data.get("status") == "TIMEOUT":
            raise ValidationError(_("No finger detected within timeout. Please try again."))

        if data.get("status") != "OK":
            raise ValidationError(
                _("Fingerprint service error: %s") % data.get("message", "Unknown error")
            )

        verified  = data.get("verified", False)
        score     = data.get("score", 0)
        threshold = data.get("threshold", 50)

        return {
            "type": "ir.actions.client",
            "tag":  "display_notification",
            "params": {
                "title":   _("Verified") + " ✓" if verified else _("Not Matched") + " ✗",
                "message": _("Score: %(score)s / %(threshold)s — %(result)s") % {
                    "score":     score,
                    "threshold": threshold,
                    "result":    _("MATCH") if verified else _("NO MATCH"),
                },
                "type":   "success" if verified else "warning",
                "sticky": True,
            },
        }

    def action_clear_fingerprint(self):
        """Remove enrolled fingerprint data from this staff record."""
        self.ensure_one()
        self.write({
            "fingerprint_template_b64": False,
            "fingerprint_enrolled_at":  False,
            "fingerprint_id":           False,
        })
        return {
            "type": "ir.actions.client",
            "tag":  "display_notification",
            "params": {
                "title":   _("Fingerprint Removed"),
                "message": _("Fingerprint data for %s has been cleared.") % self.name,
                "type":    "warning",
                "sticky":  False,
            },
        }