from flask import Blueprint
from mylab import weblab

from weblablib import requires_active

main_blueprint = Blueprint('main', __name__)

@main_blueprint.route('/')
@requires_active
def index():
    return render_template("lab.html")

