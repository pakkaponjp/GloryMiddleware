# gas_station_cash/models/gas_station_payment.py

from odoo import api, fields, models

class GasStationPayment(models.Model):
    _name = "gas.station.payment"
    _inherit = "pos.connector.mixin"   # <— inherit the mixin
    _description = "Gas Station Payment linked to POS"

    # your fields here: amount, staff, etc.

    def action_send_to_pos(self):
        self.ensure_one()
        items = [
            {
                "sku": "ITEM-9876",
                "name": "Fuel",
                "amount": self.amount_fuel,
            },
            {
                "sku": "ITEM-1234",
                "name": "Engine Oil",
                "amount": self.amount_engine_oil,
            },
        ]
        res = self.send_transaction_to_pos(
            transaction_id=self.name,
            staff_id=self.staff_id.external_id or self.staff_id.name,
            items=items,
            totals=self.amount_total,
            payments="CASH",
        )
        # You can store res["queued_job_id"], or show a banner if sent=False
