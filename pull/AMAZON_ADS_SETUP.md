# Amazon Ads API connection - one-time setup

Amazon's API is the most involved of the platforms (there's an access-approval step), so start
early. You need 5 values in `pull/.amazon_creds.json`. Amazon only serves ~the last 60 days of
data via the API, so recent days come from here and deep history comes from your existing
Amazon sheet (a one-time CSV backfill, like we did for Google).

## The 5 values

| Key | What it is |
|---|---|
| `AMAZON_ADS_CLIENT_ID` | Login-with-Amazon (LWA) app client id |
| `AMAZON_ADS_CLIENT_SECRET` | LWA app client secret |
| `AMAZON_ADS_REFRESH_TOKEN` | OAuth refresh token (advertising scope) |
| `AMAZON_ADS_PROFILE_ID` | the advertising profile id for TerraSlate's US marketplace |
| `AMAZON_ADS_REGION` | `NA` (North America / US) |

## Step 1 - Request Amazon Ads API access (the slow one, start first)
Go to the Amazon Ads API onboarding: https://advertising.amazon.com/API/docs/en-us/onboarding/overview
Sign in with the Amazon account that manages TerraSlate's advertising, and request **API
access** for the account. Amazon reviews this; it can take a few days. You cannot pull real
data until this is granted.

## Step 2 - Create a Login with Amazon (LWA) security profile
1. Go to https://developer.amazon.com → **Login with Amazon** → **Create a New Security Profile**
   (name it e.g. "TerraSlate Dashboard").
2. Open the profile's **Web Settings** and note the **Client ID** and **Client Secret**.
3. Add an **Allowed Return URL**: `https://www.amazon.com` (used only to capture the auth code
   in the next step; any URL you control works).

## Step 3 - Get a refresh token (OAuth)
1. In a browser, visit this URL (replace CLIENT_ID and REDIRECT with your values, REDIRECT must
   match the Allowed Return URL above, URL-encoded):
   ```
   https://www.amazon.com/ap/oa?client_id=CLIENT_ID&scope=advertising::campaign_management&response_type=code&redirect_uri=REDIRECT
   ```
2. Approve. Amazon redirects to your return URL with `?code=XXXX` in the address bar - copy that code.
3. Exchange the code for tokens (run this in Terminal, filling in your values):
   ```bash
   curl -X POST https://api.amazon.com/auth/o2/token \
     -d "grant_type=authorization_code&code=THE_CODE&redirect_uri=REDIRECT&client_id=CLIENT_ID&client_secret=CLIENT_SECRET"
   ```
   The JSON response includes `"refresh_token": "Atzr|..."` - that's your `AMAZON_ADS_REFRESH_TOKEN`.

## Step 4 - Get your Profile ID
```bash
curl https://advertising-api.amazon.com/v2/profiles \
  -H "Authorization: Bearer ACCESS_TOKEN_FROM_STEP_3" \
  -H "Amazon-Advertising-API-ClientId: CLIENT_ID"
```
Pick the profile whose `countryCode` is `US` and `accountInfo.name` matches TerraSlate. Its
`profileId` is your `AMAZON_ADS_PROFILE_ID`.

## Step 5 - Fill the creds file and test
```bash
cd /Users/jayvee/Documents/ds-work/terraslate-marketing-dashboard
cp pull/.amazon_creds.json.example pull/.amazon_creds.json
# edit it and paste in your 5 values, then tell Claude "the Amazon creds are in"
```
Claude runs `python3 pull/amazon_ads.py`, confirms the report columns against the real
response, then wires it into the daily refresh. Deep history is loaded separately from your
Amazon sheet.

If a report column name is rejected on the first run, that's normal - Amazon's column ids vary
by ad product; Claude will adjust and rerun.
