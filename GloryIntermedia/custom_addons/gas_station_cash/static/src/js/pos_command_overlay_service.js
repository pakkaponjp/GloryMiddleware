/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

export const posCommandOverlayService = {
	dependencies: ["bus_service"],

	start(env, { bus_service }) {
		console.log("🚀 [pos_command_overlay] SERVICE STARTING...");
		
		const terminalId = window.localStorage.getItem("pos_terminal_id") || "TERM-01";
		const channel = `gas_station_cash:${terminalId}`;
		
		console.log("📋 [pos_command_overlay] Config:");
		console.log("   - Terminal ID:", terminalId);
		console.log("   - Channel:", channel);
		console.log("   - Bus service available:", !!bus_service);

		const state = reactive({
			visible: false,
			action: null,
			request_id: null,
			status: null,
			message: "",
		});

		// Log whenever state.visible changes
		const originalVisible = state.visible;
		Object.defineProperty(state, 'visible', {
			get() { return this._visible; },
			set(value) {
				console.log(`🔔 [pos_command_overlay] state.visible changing: ${this._visible} → ${value}`);
				this._visible = value;
			}
		});
		state.visible = originalVisible;

		// ✅ show เฉพาะ action ที่ต้องการจริง ๆ
		const ALLOWED_ACTIONS = new Set(["CloseShift", "EndOfDay"]);

		// ✅ กัน overlay โผล่จากคำสั่งเก่า หลัง refresh/เข้าใหม่
		const LAST_KEY = `gsc_last_pos_req_${terminalId}`;
		const getLastSeen = () => window.localStorage.getItem(LAST_KEY);
		const setLastSeen = (v) => window.localStorage.setItem(LAST_KEY, String(v));

		bus_service.addChannel(channel);
		console.log("✅ [pos_command_overlay] Subscribed to channel:", channel);

		function extractNotifications(detail) {
			if (detail?.notifications && Array.isArray(detail.notifications)) return detail.notifications;
			if (Array.isArray(detail)) return detail;
			return [];
		}

		function normalizeNotif(notif) {
			// ✅ Odoo 17 style: {type, payload, id, channel?}
			if (notif && typeof notif === "object" && !Array.isArray(notif)) {
				return {
					ch: notif.channel || null,
					event: notif.type || notif.event || null,
					payload: notif.payload || null,
				};
			}

			// ✅ legacy: [ch, event, payload]
			if (Array.isArray(notif) && notif.length === 3) {
				return { ch: notif[0], event: notif[1], payload: notif[2] };
			}

			// ✅ legacy: [ch, {type, payload}] or [ch, [event, payload]]
			if (Array.isArray(notif) && notif.length === 2) {
				const ch = notif[0];
				const msg = notif[1];
				if (Array.isArray(msg) && msg.length === 2) return { ch, event: msg[0], payload: msg[1] };
				if (msg && typeof msg === "object") return { ch, event: msg.type || msg.event, payload: msg.payload || msg };
			}

			return null;
		}

		let hideTimer = null;
		function show(payload) {
			console.log("👁️ [pos_command_overlay] SHOW called with:", payload);
			if (hideTimer) {
				clearTimeout(hideTimer);
				hideTimer = null;
			}
			state.visible = true;
			state.action = payload.action || "Processing";
			state.request_id = payload.request_id || payload.command_id || null;
			state.status = payload.status || "processing";
			state.message = payload.message || "Please wait...";
			console.log("✅ [pos_command_overlay] State after show:", {
				visible: state.visible,
				action: state.action,
				message: state.message
			});
		}

		function hideWithDelay(ms = 3000) {
			console.log(`⏰ [pos_command_overlay] Will hide in ${ms}ms`);
			if (hideTimer) clearTimeout(hideTimer);
			hideTimer = setTimeout(() => {
				console.log("🙈 [pos_command_overlay] HIDING overlay now");
				state.visible = false;
				state.action = null;
				state.request_id = null;
				state.status = null;
				state.message = "";
				hideTimer = null;
			}, ms);
		}

		bus_service.addEventListener("notification", ({ detail }) => {
			console.log("📬 [pos_command_overlay] Notification event received!");
			console.log("   Detail:", detail);
			
			const notifications = extractNotifications(detail);
			console.log(`   Extracted ${notifications.length} notification(s)`);

			for (const raw of notifications) {
				console.log("   Processing raw notification:", raw);
				
				const n = normalizeNotif(raw);
				if (!n) {
					console.log("   ⚠️ Could not normalize, skipping");
					continue;
				}

				const { ch, event, payload } = n;
				console.log("   Normalized:", { ch, event, payload });

				// channel อาจเป็น null ใน object style → ให้ผ่านได้
				if (ch && ch !== channel) {
					console.log(`   ⏭️ Wrong channel (expected ${channel}, got ${ch})`);
					continue;
				}
				
				if (event !== "pos_command") {
					console.log(`   ⏭️ Wrong event type (expected pos_command, got ${event})`);
					continue;
				}
				
				if (!payload) {
					console.log("   ⚠️ No payload!");
					continue;
				}

				// ✅ กรอง action
				if (payload.action && !ALLOWED_ACTIONS.has(payload.action)) {
					console.log(`   ⏭️ Action not allowed: ${payload.action}`);
					continue;
				}

				const st = payload.status;
				const reqId = payload.request_id || payload.command_id || null;

				console.log("✅ [pos_command_overlay] VALID notification received!");
				console.log("   Action:", payload.action);
				console.log("   Status:", st);
				console.log("   Request ID:", reqId);
				console.log("   Message:", payload.message);

				if (st === "processing" || st === "received") {
					// ✅ กัน "processing เก่าค้าง" โผล่ตอนเข้า app/refresh
					if (reqId && reqId === getLastSeen()) {
						console.log("   ⏭️ Already seen this request, skipping");
						continue;
					}
					if (reqId) setLastSeen(reqId);

					console.log("   → Calling show()");
					show(payload);
				} else if (st === "done" || st === "failed") {
					console.log("   → Calling show() then hideWithDelay(3000)");
					show(payload);
					hideWithDelay(3000);
				} else {
					console.log("   → Updating message/status only");
					if (payload.message) state.message = payload.message;
					if (payload.status) state.status = payload.status;
				}
			}
		});

		console.log("✅ [pos_command_overlay] Service started successfully");
		console.log("   State object:", state);
		console.log("   Initial visible:", state.visible);

		return { state, channel };
	},
};

registry.category("services").add("pos_command_overlay", posCommandOverlayService);