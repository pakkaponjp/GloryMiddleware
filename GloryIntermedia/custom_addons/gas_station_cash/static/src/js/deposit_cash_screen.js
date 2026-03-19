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
    // breakdown = { notes: [{value, qty},...], coins: [{value, qty},...] }
    _onCashInDone(amount, breakdown) {
        const numericAmount = Number(amount || 0);
        console.log("[DepositCash] cash-in done, amount:", numericAmount, "breakdown:", breakdown);

        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;
        this.state.step = "summary";

        // Notify Odoo: replenishment done → enable Leave Float + save denomination
        this._setFloatReplenished(breakdown);
    }

    /**
     * Notify Odoo that replenishment is complete.
     * Converts breakdown { notes: [{value, qty}], coins: [{value, qty}] }
     * into denomination map and saves to ir.config_parameter via Odoo route.
     *
     * breakdown.notes/coins values are in satang:
     *   fv=5000  → ฿50
     *   fv=2000  → ฿20
     *   fv=1000  → ฿10 coin
     *   etc.
     */
    async _setFloatReplenished(breakdown) {
        try {
            // Convert breakdown notes/coins → denomination map
            // Key mapping: satang fv → denomination key
            const FV_TO_KEY = {
                100000: "note_1000",
                50000:  "note_500",
                10000:  "note_100",
                5000:   "note_50",
                2000:   "note_20",
                1000:   "coin_10",
                500:    "coin_5",
                200:    "coin_2",
                100:    "coin_1",
                50:     "coin_050",
                25:     "coin_025",
            };

            const denomination = {};
            const notes = breakdown?.notes || [];
            const coins = breakdown?.coins || [];

            for (const item of [...notes, ...coins]) {
                const fv  = Number(item.value || 0);
                const qty = Number(item.qty   || 0);
                const key = FV_TO_KEY[fv];
                if (key && qty > 0) {
                    denomination[key] = qty;
                }
            }

            console.log("[DepositCash] set_replenished denomination:", denomination);

            const result = await this.rpc("/gas_station_cash/float/set_replenished", {
                breakdown: { notes, coins },
                denomination,
            });
            console.log("[DepositCash] float replenished set:", result);
        } catch (e) {
            console.warn("[DepositCash] float replenished set failed (non-critical):", e);
        }
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

        // Replenishment is cash loaded INTO the machine — NOT a POS transaction.
        // Do NOT send to POS.

        this.props.onDone?.(amount);
    }
}