# advanced

This is a more advanced example of how to use **weblablib**.

## What does this lab do?

This lab is just a simple laboratory showing ten light bulbs (on which you can click to turn them on and off) and a fake "microcontroller" that you can either send a file that works or one which doesn't.

## File structure

The structure is as follows:

### autoapp.py

It's a helper file, to assist the [Flask CLI](http://flask.pocoo.org/docs/0.12/cli). It just calls the `create_app` method.

### config.py

The configuration file. Many of the values are taken from the environment variables. See the `wsgi_app.py` file for an example on how to configure it.

### requirements.txt

The Python requirements file, with all the dependencies.

### mylab folder

#### mylab/hardware.py

This file represents the access to the hardware. Typically here you would use a library or do something depending on your laboratory (e.g., using serial ports, LXI, Raspberry Pi API...).

#### mylab/views.py

Flask views for the different web methods in the laboratory (programming the microcontroller, turning on the lights, current status...). The JavaScript code will call these methods.

#### mylab/__init__.py

Creation of the Flask app and registering the views, etc.

#### mylab/static/js/lab.js

JavaScript code.

#### mylab/templates/index.html

HTML template (using `weblab_poll_script`, `weblab_user.time_left`, etc.).

## Session management

WebLab-Deusto will be in charge of the session.

Flask comes with an object called `session` that is available in all the requests, but not in requests done by WebLab-Deusto or in threads (tasks, etc.).

For that reason there is something called `weblab_user.data`, which by default is a dictionary, and you can add data to it that will be available through different views and threads. You can see in `hardware.py` how it can be used.

## Tasks

In `hardware.py` there is an example of a task, that takes long to be executed (10 seconds). It is run from `views.py` with `program_device.delay(code)`, and you can see how the task can be retrieved, etc.

## Commands

In addition to the commands that come from *weblablib*, in `mylab/__init__.py` you can see how you can add custom commands to do things like cleaning resources from outside.

## Deployment

### Install the dependencies

You will need to create a virtual environment, and then install all the requirements:

```shell

 $ pip install -r requirements.txt
```

### Running it for development

So as to run it, in Linux / Mac OS X:

```shell

 $ export FLASK_DEBUG=1 # If developing
 $ export FLASK_APP=autoapp.py
 $ flask run

```

Alternatively, you can do also:
```shell
 $ . localrc
 $ flask run
```

If you have installed Flask-SocketIO (e.g., if you run the ``complete`` example and then you come back to this one), then you might encounter the following error:
```shell

 $ flask run
 File "/usr/lib/python3.5/signal.py", line 47, in signal
    handler = _signal.signal(_enum_to_int(signalnum), _enum_to_int(handler))
    ValueError: signal only works in main thread
 $
```

In that case, it is safer to simply run ``python run_debug.py``.

Since ``localrc`` already contains those variables.

In Microsoft Windows:
```shell
 C:\...\> set FLASK_DEBUG=1 # If developing
 C:\...\> set FLASK_APP=autoapp.py
 C:\...\> flask run
```

And you can test it using [WebLab-Deusto](https://weblabdeusto.readthedocs.org) or using the weblablib command line interface in other terminal:

```shell

 $ export FLASK_APP=autoapp.py # (or . localrc)
 $ flask weblab fake new --open-browser
```

### Running it for production environments

In a production environment, you must use a proper server such as `gunicorn`. To do this:

```shell

pip install gunicorn

```

Then, you have to have a file such as `wsgi_app.py`. Important: change all the values there (e.g., `WEBLAB_PASSWORD`, `SECRET_KEY`, etc.).

Once you change it, you can run a script like `gunicorn_start.sh`. Furthermore, this script is prepared to be launched from [supervisor](http://supervisord.org/).

Finally, you have further information on WebLab-Deusto for unmanaged servers [in the official documentation](http://weblabdeusto.readthedocs.io/en/latest/#remote-laboratory-development-and-management).

