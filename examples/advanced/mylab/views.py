from flask import Blueprint, url_for, render_template
from mylab import weblab

from weblablib import requires_active

main_blueprint = Blueprint('main', __name__)

@weblab.initial_url
def initial_url():
    """
    Where do we send the user when a new user comes?
    """
    return url_for('main.index')

@main_blueprint.route('/')
@requires_active()
def index():
    return render_template("index.html")

