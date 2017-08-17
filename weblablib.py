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
import base64
import datetime
import threading
import traceback
import webbrowser

from functools import wraps

import redis
import click

from werkzeug import LocalProxy
from flask import Blueprint, Response, jsonify, request, current_app, redirect, \
     url_for, g, session, after_this_request, render_template

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
    WEBLAB_PAST_USERS_TIMEOUT = 'WEBLAB_PAST_USERS_TIMEOUT'

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
    def __init__(self, app=None, base_url=None, callback_url=None):
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

        self._tasks = {
            # task_id: _Task
        }

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Initialize the app. This method MUST be called (unless 'app' is provided in the constructor of WebLab)
        """
        if self._initialized:
            return

        if app is None:
            raise ValueError("app must be a Flask app")

        self._app = app

        #
        # Register the extension
        #
        if 'weblab' in self._app.extensions:
            print("Overriding existing WebLab extension (did you create two WebLab() ?)", file=sys.stderr)

        self._app.extensions['weblab'] = self

        #
        # Initialize Redis Manager
        #
        redis_url = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_URL, 'redis://localhost:6379/0')
        self._redis_manager = _RedisManager(redis_url, self)

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
            self._callback_url = self._app.config.get(ConfigurationKeys.WEBLAB_CALLBACK_URL)

        if not self._callback_url:
            raise ValueError("Invalid callback URL. Either provide it in the constructor or in the WEBLAB_CALLBACK_URL configuration")
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
                raise ValueError("Invalid configuration. Missing {}".format(key))

        def weblab_poll_script():
            weblab_timeout = int(1000 * self.timeout // 2)
            return """<script>
            var WEBLAB_TIMEOUT = setInterval(function () {
                $.get("{url}")
            }, {timeout} )
            </script>""".format(timeout=weblab_timeout)

        @self._app.context_processor
        def weblab_context_processor():
            return dict(weblab_poll_script=weblab_poll_script)

        if hasattr(app, 'cli'):
            @self._app.cli.command('clean-expired-users')
            def clean_expired_users():
                self.clean_expired_users()

            @self._app.cli.command('fake-new-user')
            @click.option('--name', default='John Smith', help="First and last name")
            @click.option('--username', default='john.smith', help="Username passed")
            @click.option('--username-unique', default='john.smith@institution', help="Unique username passed")
            @click.option('--time', default=300, help="Time in seconds passed to the laboratory")
            @click.option('--back', default='http://weblab.deusto.es', help="URL to send the user back")
            @click.option('--open-browser', is_flag=True, help="Open the fake use in a web browser")
            def fake_user(name, username, username_unique, time, back, open_browser):
                time = float(time)
                
                start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '.0'

                request_data = {
                    'client_initial_data': {},
                    'server_initial_data': {
                        'priority.queue.slot.start': start_time,
                        'priority.queue.slot.length': time,
                        'request.username': username,
                        'request.username.unique': username_unique,
                    },
                    'back': back,
                }

                result = _process_start_request(request_data)
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

            @self._app.cli.command('fake-status')
            def fake_status():
                if not os.path.exists('.fake_weblab_user_session_id'):
                    print("Session not found. Did you call fake-new-user first?")
                    return
                session_id = open('.fake_weblab_user_session_id').read()
                status_time = _status_time(session_id)
                print(self._redis_manager.get_user(session_id))
                print("Should finish: {}".format(status_time))

            @self._app.cli.command('fake-dispose')
            def fake_dispose():
                if not os.path.exists('.fake_weblab_user_session_id'):
                    print("Session not found. Did you call fake-new-user first?")
                    return
                session_id = open('.fake_weblab_user_session_id').read()
                print(self._redis_manager.get_user(session_id))
                try:
                    _dispose_user(session_id)
                except _NotFoundError:
                    print("Not found")
                else:
                    print("Deleted")
            
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
            self._cleaner_thread = _CleanerThread(self._app)
            self._cleaner_thread.start()

        self._initialized = True

    def _session_id(self):
        """
        Return the session identifier from the Flask session object
        """
        return session.get(self._session_id_name)

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
                _dispose_user(session_id)
            except _NotFoundError:
                pass
            except Exception:
                traceback.print_exc()

    def task(self, func):
        """
        A task is a function that can be called later on by the WebLab wrapper. It is a set
        of threads running in the background, so you don't need to deal with it later on.

        @weblab.task
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
        wrapper = _TaskWrapper(self, func)
        if func.__name__ in self._task_functions:
            raise ValueError("You can't have two tasks with the same name ({})".format(func.__name__))

        self._task_functions[func.__name__] = wrapper
        return wrapper

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
    def __unicode__(self):
        """Unicode representation"""

    def __str__(self):
        return self.__unicode__().encode('utf8')

