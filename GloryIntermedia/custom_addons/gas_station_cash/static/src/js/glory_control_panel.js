/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class GloryControlPanel extends Component {
    // ไว้ค่อยเติม handler ทีหลังได้
}

GloryControlPanel.template = "gas_station_cash.GloryControlPanel";

// ✅ สำคัญ: register ให้ <widget name="glory_control_buttons"/> ใช้งานได้
registry.category("view_widgets").add("glory_control_buttons", {
    component: GloryControlPanel,
});
