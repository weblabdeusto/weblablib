#!/bin/bash

PORT=8080
WORKERS=10
_term() {
   kill -TERM "$child" 2>/dev/null
}

# When SIGTERM is sent, send it to weblab-admin
trap _term SIGTERM

# TODO: fix these two variables
FOLDER=.
VIRTUALENV_ACTIVATE=/home/user/.virtualenvs/mylab/bin/activate

cd $FOLDER
. $VIRTUALENV_ACTIVATE
date
export FLASK_DEBUG=0
export FLASK_APP=autoapp.py
flask clean-resources # Clean resources before running gunicorn
gunicorn --bind 127.0.0.1:$PORT -w $WORKERS wsgi_app:application &

child=$!
wait "$child"

