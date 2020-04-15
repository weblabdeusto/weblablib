# Copyright 2017 onwards LabsLand Experimentia S.L.
# This software is licensed under the GNU AGPL v3:
# GNU Affero General Public License version 3 (see the file LICENSE)
# Read in the documentation about the license

from __future__ import unicode_literals, print_function, division

import abc
import json
import zlib
import warnings

import six

from werkzeug.datastructures import ImmutableDict
from werkzeug.local import LocalProxy
from flask import g, current_app

from weblablib.utils import create_token, _current_backend, _current_timestamp, \
     _current_weblab, _current_session_id

from weblablib.tasks import current_task

def get_weblab_user(cached=True):
    """
    Get the current user. If ``cached=True`` it will store it and return the same each time.
    If you need to get always a different one get it with ``cached=False``. In long tasks, for
    example, it's normal to call it with ``cached=False`` so it gets updated with whatever
    information comes from other threads.

    Two shortcuts exist to this function:
     * :data:`weblab_user`: it is equivalent to ``get_weblab_user(cached=True)``
     * :data:`socket_weblab_user`: it is equivalent to ``get_weblab_user(cached=False)``

    Given that the function always returns a :class:`CurrentUser` or :class:`ExpiredUser` or :class:`AnonymousUser`, it's safe to do things like::

       if not weblab_user.anonymous:
           print(weblab_user.username)
           print(weblab_user.username_unique)

    :param cached: if this method is called twice in the same thread, it will return the same object.
    """
    if cached and hasattr(g, 'weblab_user'):
        return g.weblab_user

    # Cached: then use Redis
    session_id = _current_session_id()
    if session_id is None:
        return _set_weblab_user_cache(AnonymousUser())

    user = _current_backend().get_user(session_id)
    # Store it for next requests in the same call
    return _set_weblab_user_cache(user)

def _set_weblab_user_cache(user):
    g.weblab_user = user
    return user

weblab_user = LocalProxy(get_weblab_user) # pylint: disable=invalid-name

socket_weblab_user = LocalProxy(lambda: get_weblab_user(cached=False)) # pylint: disable=invalid-name


class WebLabUser(object):
    """
    Abstract representation of a WebLabUser. Implementations:

     * :class:`AnonymousUser`
     * :class:`CurrentUser`
     * :class:`ExpiredUser`

    """
    __metaclass__ = abc.ABCMeta

    @abc.abstractproperty
    def active(self):
        """Is the user active right now or not?"""

    @abc.abstractproperty
    def is_anonymous(self):
        """Was the user a valid user recently?"""

    @abc.abstractmethod
    def __str__(self):
        """str representation"""

class AnonymousDataImmutableDict(dict):
    def _method(self, *args, **kwargs): # pylint: disable=unused-argument, no-self-use
        raise TypeError("Anonymous user contains no valid data")

    __setitem__ = __getitem__ = __delitem__ = __iter__ = __len__ = _method

    keys = values = get = setdefault = items = iteritems = _method

    pop = popitem = copy = update = clear = _method

@six.python_2_unicode_compatible
class AnonymousUser(WebLabUser):
    """
    Implementation of :class:`WebLabUser` representing anonymous users.
    """

    @property
    def active(self):
        """Is active? Always ``False``"""
        return False

    @property
    def is_anonymous(self):
        """Is anonymous? Always ``True``"""
        return True

    @property
    def locale(self):
        """Language requested by WebLab-Deusto? Always ``None``"""
        return None

    @property
    def data(self):
        """An object that raises error if accessed as a dict"""
        return AnonymousDataImmutableDict()

    def __str__(self):
        return "Anonymous user"

_OBJECT = object()

