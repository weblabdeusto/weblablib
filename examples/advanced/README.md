# advanced

This is a more advanced example of how to use **weblablib**.

## What does this lab do?


(TODO)

### File structure

(TO BE EXPLAINED)

### Session management

(TO BE EXPLAINED)

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
 $ flask fake-new-user --open-browser
```

### Running it for production environments

(TODO)
