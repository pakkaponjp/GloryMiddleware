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
            step:          "amount",  // "amount" | "processing" | "collecting" | "done"
            amount:        "",        // whole-baht digit string
            subBahtSatang: 0,         // 0 | 25 | 50 | 75
            error:         "",
            busy:          false,
            resultMessage: "",
            // Summary fields
            insertedSatang: 0,   // actual cash customer inserted
            changeSatang:   0,   // change dispensed
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
                this.state.step           = "done";
                this.state.resultMessage  = `Deposit ฿${amountThb.toLocaleString()} complete`;
                this.state.insertedSatang = resp.inserted_satang || amountSatang;
                this.state.changeSatang   = resp.change_satang   || 0;
                this.props.onStatusUpdate?.(this.state.resultMessage);

                // Print receipt — non-critical
                this.rpc("/gas_station_cash/print/deposit_with_amount", {
                    reference:    resp.reference || `TXN-${Date.now()}`,
                    deposit_type: this.props.depositType,
                    staff_name:   this.props.employeeDetails?.name || this.props.employeeDetails?.external_id || "",
                    deposit_id:   resp.deposit_id || null,
                    total_satang: amountSatang,
                    product_name: resp.product_name || null,
                    datetime_str: new Date().toLocaleString("th-TH", {
                        day: "2-digit", month: "2-digit", year: "numeric",
                        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
                    }),
                }).catch(e => console.warn("[DepositWithAmount] Print failed:", e));

                setTimeout(() => this.props.onDone?.(amountThb), 3000);
            } else if (resp.cannot_dispense) {
                // Machine accepted cash but cannot dispense change
                // cash-out/execute was called — user needs to collect from exit slot
                console.warn("[DepositWithAmount] Cannot dispense — return_ok=", resp.return_ok);

                if (resp.return_ok) {
                    // Cash is being dispensed — show collecting screen and poll
                    this.state.step = "collecting";
                    this.props.onStatusUpdate?.("⚠️ Cannot dispense change. Please collect your cash.");
                    this._pollUntilCollected();
                } else {
                    // Could not return — tell user to contact staff
                    this.state.step  = "amount";
                    this.state.error = "Cannot dispense change. Please contact staff to collect your cash.";
                    this.props.onStatusUpdate?.("⚠️ " + this.state.error);
                }
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

    async _pollUntilCollected(maxAttempts = 20, intervalMs = 1500) {
        // Poll FCC status until DevStatus st != 3000 (exit slot cleared = user collected cash)
        for (let i = 0; i < maxAttempts; i++) {
            await new Promise(r => setTimeout(r, intervalMs));
            try {
                const status = await this.rpc("/gas_station_cash/fcc/status", {});
                const devStatuses = status?.raw?.Status?.DevStatus || [];
                const exitClear = devStatuses.every(d => d.st !== 3000);
                console.log("[DepositWithAmount] Poll status — devStatuses:", devStatuses, "exitClear:", exitClear);
                if (exitClear) {
                    console.log("[DepositWithAmount] Cash collected by user");
                    break;
                }
            } catch (e) {
                console.warn("[DepositWithAmount] Poll status failed:", e);
            }
        }
        // After polling — show error and return to menu
        this.state.step  = "amount";
        this.state.error = "Cannot dispense change. Your cash has been returned to the exit slot.";
        this.props.onStatusUpdate?.("⚠️ " + this.state.error);
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