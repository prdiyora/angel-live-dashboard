# angel-live-dashboard

Clean, read-only live-price dashboard for the top 10 NSE stocks, powered by
Angel One SmartAPI. Hosted free on GitHub Pages; prices refresh about every
5 minutes during market hours via a GitHub Actions job.

## How it works

1. `.github/workflows/update-quotes.yml` runs Mon-Fri, ~08:30-16:25 IST.
2. `scripts/fetch_quotes.py` logs in to SmartAPI (client code + MPIN + TOTP,
   all from repo secrets), makes ONE batched quote call (FULL mode), and
   writes `docs/quotes.json`.
3. GitHub Pages serves `docs/`; the page auto-reloads every 60 s.

READ-ONLY by design: the script calls only `loginByPassword` and the
market-data quote endpoint. No order, portfolio or funds endpoints exist
anywhere in this repo.

## Setup (one time)

Repo secrets (Settings > Secrets and variables > Actions):
`ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_MPIN`, `ANGEL_TOTP_SECRET`

Pages: Settings > Pages > Deploy from branch `main`, folder `/docs`.

## Edit the watchlist

Edit `docs/watchlist.json` (name, symbol, Angel instrument token) right here
on GitHub. Tokens come from the SmartAPI scrip master. Next run picks it up.

## Limits (honest)

- Refresh is ~every 5 min (GitHub's scheduler can lag a few minutes more).
  True tick-by-tick would need the SmartAPI websocket on an always-on server.
- SmartAPI logs in fresh every run, so the daily token expiry never matters.
- Market data only; nothing about the account, holdings or orders is shown.
