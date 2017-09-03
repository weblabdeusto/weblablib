from __future__ import unicode_literals, print_function, division

import time
from flask import Flask, request, session, has_request_context
from flask_assets import Environment
from flask_babel import Babel
from flask_debugtoolbar import DebugToolbarExtension
from flask_redis import FlaskRedis
from flask_socketio import SocketIO

from weblablib import WebLab, weblab_user

from config import config

# weblablib
weblab = WebLab()

# other extensions
babel = Babel()
assets = Environment()
toolbar = DebugToolbarExtension()
redis = FlaskRedis(decode_responses=True)
socketio = SocketIO()

def create_app(config_name):
    """
    This is a factory method. You can provide different setting names
    (development, testing, production) and it will initialize a Flask
    app with those settings. Check 'config.py' for further information.
    """
    app = Flask(__name__)
    config_class = config[config_name]
    print("{}: Using config: {}".format(time.asctime(), config_class.__name__))
    app.config.from_object(config_class)

    # Initialize the Flask plug-ins (including WebLab)
    weblab.init_app(app)
    toolbar.init_app(app)
    redis.init_app(app)
    babel.init_app(app)
    assets.init_app(app)
    socketio.init_app(app, message_queue='redis://', channel='mylab')

    # Register the views
    from .views import main_blueprint
    app.register_blueprint(main_blueprint)

    from .hardware import clean_resources

    @app.cli.command('clean-resources')
    def clean_resources_command():
        """
        You can now run:
        $ flask clean-resources

        And it will call the clean_resources method. Imagine that you have a
        resource which is telling a motor to move against a wall, and suddenly
        the computer where this code runs is restarted (due to an external
        factor). You want that the server, as soon as it starts, stops that
        procedure.

        Doing this, in the launching script you can call "flask clean-resoures"
        so every time you run the lab, first it stops any ongoing action.
        """
        clean_resources()

    # app is a valid Flask app
    return app

@babel.localeselector
def get_locale():
    """Defines what's the current language for the user. It uses different approaches"""
    supported_languages = [ translation.language for translation in babel.list_translations() ]

    locale = None
    
    # This is used also from tasks (which are not in a context environment)
    if has_request_context():
        # If user accesses http://localhost:5000/?locale=es force it to Spanish, for example
        locale = request.args.get('locale', None)
        if locale not in supported_languages:
            locale = None

    # If not explicitly stated (?locale=something), use whatever WebLab-Deusto said
    if locale is None:
        locale = weblab_user.locale or None
        if locale not in supported_languages:
            locale = None

    if locale is None:
        locale = weblab_user.data.get('locale')

    # Otherwise, check what the web browser is using (the web browser might state multiple
    # languages)
    if has_request_context():
        if locale is None:
            locale = request.accept_languages.best_match(supported_languages)

    # Otherwise... use the default one (English)
    if locale is None:
        locale = 'en'

    # Store the decision so next time we don't need to check everything again
    weblab_user.data['locale'] = locale
    return locale

