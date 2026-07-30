"""One-off explorer for the Polymarket US API — prints instrument + position
shapes so we can design the market-mapping layer. Reads keys from .env at
runtime (which is gitignored); no secrets are stored in this file.

Run from the repo root:  python3 scripts/explore_us.py
"""
import time, base64, json, urllib.request
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
    sig = base64.b64encode(priv.sign(f"{ts}GET{path}".encode())).decode()
    req = urllib.request.Request(
        "https://api.polymarket.us" + path,
        headers={
            "X-PM-Access-Key": env["POLYMARKET_KEY_ID"],
            "X-PM-Timestamp": ts,
            "X-PM-Signature": sig,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


print("=== INSTRUMENTS ===")
print(json.dumps(get("/v1/refdata/instruments"), indent=1)[:2200])
print("\n=== MY POSITIONS ===")
try:
    print(json.dumps(get("/v1/portfolio/positions"), indent=1)[:1500])
except Exception as e:
    print("positions err:", e)
