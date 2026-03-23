/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * DepositWithAmountScreen
 *
 * Number pad screen used by coffee_shop / convenient_store / rental deposits.
 *
 * Flow:
 *   User enters target deposit amount → OK → machine accepts cash from user
 *   → machine automatically dispenses change = (inserted cash) - amount
 *   → audit record saved as normal deposit
 *
 * Props:
 *   depositType        'coffee_shop' | 'convenient_store' | 'rental'
 *   employeeDetails    { employee_id, external_id, role, name }
 *   onDone             called after successful deposit (amount: number)
 *   onCancel           called when user cancels
 *   onSkipToNormal     go to normal deposit screen (coffee_shop/convenient_store only)
 *   onStatusUpdate     optional status bar callback
 *   onApiError         optional error handler
 */
export class DepositWithAmountScreen extends Component {
    static template = "gas_station_cash.DepositWithAmountScreen";

    static props = {
        depositType:     { type: String },
        employeeDetails: { type: Object, optional: true },
        onDone:          { type: Function },
        onCancel:        { type: Function },
        onSkipToNormal:  { type: Function, optional: true },
        onStatusUpdate:  { type: Function, optional: true },
        onApiError:      { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");

        this.state = useState({
            step:          "amount",  // "amount" | "processing" | "done"
            amount:        "",        // whole-baht digit string
            subBahtSatang: 0,         // 0 | 25 | 50 | 75
            error:         "",
            busy:          false,
            resultMessage: "",
        });
    }

    // ── Getters ───────────────────────────────────────────────────────────────

    get depositTypeName() {
        const names = {
            coffee_shop:      "Coffee Shop Sales",
            convenient_store: "Convenient Store Sales",
            rental:           "Rental",
        };
        return names[this.props.depositType] || this.props.depositType;
    }

    get showSkipButton() {
        return ["coffee_shop", "convenient_store"].includes(this.props.depositType);
    }

    get numericAmountSatang() {
        const raw  = String(this.state.amount || "").replace(/[^\d]/g, "");
        const baht = parseInt(raw || "0", 10);
        return (Number.isFinite(baht) ? baht : 0) * 100 + (this.state.subBahtSatang || 0);
    }

    get numericAmount() {
        return this.numericAmountSatang / 100;
    }

    get displayAmount() {
        const satang = this.numericAmountSatang;
        if (satang === 0) return "0";
        const thb = satang / 100;
        return this.state.subBahtSatang > 0
            ? thb.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
            : Math.floor(thb).toLocaleString();
    }

    get canConfirm() {
        return this.numericAmountSatang > 0 && !this.state.busy;
    }

    // ── Keypad (same pattern as WithdrawalScreen) ─────────────────────────────

    _onKeypadPress(digit) {
        if (this.state.step !== "amount") return;
        if (String(this.state.amount).length >= 7) return;
        if (this.state.amount === "" && digit === "0") return;
        this.state.amount = String(this.state.amount || "") + String(digit);
        this.state.error  = "";
    }

    _onBackspace() {
        if (this.state.step !== "amount") return;
        this.state.amount = String(this.state.amount || "").slice(0, -1);
        this.state.error  = "";
    }

    _onClear() {
        if (this.state.step !== "amount") return;
        this.state.amount        = "";
        this.state.subBahtSatang = 0;
        this.state.error         = "";
    }

    _onSubBahtPress(satang) {
        if (this.state.step !== "amount") return;
        this.state.subBahtSatang = this.state.subBahtSatang === satang ? 0 : satang;
        this.state.error         = "";
    }

    // ── Confirm ───────────────────────────────────────────────────────────────

    async _onConfirm() {
        if (!this.canConfirm) return;

        const amountSatang = this.numericAmountSatang;
        const amountThb    = this.numericAmount;

        this.state.busy  = true;
        this.state.step  = "processing";
        this.state.error = "";
        this.props.onStatusUpdate?.("Processing — please insert cash into the machine...");

        try {
            const resp = await this.rpc("/gas_station_cash/deposit_with_change", {
                deposit_type:      this.props.depositType,
                amount_satang:     amountSatang,
                staff_external_id: this.props.employeeDetails?.external_id || "",
                employee_id:       this.props.employeeDetails?.employee_id  || "",
            });

            if (resp.success) {
                this.state.step          = "done";
                this.state.resultMessage = `Deposit ฿${amountThb.toLocaleString()} complete`;
                this.props.onStatusUpdate?.(this.state.resultMessage);
                setTimeout(() => this.props.onDone?.(amountThb), 3000);
            } else {
                this.state.step  = "amount";
                this.state.error = resp.message || "Deposit failed. Please try again.";
                this.props.onStatusUpdate?.(this.state.error);
                this.props.onApiError?.(this.state.error);
            }
        } catch (err) {
            console.error("[DepositWithAmount] rpc error:", err);
            this.state.step  = "amount";
            this.state.error = "Connection error. Please try again.";
            this.props.onStatusUpdate?.(this.state.error);
            this.props.onApiError?.(this.state.error);
        } finally {
            this.state.busy = false;
        }
    }

    _onCancel() {
        if (this.state.busy) return;
        this.props.onCancel?.();
    }

    _onSkipToNormal() {
        if (this.state.busy) return;
        this.props.onSkipToNormal?.();
    }
}