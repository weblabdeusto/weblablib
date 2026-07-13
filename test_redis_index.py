from __future__ import unicode_literals, print_function, division

import json
import os
import unittest
import uuid

import redis
from click.testing import CliRunner
from flask import Flask

import weblablib
from weblablib.backends.redis_manager import RedisManager
from weblablib.exc import AlreadyRunningError, InvalidConfigError


INDEX_SENTINEL = '__weblablib_index_v1__'


class CapturingLogger(object):
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []
        self.critical_messages = []

    def _message(self, message, args):
        if args:
            return message % args
        return message

    def info(self, message, *args, **kwargs):
        self.info_messages.append(self._message(message, args))

    def warning(self, message, *args, **kwargs):
        self.warning_messages.append(self._message(message, args))

    def critical(self, message, *args, **kwargs):
        self.critical_messages.append(self._message(message, args))


class FakeApp(object):
    def __init__(self, logger):
        self.logger = logger


class FakeWebLab(object):
    timeout = 10

    def __init__(self, logger):
        self._app = FakeApp(logger)


class FakeCurrentUser(object):
    max_date = 1100
    last_poll = 1000
    username = 'user'
    username_unique = 'user@example.invalid'
    data = {'answer': 42}
    back = 'https://example.invalid/back'
    exited = False
    locale = 'en'
    full_name = 'Test User'
    experiment_name = 'experiment'
    category_name = 'category'
    experiment_id = 'experiment@category'
    start_date = 900
    request_client_data = {'client': True}
    request_server_data = {'server': True}


class FakeExpiredUser(FakeCurrentUser):
    pass


class BaseRedisIndexTest(unittest.TestCase):
    def setUp(self):
        self.redis_url = os.environ.get('WEBLABLIB_TEST_REDIS_URL')
        if not self.redis_url:
            self.skipTest('WEBLABLIB_TEST_REDIS_URL must point to an isolated Redis')
        self.key_base = 'weblablib-index-test-{}'.format(uuid.uuid4().hex)
        self.client = redis.StrictRedis.from_url(self.redis_url, decode_responses=True)
        self.logger = CapturingLogger()
        self.app = Flask(__name__)
        self.app.config['WEBLAB_EXPIRED_USERS_TIMEOUT'] = 60

    def tearDown(self):
        if not hasattr(self, 'client'):
            return
        keys = self.client.keys('{}:*'.format(self.key_base))
        if keys:
            self.client.delete(*keys)

    @property
    def active_index_key(self):
        return '{}:weblab:index:v1:active_sessions'.format(self.key_base)

    @property
    def pending_index_key(self):
        return '{}:weblab:index:v1:pending_tasks'.format(self.key_base)

    @property
    def ready_key(self):
        return '{}:weblab:index:v1:ready'.format(self.key_base)

    @property
    def lock_key(self):
        return '{}:weblab:index:v1:migration_lock'.format(self.key_base)

    def manager(self, mode='legacy', epoch=None):
        return RedisManager(self.redis_url, self.key_base, 60,
                            FakeWebLab(self.logger), index_mode=mode,
                            index_epoch=epoch)

    def seed_session(self, session_id, max_date=900, last_poll=1000,
                     exited='false'):
        key = '{}:weblab:active:{}'.format(self.key_base, session_id)
        self.client.hset(key, 'max_date', max_date)
        self.client.hset(key, 'last_poll', last_poll)
        self.client.hset(key, 'exited', exited)

    def seed_task(self, task_id, marker=True, running=None):
        task_key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)
        self.client.hset(task_key, 'name', 'task')
        self.client.hset(task_key, 'session_id', 'session')
        self.client.hset(task_key, 'args', '[]')
        self.client.hset(task_key, 'kwargs', '{}')
        if running is not None:
            self.client.hset(task_key, 'running', running)
        if marker:
            self.client.set('{}:weblab:task_ids:active:{}'.format(
                self.key_base, task_id), task_id)

    def prepare_index(self, epoch='epoch-1'):
        shadow = self.manager('shadow', epoch)
        result = shadow.prepare_redis_index(scan_count=10)
        self.assertTrue(result['ready'])
        return shadow


