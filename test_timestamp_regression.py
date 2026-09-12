import datetime
import unittest
from unittest import mock
from weblablib.utils import _to_timestamp
from test_redis_index import BaseRedisIndexTest

class TimestampFormattingTest(unittest.TestCase):
    def test_every_small_fraction_round_trips_without_exponent(self):
        for microsecond in list(range(101)) + [999, 1000, 999999]:
            value = datetime.datetime(2026, 9, 12, 20, 52, 39, microsecond)
            result = _to_timestamp(value)
            self.assertNotIn('e', result.lower())
            self.assertEqual(datetime.datetime.fromtimestamp(float(result)), value)

    def test_fraction_before_epoch_is_not_subtracted_twice(self):
        value = datetime.datetime.fromtimestamp(-0.5)
        self.assertEqual(float(_to_timestamp(value)), -0.5)

class PollTimestampRegressionTest(BaseRedisIndexTest):
    def check_mode(self, mode):
        now = datetime.datetime(2026, 9, 12, 20, 52, 39, 43)
        epoch = now.timestamp()
        self.seed_session('active-session', max_date=epoch + 300, last_poll=epoch - 2)
        if mode == 'indexed': self.prepare_index()
        manager = self.manager(mode, 'epoch-1' if mode == 'indexed' else None)
        with mock.patch('weblablib.utils.datetime.datetime') as clock:
            clock.now.return_value = now
            manager.poll('active-session')
            saved = float(self.client.hget(self.key_base + ':weblab:active:active-session', 'last_poll'))
            self.assertAlmostEqual(saved, epoch, places=5)
            self.assertEqual(manager.find_expired_sessions(), [])

    def test_legacy_poll_does_not_expire_at_microsecond_43(self):
        self.check_mode('legacy')

    def test_indexed_poll_does_not_expire_at_microsecond_43(self):
        self.check_mode('indexed')
