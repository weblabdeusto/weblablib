.. _configuration:

Configuration values
====================

The following are the configuration variables of **weblablib**:

WebLab-Deusto
-------------

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_USERNAME``               WebLab-Deusto credentials. It is not the
                                  username of the new user: it represents
                                  the system itself (e.g., the WebLab-Deusto
                                  system calling). **Mandatory**
``WEBLAB_PASSWORD``               WebLab-Deusto credentials. Read also
                                  ``WEBLAB_USERNAME``. **Mandatory**
``WEBLAB_POLL_INTERVAL``          WebLab-Deusto is connecting every few seconds
                                  to the laboratory asking if the user is still
                                  alive or if he left. By default, 5 seconds.
                                  You can regulate it with this configuration
                                  variable. Note that if you establish ``0``,
                                  then WebLab-Deusto will not ask again and
                                  will wait until the end of the cycle.
================================= =========================================

URLs
----

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_CALLBACK_URL``           **weblablib** creates a set or URLs for
                                  receiving methods directly by the user.
                                  This methods must be publicly available by
                                  the student. It can be ``/mylab/callback``.
``WEBLAB_BASE_URL``               If you want to start /weblab/sessions
                                  somewhere else (e.g., ``/mylab``), you can
                                  configure it here.
``WEBLAB_SCHEME``                 If set to ``https``, forces using ``https`` in
                                  the link sent to the user.
================================= =========================================

Redis
-----

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_REDIS_URL``              Url used for connecting to Redis. By
                                  default it's the database 0 with localhost
                                  and standard port, but you can configure it:
                                  ``redis://localhost:6379/``.
``WEBLAB_REDIS_BASE``             If you use multiple laboratories in the same
                                  server, you should give different values to
                                  this configuration so there is no conflict
                                  in Redis. If one is ``lab1`` and the other
                                  is ``lab2``, in Redis values will start by
                                  ``lab1:`` or ``lab2:``.
``WEBLAB_REDIS_INDEX_MODE``       Redis discovery mode. ``legacy`` (the
                                  default) preserves the historical behavior.
                                  ``shadow`` maintains indices while legacy
                                  discovery remains authoritative. ``indexed``
                                  uses a prepared index and avoids ``KEYS`` on
                                  normal cleaner and task-runner paths.
``WEBLAB_REDIS_INDEX_EPOCH``      Deployment-controlled identifier required in
                                  ``shadow`` and ``indexed`` modes. Use a new
                                  value after every rollback before preparing
                                  and enabling indexed reads again.
================================= =========================================

Redis discovery indices
^^^^^^^^^^^^^^^^^^^^^^^

The Redis index is explicitly opt-in. Flask configuration takes precedence;
the same-named environment variables are used only when the Flask keys are not
set. In ``legacy`` mode WebLabLib performs exactly the historical Redis
operations and does not read or write index keys.

Use this sequence independently for each ``WEBLAB_REDIS_BASE``:

#. Upgrade every process that can create sessions or tasks for that base, set
   ``WEBLAB_REDIS_INDEX_MODE=shadow``, and set a new
   ``WEBLAB_REDIS_INDEX_EPOCH``.
#. Run ``flask weblab redis-index status --json`` and resolve every reported
   Redis safety or key-type error.
#. Run ``flask weblab redis-index prepare --json``. Preparation is locked,
   backfills missing live members with ``SCAN``, and requires zero missing live
   members before recording readiness. Stale members are harmless and are
   validated and pruned by indexed reads.
#. Change readers to ``indexed`` only after preparation reports ``ready: true``.
   Producers may remain in ``shadow`` during a staged rollout because both
   modes dual-write the same index.

WebLabLib 0.5.8 processes can coexist with 0.5.9 while 0.5.9 remains in
``shadow``. Do not leave an old writer for a Redis base after any reader for
that base enters ``indexed``; old writers do not maintain the index. Rollback
all affected processes for that base to ``legacy`` together. A later re-upgrade
must use a new epoch and repeat shadow preparation.

Index modes require standalone Redis, a non-``allkeys-*`` eviction policy, and
permission to inspect server configuration and execute the required
``TYPE``, ``SCAN``, set, string, and hash commands. Redis Cluster remains
unsupported. Existing session/task hashes and markers remain the TTL authority
and are kept for rollback compatibility.

If readiness or an index set disappears at runtime, or candidate validation
fails, an indexed read invalidates readiness, emits a rate-limited critical
event, and falls back to legacy discovery for that call. An index-maintaining
write failure also invalidates readiness and preserves the Redis error for the
caller. Return the affected Redis base to ``shadow`` and repeat preparation
before using ``indexed`` again. Normal healthy indexed cleaner and task-runner
paths do not issue ``KEYS`` or ``SCAN``.

Session management
------------------

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_SESSION_ID_NAME``        The name that the **weblablib** session will
                                  have in the Flask **session** object.
``WEBLAB_TIMEOUT``                Value in seconds taken by **weblablib** to
                                  consider a user expired if s/he hasn't polled
                                  in this time.
``WEBLAB_AUTOPOLL``               If ``True`` (default value), it will make
                                  that every call to the server will call
                                  ``poll``.
``WEBLAB_EXPIRED_USERS_TIMEOUT``  Once the user is expired, the information is
                                  kept in Redis for some time. By default, this
                                  is ``3600`` (seconds, which is one hour).
``WEBLAB_UNAUTHORIZED_LINK``      When a user is not logged in (or the session
                                  expired -after an hour-, by default finds an
                                  ``Access forbidden`` message. You can put
                                  a link here to redirect him to a different
                                  URL (such as your WebLab-Deusto system, so
                                  the student is forced to log in).
``WEBLAB_UNAUTHORIZED_TEMPLATE``  Same as ``WEBLAB_UNAUTHORIZED_LINK``, but
                                  instead of redirecting, it renders a template.
                                  If you put ``forbidden.html``, it will render
                                  whatever is in ``templates/forbidden.html``.
================================= =========================================

Processes and threading
-----------------------

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_AUTOCLEAN_THREAD``       By default ``True``, it states whether there
                                  will be a thread by process cleaning sessions
                                  of expired users or not.
``WEBLAB_TASK_THREADS_PROCESS``   By default ``3``, it is the number of threads
                                  in each **weblablib** process running tasks
                                  submitted by user.
``WEBLAB_NO_THREAD``              Equivalent to ``WEBLAB_AUTOCLEAN_THREAD=False``
                                  and ``WEBLAB_TASK_THREADS_PROCESS=0``. If you
                                  use it, make sure you run ``flask loop``
================================= =========================================
