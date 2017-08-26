.. _advanced:

Advanced features
=================

Tasks
-----

When developing a remote laboratory, there are tasks that typically take a long time. For example, you might need to compile some code submitted by the user. Or you might run a task of a control laboratory that takes 20 seconds.

In general, if a task takes 0-2 seconds is fine to be run in a view. But other than that, it might be too long. For this reason, in **weblablib** you can define tasks, which will be run in other threads or processes.

Defining a task is quite easy. In ``hardware.py`` you can add something like:

.. code-block:: python

   @weblab.task()
   def program_device(contents):
       """ Programs a device. Typically takes 5-10 seconds """
       if weblab_user.time_left < 10:
           raise Exception("Error: user does not have "
                           "enough time to run it!")

       time.sleep(10) # In this case
       return len(contents)

From this point, you can run the synchronously:

.. code-block:: python

   code = "my-own-code"

   # This runs it in this thread,
   # exactly as if it was not a task
   result = program_device(code)

Or asynchronously (common when it's tasks) and play with the ``WebLabTask`` object:

.. code-block:: python

   # This other code runs it in a different
   # process
   task = program_device.delay(code)

   # The following is a string that you can store in
   # Flask session or in weblab_user.data
   task.task_id

   # 'submitted', 'running' or 'failed'/'done' if finished.
   task.status

   # These two attributes are None while 'submitted' or 'running'
   task.result # the result of the function
   task.error # the exception data, if an exception happened

If you store the ``task.task_id``, you can retrieve the task in other views or later on:

.. code-block:: python

   # With the task_id, you can later obtain it in the same view in
   # the future:
   task = weblab.get_task(task_id)

   # and then ask if it is still running or not, and obtain
   # the result. You can also run:
   if task.status == 'done':
       print(task.result)

At any point (including ``on_dispose``), you can see what tasks are still running:

.. code-block:: python

   for task in weblab.running_tasks:
        print(task.status)

Or all the tasks assigned in this session (finished or not):

.. code-block:: python

   for task in weblab.tasks:
        print(task.name, task.result)


When WebLab-Deusto calls to clean resources to your laboratory, **weblablib** will report
of whether all the tasks assigned to the current session have finished or not, and no
user will be assigned until the task is finished. So make sure that your task ends in time
so as to not consume time of other users, and avoid starting tasks when the
``weblab_user.time_left`` is too short.

Multiple laboratories in the same server
----------------------------------------

If you are running multiple laboratories in the same server, you should configure a different ``WEBLAB_REDIS_BASE`` value and/or ``WEBLAB_REDIS_URL``. **weblablib** relies on Redis to store the current status of the users and the laboratory, so if you run both in the default database with the default redis base name, there might be conflicts.

To avoid this, either you use a different database (by default in Redis there are 16 databases, so you can use ``redis://localhost:6379/1`` or ``redis://localhost:6379/2``), or you can use the same one but using ``WEBLAB_REDIS_BASE`` different (e.g., ``lab1`` and ``lab2`` ). This would be recommended so later if you need to debug what is in Redis you can clearly see that there are values starting by ``lab1:`` or by ``lab2:`` refering to one or the other.

Multiple laboratories through the same server
---------------------------------------------

If you have 3 Raspberry Pi with different laboratories running, and, at the same time, you have
a single server that proxies requests to all, you may face session problems. To avoid this, please
rely on the Flask session configuration variables, such as:

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``SESSION_COOKIE_NAME``           The name of the cookie. By default it's
                                  ``session``, so it's better to change it
                                  in each laboratory to ``lab1sess`` and
                                  ``lab2sess`` or similar.
``SESSION_COOKIE_PATH``           The path of the cookie. By default the 
                                  session cookie is stored in ``/``, but 
                                  this way you can make sure that if you put
                                  ``/lab1``, when the user goes to ``/lab2``,
                                  no problem will arise.
``SECRET_KEY``                    It is also recommendable that each lab have
                                  a different key. If everything else fails,
                                  at least the session created by other 
                                  laboratory will not affect to the present
                                  one.
================================= =========================================

Forbidden page
--------------

By default, if a new user comes to your laboratory, he will see a simple ``Access forbidden`` message. However, you can do two other things:

 #. Forward the user to a link by adding ``WEBLAB_UNAUTHORIZED_LINK`` to ``config``. For example, typically here you will put a link to your public WebLab-Deusto system. If a user bookmarks the laboratory, he will be redirected to your WebLab-Deusto so he authenticates. In other scenarios, you might point to LabsLand, to your LMS (e.g., Moodle) or similar.
 #. Display another website. You can create a template in the ``templates`` folder and use it by adding the ``WEBLAB_UNAUTHORIZED_TEMPLATE`` variable. If you set it to ``forbidden.html``, you will see it in WebLab-Deusto.

Timeout management
------------------

By default, if the user does not contact the laboratory in 15 seconds, it is assumed that the user left. You can configure this by managing the ``WEBLAB_TIMEOUT`` variable.

Also, an ``ExpiredUser`` exists only for an hour by default. If you want to extend this time, use the ``WEBLAB_EXPIRED_USERS_TIMEOUT`` variable. Similarly, if you want to delete from memory users as soon as possible, you can configure it to ``240`` seconds (3 minutes) or similar. It is not recommended to use smaller values or the users might not have the chance to return to the previuos system.

https
-----

If you want to force https, sometimes you may find that the URL returned does not use it because of a misconfiguration in the web server (e.g., nginx, apache). An easy way to fix it is by setting the configuration of ``WEBLAB_SCHEME`` to ``https``.

Processes vs. threads
---------------------

By default, weblablib creates a set of threads per process run, which are running tasks and cleaning threads. By default, 3 threads are dedicated to tasks, and 1 to cleaning expired sessions.

So if you run:

.. code-block:: shell

   gunicorn --bind 127.0.0.1:8080 -w 10 wsgi_app:application

For example, you'll be running 10 processes, and each of them 3 threads for tasks (30) and 1 thread for cleaning expired sessions. You can reduce the number of threads per process by changing ``WEBLAB_TASK_THREADS_PROCESS``.

Another approach (which is indeed cleaner) is to run no thread, and run the tasks, etc. outside. To do this, you can configure ``WEBLAB_TASK_THREADS_PROCESS`` to ``0``,  ``WEBLAB_AUTOCLEAN_THREAD`` to ``False``, and then run in parallel:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask clean-expired-users

And in another process:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask run-tasks

These two processes end immediately. You can run them in a loop outside, use ``cron`` or similar tools or so.

This way, the ``gunicorn`` processes will only manage web requests, and the external processes will run the tasks and clean expired users.

Base URL
--------

By default, everything is running in ``/``, and **weblablib** automatically generate ``/weblab/sessions/`` URLs. If you have more than
one lab in a public server (quite common if you have a single public IP for several laboratories), then you may have to play with ``SCRIPT_NAME``.

For example:

.. code-block:: shell

    SCRIPT_NAME=/lab1 gunicorn --bind 127.0.0.1:8080 -w 10 \
                      wsgi_app:application

And then in nginx or Apache configuring that https://yourserver/lab1 goes to http://localhost:8080/lab1 will work. In this case, you have to configure ``http_experiment_url`` to ``http://localhost:8080/lab1``. In some circumstances, you may also want to provide a base URL for weblab alone. In that case, you can use the ``WEBLAB_BASE`` url.

