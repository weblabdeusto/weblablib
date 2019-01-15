.. _changelog:

Changelog
=========


Version 0.5.0
-------------

Link: https://docs.labsland.com/weblablib/en/0.5.0/


Tasks
^^^^^

 * ``ensure_unique`` has been replaced by ``unique='global'``. This allows us to put also ``unique='user'`` for concurrent laboratories.

Bug fixes:
^^^^^^^^^^

 * If the ``on_dispose`` was long, it would happen that WebLab would consider the experiment already finished.


Version 0.4.1
-------------

Link: https://docs.labsland.com/weblablib/en/0.4.1/

Bug fixes:
^^^^^^^^^^

In some contexts, the poll message receives a temporary error (such as 502). In those cases we try a couple of seconds later instead of automatically kicking out the user.


Version 0.4
-----------

Link: https://docs.labsland.com/weblablib/en/0.4/

General
^^^^^^^

 * Added ``WEBLAB_NO_THREAD`` which is equivalent to ``WEBLAB_AUTOCLEAN_THREAD=False`` and ``WEBLAB_TASK_THREADS_PROCESS=0``.

Tasks
^^^^^

 * A ``WebLabTask`` supports ``.join()`` method. It defaults to ``.join(timeout=None, error_on_timeout=True)``,  raising an error, but can be configured with those parameters.
 * It also supports ``run_sync()``, with the optional named parameter ``timeout``. This guarantees that you can run tasks in a background process such as ``flask weblab loop``.
 * There is also now a ``stop()`` method and a ``stopping`` flag. If you call ``stop``, ``stopping`` will be ``True``. There is also a property called ``current_task_stopping``.
 * ``@weblab.task()`` now supports ``@weblab.task(ensure_unique=True)``. If multiple threads attempt to raise the same task, only one will run it (and the rest will fail)
 * New methods in ``WebLab``:
 
  * ``weblab.get_running_task(function_or_name)`` (which returns the any or ``None``; use with ``ensure_unique=True``) and ``webalb.get_running_tasks(func_or_name)`` to obtain all.
  * ``weblab.join_tasks(function_or_name, timeout=None, stop=False)`` which calls ``stop()`` if ``stop`` and joins all the tasks with that function (or name of function).

WebSockets
^^^^^^^^^^

 * Flask-SocketIO support through helpers:

   * ``socket_requires_login`` and ``socket_requires_active`` behave similar to ``requires_login`` and ``requires_active``; but calling ``disconnect`` of Flask-SocketIO
   * ``socket_weblab_user`` is equivalent to ``weblab_user``, but using it in real time without caching. This avoids the typical problems of a long-standing thread with WebSockets

Examples
^^^^^^^^

 * A new example, ``complete``, has been added. It includes:

   * Example of WebSocket support, including in a task in a different process.
   * Example of use of Flask-Babel for internationalization
   * Example of use of Flask-Assets for minimizing the static files


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

Link: https://docs.labsland.com/weblablib/en/0.3/

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

Link: https://docs.labsland.com/weblablib/en/0.2/

Version 0.1 was uploaded to Pypi, etc., but was not production ready (no tests, docs, some bugs, etc.)
