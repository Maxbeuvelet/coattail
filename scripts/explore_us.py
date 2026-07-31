"""Fetch the exact Henan/Dalian event by slug + find the events endpoint.
Signs path-only. Reads keys from .env. Run from repo root."""
import time, base64, json, urllib.request, urllib.error
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import ed25519

env = {}
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
priv = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(env["POLYMARKET_SECRET_KEY"])[:32])

def get(path):
    ts = str(int(time.time()*1000))
    sig = base64.b64encode(priv.sign(f"{ts}GET{path.split('?')[0]}".encode())).decode()
    req = urllib.request.Request("https://api.polymarket.us"+path, headers={
        "X-PM-Access-Key": env["POLYMARKET_KEY_ID"], "X-PM-Timestamp": ts,
        "X-PM-Signature": sig, "Content-Type": "application/json", "User-Agent": "coattail/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.getcode(), r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:150]

SLUG = "csl-hen-ygb-2026-07-31"
for path in [
    f"/v1/events/{SLUG}",
    f"/v1/markets/{SLUG}",
    f"/v1/events?slug={SLUG}",
    f"/v1/markets?slug={SLUG}",
    "/v1/events?limit=3",
    "/v1/events?closed=false&limit=3",
]:
    code, body = get(path)
    tag = "  <== HIT" if code == 200 else ""
    print(f"\nHTTP {code}  {path}{tag}")
    if code == 200:
        print(body[:1400])
