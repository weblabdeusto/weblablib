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

   # a string 'submitted', 'running' or 'failed'/'done' if finished.
   task.status

   task.submitted  # bool: not yet started by a worker
   task.running    # bool: started by a worker, not yet finished
   task.done       # bool: finished successfully
   task.failed     # bool: finished with error
   task.finished   # task.failed or task.done

   # These two attributes are None while 'submitted' or 'running'
   task.result # the result of the function
   task.error # the exception data, if an exception happened

   # Join operations
   task.join(timeout=5, error_on_timeout=False) # wait 5 seconds, otherwise do nothing
   task.join(timeout=5, error_on_timeout=True) # wait 5 seconds, otherwise raise error
   task.join() # wait until it finishes

   # Stop flag
   task.stop() # Raises a flag
   task.stopping # True or False

If you store the ``task.task_id``, you can retrieve the task in other views or later on:

.. code-block:: python

   # With the task_id, you can later obtain it in the same view in
   # the future:
   task = weblab.get_task(task_id)

   # and then ask if it is still running or not, and obtain
   # the result. You can also run:
   if task.done:
       print(task.result)


You can also block the current thread until the task is run, by running:

.. code-block:: python

   task = program_device.run_sync()

   # or 

   task = program_device.run_sync(timeout=5)

   # then, as in any task:

   task.result
   task.error

This is essentially equivalent to do:

.. code-block:: python

   task = program_device.delay()
   task.join(timeout=5)

The reason for doing this is for making sure that certain code runs in the task threads. This can be useful for resources, as explained in :ref:`advanced_proceses_resources`.

At any point (including ``on_dispose``), you can see what tasks are still running:

.. code-block:: python

   for task in weblab.running_tasks:
        print(task.status)

Or all the tasks assigned in this session (finished or not):

.. code-block:: python

   for task in weblab.tasks:
        print(task.name, task.result)

Also, inside the task, you can get information and change information about the task:

.. code-block:: python
   
   from weblablib import current_task, current_task_stopping

   @weblab.task()
   def program_device(path):
       # ...
       current_task.task_id
       print(current_task.data)
       current_task.update_data({ 'a': 'b' })

       if current_task.stopping:
           # ...

       if current_task_stopping:
           # ...

And obtain this information from outside:

.. code-block:: python

   task = weblab.get_task(task_id)
   print(task.data['a'])

When WebLab-Deusto calls to clean resources to your laboratory, **weblablib** will report
of whether all the tasks assigned to the current session have finished or not, and no
user will be assigned until the task is finished. So make sure that your task ends in time
so as to not consume time of other users, and avoid starting tasks when the
``weblab_user.time_left`` is too short.

WebSockets with Flask-SocketIO
------------------------------

WebSockets are a technology that allows the server to *push* data to the client. This is very interesting from the remote laboratory perspective: you can push data from the server to the client, which is something that you may want many circumstances.

So as to support ``Flask-SocketIO``, there are a couple of things you have to take into account, though:

Threading model
^^^^^^^^^^^^^^^

``weblablib`` by default relies on the classic threading model, while ``Flask-SocketIO`` relies on gevent or eventlet. This means that, in a regular app you can simply do:

.. code-block:: bash

   $ flask run

And it will run the threads. When using ``Flask-SocketIO``, you need to run a modified version of ``flask run``, which is a simple script stored in a file such as ``run_debug.py`` like:

.. code-block:: python

	from gevent import monkey
	monkey.patch_all()

	import os
	from mylab import create_app, socketio
	app = create_app('development')
	socketio.run(app)

This way, one process will be running with ``gevent`` model.

Additionally, you can optionally run another process: 

.. code-block:: bash

   $ flask weblab loop
   
This process does not need to use gevent or eventlet. It may, but it is not required.

If you use a second process (``flask weblab loop``), it is important that when you initialize Flask-SocketIO, you use a message_queue:

.. code-block:: python

   socketio.init_app(app, message_queue='redis://', channel='mylab')

This way, both processes will be able to exchange messages with the web browser.

WebLab Tasks
^^^^^^^^^^^^

The support of SocketIO is perfectly compatible with WebLab Tasks (both in the same process or in a different one), as long as the points covered in the previous section are taken into account.

Authentication model
^^^^^^^^^^^^^^^^^^^^

``weblablib`` provides ``requires_active`` and ``requires_login``. However, these two methods are intended to be used in regular Flask views, which are typically short operations, and where the operations expect a regular HTTP response.

