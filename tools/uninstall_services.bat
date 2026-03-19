@echo off
:: ============================================================
:: uninstall_services.bat
:: Uninstall Flask services
:: Run as Administrator
:: ============================================================

set TOOLS_DIR=C:\GloryMiddleware\tools

echo ==========================================
echo  Glory Middleware - Uninstall Services
echo ==========================================

%TOOLS_DIR%\GloryAPI.exe stop
%TOOLS_DIR%\GloryAPI.exe uninstall

%TOOLS_DIR%\PrinterService.exe stop
%TOOLS_DIR%\PrinterService.exe uninstall

%TOOLS_DIR%\FingerprintService.exe stop
%TOOLS_DIR%\FingerprintService.exe uninstall

echo.
echo ==========================================
echo  Done! Services uninstalled.
echo ==========================================
pause