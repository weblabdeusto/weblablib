# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import time
import json
import traceback

from flask import g

from weblablib.exc import NotFoundError
from weblablib.utils import _current_weblab, _current_backend, _current_session_id
from weblablib.users import ExpiredUser, CurrentUser, weblab_user, _set_weblab_user_cache

def status_time(session_id):
    weblab = _current_weblab()
    backend = weblab._backend
    user = backend.get_user(session_id)
    if isinstance(user, ExpiredUser) and user.disposing_resources:
        return 2 # Try again in 2 seconds

    if user.is_anonymous or not isinstance(user, CurrentUser):
        return -1

    if user.exited:
        return -1

    if weblab.timeout and weblab.timeout > 0:
        # If timeout is set to -1, it will never timeout (unless user exited)
        if user.time_without_polling >= weblab.timeout:
            return -1

    if user.time_left <= 0:
        return -1

    return min(weblab.poll_interval, int(user.time_left))

def store_initial_weblab_user_data():
    session_id = _current_session_id()
    if session_id:
        backend = _current_backend()
        current_user = backend.get_user(session_id)
        if current_user.active:
            g._initial_data = json.dumps(current_user.data)

def update_weblab_user_data(response):
    # If a developer does:
    #
    # weblab_user.data["foo"] = "bar"
    #
    # Nothing is triggered in Redis. For this reason, after each request
    # we check that the data has changed or not.
    #
    session_id = _current_session_id()
    backend = _current_backend()
    if session_id:
        if weblab_user.active:
            # If there was no data in the beginning
            # OR there was data in the beginning and now it is different,
            # only then modify the current session
            if not hasattr(g, '_initial_data') or g._initial_data != json.dumps(weblab_user.data):
                backend.update_data(session_id, weblab_user.data)

    return response


def dispose_user(session_id, waiting):
    backend = _current_backend()
    user = backend.get_user(session_id)
    if user.is_anonymous:
        raise NotFoundError()

    if isinstance(user, CurrentUser):
        current_expired_user = user.to_expired_user()
        deleted = backend.delete_user(session_id, current_expired_user)

        if deleted:
            try:
                weblab = _current_weblab()
                weblab._set_session_id(session_id)
                if weblab._on_dispose:

                    _set_weblab_user_cache(user)
                    try:
                        weblab._on_dispose()
                    except Exception:
                        traceback.print_exc()
                    update_weblab_user_data(response=None)
            finally:
                backend.finished_dispose(session_id)

            unfinished_tasks = backend.get_unfinished_tasks(session_id)
            for task_id in unfinished_tasks:
                unfinished_task = weblab.get_task(task_id)
                if unfinished_task:
                    unfinished_task.stop()

            while unfinished_tasks:
                unfinished_tasks = backend.get_unfinished_tasks(session_id)
                time.sleep(0.1)

            backend.clean_session_tasks(session_id)

            backend.report_session_deleted(session_id)

    if waiting:
        # if another thread has started the _dispose process, it might take long
        # to process it. But this (sessions) is the one that tells WebLab-Deusto
        # that someone else can enter in this laboratory. So we should wait
        # here until the process is over.

        while not backend.is_session_deleted(session_id):
            # In the future, instead of waiting, this could be returning that it is still finishing
            time.sleep(0.1)
