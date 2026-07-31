"""Hunt specifically for the soccer the user sees (Henan/Dalian) in the US API,
plus collect categories/tags. Signs path-only. Reads keys from .env. Run from root."""
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

# 1) quick filter-param attempts for "Henan"
print("--- filter-param attempts ---")
for p in ["/v1/markets?q=Henan","/v1/markets?search=Henan","/v1/markets?question=Henan","/v1/markets?title=Henan","/v1/markets?category=soccer&limit=3"]:
    d=get(p); n=len(d.get("markets",[])) if "_err" not in d else d
    print(f"  {p} -> {n}")

# 2) deep deduped scan, hunt Henan/Dalian/soccer, collect tags/categories
ids=set(); qs=[]; tags=set(); cats=set(); off=0; empty=0
while off<=40000:
    d=get(f"/v1/markets?closed=false&limit=200&offset={off}")
    if "_err" in d: print("stopped:",d); break
    ms=d.get("markets",[]); new=0
    for m in ms:
        mid=m.get("id")
        if mid in ids: continue
        ids.add(mid); new+=1; qs.append(m.get("question",""))
        cats.add(m.get("category","")); 
        for t in (m.get("tags") or []): tags.add(str(t)[:24])
    if new==0: empty+=1
    if empty>=3: break
    off+=200; time.sleep(0.06)

print(f"\nunique markets: {len(ids)}")
print("categories seen:", sorted(cats))
print("tags sample:", sorted(tags)[:40])
hits=[q for q in qs if any(w in q.lower() for w in ["henan","dalian","yingbo","chinese","super lg","soccer","football club"])]
print("Henan/Dalian/soccer hits:", len(hits), hits[:8])
