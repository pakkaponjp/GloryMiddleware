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
        employeeDetails: { type: Object, optional: true },
        onCancel:       { type: Function, optional: true },
        onDone:         { type: Function, optional: true },   // back to home
        onApiError:     { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        // ✅ RPC service (Odoo JSON-RPC). Backend will talk TCP to POS if needed.
        this.rpc = useService("rpc");

        this.state = useState({
            step: "counting",      // 'counting' | 'summary'
            liveAmount: 0,
            finalAmount: 0,
            busy: false,
        });
    }

    _onCashInDone(amount) {
        const amt = Number(amount ?? this.state.liveAmount) || 0;

        // Keep existing behavior first (so summary works immediately)
        this.state.finalAmount = amt;
        this.state.liveAmount = amt;
        this.state.step = "summary";

        // Always POS-related for Oil Deposit menu
        const txId = `TXN-${Date.now()}`;
        const staffId = this.props.employeeDetails?.external_id || "CASHIER-0000";

        // Fire-and-forget audit + POS workflow (server decides + records everything)
        this.props.onStatusUpdate?.("Recording deposit (Oil) ...");
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
                if (!ok) {
                    console.error("[OilDeposit] finalize failed:", resp);
                    this.props.onStatusUpdate?.("Warning: deposit record failed (see logs)." );
                    return;
                }

                // pos_status: ok | queued | na
                const posStatus = resp?.pos_status || "na";
                const depId = resp?.deposit_id;
                if (posStatus === "ok") {
                    this.props.onStatusUpdate?.(`Recorded + POS OK (deposit_id=${depId}).`);
                } else if (posStatus === "queued") {
                    this.props.onStatusUpdate?.(`Recorded + queued for POS (deposit_id=${depId}).`);
                } else {
                    this.props.onStatusUpdate?.(`Recorded (deposit_id=${depId}).`);
                }
            })
            .catch((err) => {
                console.error("[OilDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Error: cannot record deposit (see logs)." );
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
