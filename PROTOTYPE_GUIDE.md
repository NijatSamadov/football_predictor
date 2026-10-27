# Archived prototype guide

This records the original results-only prototype. For current xG support and results, read README.md and XG_RESULTS.md. Statements below about missing xG apply to the original experiment. Raw data mentioned here remain local and are not included in GitHub.

# Football predictor: free-data starting point

> Latest results: see [RESULTS.md](RESULTS.md) and [START_HERE.md](START_HERE.md).
>
> Update: a verified calendar-year error was found in the 2019/20 Premier League
> source. The original development results below are superseded. The current
> experiment excludes that league-season, repeats development selection, and uses
> a replacement frozen lock before any reserved-season model scoring. See
> `EXPERIMENT_PLAN.md`, `quality_filter.py`, and the final `RESULTS.md` report.

The project now has a working OpenFootball adapter and a first real-data development
backtest. The source data, normalized records and audit reports are included locally.
No subscription, provider account, API key, GPU or GPU rental was used.

This is a research prototype. Its historical test does not yet establish an advantage
in live forecasting or over bookmaker odds.

## What is connected

[OpenFootball public JSON API](https://github.com/openfootball/football.json) serves
historical fixtures/results as JSON files over HTTPS, without authentication.
The repository dedicates the data to the public domain under CC0.
It is a collection of downloadable JSON datasets, not a full live sports-data feed.
Its README explains that upstream updates are not guaranteed to happen daily.

The included snapshot is pinned to repository commit
`e6744429ee395bc86f247348c6184bb08d4eb361` for reproducibility.
The collector retains the source URL and hashes the cached and normalized files.
Cached JSON is reserialized; its hash is a local content-integrity check, not the
upstream Git blob hash. This session acquired it through the connected GitHub tool
because shell networking was unavailable. The standalone collector uses HTTPS.

Initial coverage: Premier League, Bundesliga, La Liga, Serie A, Ligue 1,
Eredivisie and Primeira Liga, for 2018/19 through 2023/24.
42 league-season files contained 14,554 records. After excluding 175 cancelled games
and one administrative award, 14,378 completed regulation-time results remain.

This source does not cover every competition. The adapter currently configures these
seven senior men's leagues only. Cups, women's/youth football and national teams
need their own verified feeds and population segments. No data are invented for
unsupported competitions.

There are no bookmaker odds, xG, player-availability records or confirmed lineups
in this dataset. Those features are absent from this first model comparison.

## How the API fits into the model

1. `import_free_data.py` downloads one JSON file per league and season, or reads
   the included versioned cache with `--cache-only`.
2. It reads full-time scores, excludes unsuitable statuses/rounds, and maps known
   club-name variations to stable country-namespaced team IDs. It does not use fuzzy
   matching. It rejects duplicate logical fixtures rather than counting them twice.
3. It writes normalized internal JSONL records and a manifest listing exclusions,
   source URLs, source version and local file hashes.
4. `predictor.py` builds features from earlier available results, fits models and
   evaluates later matches. Data collection and model fitting are separate steps.
5. `analyze_development.py` compares the models on the same matches, including a
   constant 1-0 submission as a basic control. User-facing picks can remain text.

## Timing limitations of this free archive

Dates and local-time strings do not provide explicit historical UTC offsets or
publication times. The adapter therefore does NOT pretend to know exact kickoff
or information-availability timestamps.

`kickoff_utc` is explicitly marked `kickoff_basis=date_proxy_utc_midnight` for
chronological ordering. Source dates/local-time strings are retained separately.
Results become usable at midnight UTC two calendar days after the listed date,
with `availability_basis=reconstructed`. A three-day delay is also evaluated as
a sensitivity check. Missing result-publication timestamps are never replaced by
today's download time.

For these records, `--hours-before 24` means one day before the midnight date proxy,
not a verified 24-hour pre-kickoff replay. This deliberately conservative convention
can exclude useful recent results. Do not use this archive to claim one-hour lineup
validation. Later corrections, rescheduling knowledge and exceptional neutral venues
remain possible sources of error; the source is not independently verified per match.

## Implemented models and scoring

- Regularized Poisson regression: standardized historical features predict goals.
- Histogram gradient boosting with Poisson loss: the same features predict goals.
- Both convert home/away goal rates to an independent Poisson score distribution.
  The grid accounts for omitted high-score probability and derives coherent 1X2
  probabilities from that same distribution.
- A market-based Poisson benchmark exists, but is unavailable for this dataset.
- Dixon-Coles, bivariate Poisson, Bayesian models, CatBoost, deep learning, xG/player
  features and model blending are not implemented in this version.

Features include decayed scoring/conceding rates for both teams, home advantage,
league scoring levels, amount of available history and elapsed days since prior games.
League/team estimates are shrunk toward pooled priors. Population segments train
separately; competitions within a segment share the learned model.

Only the regulation-time score, including stoppage time, counts:
exact score = 10,000 points total; otherwise correct winner/draw = 4,000; wrong = 0.
The submitted score maximizes expected points over the entire score grid:
`4000 * P(correct outcome) + 6000 * P(exact score)`.

## First development test

The initial run predicts 2,364 matches in the 2023/24 season across all seven leagues.
Parameters refit monthly, using only labels available before each refit. Earlier
results may update later features after the reconstructed availability time.
Training examples also receive features based only on their earlier history.

Fixed engineering defaults, not tuned: 180-day feature half-life, 365-day training
weight half-life, league/team shrinkage weights 10/5, Poisson regularization 0.1;
boosting 100 iterations, 15 leaves, minimum leaf size 30, L2 regularization 5.
All models ran locally on CPU. No hardware purchase or rental was needed.

With the two-day reconstructed result delay:

| Method | Points per match | Exact scores | Correct outcomes, including exact |
| --- | ---: | ---: | ---: |
| Poisson regression | 2,840.9 | 270 / 2,364 (11.42%) | 1,274 / 2,364 (53.89%) |
| Gradient boosting | 2,813.0 | 255 / 2,364 (10.79%) | 1,280 / 2,364 (54.15%) |
| Always submit 1-0 | 2,246.2 | 205 / 2,364 (8.67%) | 1,020 / 2,364 (43.15%) |

Boosting minus Poisson = -27.9 points per match. An approximate calendar-week block
bootstrap gives a 95% interval of -102.5 to +41.7 (40 week blocks, 5,000 resamples).
This does not establish a difference between the learned models. In particular,
there is no demonstrated benefit from the more complex model in this test.
With a three-day result delay, the averages are 2,834.2 for Poisson and 2,792.7
for boosting; the model ranking is unchanged. This is a timing sensitivity check,
not proof that either model will outperform in future matches.
No bookmaker comparison or comparison to the user's selections has been performed.

`data/development-summary.json` contains the summary and caveats;
`data/development-2023-24.json` contains probabilities and predictions for auditing.
These are development results, not a final untouched test. 2024/25 and later seasons
were not collected/evaluated here and remain candidates for later held-out testing.

## Run locally

Python 3.11+ with `requirements.txt` installed. From this project directory:

```powershell
# Rebuild the dataset without an account or internet access; cache is included.
python import_free_data.py --cache-only

# Download missing files over HTTPS instead, where shell networking is available.
python import_free_data.py

# Keep CPU thread use modest on a laptop.
$env:OMP_NUM_THREADS='4'
$env:OPENBLAS_NUM_THREADS='4'

# Repeat the development backtest, with the timing convention described above.
python predictor.py data/matches-delay2d.jsonl --start 2023-07-01T00:00:00Z --end 2024-07-01T00:00:00Z --hours-before 24 --output data/development-2023-24.json
python analyze_development.py data/matches-delay2d.jsonl data/development-2023-24.json --output data/development-summary.json

# Sensitivity to reconstructed result availability.
python import_free_data.py --cache-only --result-delay-days 3
python predictor.py data/matches-delay3d.jsonl --start 2023-07-01T00:00:00Z --end 2024-07-01T00:00:00Z --hours-before 24 --output data/development-2023-24-delay3d.json

# Provider semantics, points, distributions, training and leakage checks.
python -m unittest discover -s . -p 'test_*.py' -v
```

The collector supports `--leagues`, `--seasons`, a pinned `--ref`, and a data directory.
A league-season file must actually exist upstream; missing files fail explicitly.
An existing cache is always namespaced by commit; different source versions are not
silently mixed. Do not change the source version during an experiment.

## Next development steps

1. Independently check samples of results/identities and improve data coverage.
2. Tune candidates only on chronological development windows; compare data additions
   on identical match sets. Exact score accuracy alone is not the game's objective.
3. Obtain free, suitably timestamped odds where feasible; benchmark before buying
   richer data. Keep incremental spending at zero for now (see `BUDGET.md`).
4. Freeze the chosen settings, then evaluate untouched recent seasons once. Report
   game points, calibration/probability scores, coverage, per-league results and
   uncertainty. Do not select a winner from this development season alone.
5. Start a prospective shadow log before relying on the model: store predictions
   before games, then compare realized points with simple/market/human controls.
6. Add verified upcoming fixtures, saved trained models and a text prediction command.
   This prototype currently provides historical evaluation, not a live forecast
   service. Starting-XI screenshots have no fitted player effect yet.
