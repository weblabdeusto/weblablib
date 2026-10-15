import os
import unittest
from unittest.mock import Mock, patch

from flask import Flask, render_template_string, session
from weblablib import WebLab
from weblablib.exc import InvalidConfigError


class BrowserPollIntervalTest(unittest.TestCase):
    def render(self, timeout=90, configured=None, environment=None):
        app = Flask(__name__)
        app.config.update(SECRET_KEY='private-test-only', WEBLAB_USERNAME='qa',
                          WEBLAB_PASSWORD='qa', WEBLAB_TIMEOUT=timeout,
                          WEBLAB_AUTOCLEAN_THREAD=False, WEBLAB_TASK_THREADS_PROCESS=0)
        if configured is not None:
            app.config['WEBLAB_BROWSER_POLL_INTERVAL'] = configured
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('WEBLAB_BROWSER_POLL_INTERVAL', None)
            if environment is not None:
                os.environ['WEBLAB_BROWSER_POLL_INTERVAL'] = environment
            WebLab(app, backend=Mock())
            with app.test_request_context('/'):
                session['weblab_session_id'] = 'private-qa'
                return str(render_template_string('{{ weblab_poll_script() }}'))

    def test_historical_default(self):
        self.assertIn('setInterval(WEBLAB_INTERVAL_FUNCTION, 7500 )', self.render(15))

    def test_existing_long_default_unchanged(self):
        self.assertIn('setInterval(WEBLAB_INTERVAL_FUNCTION, 45000 )', self.render())

    def test_independent_browser_heartbeat(self):
        self.assertIn('setInterval(WEBLAB_INTERVAL_FUNCTION, 5000 )', self.render(configured=5))

    def test_deployment_environment(self):
        self.assertIn('setInterval(WEBLAB_INTERVAL_FUNCTION, 5000 )', self.render(environment='5'))

    def test_app_config_precedes_environment(self):
        self.assertIn('setInterval(WEBLAB_INTERVAL_FUNCTION, 3000 )', self.render(configured=3, environment='5'))

    def test_disabled_timeout(self):
        self.assertIn('timeout is 0 or negative', self.render(timeout=0))

    def test_invalid_cadence_rejected(self):
        for value in (0, -1, 90, 91, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(InvalidConfigError):
                self.render(configured=value)


if __name__ == '__main__':
    unittest.main()
