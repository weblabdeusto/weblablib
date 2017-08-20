from __future__ import unicode_literals, print_function, division

import time
from flask import Flask
from flask_debugtoolbar import DebugToolbarExtension
from flask_redis import FlaskRedis

from weblablib import WebLab

from config import config

weblab = WebLab()
toolbar = DebugToolbarExtension()
redis = FlaskRedis()

def create_app(config_name):
    app = Flask(__name__)
    config_class = config[config_name]
    print("{}: Using config: {}".format(time.asctime(), config_class.__name__))
    app.config.from_object(config_class)

    # Initialize the plug-ins (as WebLab)
    weblab.init_app(app)
    toolbar.init_app(app)
    redis.init_app(app)

    # Register the views
    from .views import main_blueprint
    app.register_blueprint(main_blueprint)

    # app is a valid Flask app
    return app

