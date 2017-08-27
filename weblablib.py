"""
weblablib
~~~~~~~~~

This library is a wrapper for developing unmanaged WebLab-Deusto remote laboratories. You may find
documentation about WebLab-Deusto at:

   https://weblabdeusto.readthedocs.org/

This library heavily relies on Flask, so if you are new to Flask, you might find very useful to
learn a bit about it first:

   http://flask.pocoo.org/

The library is designed to forget about the integration with WebLab-Deusto and make it easy. It
provides:

 * A WebLab object. You must initialize it with the app. It will include a set of new web methods
   that WebLab-Deusto uses. It also allows you to define what methods should be call on the
   beginning and end of the user session.

 * A set of methods to access information about the current information, such as ``weblab_user``,
   (which can be anonymous or not, active or not), ``requires_login`` (for methods which should
   never be used by anonymous users), ``requires_active`` (for methods which should only be
   used by users who are supposed to be using the laboratory now), ``poll`` (to report WebLab
   that the user is still active) or ``logout`` (to report WebLab that the user left).

Please, check the examples in the examples folder in the github repo.
"""

from __future__ import unicode_literals, print_function, division

import os
import abc
import sys
import json
import time
import atexit
import base64
import pickle
import datetime
import threading
import traceback
import webbrowser

from functools import wraps

import six
import redis
import click

from werkzeug import LocalProxy
from flask import Blueprint, Response, jsonify, request, current_app, redirect, \
     url_for, g, session, after_this_request, render_template, Markup, \
     has_request_context

__all__ = ['WebLab',
           'logout', 'poll',
           'weblab_user',
           'requires_login', 'requires_active',
           'CurrentUser', 'AnonymousUser', 'ExpiredUser']

class ConfigurationKeys(object):
    """
    ConfigurationKeys represents all the configuration keys available in weblablib.
    """

    # # # # # # # # # #
    #                 #
    #  Mandatory keys #
    #                 #
    # # # # # # # # # #

    #
    # WebLab-Deusto needs to be authenticated in this system.
    # So we need a pair of credentials representing the system,
    # not the particular user coming. This is what you configured
    # in WebLab-Deusto when you add the laboratory.
    #
    WEBLAB_USERNAME = 'WEBLAB_USERNAME'
    WEBLAB_PASSWORD = 'WEBLAB_PASSWORD'

    # # # # # # # # # #
    #                 #
    #  Optional keys  #
    #                 #
    # # # # # # # # # #

    # the base URL is what you want to put before the /weblab/ URLs,
    # e.g., if you want to put it in /private/weblab/ you can do that
    # (after all, even at web server level you can configure that
    # the weblab URLs are only available to WebLab-Deusto)
    WEBLAB_BASE_URL = 'WEBLAB_BASE_URL'

    # the callback URL must be a public URL where users will be
    # forwarded to. For example "/lab/callback"
    WEBLAB_CALLBACK_URL = 'WEBLAB_CALLBACK_URL'

    # This is the key used in the Flask session object.
    WEBLAB_SESSION_ID_NAME = 'WEBLAB_SESSION_ID_NAME'

    # Redis URL for storing information
    WEBLAB_REDIS_URL = 'WEBLAB_REDIS_URL'

    # Redis base. If you have more than one lab in the same Redis server,
    # you can use this variable to make it work without conflicts. By default
    # it's lab, so all the keys will be "lab:weblab:active:session-id", for example
    WEBLAB_REDIS_BASE = 'WEBLAB_REDIS_BASE'

    # How long the results of the tasks should be stored in Redis? In seconds.
    # By default one hour.
    WEBLAB_TASK_EXPIRES = 'WEBLAB_TASK_EXPIRES'

    # Number of seconds. If the user does not poll in that time, we consider
    # that he will be kicked out. Defaults to 15 seconds. It can be set
    # to -1 to disable the timeout (and therefore polling makes no sense)
    WEBLAB_TIMEOUT = 'WEBLAB_TIMEOUT'

    # Automatically poll in every method. By default it's true. So any call
    # made to any web method will automatically poll.
    WEBLAB_AUTOPOLL = 'WEBLAB_AUTOPOLL'

    # If a user doesn't have a session, you can forward him to WebLab-Deusto.
    # put the link to the WebLab-Deusto there
    WEBLAB_UNAUTHORIZED_LINK = 'WEBLAB_UNAUTHORIZED_LINK'

    # If a user doesn't have a session and you don't configure WEBLAB_UNAUTHORIZED_LINK
    # then you can put 'unauthorized.html' here, and place a 'unauthorized.html' file
    # in a 'templates' directory (see Flask documentation for details)
    WEBLAB_UNAUTHORIZED_TEMPLATE = 'WEBLAB_UNAUTHORIZED_TEMPLATE'

    # Force 'http' or 'https'
    WEBLAB_SCHEME = 'WEBLAB_SCHEME'

    # Once a user is moved to inactive, the session has to expire at some point.
    # Establish in seconds in how long (defaults to 3600, which is one hour)
    WEBLAB_EXPIRED_USERS_TIMEOUT = 'WEBLAB_EXPIRED_USERS_TIMEOUT'

    # In some rare occasions, it may happen that the dispose method is not called.
    # For example, if the Experiment server suddenly has no internet for a temporary
    # error, the user will not call logout, and WebLab-Deusto may fail to communicate
    # that the user has finished, and store that it has finished internally in
    # WebLab-Deusto. For some laboratories, it's important to be extra cautious and
    # make sure that someone calls the _dispose method. To do so, you may call
    # directly "flask clean_expired_users" manually (and cron it), or you may just
    # leave this option as True, which is the default behavior, and it will create
    # a thread that will be in a loop. If you have 10 gunicorn workers, there will
    # be 10 threads, but it shouldn't be a problem since they're synchronized with
    # Redis internally.
    WEBLAB_AUTOCLEAN_THREAD = 'WEBLAB_AUTOCLEAN_THREAD'

    # You can either call "flask run-tasks" or rely on the threads created
    # for running threads.
    WEBLAB_TASK_THREADS_PROCESS = 'WEBLAB_TASK_THREADS_PROCESS'

