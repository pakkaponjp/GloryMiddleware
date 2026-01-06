/** @odoo-module **/

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

export const posCommandOverlayService = {
  dependencies: ["bus_service"],

  start(env, { bus_service }) {
    const state = reactive({
      visible: false,
      action: null,
      request_id: null,
      status: null,
      message: "",
    });

    const terminalId = window.localStorage.getItem("pos_terminal_id") || "TERM-01";
    const channel = `gas_station_cash:${terminalId}`;

    console.log("[pos_command_overlay] start service, terminalId=", terminalId, "channel=", channel);

    bus_service.addChannel(channel);

    function extractNotifications(detail) {
      // Odoo บางกรณีส่งเป็น detail.notifications
      if (detail?.notifications && Array.isArray(detail.notifications)) return detail.notifications;
      // บางกรณี detail เองเป็น array
      if (Array.isArray(detail)) return detail;
      return [];
    }

    function normalizeNotif(notif) {
      // ✅ Odoo 17: object {type, payload, id, channel?}
      if (notif && typeof notif === "object" && !Array.isArray(notif)) {
        return {
          ch: notif.channel || null,
          event: notif.type || notif.event || null,
          payload: notif.payload || notif,
        };
      }

      // ✅ legacy array formats
      // 1) [channel, "pos_command", payload]
      // 2) [channel, {type:"pos_command", payload:{...}}]
      // 3) [channel, ["pos_command", payload]]
      if (!Array.isArray(notif)) return null;

      if (notif.length === 3) {
        return { ch: notif[0], event: notif[1], payload: notif[2] };
      }

      if (notif.length === 2) {
        const ch = notif[0];
        const msg = notif[1];
        if (Array.isArray(msg) && msg.length === 2) return { ch, event: msg[0], payload: msg[1] };
        if (msg && typeof msg === "object") return { ch, event: msg.type || msg.event, payload: msg.payload || msg };
      }

      return null;
    }

    bus_service.addEventListener("notification", ({ detail }) => {
      const notifications = extractNotifications(detail);
      console.log("[pos_command_overlay] notifications(raw):", notifications);

      for (const notif of notifications) {
        const n = normalizeNotif(notif);
        if (!n) continue;

        const { ch, event, payload } = n;

        // ถ้า notif มี channel มา ให้ match; ถ้าไม่มี (object style) ให้ถือว่ามาจาก channel ที่เราสมัครไว้
        if (ch && ch !== channel) continue;
        if (event !== "pos_command") continue;

        console.log("[pos_command_overlay] ✅ pos_command payload:", payload);

        const st = payload?.status;
        if (st === "processing" || st === "received") {
          state.visible = true;
          state.action = payload.action || null;
          state.request_id = payload.request_id || payload.command_id || null;
          state.status = st;
          state.message = payload.message || "Processing...";
          console.log("[pos_command_overlay] state.visible => true", payload);
        } else if (st === "done" || st === "failed") {
          state.visible = false;
          state.action = null;
          state.request_id = null;
          state.status = null;
          state.message = "";
        } else {
          console.log("[pos_command_overlay] state.visible => true", payload);
          if (payload?.message) state.message = payload.message;
          if (payload?.status) state.status = payload.status;
        }
      }
    });

    bus_service.start();
    return { state };
  },
};

registry.category("services").add("pos_command_overlay", posCommandOverlayService);
