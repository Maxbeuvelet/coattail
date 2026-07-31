"""Confirm ?slug= filtering + find the Chinese-Super-League market slug pattern.
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
            return json.loads(r.read().decode(errors="replace"))
    except urllib.error.HTTPError as e:
        return {"_err": e.code}

# 1) does ?slug= work with a KNOWN market slug?
print("=== slug filter test (known NFL slug) ===")
d = get("/v1/markets?slug=aec-nfl-lac-ten-2025-11-02")
print("returned", len(d.get("markets",[])), "market(s)")

# 2) try soccer market-slug candidates from the event slug
print("\n=== soccer market-slug candidates ===")
for s in ["csl-hen-ygb-2026-07-31","csl-hen-ygb-2026-07-31-moneyline",
          "csl-hen-ygb-2026-07-31-ml","hen-ygb-2026-07-31","csl-hen-ygb"]:
    n = len(get(f"/v1/markets?slug={s}").get("markets",[]))
    print(f"  slug={s} -> {n}")

# 3) deep scan SLUGS for 'csl' (Chinese Super League) to learn the real pattern
print("\n=== scanning slugs for 'csl'/soccer providers ===")
ids=set(); found=[]; prefixes={}; off=0; empty=0
while off<=20000:
    d=get(f"/v1/markets?limit=200&offset={off}")
    if "_err" in d: break
    ms=d.get("markets",[]); new=0
    for m in ms:
        i=m.get("id")
        if i in ids: continue
        ids.add(i); new+=1
        sl=m.get("slug","")
        pre=sl.split("-")[0] if sl else "?"
        prefixes[pre]=prefixes.get(pre,0)+1
        if "csl" in sl or "hen" in sl or "ygb" in sl:
            found.append((sl, m.get("question","")[:40]))
    if new==0: empty+=1
    if empty>=2 or not ms: break
    off+=200; time.sleep(0.05)
import collections
print("scanned", len(ids), "| slug prefixes:", collections.Counter(prefixes).most_common(15))
print("csl/hen/ygb slug hits:", len(found), found[:6])
