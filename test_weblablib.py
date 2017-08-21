import os
import sys
import json
import time
import base64
import datetime

import six
if six.PY2:
    from StringIO import StringIO
else:
    from io import StringIO
from flask import Flask, url_for, render_template_string, g, session
import flask.cli as flask_cli

import weblablib
import unittest
from click.testing import CliRunner


os.environ['FLASK_APP'] = 'fake.py' # Overrided later
cmp = lambda a, b: a.__cmp__(b)

class StdWrap(object):
    def __enter__(self):
        self.sysout = sys.stdout
        self.syserr = sys.stderr
        self.fake_stdout = sys.stdout = StringIO()
        self.fake_stderr = sys.stderr = StringIO()

    def __exit__(self, *args, **kwargs):
        sys.stdout = self.sysout
        sys.stderr = self.syserr

class BaseWebLabTest(unittest.TestCase):
    def get_config(self):
        return {
            'SECRET_KEY': 'super-secret',
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': self.server_name,
            'WEBLAB_SCHEME': 'https',
            'WEBLAB_AUTOCLEAN_THREAD': False, # No thread
            'WEBLAB_TASK_THREADS_PROCESS': 0, # No thread
        }

    def create_weblab(self):
        self.weblab = weblablib.WebLab()
        self.app = Flask(__name__)
        flask_cli.locate_app = lambda *args: self.app
        self.server_name = 'localhost:5000'
        self.app.config.update(self.get_config())
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
            return self.task()

        with self.assertRaises(ValueError) as cm:
            @self.weblab.task()
            def task():
                self.task()

        self.assertIn("same name", str(cm.exception))
           

        self.current_task = task

    def get_json(self, rv):
        return json.loads(rv.get_data(as_text=True))

    def get_text(self, rv):
        return rv.get_data(as_text=True)

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

