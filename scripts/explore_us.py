"""Probe Polymarket US endpoints to find the markets/events listing. Reads keys
from .env at runtime (gitignored). Run from repo root."""
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


candidates = [
    "/v1/markets?limit=3",
    "/v1/markets",
    "/v1/events?limit=3",
    "/v1/events",
    "/v1/refdata/symbols",
    "/v1/instruments?limit=3",
    "/v1/marketdata/markets?limit=3",
    "/v1/search?q=PAOK",
]
for path in candidates:
    code, body = get(path)
    flag = "  <== 200 OK" if code == 200 else ""
    print(f"\nHTTP {code}  {path}{flag}\n  {body[:180]}")