#############################################################
#
# WebLab-Deusto Flask extension:
#
#
#

class WebLab(object):
    """
    WebLab is a Flask extension that manages the settings (redis, session, etc.), and
    the registration of certain methods (e.g., on_start, etc.)
    """
    def __init__(self, app=None, callback_url=None, base_url=None):
        """
        Initializes the object. All the parameters are optional.

        @app: the Flask application

        @base_url: the base URL to be used. By default, the WebLab URLs will be '/weblab/sessions/<something>'.
        If You provide base_url = '/foo', then it will be listening in '/foo/weblab/sessions/<something>'.
        This is the route that will be used in the Flask application (so if your application is deployed in /bar,
        then it will be /bar/foo/weblab/sessions/<something> . This URLs do NOT need to be publicly available (they
        can be only available to WebLab-Deusto if you want, by playing with the firewall or so). You can also configure
        it with WEBLAB_BASE_URL in the Flask configuration.

        @callback_url: a URL that WebLab will implement that must be public. For example, '/mylab/callback/', this URL
        must be available to the final user. The user will be redirected there with a token and this code will redirect him
        to the initial_url. You can also configure it with WEBLAB_CALLBACK_URL in configuration.
        """
        self._app = app
        self._base_url = base_url
        self._callback_url = callback_url
        self._redis_client = None

        self.cleaner_thread_interval = 5
        self.timeout = 15 # Will be overrided by the init_app method
        self._initial_url = None
        self._session_id_name = 'weblab_session_id' # overrided by WEBLAB_SESSION_ID_NAME
        self._redirection_on_forbiden = None
        self._template_on_forbiden = None
        self._cleaner_thread = None

        self._on_start = None
        self._on_dispose = None

        self._initialized = False

        self._task_functions = {
            # func_name: _TaskWrapper
        }

        self._task_threads = []

        if app is not None:
            self.init_app(app)

    def _cleanup(self):
        old_threads = []
        for task_thread in self._task_threads:
            task_thread.stop()
            old_threads.append(task_thread)

        if self._cleaner_thread:
            self._cleaner_thread.stop()
            old_threads.append(self._cleaner_thread)

        for old_thread in old_threads:
            old_thread.join()

    def init_app(self, app):
        """
        Initialize the app. This method MUST be called (unless 'app' is provided in the constructor of WebLab)
        """
        if app is None:
            raise ValueError("app must be a Flask app")

        if self._initialized:
            if app != self._app:
                raise ValueError("Error: app already initialized with a different app!")

            if pickle.dumps(app.config) != self._app_config:
                raise ValueError("Error: app previously called with different config!")

            # Already initialized with the same app
            return

        self._app = app
        self._app_config = pickle.dumps(app.config)

        #
        # Register the extension
        #
        if 'weblab' in self._app.extensions:
            raise ValueError("Error: another WebLab extension already installed in this app!")

        self._app.extensions['weblab'] = self

        #
        # Initialize Redis Manager
        #
        redis_url = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_URL, 'redis://localhost:6379/0')
        redis_base = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_BASE, 'lab')
        task_expires = self._app.config.get(ConfigurationKeys.WEBLAB_TASK_EXPIRES, 3600)
        self._redis_manager = _RedisManager(redis_url, redis_base, task_expires, self)

        #
        # Initialize session settings
        #
        self._session_id_name = self._app.config.get(ConfigurationKeys.WEBLAB_SESSION_ID_NAME, 'weblab_session_id')
        self.timeout = self._app.config.get(ConfigurationKeys.WEBLAB_TIMEOUT, 15)
        autopoll = self._app.config.get(ConfigurationKeys.WEBLAB_AUTOPOLL, True)
        self._redirection_on_forbiden = self._app.config.get(ConfigurationKeys.WEBLAB_UNAUTHORIZED_LINK)
        self._template_on_forbiden = self._app.config.get(ConfigurationKeys.WEBLAB_UNAUTHORIZED_TEMPLATE)

        #
        # Initialize and register the "weblab" blueprint
        #
        if not self._base_url:
            self._base_url = self._app.config.get(ConfigurationKeys.WEBLAB_BASE_URL)

        if self._base_url:
            url = '{}/weblab'.format(self._base_url)
            if self._base_url.endswith('/'):
                print("Note: your base_url ({}) ends in '/'. This way, the url will be {} (with //). Are you sure that's what you want?".format(self._base_url, url), file=sys.stderr)
        else:
            url = '/weblab'

        self._app.register_blueprint(_weblab_blueprint, url_prefix=url)

        #
        # Add a callback URL
        #
        if not self._callback_url:
            self._callback_url = self._app.config.get(ConfigurationKeys.WEBLAB_CALLBACK_URL, '/callback')

        if not self._callback_url:
            raise InvalidConfigError("Empty URL. Either provide it in the constructor or in the WEBLAB_CALLBACK_URL configuration")
        elif self._callback_url.endswith('/'):
            print("Note: your callback URL ({}) ends with '/'. It is discouraged".format(self._callback_url), file=sys.stderr)

        @self._app.route(self._callback_url + '/<session_id>')
        def weblab_callback_url(session_id):
            if self._initial_url is None:
                print("ERROR: You MUST use @weblab.initial_url to point where the WebLab users should be redirected to.", file=sys.stderr)
                return "ERROR: laboratory not properly configured, didn't call @weblab.initial_url", 500

            if self._redis_manager.session_exists(session_id):
                session[self._session_id_name] = session_id
                return redirect(self._initial_url())

            return self._forbidden_handler()

        @self._app.route(self._callback_url + '/<session_id>/poll')
        def weblab_poll_url(session_id):
            if session.get(self._session_id_name) != session_id:
                return jsonify(success=False, reason="Different session identifier")

            if not self._redis_manager.session_exists(session_id):
                return jsonify(success=False, reason="Not found")

            poll()
            return jsonify(success=True)

        self._app.after_request(_update_weblab_user_data)

        #
        # Add autopoll
        #
        if autopoll:
            @self._app.after_request
            def poll_after_request(response):
                """
                Poll after every request
                """
                if hasattr(g, 'poll_requested'):
                    poll_requested = g.poll_requested
                else:
                    poll_requested = False

                # Don't poll twice: if requested manually there is another after_this_request
                if not poll_requested:
                    session_id = _current_session_id()
                    if session_id:
                        self._redis_manager.poll(session_id)

                return response

        #
        # Don't start if there are missing parameters
        #
        for key in 'WEBLAB_USERNAME', 'WEBLAB_PASSWORD':
            if key not in self._app.config:
                raise InvalidConfigError("Invalid configuration. Missing {}".format(key))

        def weblab_poll_script():
            """
            Create a HTML script that calls poll automatically.
            """
            weblab_timeout = int(1000 * self.timeout / 2)
            session_id = _current_session_id()
            if session_id:
                return Markup("""<script>
                var WEBLAB_TIMEOUT = null;
                if (window.jQuery !== undefined) {
                    WEBLAB_TIMEOUT = setInterval(function () {
                        $.get("%(url)s").done(function(result) {
                            if(!result.success)
                                clearInterval(WEBLAB_TIMEOUT);
                        }).fail(function() {
                            clearInterval(WEBLAB_TIMEOUT);
                        });
                    }, %(timeout)s )
                } else {
                    var msg = "weblablib error: jQuery not loaded BEFORE {{ weblab_poll_script() }}. Can't poll";
                    if (console && console.error) {
                        console.error(msg);
                    } else if (console && console.log) {
                        console.log(msg);
                    } else {
                        alert(msg);
                    }
                }
                </script>""" % dict(timeout=weblab_timeout, url=url_for('weblab_poll_url', session_id=session_id)))
            return Markup("<!-- session_id not found; no script -->")

        @self._app.context_processor
        def weblab_context_processor():
            return dict(weblab_poll_script=weblab_poll_script, weblab_user=weblab_user, weblab=self)

        if hasattr(app, 'cli'):
            @self._app.cli.command('clean-expired-users')
            def clean_expired_users():
                """
                Clean expired users.

                By default, a set of threads will be doing this, but you can also run it manually and
                disable the threads.
                """
                self.clean_expired_users()

            @self._app.cli.command('run-tasks')
            def run_tasks():
                """
                Run planned tasks.

                By default, a set of threads will be doing this, but you can run the tasks manually in
                external processes.
                """
                self.run_tasks()

            @self._app.cli.command('fake-new-user')
            @click.option('--name', default='John Smith', help="First and last name")
            @click.option('--username', default='john.smith', help="Username passed")
            @click.option('--username-unique', default='john.smith@institution', help="Unique username passed")
            @click.option('--assigned-time', default=300, help="Time in seconds passed to the laboratory")
            @click.option('--back', default='http://weblab.deusto.es', help="URL to send the user back")
            @click.option('--locale', default='en', help="Language")
            @click.option('--open-browser', is_flag=True, help="Open the fake use in a web browser")
            def fake_user(name, username, username_unique, assigned_time, back, locale, open_browser):
                """
                Create a fake WebLab-Deusto user session.

                This command creates a new user session and stores the session in disk, so you
                can use other commands to check its status or delete it.
                """
                assigned_time = float(assigned_time)

                start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '.0'

                request_data = {
                    'client_initial_data': {},
                    'server_initial_data': {
                        'priority.queue.slot.start': start_time,
                        'priority.queue.slot.length': assigned_time,
                        'request.username': username,
                        'request.full_name': name,
                        'request.username.unique': username_unique,
                        'request.locale': locale,
                    },
                    'back': back,
                }

                result = _process_start_request(request_data)
                if 'url' in result:
                    print()
                    print("Congratulations! The session is started")
                    print()
                    print("Open: {}".format(result['url']))
                    if not open_browser:
                        print(" (Next time, you can use --open-browser to automatically open the session in your web browser)")
                    print()
                    print("Session identifier: {}\n".format(result['session_id']))
                    open(".fake_weblab_user_session_id", 'w').write(result['session_id'])
                    print("Now you can make calls as if you were WebLab-Deusto (no argument needed):")
                    print(" - flask fake-status")
                    print(" - flask fake-dispose")
                    print()
                    if open_browser:
                        webbrowser.open(result['url'])
                else:
                    print()
                    print("Error processing request: {}".format(result['message']))
                    print()

            @self._app.cli.command('fake-status')
            def fake_status():
                """
                Check status of a fake user.

                Once you create a user with fake-new-user, you can use this command to
                simulate the status method of WebLab-Deusto and see what it would return.
                """
                if not os.path.exists('.fake_weblab_user_session_id'):
                    print("Session not found. Did you call fake-new-user first?")
                    return
                session_id = open('.fake_weblab_user_session_id').read()
                status_time = _status_time(session_id)
                print(self._redis_manager.get_user(session_id))
                print("Should finish: {}".format(status_time))

            @self._app.cli.command('fake-dispose')
            def fake_dispose():
                """
                End a session of a fake user.

                Once you create a user with fake-new-user, you can use this command to
                simulate the dispose method of WebLab-Deusto to kill the current session.
                """
                if not os.path.exists('.fake_weblab_user_session_id'):
                    print("Session not found. Did you call fake-new-user first?")
                    return
                session_id = open('.fake_weblab_user_session_id').read()
                print(self._redis_manager.get_user(session_id))
                try:
                    _dispose_user(session_id, waiting=True)
                except _NotFoundError:
                    print("Not found")
                else:
                    print("Deleted")

                if os.path.exists('.fake_weblab_user_session_id'):
                    os.remove('.fake_weblab_user_session_id')

            if not self._app.config.get('SERVER_NAME'):
                if 'fake-new-user' in sys.argv:
                    server_name = os.environ.get('SERVER_NAME')
                    default_server_name = 'localhost:5000'
                    if not server_name:
                        print(file=sys.stderr)
                        print("Note: No SERVER_NAME provided; using {!r} If you want other, run:".format(default_server_name), file=sys.stderr)
                        print("      $ export SERVER_NAME=localhost:5001", file=sys.stderr)
                        print(file=sys.stderr)
                        server_name = default_server_name

                    self._app.config['SERVER_NAME'] = server_name

        if self._app.config.get('WEBLAB_AUTOCLEAN_THREAD', True):
            self._cleaner_thread = _CleanerThread(self, self._app)
            self._cleaner_thread.start()

        threads_per_process = self._app.config.get('WEBLAB_TASK_THREADS_PROCESS', 3)
        if threads_per_process > 0: # If set to 0, no thread is running
            for number in six.moves.range(threads_per_process):
                task_thread = _TaskRunner(number, self, self._app)
                self._task_threads.append(task_thread)
                task_thread.start()

        self._initialized = True

    def _session_id(self):
        """
        Return the session identifier from the Flask session object
        """
        if hasattr(g, 'session_id'):
            return g.session_id

        if not has_request_context():
            raise NoContextError("Error: you're trying to access the session (e.g., for the WebLab session id) outside a Flask request (like a Flask command, a thread or so)")

        return session.get(self._session_id_name)

    def _set_session_id(self, session_id): #pylint: disable=no-self-use
        g.session_id = session_id

    def _forbidden_handler(self):
        if self._redirection_on_forbiden:
            return redirect(self._redirection_on_forbiden)

        if self._template_on_forbiden:
            return render_template(self._template_on_forbiden)

        return "Access forbidden", 403

    def initial_url(self, func):
        """
        This must be called. It's a decorator for establishing where the user should be redirected (the lab itself).

        Typically, this is just the url_for('index') or so in the website.
        """
        if self._initial_url is not None:
            raise ValueError("initial_url has already been defined")

        self._initial_url = func
        return func

    def on_start(self, func):
        """
        Register a method for being called when a new user comes. The format is:

        @weblab.on_start
        def start(client_data, server_data):
            return data # simple data, e.g., None, a dict, a list... that will be available as weblab_user.data

        """
        if self._on_start is not None:
            raise ValueError("on_start has already been defined")

        self._on_start = func
        return func

    def on_dispose(self, func):
        """
        Register a method for being called when a new user comes.

        @weblab.on_dispose
        def dispose():
            pass
        """
        if self._on_dispose is not None:
            raise ValueError("on_dispose has already been defined")

        self._on_dispose = func
        return func

    def clean_expired_users(self):
        """
        Typically, users are deleted by WebLab-Deusto calling the dispose method.
        However, in some conditions (e.g., restarting WebLab), the dispose method
        might not be called, and the laboratory can end in a wrong state. So as to
        avoid this, weblablib provides three systems:
        1. A command flask clean_expired_users.
        2. A thread that by default is running which calls this method every few seconds.
        3. This API method, available as: weblab.clean_expired_users()
        """
        for session_id in self._redis_manager.find_expired_sessions():
            try:
                _dispose_user(session_id, waiting=False)
            except _NotFoundError:
                pass
            except Exception:
                traceback.print_exc()


    def run_tasks(self):
        if not self._task_functions:
            # If no task was registered, simply ignore
            return

        task_ids = self._redis_manager.get_tasks_not_started()

        for task_id in task_ids:
            task_data = self._redis_manager.start_task(task_id)

            if task_data is None:
                # Someone else took the task
                continue

            func_name = task_data['name']
            args = task_data['args']
            kwargs = task_data['kwargs']
            session_id = task_data['session_id']

            func = self._task_functions.get(func_name)
            if func is None:
                self._redis_manager.finish_task(task_id, error={
                    'code': 'not-found',
                    'message': "Task {} not found".format(func_name),
                })
                continue

            self._set_session_id(session_id)
            user = self._redis_manager.get_user(session_id)
            _set_weblab_user_cache(user)
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                traceback.print_exc()
                self._redis_manager.finish_task(task_id, error={
                    'code': 'exception',
                    'class': type(error).__name__,
                    'message': '{}'.format(error),
                })
            else:
                self._redis_manager.finish_task(task_id, result=result)


    def task(self):
        """
        A task is a function that can be called later on by the WebLab wrapper. It is a set
        of threads running in the background, so you don't need to deal with it later on.

        @weblab.task()
        def function(a, b):
            return a + b

        You can either call it directly (no thread involved):

        result = function(5, 3)

        Or you can call it delayed (and it will be run in a different thread):

        task_result = function.delay(5, 3)
        task_result.task_id # The task identifier
        task_result.status # Either submitted, running, done or failed
        task_result.result # If done
        task_result.error # If failed

        Later on, you can get tasks by running:

        task_result = weblab.get_task(task_id)

        """
        #
        # In the future, weblab.task() will have other parameters, such as
        # discard_result (so the redis record is immediately discarded)
        #
        def task_wrapper(func):
            wrapper = _TaskWrapper(self, func)
            if func.__name__ in self._task_functions:
                raise ValueError("You can't have two tasks with the same name ({})".format(func.__name__))

            self._task_functions[func.__name__] = wrapper
            return wrapper

        return task_wrapper

    def get_task(self, task_id):
        """
        Given a task of the current user, return the WebLabTask object
        """
        task_data = self._redis_manager.get_task(task_id)
        if task_data:
            # Don't return tasks of other users
            if task_data['session_id'] == _current_session_id():
                return WebLabTask(self, task_data['task_id'])

    @property
    def tasks(self):
        """
        Return all the tasks created in the current session (completed or not)
        """
        session_id = _current_session_id()
        tasks = []
        for task_id in self._redis_manager.get_all_tasks(session_id):
            tasks.append(WebLabTask(self, task_id))
        return tasks

    @property
    def running_tasks(self):
        """
        Check which tasks are still running and return them.
        """
        session_id = _current_session_id()
        tasks = []
        for task_id in self._redis_manager.get_unfinished_tasks(session_id):
            tasks.append(WebLabTask(self, task_id))
        return tasks

    def create_token(self): # pylint: disable=no-self-use
        """
        Create a URL-safe random unique token in a safe way.
        """
        return _create_token()

