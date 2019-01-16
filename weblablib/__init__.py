"""
weblablib
~~~~~~~~~

This library is a wrapper for developing unmanaged WebLab-Deusto remote laboratories. You may find
documentation about WebLab-Deusto at:

   https://weblabdeusto.readthedocs.org/

And the documentation on weblablib at:

   https://docs.labsland.com/weblablib/

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

# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import os
import abc
import sys
import json
import time
import atexit
import base64
import pickle
import signal
import datetime
import threading
import traceback
import webbrowser

from functools import wraps

import six
import redis
import click
import requests

from werkzeug import LocalProxy, ImmutableDict
from flask import Blueprint, Response, jsonify, request, current_app, redirect, \
     url_for, g, session, after_this_request, render_template, Markup, \
     has_request_context, has_app_context

from weblablib.exc import WebLabError, NoContextError, InvalidConfigError, \
     WebLabNotInitializedError, TimeoutError, AlreadyRunningError, \
     NotFoundError

from weblablib.utils import create_token, _current_weblab, _current_backend, \
     _current_session_id, _to_timestamp, _current_timestamp

from weblablib.config import ConfigurationKeys
from weblablib.users import WebLabUser, AnonymousUser, ExpiredUser, CurrentUser

from weblablib.backends import RedisManager

try:
    from flask_socketio import disconnect as socketio_disconnect
except ImportError:
    _FLASK_SOCKETIO = False
    _FLASK_SOCKETIO_IMPORT_ERROR = traceback.format_exc()
else:
    _FLASK_SOCKETIO = True
    _FLASK_SOCKETIO_IMPORT_ERROR = None

__all__ = ['WebLab',
           'logout', 'poll',
           'weblab_user', 'get_weblab_user', 'socket_weblab_user',
           'requires_login', 'requires_active',
           'socket_requires_login', 'socket_requires_active',
           'current_task', 'current_task_stopping', 'WebLabTask',
           'WebLabError', 'NoContextError', 'InvalidConfigError',
           'WebLabNotInitializedError', 'TimeoutError',
           'AlreadyRunningError', 'CurrentUser', 'AnonymousUser',
           'ExpiredUser']

__version__ = '0.5'
__license__ = 'GNU Affero General Public License v3 http://www.gnu.org/licenses/agpl.html'


#############################################################
#
# WebLab-Deusto Flask extension:
#
#
#

class WebLab(object):
    """
    WebLab is a Flask extension that manages the settings (backend, session, etc.), and
    the registration of certain methods (e.g., on_start, etc.)

    Initializes the object. All the parameters are optional.

    :param app: the Flask application

    :param base_url: the base URL to be used. By default, the WebLab URLs will be
                     ``/weblab/sessions/<something>``.  If you provide ``base_url = '/foo'``, then
                     it will be listening in ``/foo/weblab/sessions/<something>``. This is the
                     route that will be used in the Flask application (so if your application
                     is deployed in ``/bar``, then it will be
                     ``/bar/foo/weblab/sessions/<something>``. This URLs do NOT need to be
                     publicly available (they can be only available to WebLab-Deusto if you
                     want, by playing with the firewall or so). You can also configure it with
                     ``WEBLAB_BASE_URL`` in the Flask configuration.

    :param callback_url: a URL that WebLab will implement that must be public. For example,
                         ``/mylab/callback/``, this URL must be available to the final user.
                         The user will be redirected there with a token and this code will
                         redirect him to the initial_url. You can also configure it with
                         ``WEBLAB_CALLBACK_URL`` in configuration.
    """

    def __init__(self, app=None, callback_url=None, base_url=None, backend=None):
        self._app = app
        self._base_url = base_url
        self._callback_url = callback_url
        self._backend = backend

        self.poll_interval = 5
        self.cleaner_thread_interval = 5
        self.timeout = 15 # Will be overrided by the init_app method
        self.join_step_time = 0.05 # Default value, when calling task.join() how long it should wait.
        # Advanced developers can modify this on real time.
        self._initial_url = None
        self._session_id_name = 'weblab_session_id' # overrided by WEBLAB_SESSION_ID_NAME
        self._redirection_on_forbiden = None
        self._template_on_forbiden = None
        self._cleaner_thread = None
        self._user_loader = None

        self._on_start = None
        self._on_dispose = None

        self._initialized = False

        self._task_functions = {
            # func_name: _TaskWrapper
        }

        self._task_threads = []
        self._stopping = False

        if app is not None:
            self.init_app(app)

    def _cleanup(self):
        self._stopping = True
        old_threads = []
        for task_thread in self._task_threads:
            task_thread.stop()
            old_threads.append(task_thread)

        if self._cleaner_thread:
            self._cleaner_thread.stop()
            old_threads.append(self._cleaner_thread)

        for old_thread in old_threads:
            old_thread.join()

    def init_app(self, app, backend=None):
        """
        Initialize the app. This method MUST be called (unless 'app' is provided in the
        constructor of WebLab; then it's called in that moment internally). Most configuration
        variables are taken here (so changing ``app.config`` afterwards will not affect
        ``WebLab``).
        """
        if app is None:
            raise ValueError("app must be a Flask app")

        if self._initialized:
            if app != self._app:
                raise ValueError("Error: app already initialized with a different app!")

            if pickle.dumps(app.config) != self._app_config: # pylint: disable=access-member-before-definition
                raise ValueError("Error: app previously called with different config!")

            # Already initialized with the same app
            return

        if self._backend is None and backend:
            self._backend = backend

        self._app = app
        self._app_config = pickle.dumps(app.config)

        #
        # Register the extension
        #
        if 'weblab' in self._app.extensions:
            raise ValueError("Error: another WebLab extension already installed in this app!")

        self._app.extensions['weblab'] = self

        #
        # Initialize the backend. Defaults to RedisManager
        #

        if self._backend is None:
            redis_url = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_URL, 'redis://localhost:6379/0')
            redis_base = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_BASE, 'lab')
            task_expires = self._app.config.get(ConfigurationKeys.WEBLAB_TASK_EXPIRES, 3600)
            self._backend = RedisManager(redis_url, redis_base, task_expires, self)

        #
        # Initialize session settings
        #
        self._session_id_name = self._app.config.get(ConfigurationKeys.WEBLAB_SESSION_ID_NAME, 'weblab_session_id')
        self.timeout = self._app.config.get(ConfigurationKeys.WEBLAB_TIMEOUT, 15)
        self.poll_interval = self._app.config.get(ConfigurationKeys.WEBLAB_POLL_INTERVAL, 5)
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

        doc_link = 'https://docs.labsland.com/weblablib/'

        @self._app.route(self._callback_url + '/<session_id>')
        def weblab_callback_url(session_id):
            if self._initial_url is None:
                print("ERROR: You MUST use @weblab.initial_url to point where the WebLab users should be redirected to.", file=sys.stderr)
                print("Check the documentation: {}.".format(doc_link), file=sys.stderr)
                return "ERROR: laboratory not properly configured, didn't call @weblab.initial_url", 500

            if self._backend.session_exists(session_id):
                session[self._session_id_name] = session_id
                return redirect(self._initial_url())

            return self._forbidden_handler()

        @self._app.route(self._callback_url + '/<session_id>/poll')
        def weblab_poll_url(session_id):
            if session.get(self._session_id_name) != session_id:
                return jsonify(success=False, reason="Different session identifier")

            if not self._backend.session_exists(session_id):
                return jsonify(success=False, reason="Not found")

            if not weblab_user.active:
                return jsonify(success=False, reason="User inactive")

            poll()
            return jsonify(success=True)

        @self._app.route(self._callback_url + '/<session_id>/logout')
        def weblab_logout_url(session_id):
            # CSRF would be useful; but we don't really need it in this case
            # given that the session_id is already secret, random and unique.
            if session.get(self._session_id_name) != session_id:
                return jsonify(success=False, reason="Different session identifier")
            logout()
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
                        self._backend.poll(session_id)

                return response

        #
        # Don't start if there are missing parameters
        #
        for key in 'WEBLAB_USERNAME', 'WEBLAB_PASSWORD':
            if key not in self._app.config:
                raise InvalidConfigError("Invalid configuration. Missing {}".format(key))

        def weblab_poll_script(logout_on_close=False, callback=None):
            """
            Create a HTML script that calls poll automatically.
            """
            if self.timeout <= 0:
                return Markup("<!-- timeout is 0 or negative; no script -->")

            weblab_timeout = int(1000 * self.timeout / 2)
            session_id = _current_session_id()
            if not session_id:
                return Markup("<!-- session_id not found; no script -->")

            if logout_on_close:
                logout_code = """
                $(window).bind("beforeunload", function() {
                    $.get("%(url)s");
                });
                """ % dict(url=url_for('weblab_logout_url', session_id=session_id))
            else:
                logout_code = ""

            if callback:
                callback_code = "{}();".format(callback)
            else:
                callback_code = ""

            return Markup("""<script>
                var WEBLAB_TIMEOUT = null;
                var WEBLAB_RETRIES = 3;
                if (window.jQuery !== undefined) {
                    var WEBLAB_INTERVAL_FUNCTION = function(){
                        $.get("%(url)s").done(function(result) {
                            if(!result.success) {
                                clearInterval(WEBLAB_TIMEOUT);
                                %(callback_code)s
                            } else {
                                WEBLAB_RETRIES = 3;
                            }
                        }).fail(function(errorData) {
                            if (WEBLAB_RETRIES > 0 && (errorData.status == 502 || errorData.status == 503)) {
                                WEBLAB_RETRIES -= 1;
                                setTimeout(WEBLAB_INTERVAL_FUNCTION, 1500); // Force a try-again in 1.5 seconds
                            } else {
                                clearInterval(WEBLAB_TIMEOUT);
                                %(callback_code)s
                            }
                        });
                    }
                    WEBLAB_TIMEOUT = setInterval(WEBLAB_INTERVAL_FUNCTION, %(timeout)s );
                    %(logout_code)s
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
                </script>""" % dict(timeout=weblab_timeout, url=url_for('weblab_poll_url', session_id=session_id),
                                    logout_code=logout_code, callback_code=callback_code))


        @self._app.context_processor
        def weblab_context_processor():
            return dict(weblab_poll_script=weblab_poll_script, weblab_user=weblab_user, weblab=self)

        @self._app.after_request
        def after_request(response):
            response.headers['powered-by'] = doc_link
            return response

        click.disable_unicode_literals_warning = True
        @app.cli.group('weblab')
        def weblab_cli():
            """WebLab-Deusto related operations: initialize new sessions for development, run tasks, etc."""
            pass

        @weblab_cli.command('clean-expired-users')
        def clean_expired_users():
            """
            Clean expired users.

            By default, a set of threads will be doing this, but you can also run it manually and
            disable the threads.
            """
            self.clean_expired_users()

        @weblab_cli.command('run-tasks')
        def run_tasks():
            """
            Run planned tasks.

            By default, a set of threads will be doing this, but you can run the tasks manually in
            external processes.
            """
            self.run_tasks()

        @weblab_cli.command('loop')
        @click.option('--threads', default=5, help="Number of threads")
        @click.option('--reload/--no-reload', default=None, help="Reload as code changes. Defaults to whether the app is in FLASK_DEBUG mode")
        def loop(threads, reload): # pylint: disable=redefined-builtin
            """
            Run planned tasks and clean expired users, permanently.
            """
            if reload is None:
                reload = current_app.debug

            def run_loop():
                if reload:
                    print("Running with reloader. Don't use this in production mode.")
                self.loop(int(threads), reload)

            if reload:
                from werkzeug.serving import run_with_reloader
                run_with_reloader(run_loop)
            else:
                run_loop()

        @weblab_cli.group()
        def fake():
            """Fake user management.

            With this interface, you can test your laboratory without WebLab-Deusto. It implements the same
            methods used by WebLab-Deusto (create new user, check status, kick out user), from a command
            line interface. The "new" command has several parameters for changing language, user name, etc.
            """
            pass

        def _weblab_api_request(url_name, json_data, session_id=None):
            if session_id:
                url = url_for(url_name, session_id=session_id, _external=True)
            else:
                url = url_for(url_name, _external=True)
            weblab_username = current_app.config.get('WEBLAB_USERNAME')
            weblab_password = current_app.config.get('WEBLAB_PASSWORD')
            response = requests.post(url, json=json_data, auth=(weblab_username, weblab_password))
            return response.json()

        @fake.command('new')
        @click.option('--name', default='John Smith', help="First and last name")
        @click.option('--username', default='john.smith', help="Username passed")
        @click.option('--username-unique', default='john.smith@institution', help="Unique username passed")
        @click.option('--assigned-time', default=300, help="Time in seconds passed to the laboratory")
        @click.option('--back', default='http://weblab.deusto.es', help="URL to send the user back")
        @click.option('--locale', default='en', help="Language")
        @click.option('--experiment-name', default='mylab', help="Experiment name")
        @click.option('--category-name', default='Lab Experiments', help="Category name (of the experiment)")
        @click.option('--dont-open-browser', is_flag=True, help="Do not open the fake user in a web browser")
        def fake_user(name, username, username_unique, assigned_time, back, locale, experiment_name, category_name, dont_open_browser):
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
                    'request.experiment_id.experiment_name': experiment_name,
                    'request.experiment_id.category_name': category_name,
                },
                'back': back,
            }

            initial_time = time.time()
            result = _weblab_api_request('weblab._start_session', request_data)
            final_time = time.time()

            if 'url' in result:
                print()
                print("Congratulations! The session is started [in {:.2f} seconds]".format(final_time - initial_time))
                print()
                print("Open: {}".format(result['url']))
                print()
                print("Session identifier: {}\n".format(result['session_id']))
                open(".fake_weblab_user_session_id", 'w').write(result['session_id'])
                print("Now you can make calls as if you were WebLab-Deusto (no argument needed):")
                print(" - flask weblab fake status")
                print(" - flask weblab fake dispose")
                print()
                if not dont_open_browser:
                    webbrowser.open(result['url'])
            else:
                print()
                print("Error processing request: {}".format(result['message']))
                print()

        @fake.command('status')
        def fake_status():
            """
            Check status of a fake user.

            Once you create a user with flask "weblab fake new", you can use this command to
            simulate the status method of WebLab-Deusto and see what it would return.
            """
            if not os.path.exists('.fake_weblab_user_session_id'):
                print("Session not found. Did you call 'flask weblab fake new' first?")
                return
            session_id = open('.fake_weblab_user_session_id').read()
            status_time = _status_time(session_id)
            print(self._backend.get_user(session_id))
            print("Should finish: {}".format(status_time))

        @fake.command('dispose')
        def fake_dispose():
            """
            End a session of a fake user.

            Once you create a user with 'flask weblab fake new', you can use this command to
            simulate the dispose method of WebLab-Deusto to kill the current session.
            """
            if not os.path.exists('.fake_weblab_user_session_id'):
                print("Session not found. Did you call 'flask weblab fake new' first?")
                return
            session_id = open('.fake_weblab_user_session_id').read()
            print(self._backend.get_user(session_id))

            request_data = {
                'action': 'delete',
            }
            result = _weblab_api_request('weblab._dispose_experiment', session_id=session_id, json_data=request_data)

            if os.path.exists('.fake_weblab_user_session_id'):
                os.remove('.fake_weblab_user_session_id')

            print(result['message'])

        if not self._app.config.get('SERVER_NAME'):
            if 'new' in sys.argv and 'fake' in sys.argv:
                server_name = os.environ.get('SERVER_NAME')
                default_server_name = 'localhost:5000'
                if not server_name:
                    print(file=sys.stderr)
                    print("Note: No SERVER_NAME provided; using {!r} If you want other, run:".format(default_server_name), file=sys.stderr)
                    print("      $ export SERVER_NAME=localhost:5001", file=sys.stderr)
                    print(file=sys.stderr)
                    server_name = default_server_name

                self._app.config['SERVER_NAME'] = server_name

        if self._app.config.get('WEBLAB_NO_THREAD', False):
            if self._app.config.get('WEBLAB_AUTOCLEAN_THREAD', False):
                raise ValueError("WEBLAB_NO_THREAD=True is incompatible with WEBLAB_AUTOCLEAN_THREAD=True")

            if self._app.config.get('WEBLAB_TASK_THREADS_PROCESS', 0) > 0:
                raise ValueError("WEBLAB_NO_THREAD=True is incompatible with WEBLAB_TASK_THREADS_PROCESS > 0")

        else:
            if self._app.config.get('WEBLAB_AUTOCLEAN_THREAD', True):
                self._cleaner_thread = _CleanerThread(self, self._app)
                self._cleaner_thread.start()

            threads_per_process = self._app.config.get('WEBLAB_TASK_THREADS_PROCESS', 3)
            if threads_per_process > 0: # If set to 0, no thread is running
                for number in six.moves.range(threads_per_process):
                    task_thread = _TaskRunner(number, self, self._app)
                    self._task_threads.append(task_thread)
                    task_thread.start()

        for task_wrapper in self._task_functions.values():
            # XXX This is cleaning locks when restarted. Is this a good thing? 
            # A current user in production might be in problem if done this way.
            if task_wrapper.unique == 'global':
                func = task_wrapper.func
                self._backend.clean_lock_global_unique_task(func.__name__)
            if task_wrapper.unique == 'user':
                pass # Nothing to do...

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
        This must be called, and only once. It's a decorator for establishing
        where the user should be redirected (the lab itself).
        Example::

            @weblab.initial_url
            def initial_url():
                return url_for('index')

        :param func: The function that will be called to get the initial URL. It takes no parameter.
        """
        if self._initial_url is not None:
            raise ValueError("initial_url has already been defined")

        self._initial_url = func
        return func

    def on_start(self, func):
        """
        Register a method for being called when a new user comes. The format is::

            @weblab.on_start
            def start(client_data, server_data):
                initialize_my_resources() # Example code

        :param func: The function that will be used on start.

        This function has two parameters:

        :param client_data: Data provided by the WebLab-Deusto client. It is a dictionary with different parameters.
        :param server_data: Data provided by the WebLab-Deusto server (username, etc., generally wrapped in the ``weblab_user`` method)
        """
        if self._on_start is not None:
            raise ValueError("on_start has already been defined")

        self._on_start = func
        return func

    def on_dispose(self, func):
        """
        Register a method for being called when a new user comes::

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
         3. This API method, available as ``weblab.clean_expired_users()``

        """
        for session_id in self._backend.find_expired_sessions():
            try:
                _dispose_user(session_id, waiting=False)
            except NotFoundError:
                pass
            except Exception:
                traceback.print_exc()


    def run_tasks(self):
        """
        Run all the pending tasks, once. It does not have any loop or waits for any new task:
        it just runs it once. You can use it in your code for running tasks in the pace you
        consider, or use ``flask weblab loop``.
        """
        if not self._task_functions:
            # If no task was registered, simply ignore
            return

        task_ids = self._backend.get_tasks_not_started()

        for task_id in task_ids:
            task_data = self._backend.start_task(task_id)

            if task_data is None:
                # Someone else took the task
                continue

            func_name = task_data['name']
            args = task_data['args']
            kwargs = task_data['kwargs']
            session_id = task_data['session_id']

            func = self._task_functions.get(func_name)
            if func is None:
                self._backend.finish_task(task_id, error={
                    'code': 'not-found',
                    'message': "Task {} not found".format(func_name),
                })
                continue

            self._set_session_id(session_id)
            user = self._backend.get_user(session_id)
            _set_weblab_user_cache(user)
            g._weblab_task_id = task_id
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                traceback.print_exc()
                self._backend.finish_task(task_id, error={
                    'code': 'exception',
                    'class': type(error).__name__,
                    'message': '{}'.format(error),
                })
            else:
                self._backend.finish_task(task_id, result=result)
            finally:
                delattr(g, '_weblab_task_id')


    def task(self, unique=None):
        """
        A task is a function that can be called later on by the WebLab wrapper. It is a set
        of threads running in the background, so you don't need to deal with it later on::

            @weblab.task()
            def function(a, b):
                return a + b

        You can either call it directly (no thread involved)::

            result = function(5, 3)

        Or you can call it delayed (and it will be run in a different thread)::

            task_result = function.delay(5, 3)
            task_result.task_id # The task identifier
            task_result.status # Either submitted, running, done or failed
            task_result.result # If done
            task_result.error # If failed

        Or you can call it synchronously (but run in other thread / process):

            task_result = function.run_sync(5, 3)
            task_result.task_id
            # ...

        You can use this :class:`WebLabTask` object, or later, you can get the task
        in other view using :meth:`WebLab.get_task`::

            task_result = weblab.get_task(task_id)

        By using :meth:`WebLab.tasks` or :meth:`WebLab.running_tasks` (if still running)::

            for task in weblab.running_tasks:
                if task.name == 'function':
                   # ...

            for task in weblab.tasks:
                if task.name == 'function':
                   # ...

        Or even by name directly with :meth:`WebLab.get_running_task` or :meth:`WebLab.get_running_tasks` or similar::

            # Only the running ones
            weblab.get_running_tasks(function) # By the function
            weblab.get_running_tasks('function') # By the name

            # All (running and stopped)
            weblab.get_tasks(function)
            weblab.get_tasks('function')

            # Only one (the first result). Useful when you run one task only once.
            weblab.get_running_task(function)
            weblab.get_running_task('function')

            # Yes, it's the same as get_task(task_id). It supports both
            weblab.get_task(function)
            weblab.get_task('function')

        Finally, you can join a task with :meth:`WebLabTask.join` or :meth:`WebLab.join_tasks`:

            task.join()
            task.join(timeout=5) # Wait 5 seconds, raise an error
            task.join(stop=True) # Call .stop() first

            weblab.join_tasks(function)
            weblab.join_tasks('function', stop=True)

        :params unique: If you want this task to be not called if another task of the same
                        type. It can be: None (no uniqueness), 'global' or 'user'.
        """
        #
        # In the future, weblab.task() will have other parameters, such as
        # discard_result (so the backend record is immediately discarded)
        #
        def task_wrapper(func):
            wrapper = _TaskWrapper(self, func, unique)
            if func.__name__ in self._task_functions:
                raise ValueError("You can't have two tasks with the same name ({})".format(func.__name__))

            if unique and self._initialized:
                if unique == 'global':
                    self._backend.clean_lock_global_unique_task(func.__name__)
                elif unique == 'user':
                    pass # Nothing to do
                else:
                    raise ValueError("unique must be None, 'global' or 'user'")

            self._task_functions[func.__name__] = wrapper
            return wrapper

        return task_wrapper

    def get_task(self, identifier):
        """
        Given a task of the current user, return the :class:`WebLabTask` object.

        The identifier can be:
          1. A ``task_id``
          2. A function name
          3. A function

        See also :meth:`WebLab.task` for examples.

        :param identifier: either a ``task_id``, a function name or a function.
        """
        name = identifier
        func = False
        if hasattr(identifier, '__code__'):
            name = identifier.__name__
            func = True

        if not func:
            task_data = self._backend.get_task(name)
            if task_data:
                # Don't return tasks of other users
                if task_data['session_id'] == _current_session_id():
                    return WebLabTask(self, task_data['task_id'])

        if has_app_context():
            # if no task_data or func is True:
            tasks = self.get_tasks(name)
            if tasks:
                return tasks[0]

    @property
    def tasks(self):
        """
        Return all the tasks created in the current session (completed or not)

        See also :meth:`WebLab.task` for examples.
        """
        session_id = _current_session_id()
        tasks = []
        for task_id in self._backend.get_all_tasks(session_id):
            tasks.append(WebLabTask(self, task_id))
        return tasks

    @property
    def running_tasks(self):
        """
        Check which tasks are still running and return them.

        See also :meth:`WebLab.task` for examples.
        """
        session_id = _current_session_id()
        tasks = []
        for task_id in self._backend.get_unfinished_tasks(session_id):
            tasks.append(WebLabTask(self, task_id))
        return tasks

    def get_running_tasks(self, func_or_name):
        """
        Get all the running tasks with a given name or function.

        See also :meth:`WebLab.task` for examples.
        """
        name = func_or_name
        if hasattr(func_or_name, '__code__'):
            name = func_or_name.__name__

        tasks = []
        for task in self.running_tasks:
            if task.name == name:
                tasks.append(task)
        return tasks

    def get_running_task(self, func_or_name):
        """
        Get **any** running task with the provided name (or function). This is useful when using unique=global|user (so you know there will be only one task using it).

        See also :meth:`WebLab.task` for examples.

        :param func_or_name: a function or a function name of a task
        """
        tasks = self.get_running_tasks(func_or_name)
        if tasks:
            return tasks[0]

    def get_tasks(self, func_or_name):
        """
        Get all the tasks (running or stopped) with the provided name (or function). This is useful when using unique=global|user (so you know there will be only one task using it).

        See also :meth:`WebLab.task` for examples.

        :param func_or_name: a function or a function name of a task
        """
        name = func_or_name
        if hasattr(func_or_name, '__code__'):
            name = func_or_name.__name__

        tasks = []
        for task in self.tasks:
            if task.name == name:
                tasks.append(task)
        return tasks

    def join_tasks(self, func_or_name, timeout=None, stop=False):
        """
        Stop (optionally) and join all the tasks with a given name.

        :param func_or_name: you can either provide the task function or its name (string)
        :param timeout: seconds to wait. By default wait forever.
        :param stop: call ``stop()`` to each task before call ``join()``.
        """
        tasks = self.get_running_tasks(func_or_name)

        if stop:
            for task in tasks:
                task.stop()

        for task in tasks:
            task.join(timeout=timeout, error_on_timeout=False)

    def create_token(self, size=None): # pylint: disable=no-self-use
        """
        Create a URL-safe random token in a safe way. You can use it for secret generation.

        :param size: the size of random bytes. The token will be later converted to base64, so
                     the length of the returned string will be different (e.g., size=32 returns
                     length=43).
        :return: a unique token.
        """
        return create_token(size)

    def user_loader(self, func):
        """
        Create a user loader. It must be a function such as::

            @weblab.user_loader
            def user_loader(username_unique):
                return User.query.get(weblab_username=username_unique)

        Or similar. Internally, you can also work with :data:`weblab_user`,
        for creating the object if not present or similar.

        With this, you can later do::

            user_db = weblab_user.user

        and internally it will call the user_loader to obtain the
        user associated to this current user.
        Otherwise, ``weblab_user.user`` will return ``None``.

        :param func: The function that will be called.
        """
        if self._user_loader is not None:
            raise ValueError("A user_loader has already been registered")

        self._user_loader = func

    def loop(self, threads, reload): # pylint: disable=redefined-builtin
        """
        Launch ``threads`` threads that run tasks and clean expired users continuously.

        :param threads: Number of threads.
        :param reload: Reload if the source code is changed. Defaults to ``FLASK_DEBUG``.
        """
        print("Running {} threads".format(threads))
        loop_threads = []

        def stop_threads(*args): # pylint: disable=unused-argument
            if not self._stopping:
                print("Waiting...")
            self._stopping = True
            for loop_thread in loop_threads:
                loop_thread.stop()

            for loop_thread in loop_threads:
                loop_thread.join()

        if not reload:
            signal.signal(signal.SIGTERM, stop_threads)

        for number in range(1, threads + 1):
            task_thread = _TaskRunner(number, self, self._app)
            loop_threads.append(task_thread)
            task_thread.start()

            cleaner_thread = _CleanerThread(weblab=self, app=self._app, n=number)
            loop_threads.append(cleaner_thread)
            cleaner_thread.start()

        while True:
            try:
                time.sleep(0.2)
            except Exception:
                break

            if self._stopping or _TESTING_LOOP:
                break

        stop_threads()

_TESTING_LOOP = False


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

            _current_backend().poll(session_id)
            return response

        g.poll_requested = True


def get_weblab_user(cached=True):
    """
    Get the current user. If ``cached=True`` it will store it and return the same each time.
    If you need to get always a different one get it with ``cached=False``. In long tasks, for
    example, it's normal to call it with ``cached=False`` so it gets updated with whatever
    information comes from other threads.

    Two shortcuts exist to this function:
     * :data:`weblab_user`: it is equivalent to ``get_weblab_user(cached=True)``
     * :data:`socket_weblab_user`: it is equivalent to ``get_weblab_user(cached=False)``

    Given that the function always returns a :class:`CurrentUser` or :class:`ExpiredUser` or :class:`AnonymousUser`, it's safe to do things like::

       if not weblab_user.anonymous:
           print(weblab_user.username)
           print(weblab_user.username_unique)

    :param cached: if this method is called twice in the same thread, it will return the same object.
    """
    if cached and hasattr(g, 'weblab_user'):
        return g.weblab_user

    # Cached: then use Redis
    session_id = _current_session_id()
    if session_id is None:
        return _set_weblab_user_cache(AnonymousUser())

    user = _current_backend().get_user(session_id)
    # Store it for next requests in the same call
    return _set_weblab_user_cache(user)

def _set_weblab_user_cache(user):
    g.weblab_user = user
    return user

weblab_user = LocalProxy(get_weblab_user) # pylint: disable=invalid-name

socket_weblab_user = LocalProxy(lambda: get_weblab_user(cached=False)) # pylint: disable=invalid-name


def _current_task():
    task_id = getattr(g, '_weblab_task_id', None)
    if task_id is None:
        return None

    weblab = _current_weblab()
    return WebLabTask(weblab=weblab, task_id=task_id)

current_task = LocalProxy(_current_task) # pylint: disable=invalid-name

def _current_task_stopping():
    task = _current_task()
    if task:
        return task.stopping
    return False

current_task_stopping = LocalProxy(_current_task_stopping) # pylint: disable=invalid-name

def requires_login(func):
    """
    Decorator. Requires the user to have logged in. For example, the user might have finished
    but you still want to display his/her results or similar. With this method, the user will
    still be able to use this method. Don't use it with sensors, etc.
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
    Decorator. Requires the user to be an active user. If the user is not logged in
    or his/her time expired or he called ``logout``, the method will not be called.
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

def socket_requires_login(func):
    """
    Decorator. Requires the user to be a user (expired or active); otherwise it calls
    Flask-SocketIO disconnect.

    Essentially, equivalent to :func:`requires_login`, but calling ``disconnect``. And obtaining
    the information in real time (important in Flask-SocketIO events, where the same thread
    is used for all the events and :func:`requires_login` caches the user data).
    """
    if not _FLASK_SOCKETIO:
        print("Warning: using socket_requires_active on {} but Flask-SocketIO was not properly imported). Nothing is done.".format(func))
        print(_FLASK_SOCKETIO_IMPORT_ERROR)
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        if socket_weblab_user.is_anonymous:
            socketio_disconnect()
        return func(*args, **kwargs)

    return wrapper

def socket_requires_active(func):
    """
    Decorator. Requires the user to be a user (only active); otherwise it calls
    Flask-SocketIO disconnect.

    Essentially, equivalent to :func:`requires_active`, but calling ``disconnect``. And obtaining
    the information in real time (important in Flask-SocketIO events, where the same thread
    is used for all the events and :func:`requires_active` caches the user data)
    """
    if not _FLASK_SOCKETIO:
        print("Warning: using socket_requires_active on {} but Flask-SOCKETIO was not properly imported. Nothing is done.".format(func))
        print(_FLASK_SOCKETIO_IMPORT_ERROR)
        return func

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not socket_weblab_user.active:
            socketio_disconnect()
        return func(*args, **kwargs)

    return wrapper

def logout():
    """
    Notify WebLab-Deusto that the user left the laboratory, so next user can enter.

    This process is not real time. What it happens is that WebLab-Deusto periodically is requesting
    whether the user is still alive or not. If you call logout, weblablib will reply the next time
    that the user left. So it may take some seconds for WebLab-Deusto to realize of that. You can
    regulate this time with ``WEBLAB_POLL_INTERVAL`` setting (defaults to 5).
    """
    session_id = _current_session_id()
    if session_id:
        _current_backend().force_exit(session_id)


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
    Create a new session: WebLab-Deusto is telling us that a new user is coming. We register the user in the backend system.
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

    experiment_name = server_initial_data['request.experiment_id.experiment_name']
    category_name = server_initial_data['request.experiment_id.category_name']
    experiment_id = '{}@{}'.format(experiment_name, category_name)

    # Create a global session
    session_id = create_token()

    # Prepare adding this to backend
    user = CurrentUser(session_id=session_id, back=request_data['back'],
                       last_poll=_current_timestamp(), max_date=float(_to_timestamp(max_date)),
                       username=server_initial_data['request.username'],
                       username_unique=server_initial_data['request.username.unique'],
                       exited=False, data={}, locale=locale,
                       full_name=full_name, experiment_name=experiment_name,
                       experiment_id=experiment_id, category_name=category_name,
                       request_client_data=client_initial_data,
                       request_server_data=server_initial_data,
                       start_date=float(_to_timestamp(start_date)))

    backend = _current_backend()

    backend.add_user(session_id, user, expiration=30 + int(float(server_initial_data['priority.queue.slot.length'])))


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
        except Exception as error:
            traceback.print_exc()
            current_app.logger.warning("Error calling _on_start: {}".format(error), exc_info=True)
            try:
                _dispose_user(session_id, waiting=True)
            except Exception as nested_error:
                traceback.print_exc()
                current_app.logger.warning("Error calling _on_dispose after _on_start failed: {}".format(nested_error), exc_info=True)

            return dict(error=True, message="Error initializing laboratory")
        else:
            backend.update_data(session_id, data)
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
    except NotFoundError:
        return jsonify(message="Not found")

    return jsonify(message="Deleted")


######################################################################################
#
#
#     Task management
#

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
        session_id = None # only used if unique='user'
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
        """Starts the function in a thread or in another process.
        It returns a WebLabTask object"""
        session_id = _current_session_id()
        task_id = self._backend.new_task(session_id, self._name, args, kwargs)
        return WebLabTask(self._weblab, task_id)

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
        while not self.finished:
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
    def _task_data(self):
        return self._backend.get_task(self._task_id)

    @property
    def session_id(self):
        """
        The current ``session_id`` that represents this session.
        """
        task_data = self._task_data
        if task_data:
            return task_data['session_id']

    @property
    def name(self):
        """
        The name of the function. For example, in::

            @weblab.task()
            def my_task():
                pass

        The name would be ``my_task``.
        """
        task_data = self._task_data
        if task_data:
            return task_data['name']

    @property
    def data(self):
        """
        Dictionary that you can use to store information from outside and inside the task
        running. For example, you may call::

            @weblab.task()
            def my_task():
                # Something long, but 80%
                data = current_task.data
                data['percent'] = 0.8
                current_task.update_data(data)

            # From outside
            task = weblab.get_task(task_id)
            print(task.data.get('percent'))

        Note: every time you call ``data``, it returns a different object. Don't do::

            current_task.data['foo'] = 'bar'
        """
        task_data = self._task_data
        if task_data:
            return task_data['data']

    @data.setter
    def data(self, new_data):
        self._backend.update_task_data(self._task_id, new_data)

    def update_data(self, new_data):
        """Same as::

            task.data = new_data

        :param new_data: new data to be stored in the task data.
        """
        self._backend.update_task_data(self._task_id, new_data)

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
        task_data = self._task_data
        if task_data:
            return task_data['status']

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
        task_data = self._task_data
        if task_data:
            return task_data['stopping']

    @property
    def result(self):
        """
        In case of having finished succesfully (:data:`WebLabTask.done` being ``True``), this
        returns the result. Otherwise, it returns ``None``.
        """
        task_data = self._task_data
        if task_data:
            return task_data['result']

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
                # In the case of a ConnectionError, let's wait a bit more to see if
                # it happens again. It can be that we are just restarting the server
                # and Redis died before, or a Redis upgrade or so.
                traceback.print_exc()
                time.sleep(5)
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

def _status_time(session_id):
    weblab = _current_weblab()
    backend = weblab._backend
    user = backend.get_user(session_id)
    if isinstance(user, ExpiredUser) and user.disposing_resources:
        return 2 # Try again in 2 seconds

    if user.is_anonymous or not isinstance(user, CurrentUser):
        return -1

    if user.exited:
        return -1

    if weblab.timeout and weblab.timeout > 0:
        # If timeout is set to -1, it will never timeout (unless user exited)
        if user.time_without_polling >= weblab.timeout:
            return -1

    if user.time_left <= 0:
        return -1

    return min(weblab.poll_interval, int(user.time_left))

def _update_weblab_user_data(response):
    # If a developer does:
    #
    # weblab_user.data["foo"] = "bar"
    #
    # Nothing is triggered in Redis. For this reason, after each request
    # we check that the data has changed or not.
    #
    session_id = _current_session_id()
    backend = _current_backend()
    if session_id:
        if weblab_user.active:
            current_user = backend.get_user(session_id)
            if current_user.active:
                if json.dumps(current_user.data) != weblab_user.data:
                    backend.update_data(session_id, weblab_user.data)

    return response


def _dispose_user(session_id, waiting):
    backend = _current_backend()
    user = backend.get_user(session_id)
    if user.is_anonymous:
        raise NotFoundError()

    if isinstance(user, CurrentUser):
        current_expired_user = user.to_expired_user()
        deleted = backend.delete_user(session_id, current_expired_user)

        if deleted:
            try:
                weblab = _current_weblab()
                if weblab._on_dispose:
                    weblab._set_session_id(session_id)
                    _set_weblab_user_cache(user)
                    try:
                        weblab._on_dispose()
                    except Exception:
                        traceback.print_exc()
                    _update_weblab_user_data(None)
            finally:
                backend.finished_dispose(session_id)

            unfinished_tasks = backend.get_unfinished_tasks(session_id)
            for task_id in unfinished_tasks:
                unfinished_task = weblab.get_task(task_id)
                if unfinished_task:
                    unfinished_task.stop()

            while unfinished_tasks:
                unfinished_tasks = backend.get_unfinished_tasks(session_id)
                time.sleep(0.1)

            backend.clean_session_tasks(session_id)

            backend.report_session_deleted(session_id)

    if waiting:
        # if another thread has started the _dispose process, it might take long
        # to process it. But this (sessions) is the one that tells WebLab-Deusto
        # that someone else can enter in this laboratory. So we should wait
        # here until the process is over.

        while not backend.is_session_deleted(session_id):
            # In the future, instead of waiting, this could be returning that it is still finishing
            time.sleep(0.1)


class _CleanerThread(threading.Thread):
    """
    _CleanerThread is a thread that keeps calling the _clean_expired_users. It is optional, activated with WEBLAB_AUTOCLEAN_THREAD
    """

    _instances = []

    def __init__(self, weblab, app, n=1):
        super(_CleanerThread, self).__init__()
        self.app = app
        self.name = "WebLabCleaner-{}".format(n)
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
            except redis.ConnectionError:
                # In the case of a ConnectionError it can be
                # that we're just restarting the server or so.
                # Wait a bit further
                traceback.print_exc()
                time.sleep(5)
            except Exception:
                traceback.print_exc()

            initial_time = time.time()
            while True:
                time.sleep(0.05)
                elapsed = time.time() - initial_time
                if time.time() - initial_time > self.weblab.cleaner_thread_interval:
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
