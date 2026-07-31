"""Search Polymarket US for the bot's whale markets. Signs PATH ONLY (no query).
Reads keys from .env (gitignored). Run from repo root."""
import time, base64, json, urllib.request, urllib.error
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

priv = ed25519.Ed25519PrivateKey.from_private_bytes(
    base64.b64decode(env["POLYMARKET_SECRET_KEY"])[:32]
)


def get(path):
    ts = str(int(time.time() * 1000))
    sign_path = path.split("?")[0]  # <-- sign path WITHOUT query string
    sig = base64.b64encode(priv.sign(f"{ts}GET{sign_path}".encode())).decode()
    req = urllib.request.Request(
        "https://api.polymarket.us" + path,
        headers={
            "X-PM-Access-Key": env["POLYMARKET_KEY_ID"],
            "X-PM-Timestamp": ts,
            "X-PM-Signature": sig,
            "Content-Type": "application/json",
            "User-Agent": "coattail/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.getcode(), r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")


print("=== one market's full shape (for mapping) ===")
code, body = get("/v1/markets?limit=1")
print(f"HTTP {code}\n{body[:900]}")

print("\n=== SEARCH for your whales' teams (does US carry them?) ===")
for team in ["PAOK", "Hammarby", "Panathinaikos", "Auda", "Chiefs"]:
    code, body = get(f"/v1/search?q={team}")
    print(f"\n[{team}] search -> HTTP {code}\n  {body[:220]}")
