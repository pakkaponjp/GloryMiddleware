@echo off
:: ============================================================
:: install_services.bat
:: Install Flask services using WinSW
:: Run as Administrator
:: ============================================================

set TOOLS_DIR=C:\GloryMiddleware\tools
set LOG_DIR=C:\GloryMiddleware\logs

:: Create log directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ==========================================
echo  Glory Middleware - Install Services
echo ==========================================

echo [1/3] Installing GloryAPI...
%TOOLS_DIR%\GloryAPI.exe install

echo [2/3] Installing PrinterService...
%TOOLS_DIR%\PrinterService.exe install

echo [3/3] Installing FingerprintService...
%TOOLS_DIR%\FingerprintService.exe install

echo.
echo Starting services...
%TOOLS_DIR%\GloryAPI.exe start
%TOOLS_DIR%\PrinterService.exe start
%TOOLS_DIR%\FingerprintService.exe start

echo.
echo ==========================================
echo  Done! Check status: services.msc
echo  Logs: %LOG_DIR%
echo ==========================================
pause