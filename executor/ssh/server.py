# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: August 10, 2016
# URL: https://executor.readthedocs.io

"""
OpenSSH server automation for testing.

The :mod:`executor.ssh.server` module defines the :class:`SSHServer` class
which can be used to start temporary OpenSSH servers that are isolated enough
from the host system to make them usable in the :mod:`executor` test suite (to
test remote command execution).
"""

# Standard library modules.
import itertools
import logging
import os
import random
import shutil
import socket
import tempfile

# Modules included in our package.
from executor import ExternalCommand, execute, which

# External dependencies.
from humanfriendly import Spinner, Timer, format, format_timespan, pluralize
from property_manager import lazy_property, mutable_property

# Initialize a logger.
logger = logging.getLogger(__name__)

SSHD_PROGRAM_NAME = 'sshd'
"""The name of the SSH server executable (a string)."""


class EphemeralTCPServer(ExternalCommand):

    """
    Make it easy to launch ephemeral TCP servers.

    The :class:`EphemeralTCPServer` class makes it easy to allocate an
    `ephemeral port number`_ that is not (yet) in use.

    .. _ephemeral port number: \
        http://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers#Dynamic.2C_private_or_ephemeral_ports
    """

    @property
    def async(self):
        """Ephemeral TCP servers always set :attr:`.ExternalCommand.async` to :data:`True`."""
        return True

    @mutable_property
    def scheme(self):
        """A URL scheme that indicates the purpose of the ephemeral port (a string, defaults to 'tcp')."""
        return 'tcp'

    @mutable_property
    def hostname(self):
        """The host name or IP address to connect to (a string, defaults to ``localhost``)."""
        return 'localhost'

    @lazy_property
    def port_number(self):
        """A dynamically selected port number that was not in use at the moment it was selected (an integer)."""
        self.logger.debug("Looking for a free ephemeral port (for %s traffic) ..", self.scheme.upper())
        for i in itertools.count(1):
            port_number = random.randint(49152, 65535)
            if not self.is_connected(port_number):
                self.logger.debug("Took %s to select free ephemeral port (%s).",
                                  pluralize(i, "attempt"),
                                  self.render_location(port_number=port_number))
                return port_number

    @mutable_property
    def connect_timeout(self):
        """The timeout in seconds for connection attempts (a number, defaults to 2)."""
        return 2

    @mutable_property
    def wait_timeout(self):
        """The timeout in seconds for :func:`wait_until_connected()` (a number, defaults to 30)."""
        return 30

    def start(self, **options):
        """
        Start the TCP server and wait for it to start accepting connections.

        :param options: Any keyword arguments are passed to the
                        :func:`~executor.ExternalCommand.start()` method of the
                        superclass.
        :raises: Any exceptions raised by :func:`wait_until_connected()`
                 and/or the :func:`~executor.ExternalCommand.start()` method of
                 the superclass.

        If the TCP server doesn't start accepting connections within the
        configured timeout (see :attr:`wait_timeout`) the process will be
        terminated and the timeout exception will be propagated.
        """
        if not self.was_started:
            self.logger.debug("Preparing to start %s server ..", self.scheme.upper())
            super(EphemeralTCPServer, self).start(**options)
            try:
                self.wait_until_connected()
            except TimeoutError:
                self.terminate()
                raise

    def wait_until_connected(self, port_number=None):
        """
        Wait until the TCP server starts accepting connections.

        :param port_number: The port number to check (an integer, defaults to
                            the computed value of :attr:`port_number`).
        :raises: :exc:`TimeoutError` when the SSH server isn't fast enough to
                 initialize.
        """
        timer = Timer()
        if port_number is None:
            port_number = self.port_number
        location = self.render_location(port_number=port_number)
        with Spinner(timer=timer) as spinner:
            while not self.is_connected(port_number):
                if timer.elapsed_time > self.wait_timeout:
                    msg = "%s server didn't start accepting connections within timeout of %s!"
                    raise TimeoutError(msg % (self.scheme.upper(), format_timespan(self.wait_timeout)))
                spinner.step(label="Waiting for server to accept connections (%s)" % location)
                spinner.sleep()
        self.logger.debug("Waited %s for server to accept connections (%s).", timer, location)

    def is_connected(self, port_number=None):
        """
        Check whether the TCP server is accepting connections.

        :param port_number: The port number to check (an integer, defaults to
                            the computed value of :attr:`port_number`).
        :returns: :data:`True` if the TCP server is accepting connections,
                  :data:`False` otherwise.
        """
        if port_number is None:
            port_number = self.port_number
        location = self.render_location(port_number=port_number)
        self.logger.debug("Checking whether %s is accepting connections ..", location)
        try:
            socket.create_connection((self.hostname, port_number), self.connect_timeout)
            self.logger.debug("Yes %s is accepting connections.", location)
            return True
        except Exception:
            self.logger.debug("No %s isn't accepting connections.", location)
            return False

    def render_location(self, scheme=None, hostname=None, port_number=None):
        """Render a human friendly representation of an :class:`EphemeralTCPServer` object."""
        return format("{scheme}://{host}:{port}",
                      scheme=scheme or self.scheme,
                      host=hostname or self.hostname,
                      port=port_number or self.port_number)


