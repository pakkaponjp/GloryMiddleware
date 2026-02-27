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
            warnings: [],
            hasWarnings: false,
            warningLevels: new Map(), // Map of value_satang -> warning_quantity
            branchType: 'convenience_store',
            savingBranchType: false,
        });
        
        // Glory machine denominations — fv = face value in smallest currency unit.
        // Thai Baht denominations — fv = machine face value; fv/100 = THB display.
        // ONLY these fv values will be shown. Any other denomination from the machine is ignored.
        // capacity = stacker max from odoo.conf [glory_machine_config]
        // configKey maps to the odoo.conf key for live-loading via /api/glory/get_stacker_capacities
        this.ALL_NOTES = [
            { value: 100000, valueTHB: 1000, label: "1,000 THB", capacity: 100, configKey: "stacker_note_1000_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/note1000.png" },
            { value: 50000,  valueTHB: 500,  label: "500 THB",   capacity: 100, configKey: "stacker_note_500_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note500.png"  },
            { value: 10000,  valueTHB: 100,  label: "100 THB",   capacity: 100, configKey: "stacker_note_100_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note100.png"  },
            { value: 5000,   valueTHB: 50,   label: "50 THB",    capacity: 100, configKey: "stacker_note_050_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note50.png"   },
            { value: 2000,   valueTHB: 20,   label: "20 THB",    capacity: 100, configKey: "stacker_note_020_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note20.png"   },
        ];

        this.ALL_COINS = [
            { value: 1000, valueTHB: 10,   label: "10 THB",   capacity: 200, configKey: "stacker_coin_10_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/coin10.jpg"  },
            { value: 500,  valueTHB: 5,    label: "5 THB",    capacity: 200, configKey: "stacker_coin_5_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin5.jpg"   },
            { value: 200,  valueTHB: 2,    label: "2 THB",    capacity: 200, configKey: "stacker_coin_2_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin2.jpg"   },
            { value: 100,  valueTHB: 1,    label: "1 THB",    capacity: 200, configKey: "stacker_coin_1_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin1.jpg"   },
            { value: 50,   valueTHB: 0.50, label: "0.50 THB", capacity: 200, configKey: "stacker_coin_050_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/coin050.jpg" },
            { value: 25,   valueTHB: 0.25, label: "0.25 THB", capacity: 200, configKey: "stacker_coin_025_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/coin025.jpg" },
        ];
        
        onWillStart(async () => {
            await this.loadBranchType();
            await this.loadCapacities();
            await this.loadChangeAllowedNotes();
            await this.loadWarningLevels();
            await this.loadInventory();
        });
    }

    async loadBranchType() {
        try {
            const response = await this.rpc("/api/glory/get_branch_type", {});
            const result = response.result || response;
            if (result && result.data && result.data.branch_type) {
                this.state.branchType = result.data.branch_type;
            }
        } catch (error) {
            console.warn("Could not load branch type, using default", error);
        }
    }

    async loadCapacities() {
        try {
            const response = await this.rpc("/api/glory/get_stacker_capacities", {});
            const result = response.result || response;
            if (result && result.data && result.data.capacities) {
                const caps = result.data.capacities;
                this.ALL_NOTES.forEach(n => {
                    if (caps[n.configKey] !== undefined) n.capacity = parseInt(caps[n.configKey]);
                });
                this.ALL_COINS.forEach(c => {
                    if (caps[c.configKey] !== undefined) c.capacity = parseInt(caps[c.configKey]);
                });
            }
        } catch (error) {
            console.warn("Could not load stacker capacities, using defaults", error);
        }
    }

    async setBranchType(type) {
        if (this.state.savingBranchType || this.state.branchType === type) return;
        this.state.savingBranchType = true;
        try {
            const response = await this.rpc("/api/glory/set_branch_type", { branch_type: type });
            const result = response.result || response;
            if (result && result.success) {
                this.state.branchType = type;
                this.notification.add(
                    `Branch type set to: ${type === 'gas_station' ? 'Gas Station' : 'Convenience Store'}`,
                    { type: "success" }
                );
            } else {
                this.notification.add(result.message || "Failed to save branch type", { type: "danger" });
            }
        } catch (error) {
            this.notification.add(`Error saving branch type: ${error.message || "Unknown error"}`, { type: "danger" });
        } finally {
            this.state.savingBranchType = false;
        }
    }

    async loadWarningLevels() {
        try {
            const response = await this.rpc("/api/glory/get_warning_levels", {
                type: "command",
                name: "get_warning_levels",
                transactionId: `WL-${Date.now()}`,
                timestamp: new Date().toISOString(),
                data: {}
            });
            
            const result = response.result || response;
            if (result && result.data && result.data.warningLevels) {
                const warningMap = new Map();
                result.data.warningLevels.forEach(wl => {
                    if (wl.warningEnabled) {
                        warningMap.set(wl.valueSatang, wl.warningQuantity);
                    }
                });
                this.state.warningLevels = warningMap;
            }
        } catch (error) {
            console.warn("Could not load warning levels", error);
        }
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
                
                // Check warnings after loading inventory
                await this.checkWarnings();
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
    
    async checkWarnings() {
        try {
            const response = await this.rpc("/api/glory/check_inventory_warnings", {
                type: "command",
                name: "check_inventory_warnings",
                transactionId: `WARN-${Date.now()}`,
                timestamp: new Date().toISOString(),
                data: {}
            });
            
            const result = response.result || response;
            
            if (result && result.data) {
                this.state.warnings = result.data.warnings || [];
                this.state.hasWarnings = result.data.hasWarnings || false;
                
                // Show sticky notification if there are critical warnings
                const criticalWarnings = this.state.warnings.filter(w => w.severity === 'critical');
                if (criticalWarnings.length > 0) {
                    this.notification.add(
                        `⚠️ Critical: ${criticalWarnings.length} denomination(s) at critical levels!`,
                        { 
                            type: "danger",
                            sticky: true,
                        }
                    );
                }
            }
        } catch (error) {
            console.error("Error checking warnings:", error);
        }
    }
    
    getWarningClass(valueSatang, qty) {
        // Check if this denomination has a warning level
        const warningQty = this.state.warningLevels.get(valueSatang);
        if (!warningQty) {
            return '';
        }
        
        if (qty === 0) {
            return 'table-danger'; // Empty
        } else if (qty < warningQty * 0.5) {
            return 'table-danger'; // Critical
        } else if (qty < warningQty) {
            return 'table-warning'; // Warning
        }
        return '';
    }
    
    getWarningIcon(valueSatang, qty) {
        const warningQty = this.state.warningLevels.get(valueSatang);
        if (!warningQty) {
            return null;
        }
        
        if (qty === 0) {
            return '🔴'; // Empty
        } else if (qty < warningQty * 0.5) {
            return '⚠️'; // Critical
        } else if (qty < warningQty) {
            return '⚡'; // Warning
        }
        return null;
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
        // Source: cash/availability endpoint (Cash type=4 — Dispensable)
        // = FINAL AVAILABILITY FOR WITHDRAWAL from fcc_route.py
        // Already deduplicated by the API — one entry per denomination, no MAX logic needed.
        const avail = this.state.availability;

        if (!avail) {
            return { 
                notes: this.ALL_NOTES.map(n => ({ ...n, qty: 0, amount: 0, amountFormatted: "0.00", device: 1, status: 0, changeable: this.isChangeable(n.value) })), 
                coins: this.ALL_COINS.map(c => ({ ...c, qty: 0, amount: 0, amountFormatted: "0.00", device: 2, status: 0, changeable: true })), 
                totals: null 
            };
        }
        
        // Whole numbers → "500", decimals → "0.50"
        const formatTHB = (v) => Number.isInteger(v) ? String(v) : v.toFixed(2);

        // Build lookup maps pre-seeded with all known denominations at qty=0.
        const notesMap = new Map();
        const coinsMap = new Map();

        this.ALL_NOTES.forEach(note => {
            notesMap.set(note.value, {
                value:             note.value,
                valueTHB:          note.valueTHB,
                valueTHBFormatted: formatTHB(note.valueTHB),
                label:             note.label,
                img:               note.img || '',
                capacity:          note.capacity || 100,
                qty:               0,
                amount:            0,
                amountFormatted:   "0.00",
                device:            1,
                status:            0,
                changeable:        this.isChangeable(note.value),
            });
        });
        
        this.ALL_COINS.forEach(coin => {
            coinsMap.set(coin.value, {
                value:             coin.value,
                valueTHB:          coin.valueTHB,
                valueTHBFormatted: formatTHB(coin.valueTHB),
                label:             coin.label,
                img:               coin.img || '',
                capacity:          coin.capacity || 200,
                qty:               0,
                amount:            0,
                amountFormatted:   "0.00",
                device:            2,
                status:            0,
                changeable:        true,
            });
        });

        // ── Merge availability data into maps ─────────────────────────────────
        // availability.notes/coins: [{ value: fv, qty, status: 0|1|2, available }]
        // Status: 0=NG, 1=Warn, 2=OK  — already type=4 (Dispensable) only, no duplicates.
        const mergeItems = (items, map, defaultDevice) => {
            (items || []).forEach(item => {
                const fv  = parseInt(item.value  || 0);
                const qty = parseInt(item.qty    || 0);
                const st  = parseInt(item.status || 0);
                const valueTHB = fv / 100;
                const amount   = valueTHB * qty;

                if (fv <= 0) return;

                // Only update known Thai denominations — ignore anything not in ALL_NOTES/ALL_COINS
                if (map.has(fv)) {
                    const entry = map.get(fv);
                    entry.qty             = qty;
                    entry.amount          = amount;
                    entry.amountFormatted = amount.toFixed(2);
                    entry.status          = st;
                }
            });
        };

        mergeItems(avail.notes, notesMap, 1);
        mergeItems(avail.coins, coinsMap, 2);

        // ── Sort high → low denomination ──────────────────────────────────────
        const notes = Array.from(notesMap.values()).sort((a, b) => b.value - a.value);
        const coins = Array.from(coinsMap.values()).sort((a, b) => b.value - a.value);

        // ── Totals — always calculated from our deduplicated data ─────────────
        // Do NOT use inventory.totals.grand from the Bridge API: that value
        // may include double-counted Stock+Dispensable amounts.
        const notesTotal = notes.reduce((sum, n) => sum + n.amount, 0);
        const coinsTotal = coins.reduce((sum, c) => sum + c.amount, 0);
        const grandTotal = notesTotal + coinsTotal;
        
        // ── Cylinder fill % — based on stacker capacity from odoo.conf ─────────
        // SVG donut: r=14, circumference = 2π×14 ≈ 88
        const CIRC = 88;

        notes.forEach(note => {
            const cap         = note.capacity > 0 ? note.capacity : 100;
            note.pct          = Math.min(Math.round(note.qty / cap * 100), 100);
            note.pctLabel     = note.pct + '%';
            note.qtyLabel     = note.qty + '/' + cap;
            note.fillStyle    = `height: ${note.pct}%;`;
            note.warningClass = this.getWarningClass(note.value, note.qty);
            note.warningIcon  = this.getWarningIcon(note.value, note.qty);
        });

        coins.forEach(coin => {
            const cap         = coin.capacity > 0 ? coin.capacity : 200;
            coin.pct          = Math.min(Math.round(coin.qty / cap * 100), 100);
            coin.pctLabel     = coin.pct + '%';
            coin.qtyLabel     = coin.qty + '/' + cap;
            coin.fillStyle    = `height: ${coin.pct}%;`;
            coin.warningClass = this.getWarningClass(coin.value, coin.qty);
            coin.warningIcon  = this.getWarningIcon(coin.value, coin.qty);
        });

        // ── Overall donut stats for summary cards ──────────────────────────────
        const notesTotalQty  = notes.reduce((s, n) => s + n.qty, 0);
        const notesCap       = notes.reduce((s, n) => s + (n.capacity || 100), 0);
        const notesPct       = notesCap > 0 ? Math.min(Math.round(notesTotalQty / notesCap * 100), 100) : 0;
        const notesDashOff   = +(CIRC * (1 - notesPct / 100)).toFixed(2);

        const coinsTotalQty  = coins.reduce((s, c) => s + c.qty, 0);
        const coinsCap       = coins.reduce((s, c) => s + (c.capacity || 200), 0);
        const coinsPct       = coinsCap > 0 ? Math.min(Math.round(coinsTotalQty / coinsCap * 100), 100) : 0;
        const coinsDashOff   = +(CIRC * (1 - coinsPct / 100)).toFixed(2);
        
        return {
            notes,
            coins,
            totals: {
                notes:           notesTotal,
                notesFormatted:  notesTotal.toFixed(2),
                coins:           coinsTotal,
                coinsFormatted:  coinsTotal.toFixed(2),
                grand:           grandTotal,
                grandFormatted:  grandTotal.toFixed(2),
                // Donut chart data for summary cards
                CIRC:            CIRC,
                notesPct:        notesPct,
                notesPctLabel:   notesPct + '%',
                notesQtyLabel:   notesTotalQty + '/' + notesCap,
                notesDashOff:    notesDashOff,
                coinsPct:        coinsPct,
                coinsPctLabel:   coinsPct + '%',
                coinsQtyLabel:   coinsTotalQty + '/' + coinsCap,
                coinsDashOff:    coinsDashOff,
            },
        };
    }
}

InventoryDashboard.template = "glory_cash_inventory_dashboard.InventoryDashboard";

registry.category("actions").add("glory_cash_inventory_dashboard.inventory_dashboard", InventoryDashboard);