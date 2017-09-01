# weblablib

[![documentation](https://readthedocs.org/projects/weblablib/badge/?version=stable)](https://docs.labsland.com/weblablib/)
[![Version](https://img.shields.io/pypi/v/weblablib.svg)](https://pypi.python.org/pypi/weblablib/)
[![Python versions](https://img.shields.io/pypi/pyversions/weblablib.svg)](https://pypi.python.org/pypi/weblablib/)
[![build status](https://travis-ci.org/weblabdeusto/weblablib.svg?branch=master)](https://travis-ci.org/weblabdeusto/weblablib)
[![Coverage Status](https://coveralls.io/repos/github/weblabdeusto/weblablib/badge.svg?branch=master)](https://coveralls.io/github/weblabdeusto/weblablib?branch=master)

**weblablib** is a library for creating [WebLab-Deusto](https://github.com/weblabdeusto/weblabdeusto/) remote laboratories.

A remote laboratory is a software and hardware system that enables students to access real laboratories through the Internet.
For example, a student can be learning how to program a robot by writing code in a computer at home and sending it to a remote laboratory, where the student can see how the program behaves in a real environment.

Creating a remote laboratory may imply many layers, such as authentication, authorization, scheduling, etc., so Remote Laboratory Management Systems (RLMS) were created to make the common layers of remote laboatories.
WebLab-Deusto is an Open Source RLMS, and it has multiple ways ([see the docs](https://weblabdeusto.readthedocs.org)) to create a remote laboratory (in different programming languages, etc.).

In the case of Python, with the popular [Flask](http://flask.pocoo.org) microframework, **weblablib** is the wrapper used to create *unmanaged labs*.
*Unmanaged labs* is a term used in WebLab-Deusto to refer laboratories where the authors develop the full stack (server, client, deployment), as opposed to *managed labs*.

If you are familiar with Flask and with Web development, and want to be able to customize everything but not need to implement all the layers of authentication, administration, etc., this library would be very useful. Furthermore, this library allows you to develop remote laboratories for many environments (from regular computers with Linux to systems such as Raspberry Pi).

## Documentation

Read the docs: https://docs.labsland.com/weblablib/

## Installation

Simply use pip:
```
  pip install weblablib
```

## Simple usage

```python
from flask import Flask, url_for
from weblablib import WebLab, weblab_user, requires_active

app = Flask(__name__)
app.config.update({
    'SECRET_KEY': 'secret', # MUST CHANGE
    'WEBLAB_CALLBACK_URL': '/callback',
    'WEBLAB_USERNAME': 'weblabdeusto',
    'WEBLAB_PASSWORD': 'password',
})

weblab = WebLab(app)

@weblab.on_start
def on_start(client_data, server_data):
    # ...
    print("Starting user")

@weblab.on_dispose
def on_dispose():
    # ...
    print("Ending user")

@weblab.initial_url
def initial_url():
    return url_for('index')

@app.route('/')
@requires_active
def index():
    return "Hello, {}".format(weblab_user.username)

if __name__ == '__main__':
    app.run(debug=True)
```

See further examples in the ``examples`` directory.

