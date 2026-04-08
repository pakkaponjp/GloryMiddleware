/** @odoo-module **/
/**
 * export_dialog_patch.js
 * Patches ExportDataDialog to hide "Available fields" left panel by default.
 * Template override (export_dialog_patch.xml) adds the toggle button.
 */

import { ExportDataDialog } from "@web/views/view_dialogs/export_data_dialog";
import { patch } from "@web/core/utils/patch";
import { useState } from "@odoo/owl";

patch(ExportDataDialog.prototype, {
    setup() {
        // fieldSelectorState ต้องถูก set ก่อน super.setup() เรียก template
        this.fieldSelectorState = useState({ expanded: false });
        super.setup(...arguments);
    },

    toggleFieldSelector() {
        this.fieldSelectorState.expanded = !this.fieldSelectorState.expanded;
    },
});