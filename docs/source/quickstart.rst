 .. _quickstart:

Quickstart
==========

Introduction
------------

First, let's put in context what we are doing: we have a laboratory that we want
to make remotely available, and that we can control in Python (2.7 or 3.x).
Let's imagine something super-simple:

 * A set of lights (and buttons to turn them on and off).

How this really works it's up to you. You could as well have an Arduino, or a
Raspberry Pi. Or you might be controlling a FPGA device or a regular
microcontroller. Or you might be controlling a control application with a PLC.
You may be managing some chemistry and have a set of switches so the hardware
does something. All this depends on your setup. **weblablib** works on top of
that. So let's imagine a fake code as follows:

.. code-block:: python

    def clean_resources():
        # Some code that turns off all the lights
        pass

    def switch_light_on(number, state):
        # Some code (e.g., using GPIO or something)
        # that turns a light on or off
        pass

    def is_light_on(number):
        # Some code that checks if a light is on or off
        return True

In particular, let's create a version of this software that stores everything
in disk in a JSON document called ``lights.json``. It's not thread safe, but
it is the easiest approach for this tutorial. Don't bother reading this code,
it simply stores information in disk.

.. code-block:: python

   import os
   import json

   def clean_resources():
       # Some code that turns off all the lights
       for n in range(1, 11):
           switch_light(n, False)

   def switch_light(number, state):
       # Some code (e.g., using GPIO or something)
       # that turns a light on or off
       if not os.path.exists('lights.json'):
           lights = {
              # 'light-1': False
           }
           for n in range(1, 11):
               lights['light-{}'.format(n)] = False
       else:
           lights = json.load(open('lights.json'))
       lights['light-{}'.format(number)] = state
       json.dump(lights, open('lights.json', 'w'), indent=4)

   def is_light_on(number):
       # Some code that checks if a light is on or off
       if not os.path.exists('lights.json'):
           return False
       return json.load(open('lights.json'))['light-{}'.format(number)]



And let's put this code in a file called ``hardware.py``.

Creating a dummy Flask app
--------------------------

.. note::

   If you already have certain experience with `Flask <http://flask.pocoo.org/>`_, you can get the code in
   the `examples/quickstart/step1 <https://github.com/weblabdeusto/weblablib/tree/master/examples/quickstart/step1>`_ `in the GitHub repository <https://github.com/weblabdeusto/weblablib>`_,
   and then continue to :ref:`quickstart_adding_weblablib`.

The next step is to create some basic code to create the web interface. We are
going to use `Flask <http://flask.pocoo.org/>`_, and do it step by step, so you
don't need to have prior knowledge. However, if you are not familiar with  and
find problems following the quickstart, you could check their `quickstart tutorial
<http://flask.pocoo.org/docs/latest/quickstart/>`_ first.

For Flask, we'll create first the application, called ``laboratory.py``:

.. code-block:: python

   from flask import Flask

   app = Flask(__name__)
   app.config.update({
       'SECRET_KEY': 'something-random',
   })

   @app.route('/')
   def index():
       return "Welcome to the laboratory!"


This is enough for having a very simple website. The next step is to install.
Please, proceed to read `the Flask installation documentation <http://flask.pocoo.org/docs/latest/installation/>`_.
If you are familiar with Python, you simply have to create a virtualenv (not strictly required, though), and run:

.. code-block:: bash

   $ pip install Flask


Once it is installed, you can run the following (you have more information in `Flask CLI documentation <http://flask.pocoo.org/docs/latest/installation/>`_):

.. code-block:: bash

   $ export FLASK_DEBUG=1
   $ export FLASK_APP=laboratory.py
   $ flask run
    * Serving Flask app "laboratory"
    * Forcing debug mode on
    * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
    * Restarting with stat
    * Debugger is active!
    * Debugger PIN: 324-368-642

In Windows environments, you might need to run:

.. code-block:: bash

   C:\...> set FLASK_DEBUG=1
   C:\...> set FLASK_APP=laboratory.py
   C:\...> flask run

From this point, you can use your web browser to go to http://localhost:5000/ and see the
message that was in the ``index`` function. Since we used ``FLASK_DEBUG``, you can change
the ``index`` code and you'll see in the console how it restarts the web server automatically.

