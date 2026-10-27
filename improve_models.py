"""Chronological development, locked model selection and untouched-season evaluation.
CPU-only. Day-level archive convention inherited from import_free_data.py.
"""
import argparse
import hashlib
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.sparse import coo_matrix
from scipy.stats import poisson

import predictor as base

VERSION = '0.2.0-strength-dc'
DEVELOP_START = '2021-07-01T00:00:00Z'
DEVELOP_END = '2024-07-01T00:00:00Z'
SETTINGS = [
    {'name': 'strength_180_5', 'half_life': 180, 'ridge': 5.},
    {'name': 'strength_365_10', 'half_life': 365, 'ridge': 10.},
    {'name': 'strength_730_20', 'half_life': 730, 'ridge': 20.},
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_hashes():
    root = Path(__file__).parent
    return {name: digest(root/name) for name in ['improve_models.py', 'predictor.py', 'import_free_data.py', 'quality_filter.py']}


def rows_hash(rows):
    data = '\n'.join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in sorted(rows, key=lambda r:r['match_id']))
    return hashlib.sha256(data.encode()).hexdigest()


def tau(h, a, rho):
    return np.array([1-h*a*rho, 1+h*rho, 1+a*rho, 1-rho])


def effective_rho(h, a, rho):
    # Preserve nonnegative mass even for a future high-rate matchup.
    lower = max(-1/h, -1/a) + 1e-10
    upper = min(1/(h*a), 1.) - 1e-10
    return float(np.clip(rho, lower, upper))


def distribution(h, a, rho=0.):
    matrix, _, tail = base.grid(h, a)
    used = effective_rho(h, a, rho)
    factors = tau(h, a, used)
    matrix[0, 0] *= factors[0]; matrix[0, 1] *= factors[1]
    matrix[1, 0] *= factors[2]; matrix[1, 1] *= factors[3]
    matrix /= matrix.sum()
    return matrix, tail, used


def choose(matrix):
    outcome = np.array([np.tril(matrix, -1).sum(), np.trace(matrix), np.triu(matrix, 1).sum()])
    h, a = np.indices(matrix.shape)
    oi = np.where(h>a, 0, np.where(h==a, 1, 2))
    utility = 4000*outcome[oi]+6000*matrix
    score = np.unravel_index(np.argmax(utility), matrix.shape)
    return dict(score=[int(x) for x in score], expected_points=float(utility[score]),
        exact_probability=float(matrix[score]), outcome_probabilities=outcome.tolist())


def mixture(left, right, weight=.5):
    n = max(len(left),len(right))
    result = np.zeros((n,n))
    result[:len(left),:len(left)] += weight*left
    result[:len(right),:len(right)] += (1-weight)*right
    return result/result.sum()


