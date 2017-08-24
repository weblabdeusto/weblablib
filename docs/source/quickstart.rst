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
   the ``examples/quickstart/step1`` `in the GitHub repository <https://github.com/weblabdeusto/weblablib>`_,
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

To do so, you have to create a ``WebLab`` instance and initialize it with the Flask app. You can 
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

   from weblablib import requires_login, requires_active

   @app.route('/')
   @requires_login
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

In this case, you are defining that the view ``status`` and ``light`` can only be accessed by active WebLab
users (users who have been assigned and whose time in the laboratory is not over); while the ``index`` view.



# init_app
# POLLING
# LOGOUT

