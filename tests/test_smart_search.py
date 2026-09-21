import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend as b
import refresh_current as refresh


class SmartSearchTests(unittest.TestCase):
    def setUp(self):
        b._live_hints.clear()
        b._snapshot_cache.clear()
        self.params = {'region': 'EU', 'leaderboardId': 'battlegrounds', 'seasonId': '19'}

    def test_hint_neighborhood_then_tail_covers_all_pages(self):
        snapshot = {'rows': [{'accountid': 'Player', 'rank': 151, 'rating': 9000}]}
        with patch.object(b, 'load_current_snapshot', return_value=snapshot):
            pages = list(b.preferred_live_pages(['Player'], 'EU', 'battlegrounds', 19, 20))
        self.assertEqual(pages[:6], [7, 6, 8, 5, 9, 20])
        self.assertEqual(sorted(pages), list(range(2, 21)))

    def test_absent_snapshot_player_starts_at_tail(self):
        with patch.object(b, 'load_current_snapshot', return_value={'rows': []}):
            self.assertEqual(list(b.preferred_live_pages(['New'], 'EU', 'battlegrounds', 19, 5)), [5, 4, 3, 2])

    def test_missing_snapshot_uses_latest_historical_rank(self):
        with patch.object(b, 'load_current_snapshot', return_value=None), patch.object(b, 'available_archived_seasons', return_value=[18]), patch.object(b, 'load_archive_rows', return_value=[{'accountid':'Player','rank':76,'rating':9000}]):
            self.assertEqual(next(b.preferred_live_pages(['Player'], 'EU', 'battlegrounds', 19, 10)), 4)

    def test_snapshot_rejects_other_season_and_loads_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'SNAPSHOT_DIR', Path(directory)):
            p = Path(directory) / 'EU-battlegrounds.json'
            data = {'season': 18, 'region':'EU', 'mode':'battlegrounds','rows':[]}
            p.write_text(json.dumps(data))
            self.assertIsNone(b.load_current_snapshot('EU', 'battlegrounds', 19))
            data['season'] = 19
            q = p.with_suffix('.tmp');q.write_text(json.dumps(data));q.replace(p)
            self.assertIsNotNone(b.load_current_snapshot('EU', 'battlegrounds', 19))

    def first(self, *args, **kwargs):
        return {'seasonId':19,'leaderboard':{'pagination':{'totalPages':50},'rows':[]}}

    def test_player_moved_far_from_hint_is_still_found(self):
        requested=[]
        def fetch(page, params):
            requested.append(page)
            return page, [{'accountid':'Player','rank':301,'rating':10000}] if page==13 else []
        with patch.object(b,'blizzard_get',side_effect=self.first), patch.object(b,'fetch_page',side_effect=fetch), patch.object(b,'load_current_snapshot',return_value={'rows':[{'accountid':'Player','rank':51,'rating':9000}]}),patch.object(b,'MAX_WORKERS',1):
            found=b.find_live_players(['Player'],self.params)[0]
        self.assertTrue(found['found']);self.assertEqual(found['page'],13)
        self.assertEqual(requested[0],3);self.assertEqual(len(requested),len(set(requested)))

    def test_absent_player_and_unavailable_page_not_conflated(self):
        with patch.object(b,'blizzard_get',side_effect=self.first),patch.object(b,'load_current_snapshot',return_value={'rows':[]}),patch.object(b,'fetch_page',side_effect=lambda page,params:(page,None if page==44 else [])):
            result=b.find_live_players(['Absent'],self.params)[0]
            self.assertFalse(result['found']);self.assertTrue(result['incomplete'])
            with self.assertRaises(RuntimeError):b.find_player_in_season('Absent',self.params)

    def test_searches_and_history_never_contact_blizzard(self):
        from starlette.requests import Request
        snapshot = {'season':19, 'capturedAt':'2026-09-20T00:00:00Z',
                    'rows':[{'accountid':'Player','rank':100,'rating':9000}]}
        b._career_jobs['test'] = {'total_seasons':2}
        request = Request({'type':'http','headers':[], 'client':('127.0.0.1',123)})
        with patch.object(b,'load_current_snapshot',return_value=snapshot), patch.object(b,'blizzard_get',side_effect=AssertionError('Unexpected network request')), patch.object(b,'load_archive_rows',return_value=[]):
            self.assertEqual(b.seasons('battlegrounds','EU')['currentSeason'],19)
            result=b.search_players(request,'Player,Absent','battlegrounds','EU','current')
            self.assertTrue(result[0]['found'])
            self.assertFalse(result[1]['found'])
            self.assertIn('snapshot',result[1]['error'])
            self.assertEqual(result[0]['capturedAt'],snapshot['capturedAt'])
            b.run_career_search('test','Player','battlegrounds','EU',19,[19,18],('key',))
            self.assertEqual(b._career_jobs['test']['result']['matches'][0]['season'],19)

    def test_missing_snapshot_preserves_history_and_is_not_cached(self):
        b._career_jobs['test']={'total_seasons':2}
        with patch.object(b,'load_archive_rows',return_value=[{'accountid':'Player','rank':100,'rating':9000}]),patch.object(b,'load_current_snapshot',return_value=None),patch.object(b,'store_career_result') as cache:
            b.run_career_search('test','Player','battlegrounds','EU',19,[19,18],('key',))
            cache.assert_not_called()
        result=b._career_jobs['test']['result']
        self.assertEqual(result['unavailableSeasons'],[19]);self.assertEqual(len(result['matches']),1)

    def test_refresh_never_overwrites_snapshot_on_failure(self):
        first={'seasonId':19,'leaderboard':{'pagination':{'totalPages':2},'rows':[{'accountid':'A','rank':1,'rating':9000}]}}
        with tempfile.TemporaryDirectory() as directory,patch.object(refresh,'SNAPSHOT_DIR',Path(directory)),patch.object(refresh.time,'sleep'),patch.object(refresh.upstream,'get_json',side_effect=[first,RuntimeError('upstream failed')]):
            target=Path(directory)/'EU-battlegrounds.json';target.write_text('previous')
            with self.assertRaises(RuntimeError):refresh.refresh_board('EU','battlegrounds')
            self.assertEqual(target.read_text(),'previous')

    def test_refresh_publishes_full_snapshot_without_mmr_cutoff(self):
        first={'seasonId':19,'leaderboard':{'pagination':{'totalPages':1},'rows':[{'accountid':'A','rank':1,'rating':7000}]}}
        with tempfile.TemporaryDirectory() as directory,patch.object(refresh,'SNAPSHOT_DIR',Path(directory)),patch.object(refresh.time,'sleep'),patch.object(refresh.upstream,'get_json',return_value=first):
            refresh.refresh_board('EU','battlegrounds')
            data=json.loads((Path(directory)/'EU-battlegrounds.json').read_text())
            self.assertEqual(data['rows'][0]['rating'],7000);self.assertIn('capturedAt',data)

    def test_exact_name_matching_avoids_prefix_false_positives(self):
        self.assertFalse(b.player_matches_tag('Daniel#1234', 'Dan'))
        self.assertTrue(b.player_matches_tag('Dan#1234', 'Dan'))
        self.assertTrue(b.player_matches_tag('Dan', 'Dan'))
        self.assertTrue(b.player_matches_tag('dan#1234', 'DAN'))
        self.assertFalse(b.player_matches_tag('Dan#1234', 'Dan#5678'))

    def test_multiple_players_sharing_name_are_all_returned(self):
        rows = [
            {'accountid': 'Dan#1111', 'rank': 10, 'rating': 12000},
            {'accountid': 'Daniel#3333', 'rank': 5, 'rating': 13000},
            {'accountid': 'Dan#2222', 'rank': 20, 'rating': 11000},
        ]
        results = b.archived_player_results(['Dan'], rows)
        self.assertEqual(len(results), 2)
        self.assertEqual([r['btag'] for r in results], ['Dan#1111', 'Dan#2222'])

    def test_archive_cache_bounds_memory(self):
        b._archive_cache.clear()
        with tempfile.TemporaryDirectory() as directory, patch.object(b, 'ARCHIVE_DIR', Path(directory)), patch.object(b, 'MAX_CACHED_ARCHIVE_SEASONS', 2):
            for season in [1, 2, 3]:
                season_dir = Path(directory) / 'EU' / 'battlegrounds'
                season_dir.mkdir(parents=True, exist_ok=True)
                p = season_dir / f'season-{season}.json'
                p.write_text(json.dumps({'rows': [{'accountid': f'P{season}', 'rank': 1, 'rating': 9000}]}))
                b.load_archive_rows('EU', 'battlegrounds', season)
            self.assertLessEqual(len(b._archive_cache), 2)

    def test_find_live_players_returns_multiple_matches_for_shared_name(self):
        first = {
            'seasonId': 19,
            'leaderboard': {
                'pagination': {'totalPages': 1},
                'rows': [
                    {'accountid': 'Rain#1111', 'rank': 10, 'rating': 12000},
                    {'accountid': 'Rain#2222', 'rank': 20, 'rating': 11000},
                ],
            },
        }
        with patch.object(b, 'blizzard_get', return_value=first):
            results = b.find_live_players(['Rain'], self.params)
            self.assertEqual(len(results), 2)
    def test_find_live_players_flags_incomplete_when_capped_even_if_found(self):
        first = {
            'seasonId': 19,
            'leaderboard': {
                'pagination': {'totalPages': 5},
                'rows': [{'accountid': 'Rain#1111', 'rank': 10, 'rating': 12000}],
            },
        }
        with patch.object(b, 'blizzard_get', return_value=first), patch.object(b, 'MAX_PAGES_TO_SCAN', 1):
            results = b.find_live_players(['Rain'], self.params)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]['found'])
            self.assertTrue(results[0]['incomplete'])


if __name__ == '__main__':unittest.main()