class Strength:
    """Ridge-shrunk attack/defence parameters, competition intercept and home advantage.
    Fit independent Poisson rates, then conditional weighted low-score rho MLE.
    This is a two-stage Dixon-Coles adjustment, not full joint parameter estimation.
    """
    def __init__(self, half_life=365, ridge=10.):
        self.half_life, self.ridge = half_life, ridge

    def design(self, rows):
        ii, jj, vv = [], [], []
        count, teams = len(rows), len(self.teams)
        for i, r in enumerate(rows):
            comp = self.leagues.get(r['competition_id'])
            if comp is None: raise ValueError('Unseen competition: no supported league baseline')
            for side in (0,1):
                ix = 2*i+side
                own = self.teams.get(r['home_team_id'] if side==0 else r['away_team_id'])
                opp = self.teams.get(r['away_team_id'] if side==0 else r['home_team_id'])
                cells = [(2*teams+2*comp,1.)]
                if side==0 and not r['neutral_venue']: cells.append((2*teams+2*comp+1,1.))
                if own is not None: cells.append((own,1.))
                if opp is not None: cells.append((teams+opp,1.))
                for j,v in cells: ii.append(ix); jj.append(j); vv.append(v)
        return coo_matrix((vv,(ii,jj)),shape=(2*count,self.size)).tocsr()

    def fit(self, history, asof):
        train = [r for r in history if r.get('home_goals_90') is not None and
                 base.ts(r['result_available_at_utc']) < asof and
                 base.ts(r['kickoff_utc']) >= asof-timedelta(days=4*365)]
        if len(train)<100: raise ValueError('Insufficient strength-model history')
        segments = {r['segment'] for r in train}
        if len(segments)!=1: raise ValueError('Strength fitting requires exactly one population segment')
        self.segment = next(iter(segments))
        self.teams = {t:i for i,t in enumerate(sorted({r[k] for r in train for k in ['home_team_id','away_team_id']}))}
        self.leagues = {t:i for i,t in enumerate(sorted({r['competition_id'] for r in train}))}
        nt = len(self.teams); self.size = 2*nt+2*len(self.leagues)
        x = self.design(train)
        y = np.array([[r['home_goals_90'],r['away_goals_90']] for r in train],dtype=float).ravel()
        wmatch = np.array([2**(-(asof-base.ts(r['kickoff_utc'])).total_seconds()/86400/self.half_life) for r in train])
        weights = np.repeat(wmatch,2)
        target = np.zeros(self.size)
        penalty = np.full(self.size,self.ridge)
        for comp,j in self.leagues.items():
            subset = [r for r in train if r['competition_id']==comp]
            away = np.mean([r['away_goals_90'] for r in subset])
            home = np.mean([r['home_goals_90'] for r in subset])
            target[2*nt+2*j] = np.log(max(.2,away))
            target[2*nt+2*j+1] = np.log(max(.2,home)/max(.2,away))
            penalty[2*nt+2*j:2*nt+2*j+2] = [2.,10.]
        def objective(beta):
            eta = x @ beta; rate = np.exp(eta)
            delta = beta-target
            loss = np.dot(weights,rate-y*eta)+.5*np.dot(penalty,delta*delta)
            grad = np.asarray(x.T @ (weights*(rate-y))).ravel()+penalty*delta
            return float(loss),grad
        bounds = [(-2.5,2.5)]*(2*nt)+[b for _ in self.leagues for b in [(-2.,2.),(-1.,1.)]]
        fitted = minimize(objective,target,method='L-BFGS-B',jac=True,bounds=bounds,
                          options={'maxiter':500,'ftol':1e-10,'gtol':1e-6})
        if not fitted.success: raise RuntimeError('Strength optimizer failed: '+fitted.message)
        self.beta = fitted.x
        rates = np.exp(x@self.beta).reshape(-1,2)
        h,a = rates.T
        lo = max(-.2,float(np.max(-1/h)),float(np.max(-1/a)))+1e-8
        hi = min(.2,float(np.min(1/(h*a))),1.)-1e-8
        labels = y.reshape(-1,2)
        masks = [(labels[:,0]==0)&(labels[:,1]==0), (labels[:,0]==0)&(labels[:,1]==1),
                 (labels[:,0]==1)&(labels[:,1]==0), (labels[:,0]==1)&(labels[:,1]==1)]
        def rho_loss(rho):
            factors = [1-h*a*rho,1+h*rho,1+a*rho,np.full(len(h),1-rho)]
            return -sum(np.dot(wmatch[m],np.log(f[m])) for m,f in zip(masks,factors))
        estimated = minimize_scalar(rho_loss,bounds=(lo,hi),method='bounded')
        if not estimated.success: raise RuntimeError('Low-score optimization failed')
        self.rho = float(estimated.x)
        self.fit_info = dict(matches=len(train),asof=asof.isoformat(),rho=self.rho,iterations=int(fitted.nit))
        return self

    def rates(self, rows):
        if any(r['segment'] != self.segment for r in rows): raise ValueError('Population mismatch')
        result = np.exp(self.design(rows)@self.beta).reshape(-1,2)
        if not np.all((result>0)&(result<=20)): raise ValueError('Unsupported predicted goal rate')
        return result


def score_prediction(row, matrix, model, at, **extras):
    result = dict(match_id=row['match_id'],competition_id=row['competition_id'],season=row['season'],
                  kickoff_utc=row['kickoff_utc'],asof_utc=at.isoformat(),model=model,**choose(matrix),**extras)
    actual = [row['home_goals_90'],row['away_goals_90']]
    outcome = 0 if actual[0]>actual[1] else 1 if actual[0]==actual[1] else 2
    prob = result['outcome_probabilities']
    # A grid wide enough for these actual labels is required, never assign a fake floor.
    if max(actual)>=len(matrix): raise ValueError('Actual score outside computed grid; enlarge the grid')
    result.update(actual=actual,points=base.points(result['score'],actual),
        outcome_log_loss=float(-np.log(max(1e-15,prob[outcome]))),
        outcome_brier=float(np.sum((np.asarray(prob)-np.eye(3)[outcome])**2)),
        exact_log_loss=float(-np.log(max(1e-300,matrix[tuple(actual)]))))
    return result


