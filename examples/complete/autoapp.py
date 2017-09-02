import sys
# Monkeypatching is important for "flask run". gunicorn, etc. will use the wsgi_app.py
# But flask loop, for instance, does not need it.
# Otherwise (with loop, etc.), no gevent is used.
if 'run' in sys.argv:
    from gevent import monkey; monkey.patch_all()



import os
from mylab import create_app

if os.environ.get('FLASK_DEBUG') == '1':
    config_name = 'development'
else:
    config_name = os.environ.get('FLASK_CONFIG') or 'default'

app = create_app(config_name)
