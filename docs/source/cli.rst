.. _cli:

Command Line Interface (CLI) reference
======================================

weblablib uses the `Flask CLI <http://flask.pocoo.org/docs/0.12/cli/>`_ feature to add commands.

You must run:

.. code-block:: shell

   $ export FLASK_APP=example.py
   $ flask weblab
   Usage: flask weblab [OPTIONS] COMMAND [ARGS]...

     WebLab-Deusto related operations: initialize new sessions for development,
     run tasks, etc.

   Options:
     --help  Show this message and exit.

   Commands:
     clean-expired-users  Clean expired users.
     fake                 Fake user management.
     loop                 Run planned tasks and clean expired users,...
     run-tasks            Run planned tasks.


Running tasks and cleaning resources
------------------------------------

There are three commands:

clean-expired-users
^^^^^^^^^^^^^^^^^^^

This command does not run in a loop, but simply clean expired users and exits. You can use cron or other tool to manage it.

.. code-block:: shell

   $ flask weblab clean-expired-users --help
   Usage: flask weblab clean-expired-users [OPTIONS]

     Clean expired users.

     By default, a set of threads will be doing this, but you can also run it
     manually and disable the threads.

   Options:
     --help  Show this message and exit.



run-tasks
^^^^^^^^^

This command does not run in a loop, but simply runs the pending tasks and exits. You can use cron or other tool to manage it.

.. code-block:: shell

    $ flask weblab run-tasks --help
    Usage: flask weblab run-tasks [OPTIONS]

      Run planned tasks.

      By default, a set of threads will be doing this, but you can run the tasks
      manually in external processes.

    Options:
      --help  Show this message and exit.



loop
^^^^

This command does run in a loop.

.. code-block:: shell

    $ flask weblab loop --help
    Usage: flask weblab loop [OPTIONS]

      Run planned tasks and clean expired users, permanently.

    Options:
      --threads INTEGER       Number of threads
      --reload / --no-reload  Reload as code changes. Defaults to whether the app
                              is in FLASK_DEBUG mode
      --help                  Show this message and exit.


Faking users without WebLab-Deusto
----------------------------------

You can use weblablib without WebLab-Deusto for development purposes. To do so, you can use
this command so as to fake certain situations. Note that you must be in charge of making the
proper requests (e.g., you can call twice the ``new`` method; and that's something that your
laboratory might not support).


.. code-block:: shell

    $ flask weblab fake --help
    Usage: flask weblab fake [OPTIONS] COMMAND [ARGS]...

      Fake user management.

      With this interface, you can test your laboratory without WebLab-Deusto.
      It implements the same methods used by WebLab-Deusto (create new user,
      check status, kick out user), from a command line interface. The "new"
      command has several parameters for changing language, user name, etc.

    Options:
      --help  Show this message and exit.

    Commands:
      dispose  End a session of a fake user.
      new      Create a fake WebLab-Deusto user session.
      status   Check status of a fake user.

New user
^^^^^^^^

You can fake WebLab-Deusto requesting the status of the current user. All these parameters have
a default value. You can change them if you want (e.g., to test it in different languages, etc.).

.. code-block:: shell

    $ flask weblab fake new --help
    Usage: flask weblab fake new [OPTIONS]

      Create a fake WebLab-Deusto user session.

      This command creates a new user session and stores the session in disk, so
      you can use other commands to check its status or delete it.

    Options:
      --name TEXT              First and last name
      --username TEXT          Username passed
      --username-unique TEXT   Unique username passed
      --assigned-time INTEGER  Time in seconds passed to the laboratory
      --back TEXT              URL to send the user back
      --locale TEXT            Language
      --experiment-name TEXT   Experiment name
      --category-name TEXT     Category name (of the experiment)
      --dont-open-browser      Do not open the fake user in a web browser
      --help                   Show this message and exit.



Check status
^^^^^^^^^^^^

You can fake WebLab-Deusto requesting the status of the current user.

.. code-block:: shell

    $ flask weblab fake status --help
    Usage: flask weblab fake status [OPTIONS]

      Check status of a fake user.

      Once you create a user with flask "weblab fake new", you can use this
      command to simulate the status method of WebLab-Deusto and see what it
      would return.

    Options:
      --help  Show this message and exit.


Delete user
^^^^^^^^^^^

You can fake WebLab-Deusto requesting to kick out the user.

.. code-block:: shell

    $ flask weblab fake dispose --help
    Usage: flask weblab fake dispose [OPTIONS]

      End a session of a fake user.

      Once you create a user with 'flask weblab fake new', you can use this
      command to simulate the dispose method of WebLab-Deusto to kill the
      current session.

    Options:
      --help  Show this message and exit.
