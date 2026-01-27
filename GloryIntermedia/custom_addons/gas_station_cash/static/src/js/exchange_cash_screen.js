/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { LiveCashInScreen } from "./live_cash_in_screen";

export class ExchangeCashScreen extends Component {
    static template = "gas_station_cash.ExchangeCashScreen";
    
    static components = {
        LiveCashInScreen,
    };

    static props = {
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
        onApiError: { type: Function, optional: true },
        employeeDetails: { type: Object, optional: true },
    };

    setup() {
        this.state = useState({
            step: "counting",               // 'counting' | 'denominations' | 'summary'
            amount: 0,                      // final counted amount after cash-in done
            liveAmount: 0,                  // live amount (passed to LiveCashInScreen)
            denominations: [
                { value: 1000, qty: 0 },
                { value: 500, qty: 0 },
                { value: 100, qty: 0 },
                { value: 50, qty: 0 },
                { value: 20, qty: 0 },
                { value: 10, qty: 0 },
                { value: 5, qty: 0 },
                { value: 2, qty: 0 },
                { value: 1, qty: 0 },
            ],
            busy: false,
            message: null,
        });

        // Bind methods
        this.increment = this.increment.bind(this);
        this.decrement = this.decrement.bind(this);
        this.canAdd = this.canAdd.bind(this);
    }

    // ============================================================================
    // NOTIFICATION HELPERS
    // ============================================================================
    _notify(text, type = "info") {
        this.state.message = { text, type };
        this.props.onStatusUpdate?.(text, type);

        // Auto-clear after 5s
        setTimeout(() => {
            if (this.state.message?.text === text) {
                this.state.message = null;
            }
        }, 5000);
    }

    // ============================================================================
    // STEP 1: LIVE CASH-IN (via LiveCashInScreen component)
    // ============================================================================
    
    /**
     * Called when LiveCashInScreen completes successfully
     */
    _onCashInDone(amount) {
        const amt = Number(amount) || 0;
        console.log("[ExchangeCash] cash-in done, amount:", amt);

        this.state.amount = amt;
        this.state.step = "denominations";
        this._notify(`Cash counted: ฿${amt}`, "success");
    }

    /**
     * Called when user cancels from LiveCashInScreen
     */
    _onCashInCancel() {
        console.log("[ExchangeCash] cash-in cancelled");
        this.props.onCancel?.();
    }

    /**
     * Called when LiveCashInScreen encounters an API error
     */
    _onCashInError(errorMsg) {
        console.error("[ExchangeCash] cash-in error:", errorMsg);
        this._notify(errorMsg, "danger");
        this.props.onApiError?.(errorMsg);
    }

    // ============================================================================
    // STEP 2: DENOMINATION SELECTION
    // ============================================================================
    
    get totalSelected() {
        return this.state.denominations.reduce((sum, d) => sum + d.value * d.qty, 0);
    }

    get amountLeft() {
        return this.state.amount - this.totalSelected;
    }

    canAdd(denom) {
        if (!denom) return false;
        return denom.value <= this.amountLeft;
    }

    increment(denom) {
        if (this.canAdd(denom)) {
            denom.qty += 1;
        }
    }

    decrement(denom) {
        if (denom.qty > 0) {
            denom.qty -= 1;
        }
    }

    /**
     * Execute cash-out dispense
     */
    async onConfirmDenominations() {
        const totalRequested = Number(parseFloat(this.totalSelected).toFixed(2));
        const stateAmount = Number(parseFloat(this.state.amount).toFixed(2));

        if (totalRequested !== stateAmount) {
            this._notify(
                `Mismatch: Entered ฿${totalRequested} ≠ Counted ฿${stateAmount}`,
                "danger"
            );
            return;
        }

        const selected = this.state.denominations.filter(d => d.qty > 0);
        if (!selected.length) {
            this._notify("Please select at least one note/coin to dispense.", "danger");
            return;
        }

        // THB denominations
        const COIN_VALUES = new Set([1, 2, 5, 10]);
        const NOTE_VALUES = new Set([20, 50, 100, 500, 1000]);

        const notes = [];
        const coins = [];
        let intendedTHB = 0;

        for (const d of selected) {
            const thbValue = Number(d.value);
            const qty = Number(d.qty);
            if (!qty || qty <= 0) continue;

            intendedTHB += thbValue * qty;

            // GloryAPI expects fv in satang: 1.00 THB -> 100
            const fvSatang = thbValue * 100;

            if (NOTE_VALUES.has(thbValue)) {
                notes.push({ value: fvSatang, qty });
            } else if (COIN_VALUES.has(thbValue)) {
                coins.push({ value: fvSatang, qty });
            } else {
                // Unknown denomination - guess by value
                console.warn("Unknown THB denom, guessing type:", d);
                if (thbValue <= 10) {
                    coins.push({ value: fvSatang, qty });
                } else {
                    notes.push({ value: fvSatang, qty });
                }
            }
        }

        if (!notes.length && !coins.length) {
            this._notify("Please select at least one valid denomination.", "danger");
            return;
        }

        const payload = {
            session_id: "1",
            currency: "THB",
            notes,
            coins,
        };

        console.log("[ExchangeCash] Dispense payload (THB→satang):", JSON.stringify(payload));

        this._notify("Processing cash-out...", "info");
        this.state.busy = true;

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_out/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });

            const raw = await resp.json().catch(() => ({}));
            const result = raw?.jsonrpc ? raw.result : raw;

            console.log("[ExchangeCash] cash_out/execute response:", result);

            const status = result?.status;
            const code = String(result?.result_code ?? "");
            const ok = resp.ok && status === "OK" && (code === "0" || code === "10");

            if (ok && intendedTHB > 0) {
                this.state.step = "summary";
                this._notify(
                    `Cash-out accepted. Dispensing ฿${intendedTHB}. Please collect your cash.`,
                    "success"
                );
            } else {
                const msg =
                    result?.error ||
                    result?.details ||
                    `Upstream status=${status || "UNKNOWN"} result_code=${code || "?"}`;
                this._notify(`Cash-out failed: ${msg}`, "danger");
                console.error("[ExchangeCash] Cash-out failed:", { intendedTHB, status, code, result });
            }
        } catch (e) {
            console.error("[ExchangeCash] cash_out/execute error:", e);
            this._notify("Cash-out failed: communication error", "danger");
        } finally {
            this.state.busy = false;
        }
    }

    // ============================================================================
    // STEP 3: SUMMARY / DONE
    // ============================================================================
    
    onHome() {
        // Reset state and return to parent
        this.state.amount = 0;
        this.state.liveAmount = 0;
        this.state.denominations.forEach(d => d.qty = 0);
        this.state.step = "counting";
        this.props.onCancel?.();
    }
}