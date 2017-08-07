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
from flask import Blueprint, jsonify, request, current_app, Response, redirect, url_for, g, session, after_this_request, redirect

# 
# TODO: make sure the user is out
# 
class ConfigurationKeys(object):

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
        self._redirection_on_forbiden = None
        self._template_on_forbiden = None

        self._on_start = None
        self._on_dispose = None

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
        redis_url = self._app.config.get(ConfigurationKeys.WEBLAB_REDIS_URL, 'redis://localhost:6379/0')
        self._redis_manager = _RedisManager(redis_url)
        
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
        def callback_url(session_id):
            if self._initial_url is None:
                print("ERROR: You MUST use @weblab.initial_url to point where the WebLab users should be redirected to.", file=sys.stderr)
                return "ERROR: laboratory not properly configured, didn't call @weblab.initial_url", 500
            
            if self._redis_manager.session_exists(session_id):
                session[self._session_id_name] = session_id
                return redirect(self._initial_url())

            return self._forbidden_handler()

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
        
        def start(client_data, server_data, user):
            return data # simple data, e.g., None, a dict, a list... that will be available as current_user().data

        """
        if self._on_start is not None:
            raise ValueError("on_start has already been defined")

        self._on_start = func
        return func

    def on_dispose(self, func):
        """
        Register a method for being called when a new user comes.

        def stop(user):
            pass
        """
        if self._on_dispose is not None:
            raise ValueError("on_dispose has already been defined")

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

    def to_past_user(self):
        """
        Create a PastUser based on the data of the user
        """
        return PastUser(back=self.back, max_date=self.max_date, username=self.username, username_unique=self.username_unique, data=self.data)

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
    
    user = User(back=request_data['back'], last_poll=_current_timestamp(), max_date = float(_to_timestamp(max_date)), 
                username=server_initial_data['request.username'], username_unique = server_initial_data['request.username.unique'],
                exited = False, data = None)

    redis_manager = _current_redis()

    redis_manager.add_user(session_id, user, expiration = 30 + int(float(server_initial_data['priority.queue.slot.length'])))
                

    kwargs = {}
    scheme = current_app.config.get(ConfigurationKeys.WEBLAB_SCHEME)
    if scheme:
        kwargs['_scheme'] = scheme

    weblab = _current_weblab()
    if weblab._on_start:
        try:
            data = weblab._on_start(client_initial_data, server_initial_data, user)
        except:
            traceback.print_exc()
        else:
            redis_manager.update_data(session_id, data)

    link = url_for('callback_url', session_id=session_id, _external = True, **kwargs)
    return jsonify(url=link, session_id=session_id)



@_weblab_blueprint.route('/sessions/<session_id>/status')
def _status(session_id):
    """
    This method provides the current status of a particular 
    user.
    """

    weblab = _current_weblab()
    redis_manager = weblab.redis_manager
    user = redis_manager.get_user(session_id, retrieve_past = False)
    if user is None:
        return jsonify(should_finish= -1)

    if user.exited:
        return jsonify(should_finish= -1)

    if weblab.timeout and weblab.timeout > 0: 
        # If timeout is set to -1, it will never timeout (unless user exited)
        if user.time_without_polling() >= weblab.timeout:
            return jsonify(should_finish=-1)

    if user.time_left() <= 0:
        return jsonify(should_finish=-1)

    current_app.logger.debug("User {} still has {} seconds".format(user.username, user.time_left()))
    return jsonify(should_finish=min(5, int(user.time_left())))


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

    redis_manager = _current_redis()
    user = redis_manager.get_user(session_id, retrieve_past=False)
    if user is None:
        return jsonify(message="Not found")

    past_user = user.to_past_user()
    deleted = redis_manager.delete_user(session_id, past_user)
    
    if deleted:
        weblab = _current_weblab()
        if weblab._on_dispose:
            try:
                weblab._on_dispose(user)
            except:
                traceback.print_exc()

    return jsonify(message="Deleted")



######################################################################################
# 
#     Redis Management
# 


class _RedisManager(object):

    def __init__(self, redis_url):
        self.client = redis.StrictRedis.from_url(redis_url)

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

    def get_user(self, session_id, retrieve_past = False):
        pipeline = self.client.pipeline()
        key = 'weblab:active:{}'.format(session_id)
        for name in 'back', 'last_poll', 'max_date', 'username', 'username-unique', 'data', 'exited':
            pipeline.hget(key, name)
        back, last_poll, max_date, username, username_unique, data, exited = pipeline.execute()

        if max_date is not None:
            return User(back=back, last_poll=float(last_poll), max_date=float(max_date), username=username, username_unique=username_unique, data=json.loads(data), exited=json.loads(exited))

        if retrieve_past:
            return self.get_past_user(session_id)

    def get_past_user(self, session_id):
        pipeline = self.client.pipeline()
        key = 'weblab:inactive:{}'.format(session_id)
        for name in 'back', 'max_date', 'username', 'username-unique', 'data':
            pipeline.hget(key, name)

        back, max_date, username, username_unique, data = pipeline.execute()

        if max_date is not None:
            return PastUser(back=back, max_date=float(max_date), username=username, username_unique=username_unique, data=json.loads(data))

    def delete_user(self, session_id, past_user):
        if self.client.hget('weblab:active:{}'.format(session_id)), "max_date") is None:
            return False
        
        # 
        # If two processes at the same time call delete() and establish the same second,
        # it's not a big deal (as long as only one calls _on_delete later).
        # 
        pipeline = self.client.pipeline()
        pipeline.delete("weblab:active:{}".format(session_id))
    
        key = 'weblab:inactive:{}'.format(session_id)

        pipeline.hset(key, "back", past_user.back)
        pipeline.hset(key, "max_date", past_user.max_date)
        pipeline.hset(key, "username", past_user.username)
        pipeline.hset(key, "username-unique", past_user.username_unique)
        pipeline.hset(key, "data", json.dumps(past_user.data))

        # During half an hour after being created, the user is redirected to
        # the original URL. After that, every record of the user has been deleted
        pipeline.expire("weblab:inactive:{}".format(session_id), current_app.config.get(ConfigurationKeys.WEBLAB_PAST_USERS_TIMEOUT, 3600))
        results = pipeline.execute()

        return row[0] != 0 # If redis returns 0 on delete() it means that it was not deleted

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

    def session_exists(self, session_id, retrieve_past = True):
        return self.get_user(session_id, retrieve_past = retrieve_past) is not None

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

