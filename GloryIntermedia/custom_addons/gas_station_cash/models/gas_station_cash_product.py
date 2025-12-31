from odoo import models, fields


class GasStationCashProduct(models.Model):
    _name = "gas.station.cash.product"
    _description = "Gas Station Product for Cash Frontend"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)

    name = fields.Char(
        string="Name",
        required=True,
    )
    code = fields.Char(
        string="Code",
        help="Short internal code or SKU for this product.",
    )

    category = fields.Selection(
        [
            ("goods", "Goods"),
            ("rental", "Rental Space"),
        ],
        string="Category",
        required=True,
        default="goods",
        help=(
            "Goods are used for Engine Oil / Convenience items.\n"
            "Rental Space is used for rental deposits."
        ),
    )

    price = fields.Monetary(
        string="Price",
        currency_field="currency_id",
        required=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    is_pos_related = fields.Boolean(
        string="POS Related",
        default=False,
        help=(
            "If checked, deposits with this product will be counted in "
            "POS-related totals for Close Shift / End of Day."
        ),
    )

    active = fields.Boolean(
        default=True,
        help="Uncheck to archive this product from the Cash frontend.",
    )

    _sql_constraints = [
        (
            "gas_station_cash_product_code_uniq",
            "unique(code)",
            "The product code must be unique.",
        ),
    ]
