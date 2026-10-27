"""Numerical and leakage tests. Synthetic data tests plumbing, never forecast quality."""
import copy
import unittest
from datetime import timedelta

import numpy as np

import predictor as p


def row(i, kickoff, h=1, a=0, segment="men_senior_club"):
    return dict(match_id=str(i), competition_id="DEMO_LEAGUE", season="DEMO",
        segment=segment, home_team_id=f"demo:{i%8}", away_team_id=f"demo:{(i+3)%8}",
        kickoff_utc=kickoff.isoformat(), source="SYNTHETIC_TEST_ONLY", neutral_venue=False,
        home_goals_90=h, away_goals_90=a, score_scope="REGULATION", status="FINISHED",
        result_available_at_utc=(kickoff+timedelta(hours=3)).isoformat(),
        availability_basis="reconstructed")


class NumericalChecks(unittest.TestCase):
    def test_points(self):
        self.assertEqual(p.points([2, 1], [2, 1]), 10000)
        self.assertEqual(p.points([2, 1], [3, 0]), 4000)
        self.assertEqual(p.points([1, 1], [0, 0]), 4000)
        self.assertEqual(p.points([2, 1], [1, 2]), 0)
        self.assertEqual(p.points([1, 1], [1, 0]), 0)

    def test_distribution_and_expected_points(self):
        for rates in [(0.1, 0.1), (1.8, 1.1), (5, 3), (20, 20)]:
            grid, outcome, tail = p.grid(*rates)
            self.assertAlmostEqual(float(grid.sum()), 1.)
            self.assertAlmostEqual(float(outcome.sum()), 1.)
            self.assertLess(tail, 3e-12)
            answer = p.select(*rates)
            # Exhaustive reward calculation, independently grouping actual scores.
            chosen = answer["score"]
            expected = sum(float(prob)*p.points(chosen, (h, a))
                           for (h, a), prob in np.ndenumerate(grid))
            self.assertAlmostEqual(answer["expected_points"], expected, places=7)
        symmetric = p.select(1.3, 1.3)["outcome_probabilities"]
        self.assertAlmostEqual(symmetric[0], symmetric[2])

    def test_selection_is_global_maximum(self):
        grid, _, _ = p.grid(1.8, 1.0)
        answer = p.select(1.8, 1.0)
        # Direct utility for every submitted score on a smaller distribution.
        scores = list(np.ndindex(grid.shape))
        rewards = [sum(float(grid[actual])*p.points(submitted, actual) for actual in scores)
                   for submitted in scores]
        self.assertAlmostEqual(answer["expected_points"], max(rewards), places=7)

    def test_reject_nonregulation_and_missing_timestamp(self):
        r = row(0, p.ts("2020-01-01T15:00:00Z"))
        r["score_scope"] = "INCLUDING_EXTRA_TIME"
        with self.assertRaises(ValueError):
            p.validate(r)
        r = row(0, p.ts("2020-01-01T15:00:00Z"))
        r["kickoff_utc"] = "2020-01-01T15:00:00"
        with self.assertRaises(ValueError):
            p.validate(r)


