# Start here

Read [XG_RESULTS.md](XG_RESULTS.md) for the latest xG experiment, and
[RESULTS.md](RESULTS.md) for the earlier seven-league comparison.

The xG blend improved observed points on the matched EPL control, but its gain
over the existing reference was only 1.2% and remains uncertain. Keep the existing
reference and collect prospective predictions for both models.

Everything so far used free data and CPU training. No GPU rental or paid feed is
needed. This remains historical research: live fixtures, odds and lineup updates
are not connected. The xG pilot supports Premier League senior men only.

To set up the free odds account, follow [ODDS_SETUP.md](ODDS_SETUP.md). Keep the key
in local `.env` and never send it in chat or commit it.

GitHub contains code and aggregate reports; raw data stay local under `data/`.
The original local working folder also contains:

- `data/xg-experiment/matches.jsonl`: 2,660 joined regulation-time/xG games.
- `data/xg-experiment/development.json`: development results and predictions.
- `data/xg-experiment/xg-lock.json`: selected model/settings/code hashes.
- `data/xg-experiment/recent-comparison.json`: 760-game exploratory comparison.
- `data/xg-experiment/original-reference.json`: existing reference on those games.
- `data/understat/`: 140 cached public team-page exports.

For installation, commands and model details, see [README.md](README.md).
