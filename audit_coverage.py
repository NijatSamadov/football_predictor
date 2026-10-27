"""Summarize completeness, identities and source statuses without fitting any models."""
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import predictor as p


def audit(path):
    rows=p.load(path)
    groups=defaultdict(list)
    for r in rows:groups[(r['season'],r['competition_id'])].append(r)
    result=[]
    for (season,league),items in sorted(groups.items()):
        teams={r[k] for r in items for k in ['home_team_id','away_team_id']}
        expected=len(teams)*(len(teams)-1)
        appearances=Counter(t for r in items for t in [r['home_team_id'],r['away_team_id']])
        result.append(dict(season=season,competition=league,matches=len(items),teams=len(teams),
            expected_double_round_robin_matches=expected,
            completeness_ratio=len(items)/expected if expected else None,
            minimum_games_per_team=min(appearances.values()),maximum_games_per_team=max(appearances.values()),
            first_date=min(r['source_match_date'] for r in items),last_date=max(r['source_match_date'] for r in items)))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=audit(args.data)
    if args.output:args.output.write_text(json.dumps(report,indent=2),encoding='utf8')
    for r in report:print(json.dumps(r))
