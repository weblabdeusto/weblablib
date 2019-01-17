from __future__ import unicode_literals, print_function, division

import os
import time
from mylab import weblab, redis, socketio

from flask_babel import gettext

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
    weblab_user.data['local_identifier'] = weblab.create_token()
    print("   In this case: {}".format(weblab_user.data['local_identifier']))
    print()
    print("************************************************************************")

    for light in range(LIGHTS):
        redis.set('hardware:lights:{}'.format(light), 'off')
    redis.set('hardware:microcontroller:state', 'empty')
    redis.delete('hardware:microcontroller:programming')

@weblab.on_dispose
def dispose():
    print("************************************************************************")
    print("Cleaning up laboratory for user {}...".format(weblab_user.username))
    print()
    print(" - Typically, here you clean up resources (stop motors, delete programs,")
    print("   etc.)")
    print(" - In this example, we'll 'empty' the microcontroller (in a database)")
    print(" - Testing weblab_user.data: {}".format(weblab_user.data['local_identifier']))
    print()
    print("************************************************************************")

    clean_resources()

def clean_resources():
    """
    This code could be in dispose(). However, since we want to call this low-level
    code from outside any request and we can't (since we're using
    weblab_user.username in dispose())... we separate it. This way, this code can
    be called from outside using 'flask clean-resources'
    """
    redis.set('hardware:microcontroller:state', 'empty')
    redis.delete('hardware:microcontroller:programming')
    print("Microcontroller restarted")


def switch_light(number, state):
    if state:
        print("************************************************************************")
        print("  User {} (local identifier: {})".format(weblab_user.username, weblab_user.data['local_identifier']))
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

def hardware_status():
    "Return the status of the board"
    # A pipeline in Redis is a single connection, that run with
    # transaction=True (the default), it runs all the commands in a single
    # transaction. It's useful to get all the data in once and to peform
    # atomic operations 
    pipeline = redis.pipeline()

    for light in range(LIGHTS):
        pipeline.get('hardware:lights:{}'.format(light))
    
    pipeline.get('hardware:microcontroller:programming')
    pipeline.get('hardware:microcontroller:state')

    # Now it's run
    results = pipeline.execute()

    lights_data = {
        # 'light-1': True
    }

    for pos, light_state in enumerate(results[0:LIGHTS]):
        lights_data['light-{}'.format(pos+1)] = light_state == 'on'

    programming, state = results[LIGHTS:]
    if programming is not None:
        microcontroller = gettext('Programming: %(step)s', step=programming)
    elif state == 'empty':
        microcontroller = gettext("Empty memory")
    elif state == 'failed':
        microcontroller = gettext("Programming failed")
    elif state == 'programmed':
        microcontroller = gettext("Programming worked!")
    else:
        microcontroller = gettext("Invalid state: %(state)s", state=state)

    task_id = weblab_user.data.get('programming_task')
    if task_id:
        task = weblab.get_task(task_id)
        if task:
            print("Current programming task status: %s (error: %s; result: %s)" % (task.status, task.error, task.result))

    return dict(lights=lights_data, microcontroller=microcontroller, time_left=weblab_user.time_left)

@weblab.task(unique='global')
def program_device(code):

    if weblab_user.time_left < 10:
        print("************************************************************************")
        print("Error: typically, programming the device takes around 10 seconds. So if ")
        print("the user has less than 10 seconds (%.2f) to use the laboratory, don't start " % weblab_user.time_left)
        print("this task. Otherwise, the user session will still wait until the task")
        print("finishes, delaying the time assigned by the administrator")
        print("************************************************************************")
        return {
            'success': False,
            'reason': "Too few time: {}".format(weblab_user.time_left)
        }

    print("************************************************************************")
    print("You decided that you wanted to program the robot, and for some reason,  ")
    print("this takes time. In weblablib, you can create a 'task': something that  ")
    print("you can start, and it will be running in a different thread. In this ")
    print("case, this is lasting for 10 seconds from now ")
    print("************************************************************************")
    
    if redis.set('hardware:microcontroller:programming', 0) == 0:
        # Just in case two programs are sent at the very same time
        return {
            'success': False,
            'reason': "Already programming"
        }

    socketio.emit('board-status', hardware_status(), namespace='/mylab')

    for step in range(10):
        time.sleep(1)
        redis.set('hardware:microcontroller:programming', step)
        socketio.emit('board-status', hardware_status(), namespace='/mylab')
        print("Still programming...")


    if code == 'division-by-zero':
        print("************************************************************************")
        print("Oh no! It was a division-by-zero code! Expect an error!")
        print("************************************************************************")
        pipeline = redis.pipeline()
        pipeline.set('hardware:microcontroller:state', 'failed')
        pipeline.delete('hardware:microcontroller:programming')
        pipeline.execute()
        socketio.emit('board-status', hardware_status(), namespace='/mylab')
        10 / 0 # Force an exception to be raised

    print("************************************************************************")
    print("Yay! the robot has been programmed! Now you can retrieve the result ")
    print("************************************************************************")
    pipeline = redis.pipeline()
    pipeline.set('hardware:microcontroller:state', 'programmed')
    pipeline.delete('hardware:microcontroller:programming')
    pipeline.execute()

    socketio.emit('board-status', hardware_status(), namespace='/mylab')
    return {
        'success': True
    }

