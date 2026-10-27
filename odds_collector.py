"""Local, quota-limited pre-match odds archive. Uses only Python's standard library."""
import argparse
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = 'https://api.the-odds-api.com'
SPORT = 'soccer_epl'
MARKETS = 'h2h,totals'
REGION = 'eu'
VERSION = 'odds-archive-v1'


class CollectionError(RuntimeError):
    """Safe to print: never include a request URL, key, provider error body or traceback."""
    def __init__(self, message, http_status=None, allowance=None):
        super().__init__(message)
        self.http_status = http_status
        self.allowance = allowance or {}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return parsed.astimezone(timezone.utc)


def load_key(path):
    key = os.environ.get('ODDS_API_KEY', '').strip()
    if not key and Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line.startswith('ODDS_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('\"\'')
    if not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key):
        raise CollectionError('Add a valid ODDS_API_KEY to the local .env file.')
    return key


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authentication is a required query parameter; never redirect it elsewhere.
        return None


def quota(headers):
    lowered = {str(k).lower(): str(v) for k, v in headers.items()}
    result = {}
    for key, header in [('remaining', 'x-requests-remaining'),
                        ('used', 'x-requests-used'), ('cost', 'x-requests-last')]:
        raw = lowered.get(header)
        result[key] = int(raw) if raw is not None and raw.isdigit() else None
    return result


def api_get(endpoint, key, params=None):
    allowed = {'sports': '/v4/sports/', 'odds': f'/v4/sports/{SPORT}/odds/'}
    if endpoint not in allowed:
        raise CollectionError('Unsupported API endpoint.')
    query = dict(params or {}, apiKey=key)
    req = urllib.request.Request(HOST + allowed[endpoint] + '?' + urllib.parse.urlencode(query),
                                 headers={'User-Agent': 'football-predictor/0.4'})
    requested = utcnow()
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=30) as response:
            payload = response.read(10_000_001)
            received = utcnow()
            if len(payload) > 10_000_000:
                raise CollectionError('Response exceeds the archive size limit.')
            if key.encode() in payload:
                raise CollectionError('Response unexpectedly contains authentication data; not saved.')
            body = json.loads(payload)
            if not isinstance(body, list):
                raise CollectionError('Unexpected provider response schema.')
            return dict(body=body, quota=quota(response.headers),
                        requested_at_utc=stamp(requested), received_at_utc=stamp(received))
    except urllib.error.HTTPError as exc:
        advice = {401: 'Check the local API key.', 403: 'Account access was denied.',
                  429: 'Quota or rate limit reached; no automatic retry.'}
        error_code = None
        try:
            error_code = json.loads(exc.read(4096)).get('error_code')
        except (ValueError, AttributeError, OSError):
            pass
        label = f' ({error_code})' if isinstance(error_code, str) and re.fullmatch(r'[A-Z_]{1,80}', error_code) else ''
        raise CollectionError(f'Provider HTTP {exc.code}{label}. ' + advice.get(exc.code, 'Request stopped.'),
                              http_status=exc.code, allowance=quota(exc.headers or {})) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CollectionError('Network/DNS connection failed. Run the collector in a normal terminal with internet access.') from None
    except (ValueError, UnicodeError):
        raise CollectionError('Invalid provider JSON response; no automatic retry.') from None


def decimal(value):
    return type(value) in (float, int) and math.isfinite(value) and value > 1


