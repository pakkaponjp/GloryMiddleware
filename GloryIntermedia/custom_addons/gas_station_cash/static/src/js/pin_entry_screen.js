/** @odoo-module */

import { Component, useState, useRef, onWillStart, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PinEntryScreen extends Component {
    static template = "gas_station_cash.PinEntryScreen";
    static props = {
        depositType: { type: String, optional: true },
        onConfirm: { type: Function, optional: true },
        onCancel: { type: Function },
        onStatusUpdate: { type: Function },
        onLoginSuccess: { type: Function },
    };

    setup() {
        this.rpc = useService("rpc");

        this.state = useState({
            staffList: [],
            selectedStaff: null,
            pin: "",
            errorMessage: "",
            employeeDetails: {
                employee_id: null,
                external_id: null,
                role: null,
            },
            // Fingerprint identify states:
            // 'idle' | 'scanning' | 'matched' | 'no_match' | 'timeout' | 'error' | 'unavailable'
            fingerprintStatus: "idle",
            fingerprintMatchedName: "",
        });

        this.pinInput = useRef("pinInput");
        this._fingerprintAborted = false;

        this._selectStaff = this._selectStaff.bind(this);
        this._onNumberClick = this._onNumberClick.bind(this);
        this._onBackspace = this._onBackspace.bind(this);
        this._onClear = this._onClear.bind(this);
        this._onConfirmPin = this._onConfirmPin.bind(this);
        this._onCancelPin = this._onCancelPin.bind(this);
        this._onBackToStaffList = this._onBackToStaffList.bind(this);

        onWillStart(async () => {
            await this._fetchStaffList();
        });

        onWillUnmount(() => {
            // Abort any in-progress fingerprint scan when leaving this screen
            this._fingerprintAborted = true;
        });
    }

    // =========================================================================
    // GETTERS
    // =========================================================================

    get depositTypeName() {
        const names = {
            oil: "Oil Sales",
            engine_oil: "Engine Oil Sales",
            rental: "Rental",
            coffee_shop: "Coffee Shop",
            convenient_store: "Convenient Store",
            deposit_cash: "Replenish Cash",
            exchange_cash: "Exchange Cash",
            withdrawal: "Withdrawal",
        };
        return names[this.props.depositType] || this.props.depositType || "Deposit";
    }

    // =========================================================================
    // FETCH STAFF
    // =========================================================================

    async _fetchStaffList() {
        try {
            console.log("[PinEntry] Fetching staff list for deposit type:", this.props.depositType);

            const res = await this.rpc(
                "/gas_station_cash/get_staff_by_deposit_type",
                { deposit_type: this.props.depositType }
            );

            this.state.staffList = res.staff_list || [];
            this.state.errorMessage = "";
            console.log("[PinEntry] Staff list fetched:", this.state.staffList.length, "members");

            // Start fingerprint identify after staff list is ready
            this._startFingerprintIdentify();

        } catch (error) {
            console.error("[PinEntry] Error fetching staff list:", error);
            this.state.errorMessage = "Failed to load staff list";
            this.state.staffList = [];
        }
    }

    // =========================================================================
    // FINGERPRINT IDENTIFY
    // =========================================================================

    async _startFingerprintIdentify() {
        // ── Health check: fingerprint_in_use + scanner connected ─────────
        try {
            const health = await this.rpc("/gas_station_cash/fingerprint/health", {});
            if (!health.connected) {
                console.warn("[FP Identify] Scanner unavailable:", health.message);
                this.state.fingerprintStatus = "unavailable";
                this.props.onStatusUpdate("Fingerprint disconnected. Please select staff manually.");
                return;
            }
        } catch (e) {
            console.warn("[FP Identify] Health check failed — skipping fingerprint.", e);
            this.state.fingerprintStatus = "unavailable";
            this.props.onStatusUpdate("Fingerprint disconnected. Please select staff manually.");
            return;
        }

        // Build candidates — only staff who have a fingerprint template enrolled
        const candidates = this.state.staffList
            .filter(s => s.fingerprint_template_b64)
            .map(s => ({
                employee_id:   s.employee_id,
                employee_name: s.nickname || s.name,
                template_b64:  s.fingerprint_template_b64,
            }));

        if (candidates.length === 0) {
            console.log("[FP Identify] No enrolled fingerprints — skipping scan");
            this.state.fingerprintStatus = "unavailable";
            return;
        }

        console.log("[FP Identify] Starting scan with", candidates.length, "candidates");
        this.state.fingerprintStatus = "scanning";
        this.props.onStatusUpdate("Please scan your finger or select staff manually");

        try {
            const res = await this.rpc("/gas_station_cash/fingerprint/identify", {
                candidates,
                threshold: 50,
            });

            // Abort if user already navigated away
            if (this._fingerprintAborted) return;

            console.log("[FP Identify] Response:", res);

            if (res.status === "OK" && res.result === "SUCCESS") {
                const match = res.match;
                console.log("[FP Identify] Matched:", match.employee_id, "score:", match.score);

                // Find the matching staff in the list
                const matchedStaff = this.state.staffList.find(
                    s => s.employee_id === match.employee_id
                );

                if (matchedStaff) {
                    this.state.fingerprintStatus = "matched";
                    this.state.fingerprintMatchedName = matchedStaff.nickname || matchedStaff.name;
                    this.props.onStatusUpdate(
                        `Fingerprint matched: ${this.state.fingerprintMatchedName}`
                    );

                    // Short delay so user can see the match feedback, then auto-login
                    await new Promise(r => setTimeout(r, 800));
                    if (this._fingerprintAborted) return;

                    this._autoLoginByFingerprint(matchedStaff);
                } else {
                    console.warn("[FP Identify] Matched employee_id not found in staff list:", match.employee_id);
                    this.state.fingerprintStatus = "no_match";
                }

            } else if (res.status === "TIMEOUT") {
                console.log("[FP Identify] Timeout — no finger placed");
                this.state.fingerprintStatus = "timeout";
                this.props.onStatusUpdate("No fingerprint detected. Please select staff manually.");

            } else {
                // NOT_FOUND, DUPLICATE, or service error
                console.log("[FP Identify] No match or duplicate:", res.result || res.status);
                this.state.fingerprintStatus = "no_match";
                this.props.onStatusUpdate("Fingerprint not recognised. Please select staff manually.");
            }

        } catch (error) {
            if (this._fingerprintAborted) return;
            console.error("[FP Identify] Error:", error);
            this.state.fingerprintStatus = "error";
            // Don't block the user — they can still select staff + PIN
        }
    }

    _autoLoginByFingerprint(staff) {
        // Auto-login: bypass PIN entirely
        const employeeDetails = {
            employee_id: staff.employee_id,
            external_id: staff.external_id,
            role:        staff.role,
            name:        staff.nickname || staff.name,
        };
        console.log("[FP Identify] Auto-login for:", employeeDetails);
        this.props.onStatusUpdate(`Welcome, ${employeeDetails.name}!`);
        this.props.onLoginSuccess(employeeDetails, this.props.depositType);
    }

    // Retry fingerprint scan manually
    async _onRetryFingerprint() {
        this.state.fingerprintStatus = "idle";
        this.state.fingerprintMatchedName = "";
        await this._startFingerprintIdentify();
    }

    // =========================================================================
    // STAFF SELECTION
    // =========================================================================

    _selectStaff(staff) {
        this.state.selectedStaff = staff;
        this.state.pin = "";
        this.state.errorMessage = "";
        // Abort ongoing fingerprint scan when user manually selects staff
        this._fingerprintAborted = true;
        console.log("[PinEntry] Selected staff:", staff);
        this.props.onStatusUpdate("Please enter PIN for " + (staff.nickname || staff.name));
    }

    _onBackToStaffList() {
        this.state.selectedStaff = null;
        this.state.pin = "";
        this.state.errorMessage = "";
        // Re-enable fingerprint for next attempt
        this._fingerprintAborted = false;
        this.props.onStatusUpdate("Select staff member");
    }

    // =========================================================================
    // PIN ENTRY
    // =========================================================================

    _onNumberClick(number) {
        if (this.state.pin.length < 4) {
            this.state.pin += number.toString();
            this.state.errorMessage = "";
            this.props.onStatusUpdate("");
        }
    }

    _onBackspace() {
        this.state.pin = this.state.pin.slice(0, -1);
        this.state.errorMessage = "";
    }

    _onClear() {
        this.state.pin = "";
        this.state.errorMessage = "";
    }

    async _onConfirmPin() {
        if (this.state.pin.length < 4) {
            this.state.errorMessage = "PIN must be 4 digits";
            return;
        }
        if (!this.state.selectedStaff) {
            this.state.errorMessage = "Please select a staff member";
            return;
        }

        try {
            const response = await this.rpc("/gas_station_cash/verify_pin", {
                staff_id: this.state.selectedStaff.id,
                pin:      this.state.pin,
            });

            if (response.success) {
                this.state.employeeDetails = {
                    employee_id: response.employee_details.employee_id,
                    external_id: response.employee_details.external_id,
                    role:        response.employee_details.role,
                    name:        response.employee_details.name || this.state.selectedStaff.name,
                };
                this.state.errorMessage = "";
                this.props.onStatusUpdate("PIN verified successfully!");
                this.props.onLoginSuccess(this.state.employeeDetails, this.props.depositType);
            } else {
                this.state.errorMessage = response.message || "Incorrect PIN";
                this.props.onStatusUpdate("Incorrect PIN. Please try again.");
                this.state.pin = "";
            }
        } catch (error) {
            console.error("[PinEntry] Error verifying PIN:", error);
            this.state.errorMessage = "Error verifying PIN. Please try again.";
            this.props.onStatusUpdate("Error verifying PIN.");
            this.state.pin = "";
        }
    }

    _onCancelPin() {
        this._fingerprintAborted = true;
        this.state.selectedStaff = null;
        this.state.pin = "";
        this.state.errorMessage = "";
        this.props.onStatusUpdate("");
        this.props.onCancel();
    }
}