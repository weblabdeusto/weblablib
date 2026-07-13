from __future__ import unicode_literals, print_function, division

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid

import redis
from flask import Flask

import weblablib
from weblablib.backends.redis_manager import RedisManager


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
    max_date = 1
    last_poll = 1
    username = 'mixed-version-user'
    username_unique = 'mixed-version-user@example.invalid'
    data = {}
    back = 'https://example.invalid/back'
    exited = False
    locale = 'en'
    full_name = 'Mixed Version User'
    experiment_name = 'mixed-version'
    category_name = 'test'
    experiment_id = 'mixed-version@test'
    start_date = 1
    request_client_data = {}
    request_server_data = {}


class FakeExpiredUser(FakeUser):
    pass


def manager(redis_url, key_base, mode, epoch):
    if mode == 'legacy':
        return RedisManager(redis_url, key_base, 300, FakeWebLab())
    return RedisManager(redis_url, key_base, 300, FakeWebLab(),
                        index_mode=mode, index_epoch=epoch)


def worker(args):
    backend = manager(args.redis_url, args.key_base, args.mode, args.epoch)
    result = {'version': weblablib.__version__}

    if args.action == 'create':
        session_id = 'session-{}'.format(args.label)
        backend.add_user(session_id, FakeUser(), 300)
        result.update({
            'session_id': session_id,
            'task_id': backend.new_task(session_id, args.label, [], {}),
        })
    elif args.action == 'list':
        result.update({
            'tasks': sorted(backend.get_tasks_not_started()),
            'expired_sessions': sorted(backend.find_expired_sessions()),
        })
    elif args.action == 'claim':
        result['claimed'] = backend.start_task(args.task_id) is not None
    elif args.action == 'delete-session':
        app = Flask(__name__)
        app.config['WEBLAB_EXPIRED_USERS_TIMEOUT'] = 300
        with app.app_context():
            result['deleted'] = backend.delete_user(
                args.session_id, FakeExpiredUser())
    elif args.action == 'prepare':
        result['status'] = backend.prepare_redis_index(scan_count=25)
    else:
        raise ValueError('Unknown worker action {}'.format(args.action))
    print(json.dumps(result, sort_keys=True))


def run_process(python, script, source, common_args, action, mode='legacy',
                epoch=None, old=False, **fields):
    command = [python, script, '--worker', '--action', action,
               '--mode', mode] + common_args
    if epoch is not None:
        command.extend(['--epoch', epoch])
    for name, value in fields.items():
        command.extend(['--{}'.format(name.replace('_', '-')), value])

    environment = os.environ.copy()
    if old:
        environment.pop('PYTHONPATH', None)
    else:
        environment['PYTHONPATH'] = source
    output = subprocess.check_output(
        command, cwd=tempfile.gettempdir(), env=environment)
    if not isinstance(output, str):
        output = output.decode('utf-8')
    return json.loads(output)


def assert_equal(actual, expected, message):
    if actual != expected:
        raise AssertionError('{}: expected {!r}, got {!r}'.format(
            message, expected, actual))


