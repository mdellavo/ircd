(function() {

    var connection = new WebSocket('ws://dev:8080/socket');
    connection.onopen = function () {
        console.log("connected");
    };

    connection.onerror = function (error) {
        console.log('Error: ' + error);
    };

    connection.onmessage = function (e) {
        console.log('msg: ' + e.data);
    };
})();