class RedisIndexConfigurationTest(BaseRedisIndexTest):
    def test_legacy_is_default_and_creates_no_index_keys(self):
        manager = RedisManager(self.redis_url, self.key_base, 60,
                               FakeWebLab(self.logger))
        self.assertEqual(manager.index_mode, 'legacy')
        self.assertEqual(self.client.keys('{}:weblab:index:*'.format(self.key_base)), [])

        manager.add_user('session', FakeCurrentUser(), 60)
        task_id = manager.new_task('session', 'task', [], {})
        manager.find_expired_sessions()
        manager.get_tasks_not_started()
        manager.start_task(task_id)
        with self.app.app_context():
            manager.delete_user('session', FakeExpiredUser())

        self.assertEqual(self.client.keys('{}:weblab:index:*'.format(self.key_base)), [])

    def test_mode_and_epoch_validation(self):
        with self.assertRaises(InvalidConfigError):
            self.manager('unknown', 'epoch')
        with self.assertRaises(InvalidConfigError):
            self.manager('shadow', None)
        with self.assertRaises(InvalidConfigError):
            self.manager('indexed', '')

    def test_shadow_initializes_versioned_sets_outside_legacy_patterns(self):
        manager = self.manager('shadow', 'epoch-1')
        self.assertEqual(manager.index_mode, 'shadow')
        self.assertEqual(self.client.smembers(self.active_index_key),
                         set([INDEX_SENTINEL]))
        self.assertEqual(self.client.smembers(self.pending_index_key),
                         set([INDEX_SENTINEL]))
        self.assertNotIn(self.active_index_key,
                         self.client.keys('{}:weblab:active:*'.format(self.key_base)))
        self.assertNotIn(self.pending_index_key,
                         self.client.keys('{}:weblab:task_ids:active:*'.format(
                             self.key_base)))

    def test_wrong_index_type_refuses_shadow_startup_without_partial_setup(self):
        self.client.set(self.active_index_key, 'wrong-type')
        with self.assertRaises(InvalidConfigError):
            self.manager('shadow', 'epoch-1')
        self.assertEqual(self.client.type(self.pending_index_key), 'none')

    def test_allkeys_eviction_refuses_opt_in_modes(self):
        original_policy = self.client.config_get('maxmemory-policy')['maxmemory-policy']
        try:
            self.client.config_set('maxmemory-policy', 'allkeys-lru')
            with self.assertRaises(InvalidConfigError):
                self.manager('shadow', 'epoch-1')
            with self.assertRaises(InvalidConfigError):
                self.manager('indexed', 'epoch-1')
        finally:
            self.client.config_set('maxmemory-policy', original_policy)

    def test_indexed_requires_matching_prepared_epoch(self):
        self.manager('shadow', 'epoch-1')
        with self.assertRaises(InvalidConfigError):
            self.manager('indexed', 'epoch-1')

        self.prepare_index('epoch-1')
        self.manager('indexed', 'epoch-1')
        with self.assertRaises(InvalidConfigError):
            self.manager('indexed', 'epoch-2')


class RedisIndexWriteTest(BaseRedisIndexTest):
    def test_shadow_dual_writes_every_session_and_task_transition(self):
        manager = self.manager('shadow', 'epoch-1')
        manager.add_user('session', FakeCurrentUser(), 60)
        self.assertIn('session', self.client.smembers(self.active_index_key))

        task_id = manager.new_task('session', 'task', [], {})
        self.assertIn(task_id, self.client.smembers(self.pending_index_key))

        self.assertIsNotNone(manager.start_task(task_id))
        self.assertNotIn(task_id, self.client.smembers(self.pending_index_key))

        second_task = manager.new_task('session', 'task', [], {})
        manager.finish_task(second_task, result='done')
        self.assertNotIn(second_task, self.client.smembers(self.pending_index_key))

        third_task = manager.new_task('session', 'task', [], {})
        manager.clean_session_tasks('session')
        self.assertNotIn(third_task, self.client.smembers(self.pending_index_key))

        with self.app.app_context():
            self.assertTrue(manager.delete_user('session', FakeExpiredUser()))
        self.assertNotIn('session', self.client.smembers(self.active_index_key))

    def test_shadow_reads_remain_legacy_authoritative(self):
        manager = self.manager('shadow', 'epoch-1')
        self.seed_session('old-session')
        self.seed_task('old-task')

        self.assertEqual(manager.find_expired_sessions(), ['old-session'])
        self.assertEqual(manager.get_tasks_not_started(), ['old-task'])
        self.assertNotIn('old-session', self.client.smembers(self.active_index_key))
        self.assertNotIn('old-task', self.client.smembers(self.pending_index_key))

    def test_new_writer_remains_visible_to_legacy_reader(self):
        shadow = self.manager('shadow', 'epoch-1')
        legacy = self.manager('legacy')
        task_id = shadow.new_task('session', 'task', [], {})
        self.assertIn(task_id, legacy.get_tasks_not_started())


