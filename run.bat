@echo off
rem Starts Local Scan: builds the frontend when needed, then serves everything on port 8010.
rem   run.bat          normal use (double-click works too): server hidden, system-tray icon (open, copy phone link, start with Windows)
rem   run.bat -Console server in this window, with logs, the LAN URL and a QR code
rem   run.bat -Dev     backend with auto-reload on :8010 + Vite dev server on :5173 (open :5173)
cd /d "%~dp0"

if not exist frontend\node_modules (
    echo Installing frontend packages...
    pushd frontend
    call npm install
    popd
)

if /i "%~1"=="-Dev" (
    start "Vite dev server" /D frontend cmd /c npm run dev
    uv run python scripts\lan_qr.py 5173
    uv run --extra paddle --directory backend uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
    goto :end
)

if /i not "%~1"=="-Console" (
    uv sync --extra paddle
    start "" ".venv\Scripts\pythonw.exe" scripts\tray.py
    goto :end
)

rem Exit code 0 from needs_build.py means the frontend is missing or older than its sources.
uv run python scripts\needs_build.py
if not errorlevel 1 (
    echo Building frontend...
    pushd frontend
    call npm run build
    popd
)

uv run python scripts\lan_qr.py

netsh advfirewall firewall show rule name="Local Scan 8010" >nul 2>&1
if errorlevel 1 (
    echo If the phone can't connect, allow the port once ^(run this in an admin Command Prompt^):
    echo   netsh advfirewall firewall add rule name="Local Scan 8010" dir=in action=allow protocol=TCP localport=8010 profile=private
    echo.
)

uv run --extra paddle --directory backend uvicorn app.main:app --host 0.0.0.0 --port 8010

:end
if errorlevel 1 (
    echo.
    echo Local Scan stopped with an error. See the messages above.
    pause
)
