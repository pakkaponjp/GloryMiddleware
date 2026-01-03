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
            summaryItems: [],
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
        const amt = Number(amount ?? this.state.liveAmount) || 0;

        console.log("[RentalDeposit] cash-in done, amount:", amt);

        const txId = `TXN-${Date.now()}`;
        const staffId = this.props.employeeDetails?.external_id || "CASHIER-0000";

        // --- finalize deposit in background ---
        Promise.resolve().then(async () => {
            try {
                const resp = await this.rpc("/gas_station_cash/deposit/finalize", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: amt,
                    deposit_type: "rental",
                    product_id: null,
                    is_pos_related: false, // always false for rental deposit
                });

                const ok = String(resp?.status || "").toLowerCase() === "ok";
                if (!ok) {
                    console.error("[RentalDeposit] finalize not ok:", resp);
                    this.props.onStatusUpdate?.(resp?.message || "Audit failed (finalize not ok).");
                    return;
                }

                this.props.onStatusUpdate?.(`Audit saved (deposit_id=${resp.deposit_id})`);
            } catch (err) {
                console.error("[RentalDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Audit failed (see logs).");
            }
        });

        // --- update state to show summary ---
        this.state.liveAmount = amt;
        this.state.finalAmount = amt;

        this.state.summaryItems = [
            { label: "Deposit Type", value: "Coffee Sales" },
            { label: "Amount", value: amt },
        ];

        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[RentalDeposit] cancel from LiveCashInScreen");
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

        console.log("[RentalDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
