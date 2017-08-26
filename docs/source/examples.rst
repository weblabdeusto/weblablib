.. _examples:

Examples
========

In the `weblablib GitHub repository <https://github.com/weblabdeusto/weblablib/tree/master/examples>`_ you will find three examples:

 #. Simple, covering the most basic usage
 #. Advanced, with more features used
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
