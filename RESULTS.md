# Football model results: free data

The challenger has a small observed gain, but does not clear the promotion rule. Keep the original Poisson model as the reference; the improvement is unconfirmed.

Models were selected using 2021/22-2023/24 only. The selected pipeline and source code were then frozen before any reserved model scoring. Earlier test results may update later monthly fits after they become available; the target result cannot enter its prediction. No settings were retuned on the reserved seasons.

## Reserved seasons

| Season | Method | Matches | Points per match | Exact scores | Correct outcomes |
| --- | --- | ---: | ---: | ---: | ---: |
| 2024-25 | Original Poisson | 2,342 | 2,844.6 | 283 (12.08%) | 1,241 (52.99%) |
| 2024-25 | Selected challenger | 2,342 | 2,842.0 | 284 (12.13%) | 1,238 (52.86%) |
| 2024-25 | Always 1-0 | 2,342 | 2,309.1 | 234 (9.99%) | 1,001 (42.74%) |
| 2025-26 | Original Poisson | 2,362 | 2,779.8 | 265 (11.22%) | 1,244 (52.67%) |
| 2025-26 | Selected challenger | 2,362 | 2,804.4 | 274 (11.60%) | 1,245 (52.71%) |
| 2025-26 | Always 1-0 | 2,362 | 2,285.4 | 211 (8.93%) | 1,033 (43.73%) |
| ALL | Original Poisson | 4,704 | 2,812.1 | 548 (11.65%) | 2,485 (52.83%) |
| ALL | Selected challenger | 4,704 | 2,823.1 | 558 (11.86%) | 2,483 (52.78%) |
| ALL | Always 1-0 | 4,704 | 2,297.2 | 445 (9.46%) | 2,034 (43.24%) |

Correct outcomes include exact-score hits. Points are 10,000 for an exact score, otherwise 4,000 for the correct winner/draw, otherwise zero.

## Difference from the original model

| Season | Challenger minus original, points per match | Approximate 95% interval |
| --- | ---: | ---: |
| 2024-25 | -2.6 | -53.3 to +49.3 |
| 2025-26 | +24.6 | -22.8 to +69.4 |
| ALL | +11.1 | -23.9 to +45.7 |

Intervals resample whole calendar weeks (5,000 repetitions). They are approximate and do not remove data-source or model-selection limitations.

## What changed

Selected pipeline: `strength_365_10_dc_blend50`.
The new family learns opponent-adjusted team attack and defence, competition scoring levels and home advantage. Three recency/regularization settings were compared. Each also had an optional fitted Dixon-Coles low-score correction and a fixed 50:50 probability blend with the original Poisson model. The correction is fitted after the Poisson rates, rather than jointly estimating all parameters.

Development used 7,240 matches, searching 11 trained pipelines. Candidate selection maximized game points; development gains are not evidence of future superiority.

## Data quality and scope

Seven senior men's leagues: England, Germany, Spain, Italy, France, Netherlands and Portugal. This is not all-competition coverage.

The first source check missed a calendar-year error in the 2019/20 Premier League archive: 66 July 2020 fixtures were dated July 2019. The entire affected league-season (380 fixtures) was excluded. Development selection was repeated, and a replacement lock was written before any reserved model scoring. The initial run and lock remain in the data folder for audit and are marked superseded.

Independent evidence for the date error: [Premier League Bournemouth-Newcastle match summary, 1 July 2020](https://www.premierleague.com/en/news/1697163/match-summary-afc-bournemouth-v-newcastle-united).

The reserved archive contains 4,704 usable games. Twenty results are missing (the final 2024/25 round in Spain and Italy). Four additional matches are excluded as awarded or cancelled. Missing matches are not fabricated or counted as failures. These omissions limit representativeness.

Source dates are day-level proxies with reconstructed two-day result availability. This is not a verified exact-hour replay, a lineup test or a betting-market comparison. The source lacks odds, xG and starting lineups. Club-name mappings and exceptional venues still need broader independent checks.

Two newer Liverpool results were independently spot-checked against official reports. These samples do not validate the entire archive: [2025/26 opener](https://www.liverpoolfc.com/news/chiesa-and-salah-strike-late-earn-liverpool-anfield-victory-over-bournemouth), [2026 Liverpool-Manchester City](https://www.premierleague.com/en/match/2562141/liverpool-vs-manchester-city/info).

## Cost, checks and files

Incremental data cost: $0. GPU rental: $0. All training and evaluation ran locally on CPU with four configured threads. The 25 numerical, provider, scoring, population, future-label and lock checks passed.

Quality-filtered development runtime: 7.4 minutes. Reserved-test runtime: 1.3 minutes. These timings describe this run, not a hardware benchmark.

Key files:

- `improve_models.py`: training, model selection, freezing and reserved evaluation.
- `quality_filter.py`: explicit source-quality exclusion.
- `data/frozen-experiment-quality.json`: selected settings and code/history hashes.
- `data/reserved-test-quality.json`: saved forecasts, probabilities, results and metrics.
- `data/recent-experiment/coverage-audit.json`: source coverage audit.
- `EXPERIMENT_PLAN.md` and `PROMOTION_POLICY.md`: the declared protocol.

The reserved seasons are now consumed as tests. Future tuning must not treat another pass over them as a new independent test. Use a prospective prediction log or genuinely later data for the next validation.

This remains a historical research system, not an automated live forecast service.
