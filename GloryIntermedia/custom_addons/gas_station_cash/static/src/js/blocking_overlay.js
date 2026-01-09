/** @odoo-module **/

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class BlockingOverlay extends Component {
  setup() {
    // ดึง service ที่ registry.category("services").add("pos_command_overlay", ...)
    this.overlay = useService("pos_command_overlay");
    console.log("[BlockingOverlay] setup overlay service =", !!this.overlay, "visible=", this.overlay?.state?.visible);
  }
}

BlockingOverlay.template = "gas_station_cash.BlockingOverlay";
