# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

class WebLabError(Exception):
    """Wraps all weblab exceptions"""
    pass

class NoContextError(WebLabError):
    """Wraps the fact that it is attempting to call an object like
    session outside the proper scope."""
    pass

class InvalidConfigError(WebLabError, ValueError):
    """Invalid configuration"""
    pass

class WebLabNotInitializedError(WebLabError):
    """Requesting a WebLab object when ``weblab.init_app`` has not been called."""
    pass

class TimeoutError(WebLabError):
    """When joining (:meth:`WebLabTask.join`) a task with a timeout, this error may arise"""
    pass

class AlreadyRunningError(WebLabError):
    """When creating a task (:meth:`WebLab.task`) with ``unique='global'`` or ``unique='user'``, the second thread/process attempting to run the same method will obtain this error"""
    pass

class NotFoundError(WebLabError, KeyError):
    pass
