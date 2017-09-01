function clean() {
    $("#panel").hide();
    // No more time
    $("#timer").text("Time is over!");
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
            $("#timer").text(currentTime + " seconds");
        else
            $("#timer").text(currentTime + " second");
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
    $.post(LIGHT_URL.replace("LIGHT", number), {
        csrf: CSRF,
        state: state
    }).done(parseStatus);
}

function sendProgram(code) {
    $.post(MICROCONTROLLER_URL, {
        csrf: CSRF,
        code: code
    }).done(parseStatus);
}

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

