"""Scan the Polymarket US market list: categories + whether it carries the bot's
whale teams. Signs path-only. Reads keys from .env (gitignored). Run from root."""
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
        print("HTTP", e.code, e.read().decode(errors="replace")[:200]); return {}


questions, cats = [], {}
cursor, pages = None, 0
while pages < 30:
    data = get(f"/v1/markets?limit=200" + (f"&cursor={cursor}" if cursor else ""))
    ms = data.get("markets", [])
    for m in ms:
        questions.append(m.get("question", ""))
        c = m.get("category", "?"); cats[c] = cats.get(c, 0) + 1
    cursor = data.get("cursor") or data.get("nextCursor") or data.get("next")
    pages += 1
    if not ms or not cursor:
        break

print(f"scanned {len(questions)} markets across {pages} page(s)")
print("top-level keys of last response:", list(data.keys()))
print("categories:", cats)
print("\n--- does US carry your whale teams? ---")
for t in ["PAOK", "Hammarby", "Panathinaikos", "Auda", "Tromso", "Gent", "Benfica", "Rangers", "Chiefs", "soccer", "vs."]:
    hits = [q for q in questions if t.lower() in q.lower()]
    ex = (" e.g. " + hits[0]) if hits else ""
    print(f"  '{t}': {len(hits)}{ex[:60]}")
print("\n--- 20 sample market questions ---")
for q in questions[:20]:
    print("  •", q[:60])
