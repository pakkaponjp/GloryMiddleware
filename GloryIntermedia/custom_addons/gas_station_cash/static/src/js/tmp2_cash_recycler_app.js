/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";
import { PinEntryScreen } from "./pin_entry_screen";
import { OilDepositScreen } from "./oil_deposit_screen";
import { EngineOilDepositScreen } from "./engine_oil_deposit_screen";
import { RentalDepositScreen } from "./rental_deposit_screen";
import { CoffeeShopDepositScreen } from "./coffee_shop_deposit_screen";
import { ConvenientStoreDepositScreen } from "./convenient_store_deposit_screen";
import { DepositCashScreen } from "./deposit_cash_screen";
import { ExchangeCashScreen } from "./exchange_cash_screen";

// The main component for the Cash Recycler app.
// This component will be rendered when the client action is triggered.
export class CashRecyclerApp extends Component {
    static template = "gas_station_cash.CashRecyclerApp";
    static components = {
        PinEntryScreen,
        OilDepositScreen,
        EngineOilDepositScreen,
        RentalDepositScreen,
        CoffeeShopDepositScreen,
        ConvenientStoreDepositScreen,
        DepositCashScreen,
        ExchangeCashScreen,
    };

    static props = {
        action:     { type: Object, optional: true },
        actionId:   { type: Number, optional: true },
        className:  { type: String, optional: true },
        context:    { type: Object, optional: true },
        params:     { type: Object, optional: true },
        name:       { type: String, optional: true },
        displayName:{ type: String, optional: true },
    };

    setup() {
        // Create a map of technical names to translatable
        this._t = _t;
        this.session = session;

        // Setup multi-language support
        const primaryLang = this.session.user_context.lang || "en_US";
        const defaultSecondaryLang = primaryLang.startsWith('th') ? 'en_US' : 'th_TH';

        // Map deposit types to user-friendly names
        this.depositTypeNames = {
            oil: _t("Oil Sales"),
            engine_oil: _t("Engine Oil Sales"),
            rental: _t("Rental"),
            coffee_shop: _t("Coffee Shop Sales"),
            convenient_store: _t("Convenient Store Sales"),
            exchange_cash: _t("Exchange Notes and Coins"),
            deposit_cash: _t("Deposit Cash"),
        };

        // State to manage the current screen and API status
        this.state = useState({
            gloryApiStatus: "disconnected",      // connected | disconnected | connecting
            statusMessage: _t("Ready"),          // Detailed status message
            currentScreen: "mainMenu",           // 'mainMenu', 'pinEntry', etc.
            selectedDepositType: null,           // Stores the type of deposit selected
            isFullScreen: false,                 // Tracks if the app is in full-screen mode
            staffList: [],                       // optional, safe default
            employeeDetails: null,               // safe default
        });

        // Determine secondary language based on primary language
        this.getSecondaryTranslation = (englishText) => {
            return getSecondaryTranslation(englishText, this.state.secondaryLang);
        };

        // Immediately check API status on setup to get an initial state for the heartbeat icon
        this.checkGloryApiStatus();
    }

