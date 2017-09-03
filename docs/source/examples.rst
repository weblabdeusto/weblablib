.. _examples:

Examples
========

In the `weblablib GitHub repository <https://github.com/weblabdeusto/weblablib/tree/master/examples>`_ you will find three examples:

 #. Simple, covering the most basic usage
 #. Advanced, with more features used
 #. Complete, a more complex project supporting WebSockets, internationalization or minified objects
 #. Quickstart, which is the one used in :ref:`quickstart`.

They're all compatible with Python 2 and Python 3.

Simple
------

This example has a single file of code (``example.py``), and a very basic structure, using and ``on_start``, ``on_dispose``.

Advanced
--------

This example is explained in detail in the folder itself. However, the highlights are:

 * The laboratory is very similar to the one seen in :ref:`quickstart`, so you will find certain shared code.
 * It uses a ``config.py`` file so as to avoid having configurations in the source code.
 * It uses a task for ``program_device``.
 * It shows how you can have a ``localrc`` to make your life easier in development.
 * It shows a ``flask clean-resources`` script.
 * It comes with a ``gunicorn_start.sh`` and ``wsgi_app.py`` script, that you can see for how to deploy the laboratory.

Complete
--------

This example is based on ``Advanced``, but it includes (and check `the example documentation <https://github.com/weblabdeusto/weblablib/tree/master/examples/complete>`_ for further information):

 * WebSockets. Instead of sending every second the current status, it is only sent when a button is pressed or when the server decides it.
   * WebSockets works even in the ``flask weblab loop`` code: if you notice, two different processes are using the same WebSocket connection thanks to Flask-SocketIO
 * Compression of resources with Flask-Assets.
 * Internationalization. If you run ``flask weblab fake new --locale es`` you see it in Spanish, while if you run it with ``--locale en``, you see it in English. You can create more languages using these commands:

.. code-block:: bash

   # Extract all the messages (this reads all the files and finds any message doing gettext() or similar and stores it in messages.pot)
   $ pybabel extract -F babel.cfg -k lazy_gettext -k ng_gettext -o messages.pot --project complete --version 0.1 .

   # ONLY FOR NEW LANGUAGES: If you wanted to create a new set of translations for French for example, you would need to run this:
   $ pybabel init -i messages.pot -d mylab/translations -l fr

   # Once you have run the 'pybabel extract' command, messages.pot will be updated, but not each language. Whenever you
   # run this other command, you'll find a folder in mylab/translations/es/LC_MESSAGES/messages.po, which is a text file
   # you can edit (or you can use existing tools such as Google Translator Toolkit to edit)
   $ pybabel update -i messages.pot -d mylab/translations -l es

   # Once you have edited the '.po' file, you can run this command to create a '.mo' file, which is used by Flask automatically
   # whenever you restart the Flask application/gunicorn.
   $ pybabel compile -f -d mylab/translations

 
