# -*- coding: utf-8 -*-
import json
from odoo import http
from odoo.http import request

class GasStationCashPOSStatusController(http.Controller):

    @http.route("/gas_station_cash/deposit/pos_result", type="json", auth="user", methods=["POST"])
    def deposit_pos_result(self, **params):
        """
        Update POS status fields on an existing deposit audit record.
        Expected params:
          - deposit_id (int)
          - pos_status: 'ok' | 'queued' | 'failed' | 'na'
          - pos_description (str)
          - pos_time_stamp (str)
          - pos_response_json (dict/str)
          - pos_error (str)
          - pos_transaction_id (str)
        """
        deposit_id = params.get("deposit_id")
        if not deposit_id:
            return {"status": "error", "code": "MISSING_DEPOSIT_ID", "message": "deposit_id is required"}

        dep = request.env["gas.station.cash.deposit"].sudo().browse(int(deposit_id))
        if not dep.exists():
            return {"status": "error", "code": "DEPOSIT_NOT_FOUND", "message": f"deposit_id={deposit_id} not found"}

        vals = {}
        # only write fields if provided (avoid overwriting good data with null)
        for k in ["pos_status", "pos_description", "pos_time_stamp", "pos_error", "pos_transaction_id"]:
            if params.get(k) is not None:
                vals[k] = params.get(k)

        if params.get("pos_response_json") is not None:
            prj = params.get("pos_response_json")
            vals["pos_response_json"] = prj if isinstance(prj, str) else json.dumps(prj, ensure_ascii=False)

        if vals:
            dep.write(vals)

        return {"status": "ok", "deposit_id": dep.id, "pos_status": dep.pos_status}
