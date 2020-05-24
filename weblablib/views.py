# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import json
import time
import datetime
import traceback

from flask import Blueprint, Response, current_app, jsonify, request, url_for

from weblablib.exc import NotFoundError
from weblablib.config import ConfigurationKeys
from weblablib.utils import create_token, _to_timestamp, _current_backend, _current_weblab, _current_timestamp
from weblablib.users import CurrentUser, _set_weblab_user_cache
from weblablib.ops import status_time, update_weblab_user_data, dispose_user

weblab_blueprint = Blueprint("weblab", __name__) # pylint: disable=invalid-name

@weblab_blueprint.before_request
def _require_http_credentials():
    """
    All methods coming from WebLab-Deusto must be authenticated (except for /api). Here, it is used the
    WEBLAB_USERNAME and WEBLAB_PASSWORD configuration variables, which are used by WebLab-Deusto.
    Take into account that this username and password authenticate the WebLab-Deusto system, not the user.
    For example, a WebLab-Deusto in institution A might have 'institutionA' as WEBLAB_USERNAME and some
    randomly generated password as WEBLAB_PASSWORD.
    """
    # Don't require credentials in /api
    if request.url.endswith('/api'):
        return None

    auth = request.authorization
    if auth:
        provided_username = auth.username
        provided_password = auth.password
    else:
        provided_username = provided_password = None

    expected_username = current_app.config[ConfigurationKeys.WEBLAB_USERNAME]
    expected_password = current_app.config[ConfigurationKeys.WEBLAB_PASSWORD]
    if provided_username != expected_username or provided_password != expected_password:
        if request.url.endswith('/test'):
            error_message = "Invalid credentials: no username provided"
            if provided_username:
                error_message = "Invalid credentials: wrong username provided. Check the lab logs for further information."
            return Response(json.dumps(dict(valid=False, error_messages=[error_message])), status=401, headers={'WWW-Authenticate':'Basic realm="Login Required"', 'Content-Type': 'application/json'})

        if expected_username:
            current_app.logger.warning("Invalid credentials provided to access {}. Username provided: {!r} (expected: {!r})".format(request.url, provided_username, expected_username))

        return Response(response=("You don't seem to be a WebLab-Instance"), status=401, headers={'WWW-Authenticate':'Basic realm="Login Required"'})

    return None



@weblab_blueprint.route("/sessions/api")
def _api_version():
    """
    Just return the api version as defined. If in the future we support new features, they will fall under new API versions. If the report version is 1, it will only consume whatever was provided in version 1.
    """
    return jsonify(api_version="1")



@weblab_blueprint.route("/sessions/test")
def _test():
    """
    Just return that the settings are right. For example, if the password was incorrect, then something else will fail
    """
    return jsonify(valid=True)



@weblab_blueprint.route("/sessions/", methods=['POST'])
def _start_session():
    """
    Create a new session: WebLab-Deusto is telling us that a new user is coming. We register the user in the backend system.
    """
    request_data = request.get_json(force=True)
    return jsonify(**_process_start_request(request_data))

