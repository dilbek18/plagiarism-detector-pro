@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo DIQQAT: Internetdan manba qidirish uchun START_INTERNET_SERVER.bat ni oching.
echo HTML-only rejimda internet manba qidiruvi ishlamaydi.
pause
start "" "index.html"
