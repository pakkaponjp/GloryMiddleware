/** @odoo-module */

import { Component, useState, useRef, onWillStart } from "@odoo/owl";
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
            }
        });

        this.pinInput = useRef("pinInput");

        // Bind methods
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
            console.log("Fetching staff list for deposit type:", this.props.depositType);
            
            const res = await this.rpc(
               "/gas_station_cash/get_staff_by_deposit_type",
               { deposit_type: this.props.depositType }
            );
            console.log("Fetching staff list for deposit type:", res.staff_list);

            this.state.staffList = res.staff_list || [];
            this.state.errorMessage = "";

            console.log("Staff list fetched successfully:", this.state.staffList);
        } catch (error) {
            console.error("Error fetching staff list:", error);
            this.state.errorMessage = "Failed to load staff list";
            this.state.staffList = [];
        }
    }

    // =========================================================================
    // STAFF SELECTION
    // =========================================================================

    _selectStaff(staff) {
        this.state.selectedStaff = staff;
        this.state.pin = "";
        this.state.errorMessage = "";
        console.log("Selected staff:", staff);
        this.props.onStatusUpdate("Please enter PIN for " + (staff.nickname || staff.name));
    }

    _onBackToStaffList() {
        console.log("Back to staff list");
        this.state.selectedStaff = null;
        this.state.pin = "";
        this.state.errorMessage = "";
        this.props.onStatusUpdate("Select staff member");
    }

    // =========================================================================
    // PIN ENTRY
    // =========================================================================

    _onNumberClick(number) {
        console.log("Number clicked:", number);
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
        console.log("Confirming PIN:", this.state.pin);
        
        if (this.state.pin.length < 4) {
            this.state.errorMessage = "PIN must be 4 digits";
            console.warn("PIN confirmation failed: PIN too short");
            return;
        }
        
        if (!this.state.selectedStaff) {
            this.state.errorMessage = "Please select a staff member";
            console.warn("PIN confirmation failed: No staff selected");
            return;
        }

        const staffId = this.state.selectedStaff.id;
        const enteredPin = this.state.pin;
        
        try {
            const response = await this.rpc("/gas_station_cash/verify_pin", {
                staff_id: staffId,
                pin: enteredPin,
            });

            if (response.success) {
                console.log("PIN verified successfully:", response);
                this.state.employeeDetails = {
                    employee_id: response.employee_details.employee_id,
                    external_id: response.employee_details.external_id,
                    role: response.employee_details.role,
                    name: response.employee_details.name || this.state.selectedStaff.name,
                };

                this.state.errorMessage = "";
                const depositType = this.props.depositType;
                console.log("Deposit type for confirmation:", depositType);
                this.props.onStatusUpdate("PIN verified successfully!");

                if (this.props.onLoginSuccess) {
                    console.log("checking state.employeeDetails:", this.state.employeeDetails);
                    this.props.onLoginSuccess(this.state.employeeDetails, depositType);
                } else {
                    console.error("onLoginSuccess prop is not defined");
                }

            } else {
                console.warn("PIN confirmation failed: Incorrect PIN");
                this.state.errorMessage = response.message || "Incorrect PIN";
                this.props.onStatusUpdate("Incorrect PIN. Please try again.");
                this.state.pin = "";
            }
        } catch (error) {
            console.error("Error verifying PIN:", error);
            this.state.errorMessage = "Error verifying PIN. Please try again.";
            this.props.onStatusUpdate("Error verifying PIN.");
            this.state.pin = "";
        }
    }

    _onCancelPin() {
        console.log("Canceling PIN entry");
        this.state.selectedStaff = null;
        this.state.pin = "";
        this.state.errorMessage = "";
        this.props.onStatusUpdate("");
        this.props.onCancel();
        console.log("PIN entry cancelled");
    }
}