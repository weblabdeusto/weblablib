from flask import Blueprint, url_for, render_template, jsonify, session
from mylab import weblab
from mylab.hardware import program_device, is_light_on, get_microcontroller_state, switch_light, LIGHTS

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

@main_blueprint.route('/status')
@requires_active()
def status():
    "Return the status of the board"
    lights = {}
    microcontroller = {}
    
    for light in range(LIGHTS):
        lights['light-{}'.format(light)] = is_light_on(light)

    microcontroller = get_microcontroller_state()

    return jsonify(lights=lights, microcontroller=microcontroller, time_left=weblab_user.time_left)

@main_blueprint.route('/lights/<number>', methods=['POST'])
@requires_active
def light(number):
    pass

@main_blueprint.route('/microcontroller', methods=['POST'])
@requires_active
def microcontroller():
    task = program_device.delay('code')
    pass