def normalize(events, received):
    """Keep valid pre-match markets. Invalid/missing prices are never zero-filled."""
    at = instant(received)
    output, rejected, seen = [], Counter(), set()
    for event in events:
        try:
            event_id = event['id']
            if not isinstance(event_id, str) or not event_id or event_id in seen:
                raise ValueError('duplicate_or_invalid_id')
            seen.add(event_id)
            if event.get('sport_key') != SPORT:
                raise ValueError('wrong_sport')
            kick = instant(event['commence_time'])
            if kick <= at:
                raise ValueError('already_started')
            home, away = event['home_team'], event['away_team']
            if not all(isinstance(n, str) and n for n in [home, away]) or home == away:
                raise ValueError('invalid_teams')
        except (KeyError, TypeError, ValueError):
            rejected['invalid_or_started_event'] += 1
            continue
        prices, seen_books = [], set()
        for book in event.get('bookmakers', []):
            book_key = book.get('key')
            if not isinstance(book_key, str) or not book_key or book_key in seen_books:
                rejected['invalid_or_duplicate_bookmaker'] += 1
                continue
            seen_books.add(book_key)
            seen_markets = set()
            for market in book.get('markets', []):
                kind = market.get('key')
                if kind not in ['h2h', 'totals'] or kind in seen_markets:
                    continue
                seen_markets.add(kind)
                try:
                    quote_time = instant(market.get('last_update') or book['last_update'])
                    if quote_time > at or quote_time >= kick or at - quote_time > timedelta(hours=24):
                        raise ValueError('future_or_stale_quote')
                    outcomes = market['outcomes']
                    if not outcomes or any(not decimal(o.get('price')) for o in outcomes):
                        raise ValueError('invalid_price')
                    if kind == 'h2h':
                        if len(outcomes) != 3 or {o['name'] for o in outcomes} != {home, 'Draw', away}:
                            raise ValueError('not_three_way_regulation_market')
                        clean = [dict(name=o['name'], price=o['price']) for o in outcomes]
                    else:
                        groups = {}
                        for o in outcomes:
                            line = o['point']
                            if type(line) not in (float, int) or not math.isfinite(line) or line < 0:
                                raise ValueError('invalid_total_line')
                            if o['name'] not in ['Over', 'Under']:
                                raise ValueError('invalid_total_side')
                            groups.setdefault(line, []).append(o)
                        clean = []
                        for line, pair in groups.items():
                            if len(pair) != 2 or {o['name'] for o in pair} != {'Over', 'Under'}:
                                raise ValueError('incomplete_total_pair')
                            clean.extend(dict(name=o['name'], price=o['price'], point=line) for o in pair)
                    prices.append(dict(bookmaker=book_key, market=kind,
                        quoted_at_utc=stamp(quote_time), available_at_utc=received, outcomes=clean))
                except (KeyError, TypeError, ValueError):
                    rejected['invalid_stale_or_incomplete_market'] += 1
        output.append(dict(event_id=event_id, sport_key=SPORT, home_team=home, away_team=away,
                           kickoff_utc=stamp(kick), prices=prices))
    return output, dict(rejected)


