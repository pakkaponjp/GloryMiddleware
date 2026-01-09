/** @odoo-module */

import { registry } from "@web/core/registry";
import { Component, useState, onWillUnmount, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { _t } from "@web/core/l10n/translation";
import { getSecondaryTranslation } from "./translation_helper";
import { PinEntryScreen } from "./pin_entry_screen";
import { OilDepositScreen } from "./oil_deposit_screen";
import { EngineOilDepositScreen } from "./engine_oil_deposit_screen";
import { RentalDepositScreen } from "./rental_deposit_screen";
import { CoffeeShopDepositScreen } from "./coffee_shop_deposit_screen";
import { ConvenientStoreDepositScreen } from "./convenient_store_deposit_screen";
import { DepositCashScreen } from "./deposit_cash_screen";
import { ExchangeCashScreen } from "./exchange_cash_screen";
import { BlockingOverlay } from "./blocking_overlay";

// The main component for the Cash Recycler app.
// This component will be rendered when the client action is triggered.
export class CashRecyclerApp extends Component {
    static template = "gas_station_cash.CashRecyclerApp";
    static components = {
        BlockingOverlay,
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
        action: { type: Object, optional: true },
        actionId: { type: Number, optional: true },
        className: { type: String, optional: true },
        context: { type: Object, optional: true },
        params: { type: Object, optional: true },
        name: { type: String, optional: true },
        displayName: { type: String, optional: true },
    };

    setup() {
        // Create a map of technical names to translatable
        this._t = _t;
        this.session = session;
        this.rpc = useService("rpc");

        // Access the POS Command Overlay service
        this.posOverlay = useService("pos_command_overlay");

        // Setup multi-language support
        const primaryLang = this.session.user_context.lang || "en_US";
        const defaultSecondaryLang = primaryLang.startsWith('th') ? 'en_US' : 'th_TH';

        // State to manage the current screen and API status
        this.state = useState({
            gloryApiStatus: "disconnected",      // connected | disconnected | connecting
            statusMessage: _t("Ready"),          // Detailed status message
            currentScreen: "mainMenu",           // 'mainMenu', 'pinEntry', etc.
            selectedDepositType: null,           // Stores the type of deposit selected
            isFullScreen: false,                 // Tracks if the app is in full-screen mode
            staffList: [],                       // optional, safe default
            employeeDetails: null,               // safe default

            primaryLang,
            secondaryLang: defaultSecondaryLang,
        });

        // Map deposit types to user-friendly names
        this.depositTypeNames = {
            oil: _t("Oil Sales"),
            engine_oil: _t("Engine Oil Sales"),
            rental: _t("Rental"),
            coffee_shop: _t("Coffee Shop Sales"),
            convenient_store: _t("Convenient Store Sales"),
            exchange_cash: _t("Exchange Notes and Coins"),
            deposit_cash: _t("Replenish Cash"),
        };

        // Determine secondary language based on primary language
        this.getSecondaryTranslation = (englishText) => {
            return getSecondaryTranslation(englishText, this.state.secondaryLang);
        };

        // Initialize languages
        this.isPrimaryLang = (langCode) => {
            // This safely checks if primaryLang exists before calling startsWith
            if (!this.state.primaryLang) {
                return false;
            }
            return this.state.primaryLang.startsWith(langCode);
        };

        // Immediately check API status on setup to get an initial state for the heartbeat icon
        console.log("Checking Glory API status on startup...");
        this.checkGloryApiStatus();
        console.log("Starting Glory API status heartbeat...");
        this._hb = setInterval(() => this.checkGloryApiStatus(), 180000); // every 3 minutes
        this.posTerminalId = "TERM-01"; // make this dynamic later
        this.posOverlay = useService("pos_command_overlay");
        //this.posOverlay.init(this.posTerminalId); // Initialize overlay service with terminal ID
        window.localStorage.setItem("pos_terminal_id", this.posTerminalId);

        onWillStart(async () => {
            try {
                const response = await this.rpc("/gas_station_cash/middleware/ready", {
                    terminal_id: this.posTerminalId,
                });
                console.log("Middleware ready response:", response);
            } catch (error) {
                console.error("Failed to mark middleware ready", error);
            }
        });


        onWillUnmount(() => {
            // 1) Stop heartbeat timer if any
            if (this._hb) {
                clearInterval(this._hb);
                this._hb = null;
            }

            // 2) Tell Odoo that middleware is NOT READY anymore
            const posTerminalId = this.posTerminalId || "TERM-01";

            this.rpc("/gas_station_cash/middleware/not_ready", {
                terminal_id: posTerminalId,
            })
                .then((response) => {
                    console.log("Middleware not_ready response:", response);
                })
                .catch((error) => {
                    console.error("Failed to mark middleware not ready", error);
                });
        });

    }

    // A getter to dynamically select the correct component
    get activeScreen() {
        console.log("ActiveScreeen() Current screen:", this.state.currentScreen);
        console.log("Rendering OilDepositScreen with onDone:", this._onDepositConfirmed);
        switch (this.state.currentScreen) {
            case 'pinEntry':
                return {
                    Component: PinEntryScreen,
                    props: {
                        staffList: this.state.staffList,
                        depositType: this.state.selectedDepositType,
                        onLoginSuccess: this.onLoginSuccess.bind(this),
                        onCancel: this._onHome.bind(this),              // or another cancel handler
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
                        onDone: this._onDepositConfirmed.bind(this),
                        onApiError: this._onApiError.bind(this),
                    }
                };
            case 'engine_oilDeposit':
                return {
                    Component: EngineOilDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this._onDepositCancelled.bind(this),
                        onDone: this._onDepositConfirmed.bind(this),
                        onStatusUpdate: (msg) => this._onStatusUpdate(msg),
                    },
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
            case 'rentalDeposit':
                return {
                    Component: RentalDepositScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this.onCancel.bind(this),
                        onDone: this._onDepositConfirmed.bind(this),
                        onApiError: this._onApiError.bind(this),
                        onStatusUpdate: this._onStatusUpdate.bind(this),
                    },
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
                return null;
        }
    }

    _onSwitchSecondaryLanguage = (langCode) => {
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
    // -------------------------------NEW CODE--------------------------------
    async checkGloryApiStatus() {
        try {
            console.log("----------Checking Glory API status via Odoo proxy endpoint...");
            const response = await fetch("/gas_station_cash/fcc/status", {
                method: "POST",                // type="json" expects POST
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({})       // body allowed (can be empty)
            });

            if (!response.ok) {
                this.state.gloryApiStatus = "**************disconnected";
                return;
            }
            // Parse once
            const payload = await response.json();
            // Unwrap JSON-RPC if present
            const result = payload?.result ?? payload;

            console.log("Parsed /fcc/status JSON (unwrapped):", result);
            // Accept either your normalized shape or a simple status flag
            const ok =
                result?.status === "OK" ||
                result?.overall_status === "OK" ||
                result?.overall_status === "connected" ||
                result?.code === "0"; // fallback to raw result code

            this.state.gloryApiStatus = ok ? "connected" : "disconnected";
            console.log("Glory API is+++++++++++++++++", this.state.gloryApiStatus);
        } catch (err) {
            console.error("Error checking Glory API status:", err);
            this.state.gloryApiStatus = "disconnected";
        }
    }
    // -------------------------------OLD CODE--------------------------------
    // async checkGloryApiStatus() {
    //     try {
    //         // Updated API call to the new Odoo proxy endpoint
    //         // Odoo API endpoint for Glory status
    //         const response = await fetch("/gas_station_cash/glory/status");
    //         if (response.ok) {
    //             const result = await response.json();
    //             if (result.overall_status === "OK" || result.overall_status === "connected") {
    //                 this.state.gloryApiStatus = "connected";
    //             } else {
    //                 this.state.gloryApiStatus = "disconnected";
    //             }
    //         } else {
    //             this.state.gloryApiStatus = "disconnected";
    //         }
    //     } catch (error) {
    //         console.error("Error checking Glory API status:", error);
    //         this.state.gloryApiStatus = "disconnected";
    //     }
    // }


    /**
     * @private
     * Handles the click on the "Check Status" button.
     * Fetches the current FCC status and displays it at the bottom of the screen.
     */
    // async _onCheckStatusClick() {
    //     this.state.statusMessage = "Checking status, please wait...";
    //     try {
    //         // Updated API call to the new Odoo proxy endpoint
    //         const response = await fetch("/gas_station_cash/fcc/status", {
    //             method: "POST",
    //             headers: { "Content-Type": "application/json" },
    //             body: JSON.stringify({})
    //         });

    //         if (response.ok) {
    //             /*const statusData = await response.json();
    //             let message = `Overall Status: ${statusData.Status.String} (${statusData.Status.Code})`;
    //             if (statusData.DeviceStatus && statusData.DeviceStatus.length > 0) {
    //                 const deviceMessages = statusData.DeviceStatus.map(dev =>
    //                     `Device ${dev.device_id} (${dev.device_type}): ${dev.device_state}`
    //                 );
    //                 message += ` | Device Status: ${deviceMessages.join(", ")}`;
    //             }*/
    //             const payload = await response.json();
    //             const data = payload?.result ?? payload;

    //             // Flask formatter returns: { status, code, session_id, verify, raw }
    //             const code = data?.raw?.Status?.Code ?? data?.code ?? "?";
    //             const devs = data?.raw?.Status?.DevStatus || [];
    //             const deviceMessages = devs.map(d => `Dev ${d.devid}: st=${d.st}, val=${d.val}`);
    //             const message = `Overall Status: ${data.status} (code ${code})` +
    //                 (deviceMessages.length ? ` | ${deviceMessages.join(", ")}` : "");

    //             this.state.statusMessage = message;
    //         } else {
    //             const errorData = await response.json();
    //             this.state.statusMessage = `Error: Could not retrieve status. Details: ${errorData.details || "Unknown error"}`;
    //         }
    //     } catch (error) {
    //         console.error("Error checking FCC status:", error);
    //         this.state.statusMessage = `Error: Failed to connect to the Odoo proxy endpoint.`;
    //     }
    // }

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

    _onDepositConfirmed(amount) {
        console.log("Summary confirm called from cash recycler app");
        console.log("Deposit confirmed with amount:", amount);
        const confirmedAmount = amount || 0;
        this.state.currentScreen = "mainMenu";
        this.state.statusMessage = `Deposit of ${confirmedAmount} confirmed.`;
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