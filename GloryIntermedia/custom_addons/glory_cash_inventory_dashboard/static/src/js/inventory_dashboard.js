/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class InventoryDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.notification = useService("notification");
        this.state = useState({
            loading: false,
            inventory: null,
            availability: null,
            lastUpdate: null,
            autoRefresh: false,
            refreshInterval: null,
            changeAllowedNotes: new Set([100, 500, 1000, 2000, 5000]), // Default
        });
        
        // Define all THB denominations (in satang)
        this.ALL_NOTES = [
            { value: 100000, valueTHB: 1000, label: "1000 THB" },
            { value: 50000, valueTHB: 500, label: "500 THB" },
            { value: 10000, valueTHB: 100, label: "100 THB" },
            { value: 5000, valueTHB: 50, label: "50 THB" },
            { value: 2000, valueTHB: 20, label: "20 THB" },
        ];
        
        this.ALL_COINS = [
            { value: 1000, valueTHB: 10, label: "10 THB" },
            { value: 500, valueTHB: 5, label: "5 THB" },
            { value: 100, valueTHB: 1, label: "1 THB" },
        ];
        
        onWillStart(async () => {
            await this.loadChangeAllowedNotes();
            await this.loadInventory();
        });
    }

    async loadChangeAllowedNotes() {
        try {
            const response = await this.rpc("/api/glory/get_change_allowed_notes", {
                type: "command",
                name: "get_change_allowed_notes",
                timestamp: new Date().toISOString(),
                data: {}
            });
            
            const result = response.result || response;
            if (result && result.data && result.data.allowedNotes) {
                this.state.changeAllowedNotes = new Set(result.data.allowedNotes.map(v => parseInt(v)));
            }
        } catch (error) {
            console.warn("Could not load change allowed notes config, using default", error);
        }
    }

    async loadInventory() {
        this.state.loading = true;
        try {
            const response = await this.rpc("/api/glory/check_float", {
                type: "command",
                name: "check_float",
                transactionId: `CHK-${Date.now()}`,
                timestamp: new Date().toISOString(),
                data: {}
            });
            
            const result = response.result || response;
            if (result && result.data) {
                this.state.inventory = result.data.bridgeApiInventory || null;
                this.state.availability = result.data.bridgeApiAvailability || null;
                this.state.lastUpdate = new Date().toLocaleString();
            }
        } catch (error) {
            this.notification.add(
                `Error loading inventory: ${error.message || "Unknown error"}`,
                { type: "danger" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    toggleAutoRefresh() {
        this.state.autoRefresh = !this.state.autoRefresh;
        
        if (this.state.autoRefresh) {
            this.state.refreshInterval = setInterval(() => {
                this.loadInventory();
            }, 5000); // Refresh every 5 seconds
        } else {
            if (this.state.refreshInterval) {
                clearInterval(this.state.refreshInterval);
                this.state.refreshInterval = null;
            }
        }
    }

    isChangeable(valueSatang) {
        // Coins are always changeable
        if (valueSatang <= 1000) {
            return true;
        }
        // Check if note is in allowed list
        return this.state.changeAllowedNotes.has(valueSatang);
    }

    get processedInventory() {
        if (!this.state.inventory) {
            return { 
                notes: this.ALL_NOTES.map(n => ({ ...n, qty: 0, amount: 0, amountFormatted: "0.00", device: 1, status: 0, changeable: this.isChangeable(n.value) })), 
                coins: this.ALL_COINS.map(c => ({ ...c, qty: 0, amount: 0, amountFormatted: "0.00", device: 1, status: 0, changeable: true })), 
                totals: null 
            };
        }
        
        // Create maps to store actual inventory data
        const notesMap = new Map();
        const coinsMap = new Map();
        
        // Initialize all denominations with 0
        this.ALL_NOTES.forEach(note => {
            notesMap.set(note.value, {
                value: note.value,
                valueTHB: note.valueTHB,
                valueTHBFormatted: note.valueTHB.toFixed(0),
                label: note.label,
                qty: 0,
                amount: 0,
                amountFormatted: "0.00",
                device: 1,
                status: 0,
                changeable: this.isChangeable(note.value)
            });
        });
        
        this.ALL_COINS.forEach(coin => {
            coinsMap.set(coin.value, {
                value: coin.value,
                valueTHB: coin.valueTHB,
                valueTHBFormatted: coin.valueTHB.toFixed(0),
                label: coin.label,
                qty: 0,
                amount: 0,
                amountFormatted: "0.00",
                device: 1,
                status: 0,
                changeable: true // Coins are always changeable
            });
        });
        
        // Process actual inventory data from Bridge API
        if (this.state.inventory.Cash && Array.isArray(this.state.inventory.Cash)) {
            this.state.inventory.Cash.forEach(cashItem => {
                const isNotes = cashItem.type === 1;
                const isCoins = cashItem.type === 2;
                
                if (cashItem.Denomination && Array.isArray(cashItem.Denomination)) {
                    cashItem.Denomination.forEach(denom => {
                        const value = parseFloat(denom.fv || 0); // fv is face value in satang
                        const qty = parseInt(denom.Piece || 0);
                        const status = parseInt(denom.Status || 0);
                        const valueTHB = value / 100;
                        const amount = valueTHB * qty;
                        
                        const item = {
                            value: value,
                            valueTHB: valueTHB,
                            valueTHBFormatted: valueTHB.toFixed(0),
                            label: `${valueTHB.toFixed(0)} THB`,
                            qty: qty,
                            amount: amount,
                            amountFormatted: amount.toFixed(2),
                            device: denom.devid || 1,
                            status: status,
                            changeable: isCoins ? true : this.isChangeable(value)
                        };
                        
                        if (isNotes && notesMap.has(value)) {
                            notesMap.set(value, item);
                        } else if (isCoins && coinsMap.has(value)) {
                            coinsMap.set(value, item);
                        } else if (isNotes || isCoins) {
                            // Unknown denomination, add it anyway
                            const map = isNotes ? notesMap : coinsMap;
                            map.set(value, item);
                        }
                    });
                }
            });
        }
        
        // Fallback: Try direct notes/coins arrays if Bridge API structure differs
        if (notesMap.values().next().value.qty === 0 && coinsMap.values().next().value.qty === 0) {
            if (this.state.inventory.notes && Array.isArray(this.state.inventory.notes)) {
                this.state.inventory.notes.forEach(note => {
                    const value = parseFloat(note.value || 0);
                    const qty = parseInt(note.qty || 0);
                    const valueTHB = value / 100;
                    const amount = valueTHB * qty;
                    
                    if (!notesMap.has(value)) {
                        notesMap.set(value, {
                            value: value,
                            valueTHB: valueTHB,
                            valueTHBFormatted: valueTHB.toFixed(0),
                            label: `${valueTHB.toFixed(0)} THB`,
                            qty: 0,
                            amount: 0,
                            amountFormatted: "0.00",
                            device: 1,
                            status: 0,
                            changeable: this.isChangeable(value)
                        });
                    }
                    
                    const item = notesMap.get(value);
                    item.qty = qty;
                    item.amount = amount;
                    item.amountFormatted = amount.toFixed(2);
                    item.device = note.device || 1;
                    item.status = note.status || 0;
                });
            }
            
            if (this.state.inventory.coins && Array.isArray(this.state.inventory.coins)) {
                this.state.inventory.coins.forEach(coin => {
                    const value = parseFloat(coin.value || 0);
                    const qty = parseInt(coin.qty || 0);
                    const valueTHB = value / 100;
                    const amount = valueTHB * qty;
                    
                    if (!coinsMap.has(value)) {
                        coinsMap.set(value, {
                            value: value,
                            valueTHB: valueTHB,
                            valueTHBFormatted: valueTHB.toFixed(0),
                            label: `${valueTHB.toFixed(0)} THB`,
                            qty: 0,
                            amount: 0,
                            amountFormatted: "0.00",
                            device: 1,
                            status: 0,
                            changeable: true
                        });
                    }
                    
                    const item = coinsMap.get(value);
                    item.qty = qty;
                    item.amount = amount;
                    item.amountFormatted = amount.toFixed(2);
                    item.device = coin.device || 1;
                    item.status = coin.status || 0;
                });
            }
        }
        
        // Convert maps to sorted arrays
        const notes = Array.from(notesMap.values()).sort((a, b) => b.value - a.value);
        const coins = Array.from(coinsMap.values()).sort((a, b) => b.value - a.value);
        
        // Calculate totals
        let notesTotal = notes.reduce((sum, n) => sum + n.amount, 0);
        let coinsTotal = coins.reduce((sum, c) => sum + c.amount, 0);
        
        // Get totals from inventory response if available
        let grandTotal = notesTotal + coinsTotal;
        if (this.state.inventory.totals && this.state.inventory.totals.grand) {
            grandTotal = parseFloat(this.state.inventory.totals.grand) / 100;
        }
        
        // Calculate max quantity for histogram scaling
        const maxNoteQty = Math.max(...notes.map(n => n.qty), 1);
        const maxCoinQty = Math.max(...coins.map(c => c.qty), 1);
        
        // Add histogram bar height percentage to each item
        notes.forEach(note => {
            note.barHeight = maxNoteQty > 0 ? (note.qty / maxNoteQty * 180) : 0;
            note.barHeightStyle = `height: ${note.barHeight}px;`;
        });
        
        coins.forEach(coin => {
            coin.barHeight = maxCoinQty > 0 ? (coin.qty / maxCoinQty * 180) : 0;
            coin.barHeightStyle = `height: ${coin.barHeight}px;`;
        });
        
        return {
            notes: notes,
            coins: coins,
            totals: {
                notes: notesTotal,
                notesFormatted: notesTotal.toFixed(2),
                coins: coinsTotal,
                coinsFormatted: coinsTotal.toFixed(2),
                grand: grandTotal,
                grandFormatted: grandTotal.toFixed(2)
            },
            histogram: {
                maxNoteQty: maxNoteQty,
                maxCoinQty: maxCoinQty
            }
        };
    }
}

InventoryDashboard.template = "glory_cash_inventory_dashboard.InventoryDashboard";

registry.category("actions").add("glory_cash_inventory_dashboard.inventory_dashboard", InventoryDashboard);
