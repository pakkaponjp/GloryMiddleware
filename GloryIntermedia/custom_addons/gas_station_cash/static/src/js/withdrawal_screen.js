/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * WithdrawalScreen - Enter withdrawal amount
 * 
 * This screen is shown AFTER PIN verification via PinEntryScreen.
 * It only handles amount entry and withdrawal confirmation.
 * 
 * Flow:
 * 1. User clicks "Withdrawal" button
 * 2. Goes to PinEntryScreen (select staff + enter PIN)
 * 3. PIN verified → comes here (withdrawalAmount screen)
 * 4. User enters amount → confirms → done
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

        this.state = useState({
            amount: "",
            error: "",
            busy: false,
        });

        // Bind methods
        this._onKeypadPress = this._onKeypadPress.bind(this);
        this._onBackspace = this._onBackspace.bind(this);
        this._onClear = this._onClear.bind(this);
        this._onConfirm = this._onConfirm.bind(this);
        this._onCancel = this._onCancel.bind(this);
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

    get staffExternalId() {
        return this.props.employeeDetails?.external_id || "";
    }

    // =========================================================================
    // KEYPAD HANDLERS
    // =========================================================================

    _onKeypadPress(digit) {
        // Limit to reasonable length (10 digits)
        if (String(this.state.amount).length >= 10) return;
        
        // Prevent leading zeros
        if (this.state.amount === "" && digit === "0") return;
        
        this.state.amount = String(this.state.amount || "") + String(digit);
        this.state.error = "";
    }

    _onBackspace() {
        this.state.amount = String(this.state.amount || "").slice(0, -1);
        this.state.error = "";
    }

    _onClear() {
        this.state.amount = "";
        this.state.error = "";
    }

    _setQuickAmount(amount) {
        this.state.amount = String(amount);
        this.state.error = "";
    }

    // =========================================================================
    // CONFIRM WITHDRAWAL
    // =========================================================================

    async _onConfirm() {
        const amt = this.numericAmount;
        
        if (amt <= 0) {
            this.state.error = "Please enter a valid amount";
            return;
        }

        // TODO: Add limit check from backend if needed
        // const maxWithdrawal = 50000;
        // if (amt > maxWithdrawal) {
        //     this.state.error = `Maximum withdrawal is ฿${maxWithdrawal.toLocaleString()}`;
        //     return;
        // }

        console.log("[WithdrawalScreen] Confirming withdrawal:", {
            staff: this.props.employeeDetails,
            amount: amt,
        });

        this.state.busy = true;
        this.props.onStatusUpdate?.("Processing withdrawal...");

        try {
            // TODO: Call withdrawal API
            // const result = await this.rpc("/gas_station_cash/withdrawal/process", {
            //     staff_id: this.staffExternalId,
            //     amount: amt,
            // });

            // For now, just complete successfully
            this.props.onStatusUpdate?.(`Withdrawal of ฿${amt.toLocaleString()} confirmed`);
            this.props.onDone?.(amt);

        } catch (e) {
            console.error("[WithdrawalScreen] Error:", e);
            this.state.error = "Withdrawal failed. Please try again.";
            this.props.onApiError?.("Withdrawal failed");
        } finally {
            this.state.busy = false;
        }
    }

    // =========================================================================
    // CANCEL
    // =========================================================================

    _onCancel() {
        console.log("[WithdrawalScreen] Cancelled");
        this.props.onCancel?.();
    }
}