In WebSockets, the model is different:
 * Once you create a socket connection, it is virtually in the same thread on the server side until it is disconnected. It may happen that the user connects the WebSocket in the beginning (while he still has 2 minutes to use the laboratory), and then keep using the socket for more time. Using ``weblab_user`` will always return the same result since it is cached.
 * The way to finish a connection is by calling ``disconnect``, not by returning an HTTP Response.

For these reasons, ``weblablib`` provides the following three methods and properties:

 * ``socket_requires_active``: it takes the real time, non cached information. It calls ``disconnect()`` if the user is not ``active``.
 * ``socket_requires_login``: it takes the real time, non cached information. It calls ``disconnect()`` if the user is ``anonymous``.
 * ``socket_weblab_user``: it behaves exactly as ``weblab_user``, but without caching the result. Everytime you call it, it will be calling Redis.

This way, you may use:

.. code-block:: python

   from weblablib import socket_requires_active

   @socketio.on('connect', namespace='/mylab')
   @socket_requires_active
   def connect_handler():
       emit('board-status', hardware_status(), namespace='/mylab')

   @socketio.on('lights', namespace='/mylab')
   @socket_requires_active
   def lights_event(data):
       switch_light(data['number'] - 1, data['state'])
       emit('board-status', hardware_status(), namespace='/mylab')

This is guaranteed to work even if time passes between events.


Example
^^^^^^^

In :ref:`examples_complete` you may find a complete example using Flask-SocketIO, tasks and the authentication model.

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

Using database users
--------------------

In some cases, you might want to have a local database in your laboratory, and users represented there.

For example, sometimes you might want to create a ``folder``, or a ``secret`` for that user, randomly
generated and stored somewhere so the next time the user comes in, he sees the same thing. Also, there
is a function called ``create_token`` in the weblab object to create random secrets in a secure way
and URL-friendly (so you can put them in a query or similar, or even as a folder name or similar).

To do this, in the ``on_start`` method you can create the user if it doesn't exist. This example 
uses `Flask-SQLAlchemy <http://flask-sqlalchemy.pocoo.org/>`_:

.. code-block:: python

   # Using Flask-SQLAlchemy ( http://flask-sqlalchemy.pocoo.org/ )
   from .models import LabUser
   from mylab import db

   @weblab.on_start
   def start(client_data, server_data):
       user = LabUser.query.filter_by(username_unique=username_unique).first()
       if user is None:
          # first time, assign a folder
          folder_name = weblab.create_token()

          # Lab configuration
          programs_folder = current_app.config['PROGRAMS_FOLDER']
          os.mkdir(programs_name)

          # Add the user
          user = LabUser(username=weblab_user.username, 
                         username_unique=weblab_user.username_unique,
                         folder=folder_name)
          db.session.add(user)
          db.session.commit()

And then there is a ``user_loader`` function for loading the user, as well
as a ``weblab_user.user`` object which internally uses that load_user:

.. code-block:: python

   # Using Flask-SQLAlchemy ( http://flask-sqlalchemy.pocoo.org/ )
   from .models import LabUser

   @weblab.user_loader
   def load_user(username_unique):
       return LabUser.query.filter_by(username_unique=username_unique).first()

    @app.route('/files')
    @requires_active
    def files():
        user_folder = weblab_user.user.folder
        return jsonify(files=os.listdir(user_folder))

You can use this in different ways: you can create your own class and use it
relying on a database, or you can use Redis or similar.

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

So if you run (not using Flask-SocketIO):

.. code-block:: shell

   gunicorn --bind 127.0.0.1:8080 -w 10 wsgi_app:application

For example, you'll be running 10 processes, and each of them 3 threads for tasks (30) and 1 thread for cleaning expired sessions. You can reduce the number of threads per process by changing ``WEBLAB_TASK_THREADS_PROCESS``.

Another approach (which is indeed cleaner) is to run no thread, and run the tasks, etc. outside. To do this, you can configure ``WEBLAB_NO_THREAD=False`` (which is equivalent to ``WEBLAB_TASK_THREADS_PROCESS=0``,  ``WEBLAB_AUTOCLEAN_THREAD=False``), and then run in parallel:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask weblab loop

or:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask weblab loop --threads 10


This way, you'll have a process running 10 threads the ``run-tasks`` and ``clean-expired-threads`` tasks continuously.

The command has a flag ``--reload`` and ``--no-reload``. With it, whenever you change something in your code, the process will be automatically restarted. Its default value is the same as ``FLASK_DEBUG`` (so if you're in ``FLASK_DEBUG``, by default it will be run with ``reloader`` while you can change it with ``--no-reload``, and if ``FLASK_DEBUG=0`` or not set, it will not use the reload). You should not use this in production since the reloader kills the process (so if it's in the middle of a task or in the middle of a ``on_dispose`` code, it will literally kill it instead of waiting until it finishes).

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask weblab loop --reload

