from __future__ import unicode_literals, print_function, division

import time
from flask import Flask
from flask_debugtoolbar import DebugToolbarExtension

from weblablib import WebLab

from config import config

weblab = WebLab()
toolbar = DebugToolbarExtension()

def create_app(config_name):
    app = Flask(__name__)
    config_class = config[config_name]
    print("{}: Using config: {}".format(time.asctime(), config_class.__name__))
    app.config.from_object(config_class)

    weblab.init_app(app)
    toolbar.init_app(app)

    from .views import main_blueprint
    app.register_blueprint(main_blueprint)

    return app