def evaluate(rows,start,end,all_candidates=True,selected=None):
    start,end = base.ts(start),base.ts(end)
    if start>=end: raise ValueError('Invalid evaluation window')
    # This experiment deliberately supports only one configured population.
    if {r['segment'] for r in rows}!={'men_senior_club'}: raise ValueError('Unsupported population mix')
    predictions, fitting = [], []
    fold = start
    while fold<end:
        stop = min((fold.replace(day=1)+timedelta(days=32)).replace(day=1),end)
        fixtures = [r for r in rows if r.get('home_goals_90') is not None and
                    fold <= base.ts(r['kickoff_utc'])-timedelta(days=1)<stop]
        if not fixtures: fold=stop;continue
        cuts = [base.ts(r['kickoff_utc'])-timedelta(days=1) for r in fixtures]
        # No target/future labels reach model fitting; feature sweeps enforce availability.
        old = base.fit(rows,fold,24,'poisson')
        legacy = base.predict(fixtures,rows,cuts,old,'poisson')
        legacy_grids = [distribution(*r['rates'])[0] for r in legacy]
        needed = SETTINGS if all_candidates else [s for s in SETTINGS if s['name'] in (selected or '')]
        for i,(r,at,g) in enumerate(zip(fixtures,cuts,legacy_grids)):
            predictions.append(score_prediction(r,g,'legacy_poisson',at,rates=legacy[i]['rates']))
            actual=[r['home_goals_90'],r['away_goals_90']]
            predictions.append(dict(match_id=r['match_id'],competition_id=r['competition_id'],
                season=r['season'],kickoff_utc=r['kickoff_utc'],asof_utc=at.isoformat(),
                model='fixed_1_0',score=[1,0],actual=actual,points=base.points([1,0],actual)))
        if all_candidates or selected=='legacy_boosted':
            boosted = base.predict(fixtures,rows,cuts,base.fit(rows,fold,24,'boosted'),'boosted')
            for r,at,b in zip(fixtures,cuts,boosted):
                predictions.append(score_prediction(r,distribution(*b['rates'])[0],'legacy_boosted',at,rates=b['rates']))
        for config in needed:
            fitted = Strength(config['half_life'],config['ridge']).fit(rows,fold)
            fitting.append(dict(config=config['name'],**fitted.fit_info))
            rates = fitted.rates(fixtures)
            for i,(r,at,(h,a)) in enumerate(zip(fixtures,cuts,rates)):
                raw,tail,_ = distribution(h,a)
                dc,_,rho = distribution(h,a,fitted.rho)
                matrices = {config['name']:raw,config['name']+'_dc':dc,
                            config['name']+'_dc_blend50':mixture(dc,legacy_grids[i])}
                for name,g in matrices.items():
                    if all_candidates or name==selected:
                        predictions.append(score_prediction(r,g,name,at,rates=[float(h),float(a)],
                            fitted_rho=fitted.rho,effective_rho=rho,omitted_tail=tail))
        print(f'{fold.date()} : {len(fixtures)} fixtures evaluated',flush=True)
        fold=stop
    return predictions,fitting


def summarize(predictions):
    groups=defaultdict(list)
    for r in predictions:
        groups[(r['model'],'ALL')].append(r)
        groups[(r['model'],r['season'])].append(r)
        groups[(r['model'],r['competition_id'])].append(r)
    return [dict(model=m,group=g,matches=len(rs),points=sum(r['points'] for r in rs),
                 mean_points=float(np.mean([r['points'] for r in rs])),
                 exact_hits=sum(r['score']==r['actual'] for r in rs),
                 correct_outcomes=sum(r['points']>0 for r in rs),
                 **{k:float(np.mean([r[k] for r in rs])) if all(k in r for r in rs) else None
                    for k in ['outcome_log_loss','outcome_brier','exact_log_loss']})
            for (m,g),rs in sorted(groups.items())]


def paired_interval(predictions, selected, baseline='legacy_poisson'):
    left={r['match_id']:r for r in predictions if r['model']==selected}
    right={r['match_id']:r for r in predictions if r['model']==baseline}
    weeks=defaultdict(lambda:[0,0])
    common=sorted(left.keys()&right.keys())
    for mid in common:
        week=tuple(base.ts(left[mid]['kickoff_utc']).isocalendar()[:2])
        weeks[week][0]+=left[mid]['points']-right[mid]['points'];weeks[week][1]+=1
    if not weeks: raise ValueError('No paired results')
    blocks=np.array(list(weeks.values()),dtype=float)
    ix=np.random.default_rng(20261027).integers(len(blocks),size=(5000,len(blocks)))
    draws=blocks[ix].sum(axis=1)
    return dict(left=selected,right=baseline,matches=len(common),
                mean_points_difference=float(blocks[:,0].sum()/blocks[:,1].sum()),
                approximate_week_bootstrap_95_interval=np.quantile(draws[:,0]/draws[:,1],[.025,.975]).tolist())