class SSHServer(EphemeralTCPServer):

    """
    Subclass of :class:`.ExternalCommand` that manages a temporary SSH server.

    The OpenSSH server spawned by the :class:`SSHServer` class doesn't need
    `superuser privileges`_ and doesn't require any changes to ``/etc/passwd``
    or ``/etc/shadow``.
    """

    def __init__(self, **options):
        """
        Initialize an :class:`SSHServer` object.

        :param options: All keyword arguments are passed on to
                        :func:`executor.ExternalCommand.__init__()`.
        """
        self.temporary_directory = tempfile.mkdtemp(prefix='executor-', suffix='-ssh-server')
        """
        The pathname of the temporary directory used to store the files
        required to run the SSH server (a string).
        """
        self.client_key_file = os.path.join(self.temporary_directory, 'client-key')
        """The pathname of the generated OpenSSH client key file (a string)."""
        self.config_file = os.path.join(self.temporary_directory, 'config')
        """The pathname of the generated OpenSSH server configuration file (a string)."""
        self.host_key_file = os.path.join(self.temporary_directory, 'host-key')
        """The random port number on which the SSH server will listen (an integer)."""
        # Initialize the superclass.
        options.setdefault('scheme', 'ssh')
        options.setdefault('logger', logger)
        super(SSHServer, self).__init__(self.sshd_path, '-D', '-f', self.config_file, **options)

    @property
    def sshd_path(self):
        """The absolute pathname of :data:`SSHD_PROGRAM_NAME` (a string)."""
        executables = which(SSHD_PROGRAM_NAME)
        return executables[0] if executables else SSHD_PROGRAM_NAME

    @property
    def client_options(self):
        """
        The options for the OpenSSH client (required to connect with the server).

        This is a dictionary of keyword arguments for :class:`.RemoteCommand`
        to make it connect with the OpenSSH server (assuming the remote command
        connects to an IP address in the 127.0.0.0/24 range).
        """
        return dict(identity_file=self.client_key_file,
                    ignore_known_hosts=True,
                    port=self.port_number)

    def start(self, **options):
        """
        Start the SSH server and wait for it to start accepting connections.

        :param options: Any keyword arguments are passed to the
                        :func:`~EphemeralTCPServer.start()` method of the
                        superclass.
        :raises: Any exceptions raised by the
                 :func:`~EphemeralTCPServer.start()` method of the superclass.

        The :func:`start()` method automatically calls the
        :func:`generate_key_file()` and :func:`generate_config()` methods.
        """
        if not self.was_started:
            self.logger.debug("Preparing to start SSH server ..")
            for key_file in (self.host_key_file, self.client_key_file):
                self.generate_key_file(key_file)
            self.generate_config()
            super(SSHServer, self).start()

    def generate_key_file(self, filename):
        """
        Generate a temporary host or client key for the OpenSSH server.

        The :func:`start()` method automatically calls :func:`generate_key_file()`
        to generate :data:`host_key_file` and :attr:`client_key_file`. This
        method uses the ``ssh-keygen`` program to generate the keys.
        """
        if not os.path.isfile(filename):
            timer = Timer()
            self.logger.debug("Generating SSH key file (%s) ..", filename)
            execute('ssh-keygen', '-f', filename, '-N', '', '-t', 'rsa', silent=True, logger=self.logger)
            self.logger.debug("Generated key file %s in %s.", filename, timer)

    def generate_config(self):
        """
        Generate a configuration file for the OpenSSH server.

        The :func:`start()` method automatically calls
        :func:`generate_config()`.
        """
        if not os.path.isfile(self.config_file):
            self.logger.debug("Generating SSH server configuration (%s) ..", self.config_file)
            with open(self.config_file, 'w') as handle:
                handle.write("AllowUsers %s\n" % os.environ['USER'])
                handle.write("AuthorizedKeysFile %s.pub\n" % (self.client_key_file))
                handle.write("HostKey %s\n" % self.host_key_file)
                handle.write("LogLevel QUIET\n")
                handle.write("PasswordAuthentication no\n")
                handle.write("PidFile %s/sshd.pid\n" % self.temporary_directory)
                handle.write("Port %i\n" % self.port_number)
                handle.write("StrictModes no\n")
                handle.write("UsePAM no\n")
                handle.write("UsePrivilegeSeparation no\n")

    def cleanup(self):
        """Clean up :attr:`temporary_directory` after the test server finishes."""
        if self.temporary_directory:
            if os.path.isdir(self.temporary_directory):
                self.logger.debug("Cleaning up temporary directory %s ..", self.temporary_directory)
                shutil.rmtree(self.temporary_directory)
            self.temporary_directory = None
        super(SSHServer, self).cleanup()


class TimeoutError(Exception):

    """
    Raised when a TCP server doesn't start accepting connections quickly enough.

    This exception is raised by :func:`~EphemeralTCPServer.wait_until_connected()`
    when the TCP server doesn't start accepting connections within a reasonable time.
    """
