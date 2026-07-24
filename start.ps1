# ─────────────────────────────────────────────────────────────
#  Launch the copy-trade bot: backend (FastAPI) + frontend (Vite).
#  Opens each in its own window, then your browser. Close the
#  windows to stop. Paper mode by default — no real money.
# ─────────────────────────────────────────────────────────────
$root = $PSScriptRoot

Write-Host "Starting backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$root\backend'; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000"
)

Write-Host "Starting frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "cd '$root\frontend'; npm run dev"
)

Start-Sleep -Seconds 4
Start-Process "http://localhost:5173"
Write-Host "Dashboard opening at http://localhost:5173" -ForegroundColor Green
