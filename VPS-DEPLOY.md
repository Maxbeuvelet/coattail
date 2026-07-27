# Run Coattail 24/7 on a VPS

Deploys the whole app (dashboard + API + engine) in Docker, behind Caddy for
automatic HTTPS, on an always-on Linux server. Runs whether or not your PC is on.

```
 friends ─▶ https://coattail.net ─▶ VPS ─▶ Caddy (TLS) ─▶ app:8000 (Docker)
```

---

## Step 0 — Provision a VPS

Any small Linux VPS works. **1 GB RAM is plenty.** Good cheap options:
- **Hetzner** CX22 (~€4/mo) — EU/US regions
- **DigitalOcean** / **Vultr** / **Linode** basic droplet (~$5–6/mo)

Pick **Ubuntu 24.04**. Note the server's **public IP**. Open ports **22, 80, 443**
(most providers do by default, or via their firewall panel).

SSH in:
```bash
ssh root@YOUR_SERVER_IP
```

## Step 1 — ⚠️ Test the data-api FIRST (the geoblock check)

Before anything else, confirm this server can reach Polymarket's data-api. Run on
the VPS:
```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=ALL&orderBy=PNL&limit=5"
```
- **`200`** → 🎉 not blocked. Continue.
- **`403` / `000` / timeout** → this host/region is geoblocked. **Destroy the VPS
  and try a different region or provider** (EU regions like Hetzner Germany are
  often fine), then re-test. Don't proceed until you get `200`.

## Step 2 — Install Docker

```bash
curl -fsSL https://get.docker.com | sh
```

## Step 3 — Get the code

Clone your GitHub repo (push it first if you haven't — see the main README):
```bash
git clone https://github.com/YOUR_USERNAME/coattail.git
cd coattail
```

## Step 4 — Set your owner key

```bash
echo "OWNER_KEY=$(openssl rand -base64 18)" > .env
cat .env      # copy this key — you'll need it to unlock control
```

## Step 5 — Launch (works immediately on the IP)

```bash
docker compose up -d --build
```
First boot builds the image (~1–2 min). By default it serves plain HTTP, so open:

- **http://YOUR_SERVER_IP** — live, read-only, 24/7.
- **http://YOUR_SERVER_IP/?key=YOUR_OWNER_KEY** (once per device) to control it.

Watch startup with `docker compose logs -f` (Ctrl-C to stop watching).

## Step 6 — Add the domain + HTTPS (when you own it)

1. In your DNS, add **A records** → `coattail.net` and `www.coattail.net` →
   `YOUR_SERVER_IP` (Cloudflare users: **DNS only / grey cloud** for the first run).
   Confirm with `ping coattail.net`.
2. Tell Caddy to use the domain by adding a line to `.env`, then relaunch:
   ```bash
   echo "SITE_ADDRESS=coattail.net" >> .env
   docker compose up -d
   ```
   Caddy fetches a Let's Encrypt cert automatically (~30s) → **https://coattail.net**.

## Done

- Survives reboots (`restart: unless-stopped`). Your PC can be off.

---

## Day-to-day

**Update after code changes** (push from your dev machine, then on the VPS):
```bash
cd coattail && git pull && docker compose up -d --build
```

**Logs / status:**
```bash
docker compose logs -f app
docker compose ps
```

**Back up the paper book** (the SQLite volume):
```bash
docker run --rm -v coattail_app-data:/data -v $PWD:/backup alpine \
  tar czf /backup/coattail-backup.tgz -C /data .
```

**Reset the book:** Settings → Reset in the dashboard, or wipe the `app-data`
volume.

> Still paper mode. Before enabling **live trading** on a public server, we add a
> real login and lock down the server — a public box that moves real money is a
> different risk class.