class _CurrentOrExpiredUser(WebLabUser): # pylint: disable=abstract-method
    def __init__(self, session_id, back, last_poll, max_date, username, username_unique,
                 exited, data, locale, full_name, experiment_name, category_name, experiment_id,
                 request_client_data, request_server_data, start_date):
        self._session_id = session_id
        self._back = back
        self._last_poll = last_poll
        self._max_date = max_date
        self._start_date = start_date
        self._username = username
        self._username_unique = username_unique
        self._exited = exited
        self._data = data
        self._locale = locale
        self._full_name = full_name
        self._experiment_name = experiment_name
        self._category_name = category_name
        self._experiment_id = experiment_id
        self._request_client_data = request_client_data
        self._request_server_data = request_server_data

    @property
    def experiment_name(self):
        """Experiment name (as in WebLab-Deusto)"""
        return self._experiment_name

    @property
    def category_name(self):
        """Experiment category name (as in WebLab-Deusto)"""
        return self._category_name

    @property
    def experiment_id(self):
        """Experiment id (as in WebLab-Deusto)"""
        return self._experiment_id

    @property
    def full_name(self):
        """User full name"""
        return self._full_name

    @property
    def locale(self):
        """Language requested by the system (e.g., was the user using Moodle in Spanish?). 'es'"""
        return self._locale

    @property
    def back(self):
        """URL of the previous website. When the user has finished, redirect him there"""
        return self._back

    @property
    def last_poll(self):
        """Last time the user called poll() (can be done by an automated process)"""
        return self._last_poll

    @property
    def session_id(self):
        """Session identifying the current user"""
        return self._session_id

    @property
    def max_date(self):
        """When should the user finish"""
        return self._max_date

    @property
    def username(self):
        """
        Username of the user. Note: this is short, but not unique across institutions.
        There could be a ``john`` in ``institutionA`` and another ``john`` in ``institutionB``
        """
        return self._username

    @property
    def username_unique(self):
        """
        Unique username across institutions. It's ``john@institutionA`` (which is
        different to ``john@institutionB``)
        """
        return self._username_unique

    @property
    def exited(self):
        """
        Did the user call :func:`logout`?
        """
        return self._exited

    @property
    def request_client_data(self):
        """
        Information provided in the beginning of the interaction (on_start): client_data
        """
        return ImmutableDict(self._request_client_data or {})

    @property
    def request_server_data(self):
        """
        Information provided in the beginning of the interaction (on_start): server_data
        """
        return ImmutableDict(self._request_server_data or {})

    @property
    def start_date(self):
        """
        Information provided in the beginning of the interaction (on_start): client_data
        """
        return self._start_date

    def add_action(self, session_id, action):
        """
        Adds a new raw action to a session_id, returning the action_id
        """
        action_id = create_token()
        self.store_action(session_id, action_id, action)
        return action_id

    def store_action(self, session_id, action_id, action): # pylint: disable=no-self-use
        """
        Adds a new raw action to a new or existing session_id
        """
        backend = _current_backend()
        backend.store_action(session_id, action_id, action)

    def clean_actions(self, session_id): # pylint: disable=no-self-use
        """
        Remove all actions of a session_id
        """
        backend = _current_backend()
        backend.clean_actions(session_id)

class DataHolder(dict):
    def __init__(self, user, data, previous_hash=None):
        super(DataHolder, self).__init__(data)
        self._user = user
        self._initial_hash = previous_hash or self._get_hash(data)

    @property
    def initial_hash(self):
        return self._initial_hash

    def _get_hash(self, data):
        data_str = json.dumps(data)
        if six.PY2:
            data_str = data_str.decode('utf8')
        return zlib.crc32(data_str.encode('utf8'))

    def store(self):
        backend = _current_backend()
        data = self.copy()
        backend.update_data(self._user._session_id, data)
        self._initial_hash = self._get_hash(data)

    def store_if_modified(self):
        if self.is_modified:
            self.store()

    @property
    def is_modified(self):
        current_hash = self._get_hash(self)
        return current_hash != self._initial_hash

    def retrieve(self):
        backend = _current_backend()
        user = backend.get_user(self._user._session_id)
        if isinstance(user.data, DataHolder):
            self.update(user.data)
            for key in list(self):
                if key not in user.data:
                    self.pop(key, None)

