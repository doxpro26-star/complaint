# UptimeRobot — Keep Render Free Tier Awake 🤖

Render free web services **sleep after ~15 min of no traffic** (cold start 30-50s).
UptimeRobot pings your app every 5 minutes so it stays warm.

## 1. What we added in code
- `GET /healthz` → `200` JSON: `{"status":"ok","uptime_seconds":123,"db":"ok"}`
  - Fast, no auth, no DB writes — perfect for monitors.
  - UptimeRobot keyword check: `ok`
- `GET /status` → human-friendly status page (Alderway-themed) showing uptime.
- `render.yaml` health check already points to `/healthz`.

## 2. Create UptimeRobot monitor (free, 5 min)
1. Sign up at https://uptimerobot.com → Dashboard → **Add New Monitor**
2. Settings:
   - Monitor Type: **HTTP(s)**
   - Friendly Name: `civicfix-complaint`
   - URL: `https://YOUR-APP.onrender.com/healthz`
   - Monitoring Interval: **5 Minutes**
   - Keyword check (optional but recommended):
     - Keyword Type: **Exists**, Keyword Value: `ok`
     - Alert when keyword **not exists**
3. Alert Contacts: add email / Slack / Discord webhook.
4. Create → wait 5-10 min → status turns **Up** (green).

## 3. Verify
```bash
curl https://YOUR-APP.onrender.com/healthz
# {"db":"ok","status":"ok","uptime_seconds":42}

curl https://YOUR-APP.onrender.com/status
# pretty HTML page with uptime
```

## 4. How it prevents Render sleep
```
UptimeRobot (every 5 min) ──GET /healthz──▶ Render web service
                                         ◀── 200 {"status":"ok"}
```
Traffic never idles >15 min → no spin-down → citizens/engineers get instant loads.

## 5. Optional upgrades
- Add 2nd monitor for `/status` (keyword: `All systems normal`).
- Add status badge to README:
  `[![UptimeRobot](https://img.shields.io/uptimerobot/ratio/mXXXX.svg)]`
- For production: move SQLite → Render Postgres (persistent disk) — ping code unchanged.

## 6. Cost
- UptimeRobot free: 50 monitors × 5-min interval. Enough for this project.
