function turnOn(number) {
    turnLight(number, true);
    return false;
}

function turnOff(number) {
    turnLight(number, false);
    return false;
}

function turnLight(num, state) {
    var url = LIGHT_URL.replace("LIGHT", num) + "?state=" + state;
    $.get(url).done(parseStatus);
}

function clean() {
	// Not yet
}

function parseStatus(newStatus) {
    if (newStatus.error == false) {
        for (var i = 1; i < 11; i++) {
            if(newStatus["lights"]["light-" + i]) {
                $("#light_" + i + "_off").hide();
                $("#light_" + i + "_on").show();
            } else {
                $("#light_" + i + "_on").hide();
                $("#light_" + i + "_off").show();
            }
        }
    }
}

var STATUS_INTERVAL = setInterval(function () {

    $.get(STATUS_URL).done(parseStatus).fail(clean);

}, 1000);

$.get(STATUS_URL).done(parseStatus);