def database(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'odds.sqlite3', timeout=2)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY, requested_at_utc TEXT NOT NULL, received_at_utc TEXT,
        endpoint TEXT NOT NULL, status TEXT NOT NULL, cost INTEGER, remaining INTEGER,
        used INTEGER, archive_path TEXT, events INTEGER, prices INTEGER, error TEXT)''')
    db.commit()
    return db


def reserve(db, now, allowance, interval_hours=12, budget=200, reserve_credits=50):
    if interval_hours < 6 or budget < 2 or reserve_credits < 2:
        raise CollectionError('Use interval >=6 hours, budget >=2 and reserve >=2 credits.')
    db.execute('BEGIN IMMEDIATE')
    try:
        previous = db.execute("SELECT * FROM requests WHERE endpoint='odds' AND status!='rejected' ORDER BY id DESC LIMIT 1").fetchone()
        if previous and now - instant(previous['requested_at_utc']) < timedelta(hours=interval_hours):
            db.rollback()
            return None
        if allowance['used'] is None or allowance['remaining'] is None:
            raise CollectionError('Quota headers unavailable; refusing a quota-consuming request.')
        if allowance['used'] + 2 > budget or allowance['remaining'] - 2 < reserve_credits:
            raise CollectionError('Configured credit budget/reserve reached; collection stopped.')
        cur = db.execute("INSERT INTO requests(requested_at_utc, endpoint, status) VALUES (?, 'odds', 'pending')", (stamp(now),))
        db.commit()
        return cur.lastrowid
    except BaseException:
        db.rollback()
        raise


def update_request(db, request_id, status, **fields):
    allowed = {'received_at_utc', 'cost', 'remaining', 'used', 'archive_path', 'events', 'prices', 'error'}
    if not fields.keys() <= allowed:
        raise ValueError('Unknown request field')
    values = dict(status=status, **fields)
    db.execute('UPDATE requests SET ' + ', '.join(k+'=?' for k in values) + ' WHERE id=?', [*values.values(), request_id])
    db.commit()


def check_account(key, transport=api_get):
    info = transport('sports', key)
    active = any(r.get('key') == SPORT and r.get('active') is True for r in info['body'])
    return dict(connection='verified', epl_active=active, quota=info['quota'], checked_at_utc=info['received_at_utc'])


def collect(folder, key, transport=api_get, now=None, interval_hours=12, budget=200, reserve_credits=50):
    at = now or utcnow()
    with closing(database(folder)) as db:
        # Check the cooldown before even the free network call, including ambiguous attempts.
        prior = db.execute("SELECT * FROM requests WHERE endpoint='odds' AND status!='rejected' ORDER BY id DESC LIMIT 1").fetchone()
        if prior and at - instant(prior['requested_at_utc']) < timedelta(hours=interval_hours):
            return dict(status='not_due', next_attempt_at_utc=stamp(instant(prior['requested_at_utc']) + timedelta(hours=interval_hours)))
        account = check_account(key, transport)
        if not account['epl_active']:
            return dict(status='epl_not_active', **account)
        request_id = reserve(db, at, account['quota'], interval_hours, budget, reserve_credits)
        if request_id is None:
            return dict(status='not_due')
        params = dict(regions=REGION, markets=MARKETS, oddsFormat='decimal', dateFormat='iso',
                      commenceTimeFrom=stamp(at.replace(microsecond=0)),
                      commenceTimeTo=stamp((at+timedelta(days=7)).replace(microsecond=0)))
        try:
            response = transport('odds', key, params)
            events, rejected = normalize(response['body'], response['received_at_utc'])
            envelope = dict(version=VERSION, provider='The Odds API', sport=SPORT,
                parameters=params, requested_at_utc=response['requested_at_utc'],
                received_at_utc=response['received_at_utc'], quota=response['quota'],
                raw_events=response['body'], normalized_events=events, exclusions=rejected)
            serialized = json.dumps(envelope, ensure_ascii=False, allow_nan=False)
            if key in serialized:
                raise CollectionError('Authentication data detected in output; archive not written.')
            raw_dir = Path(folder)/'raw'
            raw_dir.mkdir(exist_ok=True)
            filename = response['received_at_utc'].replace(':', '').replace('.', '') + f'_{request_id}.json'
            path = raw_dir/filename
            with path.open('x', encoding='utf8') as f:
                f.write(serialized+'\n')
            count = sum(len(e['prices']) for e in events)
            update_request(db, request_id, 'saved', received_at_utc=response['received_at_utc'],
                           **response['quota'], archive_path=str(path.resolve()), events=len(events), prices=count)
            return dict(status='saved', events=len(events), markets=count, quota=response['quota'],
                        exclusions=rejected, archive=str(path), available_at_utc=response['received_at_utc'])
        except CollectionError as exc:
            rejected = exc.http_status in (400, 401, 403, 404, 422)
            update_request(db, request_id, 'rejected' if rejected else 'failed_or_ambiguous',
                           error=str(exc), **exc.allowance)
            raise
        except Exception:
            update_request(db, request_id, 'failed_or_ambiguous', error='Archive/response processing failed; inspect local files.')
            raise CollectionError('Archive/response processing failed. Request may have consumed credits; no immediate retry.') from None


def status(folder):
    with closing(database(folder)) as db:
        rows = db.execute('SELECT id,requested_at_utc,received_at_utc,status,cost,remaining,used,events,prices,error FROM requests ORDER BY id DESC LIMIT 5').fetchall()
        total = db.execute("SELECT count(*),coalesce(sum(events),0) FROM requests WHERE status='saved'").fetchone()
        return dict(saved_snapshots=total[0], event_observations=total[1], recent_requests=[dict(r) for r in rows])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'collect', 'watch', 'status'], nargs='?', default='collect')
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'data'/'odds')
    parser.add_argument('--interval-hours', type=float, default=12)
    parser.add_argument('--no-forecasts', action='store_true', help='Collect only, without scientific Python dependencies')
    parser.add_argument('--budget', type=int, default=200, help='Stop before account-wide used credits exceed this limit')
    args = parser.parse_args()
    if args.command == 'status':
        print(json.dumps(status(args.output_dir), indent=2));return
    try:
        key = load_key(args.env_file)
        if args.command == 'check':
            print(json.dumps(check_account(key), indent=2));return
        while True:
            try:
                result = collect(args.output_dir, key, interval_hours=args.interval_hours, budget=args.budget)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if result['status'] == 'saved' and not args.no_forecasts:
                    try:
                        from odds_market import forecast_snapshot
                        print(json.dumps(forecast_snapshot(result['archive'], args.output_dir/'forecasts')), flush=True)
                    except ImportError:
                        print('Odds archived. Install requirements.txt to also log market forecasts.', flush=True)
                    except Exception:
                        print('Odds archived. Forecast logging failed; prices are retained for inspection.', flush=True)
            except CollectionError as exc:
                print('Collector: '+str(exc), file=sys.stderr, flush=True)
                if args.command != 'watch':
                    raise SystemExit(1) from None
            if args.command != 'watch':
                break
            print(f'Waiting {max(6, args.interval_hours):g} hours. Keep this window open; Ctrl+C stops.', flush=True)
            time.sleep(max(6, args.interval_hours)*3600)
    except CollectionError as exc:
        print('Collector: '+str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print('\nCollector stopped. Existing archives retained.')


if __name__ == '__main__':
    main()
