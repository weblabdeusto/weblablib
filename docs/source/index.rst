.. weblablib documentation master file, created by
   sphinx-quickstart on Mon Aug  7 15:23:17 2017.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

weblablib - development
=======================

.. warning::

   This is the documentation of the development version.

   Go to https://weblablib.readthedocs.org/en/stable/ for the latest stable version.

weblablib is a library for creating `WebLab-Deusto <https://github.com/weblabdeusto/weblabdeusto/>`_ remote laboratories.

A remote laboratory is a software and hardware system that enables students to access real laboratories through the Internet. For example, a student can be learning how to program a robot by writing code in a computer at home and sending it to a remote laboratory, where the student can see how the program behaves in a real environment.

Creating a remote laboratory may imply many layers, such as authentication, authorization, scheduling, etc., so Remote Laboratory Management Systems (RLMS) were created to make the common layers of remote laboatories. WebLab-Deusto is an Open Source RLMS, and it has multiple ways (`see the docs <https://weblabdeusto.readthedocs.org>`_) to create a remote laboratory (in different programming languages, etc.).

In the case of Python, with the popular `Flask <http://flask.pocoo.org>`_ microframework, weblablib is the wrapper used to create unmanaged labs. Unmanaged labs is a term used in WebLab-Deusto to refer laboratories where the authors develop the full stack (server, client, deployment), as opposed to managed labs.

If you are familiar with Flask and with Web development (while not necessarily), and want to be able to customize everything but not need to implement all the layers of authentication, administration, etc., this library would be very useful.

.. toctree::
   :maxdepth: 2

   quickstart
   advanced
   examples
   configuration
   changelog


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

