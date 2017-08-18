from __future__ import print_function

import time
from flask import Flask, session, url_for
from flask_debugtoolbar import DebugToolbarExtension
from weblablib import WebLab, requires_active, weblab_user, poll

app = Flask(__name__)

# XXX: IMPORTANT SETTINGS TO CHANGE
app.config['SECRET_KEY'] = 'something random' # e.g., run: os.urandom(32) and put the output here
app.config['WEBLAB_USERNAME'] = 'weblabdeusto' # This is the http_username you put in WebLab-Deusto
app.config['WEBLAB_PASSWORD'] = 'password'  # This is the http_password you put in WebLab-Deusto

# XXX You should change...
# Use different cookie names for different labs
app.config['SESSION_COOKIE_NAME'] = 'lab'
# app.config['WEBLAB_UNAUTHORIZED_LINK'] = 'https://weblab.deusto.es/weblab/' # Your own WebLab-Deusto URL

# The URL for this lab (e.g., you might have two labs, /lab1 and /lab2 in the same server)
app.config['SESSION_COOKIE_PATH'] = '/lab'
# The session_id is stored in the Flask session. You might also use a different name
app.config['WEBLAB_SESSION_ID_NAME'] = 'lab_session_id'


# These are optional parameters
# Flask-Debug: don't intercept redirects (go directly)
app.config['DEBUG_TB_INTERCEPT_REDIRECTS'] = False
# app.config['WEBLAB_BASE_URL'] = '' # If you want the weblab path to start by /foo/weblab, you can put '/foo'
# app.config['WEBLAB_REDIS_URL'] = 'redis://localhost:6379/0' # default value
# app.config['WEBLAB_REDIS_BASE'] = 'lab1' # If you have more than one lab in the same redis database
# app.config['WEBLAB_CALLBACK_URL'] = '/lab/public' # If you don't pass it in the creator
# app.config['WEBLAB_TIMEOUT'] = 15 # in seconds, default value
# app.config['WEBLAB_SCHEME'] = 'https'

weblab = WebLab(app, callback_url='/lab/public')
toolbar = DebugToolbarExtension(app)

@weblab.initial_url
def initial_url():
    """
    This returns the landing URL (e.g., where the user will be forwarded).
    """
    return url_for('.lab')

@weblab.on_start
def on_start(client_data, server_data):
    """
    In this code, you can do something to setup the experiment. It is
    called for every user, before they start using it.
    """
    print("New user!")
    print(weblab_user)

@weblab.on_dispose
def on_stop():
    """
    In this code, you can do something to clean up the experiment. It is
    guaranteed to be run.
    """
    print("User expired. Here you should clean resources")
    print(weblab_user)

@app.route('/lab/')
@requires_active()
def lab():
    """
    This is your code. If you provide @requires_active to any other URL, it is secured.
    """
    user = weblab_user
    return "Hello %s. You didn't poll in %.2f seconds (timeout configured to %s). Total time left: %s" % (user.username, user.time_without_polling, weblab.timeout, user.time_left)

@app.route("/")
def index():
    return "<html><head></head><body><a href='{}'>Access to the lab</a></body></html>".format(url_for('.lab'))


if __name__ == '__main__':
    print("Run the following:")
    print()
    print(" (optionally) $ export FLASK_DEBUG=1")
    print(" $ export FLASK_APP={}".format(__file__))
    print(" $ flask run")
    print()

