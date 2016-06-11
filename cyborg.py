#!/usr/bin/env python3
# Copyright (C) 2016 taylor.fish <contact@taylor.fish>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# This program includes code from pyrcb (https://github.com/taylordotfish/pyrcb).
# Blocks of code marked "originally from pyrcb" are licensed under the GNU
# Lesser General Public License, either version 3 of the License, or (at your
# option) any later version. See "licenses/LGPL-3.0" for a copy of the license.
"""
Usage:
  cyborg [options] <irc-host> <irc-port> <bot-port> <client-port>
  cyborg --no-client [options] <irc-host> <irc-port> <bot-port>
  cyborg -h | --help | --version

Options:
  --password        Require bots to provide a password when connecting (using
                    the PASS command). Uses getpass() if stdin is a TTY.
  --global-bot      Run the bot proxy server on all interfaces,
                    instead of only localhost.
  --global-client   Run the client proxy server on all interfaces,
                    instead of only localhost.
  --multiple-bots   Allow multiple bots to connect to the bot proxy server.
  --forward-client  Forward bots PRIVMSGs and NOTICEs sent by the client.
  --ipv6            Use IPv6 for the bot and client proxy servers.
  --ssl             Use SSL/TLS when connecting to the IRC server.
  --no-client       Don't use an IRC client; manage only bots instead. You do
                    not need to provide <client-port> when using this option.
"""
from docopt import docopt
from collections import defaultdict, OrderedDict
from getpass import getpass
from threading import Event, Thread
import re
import selectors
import socket
import ssl
import sys

__version__ = "0.2.0"

# Update this link if you make any modifications.
SOURCE = "https://github.com/taylordotfish/cyborg"


class Bot:
    def __init__(self, socket):
        self.socket = socket
        self.identified = False
        self.user = False
        self.nick = False
        self.is_first = False

    def send_line(self, line):
        send_line(self.socket, line)

    def close(self):
        self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()


