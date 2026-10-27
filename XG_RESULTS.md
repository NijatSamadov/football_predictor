# Understat xG: exploratory results

**Decision: keep the existing results-only reference and shadow-test the xG blend.**
The observed xG gain is promising, but too uncertain to claim a reliable improvement.
All training ran on CPU with free data. No paid account or GPU was used.

## Same 760 Premier League games

Points per match, regulation time only. Both seasons contain all 380 fixtures.

| Model | 2024/25 | 2025/26 | Combined |
| --- | ---: | ---: | ---: |
| Matched results-only Poisson, EPL training | 2,694.7 | 2,463.2 | 2,578.9 |
| Selected 50:50 results/xG Poisson blend, EPL training | **2,805.3** | 2,521.1 | **2,663.2** |
| Existing reference Poisson, seven-league training | 2,715.8 | **2,547.4** | 2,631.6 |

The matched control isolates the addition of xG within the EPL study. The existing
reference is shown separately because changing its training population also
changes the model; a gain over the matched control alone would not establish a
gain over the previous system. Its previously saved predictions were matched by
fixture ID, actual scores and cutoff time; no refitting or reselection was used.

| Combined comparison | Points/match difference | Relative gain | Approximate 95% interval |
| --- | ---: | ---: | ---: |
| xG blend minus matched control | +84.2 | +3.3% | -12.8 to +179.5 |
| xG blend minus existing reference | +31.6 | +1.2% | -89.7 to +165.7 |

Intervals use 5,000 paired calendar-week bootstrap samples and include zero.
They are approximate: they do not cover all model-selection or source-data risk.
Against the existing reference, xG earned more points in 2024/25 and fewer in
2025/26. There is no consistent demonstrated improvement across both seasons.

The xG blend earned 2,024,000 total points, with 78 exact scores and 389 correct
outcomes (including exact scores). The existing reference earned 2,000,000,
with 78 exact scores and 383 correct outcomes. The matched control earned
1,960,000, with 74 exact scores and 379 correct outcomes.

Scoring: exact = 10,000 total; otherwise correct winner/draw = 4,000; wrong = 0.
Submission selection maximizes `4000*P(outcome) + 6000*P(exact)`.

## What was trained

Development used 1,140 EPL games from 2021/22 through 2023/24. Five fixed candidates
were compared: results Poisson, results boosting, xG Poisson, xG boosting and the
50:50 results/xG Poisson blend. The xG features summarize past xG for/against for
each side and its opponent, with 45/180-day half lives and five-match shrinkage.
Poisson models use alpha 0.1 and a 365-day training half life. All training is
monthly walk-forward; information at or after the prediction cutoff is excluded.

| Development model | Points per match |
| --- | ---: |
| Results Poisson | 2,766.7 |
| Results boosting | 2,587.7 |
| xG Poisson | 2,766.7 |
| xG boosting | 2,615.8 |
| Selected xG/results Poisson blend | 2,796.5 |

Settings and hashes were frozen before this xG comparison. Nonetheless, these
recent seasons were already examined in our earlier research, so they are **not
a fresh untouched test**. Do not tune again on them and label the result independent.

## Data and quality

- 2,660 joined EPL matches: complete 2018/19 and 2020/21-2025/26 seasons.
- 140 public Understat team-page exports; 30 distinct club identities.
- Exact goals and fixture identities must match OpenFootball; dates may differ
  by at most one day. Both clubs' page exports must agree. No unresolved joins
  were found. Two pages from the same provider are a consistency check, not
  independent verification of its xG model.
- Entire EPL 2019/20 is excluded due to the known results-source calendar error.
- xG values are the displayed two-decimal values. Publication times are
  reconstructed conservatively with a two-day delay, not historically archived.
- Prediction cutoffs use the day before the source-date proxy, not a verified
  24-hour-before-kickoff replay. Later xG revisions cannot be excluded.
- No odds, live team news or starting lineups were used. EPL results do not
  establish performance in other competitions.

Sources: [Understat EPL](https://understat.com/league/EPL/2025),
[OpenFootball](https://github.com/openfootball/football.json). Raw provider exports
and individual historical match predictions remain local; GitHub has aggregate
reports and software. The portable collector's HTTP route still needs a live
network check outside this restricted terminal; the browser collection succeeded.

## Next useful test

Log both models' forecasts before upcoming games, retaining collection and kickoff
timestamps. Add free odds snapshots after account setup and compare them with the
same fixtures and cutoff. Freeze the next evaluation window and decision rule
before results arrive. Spend on data only after a clear incremental benefit appears.