class AnonymousUser(WebLabUser):
    @property
    def active(self):
        return False

    @property
    def is_anonymous(self):
        return True

    def __unicode__(self):
        return "Anonymous user"

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

    def __init__(self, session_id, back, last_poll, max_date, username, username_unique, exited, data):
        self._session_id = session_id
        self._back = back
        self._last_poll = last_poll
        self._max_date = max_date
        self._username = username
        self._username_unique = username_unique
        self._exited = exited
        self._data = data

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
        return ExpiredUser(session_id=self._session_id, back=self._back, max_date=self._max_date, username=self._username, username_unique=self._username_unique, data=self._data)

    @property
    def active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __unicode__(self):
        return u'Current user (id: {!r}): {!r} ({!r}), last poll: {:.2f} seconds ago. Max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self.time_without_polling, self._max_date - _current_timestamp(), self._back)

class ExpiredUser(WebLabUser):
    """
    This class represents a user which has been kicked out already. Typically this ExpiredUser is kept in redis for around an hour.

    All the fields are same as in User.
    """
    def __init__(self, session_id, back, max_date, username, username_unique, data):
        self._session_id = session_id
        self._back = back
        self._max_date = max_date
        self._username = username
        self._username_unique = username_unique
        self._data = data

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
    def active(self):
        return False

    @property
    def is_anonymous(self):
        return False

    def __unicode__(self):
        return u'Expired user (id: {!r}): {!r} ({!r}), max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self._max_date - _current_timestamp(), self._back)

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

weblab_user = LocalProxy(_weblab_user)

def requires_login(redirect_back=True, current_only=False):
    """
    Decorator. Requires the user to be logged in (and be a current user or not).

    @redirect_back: if it's a expired user, automatically redirect him to the original link
    @current_only: if it's a expired_user and redirect_back is False, then act as if he was
      an invalid user
    """
    def requires_login_decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not weblab_user.active:
                if weblab_user.is_anonymous:
                    # If anonymous user: forbidden
                    return _current_weblab()._forbidden_handler()
                elif redirect_back:
                    # If expired user found, and redirect_back is the policy, return the user
                    return redirect(weblab_user.back)
                elif current_only:
                    # If it requires a current user
                    return _current_weblab()._forbidden_handler()
                # If the policy is not returning back neither requiring that
                # this is a current user... let it be
            return func(*args, **kwargs)
        return wrapper

    return requires_login_decorator

def requires_active(redirect_back=True):
    """
    Decorator. Requires the user to be a valid current user.
    Otherwise, it will call the forbidden behavior.
    """
    return requires_login(redirect_back=redirect_back, current_only=True)

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

