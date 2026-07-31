"""Deep scan of open Polymarket US markets: is there ANY soccer? Signs path-only.
Reads keys from .env (gitignored). Run from repo root."""
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

TEAMS = ["paok","hammarby","panathinaik","auda","tromso","gent","benfica","rijeka",
         "larnaca","flora","derry","cherkasy","kyiv","hajduk","dynamo","celtic","arsenal"]
SOCCER_WORDS = ["fc ","fk ","sc ","cf ","1st half","o/u","draw"]

seen=set(); questions=[]; first=None
for off in range(0, 12001, 200):
    d = get(f"/v1/markets?closed=false&limit=200&offset={off}")
    if "_err" in d: print("stopped:",d); break
    ms = d.get("markets",[])
    if not ms: break
    if first is None: first = ms[0]
    for m in ms:
        q=m.get("question",""); questions.append(q)
    time.sleep(0.08)

print("first market ALL fields:", list(first.keys()) if first else None)
print("total open markets scanned:", len(questions))
team_hits=[q for q in questions if any(t in q.lower() for t in TEAMS)]
word_hits=[q for q in questions if any(w in q.lower() for w in SOCCER_WORDS)]
print("EXACT team hits:", len(team_hits), team_hits[:6])
print("soccer-word hits:", len(word_hits), word_hits[:6])
# distinct-ish sample of what IS there
import collections
firsts=collections.Counter(q.split(" vs")[0].split(":")[0][:14] for q in questions)
print("most common market prefixes:", firsts.most_common(12))
