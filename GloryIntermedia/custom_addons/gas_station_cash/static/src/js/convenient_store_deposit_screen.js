/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class ConvenientStoreDepositScreen extends Component {
    static template = "gas_station_cash.ConvenientStoreDepositScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },            // go back home with amount
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            step: "counting",   // "counting" -> "summary"
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
        });
    }

    // Called when LiveCashInScreen finishes cash-in (End OK)
    _onCashInDone(amount) {
        const numericAmount = Number(amount || 0);
        console.log("[ConvenientStoreDeposit] cash-in done, amount:", numericAmount);

        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;
        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[ConvenientStoreDeposit] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

    // Called when the summary screen auto-returns / Done is clicked
    _onSummaryDone(amountFromSummary) {
        const amount = Number(
            amountFromSummary ??
            this.state.finalAmount ??
            this.state.liveAmount ??
            0
        );

        console.log("[ConvenientStoreDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