def _process_start_request(request_data):
    """ Auxiliar method, called also from the Flask CLI to fake_user """
    client_initial_data = request_data['client_initial_data']
    server_initial_data = request_data['server_initial_data']

    # Parse the initial date + assigned time to know the maximum time
    start_date_timestamp = server_initial_data.get('priority.queue.slot.start.timestamp')
    if start_date_timestamp: # if the time is available in timestamp, use it
        start_date = datetime.datetime.fromtimestamp(float(start_date_timestamp))
    else:
        # Otherwise, to keep backwards compatibility, assume that it's in the same timezone
        # as we are
        start_date_str = server_initial_data['priority.queue.slot.start']
        start_date_str, microseconds = start_date_str.split('.')
        difference = datetime.timedelta(microseconds=int(microseconds))
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S") + difference

    slot_length = float(server_initial_data['priority.queue.slot.length'])
    max_date = start_date + datetime.timedelta(seconds=slot_length)
    locale = server_initial_data.get('request.locale')
    full_name = server_initial_data['request.full_name']

    experiment_name = server_initial_data['request.experiment_id.experiment_name']
    category_name = server_initial_data['request.experiment_id.category_name']
    experiment_id = '{}@{}'.format(experiment_name, category_name)

    # Create a global session
    session_id = create_token()

    # Prepare adding this to backend
    user = CurrentUser(session_id=session_id, back=request_data['back'],
                       last_poll=_current_timestamp(), max_date=float(_to_timestamp(max_date)),
                       username=server_initial_data['request.username'],
                       username_unique=server_initial_data['request.username.unique'],
                       exited=False, data={}, locale=locale,
                       full_name=full_name, experiment_name=experiment_name,
                       experiment_id=experiment_id, category_name=category_name,
                       request_client_data=client_initial_data,
                       request_server_data=server_initial_data,
                       start_date=float(_to_timestamp(start_date)))

    backend = _current_backend()

    backend.add_user(session_id, user, expiration=30 + int(float(server_initial_data['priority.queue.slot.length'])))


    kwargs = {}
    scheme = current_app.config.get(ConfigurationKeys.WEBLAB_SCHEME)
    if scheme:
        kwargs['_scheme'] = scheme

    weblab = _current_weblab()
    if weblab._on_start:
        _set_weblab_user_cache(user)
        weblab._set_session_id(session_id)
        try:
            data = weblab._on_start(client_initial_data, server_initial_data)
        except Exception as error:
            traceback.print_exc()
            current_app.logger.warning("Error calling _on_start: {}".format(error), exc_info=True)
            try:
                dispose_user(session_id, waiting=True)
            except Exception as nested_error:
                traceback.print_exc()
                current_app.logger.warning("Error calling _on_dispose after _on_start failed: {}".format(nested_error), exc_info=True)

            return dict(error=True, message="Error initializing laboratory")
        else:
            if data:
                user.data = data
            user.data.store_if_modified()
            update_weblab_user_data(response=None)

    link = url_for('weblab_callback_url', session_id=session_id, _external=True, **kwargs)
    return dict(url=link, session_id=session_id)



@weblab_blueprint.route('/sessions/<session_id>/status')
def _status(session_id):
    """
    This method provides the current status of a particular
    user.
    """
    return jsonify(should_finish=status_time(session_id))

@weblab_blueprint.route('/sessions/status/multiple', methods=['POST'])
def _multiple_status():
    """
    This method provides the current status of a bulk of
    users.
    """
    t0 = time.time()

    request_data = request.get_json(silent=True, force=True)
    if request_data is None or request_data.get('session_ids') is None:
        return jsonify(success=False, error_code='missing-parameters', error_human="session_ids expected in POST JSON")

    # If the user passes a 'timeout' which is a float, calculate the
    # future timeout, which is the moment when this method should stop
    # processing requests.
    try:
        timeout = float(request_data.get('timeout'))
        future_timeout = t0 + timeout
        if future_timeout <= t0:
            future_timeout = None
    except:
        future_timeout = None

    status = {
        # session_id: status
    }

    for session_id in request_data['session_ids']:
        status[session_id] = status_time(session_id)

        if future_timeout is not None and time.time() > future_timeout:
            # Do not process more requests, timeout happened
            break

    return jsonify(status=status)


@weblab_blueprint.route('/sessions/<session_id>', methods=['POST'])
def _dispose_experiment(session_id):
    """
    This method is called to kick one user out. This may happen
    when an administrator defines so, or when the assigned time
    is over.
    """
    request_data = request.get_json(force=True)
    if 'action' not in request_data:
        return jsonify(message="Unknown op")

    if request_data['action'] != 'delete':
        return jsonify(message="Unknown op")

    try:
        dispose_user(session_id, waiting=True)
    except NotFoundError:
        return jsonify(message="Not found")

    return jsonify(message="Deleted")
