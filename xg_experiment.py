"""Fixed xG feature ablation. Recent seasons are already seen: exploratory only."""
import argparse
import json
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import predictor as base
import improve_models as common

HALVES=[45,180]
KINDS=['control_poisson','control_boosted','xg_poisson','xg_boosted','xg_blend_poisson']
DEV_START='2021-07-01T00:00:00Z'
DEV_END='2024-07-01T00:00:00Z'
TEST_END='2026-07-01T00:00:00Z'


class Decay(base.Stat):
    def __init__(self,half):super().__init__();self.half=half
    def decay(self,at):
        if self.at is not None:
            factor=2**(-(at-self.at).total_seconds()/86400/self.half)
            self.w*=factor;self.first*=factor;self.second*=factor
        self.at=at


def xg_features(fixtures,history,cutoffs):
    raw=base.features(fixtures,history,cutoffs)
    events=sorted([r for r in history if r.get('home_xg') is not None and r.get('away_xg') is not None],
                  key=lambda r:base.ts(r['xg_available_at_utc']))
    teams={h:defaultdict(lambda h=h:Decay(h)) for h in HALVES}
    leagues={h:Decay(h) for h in HALVES}
    result=[None]*len(fixtures);pointer=0
    for i in sorted(range(len(fixtures)),key=lambda i:cutoffs[i]):
        at=cutoffs[i];r=fixtures[i]
        while pointer<len(events) and base.ts(events[pointer]['xg_available_at_utc'])<at:
            e=events[pointer];when=base.ts(e['xg_available_at_utc']);kick=base.ts(e['kickoff_utc'])
            if base.ts(e['result_available_at_utc'])>when:
                raise ValueError('xG availability precedes supported result availability')
            for half in HALVES:
                h,a=e['home_xg'],e['away_xg']
                teams[half][e['home_team_id']].add(h,a,when,kick)
                teams[half][e['away_team_id']].add(a,h,when,kick)
                leagues[half].add(h,a,when,kick)
            pointer+=1
        if raw[i] is None:continue
        sides=[[],[]]
        for half in HALVES:
            league=leagues[half];league.decay(at)
            prior=(league.first+league.second)/(2*league.w) if league.w else 1.3
            stats=[]
            for key in ['home_team_id','away_team_id']:
                s=teams[half][r[key]];s.decay(at)
                stats.append([(s.first+5*prior)/(s.w+5),(s.second+5*prior)/(s.w+5),np.log1p(s.w)])
            for side in [0,1]:
                sides[side].extend([*stats[side][:2],*stats[1-side][:2],stats[side][2],stats[1-side][2]])
        result[i]=np.concatenate([raw[i],np.array(sides)],axis=1)
    return raw,result


def matrices(rows):
    if any(r['competition_id']!='openfootball:en.1' or r['segment']!='men_senior_club' for r in rows):
        raise ValueError('This first xG ablation supports EPL senior men only')
    for r in rows:
        if any(type(r.get(k)) not in [int,float] or not np.isfinite(r[k]) or not 0<=r[k]<=20 for k in ['home_xg','away_xg']):
            raise ValueError('Complete finite match xG required; missing is not zero')
    cuts=[base.ts(r['kickoff_utc'])-timedelta(days=1) for r in rows]
    plain,extended=xg_features(rows,rows,cuts)
    return plain,extended,cuts


def fit_cached(rows,plain,extended,asof,kind):
    ix=[i for i,r in enumerate(rows) if base.ts(r['result_available_at_utc'])<asof and plain[i] is not None]
    if len(ix)<100:raise ValueError('Insufficient comparable training matches')
    xs=extended if kind.startswith('xg_') else plain
    x=np.concatenate([xs[i] for i in ix])
    y=np.array([rows[i][key] for i in ix for key in ['home_goals_90','away_goals_90']])
    weights=np.array([2**(-(asof-base.ts(rows[i]['kickoff_utc'])).total_seconds()/86400/365) for i in ix for _ in [0,1]])
    if kind.endswith('poisson'):
        model=make_pipeline(StandardScaler(),PoissonRegressor(alpha=.1,max_iter=500))
        model.fit(x,y,poissonregressor__sample_weight=weights)
    else:
        model=HistGradientBoostingRegressor(loss='poisson',max_iter=100,max_leaf_nodes=15,
            min_samples_leaf=30,l2_regularization=5,early_stopping=False,random_state=17)
        model.fit(x,y,sample_weight=weights)
    return model


