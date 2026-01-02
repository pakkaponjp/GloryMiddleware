/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { LiveCashInScreen } from "./live_cash_in_screen";
import { CashInMiniSummaryScreen } from "./cash_in_mini_summary_screen";

export class EngineOilDepositScreen extends Component {
    static template = "gas_station_cash.EngineOilDepositScreen";

    static components = {
        LiveCashInScreen,
        CashInMiniSummaryScreen,
    };

    static props = {
        employeeDetails: { type: Object, optional: true },
        onCancel: { type: Function, optional: true },
        onDone: { type: Function, optional: true },            // go back home with amount
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc")
        this.state = useState({
            step: "counting",   // "counting" -> "summary"
            liveAmount: 0,
            finalAmount: 0,
            busy: false,

            products: [],
            selectedProduct: null,
            summaryItems: [],
        });

        // Bind methods
        this._onSelectProduct = this._onSelectProduct.bind(this);
        this._cancelAll = this._cancelAll.bind(this);
        this._onCashInDone = this._onCashInDone.bind(this);
        this._onCancelCounting = this._onCancelCounting.bind(this);
        this._onSummaryDone = this._onSummaryDone.bind(this);

        // Load products before showing the screen
        onWillStart(async () => {
            try {
                this.state.step = "loading";
                const result = await this.rpc("/gas_station_cash/products", {});
                const products = result?.products || [];
                this.state.products = products;

                if (!products.length) {
                    this.state.step = "select_product";
                    this.props.onStatusUpdate?.(
                        "No active products founds. Please configure Gas Station Products."
                    );

                    return;
                }

                //If only 1 product -> auto-select and go counting
                if (products.length == 1) {
                    this.state.selectedProduct = products[0];
                    this.props.onStatusUpdate?.(
                        `Gas station product: ${products[0].name} selected. You can start cash-in now.`
                    );
                    this.state.step = "counting";
                    return;
                }

                // Otherwise show list
                this.state.step = "select_product";
            } catch (error) {
                console.error("[EngineOilDeposit] failed to load products:", error);
                this.props.onApiError?.("Failed to load products");
                this.state.products = [];
                this.state.step = "select_product";
            }
        });
    }

    // ---------- Step 2: selecting product ----------
    _onSelectProduct(prod) {
        this.state.selectedProduct = prod;
        this.props.onStatusUpdate?.(`Selected engine oil: ${prod?.name || ""}`);
        this.state.step = "counting";
    }

     _cancelAll() {
        this.props.onCancel?.();
    }

    _onCashInDone(amount) {
        const numericAmount = Number(amount || 0);
        console.log("[EngineOilDeposit] cash-in done, amount:", numericAmount);

        const txId = `TXN-${Date.now()}`;
        const staffId = this.props.employeeDetails?.external_id || "CASHIER-0000";
        const product = this.state.selectedProduct;
        const productId = product?.id || null;

        // Only POS-related products should call POS
        const isPosRelated = !!product?.is_pos_related;

        if (!isPosRelated) {
            console.log("[EngineOilDeposit] product is NOT POS-related -> skip POS send", {
                product_id: productId,
                product_code: product?.code,
                is_pos_related: product?.is_pos_related,
            });
        } else {
            console.log("[EngineOilDeposit] POS CALL payload:", {
                transaction_id: txId,
                staff_id: staffId,
                amount: numericAmount,
                product_id: productId,
            });

            this.rpc("/gas_station_cash/pos/deposit_http", {
                transaction_id: txId,
                staff_id: staffId,
                amount: numericAmount,
            })
                .then((resp) => {
                    const status = String(resp?.status || "").toUpperCase();
                    const ok = status === "OK";

                    console.log("[EngineOilDeposit] POS resp:", resp, "ok=", ok);

                    if (ok) {
                        this.props.onStatusUpdate?.("POS OK. Proceeding to audit...");

                        return this.rpc("/gas_station_cash/pos/deposit_success", {
                            transaction_id: txId,
                            staff_id: staffId,
                            amount: numericAmount,
                            pos_response: resp,
                            deposit_type: "engine_oil",
                            product_id: productId,
                        });
                    } else {
                        this.props.onStatusUpdate?.("POS not OK. Queuing retry job...");

                        return this.rpc("/gas_station_cash/pos/deposit_enqueue", {
                            transaction_id: txId,
                            staff_id: staffId,
                            amount: numericAmount,
                            pos_response: resp,
                            reason: resp?.description || resp?.discription || "POS returned non-OK",
                            deposit_type: "engine_oil",
                            product_id: productId,
                        });
                    }
                })
                .then((serverResp) => {
                    console.log("[EngineOilDeposit] server follow-up resp:", serverResp);
                })
                .catch((err) => {
                    console.error("[EngineOilDeposit] POS error:", err);
                    this.props.onStatusUpdate?.("POS call failed. Queuing retry job...");

                    return this.rpc("/gas_station_cash/pos/deposit_enqueue", {
                        transaction_id: txId,
                        staff_id: staffId,
                        amount: numericAmount,
                        pos_response: null,
                        reason: String(err?.message || err),
                        deposit_type: "engine_oil",
                        product_id: productId,
                    }).catch((e2) => {
                        console.error("[EngineOilDeposit] enqueue failed:", e2);
                    });
                });
        }

        // --- existing logic continues ---
        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;

        this.state.summaryItems = [
            { label: "Deposit Type", value: "Gas Station Product" },
            { label: "Product", value: product?.name || "-" },
            { label: "Code", value: product?.code || "-" },
            { label: "Amount", value: numericAmount },
        ];

        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[EngineOilDeposit] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

    // Called when the summary screen auto-returns / Done is clicked
    _onSummaryDone(amountFromSummary) {
        // Check if the argument is an Event object (it will have a 'target' property)
        const validAmount = (amountFromSummary && typeof amountFromSummary !== 'object') 
            ? amountFromSummary 
            : null;

        const amount = Number(
            validAmount ?? 
            this.state.finalAmount ?? 
            0
        );

        console.log("[EngineOilDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
