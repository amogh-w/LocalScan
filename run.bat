@echo off
rem Starts Local Scan on port 8010 (scripts\server.py does the work).
rem   run.bat           normal use (double-click works too): server hidden, system-tray icon
rem   run.bat -Restart  restart the server hidden, no tray (quick, for trying a change)
rem   run.bat -Console  server in this window, with logs, the LAN URL and a QR code
rem   run.bat -Stop     stop the server
rem   run.bat -Dev      backend with auto-reload on :8010 + Vite dev server on :5173 (open :5173)
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

rem Install packages only when there is no venv yet or pyproject.toml / uv.lock changed since the last sync.
set SYNC=0
if not exist .venv\.synced set SYNC=1
if exist .venv\.synced (
    for /f %%f in ('dir /b /o:d pyproject.toml uv.lock .venv\.synced') do set NEWEST=%%f
)
if exist .venv\.synced if /i not "%NEWEST%"==".synced" set SYNC=1
if "%SYNC%"=="1" (
    echo Installing Python packages...
    uv sync || goto :end
    type nul > .venv\.synced
)

if /i "%~1"=="-Dev" (
    start "Vite dev server" /D frontend cmd /c npm run dev
    %PY% scripts\lan_qr.py 5173
    %PY% -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8010 --reload
    goto :end
)
if /i "%~1"=="-Restart" ( %PY% scripts\server.py & goto :end )
if /i "%~1"=="-Stop" ( %PY% scripts\server.py --stop & goto :end )
if /i "%~1"=="-Console" (
    %PY% scripts\lan_qr.py
    netsh advfirewall firewall show rule name="Local Scan 8010" >nul 2>&1
    if errorlevel 1 (
        echo If the phone can't connect, allow the port once ^(run this in an admin Command Prompt^):
        echo   netsh advfirewall firewall add rule name="Local Scan 8010" dir=in action=allow protocol=TCP localport=8010 profile=private
        echo.
    )
    %PY% scripts\server.py --console
    goto :end
)

start "" ".venv\Scripts\pythonw.exe" scripts\tray.py

:end
if errorlevel 1 (
    echo.
    echo Local Scan stopped with an error. See the messages above.
    pause
)
