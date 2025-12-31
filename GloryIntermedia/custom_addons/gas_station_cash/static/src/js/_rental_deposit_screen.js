/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class RentalDepositScreen extends Component {
    static template = "gas_station_cash.RentalDepositScreen";

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

    // Called by LiveCashInScreen when /cash_in/end OK
    _onCashInDone(amount) {
        const numericAmount = Number(amount || 0);
        console.log("[RentalDeposit] cash-in done, amount:", numericAmount);

        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;
        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[RentalDeposit] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

    // Called by CashInMiniSummaryScreen (Done button or auto 5s)
    _onSummaryDone(amountFromSummary) {
        const amount = Number(
            amountFromSummary ??
            this.state.finalAmount ??
            this.state.liveAmount ??
            0
        );

        console.log("[RentalDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
