slackrelay
-------------

slackrelay is a Slack bot which relays every message from a Slack channel to one or more predetermined backends, according to a set of preconfigured rules persisted in a config file. A key goal is to enable channel mirroring across different Slack teams. Relaying messages from and to both public and private channels is supported.

Currently, two backends are supported (but others, e.g., **irc**, can be easily integrated):
* **echo**: simply echoes the original message in the same Slack channel (for testing purposes).
* **slack-iwh**: uses incoming web hooks to relay every message to another Slack channel, possibly from another team.

Usage
-----

```
slackrelay.py [-h] [-l {debug,info,warning,error}] [-b BOT] [-z]
                     [-f CONFIG_FILE] [-e EMOJI_TO_CONFIRM] [-s SLEEP_MS] [-v]
                     bot_user_token

Slack Relay Bot

positional arguments:
  bot_user_token

optional arguments:
  -h, --help            show this help message and exit
  -l {debug,info,warning,error}, --log {debug,info,warning,error}
                        Log level
  -b BOT, --bot BOT     Bot name
  -z, --slave           Set this instance as a slave with private
                        configuration
  -f CONFIG_FILE, --config-file CONFIG_FILE
                        Configuration file
  -e EMOJI_TO_CONFIRM, --emoji-to-confirm EMOJI_TO_CONFIRM
                        Emoji that relayed messages will be updated with
                        (reacted to) to show confirmation to humans, e.g.
                        thumbsup, white_check_mark, heavy_check_mark
  -s SLEEP_MS, --sleep-ms SLEEP_MS
                        Polling interval (ms)
  -v, --version         show program's version number and exit
```

Workflow
-------

1. `git clone git@github.com:cgiuffr/slackrelay.git`
2. Add a bot user to your Slack team (at https://slack.com/apps/A0F7YS25R-bots) and note down its `$bot_user_token`
3. Invite the bot user to the channel you want to relay messages from
4. Run `python slackrelay.py $bot_user_token` on a server to listen for messages from the channel through the bot
5. Add an incoming web hook to your channel (at https://slack.com/apps/A0F7XDUAZ-incoming-webhooks) and share the incoming web hook URL with the other team so they can relay messages to your channel
6. Type `@slackrelay help` to interact with the bot and add rules to relay messages
7. When mirroring a channel across teams, repeat the (symmetric) procedure for the other team

Usage example
-------------

```
@slackrelay help
@slackrelay rule-list
@slackrelay rule-add { "backend": "echo", "name": "echo-test" }
@slackrelay rule-list
Test message1
@slackrelay rule-add { "backend": "slack-iwh", "backend-url": "https://hooks.slack.com/services/dest/incoming-web-hook-url/other-team", "name": "dest-relay" }
@slackrelay rule-list
Test message2
@slackrelay rule-del echo-test
@slackrelay rule-list
Test message3
```

Contribute
----------

If you feel like contributing to slackrelay, here are some ideas:
* Implement a **slack-p2p** backend, where bots communicate directly over a custom protocol to relay messages. Compared to **slack-iwh**, this would eliminate the need for incoming web hooks and make it easier to implement advanced Slack features.
* Implement an **irc** or any other useful (e.g., **hipchat**) backend.
* Implement support for global bot commands processed by all the bots listening on the same shared channel.
* Implement a `@slackrelay bot-list` global bot command to list all the running bots.
* Implement a `@slackrelay user-list` global bot command to list all the users.
* Improve support for /me messages.
* Improve support for deleted and edited messages.
* Implement support for custom emojis or other advanced features.
