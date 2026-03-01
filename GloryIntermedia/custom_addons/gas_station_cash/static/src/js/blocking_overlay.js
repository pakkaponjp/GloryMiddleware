/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * BlockingOverlay Component
 *
 * Handles 3 types of overlays:
 * 1. Processing - Shows spinner during operations
 * 2. Error     - Shows error message (e.g., Glory connection failed)
 * 3. Collection Summary - Shows breakdown of cash moved to collection box
 */
export class BlockingOverlay extends Component {
    static template = "gas_station_cash.BlockingOverlay";

    setup() {
        console.log("[BlockingOverlay] Setup starting...");

        this.rpc = useService("rpc");
        this.posOverlay = useService("pos_command_overlay");

        // Service state (reactive from service)
        this.state = useState(this.posOverlay.state);

        this._collectionTimer = null;

        onMounted(() => {
            console.log("[BlockingOverlay] Mounted");
            window.__blockingOverlay = this;
        });
    }

    // Watch for collection_complete → auto-close after 3s
    get showCollectionSummary() {
        const visible = this.state.visible && this.state.status === "collection_complete";
        if (visible && !this._collectionTimer) {
            this._collectionTimer = setTimeout(() => {
                this._collectionTimer = null;
                this.onCloseCollectionSummary();
            }, 3000);
        }
        if (!visible && this._collectionTimer) {
            clearTimeout(this._collectionTimer);
            this._collectionTimer = null;
        }
        return visible;
    }

    // ==================== COMPUTED ====================

    get showProcessing() {
        return this.state.visible && this.state.status === "processing";
    }

    get showError() {
        return this.state.visible && this.state.status === "error";
    }

    get showInsufficientReserve() {
        return this.state.visible && this.state.status === "insufficient_reserve";
    }

    // Safe getters that ensure string output
    // Human-readable labels for action codes
    static ACTION_LABELS = {
        'end_of_day':  'End of Day',
        'close_shift': 'Close Shift',
    };

    get actionText() {
        const action = this.state.action;
        const raw = typeof action === 'string' ? action
            : (action && typeof action === 'object')
                ? (action.title || action.message || action.action || 'Processing')
                : 'Processing';
        return BlockingOverlay.ACTION_LABELS[raw] || raw;
    }

    get messageText() {
        const msg = this.state.message;
        if (typeof msg === 'string') return msg;
        if (msg && typeof msg === 'object') {
            return msg.message || msg.text || 'Please wait...';
        }
        return 'Please wait...';
    }

    get subMessageText() {
        const sub = this.state.subMessage;
        if (typeof sub === 'string') return sub;
        return '';
    }

    // Insufficient reserve formatters
    get currentCashFormatted() {
        const amount = this.state.current_cash || 0;
        return amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    get requiredReserveFormatted() {
        const amount = this.state.required_reserve || 0;
        return amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    get shortfallFormatted() {
        const amount = this.state.shortfall || 0;
        return amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Collection summary formatters
    get collectedAmountFormatted() {
        const amount = this.state.collected_amount || 0;
        return amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    get collectedNotes() {
        const breakdown = this.state.collected_breakdown || {};
        return (breakdown.notes || []).sort((a, b) => b.value - a.value);
    }

    get collectedCoins() {
        const breakdown = this.state.collected_breakdown || {};
        return (breakdown.coins || []).sort((a, b) => b.value - a.value);
    }

    // ==================== ERROR HANDLING ====================

    onCloseError() {
        console.log("[BlockingOverlay] Closing error overlay");
        this.posOverlay.hide();
    }

    // ==================== INSUFFICIENT RESERVE HANDLING ====================

    async onCloseInsufficientReserve() {
        console.log("[BlockingOverlay] Closing insufficient reserve overlay");

        try {
            await this.rpc("/gas_station_cash/close_insufficient_reserve", {
                command_id: this.state.command_id,
            });
        } catch (e) {
            console.error("Error closing insufficient reserve:", e);
        }

        this.posOverlay.hide();
    }

    // ==================== COLLECTION SUMMARY ====================

    async onCloseCollectionSummary() {
        console.log("[BlockingOverlay] Closing collection summary");

        try {
            await this.rpc("/gas_station_cash/complete_collection", {
                command_id: this.state.command_id,
                coins_completed: true,
                notes_completed: true,
            });
        } catch (e) {
            console.error("Error completing collection:", e);
        }

        this.posOverlay.hide();
    }
}

// Register component
registry.category("main_components").add("BlockingOverlay", {
    Component: BlockingOverlay,
});