##################################################################################################################
#
#
#
#         Public classes
#
#
#

class WebLabUser(object):
    """
    Abstract representation of a WebLabUser
    """
    __metaclass__ = abc.ABCMeta

    @abc.abstractproperty
    def active(self):
        """Is the user active right now or not?"""

    @abc.abstractproperty
    def is_anonymous(self):
        """Was the user a valid user recently?"""

    @abc.abstractmethod
    def __str__(self):
        """str representation"""

@six.python_2_unicode_compatible
class AnonymousUser(WebLabUser):
    @property
    def active(self):
        return False

    @property
    def is_anonymous(self):
        return True

    @property
    def locale(self):
        return None

    def __str__(self):
        return "Anonymous user"

@six.python_2_unicode_compatible
class CurrentUser(WebLabUser):
    """
    This class represents a user which is still actively using a laboratory. If the session expires, it will become a ExpiredUser.

    back: URL to redirect the user when finished
    last_poll: the last time the user polled. Updated every time poll() is called.
    max_date: datetime, the maximum date the user is supposed to be alive. When a new reservation comes, it states the time assigned.
    username: the simple username for the user in the final system (e.g., 'tom'). It may be repeated across different systems.
    username_unique: a unique username for the user. It is globally unique (e.g., tom@school1@labsland).
    exited: the user left the laboratory (e.g., he closed the window or a timeout happened).
    data: Serialized data (simple JSON data: dicts, list...) that can be stored for the context of the current user.
    """

    def __init__(self, session_id, back, last_poll, max_date, username, username_unique, 
                 exited, data, locale, full_name):
        self._session_id = session_id
        self._back = back
        self._last_poll = last_poll
        self._max_date = max_date
        self._username = username
        self._username_unique = username_unique
        self._exited = exited
        self._data = data
        self._locale = locale
        self._full_name = full_name

    @property
    def full_name(self):
        return self._full_name

    @property
    def locale(self):
        return self._locale

    @property
    def back(self):
        return self._back

    @property
    def last_poll(self):
        return self._last_poll

    @property
    def session_id(self):
        return self._session_id

    @property
    def max_date(self):
        return self._max_date

    @property
    def username(self):
        return self._username

    @property
    def username_unique(self):
        return self._username_unique

    @property
    def exited(self):
        return self._exited

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        redis_manager = _current_redis()
        redis_manager.update_data(self._session_id, data)
        self._data = data

    @property
    def time_without_polling(self):
        """
        Seconds without polling
        """
        return _current_timestamp() - self.last_poll

    @property
    def time_left(self):
        """
        Seconds left (0 if time passed)
        """
        return max(0, self.max_date - _current_timestamp())

    def to_expired_user(self):
        """
        Create a ExpiredUser based on the data of the user
        """
        return ExpiredUser(session_id=self._session_id, back=self._back, max_date=self._max_date, username=self._username, username_unique=self._username_unique, data=self._data, locale=self._locale, full_name=self._full_name)

    @property
    def active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return 'Current user (id: {!r}): {!r} ({!r}), last poll: {:.2f} seconds ago. Max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self.time_without_polling, self._max_date - _current_timestamp(), self._back)

