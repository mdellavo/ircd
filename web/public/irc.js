(function() {

    Backbone.history.start();

    var ConnectView = Backbone.View.extend({
        events: {
            "click .connect": "connect"
        },
        template: _.template($("#connect-view").text()),
        render: function() {
            this.$el.html(this.template({}));
            return this;
        },
        connect: function() {
            var nickname = this.$el.find(".nick").val();
            var host = this.$el.find(".host").val();
            this.trigger("connect", nickname, host);
        }
    });

    var Client = function(host, nick) {
        _.extend(this, Backbone.Events);

        this.host = host;
        this.nick = nick;
        this.socket = new WebSocket('ws://' + host);

        client = this;
        this.socket.onopen = function () {
            this.send("NICK " + client.nick);
            this.send("USER " + client.nick + " 0 * :" + client.nick);
            client.trigger("open");
        };

        this.socket.onerror = function (error) {
            this.close();
            client.trigger("error", error);
        };

        this.socket.onmessage = function (e) {
            client.trigger("message", e);
        };
    };

    Client.prototype.close = function() {
        this.socket.close();
        this.socket = null;
    };

    Client.prototype.isConnected = function() {
        return this.socket != null;
    };

    Client.prototype.send = function(msg) {
        console.log("send", msg);
        this.socket.send(msg);
    };

    var App = Backbone.View.extend({

        initialize: function() {
            this.client = null;
        },

        connect: function(nick, host) {
            if (this.socket)
                return;
            this.client = new Client(host, nick);
            this.listenTo(this.client, "open", this.onOpen);
            this.listenTo(this.client, "error", this.onError);
            this.listenTo(this.client, "message", this.onMessage);
        },

        showContent: function(view) {
            this.$el.find("#content").html(view.render().el);
        },

        showConnect: function() {
            var view = new ConnectView();

            view.on("connect", function(nick, host) {
                app.connect(nick, host)
            });

            this.showContent(view);
        },

        onOpen: function() {
            console.log("connected");
        },

        onError: function(error) {
            console.log('Error: ' + error);
        },

        onMessage: function(msg) {
            console.log('msg: ' + msg.data);
        }
    });

    var AppRouter = Backbone.Router.extend({
        routes: {

        }
    });

    var app = new App({
        el: $('#container')
    });

    app.showConnect();

})();