"""Keyless OpenFootball historical-data adapter. Only configured senior leagues.
Uses date-level proxies: this is NOT an exact-hour historical-data archive.
"""
import argparse
import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from predictor import validate

REF = 'e6744429ee395bc86f247348c6184bb08d4eb361'
ROOT = 'https://raw.githubusercontent.com/openfootball/football.json'
LEAGUES = {
    'en.1': 'English Premier League', 'de.1': 'Bundesliga',
    'es.1': 'La Liga', 'it.1': 'Serie A', 'fr.1': 'Ligue 1',
    'nl.1': 'Eredivisie', 'pt.1': 'Primeira Liga',
}
# Explicit identity mappings reviewed against the downloaded seasons. No fuzzy matching.
ALIAS_GROUPS = {
 'en': [
  ['Aston Villa', 'Aston Villa FC'], ['Brighton & Hove Albion', 'Brighton & Hove Albion FC'],
  ['Crystal Palace', 'Crystal Palace FC'], ['Leeds United', 'Leeds United FC'],
  ['Leicester City', 'Leicester City FC'], ['Manchester City', 'Manchester City FC'],
  ['Manchester United', 'Manchester United FC'], ['Newcastle United', 'Newcastle United FC'],
  ['Norwich City', 'Norwich City FC'], ['Sheffield United', 'Sheffield United FC'],
  ['Tottenham Hotspur', 'Tottenham Hotspur FC'], ['West Bromwich Albion', 'West Bromwich Albion FC'],
  ['West Ham United', 'West Ham United FC'], ['Wolverhampton Wanderers', 'Wolverhampton Wanderers FC'],
 ],
 'de': [
  ['1899 Hoffenheim', 'TSG 1899 Hoffenheim'], ['Bayer Leverkusen', 'Bayer 04 Leverkusen'],
  ['Bayern München', 'FC Bayern München'], ['Bor. Mönchengladbach', 'Borussia Mönchengladbach'],
  ['Werder Bremen', 'SV Werder Bremen'],
 ],
 'es': [
  ['Atlético Madrid', 'Club Atlético de Madrid'], ['CD Alavés', 'Deportivo Alavés'],
  ['Espanyol Barcelona', 'RCD Espanyol de Barcelona'], ['RC Celta', 'RC Celta de Vigo'],
  ['Real Betis', 'Real Betis Balompié'], ['Real Madrid', 'Real Madrid CF'],
  ['Real Sociedad', 'Real Sociedad de Fútbol'], ['Real Valladolid', 'Real Valladolid CF'],
  ['Rayo Vallecano', 'Rayo Vallecano de Madrid'],
 ],
 'it': [
  ['Atalanta', 'Atalanta BC'], ['Bologna FC', 'Bologna FC 1909'],
  ['Hellas Verona', 'Hellas Verona FC'], ['Inter', 'FC Internazionale Milano'],
  ['Juventus', 'Juventus FC'], ['Lazio Roma', 'SS Lazio'],
  ['Sampdoria', 'UC Sampdoria'], ['Sassuolo Calcio', 'US Sassuolo Calcio'],
 ],
 'fr': [
  ['AS Monaco', 'AS Monaco FC'], ['Olympique Marseille', 'Olympique de Marseille'],
  ['Paris Saint-Germain', 'Paris Saint-Germain FC'], ['RC Lens', 'Racing Club de Lens'],
  ['RC Strasbourg', 'RC Strasbourg Alsace'], ['Stade Rennais', 'Stade Rennais FC 1901'],
 ],
 'nl': [
  ['AZ Alkmaar', 'AZ'], ['FC Twente', "FC Twente '65"], ['Feyenoord', 'Feyenoord Rotterdam'],
  ['NEC Nijmegen', 'NEC'], ['PSV Eindhoven', 'PSV'], ['Vitesse', 'SBV Vitesse'],
  ['sc Heerenveen', 'SC Heerenveen'],
 ],
 'pt': [
  ['Boavista', 'Boavista FC'], ['GD Estoril', 'GD Estoril Praia'], ['Gil Vicente', 'Gil Vicente FC'],
  ['SL Benfica', 'Sport Lisboa e Benfica'], ['Sporting Braga', 'Sporting Clube de Braga'],
  ['Sporting CP', 'Sporting Clube de Portugal'],
 ],
}


