@echo off
:: ============================================================
:: uninstall_services.bat
:: Uninstall Flask services
:: Run as Administrator
:: ============================================================

set TOOLS_DIR=C:\GloryMiddleware\tools
set WINSW=%TOOLS_DIR%\WinSW-x64.exe

echo ==========================================
echo  Glory Middleware — Uninstall Services
echo ==========================================

%WINSW% stop "%TOOLS_DIR%\GloryAPI.xml"
%WINSW% uninstall "%TOOLS_DIR%\GloryAPI.xml"

%WINSW% stop "%TOOLS_DIR%\PrinterService.xml"
%WINSW% uninstall "%TOOLS_DIR%\PrinterService.xml"

%WINSW% stop "%TOOLS_DIR%\FingerprintService.xml"
%WINSW% uninstall "%TOOLS_DIR%\FingerprintService.xml"

echo.
echo ==========================================
echo  Done! Services uninstalled.
echo ==========================================
pause