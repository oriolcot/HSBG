import time
import unittest
from unittest.mock import patch
import backend


class SecurityLimitsTests(unittest.TestCase):
    def setUp(self):
        backend._request_times.clear()
        backend._career_jobs.clear()

    def test_rate_limit_cannot_grow_without_bound(self):
        with patch.object(backend, 'MAX_RATE_LIMIT_CLIENTS', 2):
            self.assertFalse(backend.client_is_rate_limited('client-a'))
            self.assertFalse(backend.client_is_rate_limited('client-b'))
            self.assertTrue(backend.client_is_rate_limited('client-c'))
            self.assertEqual(len(backend._request_times), 2)
            backend._request_times['client-a'] = [time.monotonic() - 120]
            self.assertFalse(backend.client_is_rate_limited('client-c'))
            self.assertEqual(len(backend._request_times), 2)

    def test_job_retention_preserves_running_jobs(self):
        now = time.monotonic()
        backend._career_jobs.update({
            'active': {'status': 'running'},
            'old': {'status': 'completed', 'finished_at': now - 10},
            'new': {'status': 'completed', 'finished_at': now - 1},
        })
        with patch.object(backend, 'MAX_RETAINED_CAREER_JOBS', 3):
            backend.clean_up_career_jobs()
        self.assertIn('active', backend._career_jobs)
        self.assertIn('new', backend._career_jobs)
        self.assertNotIn('old', backend._career_jobs)

    def test_api_documentation_is_not_public(self):
        routes = {route.path for route in backend.app.routes}
        self.assertFalse(routes & {'/docs', '/redoc', '/openapi.json'})
