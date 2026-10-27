# xG experiment plan

Fixed before scoring the newly joined xG dataset.

- Public Understat team pages, Premier League, seasons 2018/19 and 2020/21-2025/26.
- Match-level xG, rounded to two decimals as displayed. Cross-check both club pages,
  scores, fixture identity and dates. Exclude 2019/20 under the existing quality rule.
- Same rows and training samples for results-only and xG variants.
- Add 45-day and 180-day decayed xG for/against for each side and history counts.
- Fixed settings: Poisson alpha .1; boosting identical to existing fixed defaults;
  365-day training half-life; xG shrinkage 5 matches. No hyperparameter sweep.
- Five candidates: results-only Poisson, results-only boosting, xG Poisson,
  xG boosting, and a fixed 50:50 xG/results Poisson probability blend.
- Select one xG challenger using pooled 2021/22-2023/24 points, with exact log loss
  and name as tie-breakers. Freeze code/settings/history hashes before comparison.
- Compare on 2024/25-2025/26 with monthly refits and strictly earlier available
  features/labels. Report both matched controls, exact hits and weekly intervals.
- These recent seasons were examined previously: this is an exploratory feature
  ablation, not a fresh independent final test. Require prospective confirmation.
- No target-match xG, season totals, final standings, odds or paid data.
