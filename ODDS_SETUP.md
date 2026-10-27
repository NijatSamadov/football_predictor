# Free odds collection

The account key belongs in local `.env`, beside `odds_collector.py`. Never put it
in `.env.example`, which is public source code. Both `.env` and all collected data
are excluded from Git. The collector never prints authenticated URLs or keys.

## Start on this computer

Double-click **START_ODDS_COLLECTION.cmd** in this folder, outside Codex, or run:

```powershell
python odds_collector.py watch
```

Keep that window open and the computer awake. Collection starts immediately, then
checks every 12 hours. Closing the window stops collection. This does not install
a Windows scheduled task or run when the computer is asleep. Restarting retains
the archives and respects the previous request's cooldown.

To check account access without spending odds credits:

```powershell
python odds_collector.py check
```

To collect once or inspect local status:

```powershell
python odds_collector.py collect
python odds_collector.py status
```

The collector alone uses Python's standard library. Install `requirements.txt` to
also generate the market-derived score forecasts. Use `--no-forecasts` to collect
prices without scientific Python dependencies. Missing forecasts do not discard
successfully collected odds.

## What is requested

- Premier League (`soccer_epl`), upcoming seven days.
- One bookmaker region (`eu`), decimal odds.
- Home/draw/away (`h2h`) and goal totals (`totals`).
- One league request can contain multiple fixtures and bookmakers.
- A free `/sports` check verifies account access and the credit headers before
  each due odds request. A malformed response or unknown quota stops spending.

Each odds request costs at most two credits under the documented current pricing
for these two markets and one region. Two pulls daily are about 120 credits per
30 days. The collector stops before account-wide used credits would exceed 200,
and keeps at least 50 credits remaining. Other applications using the same key
also count toward those limits. Actual provider quota headers are retained.
No payment or plan upgrade is required or performed.

## Files saved locally

- `data/odds/raw/*.json`: immutable response snapshots, safe request parameters,
  actual receive time, quota, raw provider records and checked pre-match markets.
- `data/odds/odds.sqlite3`: request/usage ledger and archive locations.
- `data/odds/forecasts/*.json`: pre-match market-Poisson picks, probabilities,
  expected points, model code hashes and source snapshot hashes.

A saved snapshot can contain no usable markets; `markets` counts usable bookmaker
markets. `event_observations` in status counts repeated event observations across
snapshots, not unique games. Empty or incomplete responses are not fabricated.

Normalized data exclude matches that have started by response receipt, future
quotes, quotes older than 24 hours, incomplete markets, invalid odds and two-way
winner markets. Raw responses are retained for audit and must not be used directly
as eligible pre-match model inputs.

The actual total line is preserved. The new market model supports half-goal lines
such as 1.5, 2.5 and 3.5. Integer/quarter lines remain archived but are not fitted,
because their push/partial-win settlement needs different mathematics. There is
no silent conversion of a 3.5 line to 2.5.

If a paid request times out after dispatch, the charge is treated as ambiguous:
there is no immediate retry, and the 12-hour cooldown still applies. A known
HTTP 400/401/403/404/422 rejection is logged separately and allows a corrected
manual restart, with a fresh quota check before spending. The tool does
not follow HTTP redirects with the API key.

## Connection status of this setup

The terminal in this Codex session cannot resolve the provider's DNS address.
Running outside it successfully passed the provider account check, confirming
the key works. The first odds request was rejected due to timestamp precision;
that request-format bug is now fixed and has a regression test. A successful
post-fix odds snapshot still needs verification. Run the launcher in a normal Windows terminal
and look for `"status": "saved"`. A network failure does not prove the key is wrong.
After collection starts, `status` reports the real archive counts and quota.

## Testing whether odds help

See [ODDS_EXPERIMENT_PLAN.md](ODDS_EXPERIMENT_PLAN.md). The software can now archive
odds and market-only predictions. It does not yet produce a live paired comparison
with a refreshed results-only model, collect final scores, or measure a gain.
Our current historical results cache ends in May 2026, so refreshing that feed is
necessary before a fair prospective reference comparison. Current free odds
cannot retroactively add pre-match prices to the already examined past seasons.

Official documentation checked 27 October 2026:
- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/ (free account currently 500 credits/month)
- https://the-odds-api.com/historical-odds-data/ (paid archive; not used)
