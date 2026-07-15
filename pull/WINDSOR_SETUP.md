# Windsor.ai connection - one-time setup (Google Ads + Amazon + Walmart)

Meta stays on its own MCP pull. Windsor handles the other three. When done, one API key in
`pull/.windsor_creds.json` feeds all three channels into the daily refresh.

## Step 1 - Create a Windsor.ai account
Sign up at https://windsor.ai (there's a free trial). Use an email you control.

## Step 2 - Connect the three sources
In the Windsor dashboard, add/connect each source and authorize with the Google/Amazon/Walmart
account that can see TerraSlate:
- **Google Ads** -> connect -> pick the TerraSlate Ads account (180-097-3324).
- **Amazon Ads** (a.k.a. Amazon Advertising) -> connect -> pick the TerraSlate profile.
- **Walmart Connect** -> connect -> pick the TerraSlate advertiser.

You only need spend + performance data, so read access is enough.

## Step 3 - Get your API key
Windsor shows an **API key** in your account (often under Settings/Profile, or on the
"API"/"Data preview"/"Get data via API" page - the generated URL contains `api_key=...`).
Copy just the key.

## Step 4 - Put the key in the creds file
```bash
cd /Users/jayvee/Documents/ds-work/terraslate-marketing-dashboard
cp pull/.windsor_creds.json.example pull/.windsor_creds.json
# edit pull/.windsor_creds.json and paste your key into WINDSOR_API_KEY
```
This file is gitignored - it never leaves your machine.

## Step 5 - Tell Claude "the Windsor key is in place"
Then Claude runs `python3 pull/windsor.py`, confirms the exact field names against the real
response, backfills history (`--since 2025-01-01`), reconciles, renders, and verifies the
three channels live on the dashboard. No further manual steps after that - the daily refresh
runs `pull/windsor.py` automatically.

## Notes
- Windsor field names vary slightly by plan/connector; `pull/windsor.py` maps them tolerantly
  and Claude will confirm against your real data on the first run.
- For Amazon/Walmart, Windsor's ad connectors report ad-attributed sales, so on the dashboard
  TACoS will equal ACoS until a total-sales (organic) source is added later.
