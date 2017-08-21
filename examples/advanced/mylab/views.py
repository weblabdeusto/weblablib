from flask import Blueprint, url_for, render_template, jsonify, session, current_app

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
    # This method generates a random identifier and stores it in Flask's session object
    # For any request coming from the client, we'll check it. This way, we avoid
    # CSRF attacks (check https://en.wikipedia.org/wiki/Cross-site_request_forgery )
    session['csrf'] = weblab.create_token()

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

    task_id = session.get('programming_task')
    if task_id:
        task = weblab.get_task(task_id)
        current_app.logger.debug("Current programming task status: ", task.status)
        current_app.logger.debug("Current programming task result: ", task.result)
        current_app.logger.debug("Current programming task error: ", task.error)

    return jsonify(error=False, lights=lights, microcontroller=microcontroller, time_left=weblab_user.time_left)



@main_blueprint.route('/lights/<int:number>', methods=['POST'])
@requires_active
def light(number):
    # Check that number is valid
    if number in range(LIGHTS):
        return jsonify(error=True, message="Invalid light number")

    request_data, error_message = _get_request_data()
    if error_message:
        return error_message

    # Turn on light
    switch_light(number, request_data.get('state'))
    return status()



@main_blueprint.route('/microcontroller', methods=['POST'])
@requires_active
def microcontroller():
    request_data, error_message = _get_request_data()
    if error_message:
        return error_message

    code = request_data.get('code')

    running_tasks = weblab.get_running_tasks()
    if len(running_tasks):
        return jsonify(error=True, message="Other tasks being run")

    task = program_device.delay(code)

    # Playing with a task:
    current_app.logger.debug("New task! {}".format(task.task_id))
    current_app.logger.debug(" - Name: {}".format(task.name))
    current_app.logger.debug(" - Status: {}".format(task.status))

    # Result and error will be None unless status is 'done' or 'failed'
    current_app.logger.debug(" - Result: {}".format(task.result))
    current_app.logger.debug(" - Error: {}".format(task.error))

    session['programming_task'] = task.task_id

    return status()



#######################################################
# 
#   Other functions
# 

def _get_request_data():
    """
    Get JSON data. If it's invalid or not a dict, return an error. 
    Then check CSRF. If invalid, return an error. Otherwise, return the data.

    The response is (data, error_message). If error_message is None, it's fine.
    """
    request_data = request.get_json(force=True, silent=True)
    if not request_data:
        return None, jsonify(error=True, message="Invalid POST data (no JSON?)")

    if not isinstance(request_data, dict):
        return None, jsonify(error=True, message="Expected dictionary")

    if not _check_csrf(request_data):
        return None, jsonify(error=True, message="Invalid CSRF")

    return request_data, None

def _check_csrf(request_data):
    expected = session.get('csrf')
    if not expected:
        current_app.logger.warning("No CSRF in session. Calling method before loading index?")
        return False

    obtained = request_data.get('csrf')
    if not obtained:
        # No CSRF passed.
        current_app.logger.warning("Missing CSRF in provided data")
        return False
    
    return expected == obtained
