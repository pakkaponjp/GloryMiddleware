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

        # For now: only active & POS-related
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

    @http.route(
        "/gas_station_cash/rentals",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def gas_station_cash_rentals(self, staff_external_id=None, **kwargs):
        """
        Return rental spaces:

        - If staff role == 'tenant'  -> only rentals with tenant_staff_id = that staff
        - Else (manager/supervisor/…) -> rentals that are assigned to some tenant
          (tenant_staff_id != False)
        """
        env = request.env

        _logger.info(
            "[/rentals] called with staff_external_id=%s, kwargs=%s",
            staff_external_id,
            kwargs,
        )

        domain = [("active", "=", True)]
        staff = None

        if staff_external_id:
            staff = (
                env["gas.station.staff"]
                .sudo()
                .search([("external_id", "=", staff_external_id)], limit=1)
            )
            _logger.info(
                "[/rentals] staff_external_id=%s -> staff=%s (role=%s)",
                staff_external_id,
                staff.id if staff else None,
                staff.role if staff else None,
            )

        if staff and staff.role == "tenant":
            # Tenant: see only own rental spaces
            domain.append(("tenant_staff_id", "=", staff.id))
        else:
            # Non-tenant: see only rentals assigned to some tenant
            domain.append(("tenant_staff_id", "!=", False))

        rentals = (
            env["gas.station.cash.rental"]
            .sudo()
            .search(domain, order="sequence, name")
        )

        _logger.info(
            "[/rentals] domain=%s -> found %s rentals",
            domain,
            len(rentals),
        )

        result = {
            "rentals": [
                {
                    "id": r.id,
                    "name": r.name,
                    "code": r.code,
                    "price": r.price,
                    "tenant_staff_id": r.tenant_staff_id.id or False,
                }
                for r in rentals
            ]
        }
        _logger.info("[/rentals] response: %s", result)
        return result
    
    @http.route(
        "/gas_station_cash/pos/deposit_stub",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def pos_deposit_stub(self, **payload):
        """
        Stub endpoint for POS deposit pre-request.

        For now, we only log the payload and return a fake success.
        Later this will send the JSON to POS over TCP.
        """
        _logger.info("[POS STUB] /pos/deposit_stub payload: %s", payload)
        return {
            "status": "stub_ok",
            "description": "Recorded stub for POS deposit",
            "echo": payload,
        }

    # @http.route(
    #     "/gas_station_cash/pos/deposit_stub",
    #     type="json",
    #     auth="user",
    #     methods=["POST"],
    #     csrf=False,
    # )
    # def pos_deposit_stub(self, **kwargs):
    #     """
    #     Stub endpoint: will eventually send deposit transaction to POS over TCP.

    #     Expected payload from frontend:
    #     {
    #         "transaction_id": "TXN-20250926-12345",   # optional for now
    #         "staff_external_id": "CASHIER-0007",
    #         "amount": 400.0,
    #         "product_code": "eo001",
    #         "deposit_type": "engine_oil"
    #     }

    #     For now we:
    #     - log the payload
    #     - (optionally) mark in DB that POS request would be sent
    #     - return status 'ok'
    #     """
    #     payload = request.jsonrequest or {}

    #     tx_id = payload.get("transaction_id")
    #     staff_ext_id = payload.get("staff_external_id")
    #     amount = payload.get("amount")
    #     product_code = payload.get("product_code")
    #     deposit_type = payload.get("deposit_type")

    #     _logger.info(
    #         "[POS STUB] Deposit request received. tx=%s staff=%s product=%s "
    #         "amount=%s type=%s payload=%s",
    #         tx_id, staff_ext_id, product_code, amount, deposit_type, payload,
    #     )

    #     # Need to update a deposit record to mark POS-request success
    #     # but we keep it minimal for now. Example (uncomment later if needed):
    #     #
    #     # if tx_id:
    #     #     deposit = request.env["gas.station.cash.deposit"].sudo().search(
    #     #         [("name", "=", tx_id)], limit=1
    #     #     )
    #     #     if deposit:
    #     #         deposit.pos_request_state = "success"

    #     # ⬇⬇ Future real TCP/HTTP call to POS (commented out for now) ⬇⬇
    #     # import socket, json
    #     # try:
    #     #     message = json.dumps({
    #     #         "transaction_id": tx_id,
    #     #         "staff_id": staff_ext_id,
    #     #         "amount": amount,
    #     #         "product_code": product_code,
    #     #         "deposit_type": deposit_type,
    #     #     })
    #     #     with socket.create_connection(("POS_HOST", POS_PORT), timeout=5) as sock:
    #     #         sock.sendall(message.encode("utf-8"))
    #     #         response_raw = sock.recv(4096)
    #     #         pos_response = json.loads(response_raw.decode("utf-8"))
    #     #         _logger.info("[POS STUB] Real POS response: %s", pos_response)
    #     # except Exception as e:
    #     #     _logger.exception("[POS STUB] Error sending to POS: %s", e)

    #     # Simple stub response for now
    #     return {
    #         "status": "ok",
    #         "message": "POS deposit request stubbed (no real POS call yet)",
    #         "transaction_id": tx_id,
    #     }