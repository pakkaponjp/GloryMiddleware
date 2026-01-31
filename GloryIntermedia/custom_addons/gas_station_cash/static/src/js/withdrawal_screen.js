/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * WithdrawalScreen - Enter withdrawal amount with inventory validation
 * 
 * Flow:
 * 1. Load cash availability from Glory machine
 * 2. User enters amount via keypad or quick amounts
 * 3. System calculates optimal denomination breakdown
 * 4. User confirms → dispense cash
 * 
 * Features:
 * - Real-time inventory check
 * - Smart denomination calculation (greedy algorithm)
 * - Shows breakdown before dispensing
 * - Validates against available stock
 */
export class WithdrawalScreen extends Component {
    static template = "gas_station_cash.WithdrawalScreen";

    static props = {
        employeeDetails: { type: Object, optional: true },
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
        onApiError: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");
        this.SESSION_ID = "1";  // TODO: Get from session manager

        this.state = useState({
            // UI state
            step: "amount",  // "amount" | "confirm" | "dispensing" | "pickup" | "done"
            amount: "",
            error: "",
            busy: false,
            
            // Inventory data
            inventory: null,
            inventoryLoading: true,
            maxWithdrawable: 0,
            currency: "THB",  // Will be updated from machine response
            
            // Calculated breakdown
            breakdown: {
                notes: [],
                coins: [],
                total: 0,
            },
            
            // Result
            dispensedAmount: 0,
            
            // Pickup waiting
            pickupPolling: false,
        });

        // Quick amount buttons (Thai Baht)
        this.quickAmounts = [500, 1000, 2000, 5000, 10000, 20000];

        // Thai Baht denominations (descending order for greedy algorithm)
        // These are the actual denominations used in Thai gas stations
        this.DENOMINATIONS = {
            notes: [1000, 500, 100, 50, 20],
            coins: [10, 5, 2, 1],
        };

        onMounted(() => this._loadInventory());
    }

    // =========================================================================
    // GETTERS
    // =========================================================================

    get displayAmount() {
        const n = this.numericAmount;
        return (n || 0).toLocaleString();
    }

    get numericAmount() {
        const raw = String(this.state.amount || "").replace(/[^\d]/g, "");
        const n = parseInt(raw || "0", 10);
        return Number.isFinite(n) ? n : 0;
    }

    get staffName() {
        return this.props.employeeDetails?.name || 
               this.props.employeeDetails?.employee_id || 
               "Staff";
    }

    get canConfirm() {
        const amt = this.numericAmount;
        return amt > 0 && 
               amt <= this.state.maxWithdrawable && 
               !this.state.busy &&
               !this.state.inventoryLoading;
    }

    get breakdownTotal() {
        return this.state.breakdown.total;
    }

    // =========================================================================
    // INVENTORY LOADING
    // =========================================================================

