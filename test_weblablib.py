import os

from flask import Flask
import flask.cli as flask_cli

import weblablib
import unittest
from click.testing import CliRunner


os.environ['FLASK_APP'] = 'fake.py' # Overrided later

class WebLabTest(unittest.TestCase):

    def create_weblab(self):
        self.weblab = weblablib.WebLab()
        self.app = Flask(__name__)
        flask_cli.locate_app = lambda *args: self.app
        self.app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        self.weblab.init_app(self.app)
        self.weblab._redis_manager.client.flushall()


    def setUp(self):
        self.create_weblab()

    def test_tasks(self):
        runner = CliRunner()

        with runner.isolated_filesystem():
            result = runner.invoke(self.app.cli, ["fake-new-user"])
            self.assertEquals(result.exit_code, 0)

            result = runner.invoke(self.app.cli, ["fake-status"])
            self.assertIn("Should finish: 5", result.output)
            self.assertEquals(result.exit_code, 0)

            result = runner.invoke(self.app.cli, ["fake-dispose"])
            self.assertIn("Deleted", result.output)
            self.assertEquals(result.exit_code, 0)

            result = runner.invoke(self.app.cli, ["fake-status"])
            self.assertIn("Session not found", result.output)
            self.assertEquals(result.exit_code, 0)

class WebLabInitErrorsTest(unittest.TestCase):

    def _check_error(self, config, error_class, message):
        with self.assertRaises(error_class) as cm:
            self.weblab = weblablib.WebLab()
            self.app = Flask(__name__)
            self.app.config.update(config)
            self.weblab.init_app(self.app)
        
        self.assertIn(message, str(cm.exception))

    def test_callback(self):
        self._check_error({
                'WEBLAB_USERNAME': 'weblabdeusto',
                'WEBLAB_PASSWORD': 'password',
                'SERVER_NAME': 'localhost:5000',
            }, ValueError, "Invalid callback")

    def test_username(self):
        self._check_error({
                'WEBLAB_CALLBACK_URL': '/mylab/callback',
                'WEBLAB_PASSWORD': 'password',
                'SERVER_NAME': 'localhost:5000',
            }, ValueError, "Missing WEBLAB_USERNAME")

    def test_password(self):
        self._check_error({
                'WEBLAB_CALLBACK_URL': '/mylab/callback',
                'WEBLAB_USERNAME': 'weblabdeusto',
                'SERVER_NAME': 'localhost:5000',
            }, ValueError, "Missing WEBLAB_PASSWORD")

