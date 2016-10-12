# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 12, 2016
# URL: https://executor.readthedocs.org

r"""
Dependency injection for command execution contexts.

The :mod:`~executor.contexts` module defines the :class:`LocalContext` and
:class:`RemoteContext` classes. Both of these classes support the same API for
executing external commands (they are simple wrappers for
:class:`.ExternalCommand` and :class:`.RemoteCommand`). This allows you to
script interaction with external commands in Python and perform that
interaction on your local system or on a remote system (over SSH) using the
exact same Python code. `Dependency injection`_ on steroids anyone? :-)

Here's a simple example:

.. code-block:: python

   from executor.contexts import LocalContext, RemoteContext
   from humanfriendly import format_timespan

   def details_about_system(context):
       return "\n".join([
           "Information about %s:" % context,
           " - Host name: %s" % context.capture('hostname', '--fqdn'),
           " - Uptime: %s" % format_timespan(float(context.capture('cat', '/proc/uptime').split()[0])),
       ])

   print(details_about_system(LocalContext()))

   # Information about local system (peter-macbook):
   #  - Host name: peter-macbook
   #  - Uptime: 1 week, 3 days and 10 hours

   print(details_about_system(RemoteContext('file-server')))

   # Information about remote system (file-server):
   #  - Host name: file-server
   #  - Uptime: 18 weeks, 3 days and 4 hours

Whether this functionality looks exciting or horrible I'll leave up to your
judgment. I created it because I'm always building "tools that help me build
tools" and this functionality enables me to *very rapidly* prototype system
integration tools developed using Python:

**During development:**
 I *write* code on my workstation which I prefer because of the "rich editing
 environment" but I *run* the code against a remote system over SSH (a backup
 server, database server, hypervisor, mail server, etc.).

**In production:**
 I change one line of code to inject a :class:`LocalContext` object instead of
 a :class:`RemoteContext` object, I install the `executor` package and the code
 I wrote on the remote system and I'm done!

.. _Dependency injection: http://en.wikipedia.org/wiki/Dependency_injection
"""

# Standard library modules.
import contextlib
import logging
import multiprocessing
import os
import random
import socket

# External dependencies.
from property_manager import lazy_property

# Modules included in our package.
from executor import DEFAULT_SHELL, ExternalCommand, quote
from executor.ssh.client import RemoteCommand

# Initialize a logger.
logger = logging.getLogger(__name__)


def create_context(**options):
    """
    Create an execution context.

    :param options: Any keyword arguments are passed on to the context's initializer.
    :returns: A :class:`LocalContext` or :class:`RemoteContext` object.

    This function provides an easy to use shortcut for constructing context
    objects: If the keyword argument ``ssh_alias`` is given (and not
    :data:`None`) then a :class:`RemoteContext` object will be created,
    otherwise a :class:`LocalContext` object is created.
    """
    ssh_alias = options.pop('ssh_alias', None)
    if ssh_alias is not None:
        return RemoteContext(ssh_alias, **options)
    else:
        return LocalContext(**options)


