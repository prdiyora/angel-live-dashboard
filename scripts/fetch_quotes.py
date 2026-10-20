#!/usr/bin/env python3
"""Fetch NSE quotes + (optionally) encrypted holdings via Angel One SmartAPI.

READ-ONLY: only loginByPassword, market quote and getAllHolding are called.
Secrets come from env vars only. Holdings are encrypted with AES-256-GCM
(PBKDF2-SHA256, 1M iterations) before they touch the repo - the passphrase
never leaves GitHub secrets / the user's own browser.
"""
import base64, json, os, sys, urllib.request
from datetime import datetime, timezone, timedelta

import pyotp

API = "https://apiconnect.angelone.in"
HEADERS_BASE = {
    "Content-Type": "application/json", "Accept": "application/json",
    "X-UserType": "USER", "X-SourceID": "WEB",
    "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
    "X-MACAddress": "00:00:00:00:00:00",
}
IST = timezone(timedelta(hours=5, minutes=30))
PBKDF2_ITER = 1_000_000

def call(path, body=None, headers=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers,
                                 method=method or ("POST" if body is not None else "GET"))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def encrypt_holdings(holdings_payload, passphrase):
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    key = kdf.derive(passphrase.encode())
    ct = AESGCM(key).encrypt(iv, json.dumps(holdings_payload).encode(), None)
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": PBKDF2_ITER,
            "salt": base64.b64encode(salt).decode(),
            "iv": base64.b64encode(iv).decode(),
            "ct": base64.b64encode(ct).decode()}

# NSE trading holidays 2026 (NSE circular 172/2025). On these dates the
# market is closed; skip everything so no stale no-op commits happen and the
# dashboard keeps showing the last trading day's close.
NSE_HOLIDAYS_2026 = {
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14",
    "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}

def main():
    today_ist = datetime.now(IST).strftime("%Y-%m-%d")
    if today_ist in NSE_HOLIDAYS_2026:
        print("NSE holiday today - market closed, nothing to do")
        return
    api_key = os.environ["ANGEL_API_KEY"]
    client_code = os.environ["ANGEL_CLIENT_CODE"]
    mpin = os.environ["ANGEL_MPIN"]
    totp_secret = os.environ["ANGEL_TOTP_SECRET"]
    passphrase = os.environ.get("ANGEL_DASH_PASSPHRASE", "").strip()

    with open("docs/watchlist.json") as f:
        watchlist = json.load(f)

    h = dict(HEADERS_BASE, **{"X-PrivateKey": api_key})
    login = call("/rest/auth/angelbroking/user/v1/loginByPassword",
                 {"clientcode": client_code, "password": mpin,
                  "totp": pyotp.TOTP(totp_secret).now()}, h)
    if not login.get("status"):
        print("LOGIN FAILED:", login.get("errorcode"), login.get("message"))
        sys.exit(1)
    jwt = login["data"]["jwtToken"]
    hq = dict(h, **{"Authorization": "Bearer " + jwt})

    quote = call("/rest/secure/angelbroking/market/v1/quote/",
                 {"mode": "FULL",
                  "exchangeTokens": {"NSE": [w["token"] for w in watchlist]}}, hq)
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
        out.append({"name": w["name"], "symbol": w["symbol"], "ltp": ltp,
                    "change": change, "pct": pct, "open": d.get("open"),
                    "high": d.get("high"), "low": d.get("low"), "prev_close": prev,
                    "volume": d.get("tradeVolume") or d.get("totalTradedVolume"),
                    "feed_time": d.get("exchFeedTime") or d.get("exchTradeTime")})

    now = datetime.now(IST)
    with open("docs/quotes.json", "w") as f:
        json.dump({"updated_at_ist": now.strftime("%Y-%m-%d %H:%M:%S IST"),
                   "updated_ts": int(now.timestamp()), "quotes": out}, f, indent=1)
    print("OK quotes", now.strftime("%H:%M IST"), "-", len(out))

    if not passphrase:
        print("holdings: skipped (no passphrase secret yet)")
        return

    funds = {}
    rms = call("/rest/secure/angelbroking/user/v1/getRMS", headers=hq)
    if rms.get("status") and rms.get("data"):
        d = rms["data"]
        def num(x):
            try: return round(float(x), 2)
            except (TypeError, ValueError): return None
        used_parts = ["utiliseddebits", "utilisedspan", "utilisedexposure",
                      "utilisedoptionpremium", "utilisedholdingsales",
                      "utilisedturnover", "utilisedpayout"]
        used = sum(num(d.get(k)) or 0 for k in used_parts)
        funds = {"available_cash": num(d.get("availablecash")),
                 "net": num(d.get("net")),
                 "collateral": num(d.get("collateral")),
                 "used_margin": round(used, 2),
                 "m2m_unrealized": num(d.get("m2munrealized")),
                 "m2m_realized": num(d.get("m2mrealized"))}
        print("OK funds - available_cash present:", funds["available_cash"] is not None)
    else:
        print("FUNDS FAILED (continuing):", rms.get("errorcode"), rms.get("message"))

    hold = call("/rest/secure/angelbroking/portfolio/v1/getAllHolding", headers=hq)
    if not hold.get("status"):
        print("HOLDINGS FAILED (quotes still saved):", hold.get("errorcode"), hold.get("message"))
        return
    data = hold.get("data") or {}
    rows = data.get("holdings", data if isinstance(data, list) else [])
    items = []
    for x in rows:
        qty = (x.get("quantity") or 0) + (x.get("t1quantity") or 0)
        avg = x.get("averageprice") or 0
        ltp = x.get("ltp") or 0
        items.append({"name": x.get("tradingsymbol"), "exch": x.get("exchange"),
                      "qty": qty, "avg": round(avg, 2), "ltp": ltp,
                      "invested": round(avg * qty, 2), "current": round(ltp * qty, 2),
                      "pnl": x.get("profitandloss"), "pnl_pct": x.get("pnlpercentage")})
    t = data.get("totalholding") or {}
    totals = {"invested": t.get("totalinvvalue"), "current": t.get("totalholdingvalue"),
              "pnl": t.get("totalprofitandloss"), "pnl_pct": t.get("totalpnlpercentage")}
    payload = {"holdings": items, "totals": totals, "funds": funds}
    enc = encrypt_holdings(payload, passphrase)
    enc["updated_at_ist"] = now.strftime("%Y-%m-%d %H:%M:%S IST")
    enc["count"] = len(items)
    with open("docs/holdings.enc.json", "w") as f:
        json.dump(enc, f, indent=1)
    print("OK holdings encrypted -", len(items), "rows")

if __name__ == "__main__":
    main()