class SimpleUnauthenticatedTest(BaseWebLabTest):
    def test_token(self):
        token1 = self.weblab.create_token()
        token2 = self.weblab.create_token()
        self.assertNotEquals(token1, token2)

    def test_callback_initial_url(self):
        self.weblab._initial_url = None
        
        with StdWrap():
            with self.app.test_client() as client:
                result = self.get_text(client.get('/mylab/callback/session.not.found'))

        self.assertIn('ERROR', result)
        self.assertIn('weblab.initial_url', result)

    def test_callback(self):
        with self.app.test_client() as client:
            result = self.get_text(client.get('/mylab/callback/session.not.found'))
            self.assertIn('forbidden', result)

    def test_anonymous(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            self.assertTrue(weblablib.weblab_user.is_anonymous)
            self.assertFalse(weblablib.weblab_user.active)

    def test_poll_url(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            url = url_for('weblab_poll_url', session_id='does.not.exist')
            result = self.get_json(client.get(url))
            self.assertIn("Different session", result['reason'])
            
            with client.session_transaction() as sess:
                sess[self.weblab._session_id_name] = 'does.not.exist'

            result = self.get_json(client.get(url))
            self.assertIn("Not found", result['reason'])

    def test_poll_script(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            result = render_template_string("{{ weblab_poll_script() }}")
            self.assertIn('session_id not found', result)

    def test_unauthorized(self):
         with self.app.test_client() as client:
            result = self.get_text(client.get('/lab/'))
            self.assertIn("Access forbidden", result)

    def test_dispose_wrong_responses(self):
        with self.app.test_client() as client:
            request_data = {
            }
            rv = client.post('/weblab/sessions/{}'.format('foo'), data=json.dumps(request_data), headers=self.auth_headers)
            self.assertIn("Unknown", self.get_json(rv)['message'])

            request_data = {
                'action': 'look at the mountains'
            }
            rv = client.post('/weblab/sessions/{}'.format('foo'), data=json.dumps(request_data), headers=self.auth_headers)
            self.assertIn("Unknown", self.get_json(rv)['message'])

            request_data = {
                'action': 'delete'
            }
            rv = client.post('/weblab/sessions/{}'.format('does.not.exist'), data=json.dumps(request_data), headers=self.auth_headers)
            self.assertIn("Not found", self.get_json(rv)['message'])

class UnauthorizedLinkSimpleTest(BaseWebLabTest):
    def get_config(self):
        config = super(UnauthorizedLinkSimpleTest, self).get_config()
        config['WEBLAB_UNAUTHORIZED_LINK'] = 'http://mylink'
        return config

    def test_unauthorized_link(self):
         with self.app.test_client() as client:
            rv = client.get('/lab/', follow_redirects=False)
            self.assertEquals(rv.location, 'http://mylink')

class UnauthorizedTemplateSimpleTest(BaseWebLabTest):
    def get_config(self):
        config = super(UnauthorizedTemplateSimpleTest, self).get_config()
        config['WEBLAB_UNAUTHORIZED_TEMPLATE'] = 'mytemplate.html'
        return config

    def test_unauthorized_template(self):
        def new_render_template(location):
            return location

        old_render_template = weblablib.render_template

        with self.app.test_client() as client:
            weblablib.render_template = new_render_template
            try:
                lab_result = self.get_text(client.get('/lab/'))
            finally:
                weblablib.render_template = old_render_template

            self.assertEquals(lab_result, 'mytemplate.html')

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
        response = self.get_json(rv)
        self.session_id = response['session_id']
        launch_url = response['url']
        relative_launch_url = launch_url.split(self.server_name, 1)[1]
        return launch_url, self.session_id
    
    def status(self, session_id = None):
        if session_id is None:
            session_id = self.session_id

        rv = self.weblab_client.get('/weblab/sessions/{}/status'.format(session_id), headers=self.auth_headers)
        return self.get_json(rv)

    def dispose(self, session_id = None):
        if session_id is None:
            session_id = self.session_id

        request_data = {
            'action': 'delete',
        }
        rv = self.weblab_client.post('/weblab/sessions/{}'.format(session_id), data=json.dumps(request_data), headers=self.auth_headers)
        return self.get_json(rv)

class UserTest(BaseSessionWebLabTest):

    def lab(self):
        task = self.current_task.delay()
        # check that it's a dictionary
        weblablib.weblab_user.data['foo'] = 'bar'

        # And in any case build another
        if weblablib.weblab_user.active:
            weblablib.weblab_user.data = {'foo': 'bar'}

        return render_template_string("@@task@@%s@@task@@{{ weblab_poll_script() }}" % task.task_id)

    def task(self):
        self.counter += 1
        time.sleep(0.2)
        return [ self.counter, weblablib.weblab_user.data['foo'] ]

    def test_simple(self):
        # New user 
        launch_url1, session_id1 = self.new_user()

        # counter is zero
        self.counter = 0
        
        # We call the relative_launch_url. It is redirected to the lab, which
        # starts a new task, which establishes that counter is zero
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))

        self.assertEquals(weblablib.weblab_user.session_id, session_id1)

        task_id = response.split('@@task@@')[1]

        # There is one task, which is running
        self.assertEquals(len(self.weblab.tasks), 1)
        self.assertEquals(len(self.weblab.running_tasks), 1)

        task1 = self.weblab.get_task(task_id)
        self.assertIsNotNone(task1)
        self.assertEquals(task1.name, 'task')
        self.assertEquals(task1.status, 'submitted')
        self.assertEquals(task1.session_id, session_id1)
        self.assertIsNone(task1.result)
        self.assertIsNone(task1.error)

        # But the counter is still zero
        self.assertEquals(self.counter, 0)

        # Run the tasks
        self.weblab.run_tasks()

        # The task has been run
        self.assertEquals(self.counter, 1)

        # There is still 1 task in this session, but no running task
        self.assertEquals(len(self.weblab.tasks), 1)
        self.assertEquals(len(self.weblab.running_tasks), 0)
        
        # Let's retrieve the task again
        task2 = self.weblab.get_task(task_id)
        self.assertEquals(task2.status, 'done')
        self.assertIsNone(task2.error)
        self.assertEquals(task2.result, [1, 'bar'])

        # And let's see how it's the same task as before
        self.assertEquals(task1, task2)
        self.assertEquals(hash(task1), hash(task2))
        self.assertEquals(cmp(task1, task2), 0)
        self.assertFalse(task1 < task2)
        self.assertFalse(task2 < task1)

        # sys.maxint/maxsize is the maximum integer. Any hash will be lower than that
        # (except for if suddenly the random string is exactly maxint...)
        if six.PY2:
            self.assertTrue(task1 < sys.maxint)
        else:
            self.assertTrue(task1 < sys.maxsize)

        self.assertIn(task1.task_id, repr(task1))
        self.assertNotEquals(task1, task1.task_id)
        self.assertNotEquals(cmp(task1, task1.task_id), 0)

        # Cool!

        self.client.get(url_for('weblab_poll_url', session_id=session_id1))
        self.client.get('/poll')
        self.client.get('/logout')

        self.weblab.clean_expired_users()

        self.status(session_id1)
        self.dispose(session_id1)
        
        self.client.get('/lab/')
        self.assertFalse(weblablib.weblab_user.active)
        self.assertFalse(weblablib.weblab_user.is_anonymous)
        self.assertEquals(weblablib.weblab_user.time_left, 0)
        self.assertEquals(weblablib.weblab_user.session_id, session_id1)
        self.assertIn(session_id1, str(weblablib.weblab_user))
        with self.assertRaises(NotImplementedError):
            weblablib.weblab_user.data = {}

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

    def test_app_trailing_slashes(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback/',
            'WEBLAB_BASE_URL': '/mylab/',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
        })
        with StdWrap():
            weblab = weblablib.WebLab(app)
        weblab._cleanup()

    def test_missing_server_name(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
        })
        with StdWrap():
            sysargv = sys.argv
            sys.argv = list(sys.argv) + [ 'fake-new-user']
            try:
                weblab = weblablib.WebLab(app)
            finally:
                sys.argv = sysargv
        weblab._cleanup()

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
