/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CashRecyclerApp } from "./cash_recycler_app";
import { GloryControlPanel } from "./glory_control_panel";

// The 'gas_station_cash.cash_recycler_app' tag is what we used in the XML client action.
// We register our main component to this tag so Odoo knows what to render.
registry.category("actions").add("gas_station_cash.cash_recycler_app", CashRecyclerApp);
registry.category("actions").add("gas_station_cash.glory_control_panel", GloryControlPanel);