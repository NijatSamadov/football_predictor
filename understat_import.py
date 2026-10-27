"""Join public Understat match-history exports to the existing quality-filtered data."""
import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import predictor as base
from import_free_data import team_id

NAMES = {
 'Arsenal':'Arsenal FC','Aston Villa':'Aston Villa FC','Bournemouth':'AFC Bournemouth',
 'Brentford':'Brentford FC','Brighton':'Brighton & Hove Albion FC','Burnley':'Burnley FC',
 'Cardiff':'Cardiff City','Chelsea':'Chelsea FC','Crystal Palace':'Crystal Palace FC',
 'Everton':'Everton FC','Fulham':'Fulham FC','Huddersfield':'Huddersfield Town',
 'Ipswich':'Ipswich Town FC','Leeds':'Leeds United FC','Leicester':'Leicester City FC',
 'Liverpool':'Liverpool FC','Luton':'Luton Town FC','Manchester City':'Manchester City FC',
 'Manchester United':'Manchester United FC','Newcastle United':'Newcastle United FC',
 'Norwich':'Norwich City FC','Nottingham Forest':'Nottingham Forest FC',
 'Sheffield United':'Sheffield United FC','Southampton':'Southampton FC','Sunderland':'Sunderland AFC',
 'Tottenham':'Tottenham Hotspur FC','Watford':'Watford FC','West Bromwich Albion':'West Bromwich Albion FC',
 'West Ham':'West Ham United FC','Wolverhampton Wanderers':'Wolverhampton Wanderers FC',
}


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(name):
    if name not in NAMES:raise ValueError('Unmapped Understat team: '+str(name))
    return team_id('en',NAMES[name])


def read_exports(folder):
    matches, witnesses, files = {},defaultdict(set),[]
    for path in sorted(Path(folder).glob('20??_*.json')):
        obj=json.loads(path.read_text(encoding='utf8'))
        if not obj.get('source','').startswith('https://understat.com/team/'):
            raise ValueError('Unexpected source page')
        files.append(dict(path=path.name,sha256=digest(path),source=obj['source'],
                          fetched_at_utc=obj['fetched_at_utc']))
        for item in obj['records']:
            r=dict(item)
            if not str(r['id']).isdigit():raise ValueError('Invalid Understat match ID')
            for k in ['home_goals','away_goals']:
                if type(r[k]) is not int or not 0<=r[k]<=30:raise ValueError('Invalid goals')
            for k in ['home_xg','away_xg']:
                if type(r[k]) not in [int,float] or not math.isfinite(r[k]) or not 0<=r[k]<=20:
                    raise ValueError('Invalid xG; missing is not zero')
            day=datetime.strptime(r['match_date'],'%b %d, %Y').date()
            r.update(date=day.isoformat(),home_id=identity(r['home']),away_id=identity(r['away']))
            if r['id'] in matches and matches[r['id']]!=r:
                raise ValueError('Conflicting Understat records for '+r['id'])
            matches[r['id']]=r;witnesses[r['id']].add(obj['source'])
    return matches,witnesses,files


def join(base_rows,understat,witnesses):
    ix={}
    for mid,u in understat.items():
        season=f"{u['season']}-{str(u['season']+1)[-2:]}"
        key=(season,u['home_id'],u['away_id'])
        if key in ix:raise ValueError('Duplicate Understat logical fixture')
        ix[key]=u
    output,issues=[],[]
    for r in base_rows:
        if r['competition_id']!='openfootball:en.1':continue
        u=ix.get((r['season'],r['home_team_id'],r['away_team_id']))
        if u is None:issues.append(dict(match_id=r['match_id'],reason='No Understat match'));continue
        if len(witnesses[u['id']])!=2:
            issues.append(dict(match_id=r['match_id'],reason='Missing independent home/away page cross-check'));continue
        scores=[r['home_goals_90'],r['away_goals_90']]
        if scores!=[u['home_goals'],u['away_goals']]:
            issues.append(dict(match_id=r['match_id'],reason='Sources disagree on score',base=scores,
                               understat=[u['home_goals'],u['away_goals']]));continue
        day=base.ts(r['kickoff_utc']).date()
        if abs((datetime.fromisoformat(u['date']).date()-day).days)>1:
            issues.append(dict(match_id=r['match_id'],reason='Sources disagree on date'));continue
        record=dict(r,home_xg=u['home_xg'],away_xg=u['away_xg'],understat_match_id=u['id'],
            xg_available_at_utc=r['result_available_at_utc'],xg_availability_basis='reconstructed',
            xg_source='https://understat.com/match/'+u['id'],xg_precision='displayed rounded to 2 decimals')
        output.append(record)
    return output,issues


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exports',type=Path,required=True)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();us,witnesses,files=read_exports(args.exports)
    rows,issues=join(base.load(args.base),us,witnesses)
    args.output_dir.mkdir(parents=True,exist_ok=True)
    output=args.output_dir/'matches.jsonl'
    output.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf8')
    manifest=dict(provider='Understat public team-page match histories',cost_usd=0,
        acquisition='Read-only browser DOM of visible match rows; not an official API',
        matches=len(rows),understat_unique_matches=len(us),pages=len(files),
        by_season=dict(Counter(r['season'] for r in rows)),issues=issues,
        exports=files,base_sha256=digest(args.base),normalized_sha256=digest(output),
        limitations=['Premier League pilot only','Displayed xG rounded to two decimals',
            'Historical xG publication time reconstructed as result availability',
            'Revised historical xG may differ from values originally published',
            '2019/20 excluded consistently with existing source-quality policy',
            'Previously examined recent seasons are exploratory, not a new untouched final test'])
    (args.output_dir/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in manifest.items() if k!='exports'},indent=2))


if __name__=='__main__':main()
