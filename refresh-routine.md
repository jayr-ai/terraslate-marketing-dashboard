# TerraSlate dashboard - daily local refresh routine

This is the exact routine the scheduled task runs each morning. It uses the Meta Ads MCP
connector (so the Claude desktop app must be open and the connector authenticated). If any
step fails, STOP: do not push, leave the last good dashboard live, and report the failure.

Repo: `/Users/jayvee/Documents/ds-work/terraslate-marketing-dashboard`
Meta ad account: `24540744` (TerraSlate Paper)

## Steps

1. Compute two date windows from today's date:
   - current window = [today - 30 days, yesterday]
   - prior window   = [today - 60 days, today - 31 days]

2. Call `ads_get_ad_entities` for the CURRENT window (daily series) and save the raw result:
   - ad_account_id `24540744`, level `account`,
     fields `["amount_spent","impressions","clicks","actions:omni_purchase","purchase_roas"]`,
     time_range = current window, `time_increment` = `1`.
   - Save the raw tool output to `pull/_meta_daily.json`.

3. Call `ads_get_ad_entities` for the PRIOR window (single total, no time_increment) and save
   the raw output to `pull/_meta_prior.json`.

3b. Pull Google Ads (+ Walmart if connected) from Windsor.ai: `python3 pull/windsor.py`. Reads
   `pull/.windsor_creds.json` (or env), updates google/walmart (Meta + Amazon untouched).
   "missing WINDSOR_API_KEY"/"no rows" is EXPECTED until connected - continue anyway.

3c. Pull Amazon Ads from the Amazon Ads API: `python3 pull/amazon_ads.py`. Reads
   `pull/.amazon_creds.json` (or env), updates the amazon channel. "missing AMAZON_ADS_..." or
   "no Amazon rows" is EXPECTED until connected - continue anyway (Amazon stays NO DATA). The
   async report flow can take a couple of minutes. Only stop on an unexpected traceback.

4. Transform, reconcile, and render (all gates run here):
   ```bash
   cd /Users/jayvee/Documents/ds-work/terraslate-marketing-dashboard
   python3 pull/meta_from_mcp.py pull/_meta_daily.json pull/_meta_prior.json
   python3 build_dashboard.py
   python3 render.py
   ```
   If `build_dashboard.py` exits non-zero (reconcile failure) or `render.py` aborts, STOP.

5. Publish:
   ```bash
   git add data.json index.html
   git commit -m "chore: daily refresh $(date +%Y-%m-%d)"
   git push
   ```
   The GitHub Pages workflow redeploys automatically on push.

6. Report one line: date, spend, revenue, blended ROAS, orders, and the top insight from
   `data.json.insights`.

## Notes
- Revenue is derived from Meta's purchase ROAS (the MCP exposes no direct revenue field); the
  daily series reconciles to the account total exactly, which is the correctness guarantee.
- `_meta_daily.json` / `_meta_prior.json` are scratch files (gitignored); safe to overwrite.
- `data.json.daily[]` is long-term history, not just the current 30-day window: it powers the
  page's date-range toggle (Today / Yesterday / Last 7 Days / This Month / Last Month / This
  Quarter / This Year / Last Year) and the left-nav per-channel views. Each refresh only
  overwrites the days it just pulled and keeps everything older, so history grows over time.
  It was seeded once with `pull/backfill_merge.py` (see that file if history ever needs
  re-seeding, e.g. after a long outage).
