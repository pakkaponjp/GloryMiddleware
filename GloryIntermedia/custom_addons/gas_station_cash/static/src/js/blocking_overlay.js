/** @odoo-module **/

import { Component, onMounted, onWillRender, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class BlockingOverlay extends Component {
  setup() {
    console.log("🎨 [BlockingOverlay] Component setup starting...");
    
    // Get the service
    this.posOverlay = useService("pos_command_overlay");
    console.log("   - Service retrieved:", !!this.posOverlay);
    console.log("   - Service state:", this.posOverlay?.state);

    // ✅ CRITICAL FIX: Use useState to make the component reactive
    // This creates a local reactive copy that will trigger re-renders
    this.state = useState(this.posOverlay.state);

    console.log("✅ [BlockingOverlay] Setup complete");
    console.log("   - Initial visible:", this.state.visible);
    console.log("   - Initial action:", this.state.action);
    console.log("   - Initial message:", this.state.message);
    
    onMounted(() => {
      console.log("🎨 [BlockingOverlay] Component MOUNTED");
      console.log("   - State visible:", this.state.visible);
      console.log("   - DOM element exists:", !!document.querySelector('.gsc_blocking_overlay'));
    });
    
    onWillRender(() => {
      console.log("🎨 [BlockingOverlay] Will render, visible:", this.state.visible);
    });
  }
}

BlockingOverlay.template = "gas_station_cash.BlockingOverlay";