"""Market-derived Poisson benchmark. Supports actual half-goal total lines, not just 2.5."""
import argparse
import hashlib
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

import odds_collector as archive
import predictor as base

VERSION = 'market-poisson-v1'


def fit_event(event, asof):
    at = archive.instant(asof)
    kick = archive.instant(event['kickoff_utc'])
    if kick <= at:
        return None
    latest = {}
    for price in event['prices']:
        quoted = archive.instant(price['quoted_at_utc'])
        available = archive.instant(price['available_at_utc'])
        if quoted > available or available > at or quoted > at or at-quoted > timedelta(hours=24):
            continue
        key = (price['bookmaker'], price['market'])
        if key not in latest or quoted > archive.instant(latest[key]['quoted_at_utc']):
            latest[key] = price
    targets = []
    for book in sorted({b for b, market in latest}):
        h2h, totals = latest.get((book, 'h2h')), latest.get((book, 'totals'))
        if h2h is None or totals is None:
            continue
        odds = {o['name']: o['price'] for o in h2h['outcomes']}
        names = [event['home_team'], 'Draw', event['away_team']]
        if set(odds) != set(names) or any(not archive.decimal(odds[n]) for n in names):
            continue
        p = 1/np.array([odds[n] for n in names]);p /= p.sum()
        lines = {}
        for o in totals['outcomes']:
            line = o['point']
            # Integer/quarter Asian lines have pushes/partial settlements. Preserve
            # them in the archive, but do not force them through a half-goal model.
            if 0 < line <= 10 and abs(line % 1-.5) < 1e-9:
                lines.setdefault(line, {})[o['name']] = o['price']
        pairs = []
        for line, prices in sorted(lines.items()):
            if set(prices) == {'Over', 'Under'} and all(archive.decimal(v) for v in prices.values()):
                inverse = np.array([1/prices['Over'], 1/prices['Under']])
                pairs.append((line, float(inverse[0]/inverse.sum())))
        if pairs:
            targets.append((book, p, pairs))
    if not targets:
        return None

    def residual(log_rates):
        rates = np.exp(log_rates)
        _, outcome, _ = base.grid(*rates)
        differences = []
        for _, target, pairs in targets:
            differences.extend((outcome-target)/np.sqrt(3))
            differences.extend((poisson.sf(int(line), rates.sum())-over)/np.sqrt(len(pairs)) for line, over in pairs)
        return np.asarray(differences)/np.sqrt(len(targets))

    solved = least_squares(residual, np.log([1.5, 1.2]),
                            bounds=(np.log([.03, .03]), np.log([10., 10.])))
    if not solved.success:
        return None
    result = base.select(*np.exp(solved.x))
    errors = []
    _, outcome, _ = base.grid(*result['rates'])
    for _, target, pairs in targets:
        errors.extend(abs(outcome-target))
        errors.extend(abs(poisson.sf(int(line), sum(result['rates']))-over) for line, over in pairs)
    result.update(model=VERSION, asof_utc=asof, bookmakers=[b for b, _, _ in targets],
                  total_lines=sorted({line for _, _, pairs in targets for line, _ in pairs}),
                  max_probability_fit_error=float(max(errors)),
                  de_vig_method='inverse_decimal_odds_normalized_within_book_and_market')
    return result


def forecast_snapshot(path, destination, now=None):
    envelope = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    at = now or archive.utcnow()
    if archive.instant(envelope['received_at_utc']) > at:
        raise ValueError('Snapshot was not available before forecast generation')
    forecasts = []
    for event in envelope['normalized_events']:
        result = fit_event(event, archive.stamp(at))
        if result is not None:
            forecasts.append(dict(event_id=event['event_id'], home_team=event['home_team'],
                away_team=event['away_team'], kickoff_utc=event['kickoff_utc'], **result))
    generated = archive.utcnow() if now is None else now
    forecasts = [r for r in forecasts if generated < archive.instant(r['kickoff_utc'])]
    payload = dict(version=VERSION, generated_at_utc=archive.stamp(generated),
                   source_snapshot=Path(path).name, source_snapshot_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                   model_code_sha256={name:hashlib.sha256((archive.ROOT/name).read_bytes()).hexdigest() for name in ['odds_market.py','predictor.py']}, forecasts=forecasts,
                   qualification='Market benchmark only; no measured improvement or completed paired comparison yet')
    dest = Path(destination);dest.mkdir(parents=True, exist_ok=True)
    target = dest/(Path(path).stem+'.forecasts.json')
    # No overwrites: repeated runs cannot silently replace a previously saved pick.
    with target.open('x', encoding='utf8') as f:
        f.write(json.dumps(payload, ensure_ascii=False, allow_nan=False)+'\n')
    return dict(saved_forecasts=len(forecasts), forecast_archive=str(target))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--output-dir', type=Path, default=archive.ROOT/'data'/'odds'/'forecasts')
    args = parser.parse_args()
    print(json.dumps(forecast_snapshot(args.snapshot, args.output_dir)))
