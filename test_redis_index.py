from __future__ import unicode_literals, print_function, division

import json
import os
import threading
import unittest
import uuid

import redis
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


class ClientProxy(object):
    def __init__(self, client, **overrides):
        self._client = client
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._client, name)


class PipelineResultProxy(object):
    def __init__(self, pipeline, mutate_results):
        self._pipeline = pipeline
        self._mutate_results = mutate_results

    def __getattr__(self, name):
        return getattr(self._pipeline, name)

    def execute(self):
        results = self._pipeline.execute()
        self._mutate_results(results)
        return results


class DeniedSaddPipeline(object):
    def __init__(self, pipeline):
        self._pipeline = pipeline

    def __getattr__(self, name):
        return getattr(self._pipeline, name)

    def sadd(self, key, *values):
        del values
        self._pipeline.hset(key, 'denied-sadd', '1')
        return self


class DeniedWatchPipeline(object):
    def __init__(self, pipeline):
        self._pipeline = pipeline

    def __getattr__(self, name):
        return getattr(self._pipeline, name)

    def watch(self, *keys):
        del keys
        raise redis.exceptions.ResponseError('command denied')


class WatchErrorOnceClient(ClientProxy):
    def __init__(self, client):
        super(WatchErrorOnceClient, self).__init__(client)
        self.pipeline_calls = 0

    def pipeline(self):
        self.pipeline_calls += 1
        pipeline = self._client.pipeline()
        if self.pipeline_calls != 1:
            return pipeline

        def raise_watch_error(results):
            raise redis.exceptions.WatchError()

        return PipelineResultProxy(pipeline, raise_watch_error)


