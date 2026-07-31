"""Explore / diagnose the Polymarket US API. Reads keys from .env at runtime
(gitignored); no secrets stored here. Run from repo root:
    python3 scripts/explore_us.py
"""
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
    sig = base64.b64encode(priv.sign(f"{ts}GET{path}".encode())).decode()
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


for path in ["/v1/refdata/instruments", "/v1/portfolio/positions", "/v1/portfolio/balance"]:
    code, body = get(path)
    print(f"\n=== {path}  ->  HTTP {code} ===")
    print(body[:800])

# also: what does the US site think of this server's IP?
try:
    with urllib.request.urlopen("https://polymarket.us/api/geoblock", timeout=15) as r:
        print("\n=== geoblock (this server's IP) ===\n" + r.read().decode()[:300])
except Exception as e:
    print("\ngeoblock check:", e)
