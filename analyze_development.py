"""Describe a development run, including a fixed-score control and weekly uncertainty."""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import predictor as p


def analyze(data_path, audit_path):
    fixtures = {r['match_id']: r for r in p.load(data_path)}
    audit = json.loads(Path(audit_path).read_text(encoding='utf8'))
    indexed = {
        name: {r['match_id']: r for r in audit['predictions'] if r['model'] == name and 'points' in r}
        for name in ['poisson', 'boosted']}
    common = sorted(set(indexed['poisson']) & set(indexed['boosted']))
    totals = []
    for name in ['poisson', 'boosted', 'fixed_1_0']:
        scores, exact, correct = [], 0, 0
        for mid in common:
            actual = [fixtures[mid]['home_goals_90'], fixtures[mid]['away_goals_90']]
            submitted = [1, 0] if name == 'fixed_1_0' else indexed[name][mid]['score']
            value = p.points(submitted, actual)
            scores.append(value); exact += value == 10000; correct += value > 0
        totals.append(dict(model=name, matches=len(scores), points=sum(scores),
            mean_points=float(np.mean(scores)), exact_hits=int(exact),
            exact_rate=exact/len(scores), correct_outcomes=int(correct), outcome_accuracy=correct/len(scores)))
    weeks = defaultdict(lambda: [0, 0])
    for mid in common:
        week = tuple(p.ts(fixtures[mid]['kickoff_utc']).isocalendar()[:2])
        weeks[week][0] += indexed['boosted'][mid]['points'] - indexed['poisson'][mid]['points']
        weeks[week][1] += 1
    # Resample whole calendar weeks so games from the same week stay together.
    # This is an approximate uncertainty diagnostic, not a superiority test.
    blocks = np.array(list(weeks.values()), dtype=float)
    rng = np.random.default_rng(20261027)
    indices = rng.integers(0, len(blocks), size=(5000, len(blocks)))
    sampled = blocks[indices].sum(axis=1)
    differences = sampled[:, 0] / sampled[:, 1]
    return dict(stage='development_only', window=audit['settings'], common_matches=len(common),
        models=totals, boosted_minus_poisson=dict(
            observed_mean_points=float(blocks[:, 0].sum()/blocks[:, 1].sum()),
            weekly_bootstrap_95_percent_interval=np.quantile(differences, [.025, .975]).tolist(),
            blocks=len(blocks), replications=5000),
        caveats=['Day-level reconstructed timing, not an archived exact-hour replay',
            'No odds benchmark is possible with these data',
            'Source is not independently verified match by match',
            'No model selection, calibration or deep-learning superiority is demonstrated',
            '2024/25 and later seasons were not collected or evaluated in this run'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('audit', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = analyze(args.data, args.audit)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
