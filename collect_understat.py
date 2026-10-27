"""Free Understat collector using the site's public, unofficial JSON endpoints.
Use where ordinary outbound HTTPS is available. No account/key required.
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT='https://understat.com'
MONTHS=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']


def request(path):
    time.sleep(1.1)
    req=urllib.request.Request(ROOT+'/'+path,headers={
        'User-Agent':'football-predictor-research/0.3',
        'X-Requested-With':'XMLHttpRequest','Referer':ROOT+'/'})
    with urllib.request.urlopen(req,timeout=30) as response:
        body=response.read(5_000_001)
    if len(body)>5_000_000:raise ValueError('Unexpectedly large response')
    return json.loads(body)


def export_match(item,season):
    if not item.get('isResult'):return None
    day=datetime.strptime(item['datetime'][:10],'%Y-%m-%d').date()
    return dict(id=str(item['id']),season=season,
        match_date=f'{MONTHS[day.month-1]} {day.day:02d}, {day.year}',
        home=item['h']['title'],away=item['a']['title'],
        home_goals=int(item['goals']['h']),away_goals=int(item['goals']['a']),
        home_xg=round(float(item['xG']['h']),2),away_xg=round(float(item['xG']['a']),2))


def collect(seasons,output):
    output.mkdir(parents=True,exist_ok=True)
    for season in seasons:
        league=request(f'getLeagueData/EPL/{season}')
        teams=league.get('teams')
        if not isinstance(teams,dict) or len(teams)!=20:
            raise ValueError('Unexpected EPL team listing; endpoint may have changed')
        for team in teams.values():
            title=team['title']
            data=request(f'getTeamData/{urllib.parse.quote(title,safe="")}/{season}')
            if not isinstance(data.get('dates'),list):raise ValueError('Missing match array')
            rows=[export_match(m,season) for m in data['dates']]
            rows=[r for r in rows if r is not None]
            slug=title.replace(' ','_')
            obj=dict(source=f'{ROOT}/team/{urllib.parse.quote(slug,safe="_")}/{season}',
                fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                precision='rounded to 2 decimal places for the fixed pilot',
                acquisition='unofficial public Understat JSON endpoint',records=rows)
            # Compatible with browser-export import. Never overwrite a cached export.
            target=output/f'{season}_{urllib.parse.quote(title,safe="")}.json'
            if target.exists():
                print('Existing export retained:',target.name,flush=True)
                continue
            target.write_text(json.dumps(obj,ensure_ascii=False)+'\n',encoding='utf8')
            print(season,title,len(rows),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seasons',nargs='+',type=int,default=[2018,2020,2021,2022,2023,2024,2025])
    parser.add_argument('--output-dir',type=Path,default=Path(__file__).parent/'data'/'understat')
    args=parser.parse_args();collect(args.seasons,args.output_dir)
