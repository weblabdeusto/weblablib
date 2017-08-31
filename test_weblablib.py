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

class WithoutWebLabTest(unittest.TestCase):
    def test_extension(self):
        app = Flask(__name__)
        with self.assertRaises(weblablib.WebLabNotInitializedError):
            with app.app_context():
                weblablib._current_weblab()

class BaseWebLabTest(unittest.TestCase):
    def get_config(self):
        return {
            'SECRET_KEY': 'super-secret',
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
        self.wrong_auth_headers = {
            'Authorization': 'Basic ' + base64.encodestring(b'wrong_weblabdeusto:wrong_password').decode('utf8').strip(),
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

class WebLabApiTest(BaseWebLabTest):
    def test_api(self):
        with self.app.test_client() as client:
            result = self.get_json(client.get('/weblab/sessions/api'))
            self.assertEquals(result['api_version'], '1')

    def test_weblab_test_without_auth(self):
        with self.app.test_client() as client:
            result = self.get_json(client.get('/weblab/sessions/test'))
            self.assertEquals(result['valid'], False)
            self.assertIn("no username", result['error_messages'][0])

    def test_weblab_test_with_wrong_auth(self):
        with StdWrap():
            with self.app.test_client() as client:
                result = self.get_json(client.get('/weblab/sessions/test', headers=self.wrong_auth_headers))
                self.assertEquals(result['valid'], False)
                self.assertIn("wrong username", result['error_messages'][0])

    def test_weblab_test_with_right_auth(self):
        with self.app.test_client() as client:
            result = self.get_json(client.get('/weblab/sessions/test', headers=self.auth_headers))
            self.assertEquals(result['valid'], True)

    def test_weblab_status_with_wrong_auth(self):
        with StdWrap():
            with self.app.test_client() as client:
                result = self.get_text(client.get('/weblab/sessions/<invalid>/status', headers=self.wrong_auth_headers))
                self.assertIn("seem to be", result)

class SimpleUnauthenticatedTest(BaseWebLabTest):
    def test_token(self):
        token1 = self.weblab.create_token()
        token2 = self.weblab.create_token()
        self.assertNotEquals(token1, token2)

    def test_task_not_found(self):
        task = self.weblab.get_task("does.not.exist")
        self.assertIsNone(task)

    def test_callback_initial_url(self):
        self.weblab._initial_url = None

        with StdWrap():
            with self.app.test_client() as client:
                result = self.get_text(client.get('/callback/session.not.found'))

        self.assertIn('ERROR', result)
        self.assertIn('weblab.initial_url', result)

    def test_callback(self):
        with self.app.test_client() as client:
            result = self.get_text(client.get('/callback/session.not.found'))
            self.assertIn('forbidden', result)

    def test_anonymous(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            self.assertTrue(weblablib.weblab_user.is_anonymous)
            self.assertFalse(weblablib.weblab_user.active)
            self.assertIsNone(weblablib.weblab_user.locale)

    def test_anonymous_on_active(self):
        with self.app.test_client() as client:
            rv = client.get('/lab/active')
            self.assertIn("forbidden", self.get_text(rv))

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

    def test_logout_url(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            url = url_for('weblab_logout_url', session_id='does.not.exist')
            result = self.get_json(client.get(url))
            self.assertIn("Different session", result['reason'])

    def test_poll_script(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            result = render_template_string("{{ weblab_poll_script() }}")
            self.assertIn('session_id not found', result)

    def test_unauthorized(self):
         with self.app.test_client() as client:
            result = self.get_text(client.get('/lab/'))
            self.assertIn("Access forbidden", result)

    def test_dispose_wrong_requests(self):
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

class SimpleNoTimeoutUnauthenticatedTest(BaseWebLabTest):
    def get_config(self):
        config = super(SimpleNoTimeoutUnauthenticatedTest, self).get_config()
        config['WEBLAB_TIMEOUT'] = 0
        return config

    def test_poll_script_timeout(self):
        with self.app.test_client() as client:
            client.get('/lab/')
            result = render_template_string("{{ weblab_poll_script() }}")
            self.assertIn('timeout is 0', result)

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

class TestNewUserError(Exception):
    pass

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

    def new_user(self, name='Jim Smith', username='jim.smith', username_unique='jim.smith@labsland', 
                 assigned_time=300, back='http://weblab.deusto.es', language='en',
                 experiment_name='mylab', category_name='Lab experiments'):
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
                'request.locale': language,
                'request.experiment_id.experiment_name': experiment_name,
                'request.experiment_id.category_name': category_name,
            },
            'back': back,
        }
        rv = self.weblab_client.post('/weblab/sessions/', data=json.dumps(request_data), headers=self.auth_headers)
        response = self.get_json(rv)
        if 'session_id' in response:
            self.session_id = response['session_id']
            launch_url = response['url']
            relative_launch_url = launch_url.split(self.server_name, 1)[1]
            return launch_url, self.session_id
        raise TestNewUserError(response['message'])

    
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
            # Optional, forces an immediate synchronization
            weblablib.weblab_user.update_data()
            weblablib.weblab_user.data = {'foo': 'bar'}

        return render_template_string("""@@task@@%s@@task@@{{ weblab_poll_script() }}
            {{ weblab_poll_script(logout_on_close=True, callback='myfunc') }}""" % task.task_id)

    def task(self):
        self.counter += 1
        weblablib.current_task.data = {'inside': 'previous'}
        weblablib.current_task.update_data({'inside': 'yes'})
        return [ self.counter, weblablib.weblab_user.data['foo'] ]

    def test_simple(self):
        # New user 
        launch_url1, session_id1 = self.new_user(language='es')

        # counter is zero
        self.counter = 0
        
        # We call the relative_launch_url. It is redirected to the lab, which
        # starts a new task, which establishes that counter is zero
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))

        self.assertEquals(weblablib.weblab_user.session_id, session_id1)
        self.assertEquals(weblablib.weblab_user.locale, 'es')
        self.assertEquals(weblablib.weblab_user.full_name, 'Jim Smith')
        self.assertEquals(weblablib.weblab_user.experiment_name, 'mylab')
        self.assertEquals(weblablib.weblab_user.category_name, 'Lab experiments')
        self.assertEquals(weblablib.weblab_user.experiment_id, 'mylab@Lab experiments')

        task_id = response.split('@@task@@')[1]

        # There is one task, which is running
        self.assertEquals(len(self.weblab.tasks), 1)
        self.assertEquals(len(self.weblab.running_tasks), 1)

        task1 = self.weblab.get_task(task_id)
        self.assertIsNotNone(task1)
        self.assertEquals(task1.name, 'task')
        self.assertEquals(task1.status, 'submitted')
        self.assertTrue(task1.submitted)
        self.assertFalse(task1.finished)
        self.assertFalse(task1.done)
        self.assertFalse(task1.failed)
        self.assertFalse(task1.running)
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
        self.assertTrue(task2.done)
        self.assertTrue(task2.finished)
        self.assertFalse(task2.failed)
        self.assertFalse(task2.submitted)
        self.assertFalse(task2.running)
        self.assertIsNone(task2.error)
        self.assertEquals(task2.result, [1, 'bar'])
        self.assertIn('inside', task2.data)
        self.assertEquals(task2.data['inside'], 'yes')

        self.assertFalse(weblablib.current_task)

        # And let's see how it's the same task as before
        self.assertEquals(task1, task2)
        self.assertEquals(hash(task1), hash(task2))
        self.assertEquals(cmp(task1, task2), 0)
        self.assertFalse(task1 < task2)
        self.assertFalse(task2 < task1)

        # sys.maxint/maxsize is the maximum integer. Any hash will be lower than that
        # (except for if suddenly the random string is exactly maxint...)
        if six.PY2:
            maxvalue = sys.maxint
            self.assertTrue(task1 < maxvalue)

        # In python 3 it's quite difficult to find the largest hashable value
        # ( sys.hash_info.modulus - 1 is the largest number where hash(n) == n, but 
        # for many other hash(x) > hash(2 ^ 61 - 1))

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

        rv = self.client.get('/lab/active')
        self.assertEquals(rv.location, 'http://weblab.deusto.es')
        
        self.client.get('/lab/')
        self.assertFalse(weblablib.weblab_user.active)
        self.assertFalse(weblablib.weblab_user.is_anonymous)
        self.assertEquals(weblablib.weblab_user.time_left, 0)
        self.assertEquals(weblablib.weblab_user.session_id, session_id1)
        self.assertIn(session_id1, str(weblablib.weblab_user))
        with self.assertRaises(NotImplementedError):
            weblablib.weblab_user.data = {}

        with self.assertRaises(NotImplementedError):
            weblablib.weblab_user.update_data()
        self.assertEquals(weblablib.weblab_user.locale, 'es')
        self.assertEquals(weblablib.weblab_user.full_name, 'Jim Smith')
        self.assertEquals(weblablib.weblab_user.experiment_name, 'mylab')
        self.assertEquals(weblablib.weblab_user.category_name, 'Lab experiments')
        self.assertEquals(weblablib.weblab_user.experiment_id, 'mylab@Lab experiments')

    def test_status_concrete_time_left(self):
        # New user, with 3 seconds
        launch_url1, session_id1 = self.new_user(assigned_time=3)
        
        should_finish = self.status()['should_finish']

        # Ask in 2..3 seconds (not 5)
        self.assertTrue(2 <= should_finish <= 3)

    def test_status_exited(self):
        # New user, with 3 seconds
        launch_url1, session_id1 = self.new_user(assigned_time=3)

        self.client.get(launch_url1, follow_redirects=True)
        self.client.get(url_for('weblab_logout_url', session_id=session_id1))
        
        should_finish = self.status()['should_finish']

        # Logged out
        self.assertEquals(should_finish, -1)

    def test_status_time_left_passed(self):
        # New user, with 3 seconds
        launch_url1, session_id1 = self.new_user(assigned_time=0.1)

        self.client.get(launch_url1, follow_redirects=True)
        time.sleep(0.2)
        
        should_finish = self.status()['should_finish']

        # time passed
        self.assertEquals(should_finish, -1)

    def test_status_timeout(self):
        # New user, with 3 seconds
        self.weblab.timeout = 0.1
        launch_url1, session_id1 = self.new_user()

        self.client.get(launch_url1, follow_redirects=True)
        time.sleep(0.2)
        
        should_finish = self.status()['should_finish']

        # time passed
        self.assertEquals(should_finish, -1)

class TaskFailTest(BaseSessionWebLabTest):

    def lab(self):
        task = self.current_task.delay()
        return str(task.task_id)

    def task(self):
        10 / 0
        return -1

    def test_task_fail(self):
        # New user 
        launch_url1, session_id1 = self.new_user()

        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))

        task_id = response

        task = self.weblab.get_task(response)
        self.assertEquals(task.status, 'submitted')
        self.assertTrue(task.submitted)
        self.assertFalse(task.failed)
        self.assertFalse(task.finished)
        self.assertFalse(task.running)
        self.assertFalse(task.done)
        
        with StdWrap():
            self.weblab.run_tasks()

        self.assertEquals(task.status, 'failed')
        self.assertTrue(task.failed)
        self.assertTrue(task.finished)
        self.assertFalse(task.done)
        self.assertFalse(task.running)
        self.assertFalse(task.submitted)
        self.assertIsNone(task.result)
        self.assertIsNotNone(task.error)
        self.assertEqual(task.error['code'], 'exception')
        self.assertIn('zero', task.error['message'])
        self.assertEqual(task.error['class'], 'ZeroDivisionError')

