/** @odoo-module **/

import { Component } from "@odoo/owl";

export class CashDepositSummaryScreen extends Component {
    static template = "gas_station_cash.CashDepositSummaryScreen";

    static props = {
        title: { type: String, optional: true },
        mainLabel: { type: String, optional: true },
        subtitle: { type: String, optional: true },
        amount: { type: [String, Number] },
        items: { type: Array, optional: true },
        onConfirm: { type: Function },
        onBack: { type: Function, optional: true },
    };
}
