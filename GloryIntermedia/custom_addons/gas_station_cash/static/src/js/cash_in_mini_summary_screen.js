/** @odoo-module **/
import { Component, onMounted } from "@odoo/owl";

export class CashInMiniSummaryScreen extends Component {
    static template = "gas_station_cash.CashInMiniSummaryScreen";

    static props = {
        summaryItems: { type: Array, optional: true },
        totalAmount: { type: Number, optional: true },
        onDone: { type: Function, optional: true },
    };

    setup() {
        // Auto return after 3 seconds
        onMounted(() => {
            this._autoTimer = setTimeout(() => {
                this._returnHome();
            }, 3000);
        });
        console.log("CashInMiniSummaryScreen setup complete");
    }

    _onConfirm() {
        this._returnHome();
    }

    _returnHome() {
        console.log("Returning home from CashInMiniSummaryScreen");
        if (this._autoTimer) {
            clearTimeout(this._autoTimer);
            this._autoTimer = null;
        }

        this.props.onDone?.(this.props.totalAmount);
    }
}
