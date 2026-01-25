/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class CoffeeShopDepositScreen extends Component {
    static template = "gas_station_cash.CoffeeShopDepositScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        employeeDetails: { type: Object, optional: true },
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc"); // 

        this.state = useState({
            step: "counting",
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
            summaryItems: [],
        });
    }

    _onCashInDone(amount) {
        const amt = Number(amount ?? this.state.liveAmount) || 0;
        console.log("[CoffeeShopDeposit] cash-in done, amount:", amt);

        const txId = `TXN-${Date.now()}`;
        const staffExternalId = this.props.employeeDetails?.external_id;

        if (!staffExternalId) {
            console.error("[CoffeeShopDeposit] missing employeeDetails.external_id");
            this.props.onStatusUpdate?.("Missing staff external_id (please login again).");
            // ยังให้ไป summary ได้
        } else {
            Promise.resolve().then(async () => {
                try {
                    const resp = await this.rpc("/gas_station_cash/deposit/finalize", {
                        transaction_id: txId,
                        staff_id: staffExternalId,
                        amount: amt,
                        deposit_type: "coffee_shop",
                        product_id: null,
                        is_pos_related: false,
                    });

                    const ok = String(resp?.status || "").toLowerCase() === "ok";
                    if (!ok) {
                        console.error("[CoffeeShopDeposit] finalize not ok:", resp);
                        this.props.onStatusUpdate?.(resp?.message || "Audit failed (finalize not ok).");
                        return;
                    }

                    this.props.onStatusUpdate?.(`Audit saved (deposit_id=${resp.deposit_id})`);
                } catch (err) {
                    console.error("[CoffeeShopDeposit] finalize error:", err);
                    this.props.onStatusUpdate?.("Audit failed (see logs).");
                }
            });
        }

        // summary
        this.state.liveAmount = amt;
        this.state.finalAmount = amt;
        this.state.summaryItems = [
            { label: "Deposit Type", value: "Coffee Shop Sales" },
            { label: "Amount", value: amt },
        ];
        this.state.step = "summary";
    }

    _onCancelCounting() {
        this.props.onCancel?.();
    }

    _onSummaryDone(amountFromSummary) {
        const validAmount = (amountFromSummary && typeof amountFromSummary !== "object") ? amountFromSummary : null;
        const amount = Number(validAmount ?? this.state.finalAmount ?? 0);
        this.props.onDone?.(amount);
    }
}
