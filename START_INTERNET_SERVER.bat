@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Internet Detector Pro - Internet Server
set LOG=%CD%\start_error.log
set PYTHONUTF8=1
set PIP_DISABLE_PIP_VERSION_CHECK=1

echo ======================================================
echo  Internet Source Plagiarism Detector Pro
echo  Internet Server: web + ilmiy + universitet manbalari
echo ======================================================
echo.
echo [%DATE% %TIME%] START > "%LOG%"
echo Papka: %CD% >> "%LOG%"

REM --- Eng ko'p uchraydigan xato: ZIP ichidan to'g'ridan-to'g'ri ochish ---
echo %CD% | find /I "\Temp\Rar$" >nul
if not errorlevel 1 (
  echo DIQQAT: Siz faylni WinRAR ichidan ochganga o'xshaysiz.
  echo Avval ZIP ni Desktopga yoki Documentsga EXTRACT qiling, keyin START_WINDOWS_SAFE.bat ni oching.
  echo DIQQAT: WinRAR temp papkasi aniqlandi. >> "%LOG%"
  echo.
)

if not exist "backend\main.py" (
  echo XATO: backend\main.py topilmadi.
  echo ZIP faylni to'liq Extract qiling. WinRAR ichidan to'g'ridan-to'g'ri ochmang.
  echo XATO: backend\main.py topilmadi. >> "%LOG%"
  pause
  exit /b 1
)

if not exist "index.html" (
  echo XATO: index.html topilmadi.
  echo ZIP faylni to'liq Extract qiling. WinRAR ichidan to'g'ridan-to'g'ri ochmang.
  echo XATO: index.html topilmadi. >> "%LOG%"
  pause
  exit /b 1
)

REM requirements.txt bo'lmasa, avtomatik yaratadi
if not exist "backend\requirements.txt" (
  echo DIQQAT: backend\requirements.txt topilmadi, yangidan yaratilmoqda...
  > "backend\requirements.txt" echo fastapi^>=0.110
  >> "backend\requirements.txt" echo uvicorn[standard]^>=0.29
  >> "backend\requirements.txt" echo pydantic^>=2.6
  >> "backend\requirements.txt" echo python-multipart^>=0.0.9
  >> "backend\requirements.txt" echo httpx^>=0.27
  >> "backend\requirements.txt" echo python-dotenv^>=1.0
)

set PY=
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; print(sys.version)" >nul 2>>"%LOG%"
  if not errorlevel 1 set PY=py -3
)
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; print(sys.version)" >nul 2>>"%LOG%"
    if not errorlevel 1 set PY=python
  )
)
if not defined PY (
  echo XATO: Python topilmadi.
  echo Python 3.10 yoki undan yuqorisini o'rnating. O'rnatishda "Add python.exe to PATH" ni belgilang.
  echo XATO: Python topilmadi. >> "%LOG%"
  pause
  exit /b 1
)

echo Python topildi: %PY%
%PY% -c "import sys; print(sys.executable); print(sys.version)" >> "%LOG%" 2>&1

if not exist "backend\.env" (
  if exist "backend\.env.example" (
    copy "backend\.env.example" "backend\.env" >nul
  ) else (
    > "backend\.env" echo SEARCH_PROVIDER=internet_server_all
    >> "backend\.env" echo ALLOW_ORIGINS=*
  )
  echo Internet Server sozlamasi yaratildi. Avtomatik qidiruv ishlaydi.
)

if not exist ".venv\Scripts\python.exe" (
  echo Virtual muhit yaratilmoqda...
  %PY% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo XATO: virtual muhit yaratilmadi. Tafsilot: start_error.log
    type "%LOG%"
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo XATO: virtual muhit faollashmadi.
  echo .venv papkasini o'chirib, qayta START_WINDOWS_SAFE.bat ni oching.
  echo XATO: venv activate failed >> "%LOG%"
  pause
  exit /b 1
)

echo Paketlar o'rnatilmoqda... Internet kerak bo'ladi.
python -m pip install --upgrade pip setuptools wheel >> "%LOG%" 2>&1

REM Avval to'g'ridan-to'g'ri asosiy paketlarni o'rnatamiz. requirements muammosi bo'lsa ham ishlaydi.
python -m pip install fastapi "uvicorn[standard]" pydantic python-multipart httpx python-dotenv >> "%LOG%" 2>&1
if errorlevel 1 (
  echo XATO: pip paketlarni o'rnata olmadi. Internet/PIP muammosi. Tafsilot: start_error.log
  type "%LOG%"
  pause
  exit /b 1
)

REM requirements.txt bor bo'lsa qo'shimcha tekshiruv. Xato chiqsa ham asosiy paketlar o'rnatilgan bo'lishi mumkin.
python -m pip install -r "backend\requirements.txt" >> "%LOG%" 2>&1

python -c "import fastapi, uvicorn, httpx, dotenv; from backend.main import app; print('Internet Server import OK')" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo XATO: Internet Server ishga tayyor emas. Tafsilot: start_error.log
  type "%LOG%"
  pause
  exit /b 1
)

echo.
echo Internet Server ishga tushmoqda: http://127.0.0.1:8000
echo Brauzer 5 soniyadan keyin ochiladi. Qora oynani yopmang.
start "" cmd /c "timeout /t 5 /nobreak >nul && start "" "http://127.0.0.1:8000""
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

echo.
echo Server to'xtadi. Agar xato bo'lsa start_error.log faylini yuboring.
pause
