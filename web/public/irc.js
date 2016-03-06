(function() {

    var Channel = Backbone.Model.extend({
        initialize: function() {
            this.messages = [];
        },
        addMessage: function(msg) {
            this.messages.push(msg);
            this.trigger("new-message", msg);
        }
    });

    var Client = function(host, nick) {
        _.extend(this, Backbone.Events);

        this.host = host;
        this.nick = nick;
        this.socket = new WebSocket('ws://' + host);

        this.channels = {};

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

        this.socket.onmessage = function (message) {
            msg = JSON.parse(message.data);
            msg.timestamp = new Date();
            client.trigger("message/" + msg.command, msg);
        };

        function writeChannel(channel, msg) {
            var ch = client.channels[channel];

            if (!ch) {
                ch = new Channel({name: channel});
                client.channels[channel] = ch;
                client.trigger("new-channel", ch);
            }

            ch.addMessage(msg);
        }

        function notice(msg) {
            writeChannel(msg.prefix.name, msg);
        }

        this.on("message/001 message/002 message/003 message/004", function(message) {
            notice(message);
        });

        this.on("message/PING", function(msg) {
            client.send("PONG " + msg.args[0]);
        });

        this.on("message/NICK", function(msg) {
            this.nick = msg.args[0];
            this.trigger("nick");
        });
    };

    Client.prototype.close = function() {
        if (this.isConnected())
            this.socket.close();
        this.socket = null;
        this.trigger("close");
    };

    Client.prototype.isConnected = function() {
        return this.socket != null;
    };

    Client.prototype.send = function(msg) {
         if (this.isConnected())
             this.socket.send(msg);
    };

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

    var ChannelView = Backbone.View.extend({
        initialize: function(options) {
            this.channel = options.channel;
            this.listenTo(this.channel, "new-message", this.onMessage);
        },
        template: _.template($("#channel-view").text()),
        render: function() {
            this.$el.html(this.template({}));
            return this;
        },
        onMessage: function(msg) {
            console.log("new-message", msg);
            var text = msg.args.join(" ");
            this.$el.append(text);
        }
    });

    var ClientView = Backbone.View.extend({
        initialize: function(options) {
            this.client = options.client;
            this.channels = {};
            this.listenTo(this.client, "open", this.onOpen);
            this.listenTo(this.client, "error", this.onError);
            this.listenTo(this.client, "close", this.onClose);
            this.listenTo(this.client, "new-channel", this.onNewChannel);

        },
        template: _.template($("#client-view").text()),
        channel_tab_template: _.template($("#channel-tab").text()),
        render: function() {
            this.$el.html(this.template({}));
            return this;
        },
        showContent: function(view) {
            this.$el.find("#content").html(view.render().el);
        },
        onOpen: function() {
            console.log("connected");
        },
        onClose: function() {
            console.log("closed")
        },
        onError: function(error) {
            console.log('Error:', error);
        },
        onNewChannel: function(channel) {
            console.log("new channel", channel);

            var view = new ChannelView({
                channel: channel
            });
            this.showContent(view);

            this.channels[channel.get("name")] = view;

            this.$el.find("#nav").append(this.channel_tab_template(channel.attributes));
        }
    });

    function connect(nick, host) {
        console.log("connecting to " + host);

        var client = new Client(host, nick);

        var app = new ClientView({
            client: client,
            el: $('#container')
        }).render();
    }

    function showConnect() {
        var view = new ConnectView({
            el: $('#container')
        }).render();

        view.on("connect", function(nick, host) {
            connect(nick, host);
        });
    }

    showConnect()
})();