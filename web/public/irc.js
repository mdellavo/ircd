(function() {

    var Channel = Backbone.Model.extend({
        defaults: function() {
            return {messages: []};
        },
        addMessage: function(msg) {
            this.get("messages").push(msg);
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
            console.log("incoming", msg);
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

        this.on("message/JOIN", function(msg) {
            writeChannel(msg.args[0], msg);
        });

        this.on("message/PRIVMSG", function(msg) {
            writeChannel(msg.args[0], msg);
        })
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

    var MessageView = Backbone.View.extend({
        initialize: function(options) {
            this.message = options.message;
        },
        template: _.template($("#message-view").text()),
        render: function() {
            var text = this.message.args.join(" ");
            this.$el.html(this.template({text: text}));
            return this;
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

            var view = this;
            _.each(this.channel.get("messages"), function(msg) {
                view.addMessage(msg);
            });

            return this;
        },
        addMessage: function(msg) {
            this.$el.append(new MessageView({message: msg}).render().el);
        },
        onMessage: function(msg) {
            console.log("new-message", msg);
            this.addMessage(msg);
        }
    });

    var ChannelTabView = Backbone.View.extend({
        events: {
            "click a": "onClicked"
        },
        initialize: function(options) {
            this.channel = options.channel;
        },
        template: _.template($("#channel-tab").text()),
        render: function() {
            this.$el.html(this.template(this.channel.attributes));
            return this;
        },
        onClicked: function(e) {
            e.preventDefault();
            this.trigger("channel-selected", this.channel);
        }
    });

    var ClientView = Backbone.View.extend({
        events: {
            "keyup #input": "onInputKey"
        },
        initialize: function(options) {
            this.client = options.client;
            this.channels = {};
            this.selected = null;
            this.listenTo(this.client, "open", this.onOpen);
            this.listenTo(this.client, "error", this.onError);
            this.listenTo(this.client, "close", this.onClose);
            this.listenTo(this.client, "new-channel", this.onNewChannel);
        },
        template: _.template($("#client-view").text()),
        render: function() {
            this.$el.html(this.template({}));
            return this;
        },
        showContent: function(view) {
            this.$el.find(".content").html(view.render().el);
        },
        addTab: function(channel) {
            var tabView = new ChannelTabView({channel: channel});
            this.listenTo(tabView, "channel-selected", this.selectChannel);
            this.$el.find(".nav").append(tabView.render().el);
        },
        addChannel: function(channel) {
            var view = new ChannelView({
                channel: channel
            });
            this.channels[channel.get("name")] = view;
            this.selectChannel(channel);
            return view;
        },
        selectChannel: function(channel) {
            var view = this.channels[channel.get("name")];
            this.showContent(view);
            this.selected = channel;
        },
        handleInput: function(val) {
            if (val.charAt(0) != '/' && this.selected) {
                val = "PRIVMSG " + this.selected.get("name") + " :" + val;

                // FIXME need to also add to channel
            } else {
                val = val.substr(1);
            }
            this.client.send(val);
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
            this.addTab(channel);
            this.addChannel(channel);
        },
        onInputKey: function(e) {
            if (e.keyCode == 13) {
                var el = this.$el.find("#input");
                var val = el.val();
                el.val("");
                this.handleInput(val);
            }
        }
    });

    function connect(nick, host) {
        console.log("connecting to " + host);

        var client = new Client(host, nick);

        var app = new ClientView({
            client: client,
            el: $('.main')
        }).render();
    }

    function showConnect() {
        var view = new ConnectView({
            el: $('.main')
        }).render();

        view.on("connect", function(nick, host) {
            connect(nick, host);
        });
    }

    showConnect()
})();