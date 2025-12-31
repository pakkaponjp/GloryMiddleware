/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class ExchangeCashScreen extends Component {
    setup() {
        console.log("ExchangeCashScreen has been successfully loaded.");
        this.state = useState({
            step: "input_amount",
            amount: "",
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
        });

        this.increment = this.increment.bind(this);
        this.decrement = this.decrement.bind(this);
        this.canAdd = this.canAdd.bind(this);
        // this.onConfirmDenominations = this.onConfirmDenominations.bind(this); //NEW
        // this.onHome = this.onHome.bind(this) //NEW
    }
// --- Number Pad Methods (Correctly placed here) ---
    onNumberPadClick(number) {
        if (this.state.amount.length < 10) {
            this.state.amount += number.toString();
        }
    }

    onBackspace() {
        this.state.amount = this.state.amount.slice(0, -1);
    }

    onConfirmAmount() {
        const enteredAmount = parseFloat(this.state.amount);
        if (!isNaN(enteredAmount) && enteredAmount > 0) {
            this.state.amount = enteredAmount;
            this.state.step = 'confirm';
        } else {
            console.error("Invalid amount entered.");
        }
    }

    onStatusUpdate = (text, type) => {
        this.state.statusMessage = text;

        // You can also add a timer to clear the message after a few seconds
        setTimeout(() => {
            this.state.statusMessage = "";
        }, 5000); // Clears the message after 5 seconds
    };

    // onStartCounting() {
    //     console.log("Input amount");
    //     const simulatedAmount = 1570;
    //     this.state.amount = simulatedAmount;
    //     this.state.step = "confirm";
    //     this.onStatusUpdate(`Cash counted: ฿${simulatedAmount}`, "info");
    // }
    onStartCounting() {
        console.log("Input amount");

        // Get the amount value from the state, which is bound to the input field
        const inputAmount = this.state.amount;

        // Check if the input amount is a valid number
        if (inputAmount && !isNaN(inputAmount)) {
            // Set the state with the validated amount
            this.state.amount = parseFloat(inputAmount);

            // Transition to the next step, for example, "confirm"
            this.state.step = "confirm";

            this.onStatusUpdate(`Cash counted: ฿${inputAmount}`, "info");
        } else {
            // Handle invalid input, e.g., show an error message
            this.onStatusUpdate("Please enter a valid amount.", "error");
        }
    }

    onConfirmExchange() {
        console.log("User confirmed amount:", this.state.amount);
        this.state.step = "denominations";
        this.onStatusUpdate("Please select notes/coins to exchange.", "info");
    }

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

    // onConfirmDenominations() {
    //     const totalRequested = this.state.denominations.reduce(
    //         (sum, d) => sum + d.value * (parseInt(d.qty) || 0),
    //         0
    //     );

    //     console.log("Requested total:", totalRequested);

    //     if (totalRequested !== this.state.amount) {
    //         this.onStatusUpdate(
    //             `Mismatch: Entered ฿${totalRequested} ≠ Counted ฿${this.state.amount}`,
    //             "danger"
    //         );
    //         return;
    //     }

    //     if (this.amountLeft === 0) {
    //         console.log("Exchange confirmed with:", this.state.denominations);

    //         this.onStatusUpdate("Exchange confirmed! Please collect your cash.", "success");
    //         console.log("Exchange confirmed. Dispensing...");

    //         // Reset
    //         this.state.step = "summary";
    //         // this.state.amount = 0;
    //         // this.state.denominations.forEach((d) => (d.qty = 0));


    //         // Trigger parent navigation
    //         // if (this.props.onExit) {
    //         //     this.props.onExit();
    //         // }
    //     }
    //     else if (totalRequested !== this.state.amount) {
    //         this.onStatusUpdate(
    //             `Mismatch: Entered ฿${totalRequested} ≠ Counted ฿${this.state.amount}`,
    //             "danger"
    //         );
    //         return;
    //     }
    //     else {
    //         this.onStatusUpdate(
    //             "Cannot proceed exchange cash."
    //         );
    //     }
    // }
    async onConfirmDenominations() {
        const totalRequested = this.state.denominations.reduce(
            (sum, d) => sum + d.value * (parseInt(d.qty) || 0),
            0
        );

        console.log("Requested total:", totalRequested);

        // Validate total matches input amount
        if (totalRequested !== this.state.amount) {
            this.onStatusUpdate(
                `Mismatch: Entered ฿${totalRequested} ≠ Counted ฿${this.state.amount}`,
                "danger"
            );
            return;
        }

        if (this.amountLeft === 0) {
            console.log("Exchange confirmed with:", this.state.denominations);

            this.onStatusUpdate("Processing exchange request...", "info");

            console.log("++++++++++++++++++++++++++++++++++++++++++++++");
            try {
                // Build payload for backend
                const denominationsPayload = this.state.denominations
                    .filter(d => d.qty > 0)
                    .map(d => ({
                        value: d.value,
                        qty: d.qty
                    }));

                const payload = {
                    amount: this.state.amount,
                    denominations: denominationsPayload,
                };

                console.log("Sending payload to /gas_station_cash/change:", payload);

                // Call Odoo controller
                const response = await fetch("/gas_station_cash/change", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });

                const result = await response.json();
                console.log("Response from /gas_station_cash/change:", result);

                if (result.success) {
                    this.onStatusUpdate("Exchange confirmed! Please collect your cash.", "success");
                    console.log("Exchange operation result:", result);

                    // Extract dispensed denominations from FCC response
                    const dispensedDenominations = [];
                    if (result.data && Array.isArray(result.data.Cash)) {
                        result.data.Cash.forEach(cash => {
                            if (cash.Denomination) {
                                cash.Denomination.forEach(denom => {
                                    dispensedDenominations.push({
                                        value: denom.fv,
                                        qty: denom.Piece,
                                        currency: denom.cc,
                                        status: denom.Status
                                    });
                                });
                            }
                        });
                    }

                    console.log("Dispensed denominations:", dispensedDenominations);

                    // Move to summary screen
                    this.state.step = "summary";

                    this.onStatusUpdate("Exchange confirmed! Please collect your cash.", "success");
                } else {
                    this.onStatusUpdate(`Exchange failed: ${result.details || "Unknown error"}`, "danger");
                }
            } catch (error) {
                console.error("Exchange API error:", error);
                this.onStatusUpdate("Exchange failed: communication error", "danger");
            }
        } else {
            this.onStatusUpdate("Cannot proceed exchange cash.", "danger");
        }
    }

    onHome() {
        // Reset the state for a new transaction
        console.log("+++++++++++++++++++++++++onHome clicked");
        this.state.amount = 0;
        this.state.denominations.forEach((d) => (d.qty = 0));
        this.state.step = "input_amount";
        this.onStatusUpdate("Ready for new exchange.", "info");

        // Trigger parent navigation
        if (this.props.onExit) {
            this.props.onExit();
        }
        console.log("-------------------------onExit didn't called.");
    }
}

ExchangeCashScreen.props = {
    onCancel: { type: Function },
    onStatusUpdate: { type: Function },
};

ExchangeCashScreen.template = "gas_station_cash.ExchangeCashScreen";