def choose_candidate(summaries):
    # Predeclared: maximize pooled development points. Tie: lower exact-score log loss,
    # then lexical name. Fixed score is a control, not an eligible trained candidate.
    eligible=[r for r in summaries if r['group']=='ALL' and r['model']!='fixed_1_0']
    return sorted(eligible,key=lambda r:(-r['mean_points'],r['exact_log_loss'],r['model']))[0]['model']


def write_json(path,obj):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf8')


def develop(data,output):
    rows=base.load(data)
    cutoff=base.ts(DEVELOP_END)
    # Refuse newer fixtures even if the caller accidentally supplies a combined archive.
    if any(base.ts(r['kickoff_utc'])>=cutoff for r in rows):
        raise ValueError('Development input contains reserved-season fixtures')
    started=time.perf_counter()
    predictions,fits=evaluate(rows,DEVELOP_START,DEVELOP_END)
    summaries=summarize(predictions);selected=choose_candidate(summaries)
    report=dict(stage='development',version=VERSION,input_sha256=digest(data),
                window=[DEVELOP_START,DEVELOP_END],summary=summaries,predictions=predictions,
                fitting=fits,elapsed_seconds=time.perf_counter()-started,selected_candidate=selected)
    write_json(output,report)
    print('Selected on development:',selected,flush=True)
    for r in summaries:
        if r['group']=='ALL': print(r['model'],round(r['mean_points'],2),flush=True)
    return report


def freeze(data,development,lock):
    if Path(lock).exists(): raise FileExistsError('Do not overwrite a frozen experiment')
    rows=base.load(data);report=json.loads(Path(development).read_text(encoding='utf8'))
    if report['stage']!='development' or report['input_sha256']!=digest(data):
        raise ValueError('Development report does not match input')
    selected=choose_candidate(report['summary'])
    candidates=[s['name']+suffix for s in SETTINGS for suffix in ['', '_dc','_dc_blend50']]
    candidates+=['legacy_poisson','legacy_boosted']
    if selected not in candidates: raise ValueError('Unknown candidate')
    record=dict(version=VERSION,locked_at_utc=datetime.now(timezone.utc).isoformat(),
        selected=selected,code_sha256=code_hashes(),development_rows_sha256=rows_hash(rows),
        development_report_sha256=digest(development),development_end=DEVELOP_END,
        settings=SETTINGS,refit='monthly; use only earlier available labels; fixed hyperparameters',
        candidate_selection='Highest 2021/22-2023/24 mean game points; ties lower exact log loss then name',
        holdout=['2024-25','2025-26'],holdout_start=DEVELOP_END,holdout_end='2026-07-01T00:00:00Z',
        timing='day-level proxy; one day before date proxy; reconstructed 2-day result availability',
        no_test_tuning=True)
    write_json(lock,record);print('Frozen model:',selected)


def test_recent(data,lock,output):
    if Path(output).exists(): raise FileExistsError('Reserved test already exists; do not silently rerun/tune it')
    frozen=json.loads(Path(lock).read_text(encoding='utf8'))
    if code_hashes()!=frozen['code_sha256']: raise ValueError('Model/adapter code changed after freezing')
    rows=base.load(data)
    old=[r for r in rows if base.ts(r['kickoff_utc'])<base.ts(frozen['development_end'])]
    if rows_hash(old)!=frozen['development_rows_sha256']: raise ValueError('Development history changed')
    selected=frozen['selected']
    started=time.perf_counter()
    predictions,fits=evaluate(rows,frozen['holdout_start'],frozen['holdout_end'],False,selected)
    summary=summarize(predictions)
    report=dict(stage='reserved_test',version=VERSION,lock_sha256=digest(lock),
                selected_candidate=selected,input_sha256=digest(data),summary=summary,
                comparisons=[paired_interval(predictions,selected)],fitting=fits,predictions=predictions,
                elapsed_seconds=time.perf_counter()-started,
                caveats=['Retrospective day-level timings; no archived pre-kickoff information feed',
                         'Earlier test results can update subsequent monthly fits; no test-driven tuning',
                         'Source coverage/quality may leave some requested recent seasons incomplete',
                         'No odds, xG, lineup data or comparison with betting markets'])
    write_json(output,report)
    for r in summary:
        if r['group']=='ALL' or r['group'] in frozen['holdout']:
            print(r['model'],r['group'],r['matches'],round(r['mean_points'],2),flush=True)
    print(json.dumps(report['comparisons']),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['develop','freeze','test'])
    parser.add_argument('--data',required=True,type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--development',type=Path)
    parser.add_argument('--lock',type=Path)
    args=parser.parse_args()
    if args.mode=='develop': develop(args.data,args.output)
    elif args.mode=='freeze': freeze(args.data,args.development,args.lock)
    else: test_recent(args.data,args.lock,args.output)


if __name__=='__main__':main()