@six.python_2_unicode_compatible
class ExpiredUser(WebLabUser):
    """
    This class represents a user which has been kicked out already. Typically this ExpiredUser is kept in redis for around an hour.

    All the fields are same as in User.
    """
    def __init__(self, session_id, back, max_date, username, username_unique, data, locale, full_name):
        self._session_id = session_id
        self._back = back
        self._max_date = max_date
        self._username = username
        self._username_unique = username_unique
        self._data = data
        self._locale = locale
        self._full_name = full_name

    @property
    def full_name(self):
        return self._full_name

    @property
    def locale(self):
        return self._locale

    @property
    def back(self):
        return self._back

    @property
    def session_id(self):
        return self._session_id

    @property
    def max_date(self):
        return self._max_date

    @property
    def username(self):
        return self._username

    @property
    def username_unique(self):
        return self._username_unique

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        raise NotImplementedError("You can't change data on an ExpiredUser")

    @property
    def time_left(self):
        return 0

    @property
    def active(self):
        return False

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return 'Expired user (id: {!r}): {!r} ({!r}), max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self._max_date - _current_timestamp(), self._back)

##################################################################################################################
#
#
#
#         Public functions
#
#
#

def poll():
    """
    Schedule that in the end of this call, it will update the value of the last time the user polled.
    """

    if hasattr(g, 'poll_requested'):
        poll_requested = g.poll_requested
    else:
        poll_requested = False

    if not poll_requested:
        @after_this_request
        def make_poll(response):
            session_id = _current_session_id()
            if session_id is None:
                return response

            _current_redis().poll(session_id)
            return response

        g.poll_requested = True