class MyLabUser(object):
    def __init__(self, username_unique, username):
        self.username_unique = username_unique
        self.username = username

class LoadUserTest(BaseSessionWebLabTest):
    def test_load_no_loader(self):
        launch_url1, session_id1 = self.new_user()
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))

        user = weblablib.weblab_user.user
        self.assertIsNone(user)

    def test_load_simple(self):
        @self.weblab.user_loader
        def user_loader(username_unique):
            return MyLabUser(username_unique, weblablib.weblab_user.username)

        launch_url1, session_id1 = self.new_user(username='user1', username_unique='unique1')
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))
        user = weblablib.weblab_user.user
        self.assertIsInstance(user, MyLabUser)
        self.assertEquals(user.username, 'user1')
        self.assertEquals(user.username_unique, 'unique1')

        user2 = weblablib.weblab_user.user
        self.assertIsInstance(user2, MyLabUser)
        self.assertEquals(user2.username, 'user1')
        self.assertEquals(user2.username_unique, 'unique1')

        launch_url2, session_id2 = self.new_user(username='user2', username_unique='unique2')
        response = self.get_text(self.client.get(launch_url2, follow_redirects=True))
        user3 = weblablib.weblab_user.user
        self.assertIsInstance(user3, MyLabUser)
        self.assertEquals(user3.username, 'user2')
        self.assertEquals(user3.username_unique, 'unique2')

    def test_user_loader_fail(self):
        @self.weblab.user_loader
        def user_loader(username_unique):
            raise Exception("Random error")

        launch_url1, session_id1 = self.new_user(username='user1', username_unique='unique1')
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))
        with self.assertRaises(Exception) as cm:
            weblablib.weblab_user.user
        
        self.assertIn("Random error", str(cm.exception))


