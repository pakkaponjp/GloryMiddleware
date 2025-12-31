from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class GasStationProduct(http.Controller):

    @http.route(
        "/gas_station_cash/products",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def gas_products_list(self, **kwargs):
        """
        Return list of active POS-related gas station products
        for the frontend (used by Engine Oil Deposit, etc).

        Request:  {}
        Response: { "products": [ {id, name, code, price, is_pos_related}, ... ] }
        """
        env = request.env
        Product = env["gas.station.cash.product"].sudo()

        # only active
        domain = [
            ("active", "=", True),
        ]

        products = Product.search(domain, order="sequence, name")

        data = [
            {
                "id": p.id,
                "name": p.name,
                "code": p.code,
                "price": p.price,
                "is_pos_related": bool(p.is_pos_related),
                "active": bool(p.active),
            }
            for p in products
        ]
        _logger.info("GasStationProduct: returning %s products", len(data))
        return {"products": data}

    @http.route(
        "/gas_station_cash/products/update",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def gas_products_update(self, **kwargs):
        payload = request.jsonrequest or {}
        product_id = payload.get("id")
        if not product_id:
            return {"status": "error", "message": "Missing product id"}

        Product = request.env["gas.station.cash.product"].sudo()
        prod = Product.search([("id", "=", product_id)], limit=1)
        if not prod:
            return {"status": "error", "message": f"Product {product_id} not found"}

        vals = {}
        if "price" in payload:
            vals["price"] = payload["price"]
        if "is_pos_related" in payload:
            vals["is_pos_related"] = bool(payload["is_pos_related"])

        if vals:
            prod.write(vals)
            _logger.info("Frontend updated product %s with %s", prod.id, vals)

        return {"status": "ok"}