def normalized(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Missing team name')
    return ' '.join(unicodedata.normalize('NFC', name).casefold().split())


def team_id(country, name):
    key = normalized(name)
    for group in ALIAS_GROUPS.get(country, []):
        if key in {normalized(item) for item in group}:
            key = normalized(group[0])
            break
    return f'openfootball:{country}:{key}'


def convert(document, league, season, source_url, result_delay_days=2):
    if league not in LEAGUES:
        raise ValueError('Competition not configured as a 90-minute senior league')
    if not re.fullmatch(r'20\d\d-\d\d', season):
        raise ValueError('Invalid season')
    if result_delay_days < 2:
        raise ValueError('At least two days required for reconstructed result availability')
    if not isinstance(document.get('matches'), list):
        raise ValueError('Source is missing matches array')
    rows, skipped, seen = [], Counter(), set()
    country = league.split('.')[0]
    for item in document['matches']:
        # Do not silently use administrative awards, abandoned games or unknown statuses.
        status = item.get('status')
        if status not in (None, 'finished'):
            skipped['status:' + str(status)] += 1
            continue
        score = item.get('score')
        if not score:
            skipped['no_full_time_score'] += 1
            continue
        if not re.fullmatch(r'Matchday \d+', item.get('round', '')):
            skipped['non_regular_round'] += 1
            continue
        if isinstance(score, dict) and any(k in score for k in ['et', 'aet', 'p', 'pen']):
            skipped['extra_time_or_penalties'] += 1
            continue
        final = score.get('ft') if isinstance(score, dict) else score
        if final is None:
            skipped['no_full_time_score'] += 1
            continue
        if (not isinstance(final, list) or len(final) != 2 or
                any(type(x) is not int or not 0 <= x <= 100 for x in final)):
            raise ValueError('Invalid full-time score')
        day = date.fromisoformat(item['date'])
        start_year = int(season[:4])
        if not start_year <= day.year <= start_year + 2:
            raise ValueError('Date falls outside the expected season range')
        # Source local times have no explicit UTC offset. Retain them for auditing only.
        # Midnight UTC is an explicit day-ordering proxy, never claimed as actual kickoff.
        proxy = datetime.combine(day, datetime.min.time(), timezone.utc)
        home = team_id(country, item['team1'])
        away = team_id(country, item['team2'])
        # Regular leagues have one home fixture per team pair per season. Exclude the
        # date from identity so rescheduling cannot create a second logical fixture.
        identity = f'{league}|{season}|{home}|{away}'
        match_id = 'openfootball:' + hashlib.sha256(identity.encode()).hexdigest()[:24]
        if match_id in seen:
            raise ValueError('Duplicate fixture: review rescheduling/league format')
        seen.add(match_id)
        row = dict(match_id=match_id, competition_id='openfootball:' + league,
            season=season, segment='men_senior_club', home_team_id=home, away_team_id=away,
            home_team_name=item['team1'], away_team_name=item['team2'],
            kickoff_utc=proxy.isoformat(), kickoff_basis='date_proxy_utc_midnight',
            source_match_date=item['date'], source_local_time=item.get('time'),
            source=source_url, neutral_venue=False, venue_basis='listed_home_team_assumption',
            home_goals_90=final[0], away_goals_90=final[1], status='FINISHED',
            score_scope='REGULATION', availability_basis='reconstructed',
            result_available_at_utc=(proxy + timedelta(days=result_delay_days)).isoformat())
        rows.append(validate(row))
    return rows, dict(skipped)


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'football-research-prototype/0.1'})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(5_000_001)
    if len(body) > 5_000_000:
        raise ValueError('Unexpectedly large league file')
    return json.loads(body)


def collect(destination, leagues, seasons, ref=REF, cache_only=False, result_delay_days=2):
    if not re.fullmatch(r'[0-9a-f]{40}', ref):
        raise ValueError('Use a pinned repository commit SHA for reproducibility')
    destination.mkdir(parents=True, exist_ok=True)
    output, manifest = [], []
    retrieved = datetime.now(timezone.utc).isoformat()
    for season in seasons:
        for league in leagues:
            if league not in LEAGUES or not re.fullmatch(r'20\d\d-\d\d', season):
                raise ValueError('Unsupported league or season')
            url = f'{ROOT}/{ref}/{season}/{league}.json'
            # Ref-namespaced caches prevent silent reuse of a different source version.
            path = destination / 'raw' / ref / season / (league + '.json')
            cached = path.exists()
            if cached:
                data = json.loads(path.read_text(encoding='utf-8-sig'))
            elif cache_only:
                raise FileNotFoundError(f'Missing cache: {path}')
            else:
                data = download(url)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
            rows, skipped = convert(data, league, season, url, result_delay_days)
            output.extend(rows)
            manifest.append(dict(league=league, league_name=LEAGUES[league], season=season,
                source=url, cache_path=str(path.relative_to(destination)),
                cache_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                included=len(rows), skipped=skipped, acquisition='existing_cache' if cached else 'https_download'))
    ids = [r['match_id'] for r in output]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate match IDs across files')
    output.sort(key=lambda r: (r['kickoff_utc'], r['match_id']))
    target = destination / f'matches-delay{result_delay_days}d.jsonl'
    target.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in output), encoding='utf-8')
    report = dict(provider='OpenFootball public JSON API', repository_ref=ref,
        assembled_at_utc=retrieved, cost_usd=0, matches=len(output), files=manifest,
        normalized_file=target.name, normalized_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        timing='Day-level retrospective proxy; not an archived 24-hour pre-kickoff replay',
        result_delay_days=result_delay_days,
        limitations=['No odds, xG, lineups or archived information-availability timestamps',
            'Listed home side assumed non-neutral; exceptional venues are not identified',
            'Administrative decisions without source status and later corrections may remain',
            'Coverage and missing match/club identities require further independent checking'])
    (destination / f'manifest-delay{result_delay_days}d.json').write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path(__file__).parent / 'data')
    parser.add_argument('--leagues', nargs='+', choices=sorted(LEAGUES), default=list(LEAGUES))
    parser.add_argument('--seasons', nargs='+', default=[f'{y}-{str(y+1)[-2:]}' for y in range(2018, 2024)])
    parser.add_argument('--ref', default=REF)
    parser.add_argument('--cache-only', action='store_true')
    parser.add_argument('--result-delay-days', type=int, choices=[2, 3], default=2)
    args = parser.parse_args()
    report = collect(args.data_dir, args.leagues, args.seasons, args.ref,
                     args.cache_only, args.result_delay_days)
    print(f"OpenFootball: {report['matches']} completed regulation fixtures from {len(report['files'])} league-season files; $0.")
    print('Retrospective day-level data. No archived odds or exact prediction-time replay.')
    print(args.data_dir / report['normalized_file'])


if __name__ == '__main__':
    main()
