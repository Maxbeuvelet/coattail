# Going live on coattail.net

Public site at `https://coattail.net`, served from this PC via a **Cloudflare
Tunnel**, running 24/7. Visitors get the read-only dashboard; you control it with
your owner key. The bot stays on this machine (the Polymarket data-api is
geoblocked from cloud hosts).

```
 friends ──▶ https://coattail.net ──▶ Cloudflare ──▶ Tunnel ──▶ localhost:8000 (this PC)
                                                                    the app + engine
```

## Step 1 — YOUR part (needs your accounts)

1. Create a free account at https://dash.cloudflare.com
2. **Add a site** → enter `coattail.net` → pick the **Free** plan.
3. Cloudflare shows you **two nameservers** (e.g. `xxx.ns.cloudflare.com`).
4. Log in to the registrar where you bought `coattail.net` and **replace its
   nameservers** with Cloudflare's two. Save.
5. Wait until Cloudflare shows the domain as **Active** (usually minutes, up to a
   few hours). You'll get an email.

Tell me when it's Active — then I do the rest.

## Step 2 — MY part (once the domain is Active)

I'll run, on this PC:
```powershell
# authenticate cloudflared to your Cloudflare account (opens your browser once)
./bin/cloudflared.exe tunnel login

# create the tunnel and point the domain at it
./bin/cloudflared.exe tunnel create coattail
./bin/cloudflared.exe tunnel route dns coattail coattail.net
./bin/cloudflared.exe tunnel route dns coattail www.coattail.net
```
Then I fill in `deploy/cloudflared-config.yml` from the example, and install both
pieces as **on-boot services** so the site is always up:
```powershell
# the app (uvicorn on :8000)  → a scheduled task / service running run-server.ps1
# the tunnel                  → cloudflared service install --config deploy/cloudflared-config.yml
```

## Result

- **Friends:** `https://coattail.net` — live, read-only.
- **You:** `https://coattail.net/?key=<OWNER_KEY>` once per device to unlock control.
- Survives reboots; no commands to run day-to-day.

> Still paper mode. Before enabling **live trading** on a public domain, we add a
> real login — the owner key alone isn't enough protection for a page that moves
> real money.
