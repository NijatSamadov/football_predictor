"""Coherence, new-model training leakage and reserved-test safeguards."""
import copy
import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import improve_models as m
import predictor as p
from test_predictor import row


class StrengthChecks(unittest.TestCase):
    def test_dc_valid_marginals_and_expected_game_reward(self):
        for h,a,rho in [(1.8,1.,-.12),(.2,.3,.15),(10.,8.,-.2),(20.,20.,.2)]:
            g,tail,used=m.distribution(h,a,rho)
            reference=p.grid(h,a)[0]
            self.assertTrue(np.all(g>=0))
            self.assertAlmostEqual(float(g.sum()),1.)
            np.testing.assert_allclose(g.sum(axis=0),reference.sum(axis=0),atol=1e-10)
            np.testing.assert_allclose(g.sum(axis=1),reference.sum(axis=1),atol=1e-10)
            chosen=m.choose(g)
            expected=sum(prob*p.points(chosen['score'],actual) for actual,prob in np.ndenumerate(g))
            self.assertAlmostEqual(chosen['expected_points'],expected,places=7)
        neutral=m.distribution(1.4,1.1,0.)[0]
        np.testing.assert_allclose(neutral,p.grid(1.4,1.1)[0])

    def test_probability_blend(self):
        a=m.distribution(.4,.2)[0];b=m.distribution(5.,4.,-.1)[0]
        combined=m.mixture(a,b)
        self.assertAlmostEqual(combined.sum(),1.)
        self.assertAlmostEqual(combined[0,0],.5*(a[0,0]+b[0,0]))
        self.assertTrue(np.all(combined>=0))

    def test_strength_learns_and_ignores_future_labels(self):
        start=p.ts('2020-01-01T15:00:00Z')
        rng=np.random.default_rng(13)
        history=[]
        for i in range(250):
            r=row(i,start+timedelta(days=i),int(rng.poisson(3. if i%2==0 else .5)),
                  int(rng.poisson(.5 if i%2==0 else 3.)))
            r['home_team_id']='strong' if i%2==0 else 'weak'
            r['away_team_id']='weak' if i%2==0 else 'strong'
            history.append(r)
        asof=start+timedelta(days=260)
        first=m.Strength().fit(history,asof)
        future=copy.deepcopy(history[0]);future['match_id']='future'
        future['kickoff_utc']=(asof+timedelta(days=1)).isoformat()
        future['result_available_at_utc']=(asof+timedelta(days=2)).isoformat()
        future['home_goals_90']=99
        second=m.Strength().fit(history+[future],asof)
        rates=first.rates([history[0]])[0]
        self.assertGreater(rates[0],rates[1]*2)
        np.testing.assert_allclose(first.beta,second.beta)
        self.assertAlmostEqual(first.rho,second.rho)
        unknown=copy.deepcopy(history[0]);unknown['away_team_id']='new_promoted_club'
        self.assertTrue(np.all(np.isfinite(first.rates([unknown]))))
        unknown['segment']='women_senior_club'
        with self.assertRaises(ValueError):first.rates([unknown])

    def test_development_cannot_accept_reserved_rows(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            root=Path(folder).resolve();assert root.is_relative_to(Path(__file__).resolve().parent)
            data=root/'rows.jsonl'
            data.write_text(json.dumps(row(1,p.ts('2024-08-01T15:00:00Z')))+'\n')
            with self.assertRaisesRegex(ValueError,'reserved-season'):
                m.develop(data,root/'report.json')

    def test_locked_code_change_rejected_before_test(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            root=Path(folder).resolve();assert root.is_relative_to(Path(__file__).resolve().parent)
            lock=root/'lock.json'
            lock.write_text(json.dumps({'code_sha256':{'changed':'file'}}))
            with self.assertRaisesRegex(ValueError,'changed after freezing'):
                m.test_recent(root/'not-read.jsonl',lock,root/'out.json')

    def test_quality_filter_removes_only_declared_league_season(self):
        import quality_filter as quality
        bad=row(1,p.ts('2020-01-01T15:00:00Z'))
        bad['competition_id']='openfootball:en.1';bad['season']='2019-20'
        good=copy.deepcopy(bad);good['match_id']='good';good['season']='2020-21'
        other=copy.deepcopy(bad);other['match_id']='other';other['competition_id']='openfootball:de.1'
        result=quality.filter_rows([bad,good,other])
        self.assertEqual([r['match_id'] for r in result],['good','other'])
        self.assertEqual(bad['season'],'2019-20')

    def test_selection_uses_points_and_excludes_control(self):
        data=[dict(model='fixed_1_0',group='ALL',mean_points=9999,exact_log_loss=None),
              dict(model='legacy_poisson',group='ALL',mean_points=2800,exact_log_loss=2.9),
              dict(model='strength_365_10_dc',group='ALL',mean_points=2900,exact_log_loss=3.)]
        self.assertEqual(m.choose_candidate(data),'strength_365_10_dc')


if __name__=='__main__':unittest.main()
