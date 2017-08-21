import os
import json
import base64
import datetime

from flask import Flask, url_for, render_template_string
import flask.cli as flask_cli

import weblablib
import unittest
from click.testing import CliRunner


os.environ['FLASK_APP'] = 'fake.py' # Overrided later

class BaseWebLabTest(unittest.TestCase):
    def create_weblab(self):
        self.weblab = weblablib.WebLab()
        self.app = Flask(__name__)
        flask_cli.locate_app = lambda *args: self.app
        self.server_name = 'localhost:5000'
        self.app.config.update({
            'SECRET_KEY': 'super-secret',
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': self.server_name,
            'WEBLAB_SCHEME': 'https',
            'WEBLAB_AUTOCLEAN_THREAD': False, # No thread
            'WEBLAB_TASK_THREADS_PROCESS': 0, # No thread
        })
        self.auth_headers = {
            'Authorization': 'Basic ' + base64.encodestring(b'weblabdeusto:password').decode('utf8').strip(),
        }
        self.weblab.init_app(self.app)
        self.weblab._redis_manager.client.flushall()

        @self.weblab.on_start
        def on_start(client_data, server_data):
            self.on_start(client_data, server_data)

        @self.weblab.on_dispose
        def on_dispose():
            self.on_dispose()

        @self.weblab.initial_url
        def initial_url():
            return url_for('lab')

        @self.app.route('/lab/')
        @weblablib.requires_login
        def lab():
            return self.lab()

        @self.app.route('/lab/active')
        @weblablib.requires_active
        def lab_active():
            return self.lab()

        @self.app.route('/logout')
        @weblablib.requires_active
        def logout():
            weblablib.logout()
            return "logout"

        @self.app.route('/poll')
        @weblablib.requires_active
        def poll():
            weblablib.poll()
            weblablib.poll() # Twice so as to test g.poll_requested
            return "poll"

        @self.weblab.task()
        def task():
            self.task()

        with self.assertRaises(ValueError) as cm:
            @self.weblab.task()
            def task():
                self.task()

        self.assertIn("same name", str(cm.exception))
           

        self.current_task = task

    def on_start(self, client_data, server_data):
        pass

    def on_dispose(self):
        pass

    def lab(self):
        return ":-)"

    def task(self):
        pass

    def setUp(self):
        self.create_weblab()

    def tearDown(self):
        self.weblab._cleanup()

class VerySimpleTest(BaseWebLabTest):
    def test_token(self):
        token1 = self.weblab.create_token()
        token2 = self.weblab.create_token()
        self.assertNotEquals(token1, token2)

class BaseSessionWebLabTest(BaseWebLabTest):
    def setUp(self):
        super(BaseSessionWebLabTest, self).setUp()
        # self.weblab_client is stateless, sessionless
        self.weblab_client = self.app.test_client()
        # while self.client represents the user web browser
        self.client = self.app.test_client(use_cookies=True)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        super(BaseSessionWebLabTest, self).tearDown()

    def new_user(self, name='Jim Smith', username='jim.smith', username_unique='jim.smith@labsland', assigned_time=300, back='http://weblab.deusto.es'):
        assigned_time = float(assigned_time)

        start_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '.0'

        request_data = {
            'client_initial_data': {},
            'server_initial_data': {
                'priority.queue.slot.start': start_time,
                'priority.queue.slot.length': assigned_time,
                'request.username': username,
                'request.full_name': name,
                'request.username.unique': username_unique,
            },
            'back': back,
        }
        rv = self.weblab_client.post('/weblab/sessions/', data=json.dumps(request_data), headers=self.auth_headers)
        response = json.loads(rv.get_data(as_text=True))
        self.session_id = response['session_id']
        self.launch_url = response['url']
        return response
    
    def status(self, session_id = None):
        if session_id is None:
            session_id = self.session_id

        rv = self.weblab_client.get('/weblab/sessions/{}/status'.format(session_id), headers=self.auth_headers)
        return json.loads(rv.get_data(as_text=True))

    def dispose(self, session_id = None):
        if session_id is None:
            session_id = self.session_id

        request_data = {
            'action': 'delete',
        }
        rv = self.weblab_client.post('/weblab/sessions/{}', data=json.dumps(request_data), headers=self.auth_headers)
        return json.loads(rv.get_data(as_text=True))

