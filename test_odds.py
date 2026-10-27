"""Synthetic fixtures test collection safety and probability plumbing, not accuracy."""
import copy
import json
import os
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
from scipy.stats import poisson

import odds_collector as c
import odds_market as m
import predictor as base

NOW = c.instant('2030-01-01T12:00:00Z')
FAKE_KEY = 'SYNTHETIC_TEST_KEY_ONLY'
TEST_WORK = Path(__file__).resolve().parent/'work'/'tests'
TEST_WORK.mkdir(parents=True, exist_ok=True)


def event(line=2.5):
    _, probs, _ = base.grid(1.8, 1.)
    over = poisson.sf(int(line), 2.8)
    return dict(id='synthetic-event', sport_key=c.SPORT, commence_time=c.stamp(NOW+timedelta(days=1)),
        home_team='Synthetic Home', away_team='Synthetic Away', bookmakers=[dict(key='test_book',
        last_update=c.stamp(NOW-timedelta(minutes=1)), markets=[dict(key='h2h', outcomes=[
            dict(name=n, price=float(1/p)) for n, p in zip(['Synthetic Home','Draw','Synthetic Away'], probs)]),
        dict(key='totals', outcomes=[dict(name='Over',point=line,price=float(1/over)),
                                   dict(name='Under',point=line,price=float(1/(1-over)))])])])


