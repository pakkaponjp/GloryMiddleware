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
        onDone: { type: Function, optional: true }, // back to home with amount
        onApiError: { type: Function, optional: true },
        onStatusUpdate: { type: Function, optional: true },
    };

    setup() {
        this.rpc = useService("rpc");

        this.state = useState({
            step: "loading", // loading -> select_product -> counting -> summary
            liveAmount: 0,
            finalAmount: 0,
            busy: false,

            products: [],
            selectedProduct: null,
            summaryItems: [],
        });

        // Bind methods (keeps your existing structure predictable)
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
                        "No active products found. Please configure Gas Station Products."
                    );
                    return;
                }

                // If only 1 product -> auto-select and go counting
                if (products.length === 1) {
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

    // ---------- Step 3: cash-in done ----------
    _onCashInDone(amount) {
        const numericAmount = Number(amount || 0);
        console.log("[EngineOilDeposit] cash-in done, amount:", numericAmount);

        // UI continues immediately
        this.state.liveAmount = numericAmount;
        this.state.finalAmount = numericAmount;

        const txId = `TXN-${Date.now()}`;
        const staffExternalId = this.props.employeeDetails?.external_id || "CASHIER-0000";

        const product = this.state.selectedProduct;
        const productId = product?.id || null;
        const isPosRelated = !!product?.is_pos_related;

        // Build summary items for the Summary screen you're already using
        this.state.summaryItems = [
            { label: "Deposit Type", value: "Engine Oil" },
            { label: "Product", value: product?.name || "-" },
            { label: "Code", value: product?.code || "-" },
            { label: "Amount", value: numericAmount },
            { label: "POS Related", value: isPosRelated ? "YES" : "NO" },
        ];

        // Fire the backend workflow (creates audit always; sends POS only if POS-related)
        this.rpc("/gas_station_cash/deposit/finalize", {
            transaction_id: txId,
            staff_id: staffExternalId,
            amount: numericAmount,
            deposit_type: "engine_oil",
            product_id: productId,
            is_pos_related: isPosRelated,
        })
            .then((resp) => {
                const ok = String(resp?.status || "").toLowerCase() === "ok";
                if (!ok) {
                    console.error("[EngineOilDeposit] finalize failed:", resp);
                    this.props.onStatusUpdate?.("Warning: audit/POS workflow failed (see logs).");
                    return;
                }

                const posStatus = resp?.pos_status || "na";
                const depositId = resp?.deposit_id;

                if (isPosRelated) {
                    // ok / queued
                    this.props.onStatusUpdate?.(
                        `Recorded (deposit_id=${depositId}). POS status=${posStatus}.`
                    );
                } else {
                    this.props.onStatusUpdate?.(`Recorded (deposit_id=${depositId}).`);
                }
            })
            .catch((err) => {
                console.error("[EngineOilDeposit] finalize error:", err);
                this.props.onStatusUpdate?.("Error: cannot record audit/POS workflow. Please notify admin.");
            });

        // Show summary (existing behavior)
        this.state.step = "summary";
    }

    _onCancelCounting() {
        console.log("[EngineOilDeposit] cancel from LiveCashInScreen");
        this.props.onCancel?.();
    }

    // ---------- Step 4: summary done ----------
    _onSummaryDone(amountFromSummary) {
        // If summary passes an event instead of value, ignore it
        const validAmount = amountFromSummary && typeof amountFromSummary !== "object" ? amountFromSummary : null;

        const amount = Number(validAmount ?? this.state.finalAmount ?? 0);
        console.log("[EngineOilDeposit] summary done, final amount:", amount);
        this.props.onDone?.(amount);
    }
}
