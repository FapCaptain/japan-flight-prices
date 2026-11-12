# Japan flight prices (May 2027)

A GitHub Action checks Google Flights via SerpApi every morning and saves the results in `data/`.
A Claude scheduled task then reads `data/latest.json`, logs it to the price sheet and sends a summary.

- Searches: BNE to Tokyo (NRT/HND) and Osaka (KIX), one-way each direction plus returns, 7 May out and 17 May back. 6 SerpApi credits a day (about 186 a month, free plan is 250).
- Change dates or routes at the top of `fetch_flights.py`.
- Run it manually: Actions tab, "Daily flight prices", "Run workflow".

## Setup

1. Settings, Secrets and variables, Actions, New repository secret: name `SERPAPI_KEY`, value your SerpApi API key.
2. Actions tab: enable workflows if prompted, then run it once manually to test.
