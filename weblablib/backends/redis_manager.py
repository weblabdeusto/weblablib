# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import json
import time

import redis
from flask import current_app

from weblablib.config import ConfigurationKeys
from weblablib.utils import create_token, _current_timestamp
from weblablib.users import AnonymousUser, CurrentUser, ExpiredUser


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

    def __init__(self, redis_url, key_base, task_expires, weblab):
        self.client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
        self.weblab = weblab
        self.key_base = key_base  # Redis base prefix to use. It is *not* user or session specific.

        self.task_expires = task_expires

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
        pipeline.execute()

    def is_session_deleted(self, session_id):
        return self.client.get('{}:weblab:sessions:{}'.format(self.key_base, session_id)) is None

    def report_session_deleted(self, session_id):
        self.client.delete('{}:weblab:sessions:{}'.format(self.key_base, session_id))

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
        self.client.delete('{}:weblab:active:{}'.format(self.key_base, session_id))
        self.client.delete('{}:weblab:inactive:{}'.format(self.key_base, session_id))

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

    def find_expired_sessions(self):
        expired_sessions = []

        for active_key in self.client.keys('{}:weblab:active:*'.format(self.key_base)):
            session_id = active_key[len('{}:weblab:active:'.format(self.key_base)):]

            session_id_key = '{}:weblab:active:{}'.format(self.key_base, session_id)

            pipeline = self.client.pipeline()
            pipeline.hget(session_id_key, 'max_date')
            pipeline.hget(session_id_key, 'last_poll')
            pipeline.hget(session_id_key, 'exited')

            max_date, last_poll, exited = pipeline.execute()

            if max_date is not None and last_poll is not None: 
                # Double check: he might be deleted in the meanwhile
                # We don't use 'active', since active takes into account 'exited'

                time_left = float(max_date) - _current_timestamp()
                time_without_polling = _current_timestamp() - float(last_poll)
                user_exited = exited in ('true', '1', 'True', 'TRUE')

                if time_left <= 0:
                    expired_sessions.append(session_id)

                elif time_without_polling >= self.weblab.timeout:
                    expired_sessions.append(session_id)

                elif user_exited:
                    expired_sessions.append(session_id)

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

    def get_tasks_not_started(self):
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

        running, name, args, kwargs, session_id = pipeline.execute()
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
        pipeline.execute()
