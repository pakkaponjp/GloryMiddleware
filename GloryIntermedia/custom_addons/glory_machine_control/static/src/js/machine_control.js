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
            cashInAmount: 0,
            cashOutAmount: 0,
            cashOutNotes: [],
            cashOutCoins: [],
            status: null,
        });
    }

    async callAPI(endpoint, data = {}) {
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
            
            if (result && result.data) {
                if (result.data.success) {
                    this.notification.add(
                        result.data.message || "Operation completed successfully",
                        { type: "success" }
                    );
                } else {
                    this.notification.add(
                        result.data.message || "Operation failed",
                        { type: "danger" }
                    );
                }
                return result.data;
            }
            return result || null;
        } catch (error) {
            this.notification.add(
                `Error: ${error.message || "Unknown error"}`,
                { type: "danger" }
            );
            return null;
        } finally {
            this.state.loading = false;
        }
    }

    async startCashIn() {
        const amount = parseFloat(this.state.cashInAmount);
        if (!amount || amount <= 0) {
            this.notification.add("Please enter a valid amount", { type: "warning" });
            return;
        }
        
        const result = await this.callAPI("cash_sale_start", {
            amountToPay: amount
        });
        
        if (result && result.success) {
            this.state.status = {
                transactionId: result.transactionId || this.props.transactionId,
                message: "Cash-in started. Monitor status below."
            };
        }
    }

    async checkCashInStatus() {
        const result = await this.callAPI("cash_sale_status", {});
        if (result) {
            this.state.status = result;
        }
    }

    async endCashIn() {
        const result = await this.callAPI("cash_sale_end", {});
        if (result) {
            this.state.status = result;
        }
    }

    async executeCashOut() {
        const amount = parseFloat(this.state.cashOutAmount);
        if (!amount || amount <= 0) {
            this.notification.add("Please enter a valid amount", { type: "warning" });
            return;
        }
        
        // Calculate denominations (simplified - you may want to enhance this)
        const notes = this.state.cashOutNotes.filter(n => n.value > 0 && n.qty > 0);
        const coins = this.state.cashOutCoins.filter(c => c.value > 0 && c.qty > 0);
        
        if (notes.length === 0 && coins.length === 0) {
            this.notification.add("Please specify notes or coins to dispense", { type: "warning" });
            return;
        }
        
        const result = await this.callAPI("payout", {
            amount: amount,
            notes: notes,
            coins: coins
        });
        
        if (result) {
            this.state.status = result;
        }
    }

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

    async rebootDevice() {
        if (!confirm("Are you sure you want to reboot the device?")) {
            return;
        }
        await this.callAPI("reboot", {});
    }

    async shutdownDevice() {
        if (!confirm("Are you sure you want to shutdown the device?")) {
            return;
        }
        await this.callAPI("shutdown", {});
    }

    addNote() {
        this.state.cashOutNotes.push({ value: 0, qty: 0 });
    }

    removeNote(index) {
        this.state.cashOutNotes.splice(index, 1);
    }

    addCoin() {
        this.state.cashOutCoins.push({ value: 0, qty: 0 });
    }

    removeCoin(index) {
        this.state.cashOutCoins.splice(index, 1);
    }
    
    removeNoteAt(index) {
        this.removeNote(index);
    }
    
    removeCoinAt(index) {
        this.removeCoin(index);
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

