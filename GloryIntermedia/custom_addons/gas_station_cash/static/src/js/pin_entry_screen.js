/** @odoo-module */

import { Component, useState, useRef, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class PinEntryScreen extends Component {
    static template = "gas_station_cash.PinEntryScreen";
    static props = {
        depositType: { type: String, optional: true },
        onConfirm: { type: Function },
        onCancel: { type: Function },
        onStatusUpdate: { type: Function },
        onLoginSuccess: { type: Function },
    };

    setup() {
        super.setup();
        this.rpc = useService("rpc"); // Use the environment service for context

        this.state = useState({
            staffList: [], // List of staff members, if needed
            selectedStaff: null, // Currently selected staff member, if needed
            pin: "",
            errorMessage: "", // Renamed 'message' to 'errorMessage' for clarity
            // State to hold employee details for the next page
            employeeDetails: {
                employee_id: null,
                external_id: null,
                role: null,
            }
        });
        this.pinInput = useRef("pinInput"); // Reference to the PIN input field

        // Bind methods to the component context
        this._selectStaff = this._selectStaff.bind(this);
        /*this._onNumberClick = this._onNumberClick.bind(this);
        this._onBackspace = this._onBackspace.bind(this);
        this._onConfirmPin = this._onConfirmPin.bind(this);
        this._onCancelPin = this._onCancelPin.bind(this);*/

        onWillStart(async () => {
            await this._fetchStaffList(); // Fetch staff list on component start
        });
    }

    async _fetchStaffList() {
        try {
            console.log("Fetching staff list for deposit type:", this.props.depositType);
            
            const res = await this.rpc(
               "/gas_station_cash/get_staff_by_deposit_type",
               { deposit_type: this.props.depositType }
            );
            console.log("Fetching staff list for deposit type:", res.staff_list);


            this.state.staffList = res.staff_list || [];
            this.state.errorMessage = null;

            console.log("Staff list fetched successfully:", this.state.staffList);
        } catch (error) {
            console.error("Error fetching staff list:", error);
            
            this.state.errorMessage = "Failed to load staff list";
            this.state.staffList = [];
        }
    }

    _selectStaff(staff) {
        this.state.selectedStaff = staff;
        console.log("Selected staff:", staff);
        this.state.staffId = staff.employee_id; // Store selected staff ID
        this.props.onStatusUpdate("Please enter PIN for " + staff.employee_id);
        this.render(); // Re-render to update the UI
    }

    _onPinInput(event) {
        const value = (event.target.value || "").replace(/\D/g, "").substring(0, 4); // Remove non-digit characters
        this.state.pin = value;
        this.props.onStatusUpdate("");
        console.log("PIN input changed:", this.state.pin);
    }

    _onKeyDown(event) {
        if (!(/^\d$/.test(event.key) || ['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'Enter', 'Tab'].includes(event.key))) {
            event.preventDefault(); // Prevent non-digit keys except 'd'
        }
        if (event.key === 'Enter') {
            this._onConfirmPin(); // Confirm PIN on Enter key
        }
    }

    // Method to handle number pad button clicks
    _onNumberClick(number) {
        console.log("Number clicked:", number);
        if (this.state.pin.length < 4) { // Limit PIN length
                this.state.pin += number.toString();
                this.props.onStatusUpdate("");
            }
    }

    // Method to handle backspace button click
    _onBackspace() {
        this.state.pin = this.state.pin.slice(0, -1);
    }

    async _onConfirmPin() {
        console.log("Confirming PIN:", this.state.pin);
        if (this.state.pin.length < 4) {
            this.state.errorMessage = "PIN must be at least 4 digits long";
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
                // Update the employeeDetails state with the response data
                console.log("PIN verified successfully:", response);
                this.state.employeeDetails = {
                    employee_id: response.employee_details.employee_id,
                    external_id: response.employee_details.external_id,
                    role: response.employee_details.role,
                };

                this.state.errorMessage = "PIN verified successfully!";

                const depositType = this.props.depositType;
                console.log("Deposit type for confirmation:", depositType);
                this.props.onStatusUpdate("PIN verified successfully! Proceeding with " + depositType + " deposit.");

                if (this.props.onLoginSuccess) {
                    console.log("checking state.employeeDetails:", this.state.employeeDetails);
                    this.props.onLoginSuccess(this.state.employeeDetails, depositType);
                } else {
                    console.error("onLoginSuccess prop is not defined on PinEntryScreen.");
                }

            } else {
                console.warn("PIN confirmation failed: Incorrect PIN");
                // Incorrect PIN
                this.props.onStatusUpdate("Incorrect PIN. Please try again.");
                this.state.pin = ""; // Clear PIN on error
            }
        } catch (error) {
            console.error("Error verifying PIN:", error);
            this.state.errorMessage = "Error verifying PIN. Please try again.";
            this.props.onStatusUpdate("Error verifying PIN. Please try again.");
        }
    }

    _onCancelPin() {
        console.log("Canceling PIN entry");
        this.props.onCancel();
        this.selectedStaff = null; // Clear selected staff on cancel
        this.state.pin = ""; // Clear PIN input on cancel
        this.props.onStatusUpdate("");
        console.log("PIN entry cancelled");
    }
}