class InvalidText(object):
    def __str__(self):
        raise ValueError('cannot stringify')

    def __unicode__(self):
        raise ValueError('cannot stringify')


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

        manager = self.manager()
        with self.assertRaises(InvalidConfigError):
            manager._normalize_index_mode(InvalidText())
        with self.assertRaises(InvalidConfigError):
            manager._normalize_index_epoch(InvalidText())

    def test_scan_count_validation(self):
        manager = self.manager()
        with self.assertRaises(InvalidConfigError):
            manager.redis_index_status(scan_count='invalid')
        with self.assertRaises(InvalidConfigError):
            manager.redis_index_status(scan_count=0)

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

    def test_wrong_ready_and_lock_types_refuse_shadow_startup(self):
        for key in (self.ready_key, self.lock_key):
            self.client.delete(key)
            self.client.sadd(key, 'wrong-type')
            with self.assertRaises(InvalidConfigError):
                self.manager('shadow', 'epoch-1')

    def test_preflight_rejects_unknown_policy_and_cluster(self):
        manager = self.manager()
        manager.client = ClientProxy(
            self.client, config_get=lambda *args, **kwargs: {})
        with self.assertRaises(InvalidConfigError):
            manager._preflight_redis_index()

        manager.client = ClientProxy(
            self.client,
            config_get=lambda *args, **kwargs: {
                'maxmemory-policy': 'noeviction'},
            info=lambda *args, **kwargs: {'cluster_enabled': 1})
        with self.assertRaises(InvalidConfigError):
            manager._preflight_redis_index()

    def test_preflight_wraps_redis_command_errors(self):
        manager = self.manager()

        def denied(*args, **kwargs):
            raise redis.exceptions.ResponseError('command denied')

        manager.client = ClientProxy(self.client, config_get=denied)
        with self.assertRaises(InvalidConfigError) as context:
            manager._preflight_redis_index()
        self.assertIn('configured index mode', str(context.exception))

    def test_preflight_uses_isolated_set_string_and_hash_command_probes(self):
        manager = self.manager()
        original_pipeline = self.client.pipeline

        cases = (
            (2, set(), 'Redis set command probe failed'),
            (5, [], 'Redis string command probe failed'),
            (8, [], 'Redis hash command probe failed'),
        )
        for result_index, replacement, expected_message in cases:
            def pipeline(result_index=result_index, replacement=replacement):
                def mutate(results):
                    results[result_index] = replacement
                return PipelineResultProxy(original_pipeline(), mutate)

            manager.client = ClientProxy(self.client, pipeline=pipeline)
            with self.assertRaises(InvalidConfigError) as context:
                manager._preflight_redis_index()
            self.assertEqual(str(context.exception), expected_message)
        self.assertEqual(self.client.keys(
            '{}:weblab:index:v1:command-probe:*'.format(self.key_base)), [])

    def test_preflight_requires_migration_watch_permission(self):
        manager = self.manager()
        original_pipeline = self.client.pipeline
        manager.client = ClientProxy(
            self.client,
            pipeline=lambda: DeniedWatchPipeline(original_pipeline()))

        with self.assertRaises(InvalidConfigError) as context:
            manager._preflight_redis_index()

        self.assertIn('configured index mode', str(context.exception))
        self.assertEqual(self.client.keys(
            '{}:weblab:index:v1:command-probe:*'.format(self.key_base)), [])

    def test_preflight_requires_migration_unwatch_permission(self):
        manager = self.manager()

        def denied_unwatch(*args, **kwargs):
            del args, kwargs
            raise redis.exceptions.ResponseError('command denied')

        manager.client = ClientProxy(
            self.client, execute_command=denied_unwatch)

        with self.assertRaises(InvalidConfigError) as context:
            manager._preflight_redis_index()

        self.assertIn('configured index mode', str(context.exception))

    def test_prepared_index_with_missing_sentinel_refuses_startup(self):
        self.prepare_index('epoch-1')
        self.client.sadd(self.active_index_key, 'stale-member')
        self.client.srem(self.active_index_key, INDEX_SENTINEL)

        with self.assertRaises(InvalidConfigError):
            self.manager('shadow', 'epoch-1')
        with self.assertRaises(InvalidConfigError):
            self.manager('indexed', 'epoch-1')

        self.assertNotIn(INDEX_SENTINEL,
                         self.client.smembers(self.active_index_key))

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

    def test_failed_indexed_startup_cannot_recreate_a_lost_prepared_index(self):
        self.seed_session('expired')
        self.prepare_index('epoch-1')
        running_manager = self.manager('indexed', 'epoch-1')
        self.client.delete(self.active_index_key)

        with self.assertRaises(InvalidConfigError):
            self.manager('shadow', 'epoch-1')
        with self.assertRaises(InvalidConfigError):
            self.manager('indexed', 'epoch-1')

        self.assertEqual(self.client.type(self.active_index_key), 'none')
        self.assertEqual(running_manager.find_expired_sessions(), ['expired'])


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

    def test_session_index_write_failure_invalidates_readiness(self):
        manager = self.prepare_index('epoch-1')
        original_pipeline = self.client.pipeline
        manager.client = ClientProxy(
            self.client,
            pipeline=lambda: DeniedSaddPipeline(original_pipeline()))

        with self.assertRaises(redis.exceptions.ResponseError):
            manager.add_user('partial-session', FakeCurrentUser(), 60)

        active_key = '{}:weblab:active:partial-session'.format(self.key_base)
        self.assertIsNotNone(self.client.hget(active_key, 'max_date'))
        self.assertNotIn('partial-session', self.client.smembers(
            self.active_index_key))
        self.assertIsNone(self.client.get(self.ready_key))
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('index_write_failed', self.logger.critical_messages[0])

    def test_task_index_write_failure_invalidates_readiness(self):
        manager = self.prepare_index('epoch-1')
        original_pipeline = self.client.pipeline
        manager.client = ClientProxy(
            self.client,
            pipeline=lambda: DeniedSaddPipeline(original_pipeline()))

        with self.assertRaises(redis.exceptions.ResponseError):
            manager.new_task('session', 'task', [], {})

        marker_keys = self.client.keys(
            '{}:weblab:task_ids:active:*'.format(self.key_base))
        self.assertEqual(len(marker_keys), 1)
        task_id = marker_keys[0].rsplit(':', 1)[1]
        self.assertIsNotNone(self.client.hget(
            '{}:weblab:tasks:{}'.format(self.key_base, task_id), 'name'))
        self.assertNotIn(task_id, self.client.smembers(self.pending_index_key))
        self.assertIsNone(self.client.get(self.ready_key))
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('index_write_failed', self.logger.critical_messages[0])

    def test_failed_readiness_delete_keeps_process_on_legacy_discovery(self):
        self.prepare_index('epoch-1')
        manager = self.manager('indexed', 'epoch-1')
        original_pipeline = self.client.pipeline

        def denied_delete(*args, **kwargs):
            del args, kwargs
            raise redis.exceptions.ResponseError('command denied')

        manager.client = ClientProxy(
            self.client,
            pipeline=lambda: DeniedSaddPipeline(original_pipeline()),
            delete=denied_delete)

        with self.assertRaises(redis.exceptions.ResponseError):
            manager.add_user('partial-session', FakeCurrentUser(), 60)

        self.assertEqual(self.client.get(self.ready_key), 'epoch-1')
        self.assertNotIn('partial-session', self.client.smembers(
            self.active_index_key))
        self.assertEqual(manager.find_expired_sessions(), ['partial-session'])
        self.assertIn('readiness_invalidation_error',
                      self.logger.critical_messages[0])


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

    def test_status_excludes_partial_legacy_records(self):
        shadow = self.manager('shadow', 'epoch-1')
        partial_session_key = '{}:weblab:active:partial'.format(self.key_base)
        self.client.hset(partial_session_key, 'max_date', 1000)
        self.client.set('{}:weblab:task_ids:active:partial'.format(
            self.key_base), 'partial')

        status = shadow.redis_index_status(scan_count=10)

        self.assertEqual(status['active_sessions']['expected'], 0)
        self.assertEqual(status['pending_tasks']['expected'], 0)

    def test_status_reports_missing_sets_wrong_types_and_command_errors(self):
        manager = self.manager()
        errors = []
        members, sentinel = manager._read_index_set('missing', errors)
        self.assertEqual(members, set())
        self.assertFalse(sentinel)
        self.assertEqual(errors, [])

        wrong_type_key = '{}:wrong-type'.format(self.key_base)
        self.client.set(wrong_type_key, 'value')
        members, sentinel = manager._read_index_set(wrong_type_key, errors)
        self.assertEqual(members, set())
        self.assertFalse(sentinel)
        self.assertIn('unexpected_type', errors)

        def denied_type(*args, **kwargs):
            raise redis.exceptions.ResponseError('command denied')

        manager.client = ClientProxy(self.client, type=denied_type)
        members, sentinel = manager._read_index_set('unreadable', errors)
        self.assertEqual(members, set())
        self.assertFalse(sentinel)
        self.assertIn('ResponseError', errors)

    def test_status_reports_unsafe_server_settings(self):
        manager = self.manager()
        manager.client = ClientProxy(
            self.client,
            config_get=lambda *args, **kwargs: {
                'maxmemory-policy': 'allkeys-lru'},
            info=lambda *args, **kwargs: {'cluster_enabled': 1})

        status = manager.redis_index_status(scan_count=10)

        self.assertFalse(status['ok'])
        self.assertIn('unsupported_eviction_policy', status['errors'])
        self.assertIn('redis_cluster_unsupported', status['errors'])

        manager.client = ClientProxy(
            self.client, config_get=lambda *args, **kwargs: {})
        status = manager.redis_index_status(scan_count=10)
        self.assertIn('maxmemory_policy_unknown', status['errors'])

    def test_status_reports_scan_and_readiness_command_errors(self):
        manager = self.manager()

        def failed_scan(*args, **kwargs):
            raise redis.exceptions.ConnectionError('offline')

        manager.client = ClientProxy(self.client, scan_iter=failed_scan)
        status = manager.redis_index_status(scan_count=10)
        self.assertFalse(status['ok'])
        self.assertIn('ConnectionError', status['errors'])

        def failed_ready_get(key, *args, **kwargs):
            if key == self.ready_key:
                raise redis.exceptions.ResponseError('command denied')
            return self.client.get(key, *args, **kwargs)

        manager.client = ClientProxy(self.client, get=failed_ready_get)
        status = manager.redis_index_status(scan_count=10)
        self.assertFalse(status['ok'])
        self.assertIn('ResponseError', status['errors'])

    def test_prepare_backfills_live_members_and_defers_safe_stale_pruning(self):
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
        self.assertEqual(result['active_sessions']['stale'], 1)
        self.assertEqual(result['pending_tasks']['missing'], 0)
        self.assertEqual(result['pending_tasks']['stale'], 1)
        self.assertEqual(self.client.smembers(self.active_index_key),
                         set([INDEX_SENTINEL, 'session', 'stale-session']))
        self.assertEqual(self.client.smembers(self.pending_index_key),
                         set([INDEX_SENTINEL, 'pending', 'stale-task']))

        indexed = self.manager('indexed', 'epoch-1')
        self.assertEqual(indexed.find_expired_sessions(), ['session'])
        self.assertEqual(indexed.get_tasks_not_started(), ['pending'])
        final_status = indexed.redis_index_status(scan_count=10)
        self.assertEqual(final_status['active_sessions']['stale'], 0)
        self.assertEqual(final_status['pending_tasks']['stale'], 0)

    def test_prepare_requires_shadow_and_honors_per_base_lock(self):
        with self.assertRaises(InvalidConfigError):
            self.manager('legacy').prepare_redis_index()

        shadow = self.manager('shadow', 'epoch-1')
        self.client.set(self.lock_key, 'other-owner', ex=60)
        with self.assertRaises(AlreadyRunningError):
            shadow.prepare_redis_index()

        for invalid_ttl in ('invalid', 0):
            self.client.delete(self.lock_key)
            with self.assertRaises(InvalidConfigError):
                shadow.prepare_redis_index(lock_ttl=invalid_ttl)

    def test_prepare_does_not_include_missing_hash_or_running_task(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.client.set('{}:weblab:task_ids:active:ghost'.format(self.key_base),
                        'ghost')
        self.seed_task('running', running='1')

        result = shadow.prepare_redis_index(scan_count=10)

        self.assertTrue(result['ready'])
        self.assertEqual(self.client.smembers(self.pending_index_key),
                         set([INDEX_SENTINEL]))

    def test_prepare_batches_large_reconciliation(self):
        shadow = self.manager('shadow', 'epoch-1')
        for number in range(25):
            self.seed_session('session-{}'.format(number))
            self.seed_task('task-{}'.format(number))

        status = shadow.prepare_redis_index(scan_count=10)

        self.assertTrue(status['ready'])
        self.assertEqual(status['active_sessions']['indexed'], 25)
        self.assertEqual(status['pending_tasks']['indexed'], 25)

    def test_prepare_fails_closed_when_parity_never_converges(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.seed_session('missing')
        original_reconcile = shadow._reconcile_redis_indices
        shadow._reconcile_redis_indices = lambda scan_count: None
        try:
            with self.assertRaises(InvalidConfigError):
                shadow.prepare_redis_index(scan_count=10)
        finally:
            shadow._reconcile_redis_indices = original_reconcile

        self.assertFalse(self.client.exists(self.ready_key))
        self.assertFalse(self.client.exists(self.lock_key))

    def test_prepare_clears_readiness_if_final_verification_changes(self):
        shadow = self.manager('shadow', 'epoch-1')
        original_status = shadow.redis_index_status
        calls = [0]

        def changed_status(scan_count=500):
            calls[0] += 1
            status = original_status(scan_count)
            if calls[0] == 2:
                status['ready'] = False
            return status

        shadow.redis_index_status = changed_status
        with self.assertRaises(InvalidConfigError):
            shadow.prepare_redis_index(scan_count=10)
        self.assertFalse(self.client.exists(self.ready_key))

    def test_prepare_does_not_delete_readiness_replaced_by_another_owner(self):
        shadow = self.manager('shadow', 'epoch-1')
        original_status = shadow.redis_index_status
        calls = [0]

        def changed_status(scan_count=500):
            calls[0] += 1
            status = original_status(scan_count)
            if calls[0] == 2:
                self.client.set(self.ready_key, 'replacement-epoch')
                status['ready'] = False
            return status

        shadow.redis_index_status = changed_status
        with self.assertRaises(InvalidConfigError):
            shadow.prepare_redis_index(scan_count=10)
        self.assertEqual(self.client.get(self.ready_key), 'replacement-epoch')

    def test_lock_release_preserves_changed_owner_and_retries_watch_error(self):
        shadow = self.manager('shadow', 'epoch-1')
        self.client.set(self.lock_key, 'other-owner')
        shadow._release_index_lock('original-owner')
        self.assertEqual(self.client.get(self.lock_key), 'other-owner')

        self.client.set(self.lock_key, 'owner')
        shadow.client = WatchErrorOnceClient(self.client)
        shadow._release_index_lock('owner')
        self.assertEqual(shadow.client.pipeline_calls, 2)
        self.assertFalse(self.client.exists(self.lock_key))

    def test_concurrent_prepare_has_one_lock_owner(self):
        first = self.manager('shadow', 'epoch-1')
        second = self.manager('shadow', 'epoch-1')
        entered = threading.Event()
        release = threading.Event()
        result = []
        errors = []
        original_reconcile = first._reconcile_redis_indices

        def blocking_reconcile(scan_count):
            entered.set()
            release.wait(5)
            return original_reconcile(scan_count)

        def prepare_first():
            try:
                result.append(first.prepare_redis_index(scan_count=10))
            except Exception as error:
                errors.append(error)

        first._reconcile_redis_indices = blocking_reconcile
        thread = threading.Thread(target=prepare_first)
        thread.start()
        self.assertTrue(entered.wait(5))
        try:
            with self.assertRaises(AlreadyRunningError):
                second.prepare_redis_index(scan_count=10)
        finally:
            release.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]['ready'])

    def test_prepare_remains_complete_during_concurrent_shadow_writes(self):
        shadow = self.manager('shadow', 'epoch-1')
        started = threading.Event()
        stop = threading.Event()
        created = []

        def writer():
            while not stop.is_set() and len(created) < 500:
                task_id = shadow.new_task('session', 'task', [], {})
                created.append(task_id)
                started.set()

        thread = threading.Thread(target=writer)
        thread.start()
        self.assertTrue(started.wait(5))
        try:
            status = shadow.prepare_redis_index(scan_count=25)
        finally:
            stop.set()
            thread.join(5)

        self.assertFalse(thread.is_alive())
        self.assertTrue(status['ready'])
        final_status = shadow.redis_index_status(scan_count=25)
        self.assertTrue(final_status['ready'])
        self.assertEqual(final_status['pending_tasks']['missing'], 0)
        self.assertEqual(final_status['pending_tasks']['stale'], 0)
        self.assertEqual(final_status['pending_tasks']['expected'], len(created))


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

    def test_indexed_task_validation_batches_markers_and_hash_fields(self):
        for number in range(25):
            self.seed_task('task-{}'.format(number))
        manager = self.indexed_manager()

        manager.client.config_resetstat()
        self.assertEqual(len(manager.get_tasks_not_started()), 25)
        stats = manager.client.info('commandstats')

        self.assertEqual(stats.get('cmdstat_keys', {}).get('calls', 0), 0)
        self.assertEqual(stats.get('cmdstat_exists', {}).get('calls', 0), 0)
        self.assertEqual(stats['cmdstat_mget']['calls'], 1)
        self.assertEqual(stats['cmdstat_hmget']['calls'], 25)

    def test_malformed_task_hash_is_not_a_runnable_index_candidate(self):
        manager = self.indexed_manager()
        marker_key = '{}:weblab:task_ids:active:malformed'.format(
            self.key_base)
        task_key = '{}:weblab:tasks:malformed'.format(self.key_base)
        self.client.set(marker_key, 'malformed')
        self.client.hset(task_key, 'unexpected-field', 'value')
        self.client.sadd(self.pending_index_key, 'malformed')

        self.assertEqual(manager.get_tasks_not_started(), [])
        self.assertNotIn('malformed',
                         self.client.smembers(self.pending_index_key))

    def test_wrong_type_legacy_marker_uses_compatible_existence_fallback(self):
        manager = self.indexed_manager()
        marker_key = '{}:weblab:task_ids:active:wrong-marker'.format(
            self.key_base)
        self.client.hset(marker_key, 'unexpected-field', 'value')
        self.seed_task('wrong-marker', marker=False)
        self.client.sadd(self.pending_index_key, 'wrong-marker')

        self.assertEqual(manager.get_tasks_not_started(), ['wrong-marker'])
        self.assertEqual(len(self.logger.warning_messages), 1)
        self.assertIn('marker_validation_fallback',
                      self.logger.warning_messages[0])

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
        self.assertIsNone(self.client.get(self.ready_key))

        self.client.set(self.active_index_key, 'wrong-type')
        self.assertEqual(manager.find_expired_sessions(), ['expired'])

    def test_index_member_read_error_falls_back_and_latches_legacy(self):
        self.seed_task('pending')
        manager = self.indexed_manager()
        original_pipeline = self.client.pipeline
        pipeline_calls = []

        def fail_first_pipeline():
            pipeline = original_pipeline()
            pipeline_calls.append(True)
            if len(pipeline_calls) == 1:
                def raise_error(results):
                    del results
                    raise redis.exceptions.ResponseError('command denied')
                return PipelineResultProxy(pipeline, raise_error)
            return pipeline

        manager.client = ClientProxy(self.client, pipeline=fail_first_pipeline)

        self.assertEqual(manager.get_tasks_not_started(), ['pending'])
        self.assertIsNone(self.client.get(self.ready_key))
        self.assertTrue(manager._index_runtime_unsafe)
        self.assertEqual(len(pipeline_calls), 2)

    def test_indexed_task_validation_error_falls_back_and_invalidates_readiness(self):
        self.seed_task('pending')
        manager = self.indexed_manager()
        original = manager._indexed_tasks_not_started

        def denied_validation(task_ids):
            del task_ids
            raise redis.exceptions.ResponseError('command denied')

        manager._indexed_tasks_not_started = denied_validation
        try:
            self.assertEqual(manager.get_tasks_not_started(), ['pending'])
        finally:
            manager._indexed_tasks_not_started = original

        self.assertIsNone(self.client.get(self.ready_key))
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('legacy_fallback', self.logger.critical_messages[0])

    def test_indexed_session_validation_error_falls_back_and_invalidates_readiness(self):
        self.seed_session('expired')
        manager = self.indexed_manager()
        original = manager._find_expired_sessions_from_ids
        calls = []

        def fail_once(session_ids):
            calls.append(set(session_ids))
            if len(calls) == 1:
                raise redis.exceptions.ResponseError('command denied')
            return original(session_ids)

        manager._find_expired_sessions_from_ids = fail_once
        try:
            self.assertEqual(manager.find_expired_sessions(), ['expired'])
        finally:
            manager._find_expired_sessions_from_ids = original

        self.assertEqual(len(calls), 2)
        self.assertIsNone(self.client.get(self.ready_key))
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('legacy_fallback', self.logger.critical_messages[0])

    def test_epoch_loss_falls_back_for_tasks_without_keys_on_healthy_path(self):
        self.seed_task('pending')
        manager = self.indexed_manager()
        self.client.set(self.ready_key, 'different-epoch')

        self.assertEqual(manager.get_tasks_not_started(), ['pending'])
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('epoch_not_ready', self.logger.critical_messages[0])

    def test_stale_session_is_pruned_and_prune_failure_is_nonfatal(self):
        manager = self.indexed_manager()
        self.client.sadd(self.active_index_key, 'stale')
        original_srem = manager.client.srem

        def failed_srem(*args, **kwargs):
            raise redis.exceptions.ResponseError('command denied')

        manager.client.srem = failed_srem
        try:
            self.assertEqual(manager.find_expired_sessions(), [])
        finally:
            manager.client.srem = original_srem

        self.assertIn('stale', self.client.smembers(self.active_index_key))
        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('prune_failed', self.logger.critical_messages[0])

    def test_shadow_parity_error_is_nonfatal_and_rate_limited(self):
        manager = self.manager('shadow', 'epoch-1')
        self.seed_task('pending')
        original_smembers = manager.client.smembers

        def failed_smembers(*args, **kwargs):
            raise redis.exceptions.ResponseError('command denied')

        manager.client.smembers = failed_smembers
        try:
            self.assertEqual(manager.get_tasks_not_started(), ['pending'])
            self.assertEqual(manager.get_tasks_not_started(), ['pending'])
        finally:
            manager.client.smembers = original_smembers

        self.assertEqual(len(self.logger.warning_messages), 1)
        self.assertIn('shadow_parity_error', self.logger.warning_messages[0])

    def test_index_event_without_logger_is_nonfatal(self):
        manager = self.manager()
        manager.weblab = object()
        self.assertFalse(manager._emit_index_event(
            'critical', 'legacy_fallback', 'pending_tasks'))

    def test_readiness_invalidation_failure_is_reported(self):
        manager = self.manager()

        def denied_delete(*args, **kwargs):
            del args, kwargs
            raise redis.exceptions.ResponseError('command denied')

        manager.client = ClientProxy(self.client, delete=denied_delete)
        manager._invalidate_index_readiness(
            'pending_tasks', 'legacy_fallback', 'test')

        self.assertEqual(len(self.logger.critical_messages), 1)
        self.assertIn('readiness_invalidation_error',
                      self.logger.critical_messages[0])

    def test_legacy_session_validation_error_is_not_masked(self):
        manager = self.manager()
        original = manager._find_expired_sessions_from_ids

        def denied_validation(session_ids):
            del session_ids
            raise redis.exceptions.ResponseError('command denied')

        manager._find_expired_sessions_from_ids = denied_validation
        try:
            with self.assertRaises(redis.exceptions.ResponseError):
                manager.find_expired_sessions()
        finally:
            manager._find_expired_sessions_from_ids = original

    def test_test_cleanup_removes_indexed_session_member(self):
        manager = self.manager('shadow', 'epoch-1')
        manager.add_user('session', FakeCurrentUser(), 60)
        manager._tests_delete_user('session')
        self.assertNotIn('session', self.client.smembers(self.active_index_key))


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
        runner = app.test_cli_runner()

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

    def test_cli_human_output_error_exit_and_custom_backend(self):
        app, extension = self.create_app({
            'WEBLAB_REDIS_INDEX_MODE': 'shadow',
            'WEBLAB_REDIS_INDEX_EPOCH': 'epoch-1',
        })
        runner = app.test_cli_runner()

        status_result = runner.invoke(app.cli, [
            'weblab', 'redis-index', 'status'])
        self.assertEqual(status_result.exit_code, 0, status_result.output)
        self.assertIn('Mode: shadow', status_result.output)
        self.assertIn('Active sessions:', status_result.output)
        self.assertIn('Pending tasks:', status_result.output)

        prepare_result = runner.invoke(app.cli, [
            'weblab', 'redis-index', 'prepare', '--scan-count', '10'])
        self.assertEqual(prepare_result.exit_code, 0, prepare_result.output)
        self.assertIn('Ready: yes', prepare_result.output)

        original_policy = self.client.config_get(
            'maxmemory-policy')['maxmemory-policy']
        try:
            self.client.config_set('maxmemory-policy', 'allkeys-lru')
            error_result = runner.invoke(app.cli, [
                'weblab', 'redis-index', 'status'])
            self.assertEqual(error_result.exit_code, 1, error_result.output)
            self.assertIn('Errors: unsupported_eviction_policy',
                          error_result.output)
        finally:
            self.client.config_set('maxmemory-policy', original_policy)

        extension._backend = object()
        custom_result = runner.invoke(app.cli, [
            'weblab', 'redis-index', 'status'])
        self.assertNotEqual(custom_result.exit_code, 0)
        self.assertIn('does not provide Redis indices', custom_result.output)
        extension._cleanup()


if __name__ == '__main__':
    unittest.main()
