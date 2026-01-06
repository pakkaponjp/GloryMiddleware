/** @odoo-module **/

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class BlockingOverlay extends Component {
  static template = "gas_station_cash.BlockingOverlay";

  setup() {
    this.posOverlay = useService("pos_command_overlay");
    console.log("[BlockingOverlay] mounted");
  }

  get state() {
    return this.posOverlay?.state || { visible: false };
  }
}