def _weblab_user():
    """
    Get the current user. Optionally, return the ExpiredUser if the current one expired.

    @active_only: if set to True, do not return a expired user (and None instead)
    """

    if hasattr(g, 'weblab_user'):
        return g.weblab_user

    # Cached: then use Redis
    session_id = _current_session_id()
    if session_id is None:
        return _set_weblab_user_cache(AnonymousUser())

    user = _current_redis().get_user(session_id)
    # Store it for next requests in the same call
    return _set_weblab_user_cache(user)

def _set_weblab_user_cache(user):
    g.weblab_user = user
    return user

weblab_user = LocalProxy(_weblab_user) # pylint: disable=invalid-name

def requires_login(func):
    """
    Decorator. Requires the user to be logged in (and be a current user or not).
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not weblab_user.active:
            if weblab_user.is_anonymous:
                # If anonymous user: forbidden
                return _current_weblab()._forbidden_handler()
            # Otherwise: if expired, just let it go
        return func(*args, **kwargs)
    return wrapper

def requires_active(func):
    """
    Decorator. Requires the user to be a valid current user.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not weblab_user.active:
            if weblab_user.is_anonymous:
                # If anonymous user: forbidden
                return _current_weblab()._forbidden_handler()
            # If expired: send back to the original URL
            return redirect(weblab_user.back)
        return func(*args, **kwargs)
    return wrapper

def logout():
    """
    Notify WebLab-Deusto that the user left the laboratory, so next user can enter.
    """
    session_id = _current_session_id()
    if session_id:
        _current_redis().force_exit(session_id)

