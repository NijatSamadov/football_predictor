"""Tests for provider semantics and prevention of unsafe score/timing assumptions."""
import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import import_free_data as d


class ProviderChecks(unittest.TestCase):
    def fixture(self):
        return {'round': 'Matchday 1', 'date': '2023-08-11', 'time': '20:00',
                'team1': 'Burnley FC', 'team2': 'Manchester City FC',
                'score': {'ht': [0, 2], 'ft': [0, 3]}}

    def convert(self, items):
        return d.convert({'matches': items}, 'en.1', '2023-24', 'https://example.test/data')

    def test_full_time_used_and_proxy_honest(self):
        rows, skipped = self.convert([self.fixture()])
        self.assertFalse(skipped)
        self.assertEqual((rows[0]['home_goals_90'], rows[0]['away_goals_90']), (0, 3))
        self.assertEqual(rows[0]['kickoff_utc'], '2023-08-11T00:00:00+00:00')
        self.assertEqual(rows[0]['kickoff_basis'], 'date_proxy_utc_midnight')
        self.assertEqual(rows[0]['result_available_at_utc'], '2023-08-13T00:00:00+00:00')
        self.assertEqual(rows[0]['source_local_time'], '20:00')

    def test_scoreless_postponed_and_awarded_not_training_labels(self):
        empty = self.fixture(); empty['score'] = {}
        postponed = self.fixture(); postponed['status'] = 'postponed'
        awarded = self.fixture(); awarded['status'] = 'awarded'
        rows, skipped = self.convert([empty, postponed, awarded])
        self.assertEqual(rows, [])
        self.assertEqual(sum(skipped.values()), 3)

    def test_extra_time_and_playoffs_excluded(self):
        extra = self.fixture(); extra['score']['et'] = [1, 3]
        playoff = self.fixture(); playoff['round'] = 'Playoff Final'
        rows, skipped = self.convert([extra, playoff])
        self.assertEqual(rows, [])
        self.assertEqual(sum(skipped.values()), 2)

    def test_zero_zero_is_not_missing(self):
        fixture = self.fixture(); fixture['score'] = {'ft': [0, 0]}
        rows, _ = self.convert([fixture])
        self.assertEqual(rows[0]['home_goals_90'], 0)
        self.assertEqual(rows[0]['away_goals_90'], 0)

    def test_alias_and_rescheduling_keep_identity(self):
        first = self.fixture()
        second = copy.deepcopy(first); second['date'] = '2023-09-01'
        second['team2'] = 'Manchester City'
        a, _ = self.convert([first]); b, _ = self.convert([second])
        self.assertEqual(a[0]['away_team_id'], b[0]['away_team_id'])
        self.assertEqual(a[0]['match_id'], b[0]['match_id'])
        with self.assertRaisesRegex(ValueError, 'Duplicate fixture'):
            self.convert([first, second])
        self.assertNotEqual(d.team_id('en', 'Manchester City'), d.team_id('de', 'Manchester City'))

    def test_invalid_score_and_unconfigured_competition_fail(self):
        bad = self.fixture(); bad['score']['ft'] = [True, 0]
        with self.assertRaises(ValueError): self.convert([bad])
        with self.assertRaises(ValueError):
            d.convert({'matches': [self.fixture()]}, 'cup', '2023-24', 'source')

    def test_unversioned_cache_does_not_impersonate_pinned_data(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parent) as folder:
            root = Path(folder).resolve()
            assert root.is_relative_to(Path(__file__).resolve().parent)
            (root/'raw'/'2023-24').mkdir(parents=True)
            (root/'raw'/'2023-24'/'en.1.json').write_text('{}')
            with self.assertRaises(FileNotFoundError):
                d.collect(root, ['en.1'], ['2023-24'], cache_only=True)


if __name__ == '__main__':
    unittest.main()
