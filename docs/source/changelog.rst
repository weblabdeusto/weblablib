.. _changelog:

Changelog
=========

Version 0.4
-----------

General
^^^^^^^

 * Added ``WEBLAB_NO_THREAD`` which is equivalent to ``WEBLAB_AUTOCLEAN_THREAD=False`` and ``WEBLAB_TASK_THREADS_PROCESS=0``.

WebSockets
^^^^^^^^^^

 * Flask-SocketIO support through helpers

CLI changes
^^^^^^^^^^^

  * Similarly to other Flask projects, all the ``weblablib`` commands are in a single command group called ``weblab``. This way, in case of using multiple libraries which include their own commands (such as Flask-Migrate or Flask-Assets), the number of commands in the ``--help`` are low, and there is a low chance of collision (e.g., you might be using a celery-like system that also has a ``run-tasks`` command or a ``loop`` command). Therefore, since this version:

 
.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
**Before weblablib 0.4**          **Since weblablib 0.4**
================================= =========================================
``flask fake-new-user``           ``flask weblab fake new``
``flask fake-dispose``            ``flask weblab fake dispose``
``flask fake-status``             ``flask weblab fake status``
``flask loop``                    ``flask weblab loop``
``flask run-tasks``               ``flask weblab run-tasks``
``flask clean-expired-users``     ``flask weblab clean-expired-users``
================================= =========================================

 * When running ``flask weblab fake new`` the default behavior is to open a web browser. ``--open-browser`` removed, and a new ``--dont-open-browser`` flag is available.
 * Added ``flask weblab loop --reload``. If you change the source code of your application, it will restart the process automatically.

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
 * Add ``flask loop`` for running tasks and thread cleaners concurrently.

Version 0.2
-----------

Version 0.1 was uploaded to Pypi, etc., but was not production ready (no tests, docs, some bugs, etc.)
