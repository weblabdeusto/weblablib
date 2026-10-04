"""Run the complete test suite against an isolated temporary Redis server."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import redis

executable = shutil.which('redis-server')
if not executable:
    raise SystemExit('redis-server is required')
with tempfile.TemporaryDirectory(prefix='weblablib-test-') as directory:
    socket = str(Path(directory) / 'redis.sock')
    process = subprocess.Popen([executable, '--port', '0', '--unixsocket', socket, '--save', '', '--appendonly', 'no'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        url = 'unix://' + socket + '?db=0'
        client = redis.Redis.from_url(url)
        for attempt in range(100):
            try:
                client.ping()
                break
            except redis.ConnectionError:
                time.sleep(.05)
        else:
            raise RuntimeError('Private Redis did not start')
        env = dict(os.environ, WEBLABLIB_TEST_REDIS_URL=url)
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'], env=env, timeout=600)
    finally:
        process.terminate()
        process.wait(timeout=10)
raise SystemExit(result.returncode)