##################################################################################################################
#
#
#
#         WebLab blueprint and web methods
#
#
#

_weblab_blueprint = Blueprint("weblab", __name__) # pylint: disable=invalid-name



@_weblab_blueprint.before_request
def _require_http_credentials():
    """
    All methods coming from WebLab-Deusto must be authenticated (except for /api). Here, it is used the
    WEBLAB_USERNAME and WEBLAB_PASSWORD configuration variables, which are used by WebLab-Deusto.
    Take into account that this username and password authenticate the WebLab-Deusto system, not the user.
    For example, a WebLab-Deusto in institution A might have 'institutionA' as WEBLAB_USERNAME and some
    randomly generated password as WEBLAB_PASSWORD.
    """
    # Don't require credentials in /api
    if request.url.endswith('/api'):
        return

    auth = request.authorization
    if auth:
        provided_username = auth.username
        provided_password = auth.password
    else:
        provided_username = provided_password = None

    expected_username = current_app.config[ConfigurationKeys.WEBLAB_USERNAME]
    expected_password = current_app.config[ConfigurationKeys.WEBLAB_PASSWORD]
    if provided_username != expected_username or provided_password != expected_password:
        if request.url.endswith('/test'):
            error_message = "Invalid credentials: no username provided"
            if provided_username:
                error_message = "Invalid credentials: wrong username provided. Check the lab logs for further information."
            return Response(json.dumps(dict(valid=False, error_messages=[error_message])), status=401, headers={'WWW-Authenticate':'Basic realm="Login Required"', 'Content-Type': 'application/json'})

        if expected_username:
            current_app.logger.warning("Invalid credentials provided to access {}. Username provided: {!r} (expected: {!r})".format(request.url, provided_username, expected_username))

        return Response(response=("You don't seem to be a WebLab-Instance"), status=401, headers={'WWW-Authenticate':'Basic realm="Login Required"'})



@_weblab_blueprint.route("/sessions/api")
def _api_version():
    """
    Just return the api version as defined. If in the future we support new features, they will fall under new API versions. If the report version is 1, it will only consume whatever was provided in version 1.
    """
    return jsonify(api_version="1")



@_weblab_blueprint.route("/sessions/test")
def _test():
    """
    Just return that the settings are right. For example, if the password was incorrect, then something else will fail
    """
    return jsonify(valid=True)



@_weblab_blueprint.route("/sessions/", methods=['POST'])
def _start_session():
    """
    Create a new session: WebLab-Deusto is telling us that a new user is coming. We register the user in the redis system.
    """
    request_data = request.get_json(force=True)
    return jsonify(**_process_start_request(request_data))

def _process_start_request(request_data):
    """ Auxiliar method, called also from the Flask CLI to fake_user """
    client_initial_data = request_data['client_initial_data']
    server_initial_data = request_data['server_initial_data']

    # Parse the initial date + assigned time to know the maximum time
    start_date_str = server_initial_data['priority.queue.slot.start']
    start_date_str, microseconds = start_date_str.split('.')
    difference = datetime.timedelta(microseconds=int(microseconds))
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S") + difference
    slot_length = float(server_initial_data['priority.queue.slot.length'])
    max_date = start_date + datetime.timedelta(seconds=slot_length)
    locale = server_initial_data.get('request.locale')
    full_name = server_initial_data['request.full_name']
    if locale and len(locale) > 2:
        locale = locale[:2]

    # Create a global session
    session_id = _create_token()

    # Prepare adding this to redis
    user = CurrentUser(session_id=session_id, back=request_data['back'],
                       last_poll=_current_timestamp(), max_date=float(_to_timestamp(max_date)),
                       username=server_initial_data['request.username'],
                       username_unique=server_initial_data['request.username.unique'],
                       exited=False, data={}, locale=locale,
                       full_name=full_name)

    redis_manager = _current_redis()

    redis_manager.add_user(session_id, user, expiration=30 + int(float(server_initial_data['priority.queue.slot.length'])))


    kwargs = {}
    scheme = current_app.config.get(ConfigurationKeys.WEBLAB_SCHEME)
    if scheme:
        kwargs['_scheme'] = scheme

    weblab = _current_weblab()
    if weblab._on_start:
        _set_weblab_user_cache(user)
        weblab._set_session_id(session_id)
        try:
            data = weblab._on_start(client_initial_data, server_initial_data)
        except Exception as e:
            traceback.print_exc()
            current_app.logger.warning("Error calling _on_start: {}".format(e), exc_info=True)
            try:
                _dispose_user(session_id, waiting=True)
            except Exception as e2:
                traceback.print_exc()
                current_app.logger.warning("Error calling _on_dispose after _on_start failed: {}".format(e2), exc_info=True)

            return dict(error=True, message="Error initializing laboratory")
        else:
            redis_manager.update_data(session_id, data)
            _update_weblab_user_data(None)

    link = url_for('weblab_callback_url', session_id=session_id, _external=True, **kwargs)
    return dict(url=link, session_id=session_id)



@_weblab_blueprint.route('/sessions/<session_id>/status')
def _status(session_id):
    """
    This method provides the current status of a particular
    user.
    """
    return jsonify(should_finish=_status_time(session_id))


@_weblab_blueprint.route('/sessions/<session_id>', methods=['POST'])
def _dispose_experiment(session_id):
    """
    This method is called to kick one user out. This may happen
    when an administrator defines so, or when the assigned time
    is over.
    """
    request_data = request.get_json(force=True)
    if 'action' not in request_data:
        return jsonify(message="Unknown op")

    if request_data['action'] != 'delete':
        return jsonify(message="Unknown op")

    try:
        _dispose_user(session_id, waiting=True)
    except _NotFoundError:
        return jsonify(message="Not found")

    return jsonify(message="Deleted")


######################################################################################
#
#     Redis Management
#


