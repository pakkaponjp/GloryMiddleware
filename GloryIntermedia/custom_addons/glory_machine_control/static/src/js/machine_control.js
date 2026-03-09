/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { xml } from "@odoo/owl";

export class MachineControl extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            inventory: null,
            status: null,
            wizardPhase: 0,  // 0=idle, 1=waiting lock note, 2=waiting lock coin, 3=waiting lock coin confirm, 4=complete
            leaveFloat: false,  // read from gas_station_cash settings
        });
        onWillStart(async () => {
            await this._loadSettings();
        });
    }

    async _loadSettings() {
        try {
            const result = await this.rpc("/web/dataset/call_kw", {
                model: "res.config.settings",
                method: "search_read",
                args: [[],  ["gas_leave_float"]],
                kwargs: { limit: 1, order: "id desc" },
            });
            if (result && result.length > 0) {
                this.state.leaveFloat = result[0].gas_leave_float || false;
            } else {
                // No settings record yet — default to true (safe: button enabled)
                this.state.leaveFloat = true;
            }
        } catch (e) {
            // Field not found or RPC error — default to true so button is usable
            console.warn("[MachineControl] _loadSettings failed, defaulting leaveFloat=true", e);
            this.state.leaveFloat = true;
        }
    }

    async callAPI(endpoint, data = {}, { silent = false } = {}) {
        this.state.loading = true;
        try {
            const response = await this.rpc(`/api/glory/${endpoint}`, {
                type: "command",
                name: endpoint,
                transactionId: `CMD-${Date.now()}`,
                timestamp: new Date().toISOString(),
                data: data
            });

            // Handle JSON-RPC wrapped response
            const result = response.result || response;
            const payload = (result && result.data) ? result.data : result;

            if (!silent) {
                if (payload && payload.success) {
                    this.notification.add(
                        payload.message || "Operation completed successfully",
                        { type: "success" }
                    );
                } else if (payload) {
                    this.notification.add(
                        payload.message || "Operation failed",
                        { type: "danger" }
                    );
                }
            }
            return payload || null;
        } catch (error) {
            if (!silent) {
                this.notification.add(
                    `Error: ${error.message || "Unknown error"}`,
                    { type: "danger" }
                );
            }
            return null;
        } finally {
            this.state.loading = false;
        }
    }









    // ── All Units Wizard ──────────────────────────────────
    // Phase 0: idle  → press "Unlock All" → phase 1
    // Phase 1: notes unlocked, waiting for user to replace & press "Lock Note"
    // Phase 2: locking notes + unlocking coins, waiting for user to replace & press "Lock Coin"
    // Phase 3: (internal transition) → phase 4
    // Phase 4: complete

    async wizardStartUnlockAll() {
        // Step 1: unlock coins only
        const result = await this.callAPI("unlock_unit", { target: "coins" });
        if (result !== null) this.state.wizardPhase = 1;
    }

    async wizardLockCoinsAndUnlockNotes() {
        // Step 2: lock coins then immediately unlock notes
        const r1 = await this.callAPI("lock_unit", { target: "coins" });
        if (r1 === null) return;
        const r2 = await this.callAPI("unlock_unit", { target: "notes" });
        if (r2 !== null) this.state.wizardPhase = 2;
    }

    async wizardLockNotesFinish() {
        // Step 3: lock notes → complete
        const result = await this.callAPI("lock_unit", { target: "notes" });
        if (result !== null) this.state.wizardPhase = 4;
    }

    wizardPhaseReset() { this.state.wizardPhase = 0; }

    async getInventory() {
        const result = await this.callAPI("check_float", {});
        if (result && result.bridgeApiInventory) {
            this.state.inventory = result.bridgeApiInventory;
        }
    }

    async lockUnits() {
        await this.callAPI("lock_units", { target: "all" });
    }

    async unlockUnits() {
        await this.callAPI("unlock_units", { target: "all" });
    }





    async unlockNotes() {
        await this.callAPI("unlock_unit", { target: "notes" });
    }

    async lockNotes() {
        await this.callAPI("lock_unit", { target: "notes" });
    }

    async unlockCoins() {
        await this.callAPI("unlock_unit", { target: "coins" });
    }

    async lockCoins() {
        await this.callAPI("lock_unit", { target: "coins" });
    }

    async allCollect() {
        if (!confirm("Collect ALL cash into the collection box?")) return;
        // silent=true — we build the notification ourselves (no double-message)
        const result = await this.callAPI("collect_all", {}, { silent: true });
        if (result && result.success) {
            this.notification.add("All cash sent to collection box.", { type: "success" });
        } else if (result) {
            this.notification.add(result.message || "Collect All failed.", { type: "danger" });
        }
    }

    async collectCash() {
        if (!confirm("Collect cash and leave float in the machine?")) return;
        // silent=true — we build the notification with float amount detail
        const result = await this.callAPI("collect_cash", {}, { silent: true });
        if (result && result.success) {
            const float = result.target_float;
            let msg = "Cash collected.";
            if (float) {
                const noteTotal = (float.notes || []).reduce((s, n) => s + n.value * n.qty, 0);
                const coinTotal = (float.coins || []).reduce((s, c) => s + c.value * c.qty, 0);
                const totalTHB = ((noteTotal + coinTotal) / 100).toFixed(2);
                msg += ` Float kept: ฿${totalTHB}`;
            }
            this.notification.add(msg, { type: "success" });
        } else if (result) {
            this.notification.add(result.message || "Collect failed.", { type: "danger" });
        }
    }

    async openExitCover() {
        await this.callAPI("open_exit_cover", {});
    }

    async closeExitCover() {
        await this.callAPI("close_exit_cover", {});
    }

    async resetMachine() {
        if (!confirm("Reset the machine? This will clear error states and return to idle.")) return;
        await this.callAPI("reset", {});
    }








    

    

    
    get formattedInventory() {
        if (!this.state.inventory) {
            return "";
        }
        return JSON.stringify(this.state.inventory, null, 2);
    }
    
    get formattedStatus() {
        if (!this.state.status) {
            return "";
        }
        return JSON.stringify(this.state.status, null, 2);
    }
    
    get processedNotes() {
        if (!this.state.inventory || !this.state.inventory.notes) {
            return [];
        }
        return this.state.inventory.notes
            .filter(note => note.qty > 0 && note.status === 2)
            .map(note => ({
                value: note.value,
                valueTHB: (note.value / 100).toFixed(2),
                qty: note.qty,
                amount: note.amount,
                amountTHB: (note.amount / 100).toFixed(2),
                status: note.status
            }))
            .sort((a, b) => b.value - a.value);
    }
    
    get processedCoins() {
        if (!this.state.inventory || !this.state.inventory.coins) {
            return [];
        }
        return this.state.inventory.coins
            .filter(coin => coin.qty > 0 && coin.status === 2)
            .map(coin => ({
                value: coin.value,
                valueTHB: (coin.value / 100).toFixed(2),
                qty: coin.qty,
                amount: coin.amount,
                amountTHB: (coin.amount / 100).toFixed(2),
                status: coin.status
            }))
            .sort((a, b) => b.value - a.value);
    }
    
    get totalNotes() {
        if (!this.state.inventory || !this.state.inventory.totals) {
            return 0;
        }
        return (this.state.inventory.totals.notes / 100).toFixed(2);
    }
    
    get totalCoins() {
        if (!this.state.inventory || !this.state.inventory.totals) {
            return 0;
        }
        return (this.state.inventory.totals.coins / 100).toFixed(2);
    }
    
    get grandTotal() {
        if (!this.state.inventory || !this.state.inventory.totals) {
            return 0;
        }
        return (this.state.inventory.totals.grand / 100).toFixed(2);
    }
}

MachineControl.template = "glory_machine_control.MachineControl";

registry.category("actions").add("machine_control", MachineControl);