class CollectorChecks(unittest.TestCase):
    def test_env_key_and_http_errors_are_not_printable_secrets(self):
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder, patch.dict(os.environ, {'ODDS_API_KEY':''}):
            path=Path(folder)/'.env';path.write_text('ODDS_API_KEY='+FAKE_KEY+'\n')
            self.assertEqual(c.load_key(path), FAKE_KEY)
        with patch('odds_collector.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=c.urllib.error.URLError('URL contains '+FAKE_KEY)
            with self.assertRaises(c.CollectionError) as raised:c.api_get('sports',FAKE_KEY)
            self.assertNotIn(FAKE_KEY,str(raised.exception))
        self.assertIsNone(c.NoRedirect().redirect_request(None,None,302,'',{},'https://other.example'))

    def test_pre_match_only_and_both_market_timestamps(self):
        e=event();rows,problems=c.normalize([e],c.stamp(NOW))
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['prices']),2);self.assertFalse(problems)
        self.assertTrue(all(p['available_at_utc']==c.stamp(NOW) for p in rows[0]['prices']))
        e['commence_time']=c.stamp(NOW)
        self.assertFalse(c.normalize([e],c.stamp(NOW))[0])
        e=event();e['bookmakers'][0]['markets'][0]['last_update']=c.stamp(NOW+timedelta(seconds=1))
        e['bookmakers'][0]['markets'][1]['last_update']=c.stamp(NOW-timedelta(days=2))
        self.assertEqual(c.normalize([e],c.stamp(NOW))[0][0]['prices'],[])

    def test_total_lines_and_incomplete_prices(self):
        e=event(3.5)
        prices=c.normalize([e],c.stamp(NOW))[0][0]['prices']
        self.assertEqual({o['point'] for p in prices if p['market']=='totals' for o in p['outcomes']},{3.5})
        e['bookmakers'][0]['markets'][1]['outcomes'].pop()
        e['bookmakers'][0]['markets'][0]['outcomes'][0]['price']=float('nan')
        self.assertEqual(c.normalize([e],c.stamp(NOW))[0][0]['prices'],[])

    def test_credit_reserve_and_account_budget(self):
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder, closing(c.database(folder)) as db:
            for quota in [dict(used=None,remaining=500),dict(used=199,remaining=301),dict(used=0,remaining=51)]:
                with self.assertRaises(c.CollectionError):c.reserve(db,NOW,quota)
            self.assertEqual(db.execute('SELECT count(*) FROM requests').fetchone()[0],0)
            first=c.reserve(db,NOW,dict(used=0,remaining=500))
            self.assertIsNotNone(first)
            self.assertIsNone(c.reserve(db,NOW+timedelta(hours=1),dict(used=0,remaining=500)))

    def test_immutable_archive_cooldown_and_quota_log(self):
        calls=[]
        def fake(endpoint,key,params=None):
            calls.append((endpoint,params))
            if endpoint=='odds':
                self.assertRegex(params['commenceTimeFrom'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$')
                self.assertNotIn('.',params['commenceTimeTo'])
            body=[dict(key=c.SPORT,active=True)] if endpoint=='sports' else [event()]
            return dict(body=body,quota=dict(used=0 if endpoint=='sports' else 2,
                remaining=500 if endpoint=='sports' else 498,cost=0 if endpoint=='sports' else 2),
                requested_at_utc=c.stamp(NOW),received_at_utc=c.stamp(NOW+timedelta(seconds=1)))
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder:
            result=c.collect(folder,FAKE_KEY,transport=fake,now=NOW+timedelta(microseconds=123456))
            self.assertEqual(result['status'],'saved');self.assertEqual(result['quota']['cost'],2)
            stored=Path(result['archive']).read_text();self.assertNotIn(FAKE_KEY,stored)
            payload=json.loads(stored);self.assertEqual(len(payload['normalized_events']),1)
            self.assertEqual(c.collect(folder,FAKE_KEY,transport=fake,now=NOW+timedelta(hours=1))['status'],'not_due')
            self.assertEqual(len(calls),2)
            self.assertEqual(c.status(folder)['saved_snapshots'],1)
            self.assertEqual(c.status(folder)['recent_requests'][0]['remaining'],498)

    def test_known_request_rejection_allows_corrected_manual_retry(self):
        calls=[]
        def fake(endpoint,key,params=None):
            calls.append(endpoint)
            if endpoint=='odds':raise c.CollectionError('Provider HTTP 422.',http_status=422,allowance=dict(cost=0,remaining=500,used=0))
            return dict(body=[dict(key=c.SPORT,active=True)],quota=dict(used=0,remaining=500,cost=0),received_at_utc=c.stamp(NOW))
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder:
            for i in range(2):
                with self.assertRaises(c.CollectionError):c.collect(folder,FAKE_KEY,transport=fake,now=NOW+timedelta(minutes=i))
            self.assertEqual(c.status(folder)['recent_requests'][0]['status'],'rejected')
            self.assertEqual(c.status(folder)['recent_requests'][0]['cost'],0)
            self.assertEqual(calls,['sports','odds','sports','odds'])

    def test_ambiguous_paid_call_does_not_trigger_immediate_retry(self):
        count=[]
        def fake(endpoint,key,params=None):
            count.append(endpoint)
            if endpoint=='odds':raise c.CollectionError('Network failed; charge unknown.')
            return dict(body=[dict(key=c.SPORT,active=True)],quota=dict(used=0,remaining=500,cost=0),received_at_utc=c.stamp(NOW))
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder:
            with self.assertRaises(c.CollectionError):c.collect(folder,FAKE_KEY,transport=fake,now=NOW)
            self.assertEqual(c.collect(folder,FAKE_KEY,transport=fake,now=NOW+timedelta(hours=1))['status'],'not_due')
            self.assertEqual(count,['sports','odds'])
            self.assertEqual(c.status(folder)['recent_requests'][0]['status'],'failed_or_ambiguous')


class MarketChecks(unittest.TestCase):
    def test_fit_recovers_known_rates_using_actual_35_line(self):
        normalized=c.normalize([event(3.5)],c.stamp(NOW))[0][0]
        got=m.fit_event(normalized,c.stamp(NOW))
        np.testing.assert_allclose(got['rates'],[1.8,1.],atol=1e-5)
        self.assertEqual(got['total_lines'],[3.5])
        self.assertAlmostEqual(sum(got['outcome_probabilities']),1)
        self.assertLess(got['max_probability_fit_error'],1e-6)
        self.assertEqual(got['score'],base.select(1.8,1.)['score'])

    def test_integer_and_quarter_totals_not_treated_as_half_goal_lines(self):
        for line in [2.,2.25,2.75]:
            normalized=c.normalize([event(line)],c.stamp(NOW))[0][0]
            self.assertIsNone(m.fit_event(normalized,c.stamp(NOW)))

    def test_future_availability_and_started_games_never_predict(self):
        e=c.normalize([event()],c.stamp(NOW))[0][0]
        changed=copy.deepcopy(e)
        for price in changed['prices']:price['available_at_utc']=c.stamp(NOW+timedelta(seconds=1))
        self.assertIsNone(m.fit_event(changed,c.stamp(NOW)))
        self.assertIsNone(m.fit_event(e,e['kickoff_utc']))
        self.assertIsNone(m.fit_event(e,c.stamp(NOW+timedelta(hours=25))))

    def test_forecast_log_cannot_overwrite_or_be_backdated(self):
        with tempfile.TemporaryDirectory(dir=TEST_WORK) as folder:
            source=Path(folder)/'snapshot.json'
            source.write_text(json.dumps(dict(received_at_utc=c.stamp(NOW),normalized_events=c.normalize([event()],c.stamp(NOW))[0])))
            result=m.forecast_snapshot(source,Path(folder)/'forecasts',now=NOW)
            self.assertEqual(result['saved_forecasts'],1)
            with self.assertRaises(FileExistsError):m.forecast_snapshot(source,Path(folder)/'forecasts',now=NOW)
            with self.assertRaises(ValueError):m.forecast_snapshot(source,Path(folder)/'other',now=NOW-timedelta(seconds=1))


if __name__=='__main__':unittest.main()
