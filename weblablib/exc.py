#####################################################################################
#
#   Exceptions
#

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

