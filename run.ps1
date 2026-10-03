# Starts Local Scan: builds the frontend when needed, then serves everything on port 8010.
#   .\run.ps1          normal use
#   .\run.ps1 -Dev     backend with auto-reload + Vite dev server on :5173
param([switch]$Dev)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Installing frontend packages..."
    Push-Location frontend; npm install; Pop-Location
}

if ($Dev) {
    Start-Process -NoNewWindow -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory "frontend"
    uv run --extra paddle --directory backend uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
    exit
}

$dist = "frontend\dist\index.html"
$newest = Get-ChildItem frontend\src, frontend\index.html, frontend\public -Recurse -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not (Test-Path $dist) -or $newest.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
    Write-Host "Building frontend..."
    Push-Location frontend; npm run build; Pop-Location
}

uv run python -c @'
import socket, qrcode
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]
except OSError:
    ip = "127.0.0.1"
url = f"http://{ip}:8010"
print(f"\n  On this PC:   http://localhost:8010\n  On the phone: {url}  (same Wi-Fi)\n")
q = qrcode.QRCode(border=1); q.add_data(url); q.print_ascii(invert=True)
'@

$rule = Get-NetFirewallRule -DisplayName "Local Scan 8010" -ErrorAction SilentlyContinue
if (-not $rule) {
    Write-Host "If the phone can't connect, allow the port once (admin PowerShell):" -ForegroundColor Yellow
    Write-Host '  New-NetFirewallRule -DisplayName "Local Scan 8010" -Direction Inbound -Protocol TCP -LocalPort 8010 -Action Allow -Profile Private' -ForegroundColor Yellow
}

uv run --extra paddle --directory backend uvicorn app.main:app --host 0.0.0.0 --port 8010