class AbstractContext(object):

    """
    Abstract base class for shared logic of all context classes.

    The most useful methods of this class are :func:`execute()`,
    :func:`test()`, :func:`capture()`, :func:`cleanup()`,
    :func:`start_interactive_shell()`, :func:`read_file()` and
    :func:`write_file()`.
    """

    def __init__(self, **options):
        """
        Initialize an :class:`AbstractContext` object.

        :param options: Any keyword arguments are passed on to all
                        :class:`.ExternalCommand` objects constructed
                        using this context.

        .. note:: This constructor must be called by subclasses.
        """
        self.options = options
        self.undo_stack = []

    def prepare_command(self, command, options):
        """
        Construct an :class:`.ExternalCommand` object based on the current context.

        :param command: A tuple of strings (the positional arguments to the
                        constructor of :class:`.ExternalCommand`).
        :param options: A dictionary (the keyword arguments to the constructor
                        of :class:`.ExternalCommand`).
        :returns: Expected to return an :class:`.ExternalCommand` object *that
                  hasn't been started yet*.

        .. note:: This is an abstract method that must be implemented by subclasses.
        """
        raise NotImplementedError()

    def prepare_interactive_shell(self, options):
        """
        Construct an :class:`.ExternalCommand` object that starts an interactive shell.

        :param options: A dictionary (the keyword arguments to the constructor
                        of :class:`.ExternalCommand`).
        :returns: Expected to return an :class:`.ExternalCommand` object *that
                  hasn't been started yet*.

        .. note:: This is an abstract method that must be implemented by subclasses.
        """
        raise NotImplementedError()

    def merge_options(self, overrides):
        """
        Merge default options and overrides into a single dictionary.

        :param overrides: A dictionary with any keyword arguments given to
                          :func:`execute()` or :func:`start_interactive_shell()`.
        :returns: The dictionary with overrides, but any keyword arguments
                  given to the constructor of :class:`AbstractContext` that are
                  not set in the overrides are set to the value of the
                  constructor argument.
        """
        for name, value in self.options.items():
            overrides.setdefault(name, value)
        return overrides

    def prepare(self, *command, **options):
        """
        Prepare to execute an external command in the current context.

        :param command: All positional arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :returns: The :class:`.ExternalCommand` object.

        .. note:: After constructing an :class:`.ExternalCommand` object this
                  method doesn't call :func:`~executor.ExternalCommand.start()`
                  which means you control if and when the command is started.
                  This can be useful to prepare a large batch of commands and
                  execute them concurrently using a :class:`.CommandPool`.
        """
        return self.prepare_command(command, options)

    def execute(self, *command, **options):
        """
        Execute an external command in the current context.

        :param command: All positional arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :returns: The :class:`.ExternalCommand` object.

        .. note:: After constructing an :class:`.ExternalCommand` object this
                  method calls :func:`~executor.ExternalCommand.start()` on the
                  command before returning it to the caller, so by the time the
                  caller gets the command object a synchronous command will
                  have already ended. Asynchronous commands don't have this
                  limitation of course.
        """
        cmd = self.prepare_command(command, options)
        cmd.start()
        return cmd

    def test(self, *command, **options):
        """
        Execute an external command in the current context and get its status.

        :param command: All positional arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :returns: The value of :attr:`.ExternalCommand.succeeded`.

        This method automatically sets :attr:`~.ExternalCommand.check` to
        :data:`False` and :attr:`~.ExternalCommand.silent` to :data:`True`.
        """
        options.update(check=False, silent=True)
        cmd = self.prepare_command(command, options)
        cmd.start()
        return cmd.succeeded

    def capture(self, *command, **options):
        """
        Execute an external command in the current context and capture its output.

        :param command: All positional arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :returns: The value of :attr:`.ExternalCommand.output`.
        """
        options['capture'] = True
        cmd = self.prepare_command(command, options)
        cmd.start()
        return cmd.output

    def cleanup(self, *command, **options):
        """
        Register an external command to be called before the context ends.

        :param command: All positional arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :raises: :exc:`~exceptions.ValueError` when :func:`cleanup()` is called
                 outside a :keyword:`with` statement.

        This method registers *the intent* to run an external command in the
        current context before the context ends. To actually run the command
        you need to use (the subclass of) the :class:`AbstractContext` object
        as a context manager (using the :keyword:`with` statement).

        The last command that is registered is the first one to be executed.
        This gives the equivalent functionality of a deeply nested
        :keyword:`try` / :keyword:`finally` structure without actually needing
        to write such ugly code :-).

        .. warning:: If a cleanup command fails and raises an exception no
                     further cleanup commands are executed. If you don't care
                     if a specific cleanup command reports an error, set its
                     :attr:`~.ExternalCommand.check` property to
                     :data:`False`.
        """
        if not self.undo_stack:
            raise ValueError("Cleanup stack can only be used inside with statements!")
        self.undo_stack[-1].append((command, options))

    def start_interactive_shell(self, **options):
        """
        Start an interactive shell in the current context.

        :param options: All keyword arguments are passed on to the
                        constructor of the :class:`.ExternalCommand` class.
        :returns: The :class:`.ExternalCommand` object.

        .. note:: After constructing an :class:`.ExternalCommand` object this
                  method calls :func:`~executor.ExternalCommand.start()` on the
                  command before returning it to the caller, so by the time the
                  caller gets the command object a synchronous command will
                  have already ended. Asynchronous commands don't have this
                  limitation of course.
        """
        cmd = self.prepare_interactive_shell(options)
        cmd.start()
        return cmd

    @property
    def have_superuser_privileges(self):
        """:data:`True` if the context has superuser privileges, :data:`False` otherwise."""
        prototype = self.prepare('true')
        return prototype.have_superuser_privileges or prototype.sudo

    @property
    def cpu_count(self):
        """
        The number of CPUs in the system (an integer).

        .. note:: This is an abstract property that must be implemented by subclasses.
        """
        raise NotImplementedError()

    def exists(self, pathname):
        """
        Check whether the given pathname exists.

        :param pathname: The pathname to check (a string).
        :returns: :data:`True` if the pathname exists,
                  :data:`False` otherwise.

        This is a shortcut for the ``test -e ...`` command.
        """
        return self.test('test', '-e', pathname)

    def is_file(self, pathname):
        """
        Check whether the given pathname points to an existing file.

        :param pathname: The pathname to check (a string).
        :returns: :data:`True` if the pathname points to an existing file,
                  :data:`False` otherwise.

        This is a shortcut for the ``test -f ...`` command.
        """
        return self.test('test', '-f', pathname)

    def is_directory(self, pathname):
        """
        Check whether the given pathname points to an existing directory.

        :param pathname: The pathname to check (a string).
        :returns: :data:`True` if the pathname points to an existing directory,
                  :data:`False` otherwise.

        This is a shortcut for the ``test -d ...`` command.
        """
        return self.test('test', '-d', pathname)

    def is_readable(self, pathname):
        """
        Check whether the given pathname exists and is readable.

        :param pathname: The pathname to check (a string).
        :returns: :data:`True` if the pathname exists and is readable,
                  :data:`False` otherwise.

        This is a shortcut for the ``test -r ...`` command.
        """
        return self.test('test', '-r', pathname)

    def is_writable(self, pathname):
        """
        Check whether the given pathname exists and is writable.

        :param pathname: The pathname to check (a string).
        :returns: :data:`True` if the pathname exists and is writable,
                  :data:`False` otherwise.

        This is a shortcut for the ``test -w ...`` command.
        """
        return self.test('test', '-w', pathname)

    def read_file(self, filename):
        """
        Read the contents of a file.

        :param filename: The pathname of the file to read (a string).
        :returns: The contents of the file (a byte string).

        This method uses cat_ to read the contents of files so that options
        like :attr:`~.ExternalCommand.sudo` are respected (regardless of
        whether we're dealing with a :class:`LocalContext` or
        :class:`RemoteContext`).

        .. _cat: http://linux.die.net/man/1/cat
        """
        return self.execute('cat', filename, capture=True).stdout

    def write_file(self, filename, contents):
        """
        Change the contents of a file.

        :param filename: The pathname of the file to write (a string).
        :param contents: The contents to write to the file (a byte string).

        This method uses a combination of cat_ and `output redirection`_ to
        change the contents of files so that options like
        :attr:`~.ExternalCommand.sudo` are respected (regardless of whether
        we're dealing with a :class:`LocalContext` or :class:`RemoteContext`).
        Due to the use of cat_ this method will create files that don't exist
        yet, assuming the directory containing the file already exists and the
        context provides permission to write to the directory.

        .. _output redirection: https://en.wikipedia.org/wiki/Redirection_(computing)
        """
        return self.execute('cat > %s' % quote(filename), shell=True, input=contents)

    @contextlib.contextmanager
    def atomic_write(self, filename):
        """
        Create or update the contents of a file atomically.

        :param filename: The pathname of the file to create/update (a string).
        :returns: A context manager (see the :keyword:`with` keyword) that
                  returns a single string which is the pathname of the
                  temporary file where the contents should be written to
                  initially.

        If an exception is raised from the :keyword:`with` block and the
        temporary file exists, an attempt will be made to remove it but failure
        to do so will be silenced instead of propagated (to avoid obscuring the
        original exception).

        The temporary file is created in the same directory as the real file,
        but a dot is prefixed to the name (making it a hidden file) and the
        suffix '.tmp-' followed by a random integer number is used.
        """
        directory, entry = os.path.split(filename)
        temporary_file = os.path.join(directory, '.%s.tmp-%i' % (entry, random.randint(1, 100000)))
        try:
            yield temporary_file
        except Exception:
            self.execute('rm', '-f', temporary_file, check=False)
        else:
            self.execute('mv', temporary_file, filename)

    def list_entries(self, directory):
        """
        List the entries in a directory.

        :param directory: The pathname of the directory (a string).
        :returns: A list of strings with the names of the directory entries.

        This method uses ``find -mindepth 1 -maxdepth 1 -print0`` to list
        directory entries instead of going for the more obvious choice ``ls
        -A1`` because ``find`` enables more reliable parsing of command output
        (with regards to whitespace).
        """
        listing = self.capture('find', directory, '-mindepth', '1', '-maxdepth', '1', '-print0')
        return [os.path.basename(fn) for fn in listing.split('\0') if fn]

    def __enter__(self):
        """Initialize a new "undo stack" (refer to :func:`cleanup()`)."""
        self.undo_stack.append([])
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Execute any commands on the "undo stack" (refer to :func:`cleanup()`)."""
        old_scope = self.undo_stack.pop()
        while old_scope:
            command, options = old_scope.pop()
            self.execute(*command, **options)


class LocalContext(AbstractContext):

    """Context for executing commands on the local system."""

    @lazy_property
    def cpu_count(self):
        """
        The number of CPUs in the system (an integer).

        This property's value is computed using :func:`multiprocessing.cpu_count()`.
        """
        return multiprocessing.cpu_count()

    def prepare_command(self, command, options):
        """Refer to :attr:`AbstractContext.prepare_command`."""
        return ExternalCommand(*command, **self.merge_options(options))

    def prepare_interactive_shell(self, options):
        """Refer to :attr:`AbstractContext.prepare_interactive_shell`."""
        return ExternalCommand(DEFAULT_SHELL, **self.merge_options(options))

    def __str__(self):
        """Render a human friendly string representation of the context."""
        return "local system (%s)" % socket.gethostname()


class RemoteContext(AbstractContext):

    """Context for executing commands on a remote system over SSH."""

    def __init__(self, ssh_alias, **options):
        """
        Initialize a :class:`RemoteContext` object.

        :param ssh_alias: The SSH alias of the remote system (a string).
        :param options: Refer to :func:`AbstractContext.__init__()`.
        """
        super(RemoteContext, self).__init__(**options)
        self.ssh_alias = ssh_alias

    @lazy_property
    def cpu_count(self):
        """
        The number of CPUs in the system (an integer).

        This property's value is computed by executing the remote command
        nproc_. If that command fails :attr:`cpu_count` falls back to the
        command ``grep -ci '^processor\s*:' /proc/cpuinfo``.

        .. _nproc: http://linux.die.net/man/1/nproc
        """
        try:
            return int(self.capture('nproc', shell=False, silent=True))
        except Exception:
            return int(self.capture('grep', '-ci', '^processor\s*:', '/proc/cpuinfo'))

    def prepare_command(self, command, options):
        """Refer to :attr:`AbstractContext.prepare_command`."""
        return RemoteCommand(self.ssh_alias, *command, **self.merge_options(options))

    def prepare_interactive_shell(self, options):
        """Refer to :attr:`AbstractContext.prepare_interactive_shell`."""
        options = self.merge_options(options)
        options['tty'] = True
        return RemoteCommand(self.ssh_alias, DEFAULT_SHELL, **options)

    def __str__(self):
        """Render a human friendly string representation of the context."""
        return "remote system (%s)" % self.ssh_alias
