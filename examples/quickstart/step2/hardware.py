import os
import json

from laboratory import weblab
from weblablib import weblab_user

@weblab.on_start
def start(client_data, server_data):
    print("Initializing {}".format(weblab_user))

@weblab.on_dispose
def dispose():
    print("Disposing {}".format(weblab_user))
    clean_resources()

def clean_resources():
    # Some code that turns off all the lights
    for n in range(1, 11):
        switch_light(n, False)

def switch_light(number, state):
    # Some code (e.g., using GPIO or something)
    # that turns a light on or off
    if not os.path.exists('lights.json'):
        lights = {
           # 'light-1': False
        }
        for n in range(1, 11):
            lights['light-{}'.format(n)] = False
    else:
        lights = json.load(open('lights.json'))
    lights['light-{}'.format(number)] = state
    json.dump(lights, open('lights.json', 'w'), indent=4)

def is_light_on(number):
    # Some code that checks if a light is on or off
    if not os.path.exists('lights.json'):
        return False
    return json.load(open('lights.json'))['light-{}'.format(number)]
