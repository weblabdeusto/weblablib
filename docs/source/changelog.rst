.. _changelog:

Changelog
=========

Version 0.3
-----------

 * Added ``weblab_user.locale`` for i18n processing.
 * Added ``weblab_user.experiment_name``, ``weblab_user.category_name`` and ``weblab_user.experiment_id`` as more metadata about the context on how the laboratory is used.
 * Added ``task.done``, ``task.failed``, ``task.finished``, ``task.running``, ``task.submitted`` so as to avoid playing with strings.
 * ``WEBLAB_CALLBACK_URL`` is now optional, and ``/callback`` by default.
 * Added ``current_task`` that can be called inside a task to get the ``task_id`` or update data.
 * Added ``current_task.data`` and ``current_task.update_data`` so as to update JSON-friendly data to measure the progress of the task.
 * Added ``@weblab.user_loader``. If set, you can later run say ``user = weblab_user.user``, and it returns a user (e.g., from your database)
 * Supported arguments on ``{{ weblab_poll_script() }}``: ``logout_on_close``, which logs out when you close the current window (by default ``False``); and ``callback`` if you want to be notified when the time has passed or an error occurs.

Version 0.2
-----------

Version 0.1 was uploaded to Pypi, etc., but was not production ready (no tests, docs, some bugs, etc.)
