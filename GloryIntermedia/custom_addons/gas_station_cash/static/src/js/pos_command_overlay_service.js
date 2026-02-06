/** @odoo-module **/

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";

/**
 * POS Command Overlay Service
 * 
 * This service manages the blocking overlay that shows during POS commands
 * like EndOfDay and CloseShift. It listens to bus notifications and updates
 * the overlay state accordingly.
 */
export const posCommandOverlayService = {
    dependencies: ["bus_service"],
    
    start(env, { bus_service }) {
        console.log("🚀 [PosCommandOverlayService] Starting...");
        
        // Reactive state that components can subscribe to
        const state = reactive({
            visible: false,
            action: "",
            message: "",
            request_id: "",
            command_id: null,
            status: "processing",  // processing | collection_complete | done | failed
            
            // Collection complete data
            show_unlock_popup: false,
            collected_amount: 0,
            collected_breakdown: {},
        });
        
        // Get terminal ID from localStorage or default
        const terminalId = window.localStorage.getItem("pos_terminal_id") || "TERM-01";
        const channel = `gas_station_cash:${terminalId}`;
        
        console.log("📡 [PosCommandOverlayService] Terminal ID:", terminalId);
        console.log("📡 [PosCommandOverlayService] Channel:", channel);
        
        // Subscribe to the channel using Odoo 17/18 bus_service API
        try {
            // Method 1: addChannel (Odoo 17+)
            if (typeof bus_service.addChannel === 'function') {
                bus_service.addChannel(channel);
                console.log("📡 [PosCommandOverlayService] Added channel via addChannel()");
            }
            
            // Method 2: subscribe (older API)
            if (typeof bus_service.subscribe === 'function') {
                bus_service.subscribe(channel, (payload) => {
                    console.log("📨 [PosCommandOverlayService] Received via subscribe:", payload);
                    handleNotification(payload);
                });
                console.log("📡 [PosCommandOverlayService] Subscribed via subscribe()");
            }
        } catch (e) {
            console.error("📡 [PosCommandOverlayService] Error subscribing:", e);
        }
        
        // Listen to all bus notifications and filter by type
        bus_service.addEventListener("notification", ({ detail: notifications }) => {
            console.log("📨 [PosCommandOverlayService] Raw notifications received:", notifications);
            
            for (const notification of notifications) {
                // Handle different notification formats
                const type = notification.type || notification[0];
                const payload = notification.payload || notification[1];
                
                console.log("📨 [PosCommandOverlayService] Processing:", { type, payload });
                
                // Check if this is our notification
                if (type === "pos_command" || type === channel) {
                    console.log("📨 [PosCommandOverlayService] ✅ Matched! Processing payload:", payload);
                    handleNotification(payload);
                }
            }
        });
        
        function handleNotification(payload) {
            if (!payload) {
                console.log("⚠️ [PosCommandOverlayService] Empty payload, ignoring");
                return;
            }
            
            const status = payload.status;
            
            console.log("🔄 [PosCommandOverlayService] Processing notification");
            console.log("   Status:", status);
            console.log("   Action:", payload.action);
            console.log("   Message:", payload.message);
            console.log("   Command ID:", payload.command_id);
            
            switch (status) {
                case "processing":
                    // Show processing overlay
                    state.visible = true;
                    state.action = payload.action || "Processing";
                    state.message = payload.message || "Processing...";
                    state.request_id = payload.request_id || "";
                    state.command_id = payload.command_id;
                    state.status = "processing";
                    state.show_unlock_popup = false;
                    console.log("📍 [PosCommandOverlayService] ✅ Showing processing overlay");
                    break;
                    
                case "collection_complete":
                    // Show unlock popup
                    state.visible = true;
                    state.action = payload.action || "Collection Complete";
                    state.message = payload.message || "Collection complete";
                    state.request_id = payload.request_id || "";
                    state.command_id = payload.command_id;
                    state.status = "collection_complete";
                    state.show_unlock_popup = true;
                    state.collected_amount = payload.collected_amount || 0;
                    state.collected_breakdown = payload.collected_breakdown || {};
                    console.log("📍 [PosCommandOverlayService] ✅ Showing unlock popup");
                    console.log("   Collected Amount:", state.collected_amount);
                    console.log("   Breakdown:", state.collected_breakdown);
                    break;
                    
                case "done":
                case "failed":
                    // Hide overlay
                    state.visible = false;
                    state.status = status;
                    state.show_unlock_popup = false;
                    console.log("📍 [PosCommandOverlayService] ✅ Hiding overlay (status:", status, ")");
                    break;
                    
                default:
                    console.log("⚠️ [PosCommandOverlayService] Unknown status:", status);
                    // Still try to show if visible flag is set
                    if (payload.visible !== undefined) {
                        state.visible = payload.visible;
                    }
            }
        }
        
        // Expose for debugging
        window.__posOverlayState = state;
        window.__posOverlayService = {
            state,
            show: (action, message) => {
                state.visible = true;
                state.action = action || "Test";
                state.message = message || "Test message";
                state.status = "processing";
            },
            hide: () => {
                state.visible = false;
            },
            testCollectionComplete: () => {
                state.visible = true;
                state.status = "collection_complete";
                state.show_unlock_popup = true;
                state.collected_amount = 12345.67;
                state.collected_breakdown = {
                    notes: [{ value: 1000, qty: 10 }, { value: 500, qty: 5 }],
                    coins: [{ value: 10, qty: 20 }]
                };
            }
        };
        console.log("🔧 [PosCommandOverlayService] Debug: window.__posOverlayService available");
        
        return {
            state,
            
            /**
             * Show the overlay manually
             */
            show(action, message, requestId) {
                state.visible = true;
                state.action = action || "Processing";
                state.message = message || "Processing...";
                state.request_id = requestId || "";
                state.status = "processing";
                state.show_unlock_popup = false;
                console.log("📍 [PosCommandOverlayService] Manual show");
            },
            
            /**
             * Hide the overlay
             */
            hide() {
                state.visible = false;
                state.show_unlock_popup = false;
                console.log("📍 [PosCommandOverlayService] Hide");
            },
            
            /**
             * Update message while visible
             */
            updateMessage(message) {
                state.message = message;
            },
        };
    },
};

// Register the service
registry.category("services").add("pos_command_overlay", posCommandOverlayService);