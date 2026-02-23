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
        setCashInOpening: { type: Function, optional: true }, // Pause status check during opening
    };

    setup() {
        this.state = useState({
            busy: this.props.busy ?? false,
            liveAmount: this.props.liveAmount ?? 0,
            machineState: null,     // Machine state from Glory API
            isCounting: false,      // True when machine is actively counting cash
            isOpening: true,        // True while machine is opening (before ready)
            machineReady: false,    // True when machine is ready to accept cash
        });

        this._pollHandle = null;

        onMounted(() => this._startCashIn());
        onWillUnmount(() => this._stopPolling());
    }
    
    // ---------- deposit type icon/name getters ----------
    
    /**
     * Get current deposit type from global app state
     */
    get currentDepositType() {
        return window.cashRecyclerApp?.state?.selectedDepositType || "oil";
    }
    
    /**
     * Get icon URL for current deposit type
     */
    get depositIconUrl() {
        const icons = {
            oil: "/gas_station_cash/static/img/oil_icon.png",
            engine_oil: "/gas_station_cash/static/img/engine_oil_icon.png",
            rental: "/gas_station_cash/static/img/rental_icon.png",
            coffee_shop: "/gas_station_cash/static/img/coffee_shop_icon.png",
            convenient_store: "/gas_station_cash/static/img/convenient_store_icon.png",
            exchange_cash: "/gas_station_cash/static/img/exchange_icon.png",
            deposit_cash: "/gas_station_cash/static/img/exchange_icon.png",
        };
        return icons[this.currentDepositType] || icons.oil;
    }
    
    /**
     * Get display name for current deposit type
     */
    get depositTypeName() {
        const names = {
            oil: "Deposit Oil Sales",
            engine_oil: "Deposit Engine Oil",
            rental: "Deposit Rental",
            coffee_shop: "Deposit Coffee Shop",
            convenient_store: "Deposit Convenient Store",
            exchange_cash: "Exchange Cash",
            deposit_cash: "Replenish Cash",
        };
        return names[this.currentDepositType] || "Deposit";
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
     * Check if machine is ready to accept cash
     * Glory Status Codes:
     * - Code 3 = "Waiting for deposit" - Machine is READY, waiting for cash
     * - Code 4 = "Counting" - Machine is actively counting
     * - Code 5 = "Escrow full" - Counting done, cash in escrow
     */
    _isMachineReady(state) {
        if (state === null || state === undefined) return false;
        
        const stateVal = String(state).toLowerCase().trim();
        
        // Glory Code 3 = Waiting for deposit = READY
        const readyStates = ['3', 'idle', 'waiting', 'ready', 'wait'];
        
        return readyStates.includes(stateVal);
    }

    /**
     * Determine if machine is actively counting based on state code from Glory API
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
     * - machine is opening
     * - machine is counting
     * - no money deposited yet (liveAmount === 0)
     */
    get confirmDisabled() {
        return this.state.busy || this.state.isOpening || this.state.isCounting || this.state.liveAmount === 0;
    }

    /**
     * Cancel button should be disabled when:
     * - busy (API call in progress)
     * - machine is opening (not ready yet)
     * - machine is actively counting
     */
    get cancelDisabled() {
        return this.state.busy || this.state.isOpening || this.state.isCounting;
    }

    // ---------- open / status ----------
    async _startCashIn() {
        this.state.busy = true;
        this.state.isOpening = true;
        this.state.machineReady = false;
        this._notify("Opening cash-in...");
        
        // Pause status check during opening to prevent interference
        // Use window.cashRecyclerApp if props not available
        this.props.setCashInOpening?.(true);
        if (window.cashRecyclerApp?.setCashInOpening) {
            window.cashRecyclerApp.setCashInOpening(true);
        }

        // === TEST DELAY: Remove or comment out for production ===
        // await new Promise(resolve => setTimeout(resolve, 3000));
        // === END TEST DELAY ===

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
                // Don't set isOpening = false yet, wait for machine to be ready
                this._notify("Waiting for machine to be ready...");
                this._beginPolling();
            } else {
                console.log("cash_in/start failed:", data);
                this._handleOpeningFailed("Failed to open cash-in.");
            }
        } catch (e) {
            console.error("cash_in/start error:", e);
            this._handleOpeningFailed("Communication error while opening cash-in.");
        }
    }
    
    /**
     * Handle opening failure - resume status check and notify error
     */
    _handleOpeningFailed(errorMessage) {
        this.state.busy = false;
        this.state.isOpening = false;
        
        // Resume status check on failure
        this.props.setCashInOpening?.(false);
        if (window.cashRecyclerApp?.setCashInOpening) {
            window.cashRecyclerApp.setCashInOpening(false);
        }
        
        this.props.onApiError?.(errorMessage);
    }
    
    /**
     * Resume status check (called when machine is ready or on completion)
     */
    _resumeStatusCheck() {
        this.props.setCashInOpening?.(false);
        if (window.cashRecyclerApp?.setCashInOpening) {
            window.cashRecyclerApp.setCashInOpening(false);
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
                
                // Check if machine is ready (state = 3 / waiting)
                const isReady = this._isMachineReady(machineState);
                
                // If machine just became ready, transition from Opening to Ready
                if (isReady && this.state.isOpening) {
                    console.log("[LiveCashIn] Machine is now READY, state:", machineState);
                    this.state.isOpening = false;
                    this.state.machineReady = true;
                    this._notify("Insert notes/coins now.");
                    
                    // Resume status check now that machine is ready
                    this._resumeStatusCheck();
                }
                
                // Check if counting
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