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

        // Print receipt — non-critical
        const txId = `RPL-${Date.now()}`;
        this.rpc("/gas_station_cash/print/replenish", {
            reference:    txId,
            staff_name:   this.props.employeeDetails?.name || this.props.employeeDetails?.external_id || "",
            total_satang: Math.round(numericAmount * 100),
            breakdown:    breakdown || {},
            datetime_str: new Date().toLocaleString("th-TH", {
                day: "2-digit", month: "2-digit", year: "numeric",
                hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
            }),
        }).catch(e => console.warn("[DepositCash] Print failed:", e));
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
        // ⚠️  breakdown ต้องเป็น deposited denominations เท่านั้น (ไม่ใช่ machine total stock)
        // ถ้า LiveCashInScreen ส่ง Glory /status inventory มา → ค่า float ใน Settings จะผิด
        try {
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

            const notes = breakdown?.notes || [];
            const coins = breakdown?.coins || [];

            // Guard: ถ้า breakdown ว่างเปล่า → LiveCashInScreen ยังไม่ได้ส่ง deposited breakdown
            // ห้ามบันทึก denomination เพราะจะทำให้ Settings ผิด
            if (!notes.length && !coins.length) {
                console.warn(
                    "[DepositCash] _setFloatReplenished: breakdown is empty — " +
                    "LiveCashInScreen has not passed deposited denominations. " +
                    "Float denomination will NOT be updated."
                );
                return;
            }

            // สะสม qty ทีละ item (ใช้ += ป้องกัน overwrite ถ้า fv ซ้ำกัน)
            const denomination = {};
            let depositedTotalSatang = 0;

            for (const item of [...notes, ...coins]) {
                const fv  = Number(item.value || 0);
                const qty = Number(item.qty   || 0);
                if (qty <= 0) continue;
                const key = FV_TO_KEY[fv];
                if (key) {
                    denomination[key] = (denomination[key] || 0) + qty;
                    depositedTotalSatang += fv * qty;
                } else {
                    console.warn("[DepositCash] set_replenished: unknown fv=%d satang — skipped", fv);
                }
            }

            const depositedTHB = depositedTotalSatang / 100;
            console.log(
                "[DepositCash] set_replenished — deposited ฿%s denomination=%o",
                depositedTHB.toLocaleString(), denomination
            );

            const result = await this.rpc("/gas_station_cash/float/set_replenished", {
                breakdown:    { notes, coins },
                denomination,
                deposited_thb: depositedTHB,   // backend ใช้ log เปรียบเทียบเท่านั้น
            });
            console.log("[DepositCash] float replenished set result:", result);

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