"""Understat joins, xG feature leakage and comparable model fitting checks."""
import copy
import unittest
from datetime import timedelta
import numpy as np
import predictor as p
import understat_import as source
import xg_experiment as x
from test_predictor import row


def example(i,kick):
    r=row(i,kick,h=(i%3)+1,a=i%2)
    r.update(competition_id='openfootball:en.1',home_xg=1.7,away_xg=.6,
             xg_available_at_utc=r['result_available_at_utc'])
    return r


class XGChecks(unittest.TestCase):
    def test_target_and_future_xg_cannot_enter_features(self):
        t=p.ts('2020-01-01T15:00:00Z');past=example(0,t);future=example(1,t+timedelta(days=7))
        cutoff=t+timedelta(days=3)
        first=x.xg_features([future],[past,future],[cutoff])[1][0]
        changed=copy.deepcopy(future);changed['home_xg']=19.;changed['away_xg']=19.
        second=x.xg_features([changed],[past,changed],[cutoff])[1][0]
        np.testing.assert_array_equal(first,second)
        altered=copy.deepcopy(past);altered['home_xg']=4.
        third=x.xg_features([future],[altered,future],[cutoff])[1][0]
        self.assertFalse(np.array_equal(first,third))

    def test_xg_exactly_at_cutoff_is_excluded(self):
        t=p.ts('2020-01-01T15:00:00Z');past=example(0,t);future=example(1,t+timedelta(days=7))
        cutoff=t+timedelta(days=3);past['xg_available_at_utc']=cutoff.isoformat()
        at=x.xg_features([future],[past],[cutoff])[1][0]
        later=copy.deepcopy(past);later['xg_available_at_utc']=(cutoff+timedelta(seconds=1)).isoformat()
        after=x.xg_features([future],[later],[cutoff])[1][0]
        np.testing.assert_array_equal(at,after)

    def test_future_labels_cannot_change_fitted_model(self):
        t=p.ts('2020-01-01T15:00:00Z')
        rows=[example(i,t+timedelta(days=i)) for i in range(140)]
        cut=t+timedelta(days=125)
        plain,extended,_=x.matrices(rows)
        first=x.fit_cached(rows,plain,extended,cut,'xg_poisson')
        changed=copy.deepcopy(rows);changed[-1]['home_goals_90']=99;changed[-1]['home_xg']=19.
        a,b,_=x.matrices(changed)
        second=x.fit_cached(changed,a,b,cut,'xg_poisson')
        np.testing.assert_allclose(first.predict(extended[126]),second.predict(b[126]))

    def test_missing_xg_is_not_zero(self):
        r=example(0,p.ts('2020-01-01T15:00:00Z'));r['home_xg']=None
        with self.assertRaises(ValueError):x.matrices([r])
        r['home_xg']=float('nan')
        with self.assertRaises(ValueError):x.matrices([r])

    def test_join_requires_score_and_two_page_witnesses(self):
        r=example(0,p.ts('2023-08-11T00:00:00Z'));r.update(season='2023-24',
             home_team_id=source.identity('Burnley'),away_team_id=source.identity('Manchester City'))
        u=dict(id='1',season=2023,home_id=r['home_team_id'],away_id=r['away_team_id'],
               date='2023-08-11',home_goals=r['home_goals_90'],away_goals=r['away_goals_90'],
               home_xg=.5,away_xg=2.)
        joined,issues=source.join([r],{'1':u},{'1':{'home-page','away-page'}})
        self.assertEqual(len(joined),1);self.assertFalse(issues)
        self.assertEqual(joined[0]['home_xg'],.5)
        self.assertEqual(len(source.join([r],{'1':u},{'1':{'home-page'}})[0]),0)
        u['home_goals']+=1
        self.assertEqual(len(source.join([r],{'1':u},{'1':{'home-page','away-page'}})[0]),0)


    def test_endpoint_adapter_completed_and_future_games(self):
        import collect_understat as collector
        item=dict(id='123',isResult=True,datetime='2025-08-16 15:00:00',
                  h=dict(title='Liverpool'),a=dict(title='Arsenal'),
                  goals=dict(h='2',a='1'),xG=dict(h='1.234',a='0.876'))
        got=collector.export_match(item,2025)
        self.assertEqual(got['match_date'],'Aug 16, 2025')
        self.assertEqual((got['home_goals'],got['away_goals']),(2,1))
        self.assertEqual((got['home_xg'],got['away_xg']),(1.23,.88))
        item['isResult']=False
        self.assertIsNone(collector.export_match(item,2025))


if __name__=='__main__':unittest.main()
