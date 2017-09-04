#!/bin/bash

PORT=8080
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

# If using Python 2:

if [ "$(python --version 2>&1 |grep 2.7)" == "" ]; then
echo "Running Python 3"
gunicorn -k gevent -w 1 --bind 127.0.0.1:$PORT wsgi_app:application &
else
echo "Running Python 2"
gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --bind 127.0.0.1:$PORT wsgi_app:application &
fi


child=$!
wait "$child"