class Cyborg:
    def __init__(self, password=None, global_bot=False, global_client=False,
                 multiple_bots=False, forward_client=False, ipv6=False,
                 no_client=False):
        self.password = password
        self.global_bot = global_bot
        self.global_client = global_client
        self.multiple_bots = multiple_bots
        self.forward_client = forward_client
        self.family = socket.AF_INET6 if ipv6 else socket.AF_INET
        self.no_client = no_client

        self.nickname = None
        self.bots = OrderedDict()

        self.accept_bot = Event()
        self.bot_server_thread = None
        self.selector = selectors.DefaultSelector()
        self._buffers = defaultdict(str)
        self._shutdown = False
        self._first_bot = True

        self.bot_port = None
        self.client_port = None
        self.client_sock = None
        self.server_sock = None

    def start(self, bot_port, client_port, irc_host, irc_port, use_ssl=False):
        self.bot_port = bot_port
        self.client_port = client_port

        def accept_client():
            client_serv = socket.socket(family=self.family)
            client_serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            client_host = "" if self.global_client else "localhost"
            client_serv.bind((client_host, client_port))
            client_serv.listen()

            # Accept client socket.
            self.client_sock, addr = client_serv.accept()
            self.send_client(":* NOTICE * :Cyborg v{0}".format(__version__))
            self.send_client(":* NOTICE * :Source: {0}".format(SOURCE))
            close_socket(client_serv)

        if self.no_client:
            # Accept one bot.
            self.start_bot_server(bot_port, loop=False)
        else:
            accept_client()

        # Connect to IRC server.
        self.server_sock = socket.create_connection((irc_host, irc_port))
        if use_ssl:
            self.server_sock = wrap_socket(self.server_sock, irc_host)

        self.selector.register(self.server_sock, selectors.EVENT_READ)
        if not self.no_client:
            self.selector.register(self.client_sock, selectors.EVENT_READ)

        while self.nickname is None:
            if not self.handle_lines():
                return

        # Start bot proxy server.
        bot_thread = Thread(target=self.start_bot_server, args=[bot_port])
        self.bot_server_thread = bot_thread
        bot_thread.start()

        while True:
            if not self.handle_lines():
                return

    def start_bot_server(self, port, loop=True):
        if not self.multiple_bots and self.bots:
            self.accept_bot.wait()
            self.accept_bot.clear()

        serv = None
        while not self._shutdown:
            if serv is None:
                serv = socket.socket(family=self.family)
                serv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                host = "" if self.global_bot else "localhost"
                serv.bind((host, port))
                serv.listen()

            bot_sock, addr = serv.accept()
            bot = Bot(bot_sock)
            if self._shutdown:
                close_socket(serv)
                bot.close()
                return

            if self._first_bot:
                bot.is_first = True
                self._first_bot = False

            self.bots[bot_sock] = bot
            bot.send_line(":* NOTICE * :Cyborg v{0}".format(__version__))
            bot.send_line(":* NOTICE * :Source: {0}".format(SOURCE))
            self.selector.register(bot.socket, selectors.EVENT_READ)

            if not loop:
                close_socket(serv)
                return

            if not self.multiple_bots:
                close_socket(serv)
                serv = None
                self.accept_bot.wait()
                self.accept_bot.clear()

    def send_bots(self, line):
        for bot in self.bots.values():
            if (bot.user and bot.nick) or bot.is_first:
                bot.send_line(line)

    def send_client(self, line):
        send_line(self.client_sock, line)

    def send_server(self, line):
        send_line(self.server_sock, line)

    def shutdown(self):
        for sock in filter(None, [self.client_sock, self.server_sock]):
            close_socket(sock)

        self._shutdown = True
        # shutdown_bot() removes items from self.bots.
        for bot in list(self.bots.values()):
            self.shutdown_bot(bot)
        self.accept_bot.set()

        if (not self.bots or self.multiple_bots) and self.bot_server_thread:
            sock = socket.socket()
            try:
                # Connect to the bot server so accept() returns.
                sock.connect(("", self.bot_port))
                close_socket(sock)
            except ConnectionError:
                pass

        if self.bot_server_thread:
            print("Waiting for bot server to close...")
            self.bot_server_thread.join()

    def shutdown_bot(self, bot):
        self.selector.unregister(bot.socket)
        bot.close()
        self._buffers.pop(bot.socket, None)
        del self.bots[bot.socket]
        if not self.multiple_bots:
            self.accept_bot.set()

    def handle_bot(self, bot, line):
        cmd, args = irc_parse(line)[1:]
        cmd = cmd.upper()
        if self.password and not bot.identified:
            print("[bot]", line)
            if cmd == "PASS" and args:
                bot.identified = (args[0] == self.password)
                if not bot.identified:
                    print("Incorrect password from bot. Shutting down bot...")
                    bot.send_line(":* NOTICE * :Incorrect password.")
                    self.shutdown_bot(bot)
            else:
                print("No password from bot. Shutting down bot...")
                bot.send_line(":* NOTICE * :Must provide a password.")
                self.shutdown_bot(bot)
            return

        # Ignore the expected USER and NICK messages
        # when the bot first connects.
        if not (bot.user and bot.nick) and not bot.is_first:
            print("[bot]", line)
            if cmd == "USER":
                bot.user = True
            elif cmd == "NICK":
                bot.nick = True
            if bot.user and bot.nick:
                message = ":* " + irc_format("001", [self.nickname, "Welcome"])
                print("[-> bot]", message)
                bot.send_line(message)
            return

        if not self.no_client:
            if cmd in ["PRIVMSG", "NOTICE"] and self.nickname:
                prefix = ":" + self.nickname + " "
                print("[bot -> client]", prefix + line)
                self.send_client(prefix + line)
        print("[bot -> server]", line)
        self.send_server(line)

    def handle_client(self, line):
        cmd, args = irc_parse(line)[1:]
        cmd = cmd.upper()
        forward_to_bot = (
            self.forward_client and self.nickname and
            cmd in ["PRIVMSG", "NOTICE"])
        if forward_to_bot:
            prefix = ":" + self.nickname + " "
            print("[client -> bot]", prefix + line)
            self.send_bots(prefix + line)
        print("[client -> server]", line)
        self.send_server(line)

    def handle_server(self, line):
        nick, cmd, args = irc_parse(line)
        cmd = cmd.upper()
        if cmd == "PING":
            print("[server]", line)
            response = irc_format("PONG", args)
            print("[-> server]", response)
            self.send_server(response)
            return

        is_self = (self.nickname and nick.lower() == self.nickname.lower())
        if cmd == "001" or (cmd == "NICK" and is_self):
            self.nickname = args[0]

        if self.no_client:
            print("[server -> bot]", line)
        else:
            print("[server -> client, bot]", line)
            self.send_client(line)
        self.send_bots(line)

    def handle_disconnect(self, sock):
        if sock in self.bots.keys():
            print("Bot disconnected. Shutting down bot...")
            self.shutdown_bot(self.bots[sock])
            return True
        name = "Client" if sock == self.client_sock else "Server"
        print(name, "disconnected. Shutting down...")
        self.shutdown()
        return False

    def handle_lines(self):
        for sock, line in self.readlines():
            if line is None:
                if not self.handle_disconnect(sock):
                    return False
            elif sock in self.bots.keys():
                self.handle_bot(self.bots[sock], line)
            elif sock == self.client_sock:
                self.handle_client(line)
            elif sock == self.server_sock:
                self.handle_server(line)
        return True

    def get_current_lines(self):
        lines = []
        ready = self.selector.select()
        sockets = [key.fileobj for key, event in ready]
        for sock in sockets:
            data = sock.recv(1024)
            if not data:
                lines.append((sock, None))
                continue
            self._buffers[sock] += data.decode(errors="ignore")
        lines += self.get_buffered_lines()
        return lines

    def get_buffered_lines(self):
        lines = []
        for sock, buf in self._buffers.items():
            while "\r\n" in buf:
                line, buf = buf.split("\r\n", 1)
                lines.append((sock, line))
            self._buffers[sock] = buf
        return lines

    def readlines(self):
        lines = self.get_current_lines()
        while not lines:
            lines = self.get_current_lines()
        return lines


