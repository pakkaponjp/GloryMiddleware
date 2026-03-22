# -*- coding: utf-8 -*-

import requests
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import config as odoo_config

_logger = logging.getLogger(__name__)


class FingerprintEnrollWizard(models.TransientModel):
    """
    Fingerprint Enrollment Wizard.

    Auto-captures on open — no manual trigger button required.
    When the wizard is opened, create() immediately calls the fingerprint
    service and transitions to either 'confirm' (success) or 'error' (failure).

    Flow:
        Open wizard
            -> _do_capture() called automatically via create()
            -> success : step = 'confirm'  -> user clicks Save Fingerprint
            -> failure : step = 'error'    -> user clicks Try Again -> _do_capture() again
    """

    _name = 'fingerprint.enroll.wizard'
    _description = 'Fingerprint Enrollment Wizard'

    # ── Fields ─────────────────────────────────────────────────

    staff_id = fields.Many2one(
        'gas.station.staff',
        string='Staff Member',
        required=True,
        readonly=True,
    )

    step = fields.Selection([
        ('confirm', 'Confirm and Save'),
        ('error',   'Error'),
    ], default='error', required=True)

    template_b64   = fields.Text(string='Captured Template', readonly=True)
    template_size  = fields.Integer(string='Template Size', readonly=True)
    status_message = fields.Char(string='Status', readonly=True)
    error_message  = fields.Text(string='Error Detail', readonly=True)

    staff_name  = fields.Char(related='staff_id.name', readonly=True)
    is_reenroll = fields.Boolean(
        string='Re-enrollment',
        help='True when replacing an existing fingerprint.',
    )

    # ── Auto-capture on wizard open ────────────────────────────

    @api.model
    def create(self, vals):
        """
        Override create() to trigger fingerprint capture immediately
        when the wizard record is created (i.e. when the dialog opens).
        """
        wizard = super().create(vals)
        wizard._do_capture()
        return wizard

    # ── User-triggered actions ─────────────────────────────────

    def action_save(self):
        """
        Save the captured fingerprint template to the staff record.
        Called when user clicks 'Save Fingerprint' on the confirm step.
        """
        self.ensure_one()

        if not self.template_b64:
            raise UserError(_("No fingerprint template to save. Please try again."))

        from odoo.fields import Datetime
        self.staff_id.sudo().write({
            'fingerprint_template_b64': self.template_b64,
            'fingerprint_enrolled_at':  Datetime.now(),
        })

        _logger.info(
            "FP Enroll: saved fingerprint for staff '%s' (id=%s)",
            self.staff_id.name, self.staff_id.id,
        )

        return {
            'type': 'ir.actions.client',
            'tag':  'display_notification',
            'params': {
                'title':   _("Fingerprint Enrolled"),
                'message': _("Fingerprint for %s saved successfully.") % self.staff_id.name,
                'type':    'success',
                'sticky':  False,
                'next':    {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_retry(self):
        """
        Reset wizard state and re-attempt fingerprint capture.
        Called when user clicks 'Try Again' (error step) or 'Scan Again' (confirm step).
        """
        self.ensure_one()

        # Clear previous capture result before retrying
        self.write({
            'step':           'error',
            'template_b64':   False,
            'template_size':  0,
            'status_message': False,
            'error_message':  False,
        })

        self._do_capture()
        return self._reopen()

    # ── Private helpers ────────────────────────────────────────

    def _get_fp_api_base(self):
        """
        Build base URL for fingerprint enroll API from odoo.conf.
    
        Keys read from odoo.conf:
            ip_fingerprint_enroll_api_host  (default: 127.0.0.1)
            port_fingerprint_enroll_api     (default: 5005)
        """
        host = odoo_config.get('ip_fingerprint_enroll_api_host', '127.0.0.1')
        port = odoo_config.get('port_fingerprint_enroll_api', '5005')
        return f"http://{host}:{port}"
    
    def _get_fp_timeout(self):
        """
        Return the HTTP request timeout for capture calls (in seconds).
    
        Key read from odoo.conf:
            timeout_fingerprint_enroll_api  (default: 3)
        """
        return int(odoo_config.get('timeout_fingerprint_enroll_api', 3))

    def _do_capture(self):
        """
        Call the fingerprint service to capture a template from the scanner.
        Updates self (step, template_b64, status_message / error_message) in-place.

        Steps:
            1. Reachability check  — GET /health (3s timeout)
            2. Capture request     — POST /api/v1/fingerprint/capture
            3. Write result to wizard record
        """
        FP_URL     = self._get_fp_url()
        FP_TIMEOUT = self._get_fp_timeout()

        # Step 1: Quick reachability check before attempting capture
        try:
            requests.get(f"{FP_URL}/health", timeout=3)
        except requests.exceptions.ConnectionError:
            self.write({
                'step': 'error',
                'error_message': (
                    f"Fingerprint service is not reachable at {FP_URL}.\n"
                    "Please make sure app_production.py is running on the configured port."
                ),
            })
            return
        except Exception:
            # Any other exception (e.g. 404 Not Found) means the service is up
            pass

        # Step 2: Send capture request to fingerprint service
        try:
            _logger.info(
                "FP Enroll: sending capture request for staff '%s'",
                self.staff_id.name,
            )
            resp = requests.post(
                f"{FP_URL}/api/v1/fingerprint/capture",
                json={"employee_id": self.staff_id.employee_id},
                timeout=FP_TIMEOUT,
            )
            data = resp.json()

        except requests.exceptions.Timeout:
            self.write({
                'step': 'error',
                'error_message': (
                    "Scanner timed out — no finger detected within 20 seconds.\n"
                    "Place your finger firmly on the sensor and try again."
                ),
            })
            return
        except Exception as e:
            self.write({
                'step':          'error',
                'error_message': f"Unexpected error contacting fingerprint service: {e}",
            })
            return

        # Step 3: Handle response
        if data.get("status") != "OK":
            self.write({
                'step':          'error',
                'error_message': data.get("message", "Unknown error from fingerprint service."),
            })
            return

        # Capture succeeded — advance to confirm step
        size = data.get("template_size", 0)
        self.write({
            'step':           'confirm',
            'template_b64':   data['template_b64'],
            'template_size':  size,
            'status_message': f"Fingerprint captured successfully ({size} bytes).",
            'error_message':  False,
        })

        _logger.info(
            "FP Enroll: capture successful for staff '%s', template_size=%s",
            self.staff_id.name, size,
        )

    def _reopen(self):
        """Return an action that reopens this wizard dialog to reflect updated state."""
        return {
            'type':      'ir.actions.act_window',
            'res_model': self._name,
            'res_id':    self.id,
            'view_mode': 'form',
            'target':    'new',
            'context':   self.env.context,
        }