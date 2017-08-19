# advanced

This is a more advanced example of how to use **weblablib**.

## What does this lab do?


(TODO)

### File structure

(TO BE EXPLAINED)

### Session management

(TO BE EXPLAINED)

## Deployment

### Running it for development

So as to run it, in Linux / Mac OS X:

```shell

 $ export FLASK_DEBUG=1 # If developing
 $ export FLASK_APP=autoapp.py
 $ flask run

```

In Microsoft Windows:
```shell
 C:\...\> set FLASK_DEBUG=1 # If developing
 C:\...\> set FLASK_APP=autoapp.py
 C:\...\> flask run
```

And you can test it using [WebLab-Deusto](https://weblabdeusto.readthedocs.org) or using the weblablib command line interface in other terminal:

```shell

 $ export FLASK_APP=autoapp.py
 $ flask fake-new-user --open-browser
```

### Running it for production environments

(TODO)
