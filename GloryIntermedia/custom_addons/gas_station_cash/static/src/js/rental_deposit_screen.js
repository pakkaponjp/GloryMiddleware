/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class RentalDepositScreen extends Component {
    static template = "gas_station_cash.RentalDepositScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        employeeDetails: { type: Object, optional: true },
        onCancel:       { type: Function, optional: true },
        onDone:         { type: Function, optional: true },
        onApiError:     { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.state = useState({
            step: "loading",          // 'loading' | 'select_rental' | 'counting' | 'summary'
            rentals: [],
            selectedRental: null,
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
        });

        onWillStart(async () => {
            try {
                const staff = this.props.employeeDetails || {};
                const payload = {};

                if (staff.external_id) {
                    payload.staff_external_id = staff.external_id;
                }

                const result = await this.rpc("/gas_station_cash/rentals", payload);
                const rentals = result?.rentals || [];

                console.log("[RentalDeposit] rentals loaded:", rentals);
                this.state.rentals = rentals;

                if (rentals.length === 1) {
                    this.state.selectedRental = rentals[0];
                    this.state.step = "counting";
                    this.props.onStatusUpdate?.(
                        `Rental space: ${rentals[0].name}`
                    );
                } else {
                    this.state.step = "select_rental";
                }
            } catch (error) {
                console.error("[RentalDeposit] error loading rentals:", error);
                this.props.onApiError?.("Failed to load rental spaces.");
                this.state.step = "select_rental";
            }
        });
    }

    _onSelectRental(rental) {
        this.state.selectedRental = rental;
        this.state.step = "counting";
        this.props.onStatusUpdate?.(
            `Selected rental: ${rental.name || ""}`
        );
    }

    _cancelAll() {
        this.props.onCancel?.();
    }

    _onCashInDone(amount) {
        const numericAmount = Number(amount ?? this.state.liveAmount) || 0;
        console.log("[RentalDeposit] cash-in done, amount:", numericAmount);
        this.state.finalAmount = numericAmount;
        this.state.liveAmount = numericAmount;
        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[RentalDeposit] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

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
