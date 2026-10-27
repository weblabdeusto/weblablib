"""Custom transport integration preserves the default WebLab behavior."""
import unittest
from unittest.mock import Mock, patch
from flask import Flask
from weblablib import WebLab
from weblablib.backends.redis_manager import RedisManager


created = []
def configured_factory(url, **kwargs):
    client = Mock()
    created.append((url, kwargs, client))
    return client


class RedisFactory(unittest.TestCase):
    def test_default_provider_retains_url_and_decoding(self):
        with patch('weblablib.backends.redis_manager.redis.StrictRedis.from_url') as factory:
            manager=RedisManager('redis://localhost:6379/6','lab',300,Mock())
        factory.assert_called_once_with('redis://localhost:6379/6',decode_responses=True)
        self.assertIs(manager.client,factory.return_value)

    def test_app_supplies_factory_before_any_backend_activity(self):
        app=Flask(__name__);created.clear()
        app.config.update(SECRET_KEY='test',WEBLAB_USERNAME='test',WEBLAB_PASSWORD='test',
            WEBLAB_REDIS_URL='redis://localhost:6379/6',WEBLAB_REDIS_CLIENT_FACTORY=configured_factory,
            WEBLAB_AUTOCLEAN_THREAD=False,WEBLAB_TASK_THREADS_PROCESS=0)
        lab=WebLab()
        try:
            lab.init_app(app)
            self.assertEqual(len(created),1)
            self.assertEqual(created[0][:2],('redis://localhost:6379/6',dict(decode_responses=True)))
            self.assertIs(lab._backend.client,created[0][2])
        finally:lab._cleanup()

    def test_factory_startup_failure_is_not_silently_replaced(self):
        factory=Mock(side_effect=RuntimeError('wrong generation'))
        with self.assertRaises(RuntimeError),patch('weblablib.backends.redis_manager.redis.StrictRedis.from_url') as fallback:
            RedisManager('redis://localhost:6379/6','lab',300,Mock(),client_factory=factory)
        fallback.assert_not_called()