Now, the code right now does not do much. Let's create a bit more! For example, if we want to
display 10 lights, we need to create some HTML code. So, create a ``templates`` folder, and add
a file called ``lab.html`` with the following contents:

.. code-block:: html

    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="utf-8">
        <meta http-equiv="X-UA-Compatible" content="IE=edge">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css" integrity="sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u" crossorigin="anonymous">
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap-theme.min.css" integrity="sha384-rHyoN1iRsVXV4nD0JutlnGaslCJuC7uwjduW9SVrLvRYooPp2bWYgmgJQIXwl/Sp" crossorigin="anonymous">

        <!-- HTML5 shim and Respond.js for IE8 support of HTML5 elements and media queries -->
        <!-- WARNING: Respond.js doesn't work if you view the page via file:// -->
        <!--[if lt IE 9]>
          <script src="https://oss.maxcdn.com/html5shiv/3.7.3/html5shiv.min.js"></script>
          <script src="https://oss.maxcdn.com/respond/1.4.2/respond.min.js"></script>
        <![endif]-->

      </head>
      <body>


        <div class="container">
          <div class="row">
            <h1>Welcome to <strong>mylab</strong>!</h1>
          </div>

          <div class="row">
            <p>This is just an example laboratory using <a href="https://weblablib.readthedocs.org">weblablib</a>.</p>
              <p>Time: <span id="timer"></span>.
            </div>
            <br><br>

            <div id="panel">
              <div class="row">
                  <h2>Lights: click on each light to change status (and read it in the console)</h2>
              </div>
              <br>
              <div class="row">
                {% for light in range(1, 11) %}
                <div class="col-sm-1 text-center">
                  Light {{ light }}
                  <br>
                  <a href="javascript:turnOff({{ light }})">
                    <img width="50px" id="light_{{ light }}_on" src="https://openclipart.org/download/116581/bulb-on.svg">
                  </a>
                  <a href="javascript:turnOn({{ light }})">
                    <img width="50px" id="light_{{ light }}_off" src="https://openclipart.org/download/110269/1296215547.svg">
                  </a>
                </div>
                {% endfor %}
              </div>
            </div>
          </div>


        <!-- jQuery (necessary for Bootstrap's JavaScript plugins) -->
        <script src="https://ajax.googleapis.com/ajax/libs/jquery/1.12.4/jquery.min.js"></script>
        <!-- Include all compiled plugins (below), or include individual files as needed -->
        <script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js" integrity="sha384-Tc5IQib027qvyjSMfHjOMaLkfuWVxZxUPnCJA7l2mCWNIpG9mGCD8wGNIcPD7Txa" crossorigin="anonymous"></script>

        <!-- Here we will have the scripts -->

      </body>
    </html>


The code itself is the standard `Bootstrap <https://getbootstrap.com/docs/3.3/>`_ template.
Bootstrap is a HTML, CSS and JavaScript framework that allows you to create interfaces very
quickly based on few principles, and compatible with other web frameworks. The key here
is that we have a ``container`` (so there will be some empty space on the right and left),
and then some ``row``, and in one of them, there is something about lights. Let's take a
closer look at that one:

.. code-block:: jinja

    <div class="row">
      {% for light in range(1, 11) %}
      <div class="col-sm-1 text-center">
        Light {{ light }}
        <br>
        <a href="javascript:turnOff({{ light }})">
          <img width="50px" id="light_{{ light }}_on" src="https://openclipart.org/download/116581/bulb-on.svg">
        </a>
        <a href="javascript:turnOn({{ light }})">
          <img width="50px" id="light_{{ light }}_off" src="https://openclipart.org/download/110269/1296215547.svg">
        </a>
      </div>
      {% endfor %}
    </div>

As you can see, this is not HTML code, but Jinja code. `Jinja <jinja.pocoo.org/>`_ is the default
templating framework used by Flask. It just repeats 10 times some HTML code, where ``{{ light }}``
will be 1, 2..10 in each iteration.

In this case we have 10 (1..10) lights in one block each. Each block has two images: one with
a light on and one with a light off. And each light has an ``id`` which is ``light_1_on`` or ``light_1_off``.
Also, if you click on any of those images, it will run the code ``javascript:turnOff(1)`` or ``javascript:turnOn(1)`` (being 1..10).

We had put the whole HTML code in ``templates/lab.html``, so it's time to change the ``laboratory.py`` code:

.. code-block:: python

   from flask import Flask, render_template

   app = Flask(__name__)
   app.config.update({
       'SECRET_KEY': 'something-random',
   })

   @app.route('/')
   def index():
       return render_template("lab.html")

If we refresh the website, we will see all the bulbs, on and off.


Now we are only missing doing something when the lights are clicked, as well as keeping the state.

To do so, let's take the ``hardware.py`` and start calling it:

.. code-block:: python

   from flask import Flask, request, render_template, jsonify
   import hardware

   app = Flask(__name__)
   app.config.update({
       'SECRET_KEY': 'something-random',
   })

   @app.route('/')
   def index():
       return render_template("lab.html")

   @app.route('/status')
   def status():
       # jsonify returns a JSON where {lights: result}
       # plus adds the 'application/json' headers, etc.
       return jsonify(lights=get_light_status(), error=False)

   @app.route('/lights/<number>/')
   def light(number):
       # request.args is a dictionary with the
       # query arguments (e.g., this checks ?state=true)
       state = request.args.get('state') == 'true'
       # We call the hardware with the state
       hardware.switch_light(number, state)
       # And return the whole status of everything
       return jsonify(lights=get_light_status(), error=False)

   def get_light_status():
       lights = {}
       for light in range(1, 11):
           lights['light-{}'.format(light)] = hardware.is_light_on(light)
       return lights


With this code, you can already test in your web browser going to URLs like:

 * http://localhost:5000/lights/1/?state=true (turn on light 1)
 * http://localhost:5000/lights/1/?state=false (turn off light 1)
 * http://localhost:5000/lights/1/?state=true (turn on light 1)
 * http://localhost:5000/lights/1/?state=false (turn off light 1)
 * http://localhost:5000/status (see current status, without changing anything)

As you can see, by entering in those URLs, you change the state of the fake lights.
You can also see that a file called ``lights.json`` has been automatically created,
and you can open it and read it.

The final step is to call from the HTML code to these URLs. We'll first create a
``static`` folder and inside we'll put a ``lab.js`` JavaScript file, with the following
contents:

.. code-block:: javascript

    function turnOn(number) {
        turnLight(number, true);
        return false;
    }

    function turnOff(number) {
        turnLight(number, false);
        return false;
    }

    function turnLight(num, state) {
        var url = LIGHT_URL.replace("LIGHT", num) + "?state=" + state;
        $.get(url).done(parseStatus);
    }

    function clean() {
        // Not yet
    }

    function parseStatus(newStatus) {
        if (newStatus.error == false) {
            for (var i = 1; i < 11; i++) {
                if(newStatus["lights"]["light-" + i]) {
                    $("#light_" + i + "_off").hide();
                    $("#light_" + i + "_on").show();
                } else {
                    $("#light_" + i + "_on").hide();
                    $("#light_" + i + "_off").show();
                }
            }
        }
    }

    var STATUS_INTERVAL = setInterval(function () {

        $.get(STATUS_URL).done(parseStatus).fail(clean);

    }, 1000);

    $.get(STATUS_URL).done(parseStatus);

As you can see, there are two variables which are not defined in the JavaScript file:

 * ``LIGHT_URL`` (which will be the URL of the lights)
 * ``STATUS_URL`` (Which will be the URL of the /status)

Other than that, the code does the following:
 * ``turnOn`` and ``turnOff`` call ``turnLight(num, state)``, which calls the
    ``/lights/1/?state=true`` web that you were calling before.
 * ``parseStatus`` receives a status (which is what any of the webs we
    implemented return) and for each light, if it's true, it hides one,
    and if it's off it hides the other light.

Therefore, every time we press on a light which is on, it will call
``turnOff(number)``, which will call the server, will modify the
``lights.json`` file, and when it obtains the ``status``, it will hide the
light on image and display the light off image. We are only missing how to
include this ``static/lab.js`` file in the HTML.

To do this, in the end of the ``lab.html`` file there are the following lines:

.. code-block:: html

       <!-- Here we will have the scripts -->

      </body>
   </html>

Under the ``Here we will...``, you must place the following code:

.. code-block:: html

     <!-- Here we will have the scripts -->
     <script>
       var STATUS_URL = "{{ url_for('status') }}";
       var LIGHT_URL = "{{ url_for('light', number='LIGHT') }}";
     </script>
     <script src="{{ url_for('static', filename='lab.js') }}"></script>

    </body>
   </html>

``url_for`` is the way Flask provides to point to URLs without having to hardcode them.
If where it says ``@app.route('/status')`` tomorrow you change the URL, all the code will
be updated, as long as the name of the function is the same.

.. warning::

   This approach (modifying state through a GET request, no special CSRF check) is
   very insecure and you shouldn't use it. Check the ``examples/advanced`` folder
   in the `GitHub weblablib repository <https://github.com/weblabdeusto/weblablib/>`_
   for a better approach. This example is just focused on having a very simple basis
   where we can rely for explaining **weblablib**.

.. _quickstart_adding_weblablib:

Adding weblablib
----------------

Why using weblablib
~~~~~~~~~~~~~~~~~~~

As you've seen in the previous example, you have a very simple website that does something
with certain hardware (faked in ``hardware.py``). It works quite well: you turn a light
off, and even if you refresh the website, stop the server and restart it, you'll see the
light off.

However, this code is very far from being usable as a remote laboratory:

 * There is no authentication neither authorization. Who is the user? Why does he/she have access?
 * What if we need an scheduling system (such as a queue)? How do we ensure that students come
   once at a time instead of multiple students accessing at the same time? In this particular case
   it might not be very important, but if for example we had a microcontroller, we would need a
   queue so when one student is .
 * How does the teacher know who and when used the lab?
 * How do you integrate the laboratory in a Learning Management System such as Moodle, Sakai, EdX or similar?
 * How does the administrator establish how long the student can access, etc.?

For all these things, you can either implement and test everything by yourself, or rely on a remote
laboratory management system, such as `WebLab-Deusto <https://weblabdeusto.readthedocs.org/>`_. Most
of those features (administration, analytics, scheduling) are covered by WebLab-Deusto, but at some
point WebLab-Deusto delegates on the particular laboratories by sending them users. So for example a
user will be authenticated in WebLab-Deusto, and attempt to access the laboratory, and still
WebLab-Deusto will be dealing with the queue of users. When the user finally has permission to use
the laboratory in that particular time, then WebLab-Deusto contacts the laboratory telling it in a
secure way "I'm WebLab-Deusto, I have this particular student, get ready for it".

The laboratory still has to implement this protocol and life cycle. And here is where **weblablib**
enters, by implementing the protocol and making it easy for laboratory developers to focus on the
laboratory.

.. note::

   You can download the code of this section in the github repository, folder `examples/quickstart/step2 <https://github.com/weblabdeusto/weblablib/tree/master/examples/quickstart/step2>`_.

   Note that in it, we have also included some time-related code in the JavaScript file.


Adding WebLab
~~~~~~~~~~~~~

To use **weblablib**, you have to create a ``WebLab`` instance and initialize it with the Flask app. You can
either do both at once:

.. code-block:: python

   from weblablib import WebLab

   weblab = WebLab(app)

or do it in two phases:

.. code-block:: python

   from weblablib import WebLab

   weblab = WebLab()

   # Later

   weblab.init_app(app)

What is important is that the configuration is loaded in Flask *before* ``init_app`` (or ``WebLab(app)``).

Additionally, ``weblablib`` has more interesting features. For example, you may want to establish that a
particular Flask view is only available for WebLab users:

.. code-block:: python

   from weblablib import requires_active

   @app.route('/')
   @requires_active
   def index():
       # ...

   @app.route('/status')
   @requires_active
   def status():
       # ...

   @app.route('/lights/<number>/')
   @requires_active
   def light(number):
       # ...

In this case, you are defining that the three views ``status`` and ``light`` can only be accessed by
active WebLab users (users who have been assigned and whose time in the laboratory is not over).

Additionally, we need to tell WebLab-Deusto what is the landing page when an experiment has been reserved,
and we do it by adding the following code:

.. code-block:: python

   from flask import url_for

   @weblab.initial_url
   def initial_url():
       # Being 'index' the name of the
       # view ("def index():") where the
       # user has to land
       return url_for('index')

This way, WebLab-Deusto will be managing students and the queue of students, and whenever it's time to
access the laboratory, it will contact the laboratory, create a session for the user, initialize it in the
user browser, and redirect the user to that (the one defined in ``initial_url``).

Polling
~~~~~~~

In WebLab-Deusto the administrator has assigned a time for the students. Let's imagine that it's
10 minutes per user. Typically, students leave earlier than the assigned time. For example, if they're
learning how to write code for a robot, they might see that the robot has already failed in 30 seconds and
might not need to continue suing it. However, if it works, they might need to stay 3 minutes or so. And if
the lesson is a very complex one, then they might need the 10 minutes.

For this reason, you might need to keep track of when is the user using the laboratory, and whenever the
student leaves, report WebLab-Deusto that the user left. With **weblablib**, this process is almost
automatic: you have to call a ``poll`` function in less than 15 seconds (or whatever you setup in
the ``WEBLAB_TIMEOUT`` configuration). There are different ways to achieve this. The simplest is adding
``weblab_poll_script`` in your template file as follows:

.. code-block:: html

        <!-- Here we will have the scripts -->
        <script>
            var STATUS_URL = "{{ url_for('status') }}";
            var LIGHT_URL = "{{ url_for('light', number='LIGHT') }}";
        </script>
        <script src="{{ url_for('static', filename='lab.js') }}"></script>

        {{ weblab_poll_script() }}

      </body>
    </html>

Internally, it will create a JavaScript script that will call a ``poll`` method every few seconds. The only
important thing is that this is called AFTER including ``jQuery`` since it relies on ``jQuery``.

This way, whenever the student leaves the laboratory (actively, or because there was a network issue on his
side, or for any other reason), the laboratory marks him as logged out, and therefore WebLab-Deusto assigns
the laboratory to someone else.

However, if you want to make this process faster, you can implement a method such as:

.. code-block:: python

   from weblablib import logout

   @app.route('/logout')
   @requires_active
   def logout_view():
       logout()
       return jsonify(result="ok")

This way, you can create in HTML a code that actively tells in a faster way to WebLab-Deusto that the user
is finished. You can also call this automatically when the web browser closes with some JavaScript code like:

.. code-block:: javascript

   $(document).ready(function()
   {
       $(window).bind("beforeunload", function() {
           $.get("{{ url_for('logout') }}");
       });
   });

Additionally, by default, **weblablib** installs a code that for any call in your Flask app, it will call
automatically ``poll``. You can disable this by configuring ``WEBLAB_AUTOPOLL`` to ``False`` in the
configuration, and then call ``poll`` manually:

.. code-block:: python

   from weblablib import poll

   @app.route('/poll')
   @requires_active
   def poll():
       poll()
       return jsonify(result='ok')

Checking user data
~~~~~~~~~~~~~~~~~~

In **weblablib** there is an special object called ``weblab_user``. It is never ``None``, and it can be either:

 * ``AnonymousUser``: when someone who has never been logged in (or not in a long time) accesses your app.
 * ``CurrentUser``: when a user has been assigned to use the laboratory, and only during that time (and if the
   user does not log out, or stopped polling)
 * ``ExpiredUser``: when a user has been previuosly assigned, but the assigned time elapsed, or the user clicked
   on log out or stopped polling.

So as to distinguish the type of user, you have two properties:

 * ``is_anonymous``: ``True`` if it's an ``AnonymousUser``
 * ``active``: ``True`` if it's an ``CurrentUser``.

Additionally, both the ``CurrentUser`` and the ``ExpiredUser`` have the following properties:

 * ``username``: the username in the original system. For example, ``tom``. Note that this is not unique: if your WebLab-Deusto is sharing the laboratory with a Moodle, there might be a ``tom`` in WebLab-Deusto and another ``tom`` in Moodle, and in both cases ``weblab_user.username`` will be ``tom``. So you can use it to talk to the username, but not for saving information for this user.
 * ``username_unique``: a full, unique, identifier of the user. For example, ``tom@school1@labsland``. Compared to the previous version, this is guaranteed to be unique.
 * ``back``: this is the URL where the user should go *after* finishing using the laboratory. For example, if the student was in a Moodle system, the ``back`` will be a link to the particular page in that Moodle system. ``requires_active`` by default redirects the user to that URL when the user has been logged in and not anymore.
 * ``time_left``: this is the time, in seconds, to finish the session. If the user was assigned 10 minutes, and 2 minutes have been passed, it will return something like ``478.3`` (seconds). Take into account that for this number to be accurate, both the laboatory server and the WebLab-Deusto server must have the same date and time, so use any time synchronization tool (e.g., a ntp server) to make sure this is the case.
 * ``data``: this is some data that you can store for passing between the different methods, tasks, etc. This information must be basic data types (such as dicts, lists, numbers, strings... anything you can encode in JSON), and not your own objects or similar.
 * ``locale``: this represents the language according to WebLab-Deusto (which will delegate in external systems too). For example, if you are using Moodle in Spanish, it will tell WebLab-Deusto that it's the case, which will establish here ``es``. You can use this with the proper library (such as Flask-Babel or Flask-BabelEx), as explained in :ref:`internationalization`.

For example:

.. code-block:: python

   from weblablib import requires_active, weblab_user

   @app.route('/status')
   @requires_active
   def status():
       # jsonify returns a JSON where {lights: result}
       # plus adds the 'application/json' headers, etc.
       return jsonify(lights=get_light_status(),
                      time_left=weblab_user.time_left,
                      error=False)


In this case, we have added to the response of status the time in seconds that is left to the
current user. You do not need to work on checking if ``weblab_user`` is anonymous or expired
since the method already has a ``@requires_active`` decorator (so if it's an anonymous user
the user will see "access forbidden", and if he is a user whose time already passed, will be
redirected to his ``weblab_user.back`` URL).

If the behavior of ``requires_active`` is too strict for your case, you also have a
``requires_login`` decorator. The difference is that while the former requires the user to
have access to the laboratory right now, the latter also accepts users which were using the
laboratory and now they can not use it anymore. For example, if the user was doing some
exercises, you may want to let the student to download the exercises for some time. In this
case, you may use ``requires_active`` to ``status`` or ``light`` (since whoever calls must
be assigend to the laboratory), but ``requires_login`` to ``index`` (and there, depending on
if the user is active or not, show one thing or another):

.. code-block:: python

   from weblablib import requires_login, weblab_user

   @app.route('/')
   @requires_login
   def index():
       if weblab_user.active:
           # Show something for current users
       else:
           # Show something for past users

Additionally, in the templates you have access to ``weblab`` and ``weblab_user``, so you can
simply run:

.. code-block:: python

   from weblablib import requires_login

   @app.route('/')
   @requires_login
   def index():
       return render_template('index.html')

And in the HTML code display:

.. code-block:: jinja

   {% if not weblab_user.active %}
       <a href="{{ weblab_user.back }}">Back</a>

       {# ... #}

       <div class="alert alert-warning">
           <h1>You don't have access to the laboratory anymore but
           you can download the following resources</h1>

           {# ... #}
       </div>
   {% endif %}

With this information, we can improve our example app by adding this in the JavaScript code:

.. code-block:: javascript

   var TIMER_INTERVAL = null;
   var TIME_LEFT = null;

   // Instead of the previously existing clean() function
   function clean() {
       clearInterval(STATUS_INTERVAL);
       clearInterval(TIME_LEFT);
       $("#panel").hide();
       $("#timer").text("session is over");
   }

   // Instead of the previuosly existing parseStatus
   function parseStatus(newStatus) {
       if (newStatus.error == false) {
           for (var i = 1; i < 11; i++) {
               if(newStatus.lights["light-" + i]) {
                   $("#light_" + i + "_off").hide();
                   $("#light_" + i + "_on").show();
               } else {
                   $("#light_" + i + "_on").hide();
                   $("#light_" + i + "_off").show();
               }
           }
           if (TIMER_INTERVAL == null) {
               TIME_LEFT = Math.round(newStatus.time_left);
               $("#timer").text("" + TIME_LEFT + " seconds");
               TIMER_INTERVAL = setInterval(function () {
                   TIME_LEFT = TIME_LEFT - 1;
                   if (TIME_LEFT >= 0) {
                       $("#timer").text("" + TIME_LEFT + " seconds");
                   } else {
                       clean();
                   }
               }, 1000);
           }
       } else {
           clean();
       }
   }

This way, in the beginning ``TIMER_INTERVAL`` is ``null``, but whenever we parse a status
from the server side (and therefore we receive a ``time_left`` value), we can start
a new interval that every second it changes the time left.


Adding basic settings
~~~~~~~~~~~~~~~~~~~~~

There are two mandatory variables that you have to configure in weblablib:

.. tabularcolumns:: |p{6.5cm}|p{8.5cm}|

================================= =========================================
``WEBLAB_USERNAME``               WebLab-Deusto has a pair of credentials
                                  representing a particular WebLab-Deusto
                                  instance in a particular laboratory.
                                  These pair are a *username* and a
                                  *password*, but they represent
                                  WebLab-Deusto, **not** the particular
                                  user coming from WebLab-Deusto. In
                                  WebLab-Deusto, this property is called
                                  ``http_experiment_username``.
``WEBLAB_PASSWORD``               Same as ``WEBLAB_USERNAME``, but this
                                  property representing the
                                  ``http_experiment_password``
                                  configuration value of WebLab-Deusto.
================================= =========================================

So, for example, we could use:

.. code-block:: python

   app = Flask(__name__)
   app.config.update({
       'SECRET_KEY': 'something-random',
       'WEBLAB_USERNAME': 'weblabdeusto',
       'WEBLAB_PASSWORD': 'password',
   })


Initializing and cleaning resources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Very often, you need to prepare the laboratory for the user before he uses it, and/or clean resources after the user has used them.

To do so, you can modify the ``hardware.py`` file to support:

.. code-block:: python

   from laboratory import weblab
   from weblablib import weblab_user

   @weblab.on_start
   def start(client_data, server_data):
       print("Initializing {}".format(weblab_user))

   @weblab.on_dispose
   def dispose():
       print("Disposing {}".format(weblab_user))
       clean_resources()

And, in ``laboratory.py``, move ``import hardware`` to the end of the file.

This way, for each user, this code will be run once at the beginning. If an error is produced in your ``start`` method,
the user will not be redirected and WebLab-Deusto will consider the laboratory as broken for a while before sending other
user.

The ``@weblab.on_dispose`` method is guaranteed to be run at some point in a matter of seconds or minutes after the user
is not using the laboratory anymore, *as long as the process is running*. However, there are situations (for example, you
configure Redis to not persist data in disk periodically and suddenly the computer where this code is running is restarted)
where it may not be run. For this reason, it is recommended that you run your ``clean_resources`` before running gunicorn or
whatever server you use later.

For example, you can add this code in ``laboratory.py``:


.. code-block:: python

   import hardware

   @app.cli.command('clean-resources')
   def clean_resources_command():
       hardware.clean_resources()

so later you can run:

.. code-block:: shell

   $ flask clean-resources

When the computer is restarted or before running the script that runs your laboratory or similar (see ``examples/advanced`` for more).

.. warning::


   Note that this code is run outside the web browser, so Flask objects like ``session`` will not work.

   Also note that, in general, it is a bad idea to store global information in a Flask script. If you are
   later running several processes (as it is normal), your laboratory will not work. If you need to store
   anything, rely on Redis see ``examples/advanced``) or a database or similar, not memory.

   So, for example, **do not do this**:

   .. code-block:: python

      # DO NOT DO THIS
      lights_on = False

      @weblab.on_start
      def start(client_data, server_data):
          global lights_on
          lights_on = True

   If you later run this in ``gunicorn`` or similar with multiple workers, the same variable will have
   different values in different servers.

Running weblablib
-----------------

So far, you have seen what code to put, but you have not even installed **weblablib**, so you could not run it. Also,
there are two ways to run this code: from WebLab-Deusto or, in development environments, from the console directly.
This section is focused on installing and running this code.

Installing weblablib
~~~~~~~~~~~~~~~~~~~~

Earlier, you installed Flask by creating an virtual environment (or not) following the instructions of `the Flask installation documentation <http://flask.pocoo.org/docs/latest/installation/>`_.
So as to install **weblablib**, you only have to activate the same virtual environment (if you were using any) and run:

.. code-block:: shell

   $ pip install weblablib

.. note::

   If you have installed WebLab-Deusto in this computer, please use a different virtual environment to
   avoid any potential conflict. For example, if you installed WebLab-Deusto in a virtualenv called
   weblab, create another virtualenv for weblablib:

   .. code-block:: shell

      $ mkvirtualenv wlib
      (wlib) % pip install weblablib

Installing redis
~~~~~~~~~~~~~~~~

**weblablib** relies on `Redis <https://redis.io/>`_, an Open Source, in-memory data structure store. In Linux distributions you can typically install it from the repositories:

.. code-block:: shell

   $ sudo apt-get install redis-server

In Microsoft Windows, you can use `Redis for Windows <https://github.com/MicrosoftArchive/redis/releases>`_, supported by Microsoft. You can either download the installer (beware that you download the *Latest release* and not a *Pre-release* which might come with bugs), or `use nuget <https://www.nuget.org/packages/redis-64/>`_.

In Mac OS X, you can install it manually or use Homebrew.

Development
~~~~~~~~~~~

Once **weblablib** is installed, running the script is exactly as before:

.. code-block:: shell

   $ export FLASK_DEBUG=1
   $ export FLASK_APP=laboratory.py
   $ flask run

However, if you open the web browser and go to the laboratory site:

 * http://localhost:5000/

You will only see ``Access forbidden``. So as to access the laboratory, you have to either:

 * Install WebLab-Deusto, follow `these instructions <http://weblabdeusto.readthedocs.io/en/latest/remote_lab_deployment.html>`_ (in particular, the *Unmanaged server* section, and configure with the following parameters:
   * ``http_experiment_url: http://localhost:5000/``
   * ``http_experiment_username: weblabdeusto`` (or whatever you used in ``WEBLAB_USERNAME``)
   * ``http_experiment_password: password``  (or whatever you used in ``WEBLAB_PASSWORD``)
 * **OR** use the command line interface for debugging.

The former is mandatory for the production mode, but the latter is the easiest version when working with. In this case, you simply run the following in a different terminal:

.. code-block:: shell

   $ export FLASK_DEBUG=1
   $ export FLASK_APP=laboratory.py
   $ flask fake-new-user --open-browser

This fakes a request from WebLab-Deusto, creating a new user. The argument ``--open-browser`` is optional, but providing it will open a session your default web browser (check `more information on how thisworks <https://docs.python.org/2/library/webbrowser.html>`_ if it uses a web browser you don't want).

As you see, you will end in http://localhost:5000/ but with a working valid WebLab-Deusto session. ``fake-new-user`` uses some default parameters, that you can change:

.. code-block:: shell

   $ flask fake-new-user --help
   Usage: flask fake-new-user [OPTIONS]

     Create a fake WebLab-Deusto user session.

     This command creates a new user session and stores the session in disk, so
     you can use other commands to check its status or delete it.

   Options:
     --name TEXT              First and last name
     --username TEXT          Username passed
     --username-unique TEXT   Unique username passed
     --assigned-time INTEGER  Time in seconds passed to the laboratory
     --back TEXT              URL to send the user back
     --locale TEXT            Language
     --open-browser           Open the fake use in a web browser
     --help                   Show this message and exit.

So, for example, you could also run:

.. code-block:: shell

   $ flask fake-new-user --name "Homer Simpson" --username hsimpson \
                         --username-unique "hsimpson@labsland" \
                         --assigned-time 600 \
                         --back https://en.wikipedia.org/wiki/Homer_Simpson \
                         --locale en
                         --open-browser

You can also fake stopping the current session by running:

.. code-block:: shell

   $ flask fake-dispose

It will delete the current session, so in the next ``weblab_user``, it will be already an ``ExpiredUser``.

You can also fake what's the current status as WebLab-Deusto does, contacting your laboratory every few seconds:

.. code-block:: shell

   $ flask fake-status

Which will return a number indicating when you should contact again, in seconds.

Production
~~~~~~~~~~

In a production environment, you should always use WebLab-Deusto, and you can rely on the `Flask deployment documentation <http://flask.pocoo.org/docs/0.12/deploying/>`_ to see how to deploy it.

In the `advanced example in the github repository <https://github.com/weblabdeusto/weblablib/tree/master/examples/advanced>`_ you have two scripts to run it using the popular `gunicorn <http://gunicorn.org/>`_ web server. These files are `wsgi_app.py` and `gunicorn_start.sh`, and you can install gunicorn by running:

.. code-block:: shell

   $ pip install gunicorn