    async _loadInventory() {
        this.state.inventoryLoading = true;
        this.props.onStatusUpdate?.("Loading cash availability...");

        try {
            // Use fetch with credentials for Odoo session authentication
            const resp = await fetch(`/gas_station_cash/fcc/cash/availability?session_id=${this.SESSION_ID}`, {
                method: "GET",
                headers: { 
                    "Content-Type": "application/json",
                },
                credentials: "same-origin",  // Important: include session cookie
            });

            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }

            const data = await resp.json();
            console.log("[WithdrawalScreen] Inventory loaded:", data);

            // Save currency from machine (auto-detected)
            const currency = data.currency || "THB";
            this.state.currency = currency;

            // Parse inventory - filter only available denominations with stock
            const inventory = {
                notes: (data.notes || []).filter(d => d.available && d.qty > 0),
                coins: (data.coins || []).filter(d => d.available && d.qty > 0),
            };

            // Calculate max withdrawable
            let maxWithdrawable = 0;
            for (const note of inventory.notes) {
                maxWithdrawable += note.value * note.qty;
            }
            for (const coin of inventory.coins) {
                maxWithdrawable += coin.value * coin.qty;
            }

            this.state.inventory = inventory;
            this.state.maxWithdrawable = maxWithdrawable;
            this.props.onStatusUpdate?.(`Available: ฿${maxWithdrawable.toLocaleString()}`);

        } catch (e) {
            console.error("[WithdrawalScreen] Failed to load inventory:", e);
            this.state.error = "Failed to load cash availability";
            this.props.onApiError?.("Cannot connect to cash machine");
        } finally {
            this.state.inventoryLoading = false;
        }
    }

    // =========================================================================
    // DENOMINATION CALCULATION
    // =========================================================================

    /**
     * Calculate optimal denomination breakdown using greedy algorithm
     * Prioritizes larger denominations first, respects inventory limits
     */
    _calculateBreakdown(targetAmount) {
        if (!this.state.inventory) {
            return { notes: [], coins: [], total: 0, shortage: targetAmount };
        }

        const result = {
            notes: [],
            coins: [],
            total: 0,
        };

        let remaining = targetAmount;

        // Build a map of available quantities
        const available = {};
        for (const note of this.state.inventory.notes) {
            available[note.value] = { qty: note.qty, device: 1 };
        }
        for (const coin of this.state.inventory.coins) {
            available[coin.value] = { qty: coin.qty, device: 2 };
        }

        // Process notes first (descending order)
        for (const value of this.DENOMINATIONS.notes) {
            if (remaining <= 0) break;
            
            const avail = available[value];
            if (!avail || avail.qty <= 0) continue;

            const needed = Math.floor(remaining / value);
            const canUse = Math.min(needed, avail.qty);

            if (canUse > 0) {
                result.notes.push({
                    value,
                    qty: canUse,
                    amount: value * canUse,
                    device: 1,
                });
                remaining -= value * canUse;
                result.total += value * canUse;
            }
        }

        // Process coins (descending order)
        for (const value of this.DENOMINATIONS.coins) {
            if (remaining <= 0) break;
            
            const avail = available[value];
            if (!avail || avail.qty <= 0) continue;

            const needed = Math.floor(remaining / value);
            const canUse = Math.min(needed, avail.qty);

            if (canUse > 0) {
                result.coins.push({
                    value,
                    qty: canUse,
                    amount: value * canUse,
                    device: 2,
                });
                remaining -= value * canUse;
                result.total += value * canUse;
            }
        }

        result.shortage = remaining;
        return result;
    }

    // =========================================================================
    // KEYPAD HANDLERS
    // =========================================================================

    _onKeypadPress(digit) {
        if (this.state.step !== "amount") return;
        if (String(this.state.amount).length >= 7) return;  // Max 9,999,999
        if (this.state.amount === "" && digit === "0") return;
        
        this.state.amount = String(this.state.amount || "") + String(digit);
        this.state.error = "";
        this._updateBreakdown();
    }

    _onBackspace() {
        if (this.state.step !== "amount") return;
        this.state.amount = String(this.state.amount || "").slice(0, -1);
        this.state.error = "";
        this._updateBreakdown();
    }

    _onClear() {
        if (this.state.step !== "amount") return;
        this.state.amount = "";
        this.state.error = "";
        this.state.breakdown = { notes: [], coins: [], total: 0 };
    }

    _setQuickAmount(amount) {
        if (this.state.step !== "amount") return;
        this.state.amount = String(amount);
        this.state.error = "";
        this._updateBreakdown();
    }

    _updateBreakdown() {
        const amt = this.numericAmount;
        if (amt <= 0) {
            this.state.breakdown = { notes: [], coins: [], total: 0 };
            return;
        }

        const breakdown = this._calculateBreakdown(amt);
        this.state.breakdown = breakdown;

        // Check if we can fulfill the amount
        if (breakdown.shortage > 0) {
            if (breakdown.total === 0) {
                this.state.error = "Insufficient cash in machine";
            } else {
                this.state.error = `Can only dispense ฿${breakdown.total.toLocaleString()} (short ฿${breakdown.shortage.toLocaleString()})`;
            }
        } else if (amt > this.state.maxWithdrawable) {
            this.state.error = `Maximum available: ฿${this.state.maxWithdrawable.toLocaleString()}`;
        } else {
            this.state.error = "";
        }
    }

    // =========================================================================
    // CONFIRM & DISPENSE
    // =========================================================================

    async _onProceedToConfirm() {
        const amt = this.numericAmount;
        
        if (amt <= 0) {
            this.state.error = "Please enter a valid amount";
            return;
        }

        // Recalculate breakdown
        const breakdown = this._calculateBreakdown(amt);
        
        if (breakdown.total <= 0) {
            this.state.error = "Cannot dispense this amount";
            return;
        }

        if (breakdown.shortage > 0) {
            // Offer to dispense what's available
            this.state.breakdown = breakdown;
            this.state.error = `Will dispense ฿${breakdown.total.toLocaleString()} instead`;
        }

        this.state.breakdown = breakdown;
        this.state.step = "confirm";
    }

    _onBackToAmount() {
        this.state.step = "amount";
        this.state.error = "";
    }

    async _onConfirmDispense() {
        const breakdown = this.state.breakdown;
        
        if (breakdown.total <= 0) {
            this.state.error = "Nothing to dispense";
            return;
        }

        console.log("[WithdrawalScreen] Dispensing:", breakdown);

        this.state.busy = true;
        this.state.step = "dispensing";
        this.props.onStatusUpdate?.("Dispensing cash...");

        // Prepare payout request
        // IMPORTANT: Glory uses cents/satang, so multiply by 100
        const GLORY_MULTIPLIER = 100;
        
        const notes = breakdown.notes.map(n => ({ 
            value: n.value * GLORY_MULTIPLIER,
            qty: n.qty,
            device: 1 
        }));
        const coins = breakdown.coins.map(c => ({ 
            value: c.value * GLORY_MULTIPLIER,
            qty: c.qty,
            device: 2 
        }));

        console.log("[WithdrawalScreen] Sending to Glory - notes:", notes, "coins:", coins);

        try {
            // Send cash-out request (don't wait for response - may timeout)
            this.rpc("/gas_station_cash/fcc/cash_out/execute", {
                session_id: this.SESSION_ID,
                amount: breakdown.total * GLORY_MULTIPLIER,
                currency: this.state.currency,
                notes,
                coins,
            }).then(result => {
                console.log("[WithdrawalScreen] Dispense response:", result);
            }).catch(e => {
                console.log("[WithdrawalScreen] Dispense request error (ignored):", e.message);
            });

            // Wait a moment for machine to start dispensing
            await new Promise(resolve => setTimeout(resolve, 1000));

            // Go directly to pickup - we'll check machine status there
            this.state.dispensedAmount = breakdown.total;
            this.state.busy = false;
            this.state.step = "pickup";
            this.props.onStatusUpdate?.("Please collect your cash");
            this._startPickupPolling();

        } catch (e) {
            console.error("[WithdrawalScreen] Dispense error:", e);
            // Even on error, go to pickup and check machine status
            this.state.dispensedAmount = breakdown.total;
            this.state.busy = false;
            this.state.step = "pickup";
            this.props.onStatusUpdate?.("Please collect your cash");
            this._startPickupPolling();
        }
    }
    
    _goToPickup(amount) {
        this.state.dispensedAmount = amount;
        this.state.busy = false;
        this.state.step = "pickup";
        this.props.onStatusUpdate?.("Please collect your cash");
        this._startPickupPolling();
    }

    // =========================================================================
    // PICKUP WAITING & POLLING
    // =========================================================================

    _startPickupPolling() {
        if (this.state.pickupPolling) return;
        
        this.state.pickupPolling = true;
        console.log("[WithdrawalScreen] Starting pickup polling...");
        setTimeout(() => this._pollForPickup(), 2000);
    }

    async _pollForPickup() {
        if (!this.state.pickupPolling || this.state.step !== "pickup") {
            return;
        }

        try {
            const statusResult = await this.rpc("/gas_station_cash/fcc/status", {
                session_id: this.SESSION_ID,
                verify: true,
            });

            console.log("[WithdrawalScreen] Full status result:", JSON.stringify(statusResult));
            
            // Status structure from Flask:
            // { status: "OK", code: "0", raw: { Status: { Code: "1", ... } } }
            const rawStatus = statusResult?.raw?.Status;
            const statusCode = rawStatus?.Code;
            
            // Also check DevStatus st value (1000 = idle)
            const devStatus = rawStatus?.DevStatus;
            let stValue = null;
            if (Array.isArray(devStatus)) {
                stValue = devStatus[0]?.st;
            } else if (devStatus) {
                stValue = devStatus.st;
            }
            
            console.log("[WithdrawalScreen] Status Code:", statusCode, "DevStatus st:", stValue);

            // Code 1 = Idle (cash picked up)
            // st 1000 = idle
            if (statusCode == 1 || statusCode === "1") {
                console.log("[WithdrawalScreen] Machine IDLE (Code=1) - cash picked up!");
                this._onCashPickedUp();
                return;
            }
        } catch (e) {
            console.log("[WithdrawalScreen] Poll error:", e.message);
        }

        setTimeout(() => this._pollForPickup(), 2000);
    }

    _stopPickupPolling() {
        this.state.pickupPolling = false;
    }

    _onCashPickedUp() {
        this._stopPickupPolling();
        this.state.step = "done";
        this.props.onStatusUpdate?.(`Dispensed ฿${this.state.dispensedAmount.toLocaleString()}`);
    }

    // =========================================================================
    // DONE & CANCEL
    // =========================================================================

    _onDone() {
        this._stopPickupPolling();
        this.props.onDone?.(this.state.dispensedAmount);
    }

    _onCancel() {
        this._stopPickupPolling();
        console.log("[WithdrawalScreen] Cancelled");
        this.props.onCancel?.();
    }
}