Another alternative is to run each process separately and per task:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask weblab clean-expired-users

And in another process:

.. code-block:: shell

   $ export FLASK_APP=laboratory.py
   $ flask weblab run-tasks

These two processes end immediately. You can run them in a loop outside in a shell, use ``cron`` or similar tools or so.

This way, the ``gunicorn`` processes will only manage web requests, and the external processes will run the tasks and clean expired users.

.. _advanced_proceses_resources:

Using resources in the same process
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you use resources such as a serial port or a USB port, you may want that everything related to it is running in the same process. This is incompatible with running gunicorn with multiple workers. However, you may be able to achieve it by running things always in ``flask weblab loop``. For example:

.. code-block:: python

   # Imagine a connection to a USB or similar
   resource_manager = None

   @weblab.on_start
   def on_start(client_data, server_data):
       global resource_manager
       # Or "acquire" or similar:
       resource_manager = MyResource()
       resource_manager.open() 

   @weblab.on_dispose
   def on_dispose():
       global resource_manager
       resource_manager.close()

This code, if multiple proceses is run, has several problems:

 * ``on_start`` will be called in a gunicorn process, and the resource will be created and ``acquired``.
 * ``on_dispose``  might be called by a gunicorn process (in a request coming from weblab). But it might be run from *other* gunicorn process. Or it may be called by a ``flask weblab loop`` process if you're executing any. In any of these cases:

   * ``resource_manager`` will be ``None``, and therefore an exception will raise
   * the resource is open in other process, so it might not be possible to re-acquire the resource for another user.

To avoid this problem, there are two options:

 1. You use ``gevent`` or ``eventlet`` as you can see in the documentation related to ``Flask-SocketIO`` (but without need of ``Flask-SocketIO``). Then you run gunicorn with a single worker. The process should work, since the resource will always be in the same process.
 1. You set ``WEBLAB_NO_THREAD=True``, and run in a different process ``flask weblab loop``. Then you change your code to the following:

.. code-block:: python

   # Imagine a connection to a USB or similar
   resource_manager = None

   @weblab.on_start
   def on_start(client_data, server_data):
       initialize_resource.run_sync()

   @weblab.on_dispose
   def on_dispose():
       clean_resource.run_sync()

   @weblab.task()
   def initialize_resource():
       global resource_manager
       # Or "acquire" or similar:
       resource_manager = MyResource()
       resource_manager.open() 

   @weblab.task()
   def clean_resource():
       global resource_manager
       resource_manager.close()
      

The ``run_sync`` guarantees that it will be run by a WebLab Task worker, but due to the ``WEBLAB_NO_THREAD=True``, there will be no thread doing it in gunicorn and it will be run in the ``flask weblab loop`` process. ``run_sync`` will wait until the task finishes, so the behavior is the same, but guaranteeing that it's in a single process.

Base URL
--------

By default, everything is running in ``/``, and **weblablib** automatically generate ``/weblab/sessions/`` URLs. If you have more than
one lab in a public server (quite common if you have a single public IP for several laboratories), then you may have to play with ``SCRIPT_NAME``.

For example:

.. code-block:: shell

    SCRIPT_NAME=/lab1 gunicorn --bind 127.0.0.1:8080 -w 10 \
                      wsgi_app:application

And then in nginx or Apache configuring that https://yourserver/lab1 goes to http://localhost:8080/lab1 will work. In this case, you have to configure ``http_experiment_url`` to ``http://localhost:8080/lab1``. In some circumstances, you may also want to provide a base URL for weblab alone. In that case, you can use the ``WEBLAB_BASE`` url.

.. _internationalization:

Internationalization (i18n)
---------------------------

The object ``weblab_user`` has a ``locale`` parameter; which is ``None`` in the Anonymous
user, but it's ``en``, ``es``... depending on what WebLab-Deusto said (which may come from
the previous system, such as the LMS or Moodle).

Therefore, if you are using ``Flask-Babel`` or ``Flask-BabelEx``, the script for selecting
locale should be similar to:

.. code-block:: python

    @babel.localeselector
    def get_locale():
        locale = request.args.get('locale', None)
        if locale is None:
            locale = weblab_user.locale
        if locale is None:
            locale = session.get('locale')
        if locale is None:
            locale = request.accept_languages.best_match(SUPPORTED_LANGUAGES)
        if locale is None:
            locale = 'en'
        session['locale'] = locale
        return locale

