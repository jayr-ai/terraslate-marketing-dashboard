# TerraSlate Paper - Marketing Dashboard

Consolidated marketing dashboard for TerraSlate Paper. Facebook/Meta Ads is live; Google Ads,
Amazon, and Walmart are wired in incrementally (they show `NO DATA` until connected).

Live URL (after Pages is enabled): `https://<owner>.github.io/<repo>/`

## Refresh locally
```bash
python3 build_dashboard.py   # reconcile daily -> headline, derive ROAS/etc, write insights
python3 render.py            # fill template -> index.html (aborts on dashes / missing tokens)
python3 -m http.server 8000  # preview at http://localhost:8000/index.html
```
Then `git add -A && git commit -m "refresh" && git push` - the GitHub Action redeploys Pages.

## How the numbers stay honest
- `data.json` is the single source of truth; `render.py` injects numbers, so the HTML never drifts.
- `build_dashboard.py` blocks publish if daily rows do not reconcile to the headline totals.
- Meta revenue is derived from purchase ROAS (Meta gives no direct revenue field); the daily
  series reconciles to the account total exactly.
- Disconnected channels read `NO DATA` and are excluded from blended totals, never treated as zero.

## Daily automation
`.github/workflows/dashboard-daily.yml` deploys on every push and on a daily cron. Pulling fresh
Meta data in the cloud requires a Meta Graph API token (see the note in that file); until then,
refresh locally and push.
