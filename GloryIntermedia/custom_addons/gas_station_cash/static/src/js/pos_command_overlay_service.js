/** @odoo-module **/

import { registry } from "@web/core/registry";
import { reactive } from "@odoo/owl";

/**
 * POS Command Overlay Service
 * 
 * This service manages the blocking overlay that shows during:
 * 1. POS commands (EndOfDay, CloseShift)
 * 2. Glory connection errors
 * 3. Collection box replacement wizard
 */
export const posCommandOverlayService = {
    dependencies: ["bus_service"],
    
    start(env, { bus_service }) {
        console.log("[PosCommandOverlayService] Starting...");
        
        // Reactive state that components can subscribe to
        const state = reactive({
            visible: false,
            action: "",
            message: "",
            subMessage: "",      // For connection errors
            request_id: "",
            command_id: null,
            status: "processing",  // processing | collection_complete | insufficient_reserve | done | failed | error
            showCloseButton: false,
            
            // Collection complete data
            show_unlock_popup: false,
            collected_amount: 0,
            collected_breakdown: {},
            
            // Insufficient reserve data
            current_cash: 0,
            required_reserve: 0,
            shortfall: 0,
        });
        
        // Get terminal ID from localStorage or default
        const terminalId = window.localStorage.getItem("pos_terminal_id") || "TERM-01";
        const channel = `gas_station_cash:${terminalId}`;
        
        console.log(" [PosCommandOverlayService] Terminal ID:", terminalId);
        console.log(" [PosCommandOverlayService] Channel:", channel);
        
        // Subscribe to the channel using Odoo 17/18 bus_service API
        try {
            if (typeof bus_service.addChannel === 'function') {
                bus_service.addChannel(channel);
                console.log(" [PosCommandOverlayService] Added channel via addChannel()");
            }
            
            if (typeof bus_service.subscribe === 'function') {
                bus_service.subscribe(channel, (payload) => {
                    console.log(" [PosCommandOverlayService] Received via subscribe:", payload);
                    handleNotification(payload);
                });
                console.log(" [PosCommandOverlayService] Subscribed via subscribe()");
            }
        } catch (e) {
            console.error(" [PosCommandOverlayService] Error subscribing:", e);
        }
        
        // Listen to all bus notifications and filter by type
        bus_service.addEventListener("notification", ({ detail: notifications }) => {
            for (const notification of notifications) {
                const type = notification.type || notification[0];
                const payload = notification.payload || notification[1];
                
                if (type === "pos_command" || type === channel) {
                    console.log(" [PosCommandOverlayService] ✅ Matched! Processing payload:", payload);
                    handleNotification(payload);
                }
            }
        });
        
        function handleNotification(payload) {
            if (!payload) return;
            
            const status = payload.status;
            
            console.log("[PosCommandOverlayService] Processing notification, status:", status);
            
            switch (status) {
                case "processing":
                    state.visible = true;
                    state.action = payload.action || "Processing";
                    state.message = payload.message || "Processing...";
                    state.subMessage = "";
                    state.request_id = payload.request_id || "";
                    state.command_id = payload.command_id;
                    state.status = "processing";
                    state.show_unlock_popup = false;
                    state.showCloseButton = false;
                    break;
                    
                case "collection_complete":
                    state.visible = true;
                    state.action = payload.action || "Collection Complete";
                    state.message = payload.message || "Collection complete";
                    state.subMessage = "";
                    state.request_id = payload.request_id || "";
                    state.command_id = payload.command_id;
                    state.status = "collection_complete";
                    state.show_unlock_popup = true;
                    state.collected_amount = payload.collected_amount || 0;
                    state.collected_breakdown = payload.collected_breakdown || {};
                    state.showCloseButton = false;
                    break;
                
                case "insufficient_reserve":
                    state.visible = true;
                    state.action = payload.action || "Insufficient Reserve";
                    state.message = payload.message || "Insufficient reserve cash";
                    state.subMessage = "";
                    state.request_id = payload.request_id || "";
                    state.command_id = payload.command_id;
                    state.status = "insufficient_reserve";
                    state.show_unlock_popup = false;
                    state.showCloseButton = true;
                    // Store reserve info for display
                    state.current_cash = payload.current_cash || 0;
                    state.required_reserve = payload.required_reserve || 0;
                    state.shortfall = payload.shortfall || 0;
                    break;
                    
                case "done":
                case "failed":
                    state.visible = false;
                    state.status = status;
                    state.show_unlock_popup = false;
                    break;
                    
                default:
                    if (payload.visible !== undefined) {
                        state.visible = payload.visible;
                    }
            }
        }
        
        // Expose for debugging
        window.__posOverlayState = state;
        window.__posOverlayService = {
            state,
            show: (arg1, arg2) => showOverlay(arg1, arg2),
            hide: () => hideOverlay(),
            testCollectionComplete: () => {
                state.visible = true;
                state.status = "collection_complete";
                state.action = "Collection Complete";
                state.message = "Cash has been collected";
                state.show_unlock_popup = true;
                state.collected_amount = 12345.67;
                state.collected_breakdown = {
                    notes: [{ value: 1000, qty: 10, fv: 100000 }, { value: 500, qty: 5, fv: 50000 }],
                    coins: [{ value: 10, qty: 20, fv: 1000 }]
                };
            }
        };
        
        /**
         * Show overlay - supports multiple call signatures:
         * 1. show("Action Title", "Message")
         * 2. show({ message: "...", subMessage: "...", showCloseButton: false })
         */
        function showOverlay(arg1, arg2) {
            state.visible = true;
            state.status = "processing";
            state.show_unlock_popup = false;
            
            if (typeof arg1 === 'object' && arg1 !== null) {
                // Object format: show({ message, subMessage, showCloseButton })
                state.action = arg1.action || arg1.title || "Notice";
                state.message = arg1.message || "Please wait...";
                state.subMessage = arg1.subMessage || "";
                state.showCloseButton = arg1.showCloseButton !== false;
                state.status = arg1.status || "error";
                console.log("📍 [PosCommandOverlayService] Show (object):", state.action, state.message);
            } else {
                // String format: show(action, message)
                state.action = arg1 || "Processing";
                state.message = arg2 || "Processing...";
                state.subMessage = "";
                state.showCloseButton = false;
                state.status = "processing";
                console.log("📍 [PosCommandOverlayService] Show (string):", state.action, state.message);
            }
        }
        
        function hideOverlay() {
            state.visible = false;
            state.show_unlock_popup = false;
            state.subMessage = "";
            console.log("📍 [PosCommandOverlayService] Hide");
        }
        
        return {
            state,
            
            /**
             * Show the overlay - supports both formats:
             * show("Action", "Message") 
             * show({ message: "...", subMessage: "...", showCloseButton: false })
             */
            show: showOverlay,
            
            /**
             * Show blocking overlay (alias for compatibility)
             */
            showBlockingOverlay: showOverlay,
            
            /**
             * Hide the overlay
             */
            hide: hideOverlay,
            
            /**
             * Hide blocking overlay (alias for compatibility)
             */
            hideBlockingOverlay: hideOverlay,
            
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