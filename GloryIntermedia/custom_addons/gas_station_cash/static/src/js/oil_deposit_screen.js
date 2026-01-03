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
        const staffId = this.props.employeeDetails?.external_id;
        if (!staffId) {
            this.props.onStatusUpdate?.("Missing staff external_id. Please login again.");
            return;
        }

        // 1) show summary immediately
        this.state.liveAmount = amt;
        this.state.finalAmount = amt;
        this.state.summaryItems = [
            { label: "Deposit Type", value: "Oil Sales" },
            { label: "Amount", value: amt },
        ];
        this.state.step = "summary";

        // 2) finalize first (ensure audit exists)
        Promise.resolve().then(async () => {
            let depositId = null;

            try {
                const resp = await this.rpc("/gas_station_cash/deposit/finalize", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: amt,
                    deposit_type: "oil",
                    product_id: null,
                    is_pos_related: true,
                });

                if (String(resp?.status || "").toLowerCase() !== "ok") {
                    console.error("[OilDeposit] finalize not ok:", resp);
                    this.props.onStatusUpdate?.(resp?.message || "Finalize failed");
                    return;
                }

                depositId = resp.deposit_id;
                this.props.onStatusUpdate?.(`Audit saved (deposit_id=${depositId})`);
            } catch (e) {
                console.error("[OilDeposit] finalize error:", e);
                this.props.onStatusUpdate?.("Audit failed (see logs).");
                return;
            }

            // 3) send to POS over TCP (via Odoo backend endpoint you already made / will make)
            try {
                // Call the RPC endpoint to send data to POS via TCP
                const posResp = await this.rpc("/gas_station_cash/pos/deposit_tcp", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: amt,
                });

                const status = String(posResp?.status || "").toLowerCase();
                const desc = String(posResp?.description || "");

                const isTcpOffline = (status === "error" && desc.startsWith("tcp_error"));

                await this.rpc("/gas_station_cash/deposit/pos_result", {
                    deposit_id: depositId,
                    pos_transaction_id: txId,
                    pos_status: isTcpOffline ? "queued" : (status === "ok" ? "ok" : "failed"),
                    pos_description: posResp?.description || "",
                    pos_time_stamp: posResp?.time_stamp || "",
                    pos_response_json: posResp,
                    pos_error: isTcpOffline ? "" : (posResp?.description || "POS returned not OK"),
                });

                this.props.onStatusUpdate?.(isTcpOffline ? "POS: queued (will retry later)" : "POS: OK");
            } catch (e) {
                console.error("[OilDeposit] POS send error:", e);

                // ถ้า TCP ส่งไม่ได้ => queued ไว้ก่อน (ไว้ retry ทีหลัง)
                await this.rpc("/gas_station_cash/deposit/pos_result", {
                    deposit_id: depositId,
                    pos_transaction_id: txId,
                    pos_status: "queued",
                    pos_error: String(e?.message || e),
                });

                this.props.onStatusUpdate?.("POS: queued (will retry later)");
            }
        });
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