class RedisIndexMigrationTest(BaseRedisIndexTest):
    def test_status_is_read_only_and_reports_missing_and_stale_members(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.seed_session('missing-session')
        self.seed_task('missing-task')
        self.client.sadd(self.active_index_key, 'stale-session')
        self.client.sadd(self.pending_index_key, 'stale-task')

        status = shadow.redis_index_status(scan_count=10)

        self.assertFalse(status['ready'])
        self.assertEqual(status['active_sessions']['missing'], 1)
        self.assertEqual(status['active_sessions']['stale'], 1)
        self.assertEqual(status['pending_tasks']['missing'], 1)
        self.assertEqual(status['pending_tasks']['stale'], 1)
        self.assertIn('stale-session', self.client.smembers(self.active_index_key))
        self.assertIn('stale-task', self.client.smembers(self.pending_index_key))

    def test_prepare_reconciles_indices_and_sets_readiness(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.seed_session('session')
        self.seed_task('pending')
        self.seed_task('running', running='1')
        self.client.sadd(self.active_index_key, 'stale-session')
        self.client.sadd(self.pending_index_key, 'stale-task')

        result = shadow.prepare_redis_index(scan_count=10)

        self.assertTrue(result['ready'])
        self.assertEqual(result['ready_epoch'], 'epoch-1')
        self.assertEqual(result['active_sessions']['missing'], 0)
        self.assertEqual(result['active_sessions']['stale'], 0)
        self.assertEqual(result['pending_tasks']['missing'], 0)
        self.assertEqual(result['pending_tasks']['stale'], 0)
        self.assertEqual(self.client.smembers(self.active_index_key),
                         set([INDEX_SENTINEL, 'session']))
        self.assertEqual(self.client.smembers(self.pending_index_key),
                         set([INDEX_SENTINEL, 'pending']))

    def test_prepare_requires_shadow_and_honors_per_base_lock(self):
        with self.assertRaises(InvalidConfigError):
            self.manager('legacy').prepare_redis_index()

        shadow = self.manager('shadow', 'epoch-1')
        self.client.set(self.lock_key, 'other-owner', ex=60)
        with self.assertRaises(AlreadyRunningError):
            shadow.prepare_redis_index()

    def test_prepare_does_not_include_missing_hash_or_running_task(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.client.set('{}:weblab:task_ids:active:ghost'.format(self.key_base),
                        'ghost')
        self.seed_task('running', running='1')

        result = shadow.prepare_redis_index(scan_count=10)

        self.assertTrue(result['ready'])
        self.assertEqual(self.client.smembers(self.pending_index_key),
                         set([INDEX_SENTINEL]))


class RedisIndexedReadTest(BaseRedisIndexTest):
    def setUp(self):
        super(RedisIndexedReadTest, self).setUp()
        self.shadow = self.manager('shadow', 'epoch-1')

    def indexed_manager(self):
        self.shadow.prepare_redis_index(scan_count=10)
        return self.manager('indexed', 'epoch-1')

    def test_indexed_session_discovery_avoids_keys_and_preserves_rules(self):
        self.seed_session('expired')
        self.seed_session('healthy', max_date=1100, last_poll=1000)
        manager = self.indexed_manager()
        old_keys = manager.client.keys
        manager.client.keys = lambda *args, **kwargs: self.fail('indexed read used KEYS')
        old_timestamp = weblablib.backends.redis_manager._current_timestamp
        weblablib.backends.redis_manager._current_timestamp = lambda: 1000
        try:
            self.assertEqual(manager.find_expired_sessions(), ['expired'])
        finally:
            weblablib.backends.redis_manager._current_timestamp = old_timestamp
            manager.client.keys = old_keys

    def test_indexed_task_discovery_validates_marker_hash_and_running(self):
        self.seed_task('pending')
        self.seed_task('running', running='1')
        self.seed_task('expired-marker', marker=False)
        self.client.set('{}:weblab:task_ids:active:ghost'.format(self.key_base),
                        'ghost')
        manager = self.indexed_manager()
        self.client.sadd(self.pending_index_key, 'running', 'expired-marker', 'ghost')
        old_keys = manager.client.keys
        manager.client.keys = lambda *args, **kwargs: self.fail('indexed read used KEYS')
        try:
            self.assertEqual(manager.get_tasks_not_started(), ['pending'])
        finally:
            manager.client.keys = old_keys

        members = self.client.smembers(self.pending_index_key)
        self.assertNotIn('running', members)
        self.assertNotIn('expired-marker', members)
        self.assertNotIn('ghost', members)

    def test_marker_expiry_is_authoritative_and_prunes_pending_member(self):
        manager = self.indexed_manager()
        task_id = manager.new_task('session', 'task', [], {})
        self.client.delete('{}:weblab:task_ids:active:{}'.format(
            self.key_base, task_id))

        self.assertEqual(manager.get_tasks_not_started(), [])
        self.assertNotIn(task_id, self.client.smembers(self.pending_index_key))

    def test_missing_index_or_runtime_wrong_type_falls_back_and_rate_limits_log(self):
        self.seed_session('expired')
        manager = self.indexed_manager()
        self.client.delete(self.active_index_key)

        self.assertEqual(manager.find_expired_sessions(), ['expired'])
        self.assertEqual(manager.find_expired_sessions(), ['expired'])
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertNotIn('expired', self.logger.critical_messages[0])

        self.client.set(self.active_index_key, 'wrong-type')
        self.assertEqual(manager.find_expired_sessions(), ['expired'])


class RedisIndexFlaskIntegrationTest(BaseRedisIndexTest):
    def create_app(self, config=None):
        app = Flask(__name__)
        app.config.update({
            'SECRET_KEY': 'secret',
            'SERVER_NAME': 'localhost:5000',
            'WEBLAB_USERNAME': 'user',
            'WEBLAB_PASSWORD': 'password',
            'WEBLAB_REDIS_URL': self.redis_url,
            'WEBLAB_REDIS_BASE': self.key_base,
            'WEBLAB_NO_THREAD': True,
        })
        if config:
            app.config.update(config)
        extension = weblablib.WebLab(app)
        return app, extension

    def test_environment_fallback_and_flask_config_precedence(self):
        old_mode = os.environ.get('WEBLAB_REDIS_INDEX_MODE')
        old_epoch = os.environ.get('WEBLAB_REDIS_INDEX_EPOCH')
        os.environ['WEBLAB_REDIS_INDEX_MODE'] = 'shadow'
        os.environ['WEBLAB_REDIS_INDEX_EPOCH'] = 'environment-epoch'
        try:
            app, extension = self.create_app()
            self.assertEqual(extension._backend.index_mode, 'shadow')
            self.assertEqual(extension._backend.index_epoch, 'environment-epoch')
            extension._cleanup()

            app, extension = self.create_app({
                'WEBLAB_REDIS_INDEX_MODE': 'legacy',
                'WEBLAB_REDIS_INDEX_EPOCH': 'config-epoch',
            })
            self.assertEqual(extension._backend.index_mode, 'legacy')
            self.assertEqual(extension._backend.index_epoch, 'config-epoch')
            extension._cleanup()
        finally:
            if old_mode is None:
                os.environ.pop('WEBLAB_REDIS_INDEX_MODE', None)
            else:
                os.environ['WEBLAB_REDIS_INDEX_MODE'] = old_mode
            if old_epoch is None:
                os.environ.pop('WEBLAB_REDIS_INDEX_EPOCH', None)
            else:
                os.environ['WEBLAB_REDIS_INDEX_EPOCH'] = old_epoch

    def test_status_and_prepare_cli_json_contract(self):
        app, extension = self.create_app({
            'WEBLAB_REDIS_INDEX_MODE': 'shadow',
            'WEBLAB_REDIS_INDEX_EPOCH': 'epoch-1',
        })
        self.seed_session('session')
        runner = CliRunner()

        status_result = runner.invoke(app.cli, [
            'weblab', 'redis-index', 'status', '--json'])
        self.assertEqual(status_result.exit_code, 0, status_result.output)
        status = json.loads(status_result.output)
        self.assertFalse(status['ready'])
        self.assertEqual(status['active_sessions']['missing'], 1)

        prepare_result = runner.invoke(app.cli, [
            'weblab', 'redis-index', 'prepare', '--scan-count', '10', '--json'])
        self.assertEqual(prepare_result.exit_code, 0, prepare_result.output)
        prepared = json.loads(prepare_result.output)
        self.assertTrue(prepared['ready'])
        extension._cleanup()


if __name__ == '__main__':
    unittest.main()
