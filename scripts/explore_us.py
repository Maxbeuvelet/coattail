"""Pull the soccer category from Polymarket US and check for the bot's teams.
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

# Does ?q= actually filter? dump the questions it returns.
print("=== ?q=Henan returns these questions ===")
for m in get("/v1/markets?q=Henan").get("markets", [])[:8]:
    print("  •", m.get("question","")[:55], "|", m.get("category",""))

# Pull soccer category, paginate, search for whale teams
print("\n=== category=soccer scan ===")
ids=set(); qs=[]; off=0; empty=0
while off<=20000:
    d=get(f"/v1/markets?category=soccer&closed=false&limit=200&offset={off}")
    if "_err" in d: print("stopped:",d); break
    ms=d.get("markets",[]); new=0
    for m in ms:
        i=m.get("id")
        if i in ids: continue
        ids.add(i); new+=1; qs.append(m.get("question",""))
    if new==0: empty+=1
    if empty>=2 or not ms: break
    off+=200; time.sleep(0.06)
print("unique soccer markets:", len(qs))
print("sample:", [q[:40] for q in qs[:12]])
TEAMS=["henan","dalian","paok","hammarby","panathinaik","auda","tromso","gent","new saints","flora","rijeka"]
hits=[q for q in qs if any(t in q.lower() for t in TEAMS)]
print("whale-team hits in soccer category:", len(hits), hits[:8])
