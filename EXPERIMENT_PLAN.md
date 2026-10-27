# Experiment plan: free-data model improvements

Declared before running development selection or collecting reserved-season results.

- Existing data: seven men's senior leagues, 2018/19-2023/24; no new data payments.
- Development scoring: July 2021-June 2024, monthly chronological refits.
- Reference models: existing Poisson regression and existing gradient boosting.
- New family: ridge-shrunk team attack/defence, competition goal level and home
  advantage; maximum four-year training window; exponentially weighted matches.
- Three fixed combinations: (180-day half-life, ridge 5), (365 days, ridge 10),
  (730 days, ridge 20).
- For each combination, compare independent Poisson, a conditional fitted
  Dixon-Coles low-score adjustment, and a 50:50 probability blend of that adjusted
  model with the existing Poisson model. No blend-weight search.
- Select by highest pooled development points. Ties: lower exact-score log loss,
  then model name. The constant 1-0 submission is an ineligible control.
- This searches 11 trained pipelines, so development gains can reflect selection
  noise. Model selection will not be repeated using reserved-season performance.
- Run numerical and leakage safeguards, freeze selected pipeline and source-code
  hashes, then collect 2024/25 and 2025/26 if available from the same source version.
- Reserved evaluation is chronological: each match is predicted before its result
  becomes available; earlier test results can update later monthly parameter fits.
  Hyperparameters, candidate identity and blend weights remain locked.
- Report all available reserved seasons separately and combined, plus exact hits,
  correct outcomes, probability scores, per-league points and approximate weekly
  block-bootstrap intervals against the original Poisson reference.
- Retain the day-level timing limitation and exclusions from the source adapter.
- No odds/xG/lineup claims, GPU rental or new subscriptions.

Data-quality amendment, before any reserved model scoring: exclude the entire
2019/20 Premier League archive because 66 fixtures have a verified wrong year.
Repeat the unchanged candidate comparison on the quality-filtered development
archive and save a new lock. The initial development run/lock remain for audit.
The quality filter is included in the replacement lock source hashes.
