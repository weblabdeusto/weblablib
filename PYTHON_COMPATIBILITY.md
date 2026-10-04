# Compatibility candidate 0.5.11

This branch starts from `88aaa22`, whose package sources match the previously
built 0.5.10 wheel. It retains Redis indices, concurrency/fail-closed behavior and
the timestamp correction. The runtime changes import Markup from MarkupSafe and
use Werkzeug's relocated development reloader. No reservation protocol changed.

Install the selected labslandlib runtime profile, then `pip install -r
requirements_test.txt`. Run `python run_python_tests.py` in that environment.
The historical `requirements.txt` contains an obsolete SocketIO development pin;
use the explicit test requirements for this compatibility matrix. The runner creates a private persistence-disabled Redis
Unix socket. Never run the historical tests against production Redis: their
session fixture intentionally clears its isolated database. The runner requires
redis-server and fails if it is unavailable.

Validated dependency pairings are the labslandlib legacy Flask1.1/Python3.8 and
modern Flask3.1/Python3.14 profiles. Tests cover indices, concurrency, timestamp
fractions, task/session lifecycle, authenticated HTTP, CLI and SocketIO. This is a
local candidate; publish/reconcile the source and wheel before deployments.
