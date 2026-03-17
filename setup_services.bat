@echo off
:: ============================================================
:: setup_services.bat
:: Register Flask services as Windows Services using NSSM
:: Run as Administrator
:: ============================================================

set BASE_DIR=C:\GloryMiddleware
set NSSM=%BASE_DIR%\tools\nssm.exe
set LOG_DIR=%BASE_DIR%\logs

:: Create log directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ==========================================
echo  Glory Middleware — Setup Windows Services
echo ==========================================

:: --- GloryAPI Service ---
echo [1/3] Installing GloryAPI...
%NSSM% install GloryAPI "%BASE_DIR%\GloryAPI\venv\Scripts\python.exe"
%NSSM% set GloryAPI AppDirectory "%BASE_DIR%\GloryAPI"
%NSSM% set GloryAPI AppParameters "app.py"
%NSSM% set GloryAPI DisplayName "Glory Cash Recycler API"
%NSSM% set GloryAPI Description "Flask API bridge for Glory FCC SOAP client"
%NSSM% set GloryAPI Start SERVICE_AUTO_START
%NSSM% set GloryAPI AppStdout "%LOG_DIR%\glory_api.log"
%NSSM% set GloryAPI AppStderr "%LOG_DIR%\glory_api_err.log"
%NSSM% set GloryAPI AppRotateFiles 1
%NSSM% set GloryAPI AppRotateBytes 10485760
%NSSM% set GloryAPI AppRestartDelay 3000

:: --- Printer Service ---
echo [2/3] Installing PrinterService...
%NSSM% install PrinterService "%BASE_DIR%\printer\venv\Scripts\python.exe"
%NSSM% set PrinterService AppDirectory "%BASE_DIR%\printer"
%NSSM% set PrinterService AppParameters "app.py"
%NSSM% set PrinterService DisplayName "Glory Printer Service"
%NSSM% set PrinterService Description "Receipt printer service"
%NSSM% set PrinterService Start SERVICE_AUTO_START
%NSSM% set PrinterService AppStdout "%LOG_DIR%\printer.log"
%NSSM% set PrinterService AppStderr "%LOG_DIR%\printer_err.log"
%NSSM% set PrinterService AppRotateFiles 1
%NSSM% set PrinterService AppRotateBytes 10485760
%NSSM% set PrinterService AppRestartDelay 3000

:: --- Fingerprint Service ---
echo [3/3] Installing FingerprintService...
%NSSM% install FingerprintService "%BASE_DIR%\fingerprint\venv\Scripts\python.exe"
%NSSM% set FingerprintService AppDirectory "%BASE_DIR%\fingerprint"
%NSSM% set FingerprintService AppParameters "app.py"
%NSSM% set FingerprintService DisplayName "Glory Fingerprint Service"
%NSSM% set FingerprintService Description "Fingerprint reader service"
%NSSM% set FingerprintService Start SERVICE_AUTO_START
%NSSM% set FingerprintService AppStdout "%LOG_DIR%\fingerprint.log"
%NSSM% set FingerprintService AppStderr "%LOG_DIR%\fingerprint_err.log"
%NSSM% set FingerprintService AppRotateFiles 1
%NSSM% set FingerprintService AppRotateBytes 10485760
%NSSM% set FingerprintService AppRestartDelay 3000

:: Start all services
echo Starting services...
%NSSM% start GloryAPI
%NSSM% start PrinterService
%NSSM% start FingerprintService

echo ==========================================
echo  Done! Check status: services.msc
echo ==========================================
pause