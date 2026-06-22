# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import hashlib
import json

import six
from flask import current_app, has_app_context, has_request_context, request

from weblablib.config import ConfigurationKeys
from weblablib.users import CurrentUser
from weblablib.utils import _current_backend, _current_session_id, _current_timestamp


EVENT_NAME = 'weblab_session_lifecycle'


def _is_enabled():
    if not has_app_context():
        return False
    return current_app.config.get(ConfigurationKeys.WEBLAB_LOG_SESSION_LIFECYCLE, True)


def _is_true(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if not isinstance(value, six.string_types):
        return bool(value)
    return value in ('true', '1', 'True', 'TRUE')


def _as_seconds(value):
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _safe_getattr(obj, name):
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _session_id_hash(session_id):
    if not session_id:
        return None
    if not isinstance(session_id, six.binary_type):
        session_id = six.text_type(session_id).encode('utf8')
    return hashlib.sha256(session_id).hexdigest()[:16]


def _request_fields(status):
    if not has_request_context():
        return {}
    url_rule = getattr(request, 'url_rule', None)
    path = getattr(url_rule, 'rule', None) or request.path
    return {
        'path': path,
        'endpoint': request.endpoint,
        'method': request.method,
        'status': status,
    }


def classify_expiry_reason(user, weblab=None, now=None):
    if now is None:
        now = _current_timestamp()

    if _is_true(_safe_getattr(user, 'exited')):
        return 'user_exited'

    max_date = _safe_getattr(user, 'max_date')
    try:
        if max_date is not None and float(max_date) <= now:
            return 'time_limit_reached'
    except (TypeError, ValueError):
        pass

    timeout = _safe_getattr(weblab, 'timeout')
    last_poll = _safe_getattr(user, 'last_poll')
    try:
        if timeout and float(timeout) > 0 and last_poll is not None:
            if now - float(last_poll) >= float(timeout):
                return 'inactivity_timeout'
    except (TypeError, ValueError):
        pass

    return 'unknown_expiry'


def _anonymous_rejection_reason():
    session_id = None
    try:
        session_id = _current_session_id()
    except Exception:
        session_id = None
    if session_id:
        return 'anonymous_session_not_found', session_id
    return 'anonymous_no_session_cookie', None


def _base_event(action, user=None, reason=None, status=None, source=None, weblab=None):
    now = _current_timestamp()
    session_id = _safe_getattr(user, 'session_id')

    event = {
        'event': EVENT_NAME,
        'action': action,
        'reason': reason,
        'session_id_hash': _session_id_hash(session_id),
        'experiment_name': _safe_getattr(user, 'experiment_name'),
        'category_name': _safe_getattr(user, 'category_name'),
        'experiment_id': _safe_getattr(user, 'experiment_id'),
        'lab_name': current_app.config.get('LAB_NAME') if has_app_context() else None,
        'environment': current_app.config.get('ENVIRONMENT') if has_app_context() else None,
        'seconds_since_start': None,
        'seconds_since_last_poll': None,
        'seconds_past_max_date': None,
        'configured_timeout_seconds': _as_seconds(_safe_getattr(weblab, 'timeout')),
        'disposing_resources': _safe_getattr(user, 'disposing_resources'),
    }

    if source is not None:
        event['source'] = source

    start_date = _safe_getattr(user, 'start_date')
    last_poll = _safe_getattr(user, 'last_poll')
    max_date = _safe_getattr(user, 'max_date')

    try:
        if start_date is not None:
            event['seconds_since_start'] = _as_seconds(now - float(start_date))
    except (TypeError, ValueError):
        pass

    try:
        if last_poll is not None:
            event['seconds_since_last_poll'] = _as_seconds(now - float(last_poll))
    except (TypeError, ValueError):
        pass

    try:
        if max_date is not None:
            event['seconds_past_max_date'] = _as_seconds(max(0, now - float(max_date)))
    except (TypeError, ValueError):
        pass

    event.update(_request_fields(status))

    return event


def _emit_event(event):
    if not _is_enabled():
        return False
    try:
        current_app.logger.info(json.dumps(event, sort_keys=True))
    except Exception:
        try:
            current_app.logger.warning("Could not emit WebLab session lifecycle event", exc_info=True)
        except Exception:
            pass
        return False
    return True


def emit_protected_request_rejected(user, status, weblab=None):
    if not _is_enabled():
        return False

    if _safe_getattr(user, 'is_anonymous'):
        reason, session_id = _anonymous_rejection_reason()
        event = _base_event('protected_request_rejected', user=None, reason=reason,
                            status=status, weblab=weblab)
        event['session_id_hash'] = _session_id_hash(session_id)
        return _emit_event(event)

    reason = classify_expiry_reason(user, weblab=weblab)
    event = _base_event('protected_request_rejected', user=user, reason=reason,
                        status=status, weblab=weblab)
    return _emit_event(event)


def emit_expiry_detected(user, weblab=None, source=None, reason=None):
    if not _is_enabled() or not isinstance(user, CurrentUser):
        return False

    session_id = _safe_getattr(user, 'session_id')
    if not session_id:
        return False

    try:
        if not _current_backend().mark_session_lifecycle_event_once(session_id, 'expiry_detected'):
            return False
    except Exception:
        current_app.logger.warning("Could not mark WebLab session lifecycle event", exc_info=True)
        return False

    reason = reason or classify_expiry_reason(user, weblab=weblab)
    event = _base_event('expiry_detected', user=user, reason=reason, source=source, weblab=weblab)
    return _emit_event(event)


def emit_session_disposed(user, weblab=None, source=None, reason=None):
    if not _is_enabled():
        return False
    reason = reason or classify_expiry_reason(user, weblab=weblab)
    event = _base_event('disposed', user=user, reason=reason, source=source, weblab=weblab)
    return _emit_event(event)
