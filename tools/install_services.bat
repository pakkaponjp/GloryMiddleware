@echo off
:: ============================================================
:: install_services.bat
:: Install Flask services using WinSW
:: Run as Administrator
:: ============================================================

set TOOLS_DIR=C:\GloryMiddleware\tools
set WINSW=%TOOLS_DIR%\WinSW-x64.exe
set LOG_DIR=C:\GloryMiddleware\logs

:: Create log directory
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo ==========================================
echo  Glory Middleware — Install Services
echo ==========================================

echo [1/3] Installing GloryAPI...
%WINSW% install "%TOOLS_DIR%\GloryAPI.xml"

echo [2/3] Installing PrinterService...
%WINSW% install "%TOOLS_DIR%\PrinterService.xml"

echo [3/3] Installing FingerprintService...
%WINSW% install "%TOOLS_DIR%\FingerprintService.xml"

echo.
echo Starting services...
%WINSW% start "%TOOLS_DIR%\GloryAPI.xml"
%WINSW% start "%TOOLS_DIR%\PrinterService.xml"
%WINSW% start "%TOOLS_DIR%\FingerprintService.xml"

echo.
echo ==========================================
echo  Done! Check status: services.msc
echo  Logs: %LOG_DIR%
echo ==========================================
pause