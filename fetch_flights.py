"""Daily Google Flights price check via SerpApi for the May 2027 Japan trip.

Runs in GitHub Actions. Needs the SERPAPI_KEY environment variable (repo secret).
Uses only the Python standard library.

Writes:
  data/latest.json          summary of today's run (read by the Claude scheduled task)
  data/runs/YYYY-MM-DD.json same summary, kept per day
  data/history.csv          one row per search per day, for trend tracking
"""

import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Trip settings. Edit these to change what gets searched.
# Each search costs 1 SerpApi credit. 6 searches a day is about 186 a month,
# inside the free plan's 250.
# ---------------------------------------------------------------------------
OUT_DATE = "2027-05-07"
BACK_DATE = "2027-05-17"

TOKYO = "NRT,HND"
OSAKA = "KIX"

SEARCHES = [
    # label, from, to, outbound date, return date (None = one-way)
    ("BNE-TYO one-way", "BNE", TOKYO, OUT_DATE, None),
    ("BNE-KIX one-way", "BNE", OSAKA, OUT_DATE, None),
    ("TYO-BNE one-way", TOKYO, "BNE", BACK_DATE, None),
    ("KIX-BNE one-way", OSAKA, "BNE", BACK_DATE, None),
    ("BNE-TYO return", "BNE", TOKYO, OUT_DATE, BACK_DATE),
    ("BNE-KIX return", "BNE", OSAKA, OUT_DATE, BACK_DATE),
]

API_URL = "https://serpapi.com/search.json"
DATA_DIR = Path(__file__).parent / "data"
TOP_N = 5  # cheapest options kept per search


def serpapi_search(api_key, dep, arr, out_date, ret_date):
    params = {
        "engine": "google_flights",
        "departure_id": dep,
        "arrival_id": arr,
        "outbound_date": out_date,
        "type": "1" if ret_date else "2",  # 1 = round trip, 2 = one-way
        "currency": "AUD",
        "hl": "en",
        "gl": "au",
        "adults": "1",
        "travel_class": "1",  # economy
        "api_key": api_key,
    }
    if ret_date:
        params["return_date"] = ret_date
    url = API_URL + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=90) as resp:
        return json.load(resp)


def summarise_option(opt):
    legs = opt.get("flights", [])
    airlines = sorted({leg.get("airline", "?") for leg in legs})
    first, last = (legs[0], legs[-1]) if legs else ({}, {})
    return {
        "price": opt.get("price"),
        "airlines": ", ".join(airlines),
        "stops": max(len(legs) - 1, 0),
        "layovers": [l.get("id") or l.get("name") for l in opt.get("layovers", [])],
        "flight_numbers": [leg.get("flight_number") for leg in legs],
        "depart": first.get("departure_airport", {}).get("time"),
        "depart_airport": first.get("departure_airport", {}).get("id"),
        "arrive": last.get("arrival_airport", {}).get("time"),
        "arrive_airport": last.get("arrival_airport", {}).get("id"),
        "duration_min": opt.get("total_duration"),
    }


def summarise(label, dep, arr, out_date, ret_date, raw):
    options = [o for o in raw.get("best_flights", []) + raw.get("other_flights", []) if o.get("price")]
    options = [summarise_option(o) for o in options]
    options.sort(key=lambda o: o["price"])
    direct = [o for o in options if o["stops"] == 0]
    insights = raw.get("price_insights", {}) or {}
    return {
        "label": label,
        "from": dep,
        "to": arr,
        "outbound_date": out_date,
        "return_date": ret_date,
        "fare_type": "Return" if ret_date else "One-way",
        "cheapest": options[0] if options else None,
        "cheapest_direct": direct[0] if direct else None,
        "top_options": options[:TOP_N],
        "price_insights": {
            "lowest_price": insights.get("lowest_price"),
            "price_level": insights.get("price_level"),
            "typical_price_range": insights.get("typical_price_range"),
        },
        "google_flights_url": raw.get("search_metadata", {}).get("google_flights_url"),
        "error": raw.get("error"),
    }


def best_combined(results):
    """Cheapest whole trip per person: a return fare, or any outbound one-way plus any inbound one-way."""
    by_label = {r["label"]: r for r in results}

    def price(label, key):
        r = by_label.get(label)
        o = r and r.get(key)
        return o["price"] if o else None

    combos = {}
    for key, tag in (("cheapest", "any"), ("cheapest_direct", "direct")):
        candidates = []
        for out in ("BNE-TYO one-way", "BNE-KIX one-way"):
            for back in ("TYO-BNE one-way", "KIX-BNE one-way"):
                a, b = price(out, key), price(back, key)
                if a and b:
                    candidates.append((a + b, f"{out} + {back}"))
        for ret in ("BNE-TYO return", "BNE-KIX return"):
            p = price(ret, key)
            if p:
                candidates.append((p, ret))
        if candidates:
            total, how = min(candidates)
            combos[tag] = {"total_per_person": total, "made_up_of": how}
    return combos


def main():
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        sys.exit("SERPAPI_KEY is not set")

    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=10)))  # Brisbane
    today = now.date().isoformat()

    results = []
    for label, dep, arr, out_date, ret_date in SEARCHES:
        try:
            raw = serpapi_search(api_key, dep, arr, out_date, ret_date)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raw = {"error": f"{type(exc).__name__}: {exc}"}
        results.append(summarise(label, dep, arr, out_date, ret_date, raw))
        print(label, "->", (results[-1]["cheapest"] or {}).get("price"), results[-1]["error"] or "")

    summary = {
        "checked": today,
        "checked_at": now.isoformat(timespec="minutes"),
        "currency": "AUD",
        "per_person": True,
        "best_combined": best_combined(results),
        "searches": results,
    }

    (DATA_DIR / "runs").mkdir(parents=True, exist_ok=True)
    for path in (DATA_DIR / "latest.json", DATA_DIR / "runs" / f"{today}.json"):
        path.write_text(json.dumps(summary, indent=2))

    hist = DATA_DIR / "history.csv"
    new_file = not hist.exists()
    with hist.open("a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["checked", "search", "out", "back", "cheapest", "cheapest_airline", "cheapest_stops",
                        "cheapest_direct", "direct_airline", "price_level", "typical_low", "typical_high"])
        for r in results:
            c, d = r["cheapest"] or {}, r["cheapest_direct"] or {}
            rng = r["price_insights"]["typical_price_range"] or [None, None]
            w.writerow([today, r["label"], r["outbound_date"], r["return_date"] or "",
                        c.get("price", ""), c.get("airlines", ""), c.get("stops", ""),
                        d.get("price", ""), d.get("airlines", ""),
                        r["price_insights"]["price_level"] or "", rng[0], rng[1]])

    if all(r["error"] for r in results):
        sys.exit("Every search failed, check the API key and SerpApi quota")


if __name__ == "__main__":
    main()
