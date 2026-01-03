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
            summaryItems: [],
        });
    }

    _onCashInDone(amount) {
        const amt = Number(amount ?? this.state.liveAmount) || 0;

        console.log("[OilDeposit] cash-in done, amount:", amt);

        const txId = `TXN-${Date.now()}`;
        const staffId = this.props.employeeDetails?.external_id || "CASHIER-0000";

        // --- finalize deposit in background ---
        Promise.resolve().then(async () => {
            try {
                const resp = await this.rpc("/gas_station_cash/deposit/finalize", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: amt,
                    deposit_type: "oil",
                    product_id: null,
                    is_pos_related: true, // always true for oil deposit
                });

                const ok = String(resp?.status || "").toLowerCase() === "ok";
                if (!ok) {
                    console.error("[OilDeposit] finalize not ok:", resp);
                    this.props.onStatusUpdate?.(resp?.message || "Audit failed (finalize not ok).");
                    return;
                }

                this.props.onStatusUpdate?.(`Audit saved (deposit_id=${resp.deposit_id})`);
            } catch (err) {
                console.error("[OilDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Audit failed (see logs).");
            }
        });

        // --- update state to show summary ---
        this.state.liveAmount = amt;
        this.state.finalAmount = amt;

        this.state.summaryItems = [
            { label: "Deposit Type", value: "Oil Sales" },
            { label: "Amount", value: amt },
        ];

        this.state.step = "summary";
    }

    _cancelCounting() {
        this.props.onCancel?.();
    }

    // Called when the summary screen auto-returns / Done is clicked
    _onSummaryDone(amountFromSummary) {
        // Check if the argument is an Event object (it will have a 'target' property)
        const validAmount = (amountFromSummary && typeof amountFromSummary !== 'object')
            ? amountFromSummary
            : null;

        const amount = Number(
            validAmount ??
            this.state.finalAmount ??
            0
        );

        console.log("[OilDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