_weblab_blueprint = Blueprint("weblab", __name__)



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
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(microseconds=int(microseconds))
    max_date = start_date + datetime.timedelta(seconds=float(server_initial_data['priority.queue.slot.length']))

    # Create a global session
    tok = os.urandom(32)
    session_id = base64.urlsafe_b64encode(tok).strip().replace('=', '').replace('-', '_').decode('utf8')

    # Prepare adding this to redis
    user = CurrentUser(session_id=session_id, back=request_data['back'], last_poll=_current_timestamp(), max_date=float(_to_timestamp(max_date)),
                username=server_initial_data['request.username'], username_unique=server_initial_data['request.username.unique'],
                exited=False, data=None)

    redis_manager = _current_redis()

    redis_manager.add_user(session_id, user, expiration=30 + int(float(server_initial_data['priority.queue.slot.length'])))


    kwargs = {}
    scheme = current_app.config.get(ConfigurationKeys.WEBLAB_SCHEME)
    if scheme:
        kwargs['_scheme'] = scheme

    weblab = _current_weblab()
    if weblab._on_start:
        _set_weblab_user_cache(user)
        try:
            data = weblab._on_start(client_initial_data, server_initial_data)
        except Exception:
            traceback.print_exc()
        else:
            redis_manager.update_data(session_id, data)

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
        _dispose_user(session_id)
    except _NotFoundError:
        return jsonify(message="Not found")

    return jsonify(message="Deleted")


######################################################################################
#
#     Redis Management
#


class _RedisManager(object):

    def __init__(self, redis_url, weblab):
        self.client = redis.StrictRedis.from_url(redis_url)
        self.weblab = weblab

    def add_user(self, session_id, user, expiration):
        key = 'weblab:active:{}'.format(session_id)

        pipeline = self.client.pipeline()
        pipeline.hset(key, 'max_date', user.max_date)
        pipeline.hset(key, 'last_poll', user.last_poll)
        pipeline.hset(key, 'username', user.username)
        pipeline.hset(key, 'username-unique', user.username_unique)
        pipeline.hset(key, 'data', json.dumps(user.data))
        pipeline.hset(key, 'back', user.back)
        pipeline.hset(key, 'exited', json.dumps(user.exited))
        pipeline.expire(key, expiration)
        pipeline.execute()

    def update_data(self, session_id, data):
        key = 'weblab:active:{}'.format(session_id)

        pipeline = self.client.pipeline()
        pipeline.hget(key, 'max_date')
        pipeline.hset(key, 'data', json.dumps(data))
        max_date, _ = pipeline.execute()

        if max_date is None: # Object had been removed
            self.client.delete(key)

    def get_user(self, session_id):
        pipeline = self.client.pipeline()
        key = 'weblab:active:{}'.format(session_id)
        for name in 'back', 'last_poll', 'max_date', 'username', 'username-unique', 'data', 'exited':
            pipeline.hget(key, name)
        back, last_poll, max_date, username, username_unique, data, exited = pipeline.execute()

        if max_date is not None:
            return CurrentUser(session_id=session_id, back=back, last_poll=float(last_poll), 
                        max_date=float(max_date), username=username, 
                        username_unique=username_unique, 
                        data=json.loads(data), exited=json.loads(exited))

        return self.get_expired_user(session_id)

    def get_expired_user(self, session_id):
        pipeline = self.client.pipeline()
        key = 'weblab:inactive:{}'.format(session_id)
        for name in 'back', 'max_date', 'username', 'username-unique', 'data':
            pipeline.hget(key, name)

        back, max_date, username, username_unique, data = pipeline.execute()

        if max_date is not None:
            return ExpiredUser(session_id=session_id, back=back, max_date=float(max_date), 
                            username=username, username_unique=username_unique, 
                            data=json.loads(data))

        return AnonymousUser()

    def delete_user(self, session_id, expired_user):
        if self.client.hget('weblab:active:{}'.format(session_id), "max_date") is None:
            return False

        #
        # If two processes at the same time call delete() and establish the same second,
        # it's not a big deal (as long as only one calls _on_delete later).
        #
        pipeline = self.client.pipeline()
        pipeline.delete("weblab:active:{}".format(session_id))

        key = 'weblab:inactive:{}'.format(session_id)

        pipeline.hset(key, "back", expired_user.back)
        pipeline.hset(key, "max_date", expired_user.max_date)
        pipeline.hset(key, "username", expired_user.username)
        pipeline.hset(key, "username-unique", expired_user.username_unique)
        pipeline.hset(key, "data", json.dumps(expired_user.data))

        # During half an hour after being created, the user is redirected to
        # the original URL. After that, every record of the user has been deleted
        pipeline.expire("weblab:inactive:{}".format(session_id), current_app.config.get(ConfigurationKeys.WEBLAB_PAST_USERS_TIMEOUT, 3600))
        results = pipeline.execute()

        return results[0] != 0 # If redis returns 0 on delete() it means that it was not deleted

    def force_exit(self, session_id):
        """
        If the user logs out, or closes the window, we have to report
        WebLab-Deusto.
        """
        pipeline = self.client.pipeline()
        pipeline.hget("weblab:active:{}".format(session_id), "max_date")
        pipeline.hset("weblab:active:{}".format(session_id), "exited", "true")
        max_date, _ = pipeline.execute()
        if max_date is None:
            # If max_date is None it means that it had been previously deleted
            self.client.delete("weblab:active:{}".format(session_id))

    def find_expired_sessions(self):
        expired_sessions = []

        for active_key in self.client.keys('weblab:active:*'):
            session_id = active_key[len('weblab:active:'):]
            user = self.get_user(session_id)
            if user.active: # Double check: he might be deleted in the meanwhile
                if user.time_left <= 0:
                    expired_sessions.append(session_id)

                elif user.time_without_polling >= self.weblab.timeout:
                    expired_sessions.append(session_id)
                    
        return expired_sessions

    def session_exists(self, session_id, retrieve_expired=True):
        user = self.get_user(session_id)
        if retrieve_expired:
            return not user.is_anonymous

        return user.active

    def poll(self, session_id):
        key = 'weblab:active:{}'.format(session_id)

        last_poll = _current_timestamp()
        pipeline = self.client.pipeline()
        pipeline.hget(key, "max_date")
        pipeline.hset(key, "last_poll", last_poll)
        max_date, _ = pipeline.execute()

        if max_date is None:
            # If the user was deleted in between, revert the last_poll
            self.client.delete(key)

