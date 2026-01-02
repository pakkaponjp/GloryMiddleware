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
        onCancel:       { type: Function, optional: true },
        onDone:         { type: Function, optional: true },   // back to home
        onApiError:     { type: Function, optional: true },
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

        this.props.onStatusUpdate?.("Sending deposit to POS...");

        this.rpc("/gas_station_cash/pos/deposit_http", {
            transaction_id: txId,
            staff_id: staffId,
            amount: amt,
        })
            .then((resp) => {
                const status = String(resp?.status || "").toUpperCase();
                const ok = status === "OK";

                if (ok) {
                    this.props.onStatusUpdate?.("POS OK. Proceeding to audit...");
                    return this.rpc("/gas_station_cash/pos/deposit_success", {
                        transaction_id: txId,
                        staff_id: staffId,
                        amount: amt,
                        pos_response: resp,
                        deposit_type: "oil",
                        product_id: null,
                    });
                } else {
                    this.props.onStatusUpdate?.("POS not OK. Queuing retry job...");
                    return this.rpc("/gas_station_cash/pos/deposit_enqueue", {
                        transaction_id: txId,
                        staff_id: staffId,
                        amount: amt,
                        pos_response: resp,
                        reason: resp?.description || resp?.discription || "POS returned non-OK",
                        deposit_type: "oil",
                        product_id: null,
                    });
                }
            })
            .catch((err) => {
                console.error("[OilDeposit] POS error:", err);
                this.props.onStatusUpdate?.("POS call failed. Queuing retry job...");

                // Network/timeout: enqueue job as well
                return this.rpc("/gas_station_cash/pos/deposit_enqueue", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: amt,
                    pos_response: null,
                    reason: String(err?.message || err),
                    deposit_type: "oil",
                    product_id: null,
                }).catch((e2) => console.error("[OilDeposit] enqueue failed:", e2));
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
