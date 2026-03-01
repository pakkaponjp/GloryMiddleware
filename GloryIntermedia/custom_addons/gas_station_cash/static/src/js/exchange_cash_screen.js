/** @odoo-module **/

import { Component, useState, onWillUnmount } from "@odoo/owl";
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
            amount: 0,                      // total THB deposited after cash-in
            liveAmount: 0,                  // live amount while counting (passed to LiveCashInScreen)

            // ── Denominations user selects for cash-out ──
            // values in THB (0.25 and 0.50 are exact in IEEE 754 — safe for arithmetic)
            denominations: [
                { value: 1000, qty: 0 },
                { value: 500,  qty: 0 },
                { value: 100,  qty: 0 },
                { value: 50,   qty: 0 },
                { value: 20,   qty: 0 },
                { value: 10,   qty: 0 },
                { value: 5,    qty: 0 },
                { value: 2,    qty: 0 },
                { value: 1,    qty: 0 },
                { value: 0.5,  qty: 0 },
                { value: 0.25, qty: 0 },
            ],

            // ── What the user actually deposited during cash-in ──
            // Stored so we can dispense the EXACT same denominations back on Cancel.
            //
            // Shape (values in SATANG, matching GloryAPI convention):
            //   { notes: [{value: <satang>, qty}, ...], coins: [{value: <satang>, qty}, ...] }
            //
            // Populated by _onCashInDone(amount, breakdown).
            // If LiveCashInScreen has not been updated to pass breakdown yet,
            // this stays null and _buildReturnPayload() uses a greedy fallback.
            cashin_breakdown: null,

            busy: false,                    // true while dispense is in progress
            cancelBusy: false,              // true while return-cash is in progress
            message: null,
            countdown: 3,                   // seconds until auto-return after success
            dispensedAmount: 0,             // THB amount successfully dispensed
            pickupPolling: false,           // true while waiting for machine idle
        });

        this._countdownTimer       = null;
        this._pickupTimer          = null;
        this._seenDispensingState  = false;  // guard: must see non-idle before accepting idle=done
        this._fccCurrency          = "THB";  // loaded from odoo.conf via /config

        // Load currency code from server (reads fcc_currency from odoo.conf)
        this._loadFccCurrency();

        this.increment = this.increment.bind(this);
        this.decrement = this.decrement.bind(this);
        this.canAdd    = this.canAdd.bind(this);

        onWillUnmount(() => {
            this._clearCountdown();
            this._stopPickupPolling();
        });
    }

    // ============================================================================
    // COUNTDOWN / AUTO-RETURN
    // ============================================================================

    _clearCountdown() {
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
    }

    _startCountdown(isDone = false) {
        this._clearCountdown();
        this.state.countdown = 3;
        this._countdownTimer = setInterval(() => {
            this.state.countdown -= 1;
            if (this.state.countdown <= 0) {
                this._clearCountdown();
                this._hardReset(isDone);
            }
        }, 1000);
    }

    // Reset ALL state and notify parent to leave this screen
    // isDone=true  → after successful dispense → call onDone (go home normally)
    // isDone=false → after cancel/return       → call onCancel
    _hardReset(isDone = false) {
        const amount = this.state.amount;
        this.state.amount           = 0;
        this.state.liveAmount       = 0;
        this.state.cashin_breakdown = null;
        this.state.denominations.forEach(d => (d.qty = 0));

        if (isDone) {
            // Set "exiting" (renders nothing) before calling onDone() so that
            // OWL never mounts LiveCashInScreen between the state reset and
            // the parent navigation — which would fire cash-in/start spuriously.
            this.state.step = "exiting";
            this.props.onDone?.(amount);
        } else {
            this.state.step = "counting";
            this.props.onCancel?.();
        }
    }

    // ============================================================================
    // NOTIFICATION HELPERS
    // ============================================================================

    _notify(text, type = "info") {
        this.state.message = { text, type };
        this.props.onStatusUpdate?.(text, type);
        setTimeout(() => {
            if (this.state.message?.text === text) this.state.message = null;
        }, 5000);
    }

    // ============================================================================
    // STEP 1: LIVE CASH-IN (via LiveCashInScreen component)
    // ============================================================================

    /**
     * Called when LiveCashInScreen completes successfully.
     *
     * @param {number} amount     - Total THB deposited (e.g. 650)
     * @param {Object} [breakdown] - Denomination breakdown of deposited cash:
     *   {
     *     notes: [ { value: <satang>, qty: <n> }, ... ],
     *     coins: [ { value: <satang>, qty: <n> }, ... ]
     *   }
     *
     * !! IMPORTANT: LiveCashInScreen must be updated to pass `breakdown` as the
     *    second argument to this callback.  Until that change is made, Cancel
     *    will use a greedy fallback to reconstruct the return denominations.
     */
    _onCashInDone(amount, breakdown = null) {
        const amt = Number(amount) || 0;
        console.log("[ExchangeCash] cash-in done. amount:", amt, "breakdown:", breakdown);

        this.state.amount           = amt;
        this.state.cashin_breakdown = breakdown;   // null until LiveCashInScreen is updated
        this.state.step             = "denominations";
        this._notify(`Cash counted: ฿${amt.toLocaleString()}`, "success");
    }

    /** Called when user cancels BEFORE inserting cash (step === 'counting') */
    _onCashInCancel() {
        console.log("[ExchangeCash] cash-in cancelled (no cash in machine)");
        // Nothing in the machine yet — safe to leave immediately
        this.props.onCancel?.();
    }

    /** Called when LiveCashInScreen encounters an API error */
    _onCashInError(errorMsg) {
        console.error("[ExchangeCash] cash-in error:", errorMsg);
        this._notify(errorMsg, "danger");
        // Do NOT propagate to this.props.onApiError — causes TypeError in CashRecyclerApp
        // (_onApiError loses its this binding when passed as a prop and invoked here)
    }

    // ============================================================================
    // STEP 2: DENOMINATION SELECTION
    // ============================================================================

    // Work in satang (integer) to avoid IEEE 754 drift with 0.25 / 0.50 THB.
    get totalSelectedSatang() {
        return this.state.denominations.reduce(
            (sum, d) => sum + Math.round(d.value * 100) * d.qty, 0
        );
    }

    get totalSelected() {
        return this.totalSelectedSatang / 100;
    }

    get amountLeftSatang() {
        return Math.round(this.state.amount * 100) - this.totalSelectedSatang;
    }

    get amountLeft() {
        return this.amountLeftSatang / 100;
    }

    canAdd(denom) {
        if (!denom) return false;
        return Math.round(denom.value * 100) <= this.amountLeftSatang;
    }

    increment(denom) {
        if (this.canAdd(denom)) denom.qty += 1;
    }

    decrement(denom) {
        if (denom.qty > 0) denom.qty -= 1;
    }

    /** Execute the cash-out dispense chosen by the user */
    async onConfirmDenominations() {
        // Compare in satang to avoid floating-point inequality with 0.25/0.50
        const totalRequested = this.totalSelectedSatang;
        const stateAmount    = Math.round(this.state.amount * 100);

        if (totalRequested !== stateAmount) {
            this._notify(
                `Mismatch: Entered ฿${(totalRequested/100).toFixed(2)} ≠ Counted ฿${(stateAmount/100).toFixed(2)}`,
                "danger"
            );
            return;
        }

        const selected = this.state.denominations.filter(d => d.qty > 0);
        if (!selected.length) {
            this._notify("Please select at least one note/coin to dispense.", "danger");
            return;
        }

        const payload = this._buildCashOutPayload(selected);
        if (!payload) return;

        this._notify("Processing cash-out...", "info");
        this.state.busy = true;

        try {
            const ok = await this._executeCashOut(payload);
            if (ok) {
                // Money has been dispensed — clear breakdown so Cancel won't re-dispense
                this.state.cashin_breakdown = null;
                this.state.dispensedAmount  = payload.intendedTHB;
                this.state.step             = "pickup";
                this._notify(
                    `Cash-out accepted. Dispensing ฿${payload.intendedTHB.toLocaleString()}. Please collect your cash.`,
                    "success"
                );
                this._startPickupPolling();
            }
            // On failure: _executeCashOut already called _notify; leave screen open for retry
        } finally {
            this.state.busy = false;
        }
    }

    // ============================================================================
    // CANCEL — Return deposited cash to user before leaving
    //
    // State machine for Cancel at denomination-selection screen:
    //
    //   state.amount === 0   →  no cash in machine, go home immediately
    //   state.amount  > 0   →  cash is in machine:
    //       1. Build return payload from cashin_breakdown (exact) or greedy fallback
    //       2. Call cash_out/execute with those denominations
    //       3a. Success  → show "฿X returned" message → hard-reset after 2.5 s
    //       3b. Failure  → show error, leave screen open so staff can intervene
    // ============================================================================

    async onHome() {
        this._clearCountdown();

        // If we are still on the counting screen, nothing is in the machine
        if (this.state.step !== "denominations" || !this.state.amount) {
            this._hardReset();
            return;
        }

        // ── Cash is in the machine — must return it first ──
        const returnPayload = this._buildReturnPayload();
        if (!returnPayload) {
            // Guard: should not happen, but leave a clear audit trail
            console.error(
                "[ExchangeCash] onHome: cashin_breakdown is null AND greedy fallback produced nothing.",
                "Cannot determine what to return. Leaving screen open."
            );
            this._notify(
                "Cannot determine denominations to return. Please call staff.",
                "danger"
            );
            return;   // intentionally do NOT hard-reset — staff must handle
        }

        this._notify("Returning cash to exit slot...", "info");
        this.state.cancelBusy = true;

        try {
            const ok = await this._executeCashOut(returnPayload);

            if (ok) {
                this._notify(
                    `฿${this.state.amount.toLocaleString()} returned. Please collect your cash.`,
                    "success"
                );
                // Give user time to read the message and collect before screen resets
                setTimeout(() => this._hardReset(), 2500);
            } else {
                // _executeCashOut already notified via _notify
                // Leave the screen open — do NOT reset — staff needs to intervene
                console.error("[ExchangeCash] onHome: return-cash dispense FAILED. Screen left open for staff.");
            }
        } catch (e) {
            console.error("[ExchangeCash] onHome: unexpected error during return-cash:", e);
            this._notify("Unexpected error returning cash. Please call staff.", "danger");
            // Do NOT reset here either — safer to leave screen open
        } finally {
            this.state.cancelBusy = false;
        }
    }

    // ============================================================================
    // PRIVATE HELPERS
    // ============================================================================

    // ============================================================================
    // PICKUP WAITING & POLLING
    // Polls /fcc/status every 2 s; when machine returns to Idle (Code=1) the
    // exchange is complete and we move to the summary countdown screen.
    // ============================================================================

    _startPickupPolling() {
        if (this.state.pickupPolling) return;
        this.state.pickupPolling      = true;
        this._seenDispensingState     = false;  // reset guard for this dispense cycle
        console.log("[ExchangeCash] Starting pickup polling...");
        // Wait 3 s before first poll to give the machine time to start dispensing
        this._pickupTimer = setTimeout(() => this._pollForPickup(), 3000);
    }

    async _pollForPickup() {
        if (!this.state.pickupPolling || this.state.step !== "pickup") return;

        try {
            // /fcc/status is type="json" — must send a JSON-RPC 2.0 envelope
            const envelope = await fetch("/gas_station_cash/fcc/status", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", id: 1, params: {} }),
                credentials: "same-origin",
            }).then(r => r.json());

            // Odoo type="json" wraps the controller return inside { result: {...} }
            const statusResult = envelope?.result ?? envelope;
            const statusCode   = statusResult?.raw?.Status?.Code;

            console.log("[ExchangeCash] Pickup poll — machine status code:", statusCode,
                        "seenDispensing:", this._seenDispensingState);

            if (statusCode == 1 || statusCode === "1") {
                // Code 1 = Idle.
                // Only accept idle-as-done once we've seen the machine go non-idle
                // first (i.e., actually start dispensing). Without this guard a
                // spurious Code=1 right after the dispense command would send us
                // home before cash is delivered.
                if (this._seenDispensingState) {
                    console.log("[ExchangeCash] Machine back to IDLE after dispensing — cash collected.");
                    this._onCashPickedUp();
                    return;
                } else {
                    console.log("[ExchangeCash] Machine IDLE but dispense not yet observed — continuing to poll.");
                }
            } else if (statusCode !== null && statusCode !== undefined) {
                // Any non-idle code means the machine is actively dispensing / busy
                this._seenDispensingState = true;
                console.log("[ExchangeCash] Machine dispensing (code=" + statusCode + ") — waiting for pickup.");
            }
        } catch (e) {
            console.log("[ExchangeCash] Pickup poll error (ignored):", e.message);
        }

        // Schedule next poll
        this._pickupTimer = setTimeout(() => this._pollForPickup(), 2000);
    }

    _stopPickupPolling() {
        this.state.pickupPolling     = false;
        this._seenDispensingState    = false;
        if (this._pickupTimer) {
            clearTimeout(this._pickupTimer);
            this._pickupTimer = null;
        }
    }

    _onCashPickedUp() {
        this._stopPickupPolling();
        this.state.step = "summary";
        this._notify(
            `Exchange complete. ฿${this.state.dispensedAmount.toLocaleString()} dispensed.`,
            "success"
        );
        console.log("[ExchangeCash] Cash picked up — showing summary, returning home in 3 s.");
        this._startCountdown(true);   // true → onDone() after countdown
    }

    // ============================================================================
    // CONFIG LOADING
    // ============================================================================

    // Fetch fcc_currency from odoo.conf via the /gas_station_cash/config endpoint.
    // Called once on setup. Falls back silently to "THB" on error.
    async _loadFccCurrency() {
        try {
            const resp = await fetch("/gas_station_cash/config", {
                method:      "POST",
                headers:     { "Content-Type": "application/json" },
                credentials: "same-origin",
                body:        JSON.stringify({ jsonrpc: "2.0", method: "call", id: 1, params: {} }),
            });
            const data     = await resp.json();
            const currency = data?.result?.currency || data?.currency;
            if (currency) {
                this._fccCurrency = currency;
                console.log("[ExchangeCash] fcc_currency loaded:", this._fccCurrency);
            }
        } catch (e) {
            console.warn("[ExchangeCash] Could not load fcc_currency, defaulting to THB:", e.message);
        }
    }

        /**
     * Build a cash_out/execute payload from an array of denomination objects.
     *
     * Items must use THB face values (NOT satang).
     * Output notes/coins use satang (×100) as required by GloryAPI.
     *
     * Returns { session_id, currency, notes, coins, intendedTHB }
     * or null if no valid items could be converted.
     */
    _buildCashOutPayload(items) {
        const COIN_VALUES = new Set([0.25, 0.5, 1, 2, 5, 10]);
        const NOTE_VALUES = new Set([20, 50, 100, 500, 1000]);

        const notes = [];
        const coins = [];
        let intendedTHB = 0;

        for (const d of items) {
            const thbValue = Number(d.value);
            const qty      = Number(d.qty);
            if (!qty || qty <= 0) continue;

            // Accumulate in satang (integer) then convert back, avoids IEEE 754 drift
            const fvSatang = Math.round(thbValue * 100);   // GloryAPI wants satang (integer)
            intendedTHB += fvSatang * qty;                 // accumulate in satang

            if (NOTE_VALUES.has(thbValue)) {
                notes.push({ value: fvSatang, qty });
            } else if (COIN_VALUES.has(thbValue)) {
                coins.push({ value: fvSatang, qty });
            } else {
                console.warn("[ExchangeCash] Unknown denomination, guessing device:", d);
                (thbValue <= 10 ? coins : notes).push({ value: fvSatang, qty });
            }
        }

        // Convert satang back to THB for display/logging
        intendedTHB = intendedTHB / 100;

        if (!notes.length && !coins.length) {
            this._notify("Please select at least one valid denomination.", "danger");
            return null;
        }

        return { session_id: "1", currency: this._fccCurrency, notes, coins, intendedTHB };
    }

    /**
     * Build the return payload for Cancel.
     *
     * Priority:
     *   1. cashin_breakdown (exact denominations deposited — requires LiveCashInScreen update)
     *   2. Greedy fallback  (largest-denomination decomposition of state.amount)
     *
     * Returns { session_id, currency, notes, coins, intendedTHB } or null.
     *
     * Values in cashin_breakdown are already in SATANG (matching GloryAPI).
     */
    _buildReturnPayload() {
        let notes       = [];
        let coins       = [];
        const intendedTHB = this.state.amount;
        const breakdown   = this.state.cashin_breakdown;

        if (breakdown && (breakdown.notes?.length || breakdown.coins?.length)) {
            // ── Happy path: use the exact denominations from cash-in ──
            notes = (breakdown.notes || []).filter(n => n.qty > 0);
            coins = (breakdown.coins || []).filter(c => c.qty > 0);
            console.log("[ExchangeCash] Return payload (exact breakdown):", { notes, coins });

        } else {
            // ── Fallback: LiveCashInScreen has not yet been updated ──
            // Decompose state.amount (THB) into standard Thai denominations greedily.
            console.warn(
                "[ExchangeCash] cashin_breakdown unavailable — using greedy fallback.",
                "TODO: update LiveCashInScreen._onEnd() to call onDone(amount, breakdown)."
            );

            // Work in SATANG (integers) to handle 0.25 and 0.50 THB correctly.
            const NOTE_DENOMS_S = [100000, 50000, 10000, 5000, 2000];  // satang
            const COIN_DENOMS_S = [1000, 500, 200, 100, 50, 25];       // satang (incl. 0.50 & 0.25)
            let remaining = Math.round(intendedTHB * 100);              // convert to satang

            for (const denomS of NOTE_DENOMS_S) {
                if (remaining <= 0) break;
                const qty = Math.floor(remaining / denomS);
                if (qty > 0) {
                    notes.push({ value: denomS, qty });
                    remaining -= denomS * qty;
                }
            }
            for (const denomS of COIN_DENOMS_S) {
                if (remaining <= 0) break;
                const qty = Math.floor(remaining / denomS);
                if (qty > 0) {
                    coins.push({ value: denomS, qty });
                    remaining -= denomS * qty;
                }
            }

            if (remaining !== 0) {
                console.error(
                    `[ExchangeCash] Greedy fallback: ${remaining} satang (฿${(remaining/100).toFixed(2)}) unaccounted.`
                );
            }
        }

        if (!notes.length && !coins.length) return null;

        return { session_id: "1", currency: this._fccCurrency, notes, coins, intendedTHB };
    }

    /**
     * POST to cash_out/execute and return true if the machine accepted the command.
     *
     * @param {{ session_id, currency, notes, coins, intendedTHB }} payload
     */
    async _executeCashOut(payload) {
        // Strip intendedTHB — it is for internal bookkeeping only, not sent to API
        const apiPayload = {
            session_id: payload.session_id,
            currency:   payload.currency,
            notes:      payload.notes,
            coins:      payload.coins,
        };
        const intendedTHB = payload.intendedTHB;

        console.log("[ExchangeCash] POST cash_out/execute:", JSON.stringify(apiPayload));

        try {
            const resp = await fetch("/gas_station_cash/fcc/cash_out/execute", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(apiPayload),
            });

            const raw    = await resp.json().catch(() => ({}));
            const result = raw?.jsonrpc ? raw.result : raw;

            console.log("[ExchangeCash] cash_out/execute response:", result);

            const status = result?.status;
            const code   = String(result?.result_code ?? "");
            const ok     = resp.ok && status === "OK" && (code === "0" || code === "10");

            // 502 = Flask SOAP read-timeout: the machine received and accepted the
            // cashout command (it is already dispensing) but took longer than the
            // configured SOAP timeout to respond.  Treat it as success and let
            // pickup-polling confirm via /fcc/status that cash was actually dispensed.
            const soapTimeout = resp.status === 502;

            if (!ok && !soapTimeout) {
                const msg =
                    result?.error ||
                    result?.details ||
                    `Upstream status=${status || "UNKNOWN"} result_code=${code || "?"}`;
                this._notify(`Cash-out failed: ${msg}`, "danger");
                console.error("[ExchangeCash] cash_out failed:", { intendedTHB, status, code, result });
            }
            if (soapTimeout) {
                console.warn("[ExchangeCash] 502 SOAP timeout — machine likely dispensing, proceeding to pickup polling.");
            }

            return ok || soapTimeout;

        } catch (e) {
            console.error("[ExchangeCash] cash_out/execute network error:", e);
            this._notify("Cash-out failed: communication error", "danger");
            return false;
        }
    }

    // ============================================================================
    // STEP 3: SUMMARY
    // (Auto-return handled by countdown → _hardReset)
    // ============================================================================
}