# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import sys
import time
import threading
import traceback

import six
import redis

from werkzeug.local import LocalProxy
from werkzeug.datastructures import ImmutableDict

from flask import g

from weblablib.utils import create_token, _current_session_id, _current_weblab

from weblablib.exc import AlreadyRunningError, TimeoutError


class _TaskWrapper(object):
    def __init__(self, weblab, func, unique):
        self._func = func
        self._unique = unique
        self._name = func.__name__
        if len(self._name) == len(create_token()):
            raise ValueError("The function '{}' has an invalid name: the number of characters "
                             "must be higher or  lower than this. Otherwise get_task(task_id) "
                             "could potentially fail".format(func.__name__))

        self._weblab = weblab
        self._backend = weblab._backend

    @property
    def func(self):
        return self._func

    @property
    def unique(self):
        return self._unique

    def __call__(self, *args, **kwargs):
        """Runs the function in the same way, directly, without catching errors"""
        session_id = None  # only used if unique='user'
        if self._unique:
            if self._unique == 'global':
                locked = self._backend.lock_global_unique_task(self._name)
                if not locked:
                    raise AlreadyRunningError("This task ({}) has been sent in parallel and it is still running".format(self._name))
            elif self._unique == 'user':
                session_id = _current_session_id()
                locked = self._backend.lock_user_unique_task(self._name, session_id)
                if not locked:
                    raise AlreadyRunningError("This task ({}) has been sent in parallel by {} and it is still running".format(self._name, session_id))
        try:
            return self._func(*args, **kwargs)
        finally:
            if self._unique:
                if self._unique == 'global':
                    self._backend.unlock_global_unique_task(self._name)
                elif self._unique == 'user':
                    self._backend.unlock_user_unique_task(self._name, session_id)

    def delay(self, *args, **kwargs):
        """
        Starts the function in a thread or in another process.
        It returns a WebLabTask object
        """
        session_id = _current_session_id()
        task_id = self._backend.new_task(session_id, self._name, args, kwargs)
        return WebLabTask(self._weblab, task_id)

#         max_times = 5 # 0.5 seconds max.
#         for x in range(max_times):
#             task_data = self._backend.get_task(task_id)
#             if task_data:
#                 return WebLabTask(self._weblab, task_id)
#             # Sometimes this is happening. Verify this is not the problem.
#             print('[{}] Task id {} of session id {} not found.'.format(time.asctime(), task_id, session_id))
#             print('[{}] Task id {} of session id {} not found.'.format(time.asctime(), task_id, session_id), file=sys.stderr)
#             all_task_ids = self._backend.get_all_tasks(session_id)
#             print('[{}] Task ids for session {}: {}.'.format(time.asctime(), session_id, all_task_ids))
#             print('[{}] Task ids for session {}: {}.'.format(time.asctime(), session_id, all_task_ids), file=sys.stderr)
#             unique_filename = '/tmp/{}-{}-{}.json'.format(session_id, x, time.time())
#             import json
#             json_contents = json.dumps(dict(args=args, kwargs=kwargs), indent=4)
#             open(unique_filename, 'w').write(json_contents)
#             print('[{}] Arguments used for session {} stored at {}.'.format(time.asctime(), session_id, unique_filename), file=sys.stdout)
#             print('[{}] Arguments used for session {} stored at {}.'.format(time.asctime(), session_id, unique_filename), file=sys.stderr)
#             sys.stdout.flush()
#             sys.stderr.flush()
#             time.sleep(0.1)
# 
#         # Regardless, raise an error
#         return WebLabTask(self._weblab, task_id)

    def run_sync(self, *args, **kwargs):
        """
        Runs the function in another thread. This is useful if for example you
        are running tasks in a single external process and you want to make sure
        that you run the method in that process. For example, take that you have
        a gunicorn server with 10 workers (10 processes). And you need to access
        a local hardware resource. You may have a single ``flask weblab loop``
        process, and configure weblablib so all the tasks are run there (by setting
        ``WEBLAB_NO_THREAD=True``). Then, in the views or in the ``on_start`` or
        ``on_dispose``, you might run:

        @weblab.task
        def my_func(a, b):
            # do something with a local resource, like a USB connection
            return a + b

        task_result = my_func.run_async(5, 6)
        print(task_result.result) # displays 11

        Internally this code is guaranteed to run in the ``loop`` process.

        :param timeout: If provided a timeout=<time in seconds>, it will wait only
                        for that time. After that, the process will continue, but
                        the ``run_async`` will finish returning the task object.
        """
        timeout = kwargs.pop('timeout', None)
        task_object = self.delay(*args, **kwargs)
        task_object.join(timeout=timeout, error_on_timeout=False)
        return task_object