class LongTaskTest(BaseSessionWebLabTest):

    def get_config(self):
        config = super(LongTaskTest, self).get_config()
        config['WEBLAB_AUTOCLEAN_THREAD'] = True
        config['WEBLAB_TASK_THREADS_PROCESS'] = 3
        return config

    def lab(self):
        task = self.current_task.delay()
        return str(task.task_id)

    def task(self):
        time.sleep(0.6)
        return 0

    def test_long_task(self):
        self.weblab.cleaner_thread_interval = 0.1
        launch_url1, session_id1 = self.new_user()
        response = self.get_text(self.client.get(launch_url1, follow_redirects=True))
        task_id = response
        
        max_time = 3
        t0 = time.time()
        while True:
            task = self.weblab.get_task(task_id)
            if task.status == 'running':
                self.assertTrue(task.running)
                self.assertFalse(task.finished)
                self.assertFalse(task.done)
                self.assertFalse(task.failed)
                self.assertFalse(task.submitted)
                break
            self.assertEquals(task.status, 'submitted')
            time.sleep(0.03)

            if time.time() - t0 > max_time:
                self.fail("Too long checking for a submitted thread")

        self.client.get('/logout')
        time.sleep(0.2) # So other thread calls clean
        self.dispose()

class DisposeErrorTest(BaseSessionWebLabTest):

    def lab(self):
        return ":-)"

    def on_dispose(self):
        raise Exception("Testing error in the dispose method")

    def test_task_fail(self):
        # New user 
        launch_url1, session_id1 = self.new_user()
        
        with StdWrap():
            self.dispose()

