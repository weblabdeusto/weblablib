import os

class Config(object):
    DEBUG = False
    DEVELOPMENT = False
    TESTING = False

    # IMPORTANT: You should wrap this script and provide an:
    #
    # export SECRET_KEY='something-fixed-but-random'
    #
    # in the script where you run this code (for example, in wsgi_app.py).
    # This way, you will always have the same SECRET_KEY, and therefore 
    # the same session regardless server restarts.
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32)

    # You should also store these credentials somewhere safer, like in the
    # same script as in the SECRET_KEY (in wsgi_app.py, not here)
    WEBLAB_USERNAME = os.environ.get('WEBLAB_USERNAME') or 'weblabdeusto'
    WEBLAB_PASSWORD = os.environ.get('WEBLAB_PASSWORD') or 'password'

    # If an unauthorized user comes in, redirect him to this link
    WEBLAB_UNAUTHORIZED_LINK = 'https://developers.labsland.com/weblablib/'

    # Alternatively, you can establish a template that will be rendered
    # WEBLAB_UNAUTHORIZED_TEMPLATE = 'unauthorized.html'

    # These URLs should change to customize your lab:
    WEBLAB_CALLBACK_URL = '/mylab/callback'
    SESSION_COOKIE_NAME = 'mylab'
    SESSION_COOKIE_PATH = '/'
    WEBLAB_SESSION_ID_NAME = 'mylab'
    WEBLAB_REDIS_BASE = 'mylab'

    # If you put this, for example, then you should configure
    # WebLab-Deusto to use http://<lab-server>/foo/weblab/
    WEBLAB_BASE_URL = '/foo'

    # Other parameters (and default values):
    #
    # WEBLAB_TIMEOUT = 15 # If the user doesn't reply in 15 seconds, consider expired
    # WEBLAB_REDIS_URL = 'redis://localhost:6379/0'
    # WEBLAB_TASK_EXPIRES = 3600 # Time to expire the session results
    # WEBLAB_AUTOPOLL = True # Every method calls poll()
    # WEBLAB_AUTOCLEAN_THREAD = True # Have a thread in each process cleaning automatically
    # WEBLAB_TASK_THREADS_PROCESS = 1 # How many threads per process will be running tasks
    # WEBLAB_EXPIRED_USERS_TIMEOUT = 3600 # How long an expired user can be before kicked out


class DevelopmentConfig(Config):
    DEBUG = True
    DEVELOPMENT = True
    DEBUG_TB_INTERCEPT_REDIRECTS = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'shared_secret_key'

class TestingConfig(Config):
    TESTING = True

class ProductionConfig(Config):
    # WEBLAB_SCHEME = 'https'
    pass

config = {
    'default': ProductionConfig,
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
}
