from flask import Flask, request, render_template, jsonify
import hardware

app = Flask(__name__)
app.config.update({
    'SECRET_KEY': 'something-random',
})

@app.route('/')
def index():
    return render_template("lab.html")

@app.route('/status')
def status():
    return jsonify(lights=get_light_status(), error=False)

@app.route('/lights/<number>/')
def light(number):
    state = request.args.get('state') == 'true'
    hardware.switch_light(number, state)
    return jsonify(lights=get_light_status(), error=False)

def get_light_status():
    lights = {}
    for light in range(1, 11):
        lights['light-{}'.format(light)] = hardware.is_light_on(light)
    return lights
