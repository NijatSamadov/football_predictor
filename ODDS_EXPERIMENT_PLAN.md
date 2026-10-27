# Prospective odds experiment: collection stage

Declared before any successful live odds collection in this project. No new
subscription or GPU is used. Scope: Premier League senior men, regulation time.
The existing historical xG experiments remain separate and exploratory.

## Already implemented

Archive current `h2h` and `totals` at most twice daily by default, one region, with
real collection/quote times, actual total lines, safe quota logs and exclusions.
Log a transparent Poisson market benchmark before kickoff, with immutable picks,
probabilities, expected points, bookmaker coverage and source/code hashes.
Inverse decimal odds are normalized within each bookmaker/market to remove the
simple proportional margin. This is an approximation, not a uniquely true
estimate of fair probabilities. Equal bookmaker weighting is fixed in advance.
Only books with complete 1X2 and at least one half-goal total line are fitted.

## Required before the paired scoring stage starts

1. Refresh the free results feed, verify fixture identities/kickoff times and
   preserve observed information-availability timestamps going forward. The
   existing local cache currently stops in May 2026 and is too stale for a live
   reference comparison. Do not confuse that stale baseline with a fair test.
2. Save the frozen reference Poisson prediction at the same actual cutoff as the
   odds model; also save a fixed 50:50 mixture of their joint score distributions.
   Do not tune mixture weights on the future test results. The paired baseline,
   blend logger and result ingestion are not connected by this collection change.
3. Record final regulation scores from a verified source, separately from the
   prediction archive. Do not treat today's prices as historic closing prices.

## Predeclared comparison rule

- Methods: reference Poisson, market-Poisson and fixed 50:50 probability mixture.
- A primary fixture uses the earliest complete saved common-method prediction
  made between 36 and 6 hours before the recorded kickoff, once all three loggers
  and the refreshed reference feed are active. Multiple snapshots are never
  independent matches. Retain missing/unsupported fixtures in coverage counts.
- Freeze primary predictions before the match and never replace a pick after
  seeing its result. Postponed matches with materially changed kickoff times
  require a new eligible pre-match forecast; otherwise mark them unscored.
- Report the first 200 eligible paired matches as one fixed evaluation window,
  with calendar-week paired bootstrap intervals. Earlier partial summaries are
  diagnostic and cannot select settings or establish superiority.
- Score exact = 10,000 total; otherwise winner/draw = 4,000; otherwise zero.
  Select each submitted score by `4000*P(outcome)+6000*P(exact)`.
- Report points/match, total points, exact hits, correct outcomes, probability
  scores and missing-data coverage, on identical fixtures/cutoffs.
- No promotion unless a challenger's combined interval for points improvement
  over the reference is above zero and both chronological 100-match halves
  improve. Otherwise retain the reference and describe the uncertainty.

This is a plan, not a claim that 200 observations will guarantee significance.
No results have been scored for this prospective experiment yet.
