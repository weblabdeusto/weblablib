"""Bounded keepalive while an authenticated start callback prepares a lab."""
from __future__ import division

from contextlib import contextmanager
import threading
import time

MAX_INITIALIZATION_SECONDS = 60


@contextmanager
def initialization_keepalive(backend, session_id, timeout, max_date):
    # Browser polling cannot begin until the callback returns its URL. Keep
    # only that preparation window alive; never extend the assigned slot.
    initialization_deadline = time.time() + MAX_INITIALIZATION_SECONDS
    deadline = min(initialization_deadline, max_date)
    interval = max(0.01, min(1.0, float(timeout) / 3))
    stop = threading.Event()
    failures = []

    def poll_until_ready():
        while not stop.wait(interval):
            if time.time() >= deadline:
                return
            try:
                backend.poll(session_id)
            except Exception as error:
                failures.append(error)
                return

    if time.time() < deadline:
        backend.poll(session_id)
    worker = threading.Thread(target=poll_until_ready)
    worker.daemon = True
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=interval + 1)
    if worker.is_alive() or failures:
        raise RuntimeError('Initialization keepalive failed')
    if time.time() >= initialization_deadline:
        raise RuntimeError('Laboratory initialization deadline exceeded')
    if time.time() < deadline:
        backend.poll(session_id)
    if not backend.get_user(session_id).active:
        raise RuntimeError('Laboratory session ended during initialization')
