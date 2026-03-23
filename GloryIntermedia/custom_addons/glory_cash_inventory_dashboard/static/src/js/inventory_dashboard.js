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
            autoRefreshClass: 'btn-outline-secondary',
            alertDismissed: false,   // user closed the popup
            alertTimer: null,         // handle for 5-min re-show timer
            wmSettings: {},           // { note_1000: {low, high}, ... }
            cassetteCapacities: { notes: 500, coins: 1200 },  // from odoo.conf
            cassetteInventory:  { notes: [], coins: [] },      // from Option type=3 (I/F cassette only)
        });
        
        // Glory machine denominations — fv = face value in smallest currency unit.
        // Thai Baht denominations — fv = machine face value; fv/100 = THB display.
        // ONLY these fv values will be shown. Any other denomination from the machine is ignored.
        // capacity = stacker max from odoo.conf [glory_machine_config]
        // configKey maps to the odoo.conf key for live-loading via /api/glory/get_stacker_capacities
        this.ALL_NOTES = [
            { value: 100000, valueTHB: 1000, label: "1,000 THB", capacity: 100, wmKey: "note_1000", configKey: "stacker_note_1000_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/note1000.png" },
            { value: 50000,  valueTHB: 500,  label: "500 THB",   capacity: 100, wmKey: "note_500",  configKey: "stacker_note_500_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note500.png"  },
            { value: 10000,  valueTHB: 100,  label: "100 THB",   capacity: 100, wmKey: "note_100",  configKey: "stacker_note_100_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note100.png"  },
            { value: 5000,   valueTHB: 50,   label: "50 THB",    capacity: 100, wmKey: "note_50",   configKey: "stacker_note_050_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note50.png"   },
            { value: 2000,   valueTHB: 20,   label: "20 THB",    capacity: 100, wmKey: "note_20",   configKey: "stacker_note_020_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/note20.png"   },
        ];

        this.ALL_COINS = [
            { value: 1000, valueTHB: 10,   label: "10 THB",   capacity: 200, wmKey: "coin_10",   configKey: "stacker_coin_10_capacity",  img: "/glory_cash_inventory_dashboard/static/img/denominations/coin10.jpg"  },
            { value: 500,  valueTHB: 5,    label: "5 THB",    capacity: 200, wmKey: "coin_5",    configKey: "stacker_coin_5_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin5.jpg"   },
            { value: 200,  valueTHB: 2,    label: "2 THB",    capacity: 200, wmKey: "coin_2",    configKey: "stacker_coin_2_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin2.jpg"   },
            { value: 100,  valueTHB: 1,    label: "1 THB",    capacity: 200, wmKey: "coin_1",    configKey: "stacker_coin_1_capacity",   img: "/glory_cash_inventory_dashboard/static/img/denominations/coin1.jpg"   },
            { value: 50,   valueTHB: 0.50, label: "0.50 THB", capacity: 200, wmKey: "coin_050",  configKey: "stacker_coin_050_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/coin050.jpg" },
            { value: 25,   valueTHB: 0.25, label: "0.25 THB", capacity: 200, wmKey: "coin_025",  configKey: "stacker_coin_025_capacity", img: "/glory_cash_inventory_dashboard/static/img/denominations/coin025.jpg" },
        ];
        
        onWillStart(async () => {
            await this.loadBranchType();
            await this.loadCapacities();
            await this.loadCassetteCapacities();
            await this.loadChangeAllowedNotes();
            await this.loadWarningLevels();
            await this.loadWatermarkSettings();
            await this.loadInventory();
            await this.loadCassetteInventory();
        });
    }


    dismissAlert() {
        // User closed popup — hide it and re-show after 5 minutes
        this.state.alertDismissed = true;
        if (this.state.alertTimer) clearTimeout(this.state.alertTimer);
        this.state.alertTimer = setTimeout(() => {
            if (this.state.hasWarnings) {
                this.state.alertDismissed = false;
            }
        }, 5 * 60 * 1000);   // 5 minutes
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

    async loadCassetteInventory() {
        try {
            const response = await this.rpc("/api/glory/get_cassette_inventory", {});
            const result = response.result || response;
            if (result && result.data && result.data.cassette) {
                this.state.cassetteInventory = {
                    notes: result.data.cassette.notes || [],
                    coins: result.data.cassette.coins || [],
                };
            }
        } catch (error) {
            console.warn("Could not load cassette inventory", error);
        }
    }

    async loadCassetteCapacities() {
        try {
            const response = await this.rpc("/api/glory/get_cassette_capacities", {});
            const result = response.result || response;
            if (result && result.data) {
                this.state.cassetteCapacities = {
                    notes: result.data.cassette_note_capacity || 500,
                    coins: result.data.cassette_coin_capacity || 1200,
                };
            }
        } catch (error) {
            console.warn("Could not load cassette capacities, using defaults", error);
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


    async loadWatermarkSettings() {
        const WM_KEYS = [
            'note_1000','note_500','note_100','note_50','note_20',
            'coin_10','coin_5','coin_2','coin_1','coin_050','coin_025',
        ];
        try {
            const icpKeys = [];
            WM_KEYS.forEach(k => {
                icpKeys.push(`gas_station_cash.wm_low_${k}`);
                icpKeys.push(`gas_station_cash.wm_high_${k}`);
            });
            const rows = await this.rpc("/web/dataset/call_kw", {
                model: "ir.config_parameter",
                method: "search_read",
                args: [[["key", "in", icpKeys]]],
                kwargs: { fields: ["key", "value"], limit: 50 },
            });
            const map = {};
            (rows || []).forEach(r => { map[r.key] = parseInt(r.value) || 0; });
            const settings = {};
            WM_KEYS.forEach(k => {
                settings[k] = {
                    low:  map[`gas_station_cash.wm_low_${k}`]  || 0,
                    high: map[`gas_station_cash.wm_high_${k}`] || 0,
                };
            });
            this.state.wmSettings = settings;
        } catch (error) {
            console.warn("Could not load watermark settings", error);
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
                await this.loadCassetteInventory();
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
                const rawW = result.data.warnings || [];
                this.state.warnings = rawW.map(w => ({
                    ...w,
                    itemClass: 'inv-alert-popup__item inv-alert-popup__item--' + w.type,
                    iconClass: w.severity === 'critical' ? 'fa fa-times-circle' : 'fa fa-exclamation-circle',
                }));
                this.state.hasWarnings = result.data.hasWarnings || false;
                // Re-show popup if new warnings found (unless user dismissed in last 5 min)
                if (this.state.hasWarnings && !this.state.alertTimer) {
                    this.state.alertDismissed = false;
                }
                
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
        this.state.autoRefreshClass = this.state.autoRefresh ? 'btn-success' : 'btn-outline-secondary';
        
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
                wmKey:             note.wmKey,       // required by enrichCylinder
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
                wmKey:             coin.wmKey,       // required by enrichCylinder
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

        const enrichCylinder = (item, defaultCap) => {
            const cap     = item.capacity > 0 ? item.capacity : defaultCap;
            const wm      = this.state.wmSettings[item.wmKey] || { low: 0, high: 0 };
            const wmLow   = wm.low  > 0 ? wm.low  : 0;
            const wmHigh  = wm.high > 0 ? wm.high : 0;

            item.pct          = Math.min(Math.round(item.qty / cap * 100), 100);
            item.pctLabel     = item.pct + '%';
            item.qtyLabel     = item.qty + '/' + cap;
            item.fillStyle    = `height: ${item.pct}%;`;
            item.warningClass    = this.getWarningClass(item.value, item.qty);
            item.warningIcon     = this.getWarningIcon(item.value, item.qty);
            item.changeableClass = (item.changeable && item.qty > 0)
                ? 'inv-changeable inv-changeable--yes'
                : 'inv-changeable inv-changeable--no';

            // Watermark line positions (% from bottom of tube)
            item.wmLowStyle  = wmLow  > 0 ? `bottom: ${Math.min(Math.round(wmLow  / cap * 100), 100)}%;` : '';
            item.wmHighStyle = wmHigh > 0 ? `bottom: ${Math.min(Math.round(wmHigh / cap * 100), 100)}%;` : '';
            item.hasWmLow    = wmLow  > 0;
            item.hasWmHigh   = wmHigh > 0;

            // wmState drives fill color + denom color
            if (wmLow > 0 && item.qty < wmLow) {
                item.wmState = 'near-empty';
            } else if (wmHigh > 0 && item.qty > wmHigh) {
                item.wmState = 'near-full';
            } else {
                item.wmState = '';
            }

            // Pre-compute class strings — avoids complex OWL template expressions
            const wmCls = item.wmState ? ` inv-cylinder__fill--${item.wmState}` : '';
            item.cylinderClass  = `inv-cylinder${item.wmState ? ` inv-cylinder--${item.wmState}` : ''}`;
            item.fillClassNotes = `inv-cylinder__fill inv-cylinder__fill--notes${wmCls}`;
            item.fillClassCoins = `inv-cylinder__fill inv-cylinder__fill--coins${wmCls}`;
        };

        notes.forEach(note => enrichCylinder(note, 100));
        coins.forEach(coin => enrichCylinder(coin, 200));

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
    get processedCassette() {
        // Source: /fcc/api/v1/cash/cassette (InventoryOperation Option type=3)
        // = actual pieces in I/F cassette, NOT stacker data
        const cassetteNotes = this.state.cassetteInventory.notes || [];
        const cassetteCoins = this.state.cassetteInventory.coins || [];
        const noteCap = this.state.cassetteCapacities.notes || 500;
        const coinCap = this.state.cassetteCapacities.coins || 1200;

        // Colour palette per denomination (high → low)
        const NOTE_COLORS = {
            100000: '#1864ab',  // ฿1,000 — deep blue
            50000:  '#862e9c',  // ฿500   — purple
            10000:  '#c92a2a',  // ฿100   — red
            5000:   '#2f9e44',  // ฿50    — green
            2000:   '#e67700',  // ฿20    — orange
        };
        const COIN_COLORS = {
            1000: '#e67700',  // ฿10   — gold
            500:  '#495057',  // ฿5    — dark silver
            200:  '#f59f00',  // ฿2    — amber
            100:  '#868e96',  // ฿1    — silver
            50:   '#c2480a',  // ฿0.50 — copper
            25:   '#e8590c',  // ฿0.25 — light copper
        };

        const formatTHB = (v) => Number.isInteger(v) ? String(v) : v.toFixed(2);

        const buildStacked = (items, colors, cap) => {
            const totalQty  = items.reduce((s, d) => s + (d.qty || 0), 0);
            const pct       = cap > 0 ? Math.min(Math.round(totalQty / cap * 100), 100) : 0;
            const wmState   = pct >= 90 ? 'near-full' : totalQty === 0 ? 'near-empty' : '';

            const segments = items
                .filter(d => (d.qty || 0) > 0)
                .map(d => {
                    const valueTHB = (d.value || 0) / 100;
                    return {
                        color:    colors[d.value] || '#adb5bd',
                        widthPct: Math.min(((d.qty || 0) / cap) * 100, 100),
                        label:    formatTHB(valueTHB),
                        qty:      d.qty || 0,
                        value:    d.value,
                    };
                });

            return { totalQty, cap, pct, pctLabel: pct + '%', wmState, segments };
        };

        return {
            notes: buildStacked(cassetteNotes, NOTE_COLORS, noteCap),
            coins: buildStacked(cassetteCoins, COIN_COLORS, coinCap),
        };
    }
}

InventoryDashboard.template = "glory_cash_inventory_dashboard.InventoryDashboard";

registry.category("actions").add("glory_cash_inventory_dashboard.inventory_dashboard", InventoryDashboard);