def send_line(sock, line):
    sock.sendall((line + "\r\n").encode())


def close_socket(sock):
    sock.shutdown(socket.SHUT_RDWR)
    sock.close()


# Parses an IRC message. (Modified; originally from pyrcb.)
# Returns (nickname, command, arguments).
def irc_parse(message):
    # Regex to parse IRC messages.
    match = re.match(r"""
        (?::  # Start of prefix
          (.*?)(?:  # Nickname
            (?:!(.*?))?  # User
            @(.*?)  # Host
          )?[ ]
        )?
        ([^ ]+)  # Command
        ((?:\ [^: ][^ ]*){0,14})  # Arguments
        (?:\ :?(.*))?  # Trailing argument
        """, message, re.VERBOSE)
    if not match:
        return ("", "", [])
    nick, user, host, cmd, args, trailing = match.groups("")
    args = args.split()
    if trailing:
        args.append(trailing)
    return (nick, cmd, args)


# Formats an IRC message. (Modified; originally from pyrcb.)
def irc_format(command, args=[]):
    command = str(command)
    args = list(map(str, args))
    if args:
        args[-1] = ":" + args[-1]
    return " ".join([command] + args)


# (Originally from pyrcb.)
# Wraps a plain socket into an SSL one. Attempts to load default CA
# certificates if none are provided. Verifies the server's certificate and
# hostname if specified.
def wrap_socket(sock, hostname=None, ca_certs=None, verify_ssl=True):
    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
    # Use load_default_certs() if available (Python >= 3.4); otherwise, use
    # set_default_verify_paths() (doesn't work on Windows).
    load_default_certs = getattr(
        context, "load_default_certs", context.set_default_verify_paths)

    if verify_ssl:
        context.verify_mode = ssl.CERT_REQUIRED
    if ca_certs:
        context.load_verify_locations(cafile=ca_certs)
    else:
        load_default_certs()

    sock = context.wrap_socket(sock)
    if verify_ssl:
        ssl.match_hostname(sock.getpeercert(), hostname)
    return sock


def main(argv):
    args = docopt(__doc__, argv=argv[1:], version=__version__)
    password = None
    if args["--password"]:
        print("Password: ", end="", flush=True, file=sys.stderr)
        password = getpass("") if sys.stdin.isatty() else input()
        if not sys.stdin.isatty():
            print("Received password.", file=sys.stderr)

    cyborg = Cyborg(
        password, args["--global-bot"], args["--global-client"],
        args["--multiple-bots"], args["--forward-client"], args["--ipv6"],
        args["--no-client"])

    client_port = None if args["--no-client"] else int(args["<client-port>"])
    try:
        cyborg.start(
            int(args["<bot-port>"]), client_port, args["<irc-host>"],
            int(args["<irc-port>"]), args["--ssl"])
    except KeyboardInterrupt:
        cyborg.shutdown()

if __name__ == "__main__":
    main(sys.argv)
