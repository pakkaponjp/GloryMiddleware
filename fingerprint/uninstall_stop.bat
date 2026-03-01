cd /d "%~dp0"
net stop "ZKBIOOnline Service"
ZKBioOnline.exe -d
pause