class _RedisManager(object):

    def __init__(self, redis_url, key_base, task_expires, weblab):
        self.client = redis.StrictRedis.from_url(redis_url, decode_responses=True)
        self.weblab = weblab
        self.key_base = key_base
        self.task_expires = task_expires

    def add_user(self, session_id, user, expiration):
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

        if max_date_active is None: # Object had been removed
            self.client.delete(key_active)

        if max_date_inactive is None: # Object had been removed
            self.client.delete(key_inactive)

    def get_user(self, session_id):
        pipeline = self.client.pipeline()
        key = '{}:weblab:active:{}'.format(self.key_base, session_id)
        for name in ('back', 'last_poll', 'max_date', 'username', 'username-unique', 'data', 
                        'exited', 'locale', 'full_name'):
            pipeline.hget(key, name)

        (back, last_poll, max_date, username, 
        username_unique, data, exited, locale, full_name) = pipeline.execute()

        if max_date is not None:
            return CurrentUser(session_id=session_id, back=back, last_poll=float(last_poll),
                               max_date=float(max_date), username=username,
                               username_unique=username_unique,
                               data=json.loads(data), exited=json.loads(exited), 
                               locale=json.loads(locale), full_name=json.loads(full_name))

        return self.get_expired_user(session_id)

    def get_expired_user(self, session_id):
        pipeline = self.client.pipeline()
        key = '{}:weblab:inactive:{}'.format(self.key_base, session_id)
        for name in 'back', 'max_date', 'username', 'username-unique', 'data', 'locale', 'full_name':
            pipeline.hget(key, name)

        back, max_date, username, username_unique, data, locale, full_name = pipeline.execute()

        if max_date is not None:
            return ExpiredUser(session_id=session_id, back=back, max_date=float(max_date),
                               username=username, username_unique=username_unique,
                               data=json.loads(data), 
                               locale=json.loads(locale),
                               full_name=json.loads(full_name))

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

        # During half an hour after being created, the user is redirected to
        # the original URL. After that, every record of the user has been deleted
        pipeline.expire("{}:weblab:inactive:{}".format(self.key_base, session_id), current_app.config.get(ConfigurationKeys.WEBLAB_EXPIRED_USERS_TIMEOUT, 3600))
        results = pipeline.execute()

        return results[0] != 0 # If redis returns 0 on delete() it means that it was not deleted

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
            user = self.get_user(session_id)
            if user.active: # Double check: he might be deleted in the meanwhile
                if user.time_left <= 0:
                    expired_sessions.append(session_id)

                elif user.time_without_polling >= self.weblab.timeout:
                    expired_sessions.append(session_id)

                elif user.exited:
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
    # Task-related Redis methods
    #
    def new_task(self, session_id, name, args, kwargs):
        """
        Get a new function, args and kwargs, and return the task_id.
        """
        task_id = _create_token()
        while True:
            pipeline = self.client.pipeline()
            pipeline.set('{}:weblab:task_ids:{}'.format(self.key_base, task_id), task_id)
            pipeline.expire('{}:weblab:task_ids:{}'.format(self.key_base, task_id), self.task_expires)
            results = pipeline.execute()

            if results[0]:
                # Ensure it's unique
                break

            # Otherwise try with another
            task_id = _create_token()

        pipeline = self.client.pipeline()
        pipeline.sadd('{}:weblab:{}:tasks'.format(self.key_base, session_id), task_id)
        pipeline.expire('{}:weblab:{}:tasks'.format(self.key_base, session_id), self.task_expires)
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'name', name)
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'session_id', session_id)
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'args', json.dumps(args))
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'kwargs', json.dumps(kwargs))
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'finished', 'false')
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'error', 'null')
        pipeline.hset('{}:weblab:tasks:{}'.format(self.key_base, task_id), 'result', 'null')
        # Missing (normal): running. When created, we know if it's a new key and therefore that
        # no other thread is processing it.
        pipeline.execute()
        return task_id

    def get_tasks_not_started(self):
        task_ids = [key[len('{}:weblab:task_ids:'.format(self.key_base)):]
                    for key in self.client.keys('{}:weblab:task_ids:*'.format(self.key_base))]

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

    def get_task(self, task_id):
        key = '{}:weblab:tasks:{}'.format(self.key_base, task_id)

        pipeline = self.client.pipeline()
        pipeline.hget(key, 'session_id')
        pipeline.hget(key, 'finished')
        pipeline.hget(key, 'error')
        pipeline.hget(key, 'result')
        pipeline.hget(key, 'running')
        pipeline.hget(key, 'name')
        session_id, finished, error_str, result_str, running, name = pipeline.execute()

        if session_id is None:
            return None

        error = json.loads(error_str)
        result = json.loads(result_str)

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
            if finished == 'false': # If finished or failed: true; if expired: None
                pending_task_ids.append(task_id)

        return pending_task_ids

    def clean_session_tasks(self, session_id):
        task_ids = self.client.smembers('{}:weblab:{}:tasks'.format(self.key_base, session_id))

        pipeline = self.client.pipeline()
        pipeline.delete('{}:weblab:{}:tasks'.format(self.key_base, session_id))
        for task_id in task_ids:
            pipeline.delete('{}:weblab:tasks:{}'.format(self.key_base, task_id))
            pipeline.delete('{}:weblab:task_ids:{}'.format(self.key_base, task_id))
        pipeline.execute()

#####################################################################################
#
#   Exceptions
#

class WebLabError(Exception):
    """Wraps weblab exceptions"""
    pass

class NoContextError(WebLabError):
    """Wraps the fact that it is attempting to call an object like
    session outside the proper scope."""
    pass

class InvalidConfigError(WebLabError, ValueError):
    """Invalid configuration"""
    pass

class WebLabNotInitializedError(WebLabError):
    pass

class _NotFoundError(WebLabError, KeyError):
    pass

######################################################################################
#
#
#     Task management
#

