#!/usr/bin/env python3
"""Fetch NSE quotes for the watchlist via Angel One SmartAPI (READ-ONLY).

Only two API calls are made: login (loginByPassword) and market-data quote.
No order/portfolio endpoints are touched. Secrets come from env vars only;
nothing is written into the repo or the published page.
"""
import json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta

import pyotp

API = "https://apiconnect.angelone.in"
HEADERS_BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-UserType": "USER",
    "X-SourceID": "WEB",
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP": "127.0.0.1",
    "X-MACAddress": "00:00:00:00:00:00",
}
IST = timezone(timedelta(hours=5, minutes=30))

def post(path, body, headers):
    req = urllib.request.Request(
        API + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def main():
    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    mpin = os.environ["ANGEL_MPIN"]
    totp_secret = os.environ["ANGEL_TOTP_SECRET"]

    with open("docs/watchlist.json") as f:
        watchlist = json.load(f)

    h = dict(HEADERS_BASE, **{"X-PrivateKey": api_key})
    login = post(
        "/rest/auth/angelbroking/user/v1/loginByPassword",
        {"clientcode": client_code, "password": mpin,
         "totp": pyotp.TOTP(totp_secret).now()},
        h,
    )
    if not login.get("status"):
        print("LOGIN FAILED:", login.get("errorcode"), login.get("message"))
        sys.exit(1)
    jwt = login["data"]["jwtToken"]

    hq = dict(h, **{"Authorization": "Bearer " + jwt})
    quote = post(
        "/rest/secure/angelbroking/market/v1/quote/",
        {"mode": "FULL",
         "exchangeTokens": {"NSE": [w["token"] for w in watchlist]}},
        hq,
    )
    if not quote.get("status"):
        print("QUOTE FAILED:", quote.get("errorcode"), quote.get("message"))
        sys.exit(1)

    by_token = {d["symbolToken"]: d for d in quote["data"].get("fetched", [])}
    out = []
    for w in watchlist:
        d = by_token.get(w["token"])
        if not d:
            out.append({"name": w["name"], "symbol": w["symbol"], "error": True})
            continue
        ltp = d.get("ltp") or 0
        prev = d.get("close") or 0
        change = round(ltp - prev, 2)
        pct = round((change / prev) * 100, 2) if prev else 0
        out.append({
            "name": w["name"], "symbol": w["symbol"],
            "ltp": ltp, "change": change, "pct": pct,
            "open": d.get("open"), "high": d.get("high"),
            "low": d.get("low"), "prev_close": prev,
            "volume": d.get("tradeVolume") or d.get("totalTradedVolume"),
            "feed_time": d.get("exchFeedTime") or d.get("exchTradeTime"),
        })

    now = datetime.now(IST)
    payload = {
        "updated_at_ist": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "updated_ts": int(now.timestamp()),
        "quotes": out,
    }
    with open("docs/quotes.json", "w") as f:
        json.dump(payload, f, indent=1)
    print("OK", payload["updated_at_ist"], "-", len(out), "quotes")

if __name__ == "__main__":
    main()