class WebLabTask(object):
    """
    WebLab-Task. You can create it by defining a task as in::

        @weblab.task()
        def my_task(arg1, arg2):
            return arg1 + arg2

    And then running it::

        task = my_task.delay(5, 10)
        print(task.task_id)

    Another option is to obtain it::

        task = weblab.get_task(task_id)

    Or simply::

        tasks = weblab.tasks

    You are not supposed to create this object.

    The life cycle is very simple:

     * They all start in ``submitted`` (so :data:`WebLabTask.submitted`)
     * When a worker takes them, it is ``running`` (:data:`WebLabTask.running`)
     * The task can be finished (:data:`WebLabTask.finished`)  due to two reasons:

       * because it fails (:data:`WebLabTask.failed`), in which case you can check :data:`WebLabTask.error`.
       * or because it works (:data:`WebLabTask.done`), in which case you can check :data:`WebLabTask.result`.

    See also :meth:`WebLab.task`.
    """
    def __init__(self, weblab, task_id):
        self._weblab = weblab
        self._backend = weblab._backend
        self._task_id = task_id
        self._task_data = self._backend.get_task(task_id)
        if self._task_data is None:
            raise ValueError("task id {} not found".format(task_id))

    def join(self, timeout=None, error_on_timeout=True):
        """
        Wait for the task to finish. timeout (in seconds), if set it will raise an exception
        if error_on_timeout, otherwise it will just finish. You can't call this method from
        the task itself (a :class:`TimeoutError` will be raised).

        Be aware that if task1 starts task2 and joins, and task2 joins task1 a deadlock will happen.

        :param timeout: ``None`` (to wait forever) or number of seconds to wait. It accepts float.
        :param error_on_timeout: if ``True``, a :class:`TimeoutError` will be raised.
        """
        if current_task:
            if current_task.task_id == self._task_id:
                raise RuntimeError("Deadlock detected: you're calling join from the task itself")

        initial_time = time.time()
        while not self.retrieve().finished:
            if timeout:
                if time.time() - initial_time > timeout:
                    if error_on_timeout:
                        raise TimeoutError("{} seconds passed".format(timeout))
                    return
                time.sleep(self._weblab.join_step_time)

    @property
    def task_id(self):
        """
        Returns the task identifier.
        """
        return self._task_id

    @property
    def session_id(self):
        """
        The current ``session_id`` that represents this session.
        """
        return self._task_data['session_id']

    @property
    def name(self):
        """
        The name of the function. For example, in::

            @weblab.task()
            def my_task():
                pass

        The name would be ``my_task``.
        """
        return self._task_data['name']

    def _is_current_task(self):
        return current_task and current_task._task_id == self._task_id

    @property
    def data(self):
        """
        Dictionary that you can use to store information from outside and inside the task
        running. For example, you may call::

            @weblab.task()
            def my_task():
                # Something long, but 80%
                current_task.data['percent'] = 0.8
                current_task.sync()

            # From outside
            task = weblab.get_task(task_id)
            print(task.data.get('percent'))

        Note: every time you call ``data``, it returns a different object. Don't do::

            current_task.data['foo'] = 'bar'
        """
        if self._is_current_task():
            return self._task_data['data']

        return ImmutableDict(self._task_data['data'])

    @data.setter
    def data(self, new_data):
        if self._is_current_task():
            self._task_data['data'] = new_data
        else:
            raise ValueError("You cannot set data outside the task itself")

    def update_data(self, new_data):
        """
        .. deprecated:: 0.5.0

        Same as::

            task.data = new_data
            task.store()

        :param new_data: new data to be stored in the task data.
        """
        self.data = new_data
        self.store()

    def store(self):
        """
        Stores the current data. This can only be used from the task itself (not from outside).

        :return: the same WebLabTask (already updated)
        """
        if self._is_current_task():
            self._backend.update_task_data(self._task_id, self._task_data['data'])
            return self

        raise ValueError("You cannot store data outside the task itself")

    def retrieve(self):
        """
        Retrieves a new version of the current task (updating status, data, etc.). 

        :return: the same WebLabTask (already updated)
        """
        self._task_data = self._backend.get_task(self._task_id)
        return self

    def stop(self):
        """
        Raise a flag so :data:`WebLabTask.stopping` becomes ``True``. This method does not
        guarantee anything: it only provides a flag so the task implementor can use it to
        stop earlier or stop any loop, by reading :data:`current_task_stopping`.

        Example::

            @weblab.task()
            def read_serial():
                while not current_task_stopping:
                      data = read()
                      process(data)

            # Outside:
            task.stop() # Causing the loop to finish
        """
        self._backend.request_stop_task(self.task_id)

    @property
    def status(self):
        """
        Current status, as string:

         * ``'submitted'`` (not yet processed by a thread)
         * ``'done'`` (finished)
         * ``'failed'`` (there was an error)
         * ``'running'`` (still running in a thread)
         * ``None`` (if the task does not exist anymore)

        instead of comparing strings, you're encouraged to use:

         * :data:`WebLabTask.done`
         * :data:`WebLabTask.failed`
         * :data:`WebLabTask.running`
         * :data:`WebLabTask.submitted`
         * :data:`WebLabTask.finished` (which is is ``True`` if ``done`` or ``failed``)

        """
        return self._task_data['status']

    @property
    def done(self):
        "Has the task finished successfully?"
        return self.status == 'done'

    @property
    def running(self):
        """
        Is the task still running? Note that this is False if it was submitted and not yet started.
        If you want to know in general if it has finished or not, use :data:`WebLabTask.finished`
        """
        return self.status == 'running'

    @property
    def submitted(self):
        "Is the task submitted but not yet processed by a worker?"
        return self.status == 'submitted'

    @property
    def failed(self):
        "Has the task finished by failing?"
        return self.status == 'failed'

    @property
    def finished(self):
        """
        Has the task finished? (either right or failing)
        """
        return self.status in ('done', 'failed')

    @property
    def stopping(self):
        """
        Did anyone call :meth:`WebLabTask.stop`? If so, you should stop running the current task.
        """
        return self._task_data['stopping']

    @property
    def result(self):
        """
        In case of having finished succesfully (:data:`WebLabTask.done` being ``True``), this
        returns the result. Otherwise, it returns ``None``.
        """
        return self._task_data['result']

    @property
    def error(self):
        """
        In case of finishing with an exception (:data:`WebLabTask.failed` being ``True``), this
        returns information about the error caused. Otherwise, it returns ``None``.

        The information is provided in a dictionary as follows::

           {
              'code': 'exception',
              'class': 'ExampleError',
              'message': '<result of converting the error in string>'
           }
        """
        return self._task_data['error']

    def __repr__(self):
        """Represent a WebLab task"""
        representation = '<WebLab Task {}>'.format(self._task_id)
        if six.PY2:
            representation = representation.encode('utf8')
        return representation

    def __lt__(self, other):
        """Compare, for Python 3"""
        if isinstance(other, WebLabTask):
            return self._task_id < other._task_id

        return hash(self) < hash(other)

    def __cmp__(self, other):
        """Compare it with other object"""
        cmp = lambda a, b: (a > b) - (a < b) # pylint: disable=redefined-builtin

        if isinstance(other, WebLabTask):
            return cmp(self._task_id, other._task_id)

        return cmp(hash(self), hash(other))

    def __eq__(self, other):
        """Is it equal to other object?"""
        return isinstance(other, WebLabTask) and self._task_id == other._task_id

    def __hash__(self):
        """Calculate the hash of this task"""
        return hash(('weblabtask:', self._task_id))