class _TaskWrapper(object):
    def __init__(self, weblab, func):
        self._func = func
        self._name = func.__name__
        self._weblab = weblab
        self._redis_manager = weblab._redis_manager

    def __call__(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    def delay(self, *args, **kwargs):
        session_id = _current_session_id()
        task_id = self._redis_manager.new_task(session_id, self._name, args, kwargs)
        return WebLabTask(self._weblab, task_id)

class WebLabTask(object):
    """
    WebLab-Task. You can create it by defining a task as in:

    @weblab.task()
    def my_task(arg1, arg2):
        return arg1 + arg2

    And then running it:

    task = my_task.delay(5, 10)
    print(task.task_id)

    Another option is to obtain it:

    task = weblab.get_task(task_id)

    Or simply:

    tasks = weblab.get_tasks()
    """
    def __init__(self, weblab, task_id):
        self._weblab = weblab
        self._redis_manager = weblab._redis_manager
        self._task_id = task_id

    @property
    def task_id(self):
        """
        Returns the task identifier.
        """
        return self._task_id

    @property
    def _task_data(self):
        return self._redis_manager.get_task(self._task_id)

    @property
    def session_id(self):
        task_data = self._task_data
        if task_data:
            return task_data['session_id']

    @property
    def name(self):
        task_data = self._task_data
        if task_data:
            return task_data['name']

    @property
    def status(self):
        """
        Current status:
         - submitted (not yet processed by a thread)
         - done (finished)
         - failed (there was an error)
         - running (still running in a thread)
         - None (if the task does not exist anymore)
        """
        task_data = self._task_data
        if task_data:
            return task_data['status']

    @property
    def result(self):
        """
        In case of finishing (task.status == 'done'), this returns the result.
        Otherwise, it returns None.
        """
        task_data = self._task_data
        if task_data:
            return task_data['result']

    @property
    def error(self):
        """
        In case of error (task.status == 'failed'), this returns the Exception
        that caused the error. Otherwise, it returns None.
        """
        task_data = self._task_data
        if task_data:
            return task_data['error']

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
        cmp = lambda a, b: (a > b) - (a < b)

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

            except Exception:
                traceback.print_exc()
                continue

            for _ in six.moves.range(20):
                time.sleep(0.05)
                if self._stopping:
                    break


######################################################################################
#
#
#     Auxiliar private functions
#
#

def _current_weblab():
    if 'weblab' not in current_app.extensions:
        raise WebLabNotInitializedError("App not initialized with weblab.init_app()")
    return current_app.extensions['weblab']

def _current_redis():
    return _current_weblab()._redis_manager

def _current_session_id():
    return _current_weblab()._session_id()

def _to_timestamp(dtime):
    return str(int(time.mktime(dtime.timetuple()))) + str(dtime.microsecond / 1e6)[1:]

def _current_timestamp():
    return float(_to_timestamp(datetime.datetime.now()))

def _create_token():
    tok = os.urandom(32)
    safe_token = base64.urlsafe_b64encode(tok).strip().replace(b'=', b'').replace(b'-', b'_')
    safe_token = safe_token.decode('utf8')
    return safe_token

def _status_time(session_id):
    weblab = _current_weblab()
    redis_manager = weblab._redis_manager
    user = redis_manager.get_user(session_id)
    if user.is_anonymous or not user.active:
        return -1

    if user.exited:
        return -1

    if weblab.timeout and weblab.timeout > 0:
        # If timeout is set to -1, it will never timeout (unless user exited)
        if user.time_without_polling >= weblab.timeout:
            return -1

    if user.time_left <= 0:
        return -1

    return min(5, int(user.time_left))

def _update_weblab_user_data(response):
    # If a developer does:
    #
    # weblab_user.data["foo"] = "bar"
    #
    # Nothing is triggered in Redis. For this reason, after each request
    # we check that the data has changed or not.
    #
    session_id = _current_session_id()
    redis_manager = _current_redis()
    if session_id:
        if weblab_user.active:
            current_user = redis_manager.get_user(session_id)
            if current_user.active:
                if json.dumps(current_user.data) != weblab_user.data:
                    redis_manager.update_data(session_id, weblab_user.data)

    return response


def _dispose_user(session_id, waiting):
    redis_manager = _current_redis()
    user = redis_manager.get_user(session_id)
    if user.is_anonymous:
        raise _NotFoundError()

    if user.active:
        current_expired_user = user.to_expired_user()
        deleted = redis_manager.delete_user(session_id, current_expired_user)

        if deleted:
            weblab = _current_weblab()
            if weblab._on_dispose:
                weblab._set_session_id(session_id)
                _set_weblab_user_cache(user)
                try:
                    weblab._on_dispose()
                except Exception:
                    traceback.print_exc()
                _update_weblab_user_data(None)

            unfinished_tasks = redis_manager.get_unfinished_tasks(session_id)
            while unfinished_tasks:
                unfinished_tasks = redis_manager.get_unfinished_tasks(session_id)
                time.sleep(0.1)

            redis_manager.clean_session_tasks(session_id)

            redis_manager.report_session_deleted(session_id)

    if waiting:
        # if another thread has started the _dispose process, it might take long
        # to process it. But this (sessions) is the one that tells WebLab-Deusto
        # that someone else can enter in this laboratory. So we should wait
        # here until the process is over.

        while not redis_manager.is_session_deleted(session_id):
            # In the future, instead of waiting, this could be returning that it is still finishing
            time.sleep(0.1)


class _CleanerThread(threading.Thread):
    """
    _CleanerThread is a thread that keeps calling the _clean_expired_users. It is optional, activated with WEBLAB_AUTOCLEAN_THREAD
    """

    _instances = []

    def __init__(self, weblab, app):
        super(_CleanerThread, self).__init__()
        self.app = app
        self.name = "WebLabCleaner"
        self.weblab = weblab
        self.daemon = True
        self._stopping = False

    def stop(self):
        self._stopping = True

    def run(self):
        _CleanerThread._instances.append(self)

        while not self._stopping:
            try:
                with self.app.app_context():
                    self.weblab.clean_expired_users()
            except Exception:
                traceback.print_exc()

            t0 = time.time()
            while True:
                time.sleep(0.05)
                if time.time() -  t0 > self.weblab.cleaner_thread_interval:
                    break

                if self._stopping:
                    break


def _cleanup_all():
    all_threads = _CleanerThread._instances + _TaskRunner._instances

    for instance in all_threads:
        instance.stop()

    for instance in all_threads:
        instance.join()

@atexit.register
def _on_exit():
    _cleanup_all()
