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
import { WithdrawalScreen } from "./withdrawal_screen";

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
        WithdrawalScreen,
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
        this.posTerminalId = "TERM-01"; // make this dynamic later
        window.localStorage.setItem("pos_terminal_id", this.posTerminalId);

        this._t = _t;
        this.session = session;
        this.rpc = useService("rpc");

        // Access the POS Command Overlay service
        this.posOverlay = useService("pos_command_overlay");

        this._gloryBlocked = false;

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
            withdrawal: _t("Withdrawal"),  // Added withdrawal
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
        this._hb = setInterval(() => this.checkGloryApiStatus(), 30000); // every 30 seconds

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
            // Withdrawal screen (after PIN verified)
            case 'withdrawalAmount':
                return {
                    Component: WithdrawalScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this._onHome.bind(this),
                        onDone: this._onWithdrawalDone.bind(this),
                        onStatusUpdate: this._onStatusUpdate.bind(this),
                        onApiError: this._onApiError.bind(this),
                    },
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
        
        // Determine next screen based on depositType
        if (depositType === "exchange_cash") {
            // Exchange is not a deposit action
            this.state.currentScreen = "exchange_cash";
        } else if (depositType === "withdrawal") {
            // Withdrawal goes to withdrawalAmount screen
            this.state.currentScreen = "withdrawalAmount";
            this.state.statusMessage = "PIN verified. Enter withdrawal amount.";
        } else {
            // All deposits go to {type}Deposit screen
            this.state.currentScreen = `${depositType}Deposit`;
            this.state.statusMessage = "PIN verified. Proceeding to deposit screen.";
        }
        
        console.log("Navigating to screen:", this.state.currentScreen);
    }

    // Glory connection overlay handlers
    _showGloryBlockedOverlay(reason = "") {
        // กันยิงซ้ำทุก ๆ interval
        if (this._gloryBlocked) return;
        this._gloryBlocked = true;

        const message = "Cannot connect to Glory Cash Recycler";
        const subMessage =
            "Please Restart the Glory machine (turn off and on the power) and check that the GloryAPI (Flask) is running, then try again."
            + (reason ? `\n\nDetails: ${reason}` : "");

        // รองรับหลายชื่อ method/field เผื่อ service คนละเวอร์ชัน
        const o = this.posOverlay;

        if (o?.showBlockingOverlay) {
            o.showBlockingOverlay({
                message,
                subMessage,
                showCloseButton: false, // block จริง ๆ
            });
            return;
        }
        if (o?.show) {
            o.show({
                message,
                subMessage,
                showCloseButton: false,
            });
            return;
        }

        // fallback: set state ตรง ๆ
        if (o?.state) {
            o.state.isBlockingVisible = true;
            o.state.blockingMessage = message;
            o.state.blockingSubMessage = subMessage;
            o.state.showCloseButton = false;

            // เผื่อ state ใช้ชื่ออื่น
            o.state.visible = true;
            o.state.message = message;
            o.state.subMessage = subMessage;
        }

        // แจ้งใน status bar ด้วย (ถ้ามี)
        this.state.statusMessage = message;
    }

    _hideGloryBlockedOverlay() {
        if (!this._gloryBlocked) return;
        this._gloryBlocked = false;

        const o = this.posOverlay;
        if (o?.hideBlockingOverlay) {
            o.hideBlockingOverlay();
            return;
        }
        if (o?.hide) {
            o.hide();
            return;
        }
        if (o?.state) {
            o.state.isBlockingVisible = false;
            o.state.visible = false;
        }
    }

    /**
     * @private
     * Checks the status of the Glory API for the heartbeat icon.
     * Updates the 'gloryApiStatus' state based on the API response.
     */
    async checkGloryApiStatus() {
        try {
            console.log("Checking Glory API status via Odoo proxy endpoint...");
            const response = await fetch("/gas_station_cash/fcc/status", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });

            if (!response.ok) {
                this.state.gloryApiStatus = "disconnected";
                this._showGloryBlockedOverlay(`HTTP ${response.status}`);
                return false;
            }

            const payload = await response.json();
            const result = payload?.result ?? payload;

            const ok =
                result?.status === "OK" ||
                result?.overall_status === "OK" ||
                result?.overall_status === "connected" ||
                result?.code === "0";

            this.state.gloryApiStatus = ok ? "connected" : "disconnected";

            if (ok) {
                this._hideGloryBlockedOverlay();
            } else {
                const reason =
                    result?.description ||
                    result?.error ||
                    result?.details ||
                    "Glory status = disconnected";
                this._showGloryBlockedOverlay(reason);
            }

            console.log("Glory API status =", this.state.gloryApiStatus, "raw=", result);
            return ok;
        } catch (err) {
            console.error("Error checking Glory API status:", err);
            this.state.gloryApiStatus = "disconnected";
            this._showGloryBlockedOverlay("Network/Fetch error (GloryAPI หรือ Odoo proxy ไม่ตอบสนอง)");
            return false;
        }
    }

    _onHome() {
        // Implement navigation logic
        console.log("Home button clicked. Returning to main menu.");
        this.state.currentScreen = 'mainMenu';
        this.state.selectedDepositType = null;
        this.state.statusMessage = "Welcome to the Cash Recycler App. Please select a deposit type.";
    }

    _onWithdrawalDone(amount) {
        console.log("[CashRecyclerApp] Withdrawal done, amount:", amount);
        this.state.currentScreen = "mainMenu";
        this.state.selectedDepositType = null;
        this.state.statusMessage = `Withdrawal of ฿${amount?.toLocaleString() || 0} completed.`;
    }
    
    // Use same flow as other menus - go through PinEntryScreen
    _onWithdrawalClick() {
        console.log("[CashRecyclerApp] Withdrawal button clicked");
        this._onMenuButtonClick('withdrawal');
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

    /**
     * Check Status button click handler
     * Manually triggers Glory API status check and updates the status message
     */
    async _onCheckStatusClick() {
        console.log("Check Status button clicked");
        this.state.statusMessage = "Checking Glory API status...";
        
        try {
            await this.checkGloryApiStatus();
            
            if (this.state.gloryApiStatus === "connected") {
                this.state.statusMessage = "Glory API: Connected ✓";
            } else {
                this.state.statusMessage = "Glory API: Disconnected ✗";
            }
        } catch (error) {
            console.error("Error checking status:", error);
            this.state.statusMessage = "Error checking Glory API status";
            this.state.gloryApiStatus = "disconnected";
        }
    }
}