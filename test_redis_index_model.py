from __future__ import unicode_literals, print_function, division

import random
import unittest

import weblablib.backends.redis_manager as redis_manager_module
from weblablib.backends.redis_manager import RedisManager
from weblablib.exc import InvalidConfigError

from test_redis_index import (BaseRedisIndexTest, CapturingLogger,
                              FakeCurrentUser, FakeExpiredUser, FakeWebLab)


class RedisIndexStateModelTest(BaseRedisIndexTest):
    def _manager_for_base(self, key_base, mode='legacy', epoch=None):
        return RedisManager(self.redis_url, key_base, 120,
                            FakeWebLab(CapturingLogger()),
                            index_mode=mode, index_epoch=epoch)

    def _operations(self):
        operations = []
        for number in range(12):
            if number < 3:
                state = 'max-date-boundary'
            elif number < 6:
                state = 'poll-boundary'
            elif number == 6:
                state = 'exited'
            else:
                state = 'healthy'
            operations.append(('add-session', 'session-{}'.format(number), state))

        for number in range(80):
            operations.append((
                'new-task', 'task-{}'.format(number),
                'session-{}'.format(number % 12)))

        randomizer = random.Random(5909)
        starts = list(range(20))
        finishes = list(range(10))
        marker_expiries = list(range(20, 25))
        randomizer.shuffle(starts)
        randomizer.shuffle(finishes)
        randomizer.shuffle(marker_expiries)
        operations.extend(('start-task', 'task-{}'.format(number))
                          for number in starts)
        operations.extend(('finish-task', 'task-{}'.format(number))
                          for number in finishes)
        operations.extend(('expire-marker', 'task-{}'.format(number))
                          for number in marker_expiries)
        operations.extend([
            ('start-task-again', 'task-0'),
            ('poll-session', 'session-3'),
            ('force-exit', 'session-8'),
            ('delete-session', 'session-0'),
            ('delete-session', 'session-7'),
            ('clean-session-tasks', 'session-4'),
            ('new-task', 'task-after-cleanup', 'session-4'),
            ('add-session', 'session-after-prepare', 'healthy'),
        ])
        return operations

    def _run_model(self, key_base, indexed):
        if indexed:
            shadow = self._manager_for_base(key_base, 'shadow', 'epoch-model')
            shadow.prepare_redis_index(scan_count=7)
            manager = self._manager_for_base(key_base, 'indexed', 'epoch-model')
        else:
            manager = self._manager_for_base(key_base)

        task_ids = {}
        task_names = {}
        trace = []

        def snapshot(operation, outcome=None):
            pending = [task_names[task_id]
                       for task_id in manager.get_tasks_not_started()]
            trace.append({
                'operation': operation,
                'outcome': outcome,
                'expired': sorted(manager.find_expired_sessions()),
                'pending': sorted(pending),
            })

        old_timestamp = redis_manager_module._current_timestamp
        redis_manager_module._current_timestamp = lambda: 1000
        try:
            for operation in self._operations():
                action = operation[0]
                outcome = None
                if action == 'add-session':
                    session_id, state = operation[1:]
                    manager.add_user(session_id, FakeCurrentUser(), 120)
                    session_key = '{}:weblab:active:{}'.format(
                        key_base, session_id)
                    if state == 'max-date-boundary':
                        manager.client.hset(session_key, 'max_date', 1000)
                    elif state == 'poll-boundary':
                        manager.client.hset(session_key, 'last_poll', 990)
                    elif state == 'exited':
                        manager.client.hset(session_key, 'exited', 'TRUE')
                elif action == 'new-task':
                    logical_name, session_id = operation[1:]
                    task_id = manager.new_task(session_id, 'task', [], {})
                    task_ids[logical_name] = task_id
                    task_names[task_id] = logical_name
                elif action == 'start-task':
                    result = manager.start_task(task_ids[operation[1]])
                    outcome = result is not None
                elif action == 'start-task-again':
                    result = manager.start_task(task_ids[operation[1]])
                    outcome = result is not None
                elif action == 'finish-task':
                    manager.finish_task(task_ids[operation[1]], result='done')
                elif action == 'expire-marker':
                    task_id = task_ids[operation[1]]
                    manager.client.delete(
                        '{}:weblab:task_ids:active:{}'.format(
                            key_base, task_id))
                elif action == 'poll-session':
                    manager.poll(operation[1])
                elif action == 'force-exit':
                    manager.force_exit(operation[1])
                elif action == 'delete-session':
                    with self.app.app_context():
                        outcome = manager.delete_user(
                            operation[1], FakeExpiredUser())
                elif action == 'clean-session-tasks':
                    manager.clean_session_tasks(operation[1])
                else:
                    self.fail('Unknown model operation {}'.format(action))
                snapshot(operation, outcome)
        finally:
            redis_manager_module._current_timestamp = old_timestamp

        return trace

    def test_indexed_mode_matches_legacy_across_healthy_state_transitions(self):
        legacy_trace = self._run_model(
            '{}:model-legacy'.format(self.key_base), indexed=False)
        indexed_trace = self._run_model(
            '{}:model-indexed'.format(self.key_base), indexed=True)
        self.assertEqual(indexed_trace, legacy_trace)

    def test_rollback_and_new_epoch_reconcile_legacy_only_writes(self):
        key_base = '{}:rollback'.format(self.key_base)
        shadow = self._manager_for_base(key_base, 'shadow', 'epoch-1')
        first_task = shadow.new_task('session', 'task', [], {})
        shadow.prepare_redis_index(scan_count=10)
        indexed = self._manager_for_base(key_base, 'indexed', 'epoch-1')
        self.assertEqual(indexed.get_tasks_not_started(), [first_task])

        legacy = self._manager_for_base(key_base)
        rollback_task = legacy.new_task('session', 'task', [], {})
        self.assertEqual(set(legacy.get_tasks_not_started()),
                         set([first_task, rollback_task]))

        shadow_new_epoch = self._manager_for_base(
            key_base, 'shadow', 'epoch-2')
        status = shadow_new_epoch.prepare_redis_index(scan_count=10)
        self.assertTrue(status['ready'])
        self.assertEqual(status['ready_epoch'], 'epoch-2')

        with self.assertRaises(InvalidConfigError):
            self._manager_for_base(key_base, 'indexed', 'epoch-1')
        indexed_new_epoch = self._manager_for_base(
            key_base, 'indexed', 'epoch-2')
        self.assertEqual(set(indexed_new_epoch.get_tasks_not_started()),
                         set([first_task, rollback_task]))


if __name__ == '__main__':
    unittest.main()
