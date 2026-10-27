"""Produce the human-readable report from a completed, locked reserved test."""
import json
from pathlib import Path
import improve_models as m

root=Path(__file__).resolve().parent
folder=root/'data'
dev=json.loads((folder/'improved-development-quality.json').read_text(encoding='utf8'))
test=json.loads((folder/'reserved-test-quality.json').read_text(encoding='utf8'))
lock=json.loads((folder/'frozen-experiment-quality.json').read_text(encoding='utf8'))
selected=lock['selected']
lookup={(r['model'],r['group']):r for r in test['summary']}
labels={selected:'Selected challenger','legacy_poisson':'Original Poisson','fixed_1_0':'Always 1-0'}
comparisons=[]
for season in ['2024-25','2025-26','ALL']:
 rs=test['predictions'] if season=='ALL' else [r for r in test['predictions'] if r['season']==season]
 comparisons.append(dict(season=season,**m.paired_interval(rs,selected)))
combined=comparisons[-1]
passes=(combined['approximate_week_bootstrap_95_interval'][0]>0 and all(r['mean_points_difference']>0 for r in comparisons[:2]))
if passes:
 conclusion='The challenger clears the predeclared historical promotion rule. Confirm it in a prospective shadow test before relying on it.'
elif combined['mean_points_difference']>0:
 conclusion='The challenger has a small observed gain, but does not clear the promotion rule. Keep the original Poisson model as the reference; the improvement is unconfirmed.'
else:
 conclusion='The challenger did not improve pooled reserved-test points. Keep the original Poisson model as the reference.'
lines=['# Football model results: free data','',conclusion,'',
 'Models were selected using 2021/22-2023/24 only. The selected pipeline and source code were then frozen before any reserved model scoring. Earlier test results may update later monthly fits after they become available; the target result cannot enter its prediction. No settings were retuned on the reserved seasons.','',
 '## Reserved seasons','',
 '| Season | Method | Matches | Points per match | Exact scores | Correct outcomes |',
 '| --- | --- | ---: | ---: | ---: | ---: |']
for season in ['2024-25','2025-26','ALL']:
 for name in ['legacy_poisson',selected,'fixed_1_0']:
  r=lookup[(name,season)];n=r['matches']
  lines.append(f"| {season} | {labels[name]} | {n:,} | {r['mean_points']:,.1f} | {r['exact_hits']:,} ({100*r['exact_hits']/n:.2f}%) | {r['correct_outcomes']:,} ({100*r['correct_outcomes']/n:.2f}%) |")
lines+=['','Correct outcomes include exact-score hits. Points are 10,000 for an exact score, otherwise 4,000 for the correct winner/draw, otherwise zero.','',
 '## Difference from the original model','',
 '| Season | Challenger minus original, points per match | Approximate 95% interval |',
 '| --- | ---: | ---: |']
for r in comparisons:
 lo,hi=r['approximate_week_bootstrap_95_interval']
 lines.append(f"| {r['season']} | {r['mean_points_difference']:+.1f} | {lo:+.1f} to {hi:+.1f} |")
lines+=['','Intervals resample whole calendar weeks (5,000 repetitions). They are approximate and do not remove data-source or model-selection limitations.','',
 '## What changed','',
 f"Selected pipeline: `{selected}`.",
 'The new family learns opponent-adjusted team attack and defence, competition scoring levels and home advantage. Three recency/regularization settings were compared. Each also had an optional fitted Dixon-Coles low-score correction and a fixed 50:50 probability blend with the original Poisson model. The correction is fitted after the Poisson rates, rather than jointly estimating all parameters.',
 '',f"Development used {next(r['matches'] for r in dev['summary'] if r['model']==selected and r['group']=='ALL'):,} matches, searching 11 trained pipelines. Candidate selection maximized game points; development gains are not evidence of future superiority.",
 '', '## Data quality and scope','',
 'Seven senior men\'s leagues: England, Germany, Spain, Italy, France, Netherlands and Portugal. This is not all-competition coverage.',
 '', 'The first source check missed a calendar-year error in the 2019/20 Premier League archive: 66 July 2020 fixtures were dated July 2019. The entire affected league-season (380 fixtures) was excluded. Development selection was repeated, and a replacement lock was written before any reserved model scoring. The initial run and lock remain in the data folder for audit and are marked superseded.',
 '', 'Independent evidence for the date error: [Premier League Bournemouth-Newcastle match summary, 1 July 2020](https://www.premierleague.com/en/news/1697163/match-summary-afc-bournemouth-v-newcastle-united).',
 '', 'The reserved archive contains 4,704 usable games. Twenty results are missing (the final 2024/25 round in Spain and Italy). Four additional matches are excluded as awarded or cancelled. Missing matches are not fabricated or counted as failures. These omissions limit representativeness.',
 '', 'Source dates are day-level proxies with reconstructed two-day result availability. This is not a verified exact-hour replay, a lineup test or a betting-market comparison. The source lacks odds, xG and starting lineups. Club-name mappings and exceptional venues still need broader independent checks.',
 '', 'Two newer Liverpool results were independently spot-checked against official reports. These samples do not validate the entire archive: [2025/26 opener](https://www.liverpoolfc.com/news/chiesa-and-salah-strike-late-earn-liverpool-anfield-victory-over-bournemouth), [2026 Liverpool-Manchester City](https://www.premierleague.com/en/match/2562141/liverpool-vs-manchester-city/info).',
 '', '## Cost, checks and files','',
 'Incremental data cost: $0. GPU rental: $0. All training and evaluation ran locally on CPU with four configured threads. The 25 numerical, provider, scoring, population, future-label and lock checks passed.',
 '',f"Quality-filtered development runtime: {dev['elapsed_seconds']/60:.1f} minutes. Reserved-test runtime: {test['elapsed_seconds']/60:.1f} minutes. These timings describe this run, not a hardware benchmark.",
 '', 'Key files:', '',
 '- `improve_models.py`: training, model selection, freezing and reserved evaluation.',
 '- `quality_filter.py`: explicit source-quality exclusion.',
 '- `data/frozen-experiment-quality.json`: selected settings and code/history hashes.',
 '- `data/reserved-test-quality.json`: saved forecasts, probabilities, results and metrics.',
 '- `data/recent-experiment/coverage-audit.json`: source coverage audit.',
 '- `EXPERIMENT_PLAN.md` and `PROMOTION_POLICY.md`: the declared protocol.',
 '', 'The reserved seasons are now consumed as tests. Future tuning must not treat another pass over them as a new independent test. Use a prospective prediction log or genuinely later data for the next validation.',
 '', 'This remains a historical research system, not an automated live forecast service.']
(root/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
(folder/'reserved-comparisons.json').write_text(json.dumps(dict(selected=selected,promotion_rule_passed=passes,conclusion=conclusion,comparisons=comparisons),indent=2),encoding='utf8')
print(conclusion)
print(json.dumps(comparisons,indent=2))
