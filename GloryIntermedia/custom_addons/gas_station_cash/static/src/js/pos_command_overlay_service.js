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
      if (detail?.notifications && Array.isArray(detail.notifications)) return detail.notifications;
      if (Array.isArray(detail)) return detail;
      return [];
    }

    function normalizeNotif(notif) {
      // Odoo 17: {type, payload, id, channel?}
      if (notif && typeof notif === "object" && !Array.isArray(notif)) {
        return {
          ch: notif.channel || null,
          event: notif.type || notif.event || null,
          payload: notif.payload || null,
        };
      }

      // legacy: [ch, event, payload]
      if (Array.isArray(notif) && notif.length === 3) {
        return { ch: notif[0], event: notif[1], payload: notif[2] };
      }

      // legacy: [ch, {type, payload}] OR [ch, [event,payload]]
      if (Array.isArray(notif) && notif.length === 2) {
        const ch = notif[0];
        const msg = notif[1];
        if (Array.isArray(msg) && msg.length === 2) return { ch, event: msg[0], payload: msg[1] };
        if (msg && typeof msg === "object") return { ch, event: msg.type || msg.event, payload: msg.payload || msg };
      }

      return null;
    }

    bus_service.addEventListener("notification", ({ detail }) => {
      const notifications = extractNotifications(detail);

      for (const notif of notifications) {
        const n = normalizeNotif(notif);
        if (!n) continue;

        const { ch, event, payload } = n;

        // Check channel and event type
        if (ch && ch !== channel) continue;
        if (event !== "pos_command") continue;
        if (!payload) continue;

        console.log("[pos_command_overlay] ✅ Received:", payload);

        const st = payload.status;

        if (st === "processing" || st === "received") {
          state.visible = true;
          state.action = payload.action || "Processing";
          state.request_id = payload.request_id || payload.command_id || null;
          state.status = st;
          state.message = payload.message || "Please wait...";
        } else if (st === "done" || st === "failed") {
          // ถ้าคุณอยากให้หน่วง 3 วิ ก่อนปิด ค่อยเพิ่ม setTimeout ตรงนี้ได้
          state.visible = false;
          state.action = null;
          state.request_id = null;
          state.status = null;
          state.message = "";
        } else {
          // update กลางทาง
          if (payload.message) state.message = payload.message;
          if (payload.status) state.status = payload.status;
        }
      }
    });

    // ให้ชัวร์ว่ารถ bus เริ่มทำงาน
    bus_service.start();

    return { state, channel };
  },
};

registry.category("services").add("pos_command_overlay", posCommandOverlayService);
