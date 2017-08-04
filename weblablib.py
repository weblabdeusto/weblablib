from __future__ import unicode_literals, print_function, division

import sys
import json
import time
import redis
import random
import datetime
import traceback
from functools import wraps
from collections import namedtuple
from flask import Blueprint, jsonify, request, current_app, Response, redirect, url_for, g, session, after_this_request

# 
# TODO: logout
# TODO: make sure the user is out
# 


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
    def __init__(self, app = None, base_url = None, callback_url = None):
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
        self._on_start = lambda *args, **kwargs: None
        self._on_dispose = lambda *args, **kwargs: None

        self._initialized = False

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        Initialize the app. This method MUST be called (unless 'app' is provided in the constructor of WebLab)
        """
        if self._initialized:
            return

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
        redis_url = self._app.config.get('WEBLAB_REDIS_URL', 'redis://localhost:6379/0')
        self._redis_manager = _RedisManager(redis_url)
        
        # 
        # Initialize session settings
        # 
        self._session_id_name = self._app.config.get('WEBLAB_SESSION_ID_NAME', 'weblab_session_id')
        self.timeout = self._app.config.get('WEBLAB_TIMEOUT', 15) # TODO: Not used yet
        autopoll = self._app.config.get('WEBLAB_AUTOPOLL', True) 
    
        # 
        # Initialize and register the "weblab" blueprint
        # 
        if not self._base_url:
            self._base_url = self._app.config.get('WEBLAB_BASE_URL')

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
            self._callback_url = self._app.config.get('WEBLAB_CALLBACK_URL')

        if not self._callback_url:
            raise ValueError("Invalid callback URL. Either provide it in the constructor or in the WEBLAB_CALLBACK_URL configuration")
        elif self._callback_url.endswith('/'):
            print("Note: your callback URL ({}) ends with '/'. It is discouraged".format(self._callback_url), file=sys.stderr)

        @self._app.route(self._callback_url + '/<session_id>')
        def callback_url(session_id):
            if self._initial_url is None:
                print("ERROR: You MUST use @weblab.initial_url to point where the WebLab users should be redirected to.", file=sys.stderr)
                return "ERROR: laboratory not properly configured, didn't call @weblab.initial_url", 500
            
            # 
            # TODO: check if the user exists before storing the session_id in the session object
            # 
            session[self._session_id_name] = session_id
            return redirect(self._initial_url())

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
                        _current_redis().poll(session_id)

                return response
        
        # 
        # Don't start if there are missing parameters
        # 
        for key in 'WEBLAB_USERNAME', 'WEBLAB_PASSWORD':
            if key not in self._app.config:
                raise ValueError("Invalid configuration. Missing {}".format(key))

        self._initialized = True

    def _session_id(self):
        """Return the session identifier from the Flask session object"""
        return session.get(self._session_id_name)

    def _forbidden_handler(self):
        # 
        # TODO: 
        # let administrators to:
        # 1. put a custom template
        # 2. redirect to a default link (e.g., a particular WebLab-Deusto)
        # 
        return "Access forbidden", 403
    
    def initial_url(self, func):
        """This must be called. It's a decorator for establishing where the user should be redirected (the lab itself).

        Typically, this is just the url_for('index') or so in the website."""
        self._initial_url = func
        return func

    def on_start(self, func):
        self._on_start = func
        return func

    def on_dispose(self, func):
        self._on_dispose = func
        return func


##################################################################################################################
# 
# 
# 
#         Public classes
# 
# 
# 

class User(namedtuple("User", ["back", "last_poll", "max_date", "username", "username_unique", "exited", "data"])):
    """
    This class represents a user which is still actively using a laboratory. If the session expires, it will become a PastUser.

    back: URL to redirect the user when finished
    last_poll: the last time the user polled. Updated every time poll() is called.
    max_date: datetime, the maximum date the user is supposed to be alive. When a new reservation comes, it states the time assigned.
    username: the simple username for the user in the final system (e.g., 'tom'). It may be repeated across different systems.
    username_unique: a unique username for the user. It is globally unique (e.g., tom@school1@labsland).
    exited: the user left the laboratory (e.g., he closed the window or a timeout happened).
    data: Serialized data (simple JSON data: dicts, list...) that can be stored for the context of the current user.
    """
    @property
    def time_without_polling(self):
        return float(_current_timestamp()) - float(self.last_poll)

    @property
    def time_left(self):
        return float(self.max_date) - float(_current_timestamp())

    active = True # Is the user an active user or a PastUser?

class PastUser(namedtuple("PastUser", ["back", "max_date", "username", "username_unique", "data"])):
    """
    This class represents a user which has been kicked out already. Typically this PastUser is kept in redis for around an hour.

    All the fields are same as in User.
    """
    active = False # Is the user an active user or a PastUser?


##################################################################################################################
# 
# 
# 
#         Public functions
# 
# 
# 

def poll():
    """Program that in the end of this call, poll will be called"""

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


def current_user(active_only=False):
    """
    Get the current user. Optionally, return the PastUser if the current one expired.

    @active_only: if set to True, do not return a past user (and None instead)
    """

    # Cached: first check
    if active_only:
        if hasattr(g, 'current_user'):
            return g.current_user
    else:
        if hasattr(g, 'current_user'):
            return g.current_user

        if hasattr(g, 'past_user'):
            return g.past_user
   
    # Cached: then use Redis
    session_id = _current_session_id()
    if session_id is None:
        g.current_user = None
        if not active_only:
            g.past_user = None
        return None

    user = _current_redis().get_user(session_id, retrieve_past = not active_only)
    if user is None:
        g.current_user = None
        if not active_only:
            g.past_user = None
        return None

    # Store it for next requests in the same call
    if user.active:
        g.current_user = user
    else:
        g.past_user = user

    # Finish
    return user
    

def past_user():
    """
    Get the past user (if the session has expired for the current user).
    """
    if hasattr(g, 'past_user'):
        return g.past_user

    session_id = _current_session_id()
    past_user = _current_redis().get_past_user(session_id)

    if past_user is None:
        g.past_user = None
        return None

    g.past_user = past_user
    return past_user

def requires_login(redirect_back=True, requires_current=False):
    """
    Decorator. Requires the user to be logged in (and be a current user or not).

    @redirect_back: if it's a past user, automatically redirect him to the original link
    @requires_current: if it's a past_user and redirect_back is False, then act as if he was 
      an invalid user
    """
    def requires_login_decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if current_user() is None:
                if past_user() is None:
                    # If no past user or current user: forbidden
                    return _current_weblab()._forbidden_handler()
                elif redirect_back:
                    # If past user found, and redirect_back is the policy, return the user
                    return redirect(past_user().back)
                elif requires_current:
                    # If it requires a current user
                    return _current_weblab()._forbidden_handler()
                # If the policy is not returning back neither requiring that 
                # this is a current user... let it be
            return func(*args, **kwargs)
        return wrapper

    return requires_login_decorator

def requires_current(redirect_back=True):
    """
    Decorator. Requires the user to be a valid current user. 
    Otherwise, it will call the forbidden behavior.
    """
    return requires_login(redirect_back=redirect_back, requires_current=True)

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

    expected_username = current_app.config['WEBLAB_USERNAME']
    expected_password = current_app.config['WEBLAB_PASSWORD']
    if provided_username != expected_username or provided_password != expected_password:
        if request.url.endswith('/test'):
            error_message = "Invalid credentials: no username provided"
            if provided_username:
                error_message = "Invalid credentials: wrong username provided. Check the lab logs for further information."
            return Response(json.dumps(dict(valid=False, error_messages=[error_message])), status=401, headers = {'WWW-Authenticate':'Basic realm="Login Required"', 'Content-Type': 'application/json'})
        
        if expected_username:
            current_app.logger.warning("Invalid credentials provided to access {}. Username provided: {!r} (expected: {!r})".format(request.url, provided_username, expected_username))

        return Response(response=("You don't seem to be a WebLab-Instance"), status=401, headers = {'WWW-Authenticate':'Basic realm="Login Required"'})



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

    client_initial_data = request_data['client_initial_data']
    server_initial_data = request_data['server_initial_data']

    # Parse the initial date + assigned time to know the maximum time
    start_date_str = server_initial_data['priority.queue.slot.start']
    start_date_str, microseconds = start_date_str.split('.')
    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(microseconds = int(microseconds))
    max_date = start_date + datetime.timedelta(seconds = float(server_initial_data['priority.queue.slot.length']))

    # Create a global session
    session_id = str(random.randint(0, 10e8)) # Not especially secure 0:-)

    # Prepare adding this to redis
    max_date_int = _to_timestamp(max_date)
    last_poll_int = _current_timestamp()
    
    pipeline = _current_redis().pipeline()
    pipeline.hset('weblab:active:{}'.format(session_id), 'max_date', max_date_int)
    pipeline.hset('weblab:active:{}'.format(session_id), 'last_poll', last_poll_int)
    pipeline.hset('weblab:active:{}'.format(session_id), 'username', server_initial_data['request.username'])
    pipeline.hset('weblab:active:{}'.format(session_id), 'username-unique', server_initial_data['request.username.unique'])
    pipeline.hset('weblab:active:{}'.format(session_id), 'data', 'null')
    pipeline.hset('weblab:active:{}'.format(session_id), 'back', request_data['back'])
    pipeline.hset('weblab:active:{}'.format(session_id), 'exited', 'false')
    pipeline.expire('weblab:active:{}'.format(session_id), 30 + int(float(server_initial_data['priority.queue.slot.length'])))
    pipeline.execute()

    kwargs = {}
    scheme = current_app.config.get('WEBLAB_SCHEME')
    if scheme:
        kwargs['_scheme'] = scheme

    user = _get_user_from_redis(session_id)
    try:
        data = _current_weblab()._on_start(client_initial_data, server_initial_data, user)
    except:
        traceback.print_exc()
    else:
        _current_redis().hset('weblab:active:{}'.format(session_id), 'data', json.dumps(data))

    link = url_for('callback_url', session_id=session_id, _external = True, **kwargs)
    return jsonify(url=link, session_id=session_id)



@_weblab_blueprint.route('/sessions/<session_id>/status')
def _status(session_id):
    """
    This method provides the current status of a particular 
    user.
    """
    last_poll = _current_redis().hget("weblab:active:{}".format(session_id), "last_poll")
    max_date = _current_redis().hget("weblab:active:{}".format(session_id), "max_date")
    username = _current_redis().hget("weblab:active:{}".format(session_id), "username")
    exited = _current_redis().hget("weblab:active:{}".format(session_id), "exited")
    
    if exited == 'true':
        return jsonify(should_finish= -1)

    if last_poll is not None:
        current_time = float(_current_timestamp())
        difference = current_time - float(last_poll)
        print("Did not poll in", difference, "seconds")
        if difference >= 15:
            return jsonify(should_finish=-1)

        print("User %s still has %s seconds" % (username, (float(max_date) - current_time)))

        if float(max_date) <= current_time:
            print("Time expired")
            return jsonify(should_finish=-1)

        return jsonify(should_finish=5)

    print("User not found")
    # 
    # If the user is considered expired here, we can return -1 instead of 10. 
    # The WebLab-Deusto scheduler will mark it as finished and will reassign
    # other user.
    # 
    return jsonify(should_finish=-1)



@_weblab_blueprint.route('/sessions/<session_id>', methods=['POST'])
def _dispose_experiment(session_id):
    """
    This method is called to kick one user out. This may happen
    when an administrator defines so, or when the assigned time
    is over.
    """
    request_data = request.get_json(force=True)
    if 'action' in request_data and request_data['action'] == 'delete':
        redis_client = _current_redis()
        back = redis_client.hget("weblab:active:{}".format(session_id), "back")
        if back is not None:
            user = _get_user_from_redis(session_id)
            try:
                _current_weblab()._on_dispose(user)
            except:
                traceback.print_exc()
            pipeline = redis_client.pipeline()
            pipeline.delete("weblab:active:{}".format(session_id))
            pipeline.hset("weblab:inactive:{}".format(session_id), "back", back)
            # During half an hour after being created, the user is redirected to
            # the original URL. After that, every record of the user has been deleted
            pipeline.expire("weblab:inactive:{}".format(session_id), current_app.config.get('WEBLAB_PAST_USERS_TIMEOUT', 3600))
            pipeline.execute()
            return jsonify(message="Deleted")
        return jsonify(message="Not found")
    return jsonify(message="Unknown op")

######################################################################################
# 
#     Redis Management
# 


class _RedisManager(object):
    def __init__(self, redis_url):
        self.client = redis.StrictRedis.from_url(redis_url)

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
            self.client.delete("weblab:active:{}".format(session_id))

    def seconds_left(self, session_id): #TODO: NOT USED YET
        """
        How much time does the current user have, in seconds
        """
        current_time = float(_current_timestamp())

        max_date = self.client.hget("weblab:active:{}".format(session_id), "max_date")
        if max_date is None:
            return 0

        left = float(max_date) - current_time
        if left <= 0:
            return 0

        return left

    def get_user(self, session_id, retrieve_past = False):
        pipeline = self.client.pipeline()
        key = 'weblab:active:{}'.format(session_id)
        for name in 'back', 'last_poll', 'max_date', 'username', 'username-unique', 'data', 'exited':
            pipeline.hget(key, name)
        back, last_poll, max_date, username, username_unique, data, exited = pipeline.execute()

        if max_date is not None:
            return User(back=back, last_poll=last_poll, max_date=max_date, username=username, username_unique=username_unique, data=data, exited=exited)

        if retrieve_past:
            return self.get_past_user(session_id)

    def get_past_user(self, session_id):
        pipeline = self.client.pipeline()
        key = 'weblab:inactive:{}'.format(session_id)
        for name in 'back', 'max_date', 'username', 'username-unique', 'data':
            pipeline.hget(key, name)

        back, max_date, username, username_unique, data = pipeline.execute()

        if max_date is not None:
            return PastUser(back=back, max_date=max_date, username=username, username_unique=username_unique, data=data)

    def poll(self, session_id):
        key = 'weblab:active:{}'.format(session_id)

        last_poll_int = _current_timestamp()
        pipeline = self.client.pipeline()
        pipeline.hget(key, "max_date")
        pipeline.hset(key, "last_poll", last_poll_int)
        max_date, _ = pipeline.execute()

        if max_date is None:
            # If the user was deleted in between, revert the last_poll
            self.client.delete(key)


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
    return _to_timestamp(datetime.datetime.now())