class StartErrorTest(BaseSessionWebLabTest):

    def lab(self):
        return ":-)"

    def on_start(self, client_data, server_data):
        raise Exception("Testing error in the start method")

    def test_task_fail(self):
        old_dispose_user = weblablib._dispose_user
        def new_dispose_user(*args, **kwargs):
            raise Exception("weird error")

        weblablib._dispose_user = new_dispose_user
        try:
            with self.assertRaises(TestNewUserError):
                with StdWrap():
                    self.new_user()
        finally:
            weblablib._dispose_user = old_dispose_user

class CLITest(BaseWebLabTest):

    def test_cli_flow(self):
        runner = CliRunner()

        with runner.isolated_filesystem():
            result = runner.invoke(self.app.cli, ["fake-new-user", "--dont-open-browser"])
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

            result = runner.invoke(self.app.cli, ["fake-new-user", "--dont-open-browser"])
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

    def test_loop_cli(self):
        runner = CliRunner()

        weblablib._TESTING_LOOP = True
        result = runner.invoke(self.app.cli, ["loop"])
        self.assertEquals(result.exit_code, 0)

class CLIFailTest(BaseWebLabTest):
    def on_start(self, client_data, server_data):
        raise Exception("Error initializing laboratory")

    def test_cli_error(self):

        runner = CliRunner()

        with runner.isolated_filesystem():
            result = runner.invoke(self.app.cli, ["fake-new-user", "--dont-open-browser"])
            self.assertIn("Error processing", result.output)

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
                'WEBLAB_CALLBACK_URL': '',
                'WEBLAB_USERNAME': 'weblabdeusto',
                'WEBLAB_PASSWORD': 'password',
                'SERVER_NAME': 'localhost:5000',
            }, ValueError, "Empty URL")

    def test_username(self):
        self._check_error({
                'WEBLAB_PASSWORD': 'password',
                'SERVER_NAME': 'localhost:5000',
            }, ValueError, "Missing WEBLAB_USERNAME")

    def test_password(self):
        self._check_error({
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
            'WEBLAB_BASE_URL': '/mylab/',
            'WEBLAB_CALLBACK_URL': '/mylab/callback/',
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
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
        })
        with StdWrap():
            sysargv = sys.argv
            sys.argv = list(sys.argv) + [ 'fake-new-user', '--dont-open-browser']
            try:
                weblab = weblablib.WebLab(app)
            finally:
                sys.argv = sysargv
        weblab._cleanup()

    def test_app_twice(self):
        app = Flask(__name__)
        app.config.update({
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

    def test_app_no_thread_and_auto_clean(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
            'WEBLAB_NO_THREAD': True,
            'WEBLAB_AUTOCLEAN_THREAD': True,
        })
        weblab = weblablib.WebLab()
        with self.assertRaises(ValueError) as cm:
            weblab.init_app(app)

        self.assertIn('incompatible with WEBLAB_AUTOCLEAN_THREAD', str(cm.exception))
        weblab._cleanup()

    def test_app_no_thread_and_task_threads(self):
        app = Flask(__name__)
        app.config.update({
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
            'SERVER_NAME': 'localhost:5000',
            'WEBLAB_NO_THREAD': True,
            'WEBLAB_TASK_THREADS_PROCESS': 5,
        })
        weblab = weblablib.WebLab()
        with self.assertRaises(ValueError) as cm:
            weblab.init_app(app)

        self.assertIn('incompatible with WEBLAB_TASK_THREADS_PROCESS', str(cm.exception))
        weblab._cleanup()

    def test_app_two_weblabs_same_app(self):
        app = Flask(__name__)
        app.config.update({
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

    def test_user_loader_duplicated(self):
        self._create_weblab()

        try:
            @self.weblab.user_loader
            def user_loader(username_unique):
                pass
            
            with self.assertRaises(ValueError):
                @self.weblab.user_loader
                def user_loader2(username_unique):
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