@six.python_2_unicode_compatible
class CurrentUser(_CurrentOrExpiredUser):
    """
    This class is a :class:`WebLabUser` representing a user which is still actively using a
    laboratory. If the session expires, it will become a :class:`ExpiredUser`.
    """

    def __init__(self, *args, **kwargs):
        super(CurrentUser, self).__init__(*args, **kwargs)
        self._data = DataHolder(self, self._data)

    @property
    def data(self):
        """
        User data. By default an empty dictionary.
        You can access to it and modify it across processes.
        See also :meth:`CurrentUser.update_data`.
        """
        return self._data

    @data.setter
    def data(self, data):
        self._data = DataHolder(self, data, previous_hash=self._data.initial_hash)

    def update_data(self, new_data=_OBJECT):
        """
        .. deprecated:: 0.5.0

        Use weblab_user.data.store() or don't use anything if inside a view or on_start.
        """
        msg = "weblablib: method 'update_data' deprecated. Please use weblab_user.data.store()"
        warnings.warn(msg)
        if current_app:
            current_app.logger.warning(msg)

        if new_data != _OBJECT:
            new_data = self._data

        self.data = self._data

    @property
    def time_without_polling(self):
        """
        Seconds without polling
        """
        return _current_timestamp() - self.last_poll

    @property
    def time_left(self):
        """
        Seconds left (0 if time passed)
        """
        return max(0, self.max_date - _current_timestamp())

    def to_expired_user(self):
        """
        Create a ExpiredUser based on the data of the user
        """
        return ExpiredUser(session_id=self._session_id, back=self._back, max_date=self._max_date,
                           last_poll=self._last_poll, exited=self._exited,
                           username=self._username, username_unique=self._username_unique,
                           data=self._data.copy(), locale=self._locale, full_name=self._full_name,
                           experiment_name=self._experiment_name, category_name=self._category_name,
                           experiment_id=self._experiment_id, request_client_data=self._request_client_data,
                           request_server_data=self._request_server_data, start_date=self._start_date,
                           disposing_resources=True)

    @property
    def user(self):
        """
        Load a related user from a database or similar. You might want to keep information about
        the current user and use this information across sessions, depending on your laboratory.
        Examples of this could be logs, or shared resources (e.g., storing the last actions of
        the user for the next time they log in). So as to load the user from the database, you
        can use :meth:`WebLab.user_loader` to define a user loader, and use this property to access
        later to it.

        For example, using `Flask-SQLAlchemy <http://flask-sqlalchemy.pocoo.org/>`_::

           from mylab.models import LaboratoryUser

           @weblab.on_start
           def start(client_data, server_data):
               # ...
               user = LaboratoryUser.query.filter(identifier.username_unique).first()
               if user is None:
                   # Make sure the user exists in the database
                   user_folder = create_user_folder()
                   user = LaboratoryUser(username=weblab_user.username,
                                     identifier=username_unique,
                                     user_folder=user_folder)
                   db.session.add(user)
                   db.session.commit()


           @weblab.user_loader
           def loader(username_unique):
               return LaboratoryUser.query.filter(identifier=username_unique).first()

           # And then later:

           @app.route('/lab')
           @requires_active
           def home():
               user_db = weblab_user.user
               open(os.path.join(user_db.user_folder, 'myfile.txt')).read()

           @app.route('/files')
           @requires_active
           def files():
               user_folder = weblab_user.user.user_folder
               # ...

        """
        user_loader = _current_weblab()._user_loader
        if user_loader is None:
            return None

        try:
            user = user_loader(self.username_unique)
        except:
            raise
        else:
            # Maybe in the future we should cache results so
            # no every weblab_user.user becomes a call to
            # the database? The main issue is with tasks or
            # long-standing processes
            return user

    @property
    def active(self):
        """Is the user active and has not called :func:`logout`?"""
        return not self._exited

    @property
    def is_anonymous(self):
        """Is the user anonymous? ``False``"""
        return False

    def __str__(self):
        return 'Current user (id: {!r}): {!r} ({!r}), last poll: {:.2f} seconds ago. Max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self.time_without_polling, self._max_date - _current_timestamp(), self._back)

@six.python_2_unicode_compatible
class ExpiredUser(_CurrentOrExpiredUser):
    """
    This class is a :class:`WebLabUser` representing a user which has been kicked out already.
    Typically this ExpiredUser is kept in the backend for around an hour (it depends on
    ``WEBLAB_EXPIRED_USERS_TIMEOUT`` setting).

    Most of the fields are same as in :class:`CurrentUser`.
    """
    def __init__(self, *args, **kwargs):
        disposing_resources = kwargs.pop('disposing_resources', False)
        super(ExpiredUser, self).__init__(*args, **kwargs)
        self.disposing_resources = disposing_resources

    @property
    def data(self):
        """
        User data. By default an empty dictionary.
        You can access to it and modify it across processes.

        Do not change this data in :class:`ExpiredUser`.
        """
        return ImmutableDict(self._data)

    @data.setter
    def data(self, value):
        raise NotImplementedError("You can't change data on an ExpiredUser")

    def update_data(self, value=None):
        """Update data. Not implemented in :class:`ExpiredUser` (expect an error)"""
        raise NotImplementedError("You can't change data on an ExpiredUser")

    @property
    def time_left(self):
        """
        Seconds left (always 0 in this case)
        """
        return 0

    @property
    def active(self):
        """
        Is it an active user? (``False``)
        """
        return False

    @property
    def is_anonymous(self):
        """
        Is it an anonymous user? (``False``)
        """
        return False

    def __str__(self):
        return 'Expired user (id: {!r}): {!r} ({!r}), max date in {:.2f} seconds. Redirecting to {!r}'.format(self._session_id, self._username, self._username_unique, self._max_date - _current_timestamp(), self._back)
