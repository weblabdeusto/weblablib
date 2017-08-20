from __future__ import unicode_literals, print_function, division
from mylab import weblab, redis

from weblablib import weblab_user

"""
This module is just an example of how you could organize your code. Here you would
manage any code related to your hardware, for example.

In this case, we're going to have a very simple laboratory that we will create
in a Redis database (in memory). You will have:

 - 10 lights (0..9)
 - 1 microcontroller, which interacts with the lights

In Redis, we'll work with 11 variables for this:

 - hardware:lights:0 {on|off}
 - hardware:lights:1 {on|off}
 - hardware:lights:2 {on|off}
 - hardware:lights:3 {on|off}
 - hardware:lights:4 {on|off}
 - hardware:lights:5 {on|off}
 - hardware:lights:6 {on|off}
 - hardware:lights:7 {on|off}
 - hardware:lights:8 {on|off}
 - hardware:lights:9 {on|off}
 - hardware:microcontroller {empty|programming|programmed|failed}
"""

LIGHTS=10

@weblab.on_start
def start(client_data, server_data):
    print("************************************************************************")
    print("Preparing laboratory for user {}...".format(weblab_user.username))
    print()
    print(" - Typically, here you prepare resources.")
    print(" - Since this method is run *before* the user goes to the lab, you can't")
    print("   store information on Flask's 'session'. But you can store it on:")
    print("   weblab_user.data")
    weblab_user.data = { 'local_identifier': os.urandom(32) }
    print()
    print("************************************************************************")

    for light in range(LIGHTS):
        redis.set('hardware:lights:{}'.format(light), 'off')
    redis.set('hardware:microcontroller', 'empty')

@weblab.on_dispose
def dispose():
    print("************************************************************************")
    print("Cleaning up laboratory for user {}...".format(weblab_user.username))
    print()
    print(" - Typically, here you clean up resources (stop motors, delete programs,")
    print("   etc.)")
    print(" - In this example, we'll 'empty' the microcontroller (in a database)")
    print()
    print("************************************************************************")

    redis.set('hardware:microcontroller', 'empty')

def switch_light(number, state):
    if state:
        print("************************************************************************")
        print("  Imagine that light {} is turning on!                                  ".format(number))
        print("************************************************************************")
        redis.set('hardware:lights:{}'.format(number), 'off')
    else:
        print("************************************************************************")
        print("  Imagine that light {} is turning off!                                 ".format(number))
        print("************************************************************************")
        redis.set('hardware:lights:{}'.format(number), 'on')

def is_light_on(number):
    return redis.get('hardware:lights:{}'.format(number)) == 'on'

def get_microcontroller_state():
    return redis.get('hardware:microcontroller')

@weblab.task()
def program_device(code):

    if weblab_user.time_left < 10:
        print("************************************************************************")
        print("Error: typically, programming the device takes around 10 seconds. So if ")
        print("the user has less than 10 secons to use the laboratory, don't start ")
        print("this task. Otherwise, the user session will still wait until the task")
        print("finishes, delaying the time assigned by the administrator")
        print("************************************************************************")
        return {
            'success': False,
            'reason': "Too few time"
        }

    print("************************************************************************")
    print("You decided that you wanted to program the robot, and for some reason,  ")
    print("this takes time. In weblablib, you can create a 'task': something that  ")
    print("you can start, and it will be running in a different thread. In this ")
    print("case, this is lasting for 10 seconds from now ")
    print("************************************************************************")
    redis.set('hardware:microcontroller', 'programming')
    for x in range(10):
        time.sleep(1)
        print("Still programming...")


    if code == 'division-by-zero':
        print("************************************************************************")
        print("Oh no! It was a division-by-zero code! Expect an error!")
        print("************************************************************************")
        redis.set('hardware:microcontroller', 'failed')
        10 / 0 # Force an exception to be raised

    print("************************************************************************")
    print("Yay! the robot has been programmed! Now you can retrieve the result ")
    print("************************************************************************")
    redis.set('hardware:microcontroller', 'programmed')

    return {
        'success': True
    }

