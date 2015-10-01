# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 1, 2015
# URL: https://executor.readthedocs.org

"""
OpenSSH server automation for testing.

The :mod:`executor.ssh.server` module defines the :class:`SSHServer` class
which can be used to start temporary OpenSSH servers that are isolated enough
from the host system to make them usable in the :mod:`executor` test suite (to
test remote command execution).
"""

# Standard library modules.
import logging
import os
import random
import shutil
import socket
import tempfile

# Modules included in our package.
from executor import execute, ExternalCommand, ExternalCommandFailed, which

# External dependencies.
from humanfriendly import format_timespan, Spinner, Timer

# Initialize a logger.
logger = logging.getLogger(__name__)

SSHD_PROGRAM_NAME = 'sshd'
"""The name of the SSH server executable (a string)."""


class SSHServer(ExternalCommand):

    """
    Subclass of :class:`.ExternalCommand` that manages a temporary SSH server.

    The OpenSSH server spawned by the :class:`SSHServer` class doesn't need
    `superuser privileges`_ and doesn't require any changes to ``/etc/passwd``
    or ``/etc/shadow``.
    """

    def __init__(self, **options):
        """
        Construct an :class:`SSHServer` object.

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
        """The pathname of the generated OpenSSH host key file (a string)."""
        # http://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers#Dynamic.2C_private_or_ephemeral_ports
        self.port = random.randint(49152, 65535)
        """The random port number on which the SSH server will listen (an integer)."""
        # Initialize the superclass.
        command = [self.sshd_path, '-D', '-f', self.config_file]
        super(SSHServer, self).__init__(*command, logger=logger, **options)

    @property
    def is_accepting_connections(self):
        """:data:`True` if the SSH server is running and accepting connections, :data:`False` otherwise."""
        if self.is_running:
            try:
                address = ('localhost', self.port)
                socket.create_connection(address, 2)
                return True
            except Exception:
                pass
        return False

    @property
    def sshd_path(self):
        """The absolute pathname of :data:`SSHD_PROGRAM_NAME` (a string or :data:`None`)."""
        matches = which(SSHD_PROGRAM_NAME)
        if matches:
            return matches[0]

    @property
    def client_options(self):
        """
        OpenSSH client options required to connect with the server.

        This is a dictionary of keyword arguments for :class:`.RemoteCommand`
        to make it connect with the OpenSSH server (assuming the remote command
        connects to an IP address in the 127.0.0.0/24 range).
        """
        return dict(identity_file=self.client_key_file,
                    ignore_known_hosts=True,
                    port=self.port)

    def start(self, **options):
        """
        Start the OpenSSH server.

        :param options: Any keyword arguments are passed to
                        :func:`wait_until_accepting_connections()`.
        :raises: :exc:`TimeoutError` when the SSH server isn't fast enough to
                 initialize.

        The :func:`start()` method automatically calls the following methods:

        1. :func:`generate_key_file()`
        2. :func:`generate_config()`
        3. :func:`executor.ExternalCommand.start()`.
        4. :func:`wait_until_accepting_connections()`
        """
        if not self.was_started:
            logger.debug("Preparing to start SSH server ..")
            for key_file in (self.host_key_file, self.client_key_file):
                self.generate_key_file(key_file)
            self.generate_config()
            super(SSHServer, self).start()
            try:
                self.wait_until_accepting_connections(**options)
            except TimeoutError:
                self.terminate()
                raise

    def wait_until_accepting_connections(self, timeout=30):
        """
        Wait until the SSH server starts accepting connections.

        :param timeout: If the SSH server doesn't start accepting connections
                        within the given timeout (number of seconds) the
                        attempt is aborted.
        :raises: :exc:`TimeoutError` when the SSH server isn't fast enough to
                 initialize.
        """
        timer = Timer()
        with Spinner(timer=timer) as spinner:
            while not self.is_accepting_connections:
                if timer.elapsed_time > timeout:
                    msg = "SSH server didn't start accepting connections within timeout of %s!"
                    raise TimeoutError(msg % format_timespan(timeout))
                spinner.step(label="Waiting for SSH server to accept connections")
                spinner.sleep()
        logger.debug("Waited %s after startup for SSH server to accept connections.", timer)

    def generate_key_file(self, filename):
        """
        Generate a temporary host or client key for the OpenSSH server.

        The :func:`start()` method automatically calls :func:`generate_key_file()`
        to generate :data:`host_key_file` and :attr:`client_key_file`. This
        method uses the ``ssh-keygen`` program to generate the keys.
        """
        if not os.path.isfile(filename):
            timer = Timer()
            logger.debug("Generating SSH key file (%s) ..", filename)
            execute('ssh-keygen', '-f', filename, '-N', '', '-t', 'rsa', silent=True, logger=self.logger)
            logger.debug("Generated key file %s in %s.", filename, timer)

    def generate_config(self):
        """
        Generate a configuration file for the OpenSSH server.

        The :func:`start()` method automatically calls
        :func:`generate_config()`.
        """
        if not os.path.isfile(self.config_file):
            logger.debug("Generating SSH server configuration (%s) ..", self.config_file)
            with open(self.config_file, 'w') as handle:
                handle.write("AllowUsers %s\n" % os.environ['USER'])
                handle.write("AuthorizedKeysFile %s.pub\n" % (self.client_key_file))
                handle.write("HostKey %s\n" % self.host_key_file)
                handle.write("LogLevel QUIET\n")
                handle.write("PasswordAuthentication no\n")
                handle.write("PidFile %s/sshd.pid\n" % self.temporary_directory)
                handle.write("Port %i\n" % self.port)
                handle.write("StrictModes no\n")
                handle.write("UsePAM no\n")
                handle.write("UsePrivilegeSeparation no\n")

    def cleanup(self):
        """Clean up :attr:`temporary_directory` after the test server finishes."""
        if self.temporary_directory:
            if os.path.isdir(self.temporary_directory):
                logger.debug("Cleaning up temporary directory %s ..", self.temporary_directory)
                shutil.rmtree(self.temporary_directory)
            self.temporary_directory = None
        super(SSHServer, self).cleanup()


class TimeoutError(ExternalCommandFailed):

    """
    Raised when the OpenSSH server doesn't initialize quickly enough.

    This exception is raised by :func:`~SSHServer.wait_until_accepting_connections()`
    when the SSH server doesn't start accepting connections within a reasonable time.
    """
