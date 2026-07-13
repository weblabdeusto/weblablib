from __future__ import unicode_literals, print_function, division

import argparse
import json
import threading
import time
import uuid

try:
    import queue
except ImportError:  # pragma: no cover - Python 2
    import Queue as queue

import redis
from flask import Flask

import weblablib.backends.redis_manager as redis_manager_module
from weblablib.backends.redis_manager import RedisManager


INDEX_SENTINEL = '__weblablib_index_v1__'


class NullLogger(object):
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def critical(self, *args, **kwargs):
        pass


class FakeApp(object):
    logger = NullLogger()


class FakeWebLab(object):
    timeout = 10
    _app = FakeApp()


class FakeUser(object):
    max_date = 2000000000
    last_poll = 1000000000
    username = 'stress-user'
    username_unique = 'stress-user@example.invalid'
    data = {}
    back = 'https://example.invalid/back'
    exited = False
    locale = 'en'
    full_name = 'Stress User'
    experiment_name = 'stress'
    category_name = 'test'
    experiment_id = 'stress@test'
    start_date = 1000000000
    request_client_data = {}
    request_server_data = {}


class FakeExpiredUser(FakeUser):
    pass


class FailingPipeline(object):
    def __init__(self, pipeline, error, commit_first):
        self._pipeline = pipeline
        self._error = error
        self._commit_first = commit_first

    def __getattr__(self, name):
        return getattr(self._pipeline, name)

    def execute(self):
        if self._commit_first:
            self._pipeline.execute()
        raise self._error


def command_calls(client, command):
    stats = client.info('commandstats')
    return int(stats.get('cmdstat_{}'.format(command), {}).get('calls', 0))


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def run_crash_contract(redis_url, key_base):
    manager = RedisManager(redis_url, key_base, 300, FakeWebLab(),
                           index_mode='shadow', index_epoch='stress-epoch')
    client = manager.client
    active_index_key = '{}:weblab:index:v1:active_sessions'.format(key_base)
    pending_index_key = '{}:weblab:index:v1:pending_tasks'.format(key_base)
    original_pipeline = client.pipeline

    client.pipeline = lambda: FailingPipeline(
        original_pipeline(), redis.exceptions.ResponseError('OOM'), False)
    try:
        manager.add_user('session-before-commit', FakeUser(), 300)
    except redis.exceptions.ResponseError:
        pass
    else:
        raise AssertionError('pre-commit failure did not propagate')
    assert_true(not client.exists(
        '{}:weblab:active:session-before-commit'.format(key_base)),
        'pre-commit failure created a session hash')
    assert_true('session-before-commit' not in client.smembers(active_index_key),
                'pre-commit failure created an index member')

    client.pipeline = lambda: FailingPipeline(
        original_pipeline(), redis.exceptions.ConnectionError('lost reply'), True)
    try:
        manager.add_user('session-after-commit', FakeUser(), 300)
    except redis.exceptions.ConnectionError:
        pass
    else:
        raise AssertionError('post-commit failure did not propagate')
    assert_true(client.exists(
        '{}:weblab:active:session-after-commit'.format(key_base)),
        'post-commit failure lost a committed session hash')
    assert_true('session-after-commit' in client.smembers(active_index_key),
                'post-commit failure lost the committed index member')

    def task_failure(commit_first, task_id, error):
        pipeline_calls = [0]

        def pipeline():
            pipeline_calls[0] += 1
            underlying = original_pipeline()
            if pipeline_calls[0] == 2:
                return FailingPipeline(underlying, error, commit_first)
            return underlying

        old_create_token = redis_manager_module.create_token
        redis_manager_module.create_token = lambda: task_id
        client.pipeline = pipeline
        try:
            manager.new_task('session', 'task', [], {})
        except error.__class__:
            pass
        else:
            raise AssertionError('task transaction failure did not propagate')
        finally:
            redis_manager_module.create_token = old_create_token

    task_failure(False, 'task-before-commit',
                 redis.exceptions.ResponseError('OOM'))
    assert_true(client.exists(
        '{}:weblab:task_ids:task-before-commit'.format(key_base)),
        'pre-commit task failure changed the legacy uniqueness-marker contract')
    assert_true(not client.exists(
        '{}:weblab:tasks:task-before-commit'.format(key_base)),
        'pre-commit task failure created a task hash')
    assert_true('task-before-commit' not in client.smembers(pending_index_key),
                'pre-commit task failure created an index member')

    task_failure(True, 'task-after-commit',
                 redis.exceptions.ConnectionError('lost reply'))
    assert_true(client.exists(
        '{}:weblab:tasks:task-after-commit'.format(key_base)),
        'post-commit task failure lost a committed task hash')
    assert_true(client.exists(
        '{}:weblab:task_ids:active:task-after-commit'.format(key_base)),
        'post-commit task failure lost the active marker')
    assert_true('task-after-commit' in client.smembers(pending_index_key),
                'post-commit task failure lost the committed index member')
    client.pipeline = original_pipeline


