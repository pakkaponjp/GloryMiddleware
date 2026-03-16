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
            alerts: [],           // watermark warnings from ICP
            alertDismissed: false,
            alertTimer: null,
        });
        onWillStart(async () => {
            await this._loadSettings();
            await this._loadAlerts();
        });
    }

    async _loadAlerts() {
        // Notes: Bridge API returns value in THB integer (1000, 500, 100, 50, 20)
        // Coins: Bridge API returns value in satang integer (1000=฿10 ... 25=฿0.25)
        //        EXCEPT fractional coins may be decimal THB: 0.50, 0.25
        // Must process notes and coins separately to avoid value collisions
        //   (e.g. value=1000 in notes = ฿1,000 note; value=1000 in coins = ฿10 coin)
        const NOTE_MAP = [
            { satang: 100000, thb: 1000, key: 'note_1000', label: '฿1,000' },
            { satang:  50000, thb:  500, key: 'note_500',  label: '฿500'   },
            { satang:  10000, thb:  100, key: 'note_100',  label: '฿100'   },
            { satang:   5000, thb:   50, key: 'note_50',   label: '฿50'    },
            { satang:   2000, thb:   20, key: 'note_20',   label: '฿20'    },
        ];
        const COIN_MAP = [
            { satang:  1000, thb:  10,   key: 'coin_10',  label: '฿10'   },
            { satang:   500, thb:   5,   key: 'coin_5',   label: '฿5'    },
            { satang:   200, thb:   2,   key: 'coin_2',   label: '฿2'    },
            { satang:   100, thb:   1,   key: 'coin_1',   label: '฿1'    },
            { satang:    50, thb:   0.5, key: 'coin_050', label: '฿0.50' },
            { satang:    25, thb:  0.25, key: 'coin_025', label: '฿0.25' },
        ];

        // Match a raw API value string against a denom list.
        // Tries as-is (satang) first, then as THB x100.
        const matchDenom = (rawStr, denomList) => {
            const f = parseFloat(rawStr);
            if (isNaN(f) || f <= 0) return null;
            const bySatang = denomList.find(d => Math.abs(d.satang - Math.round(f)) < 1);
            if (bySatang) return bySatang;
            const byThb = denomList.find(d => Math.abs(d.satang - Math.round(f * 100)) < 1);
            return byThb || null;
        };

        try {
            const icpKeys = [...NOTE_MAP, ...COIN_MAP].flatMap(d => [
                `gas_station_cash.wm_low_${d.key}`,
                `gas_station_cash.wm_high_${d.key}`,
            ]);
            const rows = await this.rpc("/web/dataset/call_kw", {
                model: "ir.config_parameter",
                method: "search_read",
                args: [[["key", "in", icpKeys]]],
                kwargs: { fields: ["key", "value"], limit: 50 },
            });
            const icp = {};
            (rows || []).forEach(r => { icp[r.key] = parseInt(r.value) || 0; });

            const invResp = await this.rpc("/api/glory/check_float", {
                type: "command", name: "check_float",
                transactionId: `MC-ALERT-${Date.now()}`,
                timestamp: new Date().toISOString(), data: {}
            });
            const avail = invResp?.result?.data?.bridgeApiAvailability
                       || invResp?.data?.bridgeApiAvailability
                       || invResp?.bridgeApiAvailability;
            if (!avail) return;

            // Process notes and coins separately to avoid value collision
            const qtyByKey = {};
            for (const item of (avail.notes || avail.Notes || [])) {
                const denom = matchDenom(String(item.value ?? item.Value ?? 0), NOTE_MAP);
                if (denom) qtyByKey[denom.key] = parseInt(item.qty ?? item.Qty ?? item.quantity ?? 0);
            }
            for (const item of (avail.coins || avail.Coins || [])) {
                const denom = matchDenom(String(item.value ?? item.Value ?? 0), COIN_MAP);
                if (denom) qtyByKey[denom.key] = parseInt(item.qty ?? item.Qty ?? item.quantity ?? 0);
            }

            // Build alerts in DENOM_MAP order: notes high→low, then coins high→low
            const alerts = [];
            for (const denom of [...NOTE_MAP, ...COIN_MAP]) {
                if (!(denom.key in qtyByKey)) continue;
                const qty  = qtyByKey[denom.key];
                const low  = icp[`gas_station_cash.wm_low_${denom.key}`]  || 0;
                const high = icp[`gas_station_cash.wm_high_${denom.key}`] || 0;
                if (low > 0 && qty < low) {
                    const sev = qty === 0 ? 'critical' : 'warning';
                    alerts.push({ label: denom.label, qty, threshold: low,
                        type: 'near_empty', severity: sev,
                        itemClass: 'mc-alert-popup__item mc-alert-popup__item--near_empty',
                        iconClass: sev === 'critical' ? 'fa fa-times-circle' : 'fa fa-exclamation-circle',
                        message: `${denom.label}: qty ${qty} below Near Empty (${low})` });
                } else if (high > 0 && qty > high) {
                    alerts.push({ label: denom.label, qty, threshold: high,
                        type: 'near_full', severity: 'warning',
                        itemClass: 'mc-alert-popup__item mc-alert-popup__item--near_full',
                        iconClass: 'fa fa-exclamation-circle',
                        message: `${denom.label}: qty ${qty} above Near Full (${high})` });
                }
            }
            this.state.alerts = alerts;
            if (alerts.length > 0) this.state.alertDismissed = false;
        } catch (e) {
            console.warn("[MachineControl] Could not load alerts:", e);
        }
    }

    dismissAlert() {
        this.state.alertDismissed = true;
        if (this.state.alertTimer) clearTimeout(this.state.alertTimer);
        this.state.alertTimer = setTimeout(() => {
            if (this.state.alerts.length > 0) this.state.alertDismissed = false;
        }, 5 * 60 * 1000);
    }

    async _loadSettings() {
        try {
            // Read directly from ir.config_parameter — reliable regardless of TransientModel state
            const result = await this.rpc("/web/dataset/call_kw", {
                model: "ir.config_parameter",
                method: "search_read",
                args: [[["key", "=", "gas_station_cash.leave_float"]], ["value"]],
                kwargs: { limit: 1 },
            });
            if (result && result.length > 0) {
                const val = result[0].value;
                this.state.leaveFloat = (val === "True" || val === "1" || val === "true");
            } else {
                // Key not set yet → leave_float is off
                this.state.leaveFloat = false;
            }
        } catch (e) {
            console.warn("[MachineControl] _loadSettings failed, defaulting leaveFloat=false", e);
            this.state.leaveFloat = false;
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

    // ── Extract planned_cash from collect response (multiple fallback paths) ──
    // Glory API may return denomination data under different paths depending on
    // firmware version / collection mode. Try all known paths in order.
    _extractPlannedCash(result) {
        // Path 1: bridgeApiResponse.data.planned_cash  (original expected path)
        if (result?.bridgeApiResponse?.data?.planned_cash?.Denomination?.length)
            return result.bridgeApiResponse.data.planned_cash;

        // Path 2: bridgeApiResponse.planned_cash
        if (result?.bridgeApiResponse?.planned_cash?.Denomination?.length)
            return result.bridgeApiResponse.planned_cash;

        // Path 3: data.planned_cash
        if (result?.data?.planned_cash?.Denomination?.length)
            return result.data.planned_cash;

        // Path 4: planned_cash at top level
        if (result?.planned_cash?.Denomination?.length)
            return result.planned_cash;

        // Path 5: bridgeApiResponse.data.Cash (some firmware versions)
        if (result?.bridgeApiResponse?.data?.Cash?.Denomination?.length)
            return result.bridgeApiResponse.data.Cash;

        // Path 6: data.Cash
        if (result?.data?.Cash?.Denomination?.length)
            return result.data.Cash;

        // Nothing found — log for debugging
        console.warn("[MachineControl] _extractPlannedCash: no denomination data found in result:", JSON.stringify(result));
        return null;
    }

    async allCollect() {
        if (!confirm("Collect ALL cash into the collection box?")) return;
        const result = await this.callAPI("collect_all", {}, { silent: true });
        console.log("[DEBUG] collect_all full result:", JSON.stringify(result));
        if (result && result.success) {
            this.notification.add("All cash sent to collection box.", { type: "success" });

            const plannedCash = this._extractPlannedCash(result);
            const breakdown   = this._plannedCashToBreakdown(plannedCash);

            // Guard: do NOT send an empty receipt to the printer — it causes printer error
            if (breakdown.totalSatang <= 0) {
                console.warn("[MachineControl] allCollect: breakdown empty, skipping print to avoid printer error");
                return;
            }

            const now = new Date().toLocaleString("th-TH", {
                day:"2-digit",month:"2-digit",year:"numeric",
                hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false
            });
            this.rpc("/gas_station_cash/print/collect_cash", {
                collect_type:     "all",
                reference:        `COL-${Date.now()}`,
                datetime_str:     now,
                collected_amount: breakdown.totalSatang,
                reserve_kept:     0,
                breakdown:        { notes: breakdown.notes, coins: breakdown.coins },
            }).catch(e => console.warn("[MachineControl] Print collect_all failed:", e));
        } else if (result) {
            this.notification.add(result.message || "Collect All failed.", { type: "danger" });
        }
    }

    async collectCash() {
        if (!confirm("Collect cash and leave float in the machine?")) return;
        const result = await this.callAPI("collect_cash", {}, { silent: true });
        console.log("[DEBUG] collect_cash full result:", JSON.stringify(result));
        if (result && result.success) {
            const float = result.target_float;
            let reserveSatang = 0;
            if (float) {
                const noteTotal = (float.notes || []).reduce((s, n) => s + n.value * n.qty, 0);
                const coinTotal = (float.coins || []).reduce((s, c) => s + c.value * c.qty, 0);
                reserveSatang = noteTotal + coinTotal;
            }
            const msg = reserveSatang > 0
                ? `Cash collected. Float kept: ฿${(reserveSatang / 100).toFixed(2)}`
                : "Cash collected.";
            this.notification.add(msg, { type: "success" });

            const plannedCash     = this._extractPlannedCash(result);
            const breakdown       = this._plannedCashToBreakdown(plannedCash);
            const collectedSatang = Math.max(0, breakdown.totalSatang - reserveSatang);

            // Guard: do NOT send an empty receipt to the printer — it causes printer error
            if (breakdown.totalSatang <= 0) {
                console.warn("[MachineControl] collectCash: breakdown empty, skipping print to avoid printer error");
                return;
            }

            const now = new Date().toLocaleString("th-TH", {
                day:"2-digit",month:"2-digit",year:"numeric",
                hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false
            });
            this.rpc("/gas_station_cash/print/collect_cash", {
                collect_type:     "leave_float",
                reference:        `COL-${Date.now()}`,
                datetime_str:     now,
                collected_amount: collectedSatang,
                reserve_kept:     reserveSatang,
                breakdown:        { notes: breakdown.notes, coins: breakdown.coins },
            }).catch(e => console.warn("[MachineControl] Print collect_cash failed:", e));
        } else if (result) {
            this.notification.add(result.message || "Collect failed.", { type: "danger" });
        }
    }

    _plannedCashToBreakdown(plannedCash) {
        // Convert Glory planned_cash.Denomination (or Cash.Denomination) to notes/coins breakdown
        const notes = [], coins = [];
        let totalSatang = 0;
        for (const d of (plannedCash?.Denomination || [])) {
            const fv  = parseInt(d.fv || 0);
            const qty = parseInt(d.Piece || 0);
            if (fv <= 0 || qty <= 0) continue;
            totalSatang += fv * qty;
            if (d.devid === 1) notes.push({ value: fv, qty });
            else               coins.push({ value: fv, qty });
        }
        return { notes, coins, totalSatang };
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

    // ── Precomputed class strings (OWL cannot handle string concat in t-att-class) ──

    get htlDot0Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-dot' + (p === 0 ? ' htl-current' : '') + (p > 0 ? ' htl-done' : '');
    }
    get htlLine0Class() {
        return 'mc-htl-line' + (this.state.wizardPhase > 0 ? ' htl-done' : '');
    }
    get htlDot1Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-dot' + (p === 1 ? ' htl-current' : '') + (p > 1 ? ' htl-done' : '') + (p < 1 ? ' htl-pending' : '');
    }
    get htlLine1Class() {
        return 'mc-htl-line' + (this.state.wizardPhase > 1 ? ' htl-done' : '');
    }
    get htlDot2Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-dot' + (p === 2 ? ' htl-current' : '') + (p >= 4 ? ' htl-done' : '') + (p < 2 ? ' htl-pending' : '');
    }
    get htlLabel0Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-label' + (p === 0 ? ' htl-current' : '') + (p > 0 ? ' htl-done' : '');
    }
    get htlLabel1Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-label' + (p === 1 ? ' htl-current' : '') + (p > 1 ? ' htl-done' : '') + (p < 1 ? ' htl-pending' : '');
    }
    get htlLabel2Class() {
        const p = this.state.wizardPhase;
        return 'mc-htl-label' + (p === 2 ? ' htl-current' : '') + (p >= 4 ? ' htl-done' : '') + (p < 2 ? ' htl-pending' : '');
    }
    get collectTopClass() {
        return 'mc-collect-section mc-collect-top' + (this.state.leaveFloat ? '' : ' mc-section-disabled');
    }
    get collectBottomClass() {
        return 'mc-collect-section mc-collect-bottom' + (!this.state.leaveFloat ? '' : ' mc-section-disabled');
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