import time

from flask import Blueprint, url_for, render_template, jsonify, session, current_app, request

from mylab import weblab
from mylab.hardware import program_device, is_light_on, get_microcontroller_state, switch_light, LIGHTS

from weblablib import requires_active, requires_login, weblab_user, logout

main_blueprint = Blueprint('main', __name__)

@weblab.initial_url
def initial_url():
    """
    Where do we send the user when a new user comes?
    """
    return url_for('main.index')



@main_blueprint.route('/')
@requires_login
def index():
    # This method generates a random identifier and stores it in Flask's session object
    # For any request coming from the client, we'll check it. This way, we avoid
    # CSRF attacks (check https://en.wikipedia.org/wiki/Cross-site_request_forgery )
    session['csrf'] = weblab.create_token()

    return render_template("index.html")

@main_blueprint.route('/status')
@requires_active
def status():
    "Return the status of the board"
    lights = {}
    microcontroller = {}

    for light in range(LIGHTS):
        lights['light-{}'.format(light + 1)] = is_light_on(light)

    microcontroller = get_microcontroller_state()

    task = weblab.get_task(program_device)
    if task:
        current_app.logger.debug("Current programming task status: %s (error: %s; result: %s)", task.status, task.error, task.result)

    return jsonify(error=False, lights=lights, microcontroller=microcontroller, time_left=weblab_user.time_left)

@main_blueprint.route('/logout', methods=['POST'])
@requires_login
def logout_view():
    if not _check_csrf():
        return jsonify(error=True, message="Invalid JSON")

    if weblab_user.active:
        logout()

    return jsonify(error=False)

@main_blueprint.route('/lights/<int:number>', methods=['POST'])
@requires_active
def light(number):
    # light number is 1..10
    internal_number = number - 1

    # Check that number is valid
    if internal_number not in range(LIGHTS):
        return jsonify(error=True, message="Invalid light number")

    if not _check_csrf():
        return jsonify(error=True, message="Invalid CSRF")

    # Turn on light
    switch_light(internal_number, request.values.get('state', 'false') == 'true')
    return status()



@main_blueprint.route('/microcontroller', methods=['POST'])
@requires_active
def microcontroller():
    if not _check_csrf():
        return jsonify(error=True, message="Invalid CSRF")

    code = request.values.get('code') or "code"

    # If there are running tasks, don't let them send the program
    if len(weblab.running_tasks):
        return jsonify(error=True, message="Other tasks being run")

    task = program_device.delay(code)

    # Playing with a task:
    current_app.logger.debug("New task! {}".format(task.task_id))
    current_app.logger.debug(" - Name: {}".format(task.name))
    current_app.logger.debug(" - Status: {}".format(task.status))

    # Result and error will be None unless status is 'done' or 'failed'
    current_app.logger.debug(" - Result: {}".format(task.result))
    current_app.logger.debug(" - Error: {}".format(task.error))

    return status()



#######################################################
#
#   Other functions
#

def _check_csrf():
    expected = session.get('csrf')
    if not expected:
        current_app.logger.warning("No CSRF in session. Calling method before loading index?")
        return False

    obtained = request.values.get('csrf')
    if not obtained:
        # No CSRF passed.
        current_app.logger.warning("Missing CSRF in provided data")
        return False

    return expected == obtained
