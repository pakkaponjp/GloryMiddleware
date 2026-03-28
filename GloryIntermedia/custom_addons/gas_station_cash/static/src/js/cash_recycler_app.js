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
import { DepositWithAmountScreen } from "./deposit_with_amount_screen";
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
        DepositWithAmountScreen,
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
        
        // Flag to pause status check during cash-in opening
        this._isCashInOpening = false;

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
            cashAlerts: [],
            cashAlertDismissed: false,
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
        
        // Expose this instance globally for LiveCashInScreen to access setCashInOpening
        window.cashRecyclerApp = this;

        onWillStart(async () => {
            try {
                const response = await this.rpc("/gas_station_cash/middleware/ready", {
                    terminal_id: this.posTerminalId,
                });
                console.log("Middleware ready response:", response);
            } catch (error) {
                console.error("Failed to mark middleware ready", error);
            }
            await this._loadAlerts();
        });


        onWillUnmount(() => {
            // 1) Stop heartbeat timer if any
            if (this._hb) {
                clearInterval(this._hb);
                this._hb = null;
            }

            // 2) Clean up fullscreen ESC blocker and listeners
            if (this._escKeyHandler) {
                document.removeEventListener('keydown', this._escKeyHandler, true);
                this._escKeyHandler = null;
            }
            if (this._fullscreenChangeHandler) {
                document.removeEventListener('fullscreenchange', this._fullscreenChangeHandler);
                document.removeEventListener('webkitfullscreenchange', this._fullscreenChangeHandler);
                document.removeEventListener('mozfullscreenchange', this._fullscreenChangeHandler);
                document.removeEventListener('MSFullscreenChange', this._fullscreenChangeHandler);
                this._fullscreenChangeHandler = null;
            }

            // 3) Clean up global reference
            if (window.cashRecyclerApp === this) {
                window.cashRecyclerApp = null;
            }

            // 3) Tell Odoo that middleware is NOT READY anymore
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

    // =========================================================================
    // TRANSACTION STATE - Disable menu buttons during active transaction
    // =========================================================================
    
    /**
     * Returns true when user is in an active transaction flow
     * This is used to disable Home, Replenish, Withdrawal, Status buttons
     */
    get isInTransaction() {
        const transactionScreens = [
            'pinEntry',
            'oilDeposit',
            'engine_oilDeposit',
            'cofee_shopDeposit',
            'convenient_sotreDeposit',
            'deposit_cashDeposit',
            'rentalDeposit',
            'exchange_cash',
            'withdrawalAmount',
        ];
        return transactionScreens.includes(this.state.currentScreen);
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
            case 'depositWithAmount':
                return {
                    Component: DepositWithAmountScreen,
                    props: {
                        depositType:    this.state.selectedDepositType,
                        employeeDetails: this.state.employeeDetails,
                        onDone:         this._onDepositConfirmed.bind(this),
                        onCancel:       this._onHome.bind(this),
                        onSkipToNormal: this._onSkipToNormalDeposit.bind(this),
                        onStatusUpdate: this._onStatusUpdate.bind(this),
                        onApiError:     this._onApiError.bind(this),
                    },
                };
            case 'exchange_cash':
                return {
                    Component: ExchangeCashScreen,
                    props: {
                        employeeDetails: this.state.employeeDetails,
                        onCancel: this._onHome.bind(this),
                        onDone: this._onHome.bind(this),
                        onStatusUpdate: this._onStatusUpdate.bind(this),
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
        if (depositType === "exit_fullscreen") {
            this.state.currentScreen = "mainMenu";
            this._doExitFullScreen();
        } else if (depositType === "exchange_cash") {
            this.state.currentScreen = "exchange_cash";
        } else if (depositType === "withdrawal") {
            this.state.currentScreen = "withdrawalAmount";
            this.state.statusMessage = "PIN verified. Enter withdrawal amount.";
        } else if (["coffee_shop", "convenient_store"].includes(depositType)) {
            // coffee_shop and convenient_store go to DepositWithAmount first
            this.state.currentScreen = "depositWithAmount";
            this.state.statusMessage = "PIN verified. Enter deposit amount.";
        } else {
            this.state.currentScreen = `${depositType}Deposit`;
            this.state.statusMessage = "PIN verified. Proceeding to deposit screen.";
        }
        
        console.log("Navigating to screen:", this.state.currentScreen);
    }

    // Glory connection overlay handlers
    _showGloryBlockedOverlay(reason = "") {
        // Prevent duplicate interval firing
        if (this._gloryBlocked) return;
        this._gloryBlocked = true;

        const message = "Cannot connect to Glory Cash Recycler";
        const subMessage =
            "Please Restart the Glory machine (turn off and on the power) and check that the GloryAPI (Flask) is running, then try again."
            + (reason ? `\n\nDetails: ${reason}` : "");

        // Support multiple method/field names across different service versions
        const o = this.posOverlay;

        if (o?.showBlockingOverlay) {
            o.showBlockingOverlay({
                message,
                subMessage,
                showCloseButton: false, // hard block — no close allowed
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

        // Fallback: set state directly
        if (o?.state) {
            o.state.isBlockingVisible = true;
            o.state.blockingMessage = message;
            o.state.blockingSubMessage = subMessage;
            o.state.showCloseButton = false;

            // Guard: state field may use a different name
            o.state.visible = true;
            o.state.message = message;
            o.state.subMessage = subMessage;
        }

        // Also update status bar if available
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
     * 
     * NOTE: Skipped during cash-in opening to prevent interference
     */

    get ctrlBtnClass() {
        return 'ctrl-btn' + (this.isInTransaction ? ' disabled' : '');
    }
    get ctrlBtnWarningClass() {
        return 'ctrl-btn ctrl-btn-warning' + (this.isInTransaction ? ' disabled' : '');
    }

    async _loadAlerts() {
        // Notes: API value is in THB (1000, 500, 100, 50, 20) → multiply by 100 to get satang
        // Coins: API value is in satang already (1000=฿10, 500=฿5, 200=฿2, 100=฿1, 50=฿0.50, 25=฿0.25)
        //        EXCEPT fractional coins (฿0.50, ฿0.25) may be returned as decimal THB: 0.50, 0.25
        const NOTE_MAP = [
            { satang: 100000, thb: 1000, key: 'note_1000', label: '฿1,000' },
            { satang:  50000, thb:  500, key: 'note_500',  label: '฿500'   },
            { satang:  10000, thb:  100, key: 'note_100',  label: '฿100'   },
            { satang:   5000, thb:   50, key: 'note_50',   label: '฿50'    },
            { satang:   2000, thb:   20, key: 'note_20',   label: '฿20'    },
        ];
        const COIN_MAP = [
            { satang:  1000, thb:  10,   key: 'coin_10',  label: '฿10'   },
            { satang:   500, thb:   5,   key: 'coin_5',   label: '฿5'    },
            { satang:   200, thb:   2,   key: 'coin_2',   label: '฿2'    },
            { satang:   100, thb:   1,   key: 'coin_1',   label: '฿1'    },
            { satang:    50, thb:   0.5, key: 'coin_050', label: '฿0.50' },
            { satang:    25, thb:  0.25, key: 'coin_025', label: '฿0.25' },
        ];

        // Find closest match in a DENOM list by trying as satang, THB integer, THB decimal
        const matchDenom = (rawStr, denomList) => {
            const f = parseFloat(rawStr);
            if (isNaN(f) || f <= 0) return null;
            // Try exact satang match
            const bySatang = denomList.find(d => Math.abs(d.satang - Math.round(f)) < 1);
            if (bySatang) return bySatang;
            // Try interpreting as THB and convert to satang (×100)
            const byThb = denomList.find(d => Math.abs(d.satang - Math.round(f * 100)) < 1);
            if (byThb) return byThb;
            return null;
        };

        try {
            const icpKeys = [...NOTE_MAP, ...COIN_MAP].flatMap(d => [
                `gas_station_cash.wm_low_${d.key}`,
                `gas_station_cash.wm_high_${d.key}`,
            ]);
            const rows = await this.rpc("/web/dataset/call_kw", {
                model: "ir.config_parameter",
                method: "search_read",
                args: [[["key", "in", icpKeys]]],
                kwargs: { fields: ["key", "value"], limit: 50 },
            });
            const icp = {};
            (rows || []).forEach(r => { icp[r.key] = parseInt(r.value) || 0; });

            const invResp = await this.rpc("/api/glory/check_float", {
                type: "command", name: "check_float",
                transactionId: `ALERT-${Date.now()}`,
                timestamp: new Date().toISOString(), data: {}
            });

            const avail = invResp?.result?.data?.bridgeApiAvailability
                       || invResp?.data?.bridgeApiAvailability
                       || invResp?.bridgeApiAvailability;
            if (!avail) return;

            // Build qty map: key (e.g. 'note_1000') → qty
            // Process notes and coins separately to avoid collision
            //   (value 1000 in notes array = ฿1,000 note; same value 1000 in coins array = ฿10 coin)
            const qtyByKey = {};
            const noteItems = avail.notes || avail.Notes || [];
            const coinItems = avail.coins || avail.Coins || [];

            for (const item of noteItems) {
                const raw = String(item.value ?? item.Value ?? 0);
                const denom = matchDenom(raw, NOTE_MAP);
                if (denom) qtyByKey[denom.key] = parseInt(item.qty ?? item.Qty ?? item.quantity ?? 0);
            }
            console.log("[CashAlert] raw coinItems from API:", JSON.stringify(coinItems));
            for (const item of coinItems) {
                const raw = String(item.value ?? item.Value ?? 0);
                const denom = matchDenom(raw, COIN_MAP);
                console.log(`[CashAlert] coin raw="${raw}" → matched=${denom ? denom.key : 'NONE'}`);
                if (denom) qtyByKey[denom.key] = parseInt(item.qty ?? item.Qty ?? item.quantity ?? 0);
            }
            console.log("[CashAlert] qtyByKey after mapping:", JSON.stringify(qtyByKey));

            const alerts = [];
            for (const denom of [...NOTE_MAP, ...COIN_MAP]) {
                if (!(denom.key in qtyByKey)) continue;
                const qty  = qtyByKey[denom.key];
                const low  = icp[`gas_station_cash.wm_low_${denom.key}`]  || 0;
                const high = icp[`gas_station_cash.wm_high_${denom.key}`] || 0;
                if (low > 0 && qty < low) {
                    const sev = qty === 0 ? 'critical' : 'warning';
                    alerts.push({
                        label: denom.label, qty, threshold: low,
                        type: 'near_empty', severity: sev,
                        itemClass: `cr-alert-popup__item cr-alert-popup__item--near_empty`,
                        iconClass: sev === 'critical' ? 'fa fa-times-circle' : 'fa fa-exclamation-circle',
                        message: `${denom.label}: qty ${qty} below Near Empty (${low})`,
                    });
                } else if (high > 0 && qty > high) {
                    alerts.push({
                        label: denom.label, qty, threshold: high,
                        type: 'near_full', severity: 'warning',
                        itemClass: `cr-alert-popup__item cr-alert-popup__item--near_full`,
                        iconClass: 'fa fa-exclamation-circle',
                        message: `${denom.label}: qty ${qty} above Near Full (${high})`,
                    });
                }
            }
            this.state.cashAlerts = alerts;
            if (alerts.length > 0) this.state.cashAlertDismissed = false;
        } catch (e) {
            console.warn("[CashAlert] Could not load cash alerts:", e);
        }
    }

    dismissCashAlert() {
        this.state.cashAlertDismissed = true;
        if (this._alertTimer) clearTimeout(this._alertTimer);
        this._alertTimer = setTimeout(() => {
            if (this.state.cashAlerts.length > 0) this.state.cashAlertDismissed = false;
        }, 5 * 60 * 1000);
    }

    async checkGloryApiStatus() {
        // Skip status check during cash-in opening to prevent interference
        if (this._isCashInOpening) {
            console.log("[StatusCheck] Skipped - Cash-in opening in progress");
            return true;
        }
        if (this._isDispensing) {
            console.log("[StatusCheck] Skipped - Cash-out dispensing in progress");
            return true;
        }
        
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

    /** Skip DepositWithAmount → go to normal deposit screen (coffee_shop / convenient_store only) */
    _onSkipToNormalDeposit() {
        const type = this.state.selectedDepositType;
        console.log("[CashRecyclerApp] Skip to normal deposit:", type);
        this.state.currentScreen = `${type}Deposit`;
        this.state.statusMessage = "Proceeding to normal deposit.";
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

        // Mark that we are intentionally in fullscreen (ESC should be blocked)
        this._intentionalFullScreen = true;
        this._exitingFullScreenIntentionally = false;

        if (document.documentElement.requestFullscreen) {
            document.documentElement.requestFullscreen();
        } else if (document.documentElement.mozRequestFullScreen) { /* Firefox */
            document.documentElement.mozRequestFullScreen();
        } else if (document.documentElement.webkitRequestFullscreen) { /* Chrome, Safari and Opera */
            document.documentElement.webkitRequestFullscreen();
        } else if (document.documentElement.msRequestFullscreen) { /* IE/Edge */
            document.documentElement.msRequestFullscreen();
        }

        // Block ESC key from doing anything while in fullscreen
        if (!this._escKeyHandler) {
            this._escKeyHandler = (e) => {
                if (e.key === 'Escape' || e.keyCode === 27) {
                    e.preventDefault();
                    e.stopPropagation();
                    e.stopImmediatePropagation();
                }
            };
            // useCapture: true so this fires before all other handlers
            document.addEventListener('keydown', this._escKeyHandler, true);
        }

        // Listen to fullscreenchange: if browser forces exit (e.g. ESC), re-enter fullscreen immediately
        if (!this._fullscreenChangeHandler) {
            this._fullscreenChangeHandler = () => {
                const isCurrentlyFullscreen =
                    document.fullscreenElement ||
                    document.webkitFullscreenElement ||
                    document.mozFullScreenElement ||
                    document.msFullscreenElement;

                if (!isCurrentlyFullscreen && this._intentionalFullScreen && !this._exitingFullScreenIntentionally) {
                    // ESC or forced browser exit — show overlay requiring user to click back in
                    console.log("[FullScreen] Exited unexpectedly (ESC?), showing re-enter overlay...");
                    this._showReenterFullscreenOverlay();
                } else if (!isCurrentlyFullscreen && this._exitingFullScreenIntentionally) {
                    // Intentional exit via Exit button — clear the flag
                    this._intentionalFullScreen = false;
                    this._exitingFullScreenIntentionally = false;
                    this._updateFullScreenUI(false);
                }
            };
            document.addEventListener('fullscreenchange', this._fullscreenChangeHandler);
            document.addEventListener('webkitfullscreenchange', this._fullscreenChangeHandler);
            document.addEventListener('mozfullscreenchange', this._fullscreenChangeHandler);
            document.addEventListener('MSFullscreenChange', this._fullscreenChangeHandler);
        }

        this._updateFullScreenUI(true);
    }

    _onExitFullScreen() {
        // Require PIN from staff with Related Odoo User before exiting fullscreen
        console.log("Exit Full screen button clicked — requesting PIN");
        this.state.currentScreen = "exitPin";
        this.state.selectedDepositType = "exit_fullscreen";
        this.state.statusMessage = "Please verify with manager PIN to exit fullscreen.";
    }

    _doExitFullScreen() {
        // Actual exit — called only after PIN verified
        console.log("PIN verified — exiting fullscreen");

        // Mark intentional fullscreen exit (not triggered by ESC)
        this._exitingFullScreenIntentionally = true;
        this._intentionalFullScreen = false;

        // Remove overlay if present
        const overlay = document.getElementById('__fs_reenter_overlay__');
        if (overlay) overlay.remove();

        // Remove ESC key blocker
        if (this._escKeyHandler) {
            document.removeEventListener('keydown', this._escKeyHandler, true);
            this._escKeyHandler = null;
        }

        // Remove fullscreenchange listeners
        if (this._fullscreenChangeHandler) {
            document.removeEventListener('fullscreenchange', this._fullscreenChangeHandler);
            document.removeEventListener('webkitfullscreenchange', this._fullscreenChangeHandler);
            document.removeEventListener('mozfullscreenchange', this._fullscreenChangeHandler);
            document.removeEventListener('MSFullscreenChange', this._fullscreenChangeHandler);
            this._fullscreenChangeHandler = null;
        }

        if (document.exitFullscreen) {
            document.exitFullscreen();
        } else if (document.mozCancelFullScreen) { /* Firefox */
            document.mozCancelFullScreen();
        } else if (document.webkitExitFullscreen) { /* Chrome, Safari and Opera */
            document.webkitExitFullscreen();
        } else if (document.msExitFullscreen) { /* IE/Edge */
            document.msExitFullscreen();
        }

        this._updateFullScreenUI(false);
    }

    /**
     * แสดง overlay บังคับให้ user คลิกกลับเข้า fullscreen
     * (browser ไม่อนุญาตให้ requestFullscreen() โดยไม่มี user gesture)
     */
    _showReenterFullscreenOverlay() {
        // Prevent duplicate overlay
        if (document.getElementById('__fs_reenter_overlay__')) return;

        const overlay = document.createElement('div');
        overlay.id = '__fs_reenter_overlay__';
        overlay.style.cssText = `
            position: fixed;
            inset: 0;
            z-index: 999999;
            background: rgba(0, 0, 0, 0.92);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 24px;
            font-family: sans-serif;
        `;

        const icon = document.createElement('div');
        icon.textContent = '⛶';
        icon.style.cssText = 'font-size: 80px; color: #fff; line-height: 1;';

        const msg = document.createElement('div');
        msg.textContent = 'กรุณาคลิกปุ่มด้านล่างเพื่อกลับสู่โหมดเต็มหน้าจอ';
        msg.style.cssText = 'color: #fff; font-size: 22px; text-align: center;';

        const btn = document.createElement('button');
        btn.textContent = 'กลับสู่โหมดเต็มหน้าจอ';
        btn.style.cssText = `
            padding: 16px 40px;
            font-size: 20px;
            font-weight: bold;
            background: #1a73e8;
            color: #fff;
            border: none;
            border-radius: 8px;
            cursor: pointer;
        `;

        btn.addEventListener('click', () => {
            // User gesture present — requestFullscreen is allowed
            const el = document.documentElement;
            const req = el.requestFullscreen || el.mozRequestFullScreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
            if (req) {
                req.call(el).catch((err) => console.error('[FullScreen] re-enter failed:', err));
            }
            overlay.remove();
        });

        overlay.appendChild(icon);
        overlay.appendChild(msg);
        overlay.appendChild(btn);
        document.body.appendChild(overlay);
    }

    /**
     */
    _updateFullScreenUI(isFullScreen) {
        const mainNavBar = document.querySelector('.o_main_navbar');
        const fullScreenButton = document.querySelector('.full-screen-button');
        const exitFullScreenButton = document.querySelector('.exit-full-screen-button');

        if (isFullScreen) {
            if (mainNavBar) mainNavBar.style.display = 'none';
            if (fullScreenButton) fullScreenButton.style.display = 'none';
            if (exitFullScreenButton) exitFullScreenButton.style.display = 'block';
        } else {
            if (mainNavBar) mainNavBar.removeAttribute('style');
            if (fullScreenButton) fullScreenButton.style.display = 'block';
            if (exitFullScreenButton) exitFullScreenButton.style.display = 'none';
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

    /**
     * Handle API errors from deposit screens
     * Shows error message and auto-returns to home after 3 seconds
     */
    _onApiError(errorMessage) {
        console.error("[CashRecyclerApp] API Error:", errorMessage);
        
        // Clear cash-in opening flag
        this._isCashInOpening = false;
    
        // Update status message with countdown
        this.state.statusMessage = `${errorMessage} - Returning to home in 3 seconds...`;
        
        // Show notification (if available)
        this._showNotification(errorMessage, "danger");
        
        // Auto-return to home after 3 seconds
        setTimeout(() => {
            console.log("[CashRecyclerApp] Auto-returning to home after error");
            this.state.currentScreen = "mainMenu";
            this.state.selectedDepositType = null;
            this.state.statusMessage = "Ready";
        }, 3000);
    }

    /**
     * Show notification toast (if notification service available)
     */
    _showNotification(message, type = "info") {
        try {
            // Try to use Odoo notification service if available
            if (this.notification) {
                this.notification.add(message, { type: type });
            }
        } catch (e) {
            console.warn("Notification service not available:", e);
        }
    }

    /**
     * Set cash-in opening flag (called from deposit screens)
     */
    setCashInOpening(isOpening) {
        console.log("[CashRecyclerApp] setCashInOpening:", isOpening);
        this._isCashInOpening = isOpening;
    }

    setDispensing(isDispensing) {
        console.log("[CashRecyclerApp] setDispensing:", isDispensing);
        this._isDispensing = isDispensing;
    }
    _onStatusUpdate(message) {
        this.state.statusMessage = message;
    }

    /**
     * Check Status button click handler
     * Fetches detailed status from GloryAPI and displays human-readable message
     */
    async _onCheckStatusClick() {
        console.log("Check Status button clicked");
        this.state.statusMessage = "Checking Glory API status...";
        
        try {
            const response = await fetch("/gas_station_cash/fcc/status-detailed", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            });
            
            if (!response.ok) {
                this.state.gloryApiStatus = "disconnected";
                this.state.statusMessage = `Glory API: HTTP Error ${response.status}`;
                return;
            }
            
            const payload = await response.json();
            const result = payload?.result ?? payload;
            
            console.log("Glory API status-detailed response:", result);
            
            // Check if connected
            const ok = result?.status === "OK";
            this.state.gloryApiStatus = ok ? "connected" : "disconnected";
            
            // Display message from API
            if (result?.message) {
                const prefix = ok ? "Glory API: Connected ✓" : "Glory API: Disconnected ✗";
                this.state.statusMessage = `${prefix} | ${result.message}`;
            } else {
                this.state.statusMessage = ok ? "Glory API: Connected ✓" : "Glory API: Disconnected ✗";
            }
            
        } catch (error) {
            console.error("Error checking status:", error);
            this.state.statusMessage = `Glory API: Error - ${error.message || "Connection failed"}`;
            this.state.gloryApiStatus = "disconnected";
        }
    }
}