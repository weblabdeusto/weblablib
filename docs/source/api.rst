API reference
=============

.. module:: weblablib

WebLab object
-------------

.. autoclass:: WebLab
   :members:

Functions and properties
------------------------

.. autofunction:: get_weblab_user

.. data:: weblab_user

   Shortcut to :func:`get_weblab_user` with ``cached=True``

.. data:: socket_weblab_user

   Shortcut to :func:`get_weblab_user` with ``cached=False``

.. autofunction:: poll

.. autofunction:: logout


Decorators
----------

.. autofunction:: requires_active

.. autofunction:: requires_login

.. autofunction:: socket_requires_active

.. autofunction:: socket_requires_login


Tasks
-----

You can start tasks with :meth:`WebLab.task`, as explained in detail in the :ref:`tasks` documentation section.


.. data:: current_task

   Running outside a task, it returns ``None``.
   Running inside a task, it returns the task object. This way you can know what is the
   ``task_id`` or read or modify :data:`WebLabTask.data`.

.. data:: current_task_stopping

   Running outside a task, it returns ``False``.
   Running inside a task, it calls :data:`WebLabTask.stopping` and returns its value.



.. autoclass:: WebLabTask
   :members:

Users
-----

.. autoclass:: CurrentUser
   :members:

.. autoclass:: ExpiredUser
   :members:

.. autoclass:: AnonymousUser
   :members:

.. autoclass:: WebLabUser
   :members:

Errors
------

.. autoclass:: WebLabError

.. autoclass:: NoContextError

.. autoclass:: InvalidConfigError

.. autoclass:: WebLabNotInitializedError

.. autoclass:: TimeoutError

.. autoclass:: AlreadyRunningError


