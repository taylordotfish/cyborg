cyborg
======

Version 0.2.0

**cyborg** allows you to run IRC bots on your personal IRC account. You and
your bots can send messages using the same nickname. When you start cyborg, it
creates two proxy servers: one for your normal IRC client and one for bots.
Your client connects to the client proxy server, and then bots can connect to
the bot proxy server.

Usage
-----

``cyborg [options] <irc-host> <irc-port> <bot-port> <client-port>``

See ``cyborg --help`` for more information.

Once you start cyborg, open your favorite IRC client and connect to
``localhost``\* on port ``<client-port>``. After your client connects, you can
start an IRC bot that should connect to ``localhost``\* on port ``<bot-port>``.
If you're using the option ``--multiple-bots``, multiple bots can connect at
the same time.

Bots should send ``USER`` and ``NICK`` messages when they first connect, as
usual. If you're using the option ``--password``, bots must supply the
specified password when they first connect (using the ``PASS`` command).

Bots can disconnect from (and reconnect to) the proxy server without
interruption, but cyborg will shut down if it gets disconnected from the client
or server. You may want to run cyborg in a loop so it reconnects when
connection to the IRC server is lost.

\* If you're using the options ``--global-bot`` or ``--global-client``, the
respective proxy servers will run on all interfaces, so you can connect from a
computer other than the one cyborg is running on.

What's new
----------

Version 0.2.0:

* Added option ``--no-client``, which allows you to use cyborg as a proxy
  server for bots only.
* Added SSL/TLS support when connecting to IRC servers (option ``--ssl``)
* Fixed a bug where cyborg would not respond to server ``PING`` messages.

Dependencies
------------

* Python ≥ 3.3
* Python package: [docopt]

Run ``pip3 install -r requirements.txt`` to install the Python packages. You
can also use ``requirements.freeze.txt`` instead to install specific versions
of the dependencies that have been verified to work.

[docopt]: https://pypi.org/project/docopt
