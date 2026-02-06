/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * BlockingOverlay Component - Step-by-Step Collection Box Replacement Wizard
 * 
 * Flow:
 * Step 1: Coins - [Unlock] → Instructions → [Lock]
 * Step 2: Notes - [Unlock] → Instructions → [Lock]
 * Step 3: Done - [Finish]
 */
export class BlockingOverlay extends Component {
    static template = "gas_station_cash.BlockingOverlay";
    
    setup() {
        console.log("🎨 [BlockingOverlay] Setup starting...");
        
        this.rpc = useService("rpc");
        this.posOverlay = useService("pos_command_overlay");
        
        // Service state (reactive from service)
        this.state = useState(this.posOverlay.state);
        
        // Local wizard state
        this.wizard = useState({
            currentStep: 1,       // 1=Coins, 2=Notes, 3=Done
            subStep: "unlock",    // "unlock" or "replace"
            isLoading: false,
            errorMessage: null,
            coinsCompleted: false,
            notesCompleted: false,
        });
        
        onMounted(() => {
            console.log("🎨 [BlockingOverlay] Mounted");
            window.__blockingOverlay = this;
        });
    }
    
    // ==================== COMPUTED ====================
    
    get showProcessing() {
        return this.state.visible && this.state.status === "processing";
    }
    
    get showWizard() {
        return this.state.visible && this.state.status === "collection_complete";
    }
    
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
    
    // ==================== STEP 1: COINS ====================
    
    async onUnlockCoins() {
        console.log("🔓 Unlocking coins...");
        this.wizard.isLoading = true;
        this.wizard.errorMessage = null;
        
        try {
            const result = await this.rpc("/gas_station_cash/unlock_unit", {
                command_id: this.state.command_id,
                target: "coins",
            });
            
            console.log("🔓 Result:", result);
            
            if (result.success) {
                this.wizard.subStep = "replace";
            } else {
                this.wizard.errorMessage = result.error || "Failed to unlock";
            }
        } catch (e) {
            console.error("Error:", e);
            this.wizard.errorMessage = "Error unlocking coin box";
        } finally {
            this.wizard.isLoading = false;
        }
    }
    
    async onLockCoins() {
        console.log("🔒 Locking coins...");
        this.wizard.isLoading = true;
        this.wizard.errorMessage = null;
        
        try {
            const result = await this.rpc("/gas_station_cash/lock_unit", {
                command_id: this.state.command_id,
                target: "coins",
            });
            
            console.log("🔒 Result:", result);
            
            if (result.success) {
                this.wizard.coinsCompleted = true;
                this.wizard.currentStep = 2;
                this.wizard.subStep = "unlock";
            } else {
                this.wizard.errorMessage = result.error || "Failed to lock";
            }
        } catch (e) {
            console.error("Error:", e);
            this.wizard.errorMessage = "Error locking coin box";
        } finally {
            this.wizard.isLoading = false;
        }
    }
    
    // ==================== STEP 2: NOTES ====================
    
    async onUnlockNotes() {
        console.log("🔓 Unlocking notes...");
        this.wizard.isLoading = true;
        this.wizard.errorMessage = null;
        
        try {
            const result = await this.rpc("/gas_station_cash/unlock_unit", {
                command_id: this.state.command_id,
                target: "notes",
            });
            
            console.log("🔓 Result:", result);
            
            if (result.success) {
                this.wizard.subStep = "replace";
            } else {
                this.wizard.errorMessage = result.error || "Failed to unlock";
            }
        } catch (e) {
            console.error("Error:", e);
            this.wizard.errorMessage = "Error unlocking note box";
        } finally {
            this.wizard.isLoading = false;
        }
    }
    
    async onLockNotes() {
        console.log("🔒 Locking notes...");
        this.wizard.isLoading = true;
        this.wizard.errorMessage = null;
        
        try {
            const result = await this.rpc("/gas_station_cash/lock_unit", {
                command_id: this.state.command_id,
                target: "notes",
            });
            
            console.log("🔒 Result:", result);
            
            if (result.success) {
                this.wizard.notesCompleted = true;
                this.wizard.currentStep = 3;
            } else {
                this.wizard.errorMessage = result.error || "Failed to lock";
            }
        } catch (e) {
            console.error("Error:", e);
            this.wizard.errorMessage = "Error locking note box";
        } finally {
            this.wizard.isLoading = false;
        }
    }
    
    // ==================== STEP 3: FINISH ====================
    
    async onFinish() {
        console.log("✅ Finishing...");
        
        try {
            await this.rpc("/gas_station_cash/complete_collection", {
                command_id: this.state.command_id,
                coins_completed: this.wizard.coinsCompleted,
                notes_completed: this.wizard.notesCompleted,
            });
        } catch (e) {
            console.error("Error:", e);
        }
        
        this._resetWizard();
        this.posOverlay.hide();
    }
    
    // ==================== SKIP ====================
    
    async onSkip() {
        console.log("⏭️ Skipping...");
        
        try {
            await this.rpc("/gas_station_cash/skip_unlock", {
                command_id: this.state.command_id,
            });
        } catch (e) {
            console.error("Error:", e);
        }
        
        this._resetWizard();
        this.posOverlay.hide();
    }
    
    // ==================== HELPERS ====================
    
    _resetWizard() {
        this.wizard.currentStep = 1;
        this.wizard.subStep = "unlock";
        this.wizard.isLoading = false;
        this.wizard.errorMessage = null;
        this.wizard.coinsCompleted = false;
        this.wizard.notesCompleted = false;
    }
}

// Register component
registry.category("main_components").add("BlockingOverlay", {
    Component: BlockingOverlay,
});