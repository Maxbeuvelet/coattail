# ─────────────────────────────────────────────────────────────
#  Lean production run — serve the already-built app on :8000.
#  No rebuild (use serve.ps1 for that). This is what the on-boot
#  service runs. Paper mode by default.
# ─────────────────────────────────────────────────────────────
$root = $PSScriptRoot
Set-Location "$root\backend"
& "$root\backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
