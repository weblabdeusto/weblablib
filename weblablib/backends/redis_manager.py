# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import json
import time

import redis
import six
from flask import current_app

from weblablib.config import ConfigurationKeys
from weblablib.exc import AlreadyRunningError, InvalidConfigError
from weblablib.utils import create_token, _current_timestamp
from weblablib.users import AnonymousUser, CurrentUser, ExpiredUser


REDIS_INDEX_MODES = ('legacy', 'shadow', 'indexed')
REDIS_INDEX_SENTINEL = '__weblablib_index_v1__'
REDIS_INDEX_PROBE_MEMBER = '__weblablib_index_v1_probe__'


class RedisManager(object):
    """
    To manage users, sessions and tasks.

    USER-RELATED STRUCTURES:
    - <prefix>:weblab:sessions:<session_id> : These keys contain the session ids, storing their creation time. They are
    set to expire when created, so they might need to be refreshed. These keys are used to check if a session has been
    deleted, or to request that a session be deleted.

    - <prefix>:weblab:active:<session_id> : These are the actual hashsets with the field values for the users. They are
    set to expire too, so they might need to be refreshed as well.

    TASK-RELATED STRUCTURES:
    - <prefix>:weblab:tasks:<task_id> : Hashset that stores the actual task info.

    - ...
    """

    def __init__(self, redis_url, key_base, task_expires, weblab,
                 index_mode='legacy', index_epoch=None):
        self.client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
        self.weblab = weblab
        self.key_base = key_base  # Redis base prefix to use. It is *not* user or session specific.

        self.task_expires = task_expires
        self.index_mode = self._normalize_index_mode(index_mode)
        self.index_epoch = self._normalize_index_epoch(index_epoch)
        self._active_sessions_index_key = '{}:weblab:index:v1:active_sessions'.format(key_base)
        self._pending_tasks_index_key = '{}:weblab:index:v1:pending_tasks'.format(key_base)
        self._index_ready_key = '{}:weblab:index:v1:ready'.format(key_base)
        self._index_lock_key = '{}:weblab:index:v1:migration_lock'.format(key_base)
        self._index_writes = self.index_mode in ('shadow', 'indexed')
        self._index_log_times = {}

        if self.index_mode != 'legacy':
            if not self.index_epoch:
                raise InvalidConfigError(
                    'WEBLAB_REDIS_INDEX_EPOCH is required in {} mode'.format(
                        self.index_mode))
            self._preflight_redis_index()
            if self.index_mode == 'indexed':
                self._validate_indexed_readiness()

    def _normalize_index_mode(self, index_mode):
        try:
            normalized = six.text_type(index_mode or 'legacy').strip().lower()
        except (TypeError, ValueError):
            raise InvalidConfigError('Invalid WEBLAB_REDIS_INDEX_MODE')
        if normalized not in REDIS_INDEX_MODES:
            raise InvalidConfigError(
                'WEBLAB_REDIS_INDEX_MODE must be one of: {}'.format(
                    ', '.join(REDIS_INDEX_MODES)))
        return normalized

    def _normalize_index_epoch(self, index_epoch):
        if index_epoch is None:
            return None
        try:
            return six.text_type(index_epoch).strip()
        except (TypeError, ValueError):
            raise InvalidConfigError('Invalid WEBLAB_REDIS_INDEX_EPOCH')

    def _preflight_redis_index(self):
        try:
            policy_config = self.client.config_get('maxmemory-policy')
            policy = policy_config.get('maxmemory-policy')
            if not policy:
                raise InvalidConfigError(
                    'Could not determine Redis maxmemory-policy')
            if policy.startswith('allkeys-'):
                raise InvalidConfigError(
                    'Redis index modes do not support {} eviction'.format(policy))

            cluster_info = self.client.info('cluster')
            if int(cluster_info.get('cluster_enabled', 0)):
                raise InvalidConfigError(
                    'Redis Cluster is not supported by the WebLabLib backend')

            expected_types = (
                (self._active_sessions_index_key, ('none', 'set')),
                (self._pending_tasks_index_key, ('none', 'set')),
                (self._index_ready_key, ('none', 'string')),
                (self._index_lock_key, ('none', 'string')),
            )
            observed_types = {}
            for key, allowed_types in expected_types:
                key_type = self.client.type(key)
                observed_types[key] = key_type
            for key, allowed_types in expected_types:
                key_type = observed_types[key]
                if key_type not in allowed_types:
                    raise InvalidConfigError(
                        'Unexpected Redis type {} for internal index key'.format(
                            key_type))

            ready_epoch = self.client.get(self._index_ready_key)
            if ready_epoch is not None:
                for key in (self._active_sessions_index_key,
                            self._pending_tasks_index_key):
                    if observed_types[key] != 'set':
                        raise InvalidConfigError(
                            'A prepared Redis index set is missing')
                    if REDIS_INDEX_SENTINEL not in self.client.smembers(key):
                        raise InvalidConfigError(
                            'A prepared Redis index sentinel is missing')

            # SCAN is management-only, but verify it before allowing a mode
            # that can later be marked ready.
            self.client.scan(cursor=0,
                             match='{}:weblab:index:v1:command-probe:*'.format(
                                 self.key_base),
                             count=1)

            probe_key = '{}:weblab:index:v1:command-probe:{}'.format(
                self.key_base, create_token())
            pipeline = self.client.pipeline()
            pipeline.sadd(probe_key, REDIS_INDEX_PROBE_MEMBER)
            pipeline.expire(probe_key, 60)
            pipeline.smembers(probe_key)
            pipeline.srem(probe_key, REDIS_INDEX_PROBE_MEMBER)
            pipeline.delete(probe_key)
            results = pipeline.execute()
            if REDIS_INDEX_PROBE_MEMBER not in results[2]:
                raise InvalidConfigError('Redis set command probe failed')

            if self.index_mode == 'shadow' and ready_epoch is None:
                pipeline = self.client.pipeline()
                pipeline.sadd(self._active_sessions_index_key,
                              REDIS_INDEX_SENTINEL)
                pipeline.sadd(self._pending_tasks_index_key,
                              REDIS_INDEX_SENTINEL)
                pipeline.execute()
        except InvalidConfigError:
            raise
        except redis.exceptions.RedisError as error:
            raise InvalidConfigError(
                'Redis does not support the configured index mode: {}'.format(
                    error))

    def _validate_indexed_readiness(self):
        status = self.redis_index_status()
        if not status['ready']:
            raise InvalidConfigError(
                'Redis indices are not prepared for epoch {}'.format(
                    self.index_epoch))

    def _validate_scan_count(self, scan_count):
        try:
            scan_count = int(scan_count)
        except (TypeError, ValueError):
            raise InvalidConfigError('Redis index scan count must be an integer')
        if scan_count <= 0:
            raise InvalidConfigError('Redis index scan count must be positive')
        return scan_count

    def _scan_ids(self, prefix, scan_count):
        pattern = '{}*'.format(prefix)
        return [key[len(prefix):]
                for key in self.client.scan_iter(match=pattern, count=scan_count)]

    def _expected_active_session_ids(self, scan_count):
        prefix = '{}:weblab:active:'.format(self.key_base)
        session_ids = self._scan_ids(prefix, scan_count)
        pipeline = self.client.pipeline()
        for session_id in session_ids:
            key = '{}{}'.format(prefix, session_id)
            pipeline.hget(key, 'max_date')
            pipeline.hget(key, 'last_poll')
        values = pipeline.execute()

        expected = set()
        for index, session_id in enumerate(session_ids):
            max_date = values[index * 2]
            last_poll = values[index * 2 + 1]
            if max_date is not None and last_poll is not None:
                expected.add(session_id)
        return expected

    def _expected_pending_task_ids(self, scan_count):
        marker_prefix = '{}:weblab:task_ids:active:'.format(self.key_base)
        task_ids = self._scan_ids(marker_prefix, scan_count)
        pipeline = self.client.pipeline()
        for task_id in task_ids:
            pipeline.exists('{}{}'.format(marker_prefix, task_id))
            task_key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)
            pipeline.exists(task_key)
            pipeline.hget(task_key, 'running')
        values = pipeline.execute()

        expected = set()
        for index, task_id in enumerate(task_ids):
            marker_exists = values[index * 3]
            task_exists = values[index * 3 + 1]
            running = values[index * 3 + 2]
            if marker_exists and task_exists and not running:
                expected.add(task_id)
        return expected

    def _read_index_set(self, key, errors):
        try:
            key_type = self.client.type(key)
            if key_type == 'none':
                return set(), False
            if key_type != 'set':
                errors.append('unexpected_type')
                return set(), False
            members = self.client.smembers(key)
        except redis.exceptions.RedisError as error:
            errors.append(error.__class__.__name__)
            return set(), False

        sentinel_present = REDIS_INDEX_SENTINEL in members
        members.discard(REDIS_INDEX_SENTINEL)
        return members, sentinel_present

    def redis_index_status(self, scan_count=500):
        scan_count = self._validate_scan_count(scan_count)
        errors = []
        policy = None
        cluster_enabled = None
        try:
            policy = self.client.config_get('maxmemory-policy').get(
                'maxmemory-policy')
            if not policy:
                errors.append('maxmemory_policy_unknown')
            elif policy.startswith('allkeys-'):
                errors.append('unsupported_eviction_policy')
            cluster_enabled = int(
                self.client.info('cluster').get('cluster_enabled', 0))
            if cluster_enabled:
                errors.append('redis_cluster_unsupported')
            expected_active = self._expected_active_session_ids(scan_count)
            expected_pending = self._expected_pending_task_ids(scan_count)
        except redis.exceptions.RedisError as error:
            errors.append(error.__class__.__name__)
            expected_active = set()
            expected_pending = set()

        indexed_active, active_sentinel = self._read_index_set(
            self._active_sessions_index_key, errors)
        indexed_pending, pending_sentinel = self._read_index_set(
            self._pending_tasks_index_key, errors)
        try:
            ready_epoch = self.client.get(self._index_ready_key)
        except redis.exceptions.RedisError as error:
            errors.append(error.__class__.__name__)
            ready_epoch = None

        active_missing = expected_active - indexed_active
        active_stale = indexed_active - expected_active
        pending_missing = expected_pending - indexed_pending
        pending_stale = indexed_pending - expected_pending
        ready = bool(
            not errors and self.index_epoch and
            ready_epoch == self.index_epoch and
            active_sentinel and pending_sentinel and
            not active_missing and not pending_missing)

        return {
            'ok': not errors,
            'mode': self.index_mode,
            'epoch': self.index_epoch,
            'ready_epoch': ready_epoch,
            'ready': ready,
            'scan_count': scan_count,
            'maxmemory_policy': policy,
            'cluster_enabled': cluster_enabled,
            'errors': sorted(set(errors)),
            'active_sessions': {
                'expected': len(expected_active),
                'indexed': len(indexed_active),
                'missing': len(active_missing),
                'stale': len(active_stale),
                'sentinel': active_sentinel,
            },
            'pending_tasks': {
                'expected': len(expected_pending),
                'indexed': len(indexed_pending),
                'missing': len(pending_missing),
                'stale': len(pending_stale),
                'sentinel': pending_sentinel,
            },
        }

    def _queue_set_members(self, pipeline, method_name, key, members,
                           batch_size):
        members = list(members)
        method = getattr(pipeline, method_name)
        for start in range(0, len(members), batch_size):
            method(key, *members[start:start + batch_size])

    def _reconcile_redis_indices(self, scan_count):
        expected_active = self._expected_active_session_ids(scan_count)
        expected_pending = self._expected_pending_task_ids(scan_count)
        indexed_active = self.client.smembers(self._active_sessions_index_key)
        indexed_pending = self.client.smembers(self._pending_tasks_index_key)
        indexed_active.discard(REDIS_INDEX_SENTINEL)
        indexed_pending.discard(REDIS_INDEX_SENTINEL)

        pipeline = self.client.pipeline()
        pipeline.sadd(self._active_sessions_index_key, REDIS_INDEX_SENTINEL)
        pipeline.sadd(self._pending_tasks_index_key, REDIS_INDEX_SENTINEL)
        self._queue_set_members(pipeline, 'sadd', self._active_sessions_index_key,
                                expected_active - indexed_active, scan_count)
        self._queue_set_members(pipeline, 'srem', self._active_sessions_index_key,
                                indexed_active - expected_active, scan_count)
        self._queue_set_members(pipeline, 'sadd', self._pending_tasks_index_key,
                                expected_pending - indexed_pending, scan_count)
        self._queue_set_members(pipeline, 'srem', self._pending_tasks_index_key,
                                indexed_pending - expected_pending, scan_count)
        pipeline.execute()

    def _release_index_lock(self, token):
        while True:
            pipeline = self.client.pipeline()
            try:
                pipeline.watch(self._index_lock_key)
                if pipeline.get(self._index_lock_key) != token:
                    pipeline.unwatch()
                    return
                pipeline.multi()
                pipeline.delete(self._index_lock_key)
                pipeline.execute()
                return
            except redis.exceptions.WatchError:
                continue
            finally:
                pipeline.reset()

    def prepare_redis_index(self, scan_count=500, lock_ttl=300):
        if self.index_mode != 'shadow':
            raise InvalidConfigError(
                'Redis indices can only be prepared in shadow mode')
        scan_count = self._validate_scan_count(scan_count)
        try:
            lock_ttl = int(lock_ttl)
        except (TypeError, ValueError):
            raise InvalidConfigError('Redis index lock TTL must be an integer')
        if lock_ttl <= 0:
            raise InvalidConfigError('Redis index lock TTL must be positive')

        token = create_token()
        if not self.client.set(self._index_lock_key, token, nx=True, ex=lock_ttl):
            raise AlreadyRunningError(
                'Another Redis index preparation is already running')

        try:
            # Invalidate any previous readiness while reconciliation runs.
            self.client.delete(self._index_ready_key)
            status = None
            for _ in range(3):
                self._reconcile_redis_indices(scan_count)
                status = self.redis_index_status(scan_count)
                if (status['ok'] and
                        status['active_sessions']['missing'] == 0 and
                        status['active_sessions']['stale'] == 0 and
                        status['pending_tasks']['missing'] == 0 and
                        status['pending_tasks']['stale'] == 0):
                    break
            else:
                raise InvalidConfigError(
                    'Redis indices did not reach parity during preparation')

            self.client.set(self._index_ready_key, self.index_epoch)
            status = self.redis_index_status(scan_count)
            if not status['ready']:
                if self.client.get(self._index_ready_key) == self.index_epoch:
                    self.client.delete(self._index_ready_key)
                raise InvalidConfigError(
                    'Redis indices changed before readiness could be verified')
            return status
        finally:
            self._release_index_lock(token)

    def _emit_index_event(self, level, action, kind, reason=None, **fields):
        rate_key = (level, action, kind)
        now = time.time()
        last_time = self._index_log_times.get(rate_key)
        if last_time is not None and now - last_time < 60:
            return False
        self._index_log_times[rate_key] = now

        event = {
            'event': 'weblab_redis_index',
            'action': action,
            'kind': kind,
            'mode': self.index_mode,
            'redis_base': self.key_base,
        }
        if reason is not None:
            event['reason'] = reason
        event.update(fields)

        app = getattr(self.weblab, '_app', None)
        logger = getattr(app, 'logger', None)
        log_method = getattr(logger, level, None)
        if log_method is None:
            return False
        log_method(json.dumps(event, sort_keys=True))
        return True

    def _report_shadow_parity(self, kind, expected_ids):
        if self.index_mode != 'shadow':
            return
        if kind == 'active_sessions':
            index_key = self._active_sessions_index_key
        else:
            index_key = self._pending_tasks_index_key
        try:
            indexed_ids = self.client.smembers(index_key)
        except redis.exceptions.RedisError as error:
            self._emit_index_event('warning', 'shadow_parity_error', kind,
                                   reason=error.__class__.__name__)
            return

        indexed_ids.discard(REDIS_INDEX_SENTINEL)
        expected_ids = set(expected_ids)
        self._emit_index_event(
            'info', 'shadow_parity', kind,
            expected_count=len(expected_ids),
            indexed_count=len(indexed_ids),
            missing_count=len(expected_ids - indexed_ids),
            stale_count=len(indexed_ids - expected_ids))

    def _indexed_members(self, kind):
        if kind == 'active_sessions':
            index_key = self._active_sessions_index_key
        else:
            index_key = self._pending_tasks_index_key
        try:
            pipeline = self.client.pipeline()
            pipeline.get(self._index_ready_key)
            pipeline.smembers(index_key)
            ready_epoch, members = pipeline.execute()
        except redis.exceptions.RedisError as error:
            self._emit_index_event(
                'critical', 'legacy_fallback', kind,
                reason=error.__class__.__name__)
            return None

        if ready_epoch != self.index_epoch:
            self._emit_index_event(
                'critical', 'legacy_fallback', kind,
                reason='epoch_not_ready')
            return None
        if REDIS_INDEX_SENTINEL not in members:
            self._emit_index_event(
                'critical', 'legacy_fallback', kind,
                reason='sentinel_missing')
            return None
        members.discard(REDIS_INDEX_SENTINEL)
        return members

    def _prune_index_members(self, kind, members):
        if not members:
            return
        if kind == 'active_sessions':
            index_key = self._active_sessions_index_key
        else:
            index_key = self._pending_tasks_index_key
        try:
            self.client.srem(index_key, *members)
        except redis.exceptions.RedisError as error:
            self._emit_index_event(
                'critical', 'prune_failed', kind,
                reason=error.__class__.__name__, member_count=len(members))

    def add_user(self, session_id, user, expiration):
        """
        Adds a new user.
        This will:
          - Store all user fields into a <prefix>:weblab:active:<sessionid> hashset.
          - Schedule this hashset to expire in a while.
          - Store the sessionid with the current time in the key <prefix>:weblab:sessions:<sessionid>
          - Schedule this last key to expire in a while.
        """
        key = '{}:weblab:active:{}'.format(self.key_base, session_id)

        pipeline = self.client.pipeline()
        pipeline.hset(key, 'max_date', user.max_date)
        pipeline.hset(key, 'last_poll', user.last_poll)
        pipeline.hset(key, 'username', user.username)
        pipeline.hset(key, 'username-unique', user.username_unique)
        pipeline.hset(key, 'data', json.dumps(user.data))
        pipeline.hset(key, 'back', user.back)
        pipeline.hset(key, 'exited', json.dumps(user.exited))
        pipeline.hset(key, 'locale', json.dumps(user.locale))
        pipeline.hset(key, 'full_name', json.dumps(user.full_name))
        pipeline.hset(key, 'experiment_name', json.dumps(user.experiment_name))
        pipeline.hset(key, 'category_name', json.dumps(user.category_name))
        pipeline.hset(key, 'experiment_id', json.dumps(user.experiment_id))
        pipeline.hset(key, 'start_date', user.start_date)
        pipeline.hset(key, 'request_client_data', json.dumps(user.request_client_data))
        pipeline.hset(key, 'request_server_data', json.dumps(user.request_server_data))
        pipeline.expire(key, expiration)
        pipeline.set('{}:weblab:sessions:{}'.format(self.key_base, session_id), time.time())
        pipeline.expire('{}:weblab:sessions:{}'.format(self.key_base, session_id), expiration + 300)
        if self._index_writes:
            pipeline.sadd(self._active_sessions_index_key, session_id)
        pipeline.execute()

    def is_session_deleted(self, session_id):
        return self.client.get('{}:weblab:sessions:{}'.format(self.key_base, session_id)) is None

    def report_session_deleted(self, session_id):
        self.client.delete('{}:weblab:sessions:{}'.format(self.key_base, session_id))

    def mark_session_lifecycle_event_once(self, session_id, action):
        expiration = current_app.config.get(ConfigurationKeys.WEBLAB_EXPIRED_USERS_TIMEOUT, 3600)
        key = '{}:weblab:lifecycle:{}:{}'.format(self.key_base, action, session_id)
        return bool(self.client.set(key, '1', ex=expiration, nx=True))

    def update_data(self, session_id, data):
        key_active = '{}:weblab:active:{}'.format(self.key_base, session_id)
        key_inactive = '{}:weblab:inactive:{}'.format(self.key_base, session_id)

        pipeline = self.client.pipeline()
        pipeline.hget(key_active, 'max_date')
        pipeline.hget(key_inactive, 'max_date')
        pipeline.hset(key_active, 'data', json.dumps(data))
        pipeline.hset(key_inactive, 'data', json.dumps(data))
        max_date_active, max_date_inactive, _, _ = pipeline.execute()

        if max_date_active is None:  # Object had been removed
            self.client.delete(key_active)

        if max_date_inactive is None:  # Object had been removed
            self.client.delete(key_inactive)

    def get_user(self, session_id):
        pipeline = self.client.pipeline()
        key = '{}:weblab:active:{}'.format(self.key_base, session_id)
        for name in ('back', 'last_poll', 'max_date', 'username', 'username-unique', 'data',
                     'exited', 'locale', 'full_name', 'experiment_name', 'category_name',
                     'experiment_id', 'request_client_data', 'request_server_data',
                     'start_date'):
            pipeline.hget(key, name)

        (back, last_poll, max_date, username,
         username_unique, data, exited, locale, full_name,
         experiment_name, category_name, experiment_id,
         request_client_data, request_server_data, start_date) = pipeline.execute()

        if max_date is not None:
            return CurrentUser(session_id=session_id, back=back, last_poll=float(last_poll),
                               max_date=float(max_date), username=username,
                               username_unique=username_unique,
                               data=json.loads(data), exited=json.loads(exited),
                               locale=json.loads(locale), full_name=json.loads(full_name),
                               experiment_name=json.loads(experiment_name),
                               category_name=json.loads(category_name),
                               request_client_data=json.loads(request_client_data),
                               request_server_data=json.loads(request_server_data),
                               start_date=float(start_date),
                               experiment_id=json.loads(experiment_id))

        return self.get_expired_user(session_id)

    def get_expired_user(self, session_id):
        pipeline = self.client.pipeline()
        key = '{}:weblab:inactive:{}'.format(self.key_base, session_id)
        for name in ('back', 'max_date', 'username', 'username-unique', 'data', 'locale',
                     'full_name', 'experiment_name', 'category_name', 'experiment_id', 'exited', 'last_poll',
                     'request_client_data', 'request_server_data', 'start_date', 'disposing_resources'):
            pipeline.hget(key, name)

        (back, max_date, username, username_unique, data, locale,
         full_name, experiment_name, category_name, experiment_id, exited, last_poll,
         request_client_data, request_server_data, start_date, disposing_resources) = pipeline.execute()

        if max_date is not None:
            return ExpiredUser(session_id=session_id, last_poll=last_poll, back=back, max_date=float(max_date), exited=exited,
                               username=username, username_unique=username_unique,
                               data=json.loads(data),
                               locale=json.loads(locale),
                               full_name=json.loads(full_name),
                               experiment_name=json.loads(experiment_name),
                               category_name=json.loads(category_name),
                               experiment_id=json.loads(experiment_id),
                               request_client_data=json.loads(request_client_data),
                               request_server_data=json.loads(request_server_data),
                               start_date=float(start_date),
                               disposing_resources=json.loads(disposing_resources))

        return AnonymousUser()

    def _tests_delete_user(self, session_id):
        "Only for testing"
        pipeline = self.client.pipeline()
        pipeline.delete('{}:weblab:active:{}'.format(self.key_base, session_id))
        pipeline.delete('{}:weblab:inactive:{}'.format(self.key_base, session_id))
        if self._index_writes:
            pipeline.srem(self._active_sessions_index_key, session_id)
        pipeline.execute()

    def delete_user(self, session_id, expired_user):
        if self.client.hget('{}:weblab:active:{}'.format(self.key_base, session_id), "max_date") is None:
            return False

        #
        # If two processes at the same time call delete() and establish the same second,
        # it's not a big deal (as long as only one calls _on_delete later).
        #
        pipeline = self.client.pipeline()
        pipeline.delete("{}:weblab:active:{}".format(self.key_base, session_id))

        key = '{}:weblab:inactive:{}'.format(self.key_base, session_id)

        pipeline.hset(key, "back", expired_user.back)
        pipeline.hset(key, "max_date", expired_user.max_date)
        pipeline.hset(key, "username", expired_user.username)
        pipeline.hset(key, "username-unique", expired_user.username_unique)
        pipeline.hset(key, "data", json.dumps(expired_user.data))
        pipeline.hset(key, "locale", json.dumps(expired_user.locale))
        pipeline.hset(key, "full_name", json.dumps(expired_user.full_name))
        pipeline.hset(key, "experiment_name", json.dumps(expired_user.experiment_name))
        pipeline.hset(key, "category_name", json.dumps(expired_user.category_name))
        pipeline.hset(key, "experiment_id", json.dumps(expired_user.experiment_id))
        pipeline.hset(key, "request_client_data", json.dumps(expired_user.request_client_data))
        pipeline.hset(key, "request_server_data", json.dumps(expired_user.request_server_data))
        pipeline.hset(key, "start_date", expired_user.start_date)
        pipeline.hset(key, "disposing_resources", json.dumps(True))

        # During half an hour after being created, the user is redirected to
        # the original URL. After that, every record of the user has been deleted
        pipeline.expire("{}:weblab:inactive:{}".format(self.key_base, session_id), current_app.config.get(ConfigurationKeys.WEBLAB_EXPIRED_USERS_TIMEOUT, 3600))
        if self._index_writes:
            pipeline.srem(self._active_sessions_index_key, session_id)
        results = pipeline.execute()

        return results[0] != 0 # If redis returns 0 on delete() it means that it was not deleted

    def finished_dispose(self, session_id):
        key = '{}:weblab:inactive:{}'.format(self.key_base, session_id)
        if self.client.hset(key, "disposing_resources", json.dumps(False)) == 1:
            self.client.delete(key)

    def force_exit(self, session_id):
        """
        If the user logs out, or closes the window, we have to report
        WebLab-Deusto.
        """
        pipeline = self.client.pipeline()
        pipeline.hget("{}:weblab:active:{}".format(self.key_base, session_id), "max_date")
        pipeline.hset("{}:weblab:active:{}".format(self.key_base, session_id), "exited", "true")
        max_date, _ = pipeline.execute()
        if max_date is None:
            # If max_date is None it means that it had been previously deleted
            self.client.delete("{}:weblab:active:{}".format(self.key_base, session_id))

    def _legacy_active_session_ids(self):
        prefix = '{}:weblab:active:'.format(self.key_base)
        return [active_key[len(prefix):]
                for active_key in self.client.keys('{}*'.format(prefix))]

    def _find_expired_sessions_from_ids(self, session_ids):
        expired_sessions = []
        valid_sessions = []
        stale_sessions = []

        for session_id in session_ids:
            session_id_key = '{}:weblab:active:{}'.format(self.key_base, session_id)

            pipeline = self.client.pipeline()
            pipeline.hget(session_id_key, 'max_date')
            pipeline.hget(session_id_key, 'last_poll')
            pipeline.hget(session_id_key, 'exited')

            max_date, last_poll, exited = pipeline.execute()

            if max_date is not None and last_poll is not None: 
                # Double check: he might be deleted in the meanwhile
                # We don't use 'active', since active takes into account 'exited'
                valid_sessions.append(session_id)

                time_left = float(max_date) - _current_timestamp()
                time_without_polling = _current_timestamp() - float(last_poll)
                user_exited = exited in ('true', '1', 'True', 'TRUE')

                if time_left <= 0:
                    expired_sessions.append(session_id)

                elif time_without_polling >= self.weblab.timeout:
                    expired_sessions.append(session_id)

                elif user_exited:
                    expired_sessions.append(session_id)
            else:
                stale_sessions.append(session_id)

        return expired_sessions, valid_sessions, stale_sessions

    def find_expired_sessions(self):
        indexed_ids = None
        if self.index_mode == 'indexed':
            indexed_ids = self._indexed_members('active_sessions')

        if indexed_ids is None:
            session_ids = self._legacy_active_session_ids()
        else:
            session_ids = indexed_ids

        expired_sessions, valid_sessions, stale_sessions = \
            self._find_expired_sessions_from_ids(session_ids)

        if self.index_mode == 'indexed' and indexed_ids is not None:
            self._prune_index_members('active_sessions', stale_sessions)
        self._report_shadow_parity('active_sessions', valid_sessions)
        return expired_sessions

    def session_exists(self, session_id):
        user = self.get_user(session_id)
        return not user.is_anonymous

    def poll(self, session_id):
        key = '{}:weblab:active:{}'.format(self.key_base, session_id)

        last_poll = _current_timestamp()
        pipeline = self.client.pipeline()
        pipeline.hget(key, "max_date")
        pipeline.hset(key, "last_poll", last_poll)
        max_date, _ = pipeline.execute()

        if max_date is None:
            # If the user was deleted in between, revert the last_poll
            self.client.delete(key)

    #
    # Storage-related Redis methods
    def store_action(self, session_id, action_id, action):
        if not isinstance(action, dict):
            raise ValueError("Actions must be dictionaries of data")

        raw_action = {
            'ts': time.time(),
        }
        raw_action.update(action)

        key = '{}:weblab:storage:{}'.format(self.key_base, session_id)

        pipeline = self.client.pipeline()
        pipeline.hset(key, action_id, json.dumps(raw_action))
        pipeline.expire(key, 3600 * 24) # Store in memory for maximum 24 hours
        pipeline.execute()

    def clean_actions(self, session_id):
        """
        Deletes all the stored actions for a session_id. Frees memory, so
        WebLab-Deusto should call it after obtaining the data.
        """
        key = '{}:weblab:storage:{}'.format(self.key_base, session_id)
        self.client.delete(key)

    #
    # Task-related Redis methods
    #
    def new_task(self, session_id, name, args, kwargs):
        """
        Get a new function, args and kwargs, and return the task_id.
        """
        task_id = create_token()
        while True:
            pipeline = self.client.pipeline()
            pipeline.set('{}:weblab:task_ids:{}'.format(self.key_base, task_id), task_id, nx=True)
            pipeline.expire('{}:weblab:task_ids:{}'.format(self.key_base, task_id), self.task_expires)
            results = pipeline.execute()

            if results[0]:
                # Ensure it's unique
                break

            # Otherwise try with another
            task_id = create_token()

        # Register the new task atomically.
        pipeline = self.client.pipeline()
        # Register the actual values for the task within a hashset with a task-specific key.
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'name', name)
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'session_id', session_id)
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'args', json.dumps(args))
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'kwargs', json.dumps(kwargs))
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'finished', 'false')
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'error', 'null')
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'result', 'null')
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'data', json.dumps({}))
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'stopping', json.dumps(False))
        # Missing (normal): running. When created, we know if it's a new key and therefore that
        # no other thread is processing it.

        # Add the taskid into a set where we will store all ids.
        pipeline.sadd('{}:weblab:{}:tasks'.format(self.key_base, session_id), task_id)
        pipeline.expire('{}:weblab:{}:tasks'.format(self.key_base, session_id), self.task_expires)

        # Only show these tasks when active is created
        pipeline.set('{}:weblab:task_ids:active:{}'.format(self.key_base, task_id), task_id)
        pipeline.expire('{}:weblab:task_ids:active:{}'.format(self.key_base, task_id), self.task_expires)
        if self._index_writes:
            pipeline.sadd(self._pending_tasks_index_key, task_id)
        pipeline.execute()
        return task_id

    def clean_lock_global_unique_task(self, task_name):
        self.unlock_global_unique_task(task_name)

    def lock_global_unique_task(self, task_name):
        key = '{}:weblab:global-unique-tasks:{}'.format(self.key_base, task_name)
        pipeline = self.client.pipeline()
        pipeline.hset(key, 'running', 1)
        pipeline.expire(key, 7200)  # 2-hour task lock is way too long in the context of remote labs
        established, _ = pipeline.execute()
        return established == 1

    def lock_user_unique_task(self, task_name, session_id):
        key = '{}:weblab:user-unique-tasks:{}:{}'.format(self.key_base, task_name, session_id)
        pipeline = self.client.pipeline()
        pipeline.hset(key, 'running', 1)
        pipeline.expire(key, 7200) # 2-hour task lock is way too long in the context of remote labs
        established, _ = pipeline.execute()
        return established == 1

    def unlock_global_unique_task(self, task_name):
        self.client.delete('{}:weblab:global-unique-tasks:{}'.format(self.key_base, task_name))

    def unlock_user_unique_task(self, task_name, session_id):
        self.client.delete('{}:weblab:user-unique-tasks:{}:{}'.format(self.key_base, task_name, session_id))

    def _legacy_tasks_not_started(self):
        task_ids = [key[len('{}:weblab:task_ids:active:'.format(self.key_base)):]
                    for key in self.client.keys('{}:weblab:task_ids:active:*'.format(self.key_base))]

        pipeline = self.client.pipeline()
        for task_id in task_ids:
            pipeline.hget('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'running')

        results = pipeline.execute()

        not_started = []

        for task_id, running in zip(task_ids, results):
            if not running:
                not_started.append(task_id)

        return not_started

    def _indexed_tasks_not_started(self, task_ids):
        pipeline = self.client.pipeline()
        for task_id in task_ids:
            marker_key = '{}:weblab:task_ids:active:{}'.format(
                self.key_base, task_id)
            task_key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)
            pipeline.exists(marker_key)
            pipeline.exists(task_key)
            pipeline.hget(task_key, 'running')
        values = pipeline.execute()

        not_started = []
        stale = []
        for index, task_id in enumerate(task_ids):
            marker_exists = values[index * 3]
            task_exists = values[index * 3 + 1]
            running = values[index * 3 + 2]
            if marker_exists and task_exists and not running:
                not_started.append(task_id)
            else:
                stale.append(task_id)
        self._prune_index_members('pending_tasks', stale)
        return not_started

    def get_tasks_not_started(self):
        if self.index_mode == 'indexed':
            indexed_ids = self._indexed_members('pending_tasks')
            if indexed_ids is not None:
                return self._indexed_tasks_not_started(indexed_ids)

        not_started = self._legacy_tasks_not_started()
        self._report_shadow_parity('pending_tasks', not_started)
        return not_started

    def start_task(self, task_id):
        """
        Mark a task as running.

        If it exists, return a dictionary with name, args, kwargs and session_id

        If it doesn't exist or is taken by other thread, return None
        """
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)

        pipeline = self.client.pipeline()
        pipeline.hset(key, 'running', '1')
        pipeline.hget(key, 'name')
        pipeline.hget(key, 'args')
        pipeline.hget(key, 'kwargs')
        pipeline.hget(key, 'session_id')
        if self._index_writes:
            pipeline.srem(self._pending_tasks_index_key, task_id)

        results = pipeline.execute()
        running, name, args, kwargs, session_id = results[:5]
        if not running:
            # other thread did the hset first
            return None

        # If runnning == 1...
        if name is None:
            # The object was deleted before
            self.client.delete(key)
            return None

        return {
            'name': name,
            'args': json.loads(args),
            'kwargs': json.loads(kwargs),
            'session_id': session_id,
        }

    def finish_task(self, task_id, result=None, error=None):
        if error and result:
            raise ValueError("You can't provide result and error: either one or the other")
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)

        pipeline = self.client.pipeline()
        pipeline.hget(key, 'session_id')
        pipeline.hset(key, 'finished', 'true')
        pipeline.hset(key, 'result', json.dumps(result))
        pipeline.hset(key, 'error', json.dumps(error))
        if self._index_writes:
            pipeline.srem(self._pending_tasks_index_key, task_id)
        results = pipeline.execute()
        if not results[0]:
            # If it had been deleted... delete it
            self.client.delete(key)

    def update_task_data(self, task_id, new_data):
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)
        pipeline = self.client.pipeline()
        pipeline.hget(key, 'name')
        pipeline.hset(key, 'data', json.dumps(new_data))
        name, _ = pipeline.execute()
        # ~lrg: This will delete the whole hashset if the 'name' field is not present, but not sure how
        # that would happen.
        if name is None:
            # Deleted in the meanwhile
            self.client.delete(key)

    def request_stop_task(self, task_id):
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)
        pipeline = self.client.pipeline()
        pipeline.hget(key, 'name')
        pipeline.hset(key, 'stopping', json.dumps(True))
        name, _ = pipeline.execute()
        if name is None:
            # Deleted in the meanwhile
            self.client.delete(key)

    def get_task(self, task_id):
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)

        pipeline = self.client.pipeline()
        pipeline.hget(key, 'session_id')
        pipeline.hget(key, 'finished')
        pipeline.hget(key, 'error')
        pipeline.hget(key, 'result')
        pipeline.hget(key, 'running')
        pipeline.hget(key, 'name')
        pipeline.hget(key, 'data')
        pipeline.hget(key, 'stopping')
        session_id, finished, error_str, result_str, running, name, data_str, stopping_str = pipeline.execute()

        if session_id is None:
            return None

        error = json.loads(error_str)
        result = json.loads(result_str)
        data = json.loads(data_str)
        stopping = json.loads(stopping_str)

        if not running:
            status = 'submitted'
        elif finished == 'true':
            if error:
                status = 'failed'
            else:
                status = 'done'
        else:
            status = 'running'

        return {
            'task_id': task_id,
            'result': result,
            'error': error,
            'status': status,
            'session_id': session_id,
            'name': name,
            'data': data,
            'stopping': stopping,
        }

    def get_all_tasks(self, session_id):
        return self.client.smembers('{}:weblab:{}:tasks'.format(self.key_base, session_id))

    def get_unfinished_tasks(self, session_id):
        task_ids = self.client.smembers('{}:weblab:{}:tasks'.format(self.key_base, session_id))
        pipeline = self.client.pipeline()
        for task_id in task_ids:
            pipeline.hget('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'finished')

        pending_task_ids = []
        for task_id, finished in zip(task_ids, pipeline.execute()):
            if finished == 'false':  # If finished or failed: true; if expired: None
                pending_task_ids.append(task_id)

        return pending_task_ids

    def clean_session_tasks(self, session_id):
        task_ids = self.client.smembers('{}:weblab:{}:tasks'.format(self.key_base, session_id))

        pipeline = self.client.pipeline()
        pipeline.delete('{}:weblab:{}:tasks'.format(self.key_base, session_id))
        for task_id in task_ids:
            pipeline.delete('{}:weblab:tasks:{}'.format(self.key_base, task_id))
            pipeline.delete('{}:weblab:task_ids:{}'.format(self.key_base, task_id))
            pipeline.delete('{}:weblab:task_ids:active:{}'.format(self.key_base, task_id))
            if self._index_writes:
                pipeline.srem(self._pending_tasks_index_key, task_id)
        pipeline.execute()
