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