class _TaskRunner(threading.Thread):

    _instances = []
    _STEPS_WAITING = 20

    def __init__(self, number, weblab, app):
        super(_TaskRunner, self).__init__()
        self.name = 'weblab-task-runner-{}'.format(number)
        self.daemon = True
        self.app = app
        self.weblab = weblab
        self._stopping = False

    def stop(self):
        self._stopping = True

    def run(self):
        _TaskRunner._instances.append(self)

        while not self._stopping:
            try:
                with self.app.app_context():
                    self.weblab.run_tasks()
            except redis.ConnectionError:
                # In the case of a redis ConnectionError, let's wait a bit more to see if
                # this happens again. It can be that we are just restarting the server
                # and Redis died before, or a Redis upgrade or so.
                traceback.print_exc()
                time.sleep(5)
            except Exception:
                traceback.print_exc()
                continue

            for _ in six.moves.range(_TaskRunner._STEPS_WAITING):
                time.sleep(0.05)
                if self._stopping:
                    break


def _current_task():
    task_id = getattr(g, '_weblab_task_id', None)
    if task_id is None:
        return None

    weblab_task = getattr(g, '_weblab_task', None)
    if weblab_task is None:
        weblab = _current_weblab()
        weblab_task = WebLabTask(weblab=weblab, task_id=task_id)
        g._weblab_task = weblab_task
    
    return weblab_task

current_task = LocalProxy(_current_task) # pylint: disable=invalid-name

def _current_task_stopping():
    task = _current_task()
    if not task:
        return False

    weblab = _current_weblab()
    updated_task_data = weblab._backend.get_task(task.task_id)
    if updated_task_data:
        return updated_task_data['stopping']

    return False

current_task_stopping = LocalProxy(_current_task_stopping) # pylint: disable=invalid-name