def run_stress(redis_url, task_count, thread_count):
    key_base = 'weblablib-index-stress-{}'.format(uuid.uuid4().hex)
    client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    app = Flask(__name__)
    app.config['WEBLAB_EXPIRED_USERS_TIMEOUT'] = 300
    started_at = time.time()
    keys_before = command_calls(client, 'keys')

    try:
        shadow = RedisManager(redis_url, key_base, 300, FakeWebLab(),
                              index_mode='shadow', index_epoch='stress-epoch')
        shadow.prepare_redis_index(scan_count=500)
        manager = RedisManager(redis_url, key_base, 300, FakeWebLab(),
                               index_mode='indexed', index_epoch='stress-epoch')
        original_keys = manager.client.keys
        manager.client.keys = lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError('indexed hot path used KEYS'))

        task_ids = [manager.new_task('session', 'task', [], {})
                    for _ in range(task_count)]
        discovered = manager.get_tasks_not_started()
        assert_true(set(discovered) == set(task_ids),
                    'indexed discovery lost or added live tasks')

        race_task = manager.new_task('session', 'task', [], {})
        start_race = threading.Event()
        race_results = []
        race_lock = threading.Lock()

        def race_claim():
            start_race.wait()
            result = manager.start_task(race_task)
            with race_lock:
                race_results.append(result)

        race_threads = [threading.Thread(target=race_claim)
                        for _ in range(thread_count)]
        for thread in race_threads:
            thread.start()
        start_race.set()
        for thread in race_threads:
            thread.join()
        assert_true(len([result for result in race_results
                         if result is not None]) == 1,
                    'concurrent claimers produced more than one winner')

        work = queue.Queue()
        for task_id in task_ids:
            work.put(task_id)
        claimed = []
        claim_failures = []
        claim_lock = threading.Lock()

        def claim_worker():
            while True:
                try:
                    task_id = work.get_nowait()
                except queue.Empty:
                    return
                result = manager.start_task(task_id)
                with claim_lock:
                    if result is None:
                        claim_failures.append(task_id)
                    else:
                        claimed.append(task_id)
                work.task_done()

        workers = [threading.Thread(target=claim_worker)
                   for _ in range(thread_count)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert_true(not claim_failures, 'a healthy queued task was not claimed')
        assert_true(len(claimed) == task_count,
                    'not every live task was claimed')
        assert_true(len(set(claimed)) == task_count,
                    'a task was claimed more than once')
        assert_true(manager.get_tasks_not_started() == [],
                    'claimed tasks remained pending')

        manager.add_user('contended-session', FakeUser(), 300)
        dispose_start = threading.Event()
        dispose_results = []
        dispose_lock = threading.Lock()

        def dispose_same_session():
            dispose_start.wait()
            with app.app_context():
                result = manager.delete_user(
                    'contended-session', FakeExpiredUser())
            with dispose_lock:
                dispose_results.append(result)

        disposers = [threading.Thread(target=dispose_same_session)
                     for _ in range(thread_count)]
        for disposer in disposers:
            disposer.start()
        dispose_start.set()
        for disposer in disposers:
            disposer.join()
        assert_true(dispose_results.count(True) == 1,
                    'concurrent disposal changed the single-winner contract')
        assert_true('contended-session' not in client.smembers(
            '{}:weblab:index:v1:active_sessions'.format(key_base)),
            'disposed session remained indexed')

        run_crash_contract(redis_url, '{}:crash'.format(key_base))
        manager.client.keys = original_keys
        keys_after = command_calls(client, 'keys')
        assert_true(keys_after == keys_before,
                    'stress hot paths issued KEYS')

        return {
            'ok': True,
            'task_count': task_count,
            'claimer_threads': thread_count,
            'disposer_threads': thread_count,
            'unique_claims': len(claimed),
            'race_winners': len([result for result in race_results
                                 if result is not None]),
            'dispose_winners': dispose_results.count(True),
            'hot_path_keys_calls': keys_after - keys_before,
            'duration_seconds': round(time.time() - started_at, 3),
        }
    finally:
        cleanup_keys = client.keys('{}:*'.format(key_base))
        if cleanup_keys:
            client.delete(*cleanup_keys)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--redis-url', required=True)
    parser.add_argument('--tasks', type=int, default=10000)
    parser.add_argument('--threads', type=int, default=50)
    args = parser.parse_args()
    result = run_stress(args.redis_url, args.tasks, args.threads)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
