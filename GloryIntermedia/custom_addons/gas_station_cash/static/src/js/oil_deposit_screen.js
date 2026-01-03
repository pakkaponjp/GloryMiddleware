/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class OilDepositScreen extends Component {
    static template = "gas_station_cash.OilDepositScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        employeeDetails: { type: Object, optional: true }, // ✅ optional, won't break callers
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },   // back to home
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc"); // ✅ add rpc service

        this.state = useState({
            step: "counting",      // 'counting' | 'summary'
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
        });
    }

    _onCashInDone(amount) {
        const amt = Number(amount ?? this.state.liveAmount) || 0;

        // keep existing behavior first (so summary works immediately)
        this.state.finalAmount = amt;
        this.state.liveAmount = amt;
        this.state.step = "summary";

        // always send to POS for this menu
        const txId = `TXN-${Date.now()}`;
        const staffId = this.props.employeeDetails?.external_id || "CASHIER-0000";

        this.rpc("/gas_station_cash/deposit/finalize", {
            transaction_id: txId,
            staff_id: staffId,
            amount: amt,
            deposit_type: "oil",
            product_id: null,
            is_pos_related: true,
        })
            .then((resp) => {
                const ok = String(resp?.status || "").toLowerCase() === "ok";
                if (!ok) throw new Error(resp?.message || "Finalize failed");
                this.props.onStatusUpdate?.(`Audit saved (deposit_id=${resp.deposit_id})`);
            })
            .catch((err) => {
                console.error("[OilDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Audit failed (see logs).");
            });
    }

    _cancelCounting() {
        this.props.onCancel?.();
    }

    _onSummaryDone(amount) {
        const amt = Number(amount ?? this.state.finalAmount ?? this.state.liveAmount) || 0;
        this.props.onDone?.(amt);
    }
}
