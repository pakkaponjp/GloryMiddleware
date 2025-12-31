/** @odoo-module **/

import { Component, useState, onWillUnmount, onMounted } from "@odoo/owl";

export class ExchangeCashScreen extends Component {
    static template = "gas_station_cash.ExchangeCashScreen";
    static props = {
        onCancel: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
        employeeDetails: { type: Object, optional: true }, // to pass user/external_id to backend
    };

    setup() {
        this.state = useState({
            step: "counting",               // counting -> denominations -> summary
            amount: 0,                      // final counted amount after End
            liveAmount: 0,                  // live total while counting
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
            message: null,                  // {text, type}
        });

        this._pollHandle = null;

        this.increment = this.increment.bind(this);
        this.decrement = this.decrement.bind(this);
        this.canAdd = this.canAdd.bind(this);

        onMounted(() => this._startCashIn());
        onWillUnmount(() => this._stopPolling());
    }

    // ---------------- Utils ----------------
    _notify(text, type = "info") {
        this.state.message = { text, type };
        if (this.props.onStatusUpdate) {
            this.props.onStatusUpdate(text, type);
        }
        // auto-clear banner after a bit
        setTimeout(() => {
            if (this.state.message?.text === text) this.state.message = null;
        }, 5000);
    }

    _stopPolling() {
        if (this._pollHandle) {
            clearInterval(this._pollHandle);
            this._pollHandle = null;
        }
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

    // ---------------- Cash-In lifecycle ----------------
    async _startCashIn() {
        this._notify("Opening cash-in...");

        // Build a user for the Flask start endpoint; you require user in your API
        // const user = this.props.employeeDetails?.external_id
        //           || this.props.employeeDetails?.employee_id
        //           || "odoo_user";

        this.state.busy = true;
        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user: "gs_cashier", session_id: "1" }),   // Flask will default / produce session_id=1 internally, or adjust proxy to send it
            });
            console.log("Cash-in start response:", resp);
            const payload = await resp.json();     // JSON-RPC style: {result: {...}} or plain JSON
            const data = payload.result ?? payload;
            console.log("+++++Cash-in start data:", data);

            if (resp.ok && data?.result?.result === 0) {
                this._notify("Insert notes/coins now.");
                this.state.step = "counting";
                this.state.busy = false;
                console.log("Beginning polling for live cash-in status....................................");
                this._beginPolling();
            } else {
                this.state.busy = false;
                this._notify("Failed to open cash-in.", "danger");
                console.error("Failed to open cash-in:", data);
            }
        } catch (e) {
            this.state.busy = false;
            console.error(e);
            this._notify("Communication error while opening cash-in.", "danger");
        }
    }

    _beginPolling() {
        this._stopPolling();
        // Poll live status (uses your /api/v1/cash-in/status wrapper)
        this._pollHandle = setInterval(async () => {
            try {
                const resp = await fetch("/gas_station_cash/fcc/cash_in/status", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: "1" }),
                });
                const payload = await resp.json();
                const data = payload.result ?? payload;

                // Your Flask returns:
                // { state, counted: { by_fv: {...}, thb: number } }
                const counted = data?.counted || {};
                let total = counted.thb ?? 0;

                if (!total && counted.by_fv) {
                    total = Object.entries(counted.by_fv)
                        .reduce((s, [fv, qty]) => s + Number(fv) * Number(qty), 0);
                }

                console.log("Polled counted data:", counted, "=> total:", total);
                this.state.liveAmount = ((total || 0) / 100).toFixed(2);  // backend gives in satang
                console.log("Polled live amount:", this.state.liveAmount);
            } catch (e) {
                console.warn("Polling failed:", e);
            }
        }, 1200);
    }

    async _confirmCounting() {
        // Finalize: EndCashin
        this._stopPolling();
        this.state.busy = true;
        this._notify("Finalizing deposit...");

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/end", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: "1", user: "gs_cashier" }),
            });
            const payload = await resp.json();
            const data = payload.result ?? payload;

            console.log("*******End cash-in response:", resp, data?.raw?.result);
            // Prefer liveAmount if End response doesn’t include totals
            //const ok = r.ok && (data.status === "OK" || data.code === "0" || data?.raw?.result === 0);
            if (resp.ok && resp.statusText === "OK") {
                // Freeze the final amount (from latest poll)
                this.state.amount = this.state.liveAmount;
                this.state.step = "denominations";
                this._notify(`Cash counted: ฿${this.state.amount}`, "success");
            } else {
                this._notify("Failed to finalize deposit.", "danger");
            }
        } catch (e) {
            console.error(e);
            this._notify("Communication error while finalizing deposit.", "danger");
        } finally {
            this.state.busy = false;
        }
    }

    async _cancelCounting() {
        this._stopPolling();
        this.state.busy = true;
        this._notify("Cancelling deposit...");

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/cancel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
            const payload = await r.json();
            const data = payload.result ?? payload;

            const ok = resp.ok && (data.status === "OK" || data.code === "0" || data?.raw?.result === 0);
            if (ok) {
                this._notify("Deposit cancelled.");
                this.props.onCancel?.();
            } else {
                this._notify("Failed to cancel deposit.", "danger");
            }
        } catch (e) {
            console.error(e);
            this._notify("Communication error while cancelling deposit.", "danger");
        } finally {
            this.state.busy = false;
        }
    }

    // ---------------- Denomination step ----------------
    get totalSelected() {
        return this.state.denominations.reduce((s, d) => s + d.value * d.qty, 0);
    }
    get amountLeft() {
        return this.state.amount - this.totalSelected;
    }
    canAdd(d) { return d?.value <= this.amountLeft; }
    increment(d) { if (this.canAdd(d)) d.qty += 1; }
    decrement(d) { if (d.qty > 0) d.qty -= 1; }

    // async onConfirmDenominations() {
    //     const totalRequested = this.totalSelected;
    //     if (totalRequested !== this.state.amount) {
    //         this._notify(`Mismatch: Entered ฿${totalRequested} ≠ Counted ฿${this.state.amount}`, "danger");
    //         return;
    //     }

    //     this._notify("Processing exchange request...");
    //     try {
    //         const denominationsPayload = this.state.denominations
    //             .filter(d => d.qty > 0)
    //             .map(d => ({ value: d.value, qty: d.qty }));

    //         const resp = await fetch("/gas_station_cash/change", {
    //             method: "POST",
    //             headers: { "Content-Type": "application/json" },
    //             body: JSON.stringify({
    //                 amount: this.state.amount,
    //                 denominations: denominationsPayload,
    //             }),
    //         });
    //         const result = await resp.json();

    //         if (result.success) {
    //             this.state.step = "summary";
    //             this._notify("Exchange confirmed! Please collect your cash.", "success");
    //         } else {
    //             this._notify(`Exchange failed: ${result.details || "Unknown error"}`, "danger");
    //         }
    //     } catch (e) {
    //         console.error(e);
    //         this._notify("Exchange failed: communication error", "danger");
    //     }
    // }

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
    
        // THB denominations (in THB units)
        const COIN_VALUES = new Set([1, 2, 5, 10]);
        const NOTE_VALUES = new Set([20, 50, 100, 500, 1000]);
    
        const notes = [];
        const coins = [];
    
        // Compute intended amount in THB BEFORE scaling
        let intendedTHB = 0;
    
        for (const d of selected) {
            const thbValue = Number(d.value);  // UI value in THB
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
    
        console.log("Dispense payload (THB→satang):", JSON.stringify(payload));
    
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
        
            console.log("*******Cash-out execute response:", resp, result);
        
            const status = result?.status;
            const code = String(result?.result_code ?? "");
            const ok = resp.ok && status === "OK" && (code === "0" || code === "10");
        
            if (ok && intendedTHB > 0) {
                this.state.step = "summary";
                this._notify(
                    `Cash-out accepted (code ${code}). Requested ฿${intendedTHB}. Please collect your cash.`,
                    "success"
                );
            } else {
                const msg =
                    result?.error ||
                    result?.details ||
                    `Upstream status=${status || "UNKNOWN"} result_code=${code || "?"}`;
                this._notify(`Cash-out failed: ${msg}`, "danger");
                console.error("Cash-out failed:", { intendedTHB, status, code, result });
            }
        } catch (e) {
            console.error("cash_out/execute error:", e);
            this._notify("Cash-out failed: communication error", "danger");
        } finally {
            this.state.busy = false;
        }
    }

    onHome() {
        // Reset and exit back to parent
        this._stopPolling();
        this.state.amount = 0.00;
        this.state.liveAmount = 0.00;
        this.state.denominations.forEach(d => d.qty = 0);
        this.state.step = "counting";
        this.props.onCancel?.();
    }
}