class LeakageChecks(unittest.TestCase):
    def setUp(self):
        self.start = p.ts("2020-01-01T15:00:00Z")
        self.past = row(0, self.start, 2, 0)
        self.future = row(1, self.start+timedelta(days=7), 5, 1)
        self.cutoff = self.start+timedelta(days=3)

    def test_future_results_and_target_label_do_not_enter_features(self):
        first = p.features([self.future], [self.past], [self.cutoff])[0]
        changed = copy.deepcopy(self.future)
        changed["home_goals_90"], changed["away_goals_90"] = 90, 90
        second = p.features([changed], [self.past, changed], [self.cutoff])[0]
        np.testing.assert_array_equal(first, second)

    def test_result_exactly_at_cutoff_excluded(self):
        cutoff = p.ts(self.past["result_available_at_utc"])
        self.assertIsNone(p.features([self.future], [self.past], [cutoff])[0])

    def test_segments_do_not_share_history(self):
        fixture = copy.deepcopy(self.future)
        fixture["segment"] = "women_senior_club"
        self.assertIsNone(p.features([fixture], [self.past], [self.cutoff])[0])

    def test_future_or_stale_market_snapshots_are_excluded(self):
        fixture = copy.deepcopy(self.future)
        base = dict(bookmaker="DEMO", home=2., draw=3.5, away=4.,
                    over25=2., under25=2.)
        fixture["odds_snapshots"] = [
            dict(base, quoted_at_utc=(self.cutoff+timedelta(hours=1)).isoformat(),
                 available_at_utc=(self.cutoff+timedelta(hours=1)).isoformat()),
            dict(base, quoted_at_utc=(self.cutoff-timedelta(days=2)).isoformat(),
                 available_at_utc=(self.cutoff-timedelta(days=2)).isoformat())]
        self.assertIsNone(p.market(fixture, self.cutoff))

    def test_fitting_market_to_known_distribution(self):
        fixture = copy.deepcopy(self.future)
        _, outcome, _ = p.grid(1.8, 1.)
        over = p.poisson.sf(2, 2.8)
        fixture["odds_snapshots"] = [
            dict(bookmaker="DEMO", quoted_at_utc=self.cutoff.isoformat(),
                 available_at_utc=self.cutoff.isoformat(),
                 home=1/outcome[0], draw=1/outcome[1], away=1/outcome[2],
                 over25=1/over, under25=1/(1-over))]
        result = p.market(fixture, self.cutoff)
        np.testing.assert_allclose(result["rates"], [1.8, 1.], atol=1e-5)
        self.assertLess(result["market_max_probability_error"], 1e-6)


class TrainingChecks(unittest.TestCase):
    def test_training_walkforward_and_label_isolation(self):
        start = p.ts("2020-01-01T15:00:00Z")
        rng = np.random.default_rng(19)
        rows = [row(i, start+timedelta(days=i), int(rng.poisson(1.5)), int(rng.poisson(1.1)))
                for i in range(190)]
        cutoff = start+timedelta(days=160)
        models = {kind: p.fit(rows, cutoff, 24, kind) for kind in ["poisson", "boosted"]}
        for model in models.values():
            self.assertIn("men_senior_club", model)
        changed = copy.deepcopy(rows)
        changed[-1]["home_goals_90"] = 99
        x = p.features([rows[162]], rows, [cutoff])[0]
        for kind in models:
            other = p.fit(changed, cutoff, 24, kind)
            np.testing.assert_allclose(
                models[kind]["men_senior_club"].predict(x),
                other["men_senior_club"].predict(x))
        results = p.walk_forward(rows, cutoff, cutoff+timedelta(days=10), 24)
        self.assertEqual(len(results), 30)
        for r in results:
            self.assertLess(p.ts(r["asof_utc"]), p.ts(rows[int(r["match_id"])]["kickoff_utc"]))
            self.assertEqual(r["status"], "unavailable" if r["model"] == "market" else "predicted")
        summary = p.summary(results)
        pair = [r for r in summary["paired_comparisons"]
                if {r["left"], r["right"]} == {"poisson", "boosted"}][0]
        self.assertEqual(pair["common_matches"], 10)

    def test_comparison_uses_common_matches(self):
        rows = [
            dict(model="poisson", match_id="A", competition_id="L", points=4000,
                 outcome_log_loss=1., outcome_brier=.5, exact_log_loss=2.),
            dict(model="boosted", match_id="A", competition_id="L", points=0,
                 outcome_log_loss=1., outcome_brier=.5, exact_log_loss=2.),
            dict(model="boosted", match_id="B", competition_id="L", points=10000,
                 outcome_log_loss=1., outcome_brier=.5, exact_log_loss=2.)]
        pair = p.summary(rows)["paired_comparisons"][0]
        self.assertEqual(pair["common_matches"], 1)
        self.assertEqual(pair["mean_points_difference"], -4000)


if __name__ == "__main__":
    unittest.main()

