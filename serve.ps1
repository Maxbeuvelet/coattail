# ─────────────────────────────────────────────────────────────
#  Serve the WHOLE app (dashboard + API) as one server on your
#  network, so your phone/other devices can reach it.
#
#  On the same Wi-Fi:  http://<this-pc-ip>:8000
#  From anywhere:      put this PC on Tailscale, use its 100.x IP
#
#  Paper mode by default — no real money. Ctrl-C to stop.
# ─────────────────────────────────────────────────────────────
$root = $PSScriptRoot

Write-Host "Building the dashboard..." -ForegroundColor Cyan
Push-Location "$root\frontend"
npm run build
Pop-Location

# Show the LAN address to open on your phone.
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
  Select-Object -First 1 -ExpandProperty IPAddress)
Write-Host ""
Write-Host "Serving on your network. On this PC:  http://localhost:8000" -ForegroundColor Green
if ($ip) { Write-Host "On your phone (same Wi-Fi):           http://${ip}:8000" -ForegroundColor Green }
Write-Host ""

Push-Location "$root\backend"
.\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Pop-Location