def evaluate(rows,start,end,names):
    plain,extended,cuts=matrices(rows)
    fold,end=base.ts(start),base.ts(end)
    results=[]
    while fold<end:
        stop=min((fold.replace(day=1)+timedelta(days=32)).replace(day=1),end)
        ix=[i for i,t in enumerate(cuts) if fold<=t<stop]
        if not ix:fold=stop;continue
        required=set(n for n in names if n!='xg_blend_poisson')
        if 'xg_blend_poisson' in names:required.update(['control_poisson','xg_poisson'])
        grids={}
        for name in sorted(required):
            fitted=fit_cached(rows,plain,extended,fold,name)
            xs=extended if name.startswith('xg_') else plain
            rates=fitted.predict(np.concatenate([xs[i] for i in ix])).reshape(-1,2)
            grids[name]=[common.distribution(*pair)[0] for pair in rates]
        if 'xg_blend_poisson' in names:
            grids['xg_blend_poisson']=[common.mixture(a,b) for a,b in zip(grids['control_poisson'],grids['xg_poisson'])]
        for name in names:
            for i,g in zip(ix,grids[name]):results.append(common.score_prediction(rows[i],g,name,cuts[i]))
        print(f'{fold.date()}: {len(ix)} matches',flush=True);fold=stop
    return results


def hashes():
    root=Path(__file__).parent
    return {n:common.digest(root/n) for n in ['xg_experiment.py','understat_import.py','predictor.py','improve_models.py','import_free_data.py']}


def develop(data,folder):
    rows=[r for r in base.load(data) if base.ts(r['kickoff_utc'])<base.ts(DEV_END)]
    start=time.perf_counter();pred=evaluate(rows,DEV_START,DEV_END,KINDS)
    summary=common.summarize(pred)
    eligible=[r for r in summary if r['group']=='ALL' and r['model'].startswith('xg_')]
    selected=sorted(eligible,key=lambda r:(-r['mean_points'],r['exact_log_loss'],r['model']))[0]['model']
    lock=folder/'xg-lock.json'
    if lock.exists():raise FileExistsError('xG experiment already locked')
    common.write_json(folder/'development.json',dict(stage='xg_development',summary=summary,predictions=pred,
        selected=selected,elapsed_seconds=time.perf_counter()-start,sklearn_version=sklearn.__version__))
    common.write_json(lock,dict(selected=selected,code_sha256=hashes(),development_rows_sha256=common.rows_hash(rows),
        settings=dict(xg_halves_days=HALVES,shrinkage=5,poisson_alpha=.1,training_half_life_days=365,
                      boosting='same fixed settings as control',blend_weight=.5),
        development=[DEV_START,DEV_END],exploratory_recent=[DEV_END,TEST_END],
        qualification='2024/25-2025/26 already examined in earlier experiments; not a fresh independent final test'))
    print('Locked xG challenger:',selected)
    for r in summary:
        if r['group']=='ALL':print(r['model'],r['matches'],round(r['mean_points'],2))


def compare(data,folder):
    lock=json.loads((folder/'xg-lock.json').read_text(encoding='utf8'))
    if lock['code_sha256']!=hashes():raise ValueError('Code changed after xG selection')
    target=folder/'recent-comparison.json'
    if target.exists():raise FileExistsError('Exploratory comparison already saved')
    rows=base.load(data)
    history=[r for r in rows if base.ts(r['kickoff_utc'])<base.ts(DEV_END)]
    if lock['development_rows_sha256']!=common.rows_hash(history):raise ValueError('Development history changed')
    start=time.perf_counter();selected=lock['selected']
    # Both matched controls stay visible, so the contribution of xG is not confused
    # with changing the learning algorithm or selecting a different match cohort.
    names=list(dict.fromkeys(['control_poisson','control_boosted',selected]))
    pred=evaluate(rows,DEV_END,TEST_END,names)
    comparator='control_boosted' if selected=='xg_boosted' else 'control_poisson'
    differences=[]
    for season in ['2024-25','2025-26','ALL']:
        subset=pred if season=='ALL' else [r for r in pred if r['season']==season]
        differences.append(dict(season=season,**common.paired_interval(subset,selected,comparator)))
    report=dict(stage='exploratory_xg_comparison',selected=selected,matched_control=comparator,
        lock_sha256=common.digest(folder/'xg-lock.json'),summary=common.summarize(pred),comparisons=differences,
        predictions=pred,elapsed_seconds=time.perf_counter()-start,sklearn_version=sklearn.__version__,
        caveats=['Premier League only; same training/test fixtures for every method',
            'Displayed xG rounded to two decimals and retrospectively reconstructed availability',
            'Recent seasons previously examined; gains require prospective confirmation'])
    common.write_json(target,report)
    for r in report['summary']:
        if r['group'] in ['ALL','2024-25','2025-26']:print(r['model'],r['group'],r['matches'],round(r['mean_points'],2))
    print(json.dumps(differences))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['develop','compare'])
    parser.add_argument('--data',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    if args.mode=='develop':develop(args.data,args.output_dir)
    else:compare(args.data,args.output_dir)


if __name__=='__main__':main()
