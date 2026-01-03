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
        const isPosRelated = !!product?.is_pos_related;

        Promise.resolve().then(async () => {
            try {
                const resp = await this.rpc("/gas_station_cash/deposit/finalize", {
                    transaction_id: txId,
                    staff_id: staffId,
                    amount: numericAmount,
                    deposit_type: "engine_oil",
                    product_id: productId,
                    is_pos_related: isPosRelated,
                });

                const ok = String(resp?.status || "").toLowerCase() === "ok";
                if (!ok) {
                    console.error("[EngineOilDeposit] finalize not ok:", resp);
                    this.props.onStatusUpdate?.(resp?.message || "Audit failed (finalize not ok).");
                    return;
                }

                this.props.onStatusUpdate?.(`Audit saved (deposit_id=${resp.deposit_id})`);
            } catch (err) {
                console.error("[EngineOilDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Audit failed (see logs).");
            }
        });

        // Update state to show summary
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
