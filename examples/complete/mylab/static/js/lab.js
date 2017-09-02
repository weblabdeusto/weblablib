var socket = io.connect('http://' + document.domain + ':' + location.port);

function clean() {
    $("#panel").hide();
    // No more time
    $("#timer").text(TIME_IS_OVER);
    running = false;
    currentTime = 0;
    clearInterval(STATUS_INTERVAL);
    clearInterval(TIMER_INTERVAL);
}

function updateTime () {
    currentTime = currentTime - 1;
    if (currentTime > 0) {
        // Still time
        if (currentTime > 1)
            $("#timer").text(SECONDS_PLURAL.replace("NUM", currentTime));
        else
            $("#timer").text(SECONDS_SING);
    } else {
        clean();
    }
}

updateTime();

function turnOn(number) {
    turnLight(number, true);
    return false;
}

function turnOff(number) {
    turnLight(number, false);
    return false;
}

function turnLight(number, state) {
    socket.emit('lights', {number:number, state: state})
}

function sendProgram(code) {
    socket.emit('program', {code: code})
}

socket.on('program-state', function(data) {
    parseStatus(data);
})

function logout() {
    $.post(LOGOUT_URL, {
        csrf: CSRF
    }).done(function () {
        clean();
    });
}

var HIDE_MESSAGES_BOX = null;

function parseStatus(newStatus) {
    if (newStatus.error == false) {
        for (var i = 1; i < 11; i++) {
            if(newStatus["lights"]["light-" + i]) {
                $("#light_" + i + "_on").hide();
                $("#light_" + i + "_off").show();
            } else {
                $("#light_" + i + "_off").hide();
                $("#light_" + i + "_on").show();
            }
        }
        $("#microcontroller_status").text(newStatus["microcontroller"]);
    } else {
        $("#error_messages_box").show();
        $("#error_messages").text((new Date().toString()) + newStatus["message"]);

        if (HIDE_MESSAGES_BOX != null) {
            clearTimeout(HIDE_MESSAGES_BOX);
        }

        HIDE_MESSAGES_BOX = setTimeout(function() {
            $("#error_messages_box").hide();
        }, 10000);
    }
}

var STATUS_INTERVAL = setInterval(function () {

    $.get(STATUS_URL).done(parseStatus).fail(clean);

}, 1000);
var TIMER_INTERVAL = setInterval(updateTime, 1000);

$.get(STATUS_URL).done(parseStatus);

