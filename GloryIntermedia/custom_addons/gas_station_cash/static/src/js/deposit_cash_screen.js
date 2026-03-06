/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class DepositCashScreen extends Component {
    static template = "gas_station_cash.DepositCashScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        employeeDetails: { type: Object, optional: true },   // { external_id, ... }
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },          // go back home with amount
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.state = useState({
            step: "counting",   // "counting" -> "summary"
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
        });
    }

    // Called by LiveCashInScreen when /cash_in/end is OK
    _onCashInDone(amount) {
        const numericAmount = Number(amount || 0);
        console.log("[DepositCash] cash-in done, amount:", numericAmount);

        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;
        this.state.step = "summary";
    }

    // Called when user cancels from LiveCashInScreen
    _onCancelCounting() {
        console.log("[DepositCash] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

    // Called by CashInMiniSummaryScreen (Done button or auto 5s)
    async _onSummaryDone(amountFromSummary) {
        const amount = Number(
            amountFromSummary ??
            this.state.finalAmount ??
            this.state.liveAmount ??
            0
        );

        console.log("[DepositCash] summary done, final amount:", amount);

        // Send Fuel deposit to POS (deposit_type='oil' -> FlowCo type_id='F')
        const staffId = this.props.employeeDetails?.external_id;
        if (staffId) {
            const txId = `TXN-${Date.now()}`;
            try {
                const posResp = await this.rpc("/gas_station_cash/pos/deposit_http", {
                    transaction_id:       txId,
                    employee_external_id: staffId,
                    amount:               amount,
                    deposit_type:         "oil",  // Fuel -> FlowCo type_id = 'F'
                });
                const ok = String(posResp?.status || "").toLowerCase() === "ok";
                console.log("[DepositCash] POS response:", posResp);
                this.props.onStatusUpdate?.(ok ? "POS: OK" : `POS: ${posResp?.description || "FAILED"}`);
            } catch (e) {
                console.error("[DepositCash] POS send error:", e);
                this.props.onStatusUpdate?.("POS: FAILED (see logs)");
            }
        } else {
            console.warn("[DepositCash] No employeeDetails.external_id — skipping POS call");
        }

        this.props.onDone?.(amount);
    }
}