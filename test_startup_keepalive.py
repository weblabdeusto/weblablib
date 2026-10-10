import time
import unittest
from unittest import mock

from weblablib import startup
from test_weblablib import BaseSessionWebLabTest, TestNewUserError


class Backend:
    def __init__(self):
        self.polls = []
        self.exists = True
        self.failure = False

    def poll(self, session_id):
        if self.failure:
            raise IOError('Redis unavailable')
        self.polls.append(time.time())

    def get_user(self, session_id):
        return type('User', (), dict(active=self.exists))()


class InitializationKeepaliveTest(unittest.TestCase):
    def test_slow_callback_keeps_polling_and_stops_after_ready(self):
        backend = Backend()
        with startup.initialization_keepalive(backend, 'session', .09, time.time() + 2):
            time.sleep(.22)
            self.assertLess(time.time() - backend.polls[-1], .09)
        count = len(backend.polls)
        self.assertGreater(count, 3)
        time.sleep(.08)
        self.assertEqual(len(backend.polls), count)

    def test_callback_failure_propagates_and_stops_polling(self):
        backend = Backend()
        with self.assertRaisesRegex(ValueError, 'original failure'):
            with startup.initialization_keepalive(backend, 'session', .09, time.time() + 2):
                raise ValueError('original failure')
        count = len(backend.polls)
        time.sleep(.08)
        self.assertEqual(len(backend.polls), count)

    def test_preparation_is_bounded_even_when_assigned_slot_is_long(self):
        backend = Backend()
        with mock.patch.object(startup, 'MAX_INITIALIZATION_SECONDS', .12):
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                with startup.initialization_keepalive(backend, 'session', .09, time.time() + 2):
                    time.sleep(.22)
        self.assertLess(backend.polls[-1] - backend.polls[0], .12)

    def test_absolute_slot_expiry_is_preserved(self):
        backend = Backend()
        max_date = time.time() + .12
        with startup.initialization_keepalive(backend, 'session', .09, max_date):
            time.sleep(.22)
        self.assertLess(backend.polls[-1], max_date)

    def test_polling_failure_does_not_return_ready(self):
        backend = Backend()
        with self.assertRaisesRegex(RuntimeError, 'keepalive failed'):
            with startup.initialization_keepalive(backend, 'session', .09, time.time() + 2):
                backend.failure = True
                time.sleep(.08)

    def test_disposed_session_does_not_return_ready(self):
        backend = Backend()
        with self.assertRaisesRegex(RuntimeError, 'ended during initialization'):
            with startup.initialization_keepalive(backend, 'session', .09, time.time() + 2):
                backend.exists = False


class NativeInitializationRaceTest(BaseSessionWebLabTest):
    def test_real_redis_cleaner_does_not_expire_pending_initialization(self):
        self.weblab.timeout = .12
        observed = []

        def prepare(client_data, server_data):
            until = time.time() + .36
            while time.time() < until:
                observed.extend(self.weblab._backend.find_expired_sessions())
                time.sleep(.02)

        self.on_start = prepare
        _, session_id = self.new_user(assigned_time=5)
        self.assertEqual(observed, [])
        self.assertTrue(self.weblab._backend.get_user(session_id).active)
        time.sleep(.18)
        self.assertIn(session_id, self.weblab._backend.find_expired_sessions())

    def test_failed_initialization_still_runs_native_dispose(self):
        disposed = []
        self.on_dispose = lambda: disposed.append(True)

        def prepare(client_data, server_data):
            raise ValueError('Preparation failed')

        self.on_start = prepare
        with self.assertRaises(TestNewUserError):
            self.new_user(assigned_time=5)
        self.assertEqual(disposed, [True])
        self.assertFalse(self.weblab._backend.find_expired_sessions())