###################################################################################### 
# 
# 
#     Task management
# 

class _TaskWrapper(object):
    def __init__(self, weblab, func):
        self.func = func
        self.weblab = weblab

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

    def delay(self, *args, **kwargs):
        pass # TODO

    def delay_name(self, name, *args, **kwargs):
        pass # TODO

# TODO: implement these two classes

class _Task(object):
    def __init__(self):
        pass

######################################################################################
#
#
#     Auxiliar private functions
#
#

def _current_weblab():
    if 'weblab' not in current_app.extensions:
        raise Exception("App not initialized with weblab.init_app()")
    return current_app.extensions['weblab']

def _current_redis():
    return _current_weblab()._redis_manager

def _current_session_id():
    return _current_weblab()._session_id()

def _to_timestamp(dt):
    return str(int(time.mktime(dt.timetuple()))) + str(dt.microsecond / 1e6)[1:]

def _current_timestamp():
    return float(_to_timestamp(datetime.datetime.now()))

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

    current_app.logger.debug("User {} still has {} seconds".format(user.username, user.time_left))
    return min(5, int(user.time_left))


def _dispose_user(session_id):
    redis_manager = _current_redis()
    user = redis_manager.get_user(session_id)
    if user.is_anonymous:
        raise _NotFoundError()

    if not user.active:
        return

    current_expired_user = user.to_expired_user()
    deleted = redis_manager.delete_user(session_id, current_expired_user)

    if deleted:
        weblab = _current_weblab()
        if weblab._on_dispose:
            _set_weblab_user_cache(user)
            try:
                weblab._on_dispose()
            except Exception:
                traceback.print_exc()

class _CleanerThread(threading.Thread):
    """
    _CleanerThread is a thread that keeps calling the _clean_expired_users. It is optional, activated with WEBLAB_AUTOCLEAN_THREAD
    """

    def __init__(self, app):
        super(_CleanerThread, self).__init__()
        self.app = app
        self.name = "WebLabCleaner"
        self.daemon = True

    def run(self):
        while True:
            time.sleep(5)
            try:
                with self.app.app_context():
                    _current_weblab().clean_expired_users()
            except Exception:
                traceback.print_exc()

class _NotFoundError(Exception):
    pass
