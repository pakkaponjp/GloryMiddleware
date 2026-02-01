/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

export class LiveCashInScreen extends Component {
    static template = "gas_station_cash.LiveCashInScreen";

    static props = {
        liveAmount:      { type: Number, optional: true },
        busy:            { type: Boolean, optional: true },
        onDone:          { type: Function, optional: true },  // OK / finished
        onCancel:        { type: Function, optional: true },  // user cancels
        onApiError:      { type: Function, optional: true },
        onStatusUpdate:  { type: Function, optional: true },
    };

    setup() {
        this.state = useState({
            busy: this.props.busy ?? false,
            liveAmount: this.props.liveAmount ?? 0,
            machineState: null,     // Machine state from Glory API
            isCounting: false,      // True when machine is actively counting cash
        });

        this._pollHandle = null;

        onMounted(() => this._startCashIn());
        onWillUnmount(() => this._stopPolling());
    }

    // ---------- helpers ----------
    _notify(text, type = "info") {
        this.props.onStatusUpdate?.(text, type);
    }

    _stopPolling() {
        if (this._pollHandle) {
            clearInterval(this._pollHandle);
            this._pollHandle = null;
        }
    }

    /**
     * Determine if machine is actively counting based on state code from Glory API
     * 
     * Glory Status Codes (from StatusResponse -> Status -> Code):
     * - Code 3 = "Waiting for deposit" - Machine is IDLE, waiting for cash
     * - Code 4 = "Counting" - Machine is actively counting
     * - Code 5 = "Escrow full" - Counting done, cash in escrow
     * 
     * From the SOAP response: <Status><n:Code>3</n:Code> means waiting
     * When "Now, counting." shows on Glory = Code is NOT 3
     */
    _isMachineCounting(state) {
        if (state === null || state === undefined) return false;
        
        const stateVal = String(state).toLowerCase().trim();
        
        // Log for debugging
        console.log("[LiveCashIn] Machine state:", stateVal);
        
        // Glory Code 3 = Waiting for deposit (NOT counting)
        // Empty, "3", "idle", "waiting" = NOT counting
        const idleStates = ['', '3', 'idle', 'waiting', 'ready', 'wait'];
        
        if (idleStates.includes(stateVal)) {
            return false;  // Not counting - waiting for cash
        }
        
        // Any other state (4, 5, "counting", etc.) = IS counting/processing
        return true;
    }

    // ---------- computed for template ----------
    
    /**
     * OK button should be disabled when:
     * - busy (API call in progress)
     * - machine is counting
     * - no money deposited yet (liveAmount === 0)
     */
    get confirmDisabled() {
        return this.state.busy || this.state.isCounting || this.state.liveAmount === 0;
    }

    /**
     * Cancel button should be disabled when:
     * - busy (API call in progress)  
     * - machine is actively counting
     */
    get cancelDisabled() {
        return this.state.busy || this.state.isCounting;
    }

    // ---------- open / status ----------
    async _startCashIn() {
        this.state.busy = true;
        this._notify("Opening cash-in...");

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user: "gs_cashier", session_id: "1" }),
            });

            const payload = await resp.json();
            const data = payload.result ?? payload;
            const inner = data.result ?? data.raw ?? {};

            // Your log: { result: { result: 0, ... }, session_id: "1" }
            const ok = resp.ok && inner.result === 0;

            if (ok) {
                console.log("cash_in/start OK:", data);
                this.state.busy = false;
                this._notify("Insert notes/coins now.");
                this._beginPolling();
            } else {
                console.log("cash_in/start failed:", data);
                this.state.busy = false;
                this.props.onApiError?.("Failed to open cash-in.");
            }
        } catch (e) {
            console.error("cash_in/start error:", e);
            this.state.busy = false;
            this.props.onApiError?.("Communication error while opening cash-in.");
        }
    }

    _beginPolling() {
        this._stopPolling();
        this._pollHandle = setInterval(async () => {
            try {
                const resp = await fetch("/gas_station_cash/fcc/cash_in/status", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: "1" }),
                });
                const payload = await resp.json();
                const data = payload.result ?? payload;

                // Get machine state
                const machineState = data.state ?? null;
                this.state.machineState = machineState;
                this.state.isCounting = this._isMachineCounting(machineState);

                // Log state for debugging
                if (this.state.isCounting) {
                    console.log("[LiveCashIn] Machine counting, state:", machineState);
                }

                // Calculate total amount
                const counted = data.counted ?? {};
                let total = counted.thb ?? 0;

                if (!total && counted.by_fv) {
                    total = Object.entries(counted.by_fv)
                        .reduce((s, [fv, qty]) => s + Number(fv) * Number(qty), 0);
                }

                this.state.liveAmount = (total || 0) / 100;  // satang → THB
            } catch (e) {
                console.warn("cash_in/status polling failed:", e);
            }
        }, 800);  // Poll slightly faster (800ms) for better UX
    }

    // ---------- OK / Done ----------
    async _confirm() {
        // Don't allow confirm while counting
        if (this.state.isCounting) {
            this._notify("Please wait for counting to complete.", "warning");
            return;
        }

        this._stopPolling();
        this.state.busy = true;
        this._notify("Finalizing cash-in...");

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/end", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: "1", user: "gs_cashier" }),
            });

            const payload = await resp.json();
            const data = payload.result ?? payload;

            console.log("cash_in/end raw payload:", payload);

            // Mirror your working exchange logic: treat HTTP OK + "OK" as success
            const ok = resp.ok && resp.statusText === "OK";

            if (ok) {
                const amount = this.state.liveAmount;
                this._notify(`Cash-in confirmed: ฿${amount}`, "success");
                this.props.onDone?.(amount);
            } else {
                console.warn("cash_in/end not OK:", data);
                this.props.onApiError?.("Failed to finalize cash-in.");
            }
        } catch (e) {
            console.error("cash_in/end error:", e);
            this.props.onApiError?.("Communication error while finalizing cash-in.");
        } finally {
            this.state.busy = false;
        }
    }

    // ---------- Cancel ----------
    async _cancel() {
        // Don't allow cancel while counting
        if (this.state.isCounting) {
            this._notify("Please wait for counting to complete.", "warning");
            return;
        }

        this._stopPolling();
        this.state.busy = true;
        this._notify("Cancelling cash-in...");

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_in/cancel", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: "1" }),
            });
            const payload = await resp.json();
            const data = payload.result ?? payload;
            const inner = data.result ?? data.raw ?? {};

            const ok = resp.ok && inner.result === 0;

            if (ok) {
                this._notify("Cash-in cancelled.");
                this.props.onCancel?.();
            } else {
                this.props.onApiError?.("Failed to cancel cash-in.");
            }
        } catch (e) {
            console.error("cash_in/cancel error:", e);
            this.props.onApiError?.("Communication error while cancelling cash-in.");
        } finally {
            this.state.busy = false;
        }
    }
}