def run_parent(args):
    args.old_python = os.path.abspath(args.old_python)
    args.new_python = os.path.abspath(args.new_python)
    args.source = os.path.abspath(args.source)
    key_base = 'weblablib-mixed-version-{}'.format(uuid.uuid4().hex)
    client = redis.StrictRedis.from_url(args.redis_url, decode_responses=True)
    script = os.path.abspath(__file__)
    common_args = ['--redis-url', args.redis_url, '--key-base', key_base]

    def old(action, **fields):
        return run_process(args.old_python, script, args.source, common_args,
                           action, old=True, **fields)

    def new(action, mode, epoch, **fields):
        return run_process(args.new_python, script, args.source, common_args,
                           action, mode=mode, epoch=epoch, **fields)

    try:
        old_created = old('create', label='old')
        assert_equal(old_created['version'], '0.5.8',
                     'old subprocess package version')

        shadow_list = new('list', 'shadow', 'epoch-1')
        assert_equal(shadow_list['tasks'], [old_created['task_id']],
                     'shadow reader visibility of old writer')

        new_created = new('create', 'shadow', 'epoch-1', label='new')
        old_list = old('list')
        assert_equal(set(old_list['tasks']),
                     set([old_created['task_id'], new_created['task_id']]),
                     'old reader visibility of new writer')

        prepared = new('prepare', 'shadow', 'epoch-1')
        assert_equal(prepared['status']['ready'], True,
                     'epoch-1 preparation readiness')
        indexed_list = new('list', 'indexed', 'epoch-1')
        assert_equal(set(indexed_list['tasks']),
                     set([old_created['task_id'], new_created['task_id']]),
                     'indexed visibility after mixed-version backfill')

        old_claim = old('claim', task_id=new_created['task_id'])
        assert_equal(old_claim['claimed'], True,
                     'old worker claim of new task')
        indexed_after_old_claim = new('list', 'indexed', 'epoch-1')
        assert_equal(indexed_after_old_claim['tasks'],
                     [old_created['task_id']],
                     'indexed pruning after old worker claim')

        indexed_created = new(
            'create', 'indexed', 'epoch-1', label='indexed')
        old_after_indexed_write = old('list')
        assert_equal(set(old_after_indexed_write['tasks']),
                     set([old_created['task_id'], indexed_created['task_id']]),
                     'old reader visibility of indexed writer')
        old_indexed_claim = old(
            'claim', task_id=indexed_created['task_id'])
        assert_equal(old_indexed_claim['claimed'], True,
                     'old worker claim of indexed task')

        old_delete = old(
            'delete-session', session_id=new_created['session_id'])
        assert_equal(old_delete['deleted'], True,
                     'old disposer deletion of new session')
        indexed_after_delete = new('list', 'indexed', 'epoch-1')
        if new_created['session_id'] in indexed_after_delete['expired_sessions']:
            raise AssertionError('old-disposed session remained indexed')

        rollback_created = old('create', label='rollback')
        rollback_legacy = old('list')
        assert_equal(set(rollback_legacy['tasks']),
                     set([old_created['task_id'],
                          rollback_created['task_id']]),
                     'legacy rollback visibility')
        shadow_epoch_two = new('list', 'shadow', 'epoch-2')
        assert_equal(set(shadow_epoch_two['tasks']),
                     set(rollback_legacy['tasks']),
                     'new-epoch shadow legacy authority')

        prepared_epoch_two = new('prepare', 'shadow', 'epoch-2')
        assert_equal(prepared_epoch_two['status']['ready'], True,
                     'epoch-2 preparation readiness')
        indexed_epoch_two = new('list', 'indexed', 'epoch-2')
        assert_equal(set(indexed_epoch_two['tasks']),
                     set(rollback_legacy['tasks']),
                     'new-epoch reconciliation of rollback writes')
        final_old_list = old('list')
        assert_equal(set(final_old_list['tasks']),
                     set(indexed_epoch_two['tasks']),
                     'final old/new reader parity')

        return {
            'ok': True,
            'old_version': old_created['version'],
            'new_version': indexed_epoch_two['version'],
            'epoch_1_ready': prepared['status']['ready'],
            'epoch_2_ready': prepared_epoch_two['status']['ready'],
            'old_reader_new_writer': True,
            'new_reader_old_writer': True,
            'old_worker_new_task': True,
            'old_disposer_new_session': True,
            'rollback_reconciled': True,
        }
    finally:
        keys = client.keys('{}:*'.format(key_base))
        if keys:
            client.delete(*keys)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--redis-url', required=True)
    parser.add_argument('--key-base')
    parser.add_argument('--old-python')
    parser.add_argument('--new-python', default=sys.executable)
    parser.add_argument('--source', default=os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--action', choices=(
        'create', 'list', 'claim', 'delete-session', 'prepare'))
    parser.add_argument('--mode', default='legacy')
    parser.add_argument('--epoch')
    parser.add_argument('--label')
    parser.add_argument('--task-id')
    parser.add_argument('--session-id')
    args = parser.parse_args()
    if not args.worker and not args.old_python:
        parser.error('--old-python is required in parent mode')
    return args


def main():
    args = parse_args()
    if args.worker:
        worker(args)
    else:
        print(json.dumps(run_parent(args), sort_keys=True))


if __name__ == '__main__':
    main()