class SimpleTest(BaseSessionWebLabTest):
    def lab(self):
        self.current_task.delay()
        return render_template_string("{{ weblab_poll_script() }}")

    def task(self):
        self.counter += 1
        return None

    def test_simple(self):
        self.new_user()

        url = self.launch_url.split(self.server_name, 1)[1]

        self.counter = 0
        self.client.get(url, follow_redirects=True)
        self.assertEquals(len(self.weblab.tasks), 1)
        self.assertEquals(len(self.weblab.running_tasks), 1)
        self.weblab.run_tasks()
        self.assertEquals(len(self.weblab.tasks), 1)
        self.assertEquals(len(self.weblab.running_tasks), 0)
        self.assertEquals(self.counter, 1)

        self.client.get('/poll')
        self.client.get('/logout')

        self.status()
        self.dispose()

class CLITest(BaseWebLabTest):

    def test_cli_flow(self):
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

            result = runner.invoke(self.app.cli, ["fake-dispose"])
            self.assertIn("Session not found", result.output)
            self.assertEquals(result.exit_code, 0)

            result = runner.invoke(self.app.cli, ["fake-status"])
            self.assertIn("Session not found", result.output)
            self.assertEquals(result.exit_code, 0)

            result = runner.invoke(self.app.cli, ["fake-new-user"])
            self.assertEquals(result.exit_code, 0)

            request_data = {
                'action': 'delete',
            }
            session_id_line = [ line for line in result.output.splitlines() if self.server_name in line ][0]
            session_id = session_id_line.strip().split('/')[-1]
            self.weblab._redis_manager._tests_delete_user(session_id)

            result = runner.invoke(self.app.cli, ["fake-dispose"])
            self.assertIn("Not found", result.output)
            self.assertEquals(result.exit_code, 0)

    def test_other_cli(self):
        runner = CliRunner()
        
        result = runner.invoke(self.app.cli, ["clean-expired-users"])
        self.assertEquals(result.exit_code, 0)

        result = runner.invoke(self.app.cli, ["run-tasks"])
        self.assertEquals(result.exit_code, 0)

class WebLabConfigErrorsTest(unittest.TestCase):

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

class WebLabSetupErrorsTest(unittest.TestCase):
    def test_empty_app(self):
        with self.assertRaises(ValueError) as cm:
            weblablib.WebLab().init_app(None)

        self.assertIn("Flask app", str(cm.exception))

    def test_app_twice(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        weblab = weblablib.WebLab(app)
        weblab.init_app(app) # No problem
        weblab._cleanup()

    def test_app_twice_different_apps(self):
        app1 = Flask(__name__)
        app1.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        app2 = Flask(__name__)
        weblab = weblablib.WebLab(app1)
        with self.assertRaises(ValueError) as cm:
            weblab.init_app(app2)

        self.assertIn('different app', str(cm.exception))
        weblab._cleanup()

    def test_app_two_weblabs_same_app(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'WEBLAB_BASE_URL': '/foo',
            'SERVER_NAME': 'localhost:5000',
        })
        weblab1 = weblablib.WebLab(app)
        with self.assertRaises(ValueError) as cm:
            weblab2 = weblablib.WebLab(app)

        self.assertIn('already installed', str(cm.exception))

        weblab1._cleanup()

    def test_app_twice_different_config(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        weblab = weblablib.WebLab(app)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback2',
        })

        with self.assertRaises(ValueError) as cm:
            weblab.init_app(app)

        self.assertIn('different config', str(cm.exception))
        weblablib._cleanup_all()
        weblab._cleanup()

    def _create_weblab(self):
        self.app = Flask(__name__)
        self.app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        self.weblab = weblablib.WebLab(self.app)
        self.weblab.init_app(self.app) # No problem

    def test_initial_url_duplicated(self):
        self._create_weblab()

        try:
            @self.weblab.initial_url
            def foo():
                pass
            
            with self.assertRaises(ValueError):
                @self.weblab.initial_url
                def bar():
                    pass
        finally:
            self.weblab._cleanup()

    def test_on_start_duplicated(self):
        self._create_weblab()

        try:
            @self.weblab.on_start
            def foo():
                pass
            
            with self.assertRaises(ValueError):
                @self.weblab.on_start
                def bar():
                    pass
        finally:
            self.weblab._cleanup()

    def test_on_dispose_duplicated(self):
        self._create_weblab()

        try:
            @self.weblab.on_dispose
            def foo():
                pass
            
            with self.assertRaises(ValueError):
                @self.weblab.on_dispose
                def bar():
                    pass
        finally:
            self.weblab._cleanup()
