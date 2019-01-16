# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import os
import time
import base64
import datetime

from flask import current_app

from weblablib.exc import WebLabNotInitializedError

def create_token(size=None):
    if size is None:
        size = 32
    tok = os.urandom(size)
    safe_token = base64.urlsafe_b64encode(tok).strip().replace(b'=', b'').replace(b'-', b'_')
    safe_token = safe_token.decode('utf8')
    return safe_token

def _current_weblab():
    if 'weblab' not in current_app.extensions:
        raise WebLabNotInitializedError("App not initialized with weblab.init_app()")
    return current_app.extensions['weblab']

def _current_backend():
    return _current_weblab()._backend

def _current_session_id():
    return _current_weblab()._session_id()

def _to_timestamp(dtime):
    return str(int(time.mktime(dtime.timetuple()))) + str(dtime.microsecond / 1e6)[1:]

def _current_timestamp():
    return float(_to_timestamp(datetime.datetime.now()))