    // A getter to dynamically select the correct component
    get activeScreen() {
        console.log("ActiveScreeen() Current screen:", this.state.currentScreen);
        switch (this.state.currentScreen) {
            case 'pinEntry':
                return {
                    Component: PinEntryScreen,
                    props: {
                        staffList: this.state.staffList,
                        depositType: this.state.selectedDepositType,
                        onLoginSuccess: this.onLoginSuccess.bind(this),
                        onCancel: this._onHome.bind(this),            // or another cancel handler
                        onConfirm: this._onDepositConfirmed.bind(this), // if you use confirm
                        onStatusUpdate: this._onStatusUpdate.bind(this),
                    }
                };
            case 'oilDeposit':
                return {
                    Component: OilDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        onConfirm: this.onConfirm.bind(this),
                    }
                };
            case 'engine_oilDeposit':
                return {
                    Component: EngineOilDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        confirm: this.onConfirm.bind(this),
                    }
                };
            case 'cofee_shopDeposit':
                return {
                    Component: CoffeeShopDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        confirm: this.onConfirm.bind(this),
                    }
                };
            case 'convenient_sotreDeposit':
                return {
                    Component: ConvenientStoreDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        confirm: this.onConfirm.bind(this),
                    }
                };
            case 'deposit_cashDeposit':
                return {
                    Component: DepositCashScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        confirm: this.onConfirm.bind(this),
                    }
                };
            case 'exchange_cash':
                return {
                    Component: ExchangeCashScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        confirm: this.onConfirm.bind(this),
                        onStatusUpdate: this.onStatusUpdate.bind(this),
                    }
                };
            default:
                return { Component: PinEntryScreen };
        }
    }

    _onSwitchSecondaryLanguage(langCode) {
        this.state.secondaryLang = langCode;
    }

    _onLoginSuccess(employeeDetails, depositType) {
        this.state.employeeDetails = employeeDetails;
        this.state.currentScreen = depositType === "exchange_cash" ? depositType : `${depositType}Deposit`; // To clearify naming, the exchange is not deposit action.
        this.state.statusMessage = "PIN verified. Proceeding to deposit screen.";
        console.log("Navigating to deposit screen:", this.state.currentScreen);
    }

    /**
     * @private
     * Checks the status of the Glory API for the heaengine_oilDepositrtbeat icon.
     * Updates the 'gloryApiStatus' state based on the API response.
     */
    async checkGloryApiStatus() {
        try {
            // Updated API call to the new Odoo proxy endpoint
            const response = await fetch("/gas_station_cash/glory/status");
            if (response.ok) {
                const result = await response.json();
                if (result.overall_status === "OK" || result.overall_status === "connected") {
                    this.state.gloryApiStatus = "connected";
                } else {
                    this.state.gloryApiStatus = "disconnected";
                }
            } else {
                this.state.gloryApiStatus = "disconnected";
            }
        } catch (error) {
            console.error("Error checking Glory API status:", error);
            this.state.gloryApiStatus = "disconnected";
        }
    }

    /**
     * @private
     * Handles the click on the "Check Status" button.
     * Fetches the current FCC status and displays it at the bottom of the screen.
     */
    async _onCheckStatusClick() {
        this.state.statusMessage = "Checking status, please wait...";
        try {
            // Updated API call to the new Odoo proxy endpoint
            const response = await fetch("/gas_station_cash/fcc/status");
            if (response.ok) {
                const statusData = await response.json();
                let message = `Overall Status: ${statusData.Status.String} (${statusData.Status.Code})`;
                if (statusData.DeviceStatus && statusData.DeviceStatus.length > 0) {
                    const deviceMessages = statusData.DeviceStatus.map(dev =>
                        `Device ${dev.device_id} (${dev.device_type}): ${dev.device_state}`
                    );
                    message += ` | Device Status: ${deviceMessages.join(", ")}`;
                }
                this.state.statusMessage = message;
            } else {
                const errorData = await response.json();
                this.state.statusMessage = `Error: Could not retrieve status. Details: ${errorData.details || "Unknown error"}`;
            }
        } catch (error) {
            console.error("Error checking FCC status:", error);
            this.state.statusMessage = `Error: Failed to connect to the Odoo proxy endpoint.`;
        }
    }

    _onHome() {
        // Implement navigation logic
        console.log("Home button clicked. Returning to main menu.");
        this.state.currentScreen = 'mainMenu';
        this.state.selectedDepositType = null;
        this.state.statusMessage = "Welcome to the Cash Recycler App. Please select a deposit type.";
    }

    _onFullScreen() {
        // Implement full-screen logic
        console.log("Full screen button clicked");
        if (document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen();
        } else if (document.documentElement.mozRequestFullScreen) { /* Firefox */
            document.documentElement.mozRequestFullScreen();
        } else if (document.documentElement.webkitRequestFullscreen) { /* Chrome, Safari and Opera */
            document.documentElement.webkitRequestFullscreen();
        } else if (document.documentElement.msRequestFullscreen) { /* IE/Edge */
            document.documentElement.msRequestFullscreen();
        }

        // Disable Main Nav Bar in Full Screen
        const mainNavBar = document.querySelector('.o_main_navbar');
        if (mainNavBar) {
            mainNavBar.style.display = 'none'; // Hide the main navigation bar
        }

        // Hide Full Screen button when in full screen
        const fullScreenButton = document.querySelector('.full-screen-button');
        const exitFullScreenButton = document.querySelector('.exit-full-screen-button');
        if (exitFullScreenButton) {
            exitFullScreenButton.style.display = 'block'; // Show the Exit Full Screen button
        }
        if (fullScreenButton) {
            fullScreenButton.style.display = 'none'; // Hide the Full Screen button
        }
    }

    _onExitFullScreen() {
        // Implement exit full-screen logic
        console.log("Exit Full screen button clicked");
        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.mozCancelFullScreen) { /* Firefox */
            document.mozCancelFullScreen();
        } else if (document.webkitExitFullscreen) { /* Chrome, Safari and Opera */
            document.webkitExitFullscreen();
        } else if (document.msExitFullscreen) { /* IE/Edge */
            document.msExitFullscreen();
        }

        // Show Main Nav Bar when exiting Full Screen
        const mainNavBar = document.querySelector('.o_main_navbar');
        if (mainNavBar) {
            mainNavBar.removeAttribute('style'); // Show the main navigation bar
        }

        // Hide Exit Full Screen button when exiting full screen
        const exitFullScreenButton = document.querySelector('.exit-full-screen-button');
        const fullScreenButton = document.querySelector('.full-screen-button');
        if (fullScreenButton) {
            fullScreenButton.style.display = 'block'; // Show the Full Screen button again
        }

        if (exitFullScreenButton) {
            exitFullScreenButton.style.display = 'none'; // Hide the Exit Full Screen button
        }
    }

    _onMenuButtonClick = (depositType) => {
        const depositTypeName = this.depositTypeNames[depositType] || depositType;

        this.state.currentScreen = "pinEntry";
        this.state.selectedDepositType = depositType;
        this.state.statusMessage = this._t("Please enter PIN for %s", depositTypeName);
    }

    // New methods to handle events from the DepositCashApp component
    _onDepositConfirmed(amount) {
        this.state.currentScreen = "mainMenu";
        this.state.statusMessage = `Deposit of ${amount} confirmed.`;
    }

    _onDepositCancelled() {
        this.state.currentScreen = "mainMenu";
        this.state.statusMessage = "Deposit canceled.";
    }

    _onApiError(errorMessage) {
        this.state.currentScreen = "error";
        this.state.statusMessage = errorMessage;
    }
    _onStatusUpdate(message) {
        this.state.statusMessage = message;
    }
}