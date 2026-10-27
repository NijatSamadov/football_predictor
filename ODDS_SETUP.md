# Free odds account setup

1. Open https://the-odds-api.com/ (the hyphens matter).
2. Choose the Starter FREE plan: currently 500 credits per month. Complete the
   account steps yourself and obtain the API key using the site's instructions.
3. In this project folder, copy `.env.example` to a file named `.env`. Put your
   key after `ODDS_API_KEY=`. Keep that file local; it is excluded from Git.
4. Tell me the account is ready. Do not paste the key into chat or GitHub.

The free plan covers current odds, not the paid historical archive. No paid plan
is needed for the next stage of our pilot. We have not connected an odds collector
or used any odds in the xG experiment.

Initial collection scope: Premier League, home/draw/away and goal totals, one
bookmaker region, a small number of snapshots before each match. Returned total
lines must be retained exactly; do not silently treat 3.5-goal odds as 2.5-goal odds.
Store bookmaker/market timestamps and collection times, and exclude in-play prices.

The provider's documented cost is markets times regions. A league request for two
markets in one region costs two credits when both markets are returned, and can
return multiple games. Twice daily for one league is approximately 120 credits in
a 30-day month. We will monitor the remaining quota rather than poll constantly.

Official references, checked 27 October 2026:
- https://the-odds-api.com/
- https://the-odds-api.com/liveapi/guides/v4/
- https://the-odds-api.com/historical-odds-data/
