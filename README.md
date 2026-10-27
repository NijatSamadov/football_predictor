# Football predictor

CPU-only research for a football score prediction game. Free results and match xG;
no GPU, paid feed or subscription used in the experiments.

**Current finding:** Understat xG is promising, but the observed gain over the
existing reference is small and uncertain. Read [XG_RESULTS.md](XG_RESULTS.md).
This is a historical research pipeline, not an automated live prediction service.

## Scoring and score selection

Only regulation time plus stoppage time counts. An exact score earns **10,000**
points total; otherwise the correct winner/draw earns **4,000**; otherwise **0**.
For each plausible score, maximize `4000 * P(outcome) + 6000 * P(exact score)`.
The most likely exact score does not always maximize these points.

## Models

- Results-only regularized Poisson and gradient boosting with Poisson loss.
- Opponent-adjusted attack/defence models, fitted low-score Dixon-Coles corrections
  and fixed probability blends, compared in the earlier seven-league experiment.
- New EPL xG features: past xG for/against, decayed over 45 and 180 days and shrunk
  toward league averages. The selected challenger blends results-only and xG
  Poisson score probabilities equally. Boosting was tested too.

Training and evaluation run on CPU. Models generate coherent joint score grids;
win/draw/loss probabilities and the points-maximizing pick use the same grid.
Monthly walk-forward fitting uses only labels available before each fold. xG
features use only earlier information available before each prediction cutoff.

## Results and limitations

[Earlier results](RESULTS.md): seven European leagues, 4,704 recent games.
[New xG comparison](XG_RESULTS.md): the same 760 EPL games for all compared models,
2024/25 and 2025/26. xG increased observed points by 3.3% versus its matched EPL
control and 1.2% versus the existing seven-league-trained reference. Both
uncertainty intervals include zero. Keep the reference model; shadow-test xG.

Recent seasons had already been examined before the xG study, so this is an
**exploratory comparison**, not a new independent final test. Historical timestamps
are reconstructed day-level proxies. Understat values were read from public team
pages and rounded to two decimals; historical revisions/publication times cannot
be ruled out. No bookmaker odds or lineup features were used. The xG pilot covers
EPL senior men only; it does not support all competitions.

## Install and check

Python 3.12 or 3.13 is recommended. In the project folder:

```powershell
python -m venv .venv
.venv/Scripts/Activate.ps1
python -m pip install -r requirements.txt
$env:OMP_NUM_THREADS='4'
$env:OPENBLAS_NUM_THREADS='4'
python -m unittest discover -s . -p 'test_*.py' -v
```

GitHub contains source, synthetic test fixtures, settings hashes and aggregate
reports. Provider data, cached exports, individual historical predictions, API
keys and fitted model files stay out of Git. The original working folder has the
experiment data; cloning this repository alone does not download those data.

## Reproduce the xG workflow

The results adapter reads [OpenFootball](https://github.com/openfootball/football.json)
at a pinned commit. Understat's public site supplies xG. The standalone xG
collector uses unofficial JSON endpoints and requires ordinary outbound HTTPS.
Its parsing is unit-tested, but that HTTP collection route could not be exercised
in the restricted terminal used for this pilot. The actual pilot successfully
collected 140 public team pages in a browser. Endpoints can change; inspect the
manifest and fail on missing or mismatched matches.

```powershell
python import_free_data.py --leagues en.1 --seasons 2018-19 2019-20 2020-21 2021-22 2022-23 2023-24 2024-25 2025-26 --data-dir data/results
python quality_filter.py data/results/matches-delay2d.jsonl data/results/matches-quality.jsonl
python collect_understat.py --output-dir data/understat
python understat_import.py --exports data/understat --base data/results/matches-quality.jsonl --output-dir data/xg-experiment
python xg_experiment.py develop --data data/xg-experiment/matches.jsonl --output-dir data/xg-experiment
python xg_experiment.py compare --data data/xg-experiment/matches.jsonl --output-dir data/xg-experiment
```

The entire EPL 2019/20 season is excluded because the results source dates 66 July
2020 games as July 2019. Development uses 2021/22-2023/24, then freezes settings,
code and development history hashes. Existing locks/comparisons are protected
against overwrite. Use a separate output directory for a separately labelled
experiment; rerunning examined seasons does not make them unseen data.

## Free odds next

Follow [ODDS_SETUP.md](ODDS_SETUP.md). The Odds API currently offers 500 monthly
credits on its free plan, with current odds and no free historical archive.
Create the account yourself and keep its key in local `.env`. An odds collector
is not connected yet; the next step is to log real pre-match prices and evaluate
prospectively before deciding whether they help. No paid account is needed.

## Files

- `predictor.py`: validation, result features, Poisson/boosting and score selection.
- `improve_models.py`: strength models, distributions, walk-forward comparisons.
- `understat_import.py`: checked joins, identity mapping and xG provenance.
- `xg_experiment.py`: matched xG study and development lock.
- `collect_understat.py`, `import_free_data.py`: free source adapters.
- `reports/`: aggregate xG results and the original experiment settings hash record.
- `PROTOTYPE_GUIDE.md`: archived schema and original adapter details.
- `test_*.py`: chronology, scoring, probability and data-quality checks.

The free feeds used here do not supply all the data needed for an all-competition
production system. Better live accuracy remains a question for future testing.
