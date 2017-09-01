import os
import sys
import six

MYLAB_DIR = os.path.abspath(os.path.dirname(__file__))

sys.path.insert(0, MYLAB_DIR)
os.chdir(MYLAB_DIR)

if six.PY2:
    sys.stdout = open('stdout.txt', 'w', 0)
    sys.stderr = open('stderr.txt', 'w', 0)
else:
    sys.stdout = open('stdout.txt', 'w')
    sys.stderr = open('stderr.txt', 'w')

#
# XXX Change these values here XXX
#
# Don't use these values. Run a Python terminal and run:
# >>> import os
# >>> os.urandom(32)
# to get new value.
os.environ['SECRET_KEY']  = '\x18\xf2\xb0\x8d\x02\xef\xef\xf7@&H\xad\xb6\x91O\t,Y\xd4\\i\x15L)\x92\x8f\x14\x82\x86\xd5=&'
os.environ['WEBLAB_USERNAME'] = 'weblabdeusto'
os.environ['WEBLAB_PASSWORD'] = 'password'

from mylab import create_app
application = create_app('production')

import logging
file_handler = logging.FileHandler(filename='errors.log')
file_handler.setLevel(logging.INFO)
application.logger.addHandler(file_handler)

