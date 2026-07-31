"""Find CURRENTLY-OPEN Polymarket US markets and check soccer overlap.
Signs path-only. Reads keys from .env (gitignored). Run from repo root."""
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
    sig = base64.b64encode(priv.sign(f"{ts}GET{path.split('?')[0]}".encode())).decode()
    req = urllib.request.Request(
        "https://api.polymarket.us" + path,
        headers={"X-PM-Access-Key": env["POLYMARKET_KEY_ID"], "X-PM-Timestamp": ts,
                 "X-PM-Signature": sig, "Content-Type": "application/json",
                 "User-Agent": "coattail/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "_body": e.read().decode(errors="replace")[:120]}


SOCCER = ["paok", "hammarby", "panathinaik", "auda", "tromso", "gent", "benfica",
          "rijeka", "larnaca", "flora", "derry", "new saints", "cherkasy"]

for q in [
    "/v1/markets?closed=false&limit=200",
    "/v1/markets?active=true&closed=false&limit=200",
    "/v1/markets?limit=200&offset=2000",
    "/v1/markets?status=open&limit=200",
]:
    data = get(q)
    if "_err" in data:
        print(f"\n{q}\n  HTTP {data['_err']} {data['_body']}"); continue
    ms = data.get("markets", [])
    soc = [m.get("question", "") for m in ms
           if any(s in m.get("question", "").lower() for s in SOCCER)]
    dates = sorted({m.get("endDate", "")[:10] for m in ms if m.get("endDate")})
    print(f"\n{q}\n  {len(ms)} markets | endDate range: {dates[:1]}..{dates[-1:]}"
          f" | SOCCER HITS: {len(soc)}")
    if soc:
        print("   ✓", soc[:4])
    print("   sample:", [m.get("question", "")[:34] for m in ms[:5]])
