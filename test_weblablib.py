from flask import Flask
import weblablib
import unittest

class WebLabTest(unittest.TestCase):

    def create_weblab(self):
        self.weblab = weblablib.WebLab()
        self.app = Flask(__name__)
        self.app.config.update({
            'WEBLAB_CALLBACK_URL': '/mylab/callback',
            'WEBLAB_USERNAME': 'weblabdeusto',
            'WEBLAB_PASSWORD': 'password',
        })
        self.weblab.init_app(self.app)

    def setUp(self):
        self.create_weblab()

    def test_weblab(self):
        pass

