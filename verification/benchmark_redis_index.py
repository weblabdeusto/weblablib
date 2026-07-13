from __future__ import unicode_literals, print_function, division

import argparse
import json
import time
import uuid

import redis

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
    timeout = 30
    _app = FakeApp()


def batched(values, size):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def delete_pattern(client, pattern):
    keys = list(client.scan_iter(match=pattern, count=1000))
    for batch in batched(keys, 1000):
        client.delete(*batch)


def seed_unrelated(client, prefix, count):
    for start in range(0, count, 1000):
        pipeline = client.pipeline(transaction=False)
        for number in range(start, min(start + 1000, count)):
            pipeline.set('{}:unrelated:{}'.format(prefix, number), '1')
        pipeline.execute()


def seed_candidates(client, key_base, kind, count, indexed, epoch):
    identifiers = ['candidate-{}'.format(number) for number in range(count)]
    for batch in batched(identifiers, 500):
        pipeline = client.pipeline(transaction=False)
        for identifier in batch:
            if kind == 'tasks':
                pipeline.set(
                    '{}:weblab:task_ids:active:{}'.format(key_base, identifier),
                    identifier)
                pipeline.hset(
                    '{}:weblab:tasks:{}'.format(key_base, identifier),
                    'name', 'task')
            else:
                session_key = '{}:weblab:active:{}'.format(
                    key_base, identifier)
                pipeline.hset(session_key, 'max_date', 2000000000)
                pipeline.hset(session_key, 'last_poll', int(time.time()))
                pipeline.hset(session_key, 'exited', 'false')
        pipeline.execute()

    if indexed:
        if kind == 'tasks':
            index_key = '{}:weblab:index:v1:pending_tasks'.format(key_base)
            other_key = '{}:weblab:index:v1:active_sessions'.format(key_base)
        else:
            index_key = '{}:weblab:index:v1:active_sessions'.format(key_base)
            other_key = '{}:weblab:index:v1:pending_tasks'.format(key_base)
        client.sadd(index_key, INDEX_SENTINEL)
        client.sadd(other_key, INDEX_SENTINEL)
        for batch in batched(identifiers, 1000):
            client.sadd(index_key, *batch)
        client.set('{}:weblab:index:v1:ready'.format(key_base), epoch)


def commandstats(client):
    raw = client.info('commandstats')
    return dict((name[len('cmdstat_'):], values)
                for name, values in raw.items()
                if name.startswith('cmdstat_'))


def cpu_usec(stats, commands=None):
    if commands is None:
        commands = [name for name in stats
                    if name not in ('info', 'config')]
    return sum(int(stats.get(name, {}).get('usec', 0)) for name in commands)


def calls(stats, command):
    return int(stats.get(command, {}).get('calls', 0))


def run_measurement(client, redis_url, key_base, kind, mode, epoch,
                    iterations, expected_count):
    manager = RedisManager(redis_url, key_base, 300, FakeWebLab(),
                           index_mode=mode,
                           index_epoch=epoch if mode != 'legacy' else None)
    client.config_resetstat()
    started_at = time.time()
    observed_count = None
    for _ in range(iterations):
        if kind == 'tasks':
            observed_count = len(manager.get_tasks_not_started())
        else:
            observed_count = len(manager.find_expired_sessions())
    elapsed = time.time() - started_at
    stats = commandstats(client)
    if observed_count != expected_count:
        raise AssertionError(
            '{} {} returned {} candidates, expected {}'.format(
                mode, kind, observed_count, expected_count))
    return {
        'iterations': iterations,
        'observed_candidates': observed_count,
        'wall_ms_per_call': round(elapsed * 1000 / iterations, 4),
        'redis_cpu_usec_per_call': round(cpu_usec(stats) / iterations, 4),
        'keys_calls': calls(stats, 'keys'),
        'keys_cpu_usec_per_call': round(
            cpu_usec(stats, ('keys',)) / iterations, 4),
        'get_smembers_cpu_usec_per_call': round(
            cpu_usec(stats, ('get', 'smembers')) / iterations, 4),
        'command_calls_per_call': round(
            sum(int(values.get('calls', 0))
                for name, values in stats.items()
                if name not in ('info', 'config')) / iterations, 4),
    }


def reduction_percent(legacy, indexed):
    if legacy <= 0:
        return 0.0
    return round((legacy - indexed) * 100.0 / legacy, 2)


def run_benchmark(redis_url, unrelated_count, candidate_counts, iterations,
                  required_reduction):
    client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
    run_id = 'weblablib-index-benchmark-{}'.format(uuid.uuid4().hex)
    epoch = 'benchmark-epoch'
    results = []
    seed_unrelated(client, run_id, unrelated_count)

    try:
        for kind in ('sessions', 'tasks'):
            for candidate_count in candidate_counts:
                legacy_base = '{}:{}:{}:legacy'.format(
                    run_id, kind, candidate_count)
                seed_candidates(client, legacy_base, kind, candidate_count,
                                False, epoch)
                legacy = run_measurement(
                    client, redis_url, legacy_base, kind, 'legacy', epoch,
                    iterations, candidate_count if kind == 'tasks' else 0)
                delete_pattern(client, '{}:*'.format(legacy_base))

                indexed_base = '{}:{}:{}:indexed'.format(
                    run_id, kind, candidate_count)
                seed_candidates(client, indexed_base, kind, candidate_count,
                                True, epoch)
                indexed = run_measurement(
                    client, redis_url, indexed_base, kind, 'indexed', epoch,
                    iterations, candidate_count if kind == 'tasks' else 0)
                delete_pattern(client, '{}:*'.format(indexed_base))

                enumeration_reduction = reduction_percent(
                    legacy['keys_cpu_usec_per_call'],
                    indexed['get_smembers_cpu_usec_per_call'])
                full_path_reduction = reduction_percent(
                    legacy['redis_cpu_usec_per_call'],
                    indexed['redis_cpu_usec_per_call'])
                results.append({
                    'kind': kind,
                    'candidates': candidate_count,
                    'legacy': legacy,
                    'indexed': indexed,
                    'enumeration_cpu_reduction_percent': enumeration_reduction,
                    'full_path_cpu_reduction_percent': full_path_reduction,
                    'passes_enumeration_target': (
                        enumeration_reduction >= required_reduction),
                })
    finally:
        delete_pattern(client, '{}:*'.format(run_id))

    failures = [result for result in results
                if not result['passes_enumeration_target'] or
                result['indexed']['keys_calls'] != 0]
    return {
        'ok': not failures,
        'redis_version': client.info('server')['redis_version'],
        'unrelated_keys': unrelated_count,
        'required_enumeration_cpu_reduction_percent': required_reduction,
        'results': results,
        'failure_count': len(failures),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--redis-url', required=True)
    parser.add_argument('--unrelated-keys', type=int, default=17600)
    parser.add_argument('--candidates', default='0,8,100,10000')
    parser.add_argument('--iterations', type=int, default=5)
    parser.add_argument('--required-reduction', type=float, default=90.0)
    args = parser.parse_args()
    candidate_counts = [int(value) for value in args.candidates.split(',')]
    result = run_benchmark(
        args.redis_url, args.unrelated_keys, candidate_counts,
        args.iterations, args.required_reduction)
    print(json.dumps(result, sort_keys=True))
    if not result['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
