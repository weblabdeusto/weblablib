# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division


class ConfigurationKeys(object):
    """
    ConfigurationKeys represents all the configuration keys available in weblablib.
    """

    # # # # # # # # # #
    #                 #
    #  Mandatory keys #
    #                 #
    # # # # # # # # # #

    #
    # WebLab-Deusto needs to be authenticated in this system.
    # So we need a pair of credentials representing the system,
    # not the particular user coming. This is what you configured
    # in WebLab-Deusto when you add the laboratory.
    #
    WEBLAB_USERNAME = 'WEBLAB_USERNAME'
    WEBLAB_PASSWORD = 'WEBLAB_PASSWORD'

    # # # # # # # # # #
    #                 #
    #  Optional keys  #
    #                 #
    # # # # # # # # # #

    # the base URL is what you want to put before the /weblab/ URLs,
    # e.g., if you want to put it in /private/weblab/ you can do that
    # (after all, even at web server level you can configure that
    # the weblab URLs are only available to WebLab-Deusto)
    WEBLAB_BASE_URL = 'WEBLAB_BASE_URL'

    # the callback URL must be a public URL where users will be
    # forwarded to. For example "/lab/callback"
    WEBLAB_CALLBACK_URL = 'WEBLAB_CALLBACK_URL'

    # This is the key used in the Flask session object.
    WEBLAB_SESSION_ID_NAME = 'WEBLAB_SESSION_ID_NAME'

    # Redis URL for storing information
    WEBLAB_REDIS_URL = 'WEBLAB_REDIS_URL'

    # Redis base. If you have more than one lab in the same Redis server,
    # you can use this variable to make it work without conflicts. By default
    # it's lab, so all the keys will be "lab:weblab:active:session-id", for example
    WEBLAB_REDIS_BASE = 'WEBLAB_REDIS_BASE'

    # How long the results of the tasks should be stored in Redis? In seconds.
    # By default one hour.
    WEBLAB_TASK_EXPIRES = 'WEBLAB_TASK_EXPIRES'

    # Number of seconds. If the user does not poll in that time, we consider
    # that he will be kicked out. Defaults to 15 seconds. It can be set
    # to -1 to disable the timeout (and therefore polling makes no sense)
    WEBLAB_TIMEOUT = 'WEBLAB_TIMEOUT'

    # Automatically poll in every method. By default it's true. So any call
    # made to any web method will automatically poll.
    WEBLAB_AUTOPOLL = 'WEBLAB_AUTOPOLL'

    # If a user doesn't have a session, you can forward him to WebLab-Deusto.
    # put the link to the WebLab-Deusto there
    WEBLAB_UNAUTHORIZED_LINK = 'WEBLAB_UNAUTHORIZED_LINK'

    # If a user doesn't have a session and you don't configure WEBLAB_UNAUTHORIZED_LINK
    # then you can put 'unauthorized.html' here, and place a 'unauthorized.html' file
    # in a 'templates' directory (see Flask documentation for details)
    WEBLAB_UNAUTHORIZED_TEMPLATE = 'WEBLAB_UNAUTHORIZED_TEMPLATE'

    # WebLab-Deusto is connecting every few seconds to the laboratory asking if the user
    # is still alive or if he left. By default, 5 seconds. You can regulate it with this
    # configuration variable. Note that if you establish '0', then WebLab-Deusto will
    # not ask again and will wait until the end of the cycle.
    WEBLAB_POLL_INTERVAL = 'WEBLAB_POLL_INTERVAL'

    # There is a thread that cleans expired sessions. If a user has been more time that it 
    # should be possible, the user will be kicked out even if WebLab-Deusto has not checked
    # yet. This is important so that if the dispose() method takes a while (e.g., deleting
    # things, etc.), we call it asap.
    WEBLAB_CLEANER_INTERVAL = 'WEBLAB_CLEANER_INTERVAL'

    # Force 'http' or 'https'
    WEBLAB_SCHEME = 'WEBLAB_SCHEME'

    # Once a user is moved to inactive, the session has to expire at some point.
    # Establish in seconds in how long (defaults to 3600, which is one hour)
    WEBLAB_EXPIRED_USERS_TIMEOUT = 'WEBLAB_EXPIRED_USERS_TIMEOUT'

    # In some rare occasions, it may happen that the dispose method is not called.
    # For example, if the Experiment server suddenly has no internet for a temporary
    # error, the user will not call logout, and WebLab-Deusto may fail to communicate
    # that the user has finished, and store that it has finished internally in
    # WebLab-Deusto. For some laboratories, it's important to be extra cautious and
    # make sure that someone calls the _dispose method. To do so, you may call
    # directly "flask clean_expired_users" manually (and cron it), or you may just
    # leave this option as True, which is the default behavior, and it will create
    # a thread that will be in a loop. If you have 10 gunicorn workers, there will
    # be 10 threads, but it shouldn't be a problem since they're synchronized with
    # Redis internally.
    WEBLAB_AUTOCLEAN_THREAD = 'WEBLAB_AUTOCLEAN_THREAD'

    # You can either call "flask run-tasks" or rely on the threads created
    # for running threads.
    WEBLAB_TASK_THREADS_PROCESS = 'WEBLAB_TASK_THREADS_PROCESS'

    # Equivalent for WEBLAB_AUTOCLEAN_THREAD=False and WEBLAB_TASK_THREADS_PROCESS=0
    WEBLAB_NO_THREAD = 'WEBLAB_NO_THREAD'
