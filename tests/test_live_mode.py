import unittest
from unittest.mock import patch
from starlette.requests import Request
from fastapi import HTTPException
import backend as b

class LiveModeTests(unittest.TestCase):
    def setUp(self):
        self.mode = patch.object(b, 'DATA_MODE', 'live')
        self.mode.start()
        self.addCleanup(self.mode.stop)
        b._season_cache.clear()
        b._request_times.clear()
        self.request = Request({'type':'http', 'headers':[], 'client':('127.0.0.1',123)})

    def test_live_season_needs_no_snapshot(self):
        with patch.object(b, 'blizzard_get', return_value={'seasonId':19}) as upstream, patch.object(b, 'load_current_snapshot', side_effect=AssertionError('snapshot required')):
            self.assertEqual(b.get_current_season('EU','battlegrounds'),19)
            self.assertEqual(b.get_current_season('EU','battlegrounds'),19)
            self.assertEqual(upstream.call_count,1)

    def test_each_search_fetches_current_results(self):
        player={'found':True,'btag':'Player','rank':1,'rating':10000}
        with patch.object(b,'get_current_season',return_value=19), patch.object(b,'find_live_players',side_effect=lambda *a:[dict(player)]) as upstream:
            for _ in range(2):
                result=b.search_players(self.request,'Player','battlegrounds','EU','current')
                self.assertEqual(result[0]['dataMode'],'live')
                self.assertIn('checkedAt',result[0])
            self.assertEqual(upstream.call_count,2)

    def test_capped_scan_does_not_claim_absence(self):
        first={'seasonId':19,'leaderboard':{'pagination':{'totalPages':4},'rows':[]}}
        with patch.object(b,'blizzard_get',return_value=first), patch.object(b,'load_current_snapshot',return_value=None), patch.object(b,'available_archived_seasons',return_value=[]), patch.object(b,'MAX_PAGES_TO_SCAN',1):
            result=b.find_live_players(['Player'],{'region':'EU','leaderboardId':'battlegrounds','seasonId':'19'})[0]
            self.assertTrue(result['incomplete'])

    def test_upstream_error_stops_additional_batches(self):
        first={'seasonId':19,'leaderboard':{'pagination':{'totalPages':10},'rows':[]}}
        with patch.object(b,'blizzard_get',return_value=first), patch.object(b,'load_current_snapshot',return_value=None), patch.object(b,'available_archived_seasons',return_value=[]), patch.object(b,'MAX_WORKERS',1), patch.object(b.time,'sleep'), patch.object(b,'fetch_page',return_value=(10,None)) as fetch:
            result=b.find_live_players(['Player'],{'region':'EU','leaderboardId':'battlegrounds','seasonId':'19'})[0]
            self.assertTrue(result['incomplete'])
            self.assertEqual(fetch.call_count,1)

    def test_history_survives_current_upstream_failure(self):
        b._career_jobs['live-test']={'total_seasons':2}
        with patch.object(b,'load_archive_rows',return_value=[{'accountid':'Player','rank':1,'rating':9000}]), patch.object(b,'load_current_snapshot',return_value=None), patch.object(b,'search_live_players',side_effect=HTTPException(status_code=503)), patch.object(b,'store_career_result') as cache:
            b.run_career_search('live-test','Player','battlegrounds','EU',19,[19,18],('live-test',))
            cache.assert_not_called()
        job=b._career_jobs['live-test']
        self.assertEqual(job['status'],'completed')
        self.assertEqual(job['result']['unavailableSeasons'],[19])
        self.assertEqual(job['result']['matches'][0]['season'],18)

    def test_invalid_mode_fails_at_startup(self):
        import subprocess,os,sys
        result=subprocess.run([sys.executable,'-c','import backend'],env={**os.environ,'HSBG_DATA_MODE':'typo'},capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('HSBG_DATA_MODE must be snapshot or live',result.stderr)
