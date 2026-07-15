# Google Ads connection - one-time setup

The Google Ads API needs 6 values. Collect them, put them in `pull/.google_creds.json`
(copy `pull/.google_creds.json.example`), and the daily refresh starts including Google Ads.
Nothing here is shared with anyone - the file stays on your machine and is gitignored.

## The 6 values

| Key | What it is | Where to get it |
|---|---|---|
| `GOOGLE_ADS_DEVELOPER_TOKEN` | API access token for your Google Ads manager account | Google Ads (manager/MCC) -> Tools & Settings -> Setup -> **API Center** -> apply for **Basic access** |
| `GOOGLE_ADS_CLIENT_ID` | OAuth client id | Google Cloud Console -> Credentials (see step 2) |
| `GOOGLE_ADS_CLIENT_SECRET` | OAuth client secret | same OAuth client |
| `GOOGLE_ADS_REFRESH_TOKEN` | long-lived OAuth token | OAuth Playground (see step 3) |
| `GOOGLE_ADS_LOGIN_CUSTOMER_ID` | manager (MCC) account id, digits only | top-right in your Google Ads **manager** account (e.g. `123-456-7890` -> `1234567890`) |
| `GOOGLE_ADS_CUSTOMER_ID` | TerraSlate's Google Ads account id, digits only | top-right when viewing the **TerraSlate** account |

If TerraSlate is not under a manager account, set `GOOGLE_ADS_LOGIN_CUSTOMER_ID` to the same
value as `GOOGLE_ADS_CUSTOMER_ID` (but note: developer tokens are issued to manager accounts,
so you'll likely create/have one).

## Step 1 - Developer token (the slow one, start first)
In the Google Ads **manager** account: Tools & Settings -> Setup -> **API Center**. Copy the
developer token and apply for **Basic access**. Google reviews this; it can take 1-3 business
days. A token with only *Test* access cannot read TerraSlate's real data, so wait for Basic.

## Step 2 - OAuth client (Google Cloud Console)
1. https://console.cloud.google.com -> create or pick a project.
2. **APIs & Services -> Library ->** enable **Google Ads API**.
3. **OAuth consent screen**: User type External, add your own Google account as a Test user,
   add scope `https://www.googleapis.com/auth/adwords`.
4. **Credentials -> Create credentials -> OAuth client ID -> Application type: Web application**.
   Under "Authorized redirect URIs" add exactly: `https://developers.google.com/oauthplayground`
5. Copy the **Client ID** and **Client secret**.

## Step 3 - Refresh token (OAuth Playground)
1. https://developers.google.com/oauthplayground -> gear icon (top right) ->
   check **Use your own OAuth credentials** -> paste your Client ID + Secret.
2. In the left "Input your own scopes" box, enter `https://www.googleapis.com/auth/adwords`
   -> **Authorize APIs** -> sign in with the Google account that can see TerraSlate.
3. Click **Exchange authorization code for tokens** -> copy the **Refresh token**.

## Step 4 - Fill the creds file
```bash
cd /Users/jayvee/Documents/ds-work/terraslate-marketing-dashboard
cp pull/.google_creds.json.example pull/.google_creds.json
# then edit pull/.google_creds.json and paste in your 6 values
```

## Step 5 - Test + backfill history
```bash
python3 pull/google_ads.py                                   # last 30 days
python3 pull/google_ads.py --since 2025-01-01 --until 2026-07-13   # backfill history
python3 build_dashboard.py && python3 render.py               # reconcile + render
```
If the test prints spend/revenue/orders, it worked. If Google rejects the API version, set
`GOOGLE_ADS_API_VERSION` in the creds file to a current version (e.g. `v19`, `v20`).

Once the file exists, the daily 6am refresh runs `pull/google_ads.py` automatically - no
further manual steps.
