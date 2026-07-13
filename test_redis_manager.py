from __future__ import unicode_literals, print_function, division

import json
import os
import threading
import unittest
import uuid

from flask import Flask

from weblablib.backends.redis_manager import RedisManager
import weblablib.backends.redis_manager as redis_manager_module


class FakeWebLab(object):
    timeout = 10


class FakeExpiredUser(object):
    back = 'https://example.invalid/back'
    max_date = 1000
    username = 'user'
    username_unique = 'user@example.invalid'
    data = {'answer': 42}
    locale = 'en'
    full_name = 'Test User'
    experiment_name = 'experiment'
    category_name = 'category'
    experiment_id = 'experiment@category'
    request_client_data = {'client': True}
    request_server_data = {'server': True}
    start_date = 900


class RedisManagerCharacterizationTest(unittest.TestCase):
    def setUp(self):
        redis_url = os.environ.get('WEBLABLIB_TEST_REDIS_URL')
        if not redis_url:
            self.skipTest('WEBLABLIB_TEST_REDIS_URL must point to an isolated Redis')

        self.key_base = 'weblablib-test-{}'.format(uuid.uuid4().hex)
        self.manager = RedisManager(redis_url, self.key_base, 60, FakeWebLab())
        self.app = Flask(__name__)
        self.app.config['WEBLAB_EXPIRED_USERS_TIMEOUT'] = 60

    def tearDown(self):
        if not hasattr(self, 'manager'):
            return
        keys = self.manager.client.keys('{}:*'.format(self.key_base))
        if keys:
            self.manager.client.delete(*keys)

    def active_key(self, session_id):
        return '{}:weblab:active:{}'.format(self.key_base, session_id)

    def task_key(self, task_id):
        return '{}:weblab:tasks:{}'.format(self.key_base, task_id)

    def active_task_key(self, task_id):
        return '{}:weblab:task_ids:active:{}'.format(self.key_base, task_id)

    def seed_active_session(self, session_id, max_date=None, last_poll=None, exited='false'):
        key = self.active_key(session_id)
        if max_date is not None:
            self.manager.client.hset(key, 'max_date', max_date)
        if last_poll is not None:
            self.manager.client.hset(key, 'last_poll', last_poll)
        self.manager.client.hset(key, 'exited', exited)

    def seed_task(self, task_id, running=None):
        key = self.task_key(task_id)
        values = {
            'name': 'task',
            'session_id': 'session',
            'args': json.dumps([1]),
            'kwargs': json.dumps({'two': 2}),
        }
        for field, value in values.items():
            self.manager.client.hset(key, field, value)
        if running is not None:
            self.manager.client.hset(key, 'running', running)

    def test_find_expired_sessions_preserves_boundary_rules(self):
        self.seed_active_session('time-limit', max_date=1000, last_poll=999)
        self.seed_active_session('poll-limit', max_date=1100, last_poll=990)
        self.seed_active_session('exited', max_date=1100, last_poll=999, exited='TRUE')
        self.seed_active_session('healthy', max_date=1100, last_poll=991)
        self.seed_active_session('missing-max-date', last_poll=999)
        self.seed_active_session('missing-last-poll', max_date=1100)
        self.seed_active_session('nonstandard-exit-value', max_date=1100,
                                 last_poll=999, exited='yes')
        self.manager.client.hset('{}:other:weblab:active:foreign'.format(self.key_base),
                                 'max_date', 1)

        old_current_timestamp = redis_manager_module._current_timestamp
        redis_manager_module._current_timestamp = lambda: 1000
        try:
            expired = self.manager.find_expired_sessions()
        finally:
            redis_manager_module._current_timestamp = old_current_timestamp

        self.assertEqual(set(expired), set(['time-limit', 'poll-limit', 'exited']))

    def test_pending_task_discovery_uses_marker_and_running_field_only(self):
        self.seed_task('pending')
        self.seed_task('running', running='1')
        self.seed_task('no-marker')
        for task_id in ('pending', 'running', 'missing-hash'):
            self.manager.client.set(self.active_task_key(task_id), task_id)

        self.assertEqual(set(self.manager.get_tasks_not_started()),
                         set(['pending', 'missing-hash']))

    def test_start_task_preserves_single_claim_and_missing_hash_cleanup(self):
        self.seed_task('task-id')

        self.assertEqual(self.manager.start_task('task-id'), {
            'name': 'task',
            'session_id': 'session',
            'args': [1],
            'kwargs': {'two': 2},
        })
        self.assertIsNone(self.manager.start_task('task-id'))

        self.assertIsNone(self.manager.start_task('missing'))
        self.assertFalse(self.manager.client.exists(self.task_key('missing')))

    def test_concurrent_task_claim_has_one_winner(self):
        self.seed_task('task-id')
        start = threading.Event()
        results = []

        def claim():
            start.wait()
            results.append(self.manager.start_task('task-id'))

        threads = [threading.Thread(target=claim) for _ in range(16)]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join()

        self.assertEqual(len([result for result in results if result is not None]), 1)

    def test_delete_user_preserves_winner_and_inactive_record(self):
        self.manager.client.hset(self.active_key('session'), 'max_date', 1000)

        with self.app.app_context():
            self.assertTrue(self.manager.delete_user('session', FakeExpiredUser()))
            self.assertFalse(self.manager.delete_user('session', FakeExpiredUser()))

        inactive_key = '{}:weblab:inactive:session'.format(self.key_base)
        self.assertFalse(self.manager.client.exists(self.active_key('session')))
        self.assertEqual(self.manager.client.hget(inactive_key, 'disposing_resources'), 'true')
        self.assertEqual(json.loads(self.manager.client.hget(inactive_key, 'data')),
                         FakeExpiredUser.data)
        self.assertGreater(self.manager.client.ttl(inactive_key), 0)

    def test_finished_dispose_preserves_existing_field_semantics(self):
        inactive_key = '{}:weblab:inactive:session'.format(self.key_base)
        self.manager.client.hset(inactive_key, 'disposing_resources', 'true')
        self.manager.finished_dispose('session')
        self.assertTrue(self.manager.client.exists(inactive_key))
        self.assertEqual(self.manager.client.hget(inactive_key, 'disposing_resources'),
                         'false')

        other_key = '{}:weblab:inactive:other'.format(self.key_base)
        self.manager.client.hset(other_key, 'max_date', '1')
        self.manager.finished_dispose('other')
        self.assertFalse(self.manager.client.exists(other_key))

    def test_force_exit_updates_existing_user_and_cleans_missing_user(self):
        self.manager.client.hset(self.active_key('existing'), 'max_date', 1000)
        self.manager.force_exit('existing')
        self.assertEqual(self.manager.client.hget(self.active_key('existing'), 'exited'),
                         'true')

        self.manager.force_exit('missing')
        self.assertFalse(self.manager.client.exists(self.active_key('missing')))

    def test_storage_validation_expiry_and_cleanup(self):
        with self.assertRaises(ValueError):
            self.manager.store_action('session', 'action', 'not-a-dictionary')

        self.manager.store_action('session', 'action', {'value': 1})
        storage_key = '{}:weblab:storage:session'.format(self.key_base)
        stored = json.loads(self.manager.client.hget(storage_key, 'action'))
        self.assertEqual(stored['value'], 1)
        self.assertIn('ts', stored)
        self.assertGreater(self.manager.client.ttl(storage_key), 0)

        self.manager.clean_actions('session')
        self.assertFalse(self.manager.client.exists(storage_key))

    def test_new_task_preserves_marker_ttl_and_persistent_task_hash(self):
        task_id = self.manager.new_task('session', 'task', [1], {'two': 2})

        self.assertEqual(self.manager.client.ttl(self.task_key(task_id)), -1)
        self.assertGreater(self.manager.client.ttl(self.active_task_key(task_id)), 0)
        self.assertGreater(self.manager.client.ttl(
            '{}:weblab:task_ids:{}'.format(self.key_base, task_id)), 0)
        self.assertGreater(self.manager.client.ttl(
            '{}:weblab:session:tasks'.format(self.key_base)), 0)

    def test_new_task_retries_a_colliding_identifier(self):
        first = 'first-id'
        second = 'second-id'
        self.manager.client.set(
            '{}:weblab:task_ids:{}'.format(self.key_base, first), first)
        identifiers = iter([first, second])
        old_create_token = redis_manager_module.create_token
        redis_manager_module.create_token = lambda: next(identifiers)
        try:
            task_id = self.manager.new_task('session', 'task', [], {})
        finally:
            redis_manager_module.create_token = old_create_token

        self.assertEqual(task_id, second)

    def test_missing_task_update_paths_do_not_leave_partial_hashes(self):
        with self.assertRaises(ValueError):
            self.manager.finish_task('task', result='result', error='error')

        self.manager.finish_task('missing-finish', result='result')
        self.manager.update_task_data('missing-update', {'value': 1})
        self.manager.request_stop_task('missing-stop')

        for task_id in ('missing-finish', 'missing-update', 'missing-stop'):
            self.assertFalse(self.manager.client.exists(self.task_key(task_id)))

    def test_clean_session_tasks_removes_all_task_lookup_keys(self):
        task_ids = [self.manager.new_task('session', 'task', [], {}) for _ in range(2)]

        self.manager.clean_session_tasks('session')

        self.assertEqual(self.manager.get_all_tasks('session'), set())
        for task_id in task_ids:
            self.assertFalse(self.manager.client.exists(self.task_key(task_id)))
            self.assertFalse(self.manager.client.exists(
                '{}:weblab:task_ids:{}'.format(self.key_base, task_id)))
            self.assertFalse(self.manager.client.exists(self.active_task_key(task_id)))


if __name__ == '__main__':
    unittest.main()
