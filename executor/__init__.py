# vim: fileencoding=utf-8

# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 12, 2016
# URL: https://executor.readthedocs.org

"""
Core functionality of the `executor` package.

If you're looking for an easy way to run external commands from Python take a
look at the :func:`execute()` function. When you need more flexibility consider
using the underlying :class:`ExternalCommand` class directly instead.

:func:`execute()` versus :class:`ExternalCommand`
-------------------------------------------------

In :mod:`executor` 1.x the :func:`execute()` function was the only interface
for external command execution. This had several drawbacks:

- The documentation for the :func:`execute()` function was getting way too
  complex given all of the supported options and combinations.

- There was no way to execute asynchronous external commands (running in the
  background) without sidestepping the complete :mod:`executor` module and
  going straight for :class:`subprocess.Popen` (with all of the verbosity
  that you get for free with :mod:`subprocess` :-).

- There was no way to prepare an external command without starting it
  immediately, making it impossible to prepare a batch of external commands
  before starting them (whether synchronously or asynchronously).

To solve these problems :mod:`executor` 2.x introduced the
:class:`ExternalCommand` class. This explains why :func:`execute()` is now a
trivial wrapper around :class:`ExternalCommand`: It's main purpose is to be an
easy to use shortcut that preserves compatibility with the old interface.

Classes and functions
---------------------
"""

# Standard library modules.
import errno
import logging
import os
import pipes
import signal
import subprocess
import sys
import tempfile

# External dependencies.
from humanfriendly import compact, format
from humanfriendly.terminal import connected_to_terminal
from property_manager import PropertyManager, mutable_property, required_property, writable_property

# Modules included in our package.
from executor.process import ControllableProcess

# Define an alias for Unicode strings that's unambiguous
# whether we are running under Python 2 or Python 3.
try:
    # This will raise a NameError exception in Python 3.
    unicode
except NameError:
    # In Python 3 all strings are Unicode strings.
    unicode = str

# Semi-standard module versioning.
__version__ = '14.1'

# Initialize a logger.
logger = logging.getLogger(__name__)

DEFAULT_ENCODING = 'UTF-8'
"""The default encoding of the standard input, output and error streams (a string)."""

DEFAULT_WORKING_DIRECTORY = os.curdir
"""
The default working directory for external commands (a string). Defaults to the
working directory of the current process using :data:`os.curdir`.
"""

DEFAULT_SHELL = 'bash'
"""
The default shell used to evaluate shell expressions (a string).

This variable isn't based on the ``$SHELL`` environment variable because:

1. Shells like ``sh``, ``dash``, ``bash`` and ``zsh`` all have their own
   subtly incompatible semantics.
2. People regularly use shells like ``fish`` as their default login shell :-).

At an interactive prompt this is no problem (advanced users have obviously
learned to context switch) but when you're writing source code the last thing
you want to worry about is which shell is going to evaluate your commands! The
:mod:`executor` package expects this shell to support the following features:

- The ``-c`` option to evaluate a shell command provided as a command line
  argument.

- The ``-`` argument to instruct the shell to read shell commands from its
  standard input stream and evaluate those.

Apart from these two things nothing else is expected from the default shell so
you're free to customize it if you really want to write your shell commands in
``fish`` or ``zsh`` syntax :-).
"""

COMMAND_NOT_FOUND_CODES = (errno.ENOENT,)
"""Numeric error codes returned when a command isn't available on the system (a tuple of integers)."""

COMMAND_NOT_FOUND_STATUS = 127
"""The exit status used by shells when a command is not found (an integer)."""

IS_WINDOWS = sys.platform.startswith('win')


def execute(*command, **options):
    """
    Execute an external command and make sure it succeeded.

    :param command: All positional arguments are passed on to the constructor
                    of :class:`ExternalCommand`.
    :param options: All keyword arguments are passed on to the constructor of
                    :class:`ExternalCommand`.
    :returns: Refer to :func:`execute_prepared()`.
    :raises: :exc:`ExternalCommandFailed` when the command exits with a
             nonzero exit code (and :attr:`~ExternalCommand.check` is
             :data:`True`).

    If :attr:`~ExternalCommand.async` is :data:`True` then :func:`execute()`
    will automatically start the external command for you using
    :func:`~ExternalCommand.start()` (but it won't wait for it to end). If you
    want to create an :class:`ExternalCommand` object instance without
    immediately starting the external command then you can use
    :class:`ExternalCommand` directly.

    **Some examples**

    By default the status code of the external command is returned as a boolean:

    >>> from executor import execute
    >>> execute('true')
    True

    However when an external command exits with a nonzero status code an
    exception is raised, this is intended to "make it easy to do the right
    thing" (never forget to check the status code of an external command
    without having to write a lot of repetitive code):

    >>> execute('false')
    Traceback (most recent call last):
      File "executor/__init__.py", line 124, in execute
        cmd.start()
      File "executor/__init__.py", line 516, in start
        self.wait()
      File "executor/__init__.py", line 541, in wait
        self.check_errors()
      File "executor/__init__.py", line 568, in check_errors
        raise ExternalCommandFailed(self)
    executor.ExternalCommandFailed: External command failed with exit code 1! (command: false)

    What's also useful to know is that exceptions raised by :func:`execute()`
    expose :attr:`~ExternalCommandFailed.command` and
    :attr:`~ExternalCommandFailed.returncode` attributes. If you know a command
    is likely to exit with a nonzero status code and you want :func:`execute()`
    to simply return a boolean you can do this instead:

    >>> execute('false', check=False)
    False
    """
    return execute_prepared(ExternalCommand(*command, **options))


def execute_prepared(command):
    """
    The logic behind :func:`execute()` and :func:`.remote()`.

    :param command: An :class:`ExternalCommand` object (or an object created
                    from a subclass with a compatible interface like for
                    example :class:`.RemoteCommand`).
    :returns: The return value of this function depends on several options:

              - If :attr:`~ExternalCommand.async` is :data:`True` the
                constructed :class:`ExternalCommand` object is returned.

              - If :attr:`~ExternalCommand.callback` is set the value of
                :attr:`~ExternalCommand.result` is returned.

              - If :attr:`~ExternalCommand.capture` is :data:`True` the value
                of :attr:`ExternalCommand.output` is returned.

              - By default the value of :attr:`~ExternalCommand.succeeded` is
                returned.
    :raises: See :func:`execute()` and :func:`.remote()`.
    """
    if command.async:
        command.start()
        return command
    else:
        command.start()
        command.wait()
        if command.callback:
            return command.result
        elif command.capture:
            return command.output
        else:
            return command.succeeded


class ExternalCommand(ControllableProcess):

    """
    Programmer friendly :class:`subprocess.Popen` wrapper.

    The :class:`ExternalCommand` class wraps :class:`subprocess.Popen` to make
    it easier to do the right thing (the simplicity of :func:`os.system()` with
    the robustness of :class:`subprocess.Popen`) and to provide additional
    features (e.g. asynchronous command execution that preserves the ability to
    provide input and capture output).

    :class:`ExternalCommand` inherits from :class:`~executor.process.ControllableProcess`
    which means that all of the process manipulation supported by
    :class:`~executor.process.ControllableProcess` is also supported by
    :class:`ExternalCommand` objects.

    Because the :class:`ExternalCommand` class has a lot of properties and
    methods here is an attempt to summarize them (this overview will no doubt
    become out of date):

    **Writable properties**
     The :attr:`async`, :attr:`callback`, :attr:`capture`,
     :attr:`capture_stderr`, :attr:`check`, :attr:`directory`,
     :attr:`encoding`, :attr:`environment`, :attr:`fakeroot`, :attr:`input`,
     :attr:`~executor.process.ControllableProcess.logger`, :attr:`merge_streams`,
     :attr:`shell`, :attr:`silent`, :attr:`stdout_file`, :attr:`stderr_file`,
     :attr:`uid`, :attr:`user`, :attr:`sudo` and :attr:`virtual_environment`
     properties allow you to configure how the external command will be run
     (before it is started).

    **Computed properties**
     The :attr:`command`, :attr:`command_line`, :attr:`decoded_stderr`,
     :attr:`decoded_stdout`, :attr:`encoded_input`, :attr:`error_message`,
     :attr:`error_type`, :attr:`failed`, :attr:`have_superuser_privileges`,
     :attr:`is_finished`, :attr:`~executor.process.ControllableProcess.is_running`,
     :attr:`is_terminated`, :attr:`output`,  :attr:`~executor.process.ControllableProcess.pid`,
     :attr:`result`, :attr:`returncode`, :attr:`stderr`, :attr:`stdout`,
     :attr:`succeeded` and :attr:`was_started` properties allow you to inspect
     if and how the external command was started, what its current status is
     and what its output is.

    **Public methods**
     The public methods :func:`start()`, :func:`wait()`,
     :func:`~executor.process.ControllableProcess.terminate()` and
     and :func:`~executor.process.ControllableProcess.kill()`
     enable you to start external commands, wait for them to
     finish and terminate them if they take too long.

    **Internal methods**
     The internal methods :func:`check_errors()`, :func:`load_output()` and
     :func:`cleanup()` are used by methods like :func:`start()`,
     :func:`wait()`, :func:`~executor.process.ControllableProcess.terminate()`
     and :func:`~executor.process.ControllableProcess.kill()` so unless you're
     reimplementing one of those methods you probably don't need these internal
     methods.

    **Context manager**
      :class:`ExternalCommand` objects can be used as context managers by using
      the :keyword:`with` statement:

      - When the scope of the :keyword:`with` statement starts the
        :func:`start()` method is called (if the external command
        isn't already running).
      - When the scope of the :keyword:`with` statement ends
        :func:`~executor.process.ControllableProcess.terminate()` is called if
        the command is still running. The :func:`load_output()` and
        :func:`cleanup()` functions are used to cleanup after the external
        command. If an exception isn't already being raised
        :func:`check_errors()` is called to make sure the external command
        succeeded.
    """

    def __init__(self, *command, **options):
        """
        Initialize an :class:`ExternalCommand` object.

        :param command: Any positional arguments are converted to a list and
                        used to set :attr:`command`.
        :param options: Keyword arguments can be used to conveniently override
                        the default values of :attr:`async`, :attr:`callback`,
                        :attr:`capture`, :attr:`capture_stderr`, :attr:`check`,
                        :attr:`directory`, :attr:`encoding`,
                        :attr:`environment`, :attr:`fakeroot`, :attr:`input`,
                        :attr:`~executor.process.ControllableProcess.logger`,
                        :attr:`merge_streams`, :attr:`shell`, :attr:`silent`,
                        :attr:`stdout_file`, :attr:`stderr_file`, :attr:`uid`,
                        :attr:`user`, :attr:`sudo` and
                        :attr:`virtual_environment`. Any other keyword argument
                        will raise :exc:`TypeError` as usual.

        The external command is not started until you call :func:`start()` or
        :func:`wait()`.
        """
        # Store the command and its arguments but make it possible for
        # subclasses to redefine whether `command' is a required property.
        self.command = list(command)
        # Set properties based on keyword arguments.
        super(ExternalCommand, self).__init__(**options)
        # Initialize instance variables.
        self.stdin_stream = CachedStream(self, 'stdin')
        self.stdout_stream = CachedStream(self, 'stdout')
        self.stderr_stream = CachedStream(self, 'stderr')

    @mutable_property
    def async(self):
        """
        Enable asynchronous command execution.

        If this option is :data:`True` (not the default) preparations are made
        to execute the external command asynchronously (in the background).
        This has several consequences:

        - Calling :func:`start()` will start the external command but will
          not block until the external command is finished, instead you are
          responsible for calling :func:`wait()` at some later point in
          time.

        - When :attr:`input` is set its value will be written to a temporary
          file and the standard input stream of the external command is
          connected to read from the temporary file.

          By using a temporary file the external command can consume its input
          as fast or slow as it pleases without needing a separate thread or
          process to "feed" the external command.

        - When :class:`capture` is :data:`True` the standard output of the
          external command is redirected to a temporary file whose contents are
          read once the external command has finished.

          By using a temporary file the external command can produce output as
          fast or slow as it pleases without needing a thread or subprocess on
          our side to consume the output in real time.
        """
        return False

    @writable_property
    def callback(self):
        """
        Optional callback used to generate the value of :attr:`result`.

        The :attr:`callback` and :attr:`result` properties were created for use
        in command pools, where it can be useful to define how to process
        (parse) a command's output when the command is constructed.
        """

    @mutable_property
    def capture(self):
        """
        Enable capturing of the standard output stream.

        If this option is :data:`True` (not the default) the standard output of
        the external command is captured and made available to the caller via
        :attr:`stdout` and :attr:`output`.

        The standard error stream will not be captured, use :attr:`capture_stderr`
        for that. You can also silence the standard error stream using the
        :attr:`silent` option.

        If :attr:`callback` is set :attr:`capture` defaults to :data:`True`
        (but you can still set :attr:`capture` to :data:`False` if that is what
        you want).
        """
        return True if self.callback else False

    @mutable_property
    def capture_stderr(self):
        """
        Enable capturing of the standard error stream.

        If this option is :data:`True` (not the default) the standard error
        stream of the external command is captured and made available to the
        caller via :attr:`stderr`.
        """
        return False

    @mutable_property
    def check(self):
        """
        Enable automatic status code checking.

        If this option is :data:`True` (the default) and the external command
        exits with a nonzero status code :exc:`ExternalCommandFailed` will be
        raised by :func:`start()` (when :attr:`async` isn't set) or
        :func:`wait()` (when :attr:`async` is set).
        """
        return True

    @mutable_property
    def command(self):
        """
        A list of strings with the command to execute.

        .. note:: In executor version 14.0 it became valid to set :attr:`input`
                  and :attr:`shell` without providing :attr:`command` (in older
                  versions it was required to set :attr:`command` regardless of
                  the other options).
        """

    @property
    def command_line(self):
        """
        The command line of the external command.

        The command line used to actually run the external command requested by
        the user (a list of strings). The command line is constructed based on
        :attr:`command` according to the following rules:

        - If :attr:`shell` is :data:`True` the external command is run using
          ``bash -c '...'`` (assuming you haven't changed :data:`DEFAULT_SHELL`)
          which means constructs like semicolons, ampersands and pipes can be
          used (and all the usual caveats apply :-).

        - If :attr:`virtual_environment` is set the command is converted to a
          shell command line and prefixed by the applicable ``source ...``
          command.

        - If :attr:`uid` or :attr:`user` is set the `sudo -u`` command will be
          prefixed to the command line generated here.

        - If :attr:`fakeroot` or :attr:`sudo` is set the respective command
          name is prefixed to the command line generated here (``sudo`` is only
          prefixed when the current process doesn't already have super user
          privileges).
        """
        command_line = list(self.command)
        use_shell = self.shell
        have_commands = (len(command_line) > 0)
        have_input = (self.input is not None)
        if use_shell and have_input and not have_commands:
            # If `shell' is enabled and `input' is given but no `command' is
            # given, we will start the DEFAULT_SHELL and instruct it to read
            # shell commands to execute from its standard input stream.
            use_shell = False
            command_line = [DEFAULT_SHELL, '-']
        # Apply the `shell' and/or `virtual_environment' options.
        if self.virtual_environment:
            activate_script = os.path.join(self.virtual_environment, 'bin', 'activate')
            if use_shell:
                # Shell command(s) provided via positional arguments or standard input.
                shell_command = 'source %s && %s' % (quote(activate_script), command_line[0])
                command_line = [DEFAULT_SHELL, '-c', shell_command] + command_line[1:]
            else:
                # Non-shell command line provided via positional arguments.
                shell_command = 'source %s && %s' % (quote(activate_script), quote(command_line))
                command_line = [DEFAULT_SHELL, '-c', shell_command]
        elif use_shell:
            # Prepare to execute a shell command.
            command_line = [DEFAULT_SHELL, '-c'] + command_line
        # Run the command under `fakeroot' to fake super user privileges?
        if self.fakeroot:
            command_line = ['fakeroot'] + command_line
        # Run the command under `sudo' to elevate or change privileges?
        return self.sudo_command + command_line

    @property
    def decoded_stdout(self):
        """
        The value of :attr:`stdout` decoded using :attr:`encoding`.

        This is a :func:`python2:unicode` object (in Python 2) or a
        :class:`python3:str` object (in Python 3).
        """
        value = self.stdout
        if value is not None:
            return value.decode(self.encoding)

    @property
    def decoded_stderr(self):
        """
        The value of :attr:`stderr` decoded using :attr:`encoding`.

        This is a :func:`python2:unicode` object (in Python 2) or a
        :class:`python3:str` object (in Python 3).
        """
        value = self.stderr
        if value is not None:
            return value.decode(self.encoding)

    @writable_property(cached=True)
    def dependencies(self):
        """
        The dependencies of the command (a list of :class:`ExternalCommand` objects).

        The :attr:`dependencies` property enables low level concurrency control
        in command pools by imposing a specific order of execution:

        - Command pools will never start a command until the
          :attr:`~.ExternalCommand.is_finished` properties of all of the
          command's :attr:`~.ExternalCommand.dependencies` are :data:`True`.

        - If :attr:`dependencies` is empty it has no effect and concurrency is
          controlled by :attr:`group_by` and :attr:`~.CommandPool.concurrency`.
        """
        return []

    @mutable_property
    def directory(self):
        """
        The working directory for the external command.

        A string, defaults to :data:`DEFAULT_WORKING_DIRECTORY`.
        """
        return DEFAULT_WORKING_DIRECTORY

    @property
    def encoded_input(self):
        """
        The value of :attr:`input` encoded using :attr:`encoding`.

        This is a :class:`python2:str` object (in Python 2) or a
        :class:`python3:bytes` object (in Python 3).
        """
        return (self.input.encode(self.encoding)
                if isinstance(self.input, unicode)
                else self.input)

    @mutable_property
    def encoding(self):
        """
        The character encoding of standard input and standard output.

        A string, defaults to :data:`DEFAULT_ENCODING`. This option is used to
        encode :attr:`input` and to decode :attr:`output`.
        """
        return DEFAULT_ENCODING

    @writable_property(cached=True)
    def environment(self):
        """
        A dictionary of environment variables for the external command.

        You only need to specify environment variables that differ from those
        of the current process (that is to say the environment variables of the
        current process are merged with the variables that you specify here).
        """
        return {}

    @mutable_property
    def error_message(self):
        """A string describing how the external command failed or :data:`None`."""
        if self.error_type is CommandNotFound:
            return format("External command isn't available! (command: %s, search path: %s)",
                          quote(self.command_line), get_search_path())
        elif self.error_type is ExternalCommandFailed:
            return format("External command failed with exit code %s! (command: %s)",
                          self.returncode, quote(self.command_line))

    @mutable_property
    def error_type(self):
        """
        An appropriate exception class or :data:`None` (when no error occurred).

        :class:`CommandNotFound` if the external command exits with return code
        :data:`COMMAND_NOT_FOUND_STATUS` or :exc:`ExternalCommandFailed` if the
        external command exits with any other nonzero return code.
        """
        if self.returncode == COMMAND_NOT_FOUND_STATUS:
            return CommandNotFound
        elif self.returncode not in (None, 0):
            return ExternalCommandFailed

    @property
    def failed(self):
        """
        Whether the external command has failed.

        - :data:`True` if :attr:`returncode` is a nonzero number
          or :attr:`error_type` is set (e.g. because the external
          command doesn't exist).
        - :data:`False` if :attr:`returncode` is zero.
        - :data:`None` when the external command hasn't been started or is
          still running.
        """
        return (not self.succeeded) if self.succeeded is not None else None

    @mutable_property
    def fakeroot(self):
        """
        Run the external command under ``fakeroot``.

        If this option is :data:`True` (not the default) and the current
        process doesn't have `superuser privileges`_ the external command is
        run with ``fakeroot``. If the ``fakeroot`` program is not installed the
        external command will fail.

        .. _superuser privileges: http://en.wikipedia.org/wiki/Superuser#Unix_and_Unix-like
        """
        return False

    @mutable_property
    def finish_event(self):
        """
        Optional callback that's called just after the command finishes.

        The :attr:`start_event` and :attr:`finish_event` properties were
        created for use in command pools, for example to report to the operator
        when specific commands are started and when they finish. The invocation
        of the :attr:`start_event` and :attr:`finish_event` callbacks is
        performed inside the :class:`ExternalCommand` class though, so you're
        free to repurpose these callbacks outside the context of command
        pools.
        """

    @mutable_property
    def group_by(self):
        """
        Identifier that's used to group the external command (any hashable value).

        The :attr:`group_by` property enables high level concurrency control in
        command pools by making it easy to control which commands are allowed
        to run concurrently and which are required to run serially:

        - Command pools will never start more than one command within a group
          of commands that share the same value of :attr:`group_by` (for values
          that aren't :data:`None`).

        - If :attr:`group_by` is :data:`None` it has no effect and concurrency
          is controlled by :attr:`dependencies` and
          :attr:`~.CommandPool.concurrency`.
        """

    @property
    def have_superuser_privileges(self):
        """
        Whether the parent Python process is running under `superuser privileges`_.

        :data:`True` if running with `superuser privileges`_, :data:`False`
        otherwise. Used by :attr:`command_line` to decide whether
        :attr:`fakeroot` or :attr:`sudo` needs to be used.
        """
        return os.getuid() == 0

    @mutable_property
    def input(self):
        """
        The input to feed to the external command on the standard input stream.

        Defaults to :data:`None`. When you provide a :func:`python2:unicode`
        object (in Python 2) or a :class:`python3:str` object (in Python 3) as
        input it will be encoded using :attr:`encoding`. To avoid the automatic
        conversion you can simply pass a :class:`python2:str` object (in Python
        2) or a :class:`python3:bytes` object (in Python 3).

        The conversion logic is implemented in the :attr:`encoded_input`
        attribute.
        """

    @property
    def is_finished(self):
        """
        Whether the external command has finished execution.

        :data:`True` once the external command has been started and has since
        finished, :data:`False` when the external command hasn't been started
        yet or is still running.
        """
        return self.was_started and not self.is_running

    @property
    def is_running(self):
        """:data:`True` if the process is currently running, :data:`False` otherwise."""
        if self.subprocess is not None:
            return self.subprocess.poll() is None
        else:
            return False

    @property
    def is_terminated(self):
        """
        Whether the external command has been terminated (a boolean).

        :data:`True` if the external command was terminated using
        :data:`signal.SIGTERM` (e.g. by
        :func:`~executor.process.ControllableProcess.terminate()`),
        :data:`False` otherwise.
        """
        return abs(self.returncode) == signal.SIGTERM if self.is_finished and self.returncode < 0 else False

    @mutable_property
    def merge_streams(self):
        """
        Whether to merge the standard output and error streams.

        A boolean, defaults to :data:`False`. If this option is enabled
        :attr:`stdout` will contain the external command's output on both
        streams.
        """
        return False

    @property
    def output(self):
        """
        The value of :attr:`stdout` decoded using :attr:`encoding`.

        This is a :func:`python2:unicode` object (in Python 2) or a
        :class:`python3:str` object (in Python 3).

        This is only available when :attr:`capture` is :data:`True`. If
        :attr:`capture` is not :data:`True` then :attr:`output` will be
        :data:`None`.

        After decoding any leading and trailing whitespace is stripped and if
        the resulting string doesn't contain any remaining newlines then the
        string with leading and trailing whitespace stripped will be returned,
        otherwise the decoded string is returned unchanged:

        >>> from executor import ExternalCommand
        >>> cmd = ExternalCommand('echo na\xc3\xafve', capture=True)
        >>> cmd.start()
        >>> cmd.output
        u'na\\xefve'
        >>> cmd.stdout
        'na\\xc3\\xafve\\n'

        This is intended to make simple things easy (:attr:`output` makes it
        easy to deal with external commands that output a single line) while
        providing an escape hatch when the default assumptions don't hold (you
        can always use :attr:`stdout` to get the raw output).
        """
        text_output = self.decoded_stdout
        if text_output is not None:
            stripped_output = text_output.strip()
            return stripped_output if '\n' not in stripped_output else text_output

    @property
    def result(self):
        """
        The result of calling the value given by :attr:`callback`.

        If the command hasn't been started yet :func:`start()` is called. When
        the command hasn't finished yet func:`wait()` is called. If
        :attr:`callback` isn't set :data:`None` is returned.
        """
        if self.callback:
            if not self.is_finished:
                self.wait()
            return self.callback(self)

    @mutable_property
    def returncode(self):
        """
        The return code of the external command (an integer) or :data:`None`.

        This will be :data:`None` until the external command has finished.
        """
        if self.subprocess is not None:
            return self.subprocess.poll()

    @mutable_property
    def shell(self):
        """
        Whether to evaluate the external command as a shell command.

        A boolean, the default depends on the value of :attr:`command`:

        - If :attr:`command` contains a single string :attr:`shell` defaults to
          :data:`True`.

        - If :attr:`command` contains more than one string :attr:`shell`
          defaults to :data:`False`.

        When :data:`shell` is :data:`True` the external command is evaluated by
        the shell given by :data:`DEFAULT_SHELL`, otherwise the external
        command is run without shell evaluation.
        """
        return len(self.command) == 1

    @mutable_property
    def silent(self):
        """
        Whether the external command's output should be silenced.

        If this is :data:`True` (not the default) any output of the external
        command is silenced by redirecting the output streams to
        :data:`os.devnull`.

        You can enable :attr:`capture` and :attr:`silent` together to capture
        the standard output stream while silencing the standard error stream.
        """
        return False

    @mutable_property
    def start_event(self):
        """
        Optional callback that's called just before the command is started.

        The :attr:`start_event` and :attr:`finish_event` properties were
        created for use in command pools, for example to report to the operator
        when specific commands are started and when they finish. The invocation
        of the :attr:`start_event` and :attr:`finish_event` callbacks is
        performed inside the :class:`ExternalCommand` class though, so you're
        free to repurpose these callbacks outside the context of command
        pools.
        """

    @property
    def stderr(self):
        """
        The output of the external command on its standard error stream.

        This is a :class:`python2:str` object (in Python 2) or a
        :class:`python3:bytes` object (in Python 3).

        This is only available when :attr:`capture_stderr` is :data:`True`. If
        :attr:`capture_stderr` is not :data:`True` then :attr:`stderr` will be
        :data:`None`.
        """
        return self.stderr_stream.load()

    @mutable_property
    def stderr_file(self):
        """
        Capture the standard error stream to the given file handle.

        When this property is set to a writable file object the standard error
        stream of the external command is redirected to the given file. The
        default value of this property is :data:`None`.

        This can be useful to (semi) permanently store command output or to run
        commands whose output is hidden but can be followed using `tail -f`_ if
        the need arises. By setting :attr:`stdout_file` and :attr:`stderr_file`
        to the same file object the output from both streams can be merged and
        redirected to the same file. This accomplishes roughly the same thing
        as setting :attr:`merge_streams` but leaves the caller in control of
        the file.

        If this property isn't set but :attr:`capture` is :data:`True` the
        external command's output is captured to a temporary file that's
        automatically cleaned up after the external command is finished and its
        output has been cached (read into memory).

        .. _tail -f: https://en.wikipedia.org/wiki/Tail_(Unix)#File_monitoring
        """

    @property
    def stdout(self):
        """
        The output of the external command on its standard output stream.

        This is a :class:`python2:str` object (in Python 2) or a
        :class:`python3:bytes` object (in Python 3).

        This is only available when :attr:`capture` is :data:`True`. If
        :attr:`capture` is not :data:`True` then :attr:`stdout` will be
        :data:`None`.
        """
        return self.stdout_stream.load()

    @mutable_property
    def stdout_file(self):
        """
        Capture the standard output stream to the given file handle.

        When this property is set to a writable file object the standard output
        stream of the external command is redirected to the given file. The
        default value of this property is :data:`None`.

        This can be useful to (semi) permanently store command output or to run
        commands whose output is hidden but can be followed using `tail -f`_ if
        the need arises. By setting :attr:`stdout_file` and :attr:`stderr_file`
        to the same file object the output from both streams can be merged and
        redirected to the same file. This accomplishes roughly the same thing
        as setting :attr:`merge_streams` but leaves the caller in control of
        the file.

        If this property isn't set but :attr:`capture` is :data:`True` the
        external command's output is captured to a temporary file that's
        automatically cleaned up after the external command is finished and its
        output has been cached (read into memory).
        """

    @mutable_property
    def subprocess(self):
        """
        A :class:`subprocess.Popen` object or :data:`None`.

        The value of this property is set by :func:`start()` and it's cleared
        by :func:`wait()` (through :func:`cleanup()`) as soon as the external
        command has finished. This enables garbage collection of the resources
        associated with the :class:`subprocess.Popen` object which helps to
        avoid `IOError: [Errno 24] Too many open files
        <http://stackoverflow.com/a/23763193/788200>`_ errors.
        """

    @property
    def succeeded(self):
        """
        Whether the external command succeeded.

        - :data:`True` if :attr:`returncode` is zero.
        - :data:`False` if :attr:`returncode` is a nonzero number
          or :attr:`error_type` is set (e.g. because the external
          command doesn't exist).
        - :data:`None` when the external command hasn't been started or is
          still running.
        """
        return self.returncode == 0 if self.is_finished else None

    @mutable_property
    def sudo(self):
        """
        Whether ``sudo`` should be used to gain superuser privileges.

        If this option is :data:`True` (not the default) and the current
        process doesn't have `superuser privileges`_ the external command is
        run with ``sudo`` to ensure that the external command runs with
        superuser privileges.

        The use of this option assumes that the ``sudo`` command is
        available.
        """
        return False

    @property
    def sudo_command(self):
        """
        The ``sudo`` command used to change privileges (a list of strings).

        This option looks at the :attr:`sudo`, :attr:`uid` and :attr:`user`
        properties to decide whether :attr:`command` should be run using
        ``sudo`` or not. If it should then a prefix for :attr:`command` is
        constructed from :attr:`sudo`, :attr:`uid`, :attr:`user` and/or
        :attr:`environment` and returned. Some examples:

        >>> from executor import ExternalCommand
        >>> ExternalCommand('true', sudo=True).sudo_command
        ['sudo']
        >>> ExternalCommand('true', uid=1000).sudo_command
        ['sudo', '-u', '#1000']
        >>> ExternalCommand('true', user='peter').sudo_command
        ['sudo', '-u', 'peter']
        >>> ExternalCommand('true', user='peter', environment=dict(gotcha='this is tricky')).sudo_command
        ['sudo', '-u', 'peter', 'gotcha=this is tricky']
        """
        command_line = []
        # Use `sudo' to run the command with super user privileges?
        if self.sudo and not self.have_superuser_privileges:
            command_line.append('sudo')
        # Use `sudo' to run the command as a different user?
        if self.uid is not None or self.user is not None:
            if not command_line:
                command_line.append('sudo')
            command_line.append('-u')
            if self.uid is not None:
                command_line.append('#%i' % self.uid)
            else:
                command_line.append(self.user)
        # If we're going to run the command under `sudo' we need to copy the
        # environment variables into the `sudo' command line, otherwise the
        # variables won't be exposed to the command!
        if command_line:
            command_line.extend('%s=%s' % (k, v) for k, v in sorted(self.environment.items()))
        return command_line

    @mutable_property
    def tty(self):
        """
        Whether the command will be attached to the controlling terminal (a boolean).

        By default :attr:`tty` is :data:`True` when:

        - :attr:`capture` is :data:`False`
        - :attr:`capture_stderr` is :data:`False`
        - :attr:`input` is :data:`None`
        - :attr:`silent` is :data:`False`
        - :attr:`stdout_file` and :attr:`stderr_file` are :data:`None` or
          files that are connected to a tty(-like) device

        If any of these conditions don't hold :attr:`tty` defaults to
        :data:`False`. When :attr:`tty` is :data:`False` the standard input
        stream of the external command will be connected to :data:`os.devnull`.
        """
        return (self.input is None and
                not self.capture and
                not self.capture_stderr and
                not self.silent and
                not any(value and not connected_to_terminal(value)
                        for value in (self.stdout_file, self.stderr_file)))

    @mutable_property
    def uid(self):
        """
        The user ID of the system user that's used to run the command.

        If this option is set to an integer number (it defaults to
        :data:`None`) the external command is prefixed with ``sudo -u #UID`` to
        run the command as a different user than the current user.

        The use of this option assumes that the ``sudo`` command is
        available.
        """

    @mutable_property
    def user(self):
        """
        The name of the system user that's used to run the command.

        If this option is set to a string (it defaults to :data:`None`) the
        external command is prefixed with ``sudo -u USER`` to run the command
        as a different user than the current user.

        The use of this option assumes that the ``sudo`` command is
        available.
        """

    @mutable_property
    def virtual_environment(self):
        """
        The `Python virtual environment`_ to activate before running the command.

        If this option is set to the directory of a Python virtual environment
        (a string) then the external command will be prefixed by a `source
        shell command`_ that evaluates the ``bin/activate`` script in the
        Python virtual environment before executing the user defined external
        command.

        .. _Python virtual environment: http://docs.python-guide.org/en/latest/dev/virtualenvs/
        .. _source shell command: https://en.wikipedia.org/wiki/Source_(command)
        """

    @mutable_property
    def was_started(self):
        """
        Whether the external command has already been started.

        :data:`True` once :func:`start()` has been called to start executing
        the external command, :data:`False` when :func:`start()` hasn't been
        called yet.
        """
        return False

    def start(self):
        """
        Start execution of the external command.

        :raises: - :exc:`ExternalCommandFailed` when
                   :attr:`~ExternalCommand.check` is :data:`True`,
                   :attr:`async` is :data:`False` and the external command
                   exits with a nonzero status code.

                 - :exc:`ValueError` when the external command is still
                   running (you need to explicitly terminate, kill or wait
                   for the running process before you can re-use the
                   :class:`ExternalCommand` object).

        This method instantiates a :class:`subprocess.Popen` object based on
        the defaults defined by :class:`ExternalCommand` and the overrides
        configured by the caller. What happens then depends on :attr:`async`:

        - If :attr:`async` is set :func:`start()` starts the external command
          but doesn't wait for it to end (use :func:`wait()` for that).

        - If :attr:`async` isn't set the ``communicate()`` method on the
          :attr:`subprocess` object is called to synchronously execute the
          external command.
        """
        if self.is_running:
            # If the external command is currently running reset() will leak
            # file descriptors and besides that it doesn't really make sense to
            # re-use ExternalCommand objects in this way.
            raise ValueError(compact("""
                External command is already running! (you need to explicitly
                terminate, kill or wait for the running process before you can
                re-use the ExternalCommand object)
            """))
        # Prepare the keyword arguments to subprocess.Popen().
        kw = dict(args=self.command_line,
                  cwd=self.directory,
                  env=os.environ.copy())
        kw['env'].update(self.environment)
        # Prepare the command's standard input/output/error streams.
        kw['stdin'] = self.stdin_stream.prepare_input()
        kw['stdout'] = self.stdout_stream.prepare_output(self.stdout_file, self.capture)
        kw['stderr'] = (subprocess.STDOUT if self.merge_streams else
                        self.stderr_stream.prepare_output(self.stderr_file, self.capture_stderr))
        # Let the operator know what's about to happen.
        self.logger.debug("Executing external command: %s", quote(kw['args']))
        # Lightweight reset of internal state.
        for name in 'error_type', 'pid', 'returncode', 'subprocess':
            delattr(self, name)
        # Invoke the start event callback?
        self.invoke_event_callback('start_event')
        # Remember that we called subprocess.Popen() regardless of whether it
        # is about to raise an exception or not.
        self.was_started = True
        # Create the subprocess.Popen object and start the subprocess.
        try:
            self.logger.debug("Constructing subprocess.Popen object ..")
            self.subprocess = subprocess.Popen(**kw)
        except OSError as e:
            if e.errno in COMMAND_NOT_FOUND_CODES:
                # Translate errno.ENOENT into a CommandNotFound exception.
                self.error_type = CommandNotFound
                # Cleanup temporary resources and raise the exception (or not).
                self.wait()
            else:
                # Don't swallow exceptions we can't handle.
                raise
        else:
            # Copy the process ID from the subprocess.Popen object as soon as
            # it becomes available. This enables us to garbage collect the
            # subprocess.Popen object without losing track of the process ID.
            self.pid = self.subprocess.pid
            # Synchronously wait for the external command to end?
            if not self.async:
                self.logger.debug("Joining synchronous process using subprocess.Popen.communicate() ..")
                stdout, stderr = self.subprocess.communicate(self.encoded_input)
                self.stdout_stream.finalize(stdout)
                self.stderr_stream.finalize(stderr)
                self.wait()
        finally:
            # Invoke the finish event callback? (only applies when the command
            # is synchronous or the subprocess module raised an exception)
            if not self.is_running:
                self.invoke_event_callback('finish_event')

    def wait(self, check=None, **kw):
        """
        Wait for the external command to finish.

        :param check: Override the value of :attr:`check` for the duration of
                      this call to :func:`wait()`. Defaults to :data:`None`
                      which means :attr:`check` is not overridden.
        :param kw: Any keyword arguments are passed on to
                   :func:`~executor.process.ControllableProcess.wait_for_process()`.
        :raises: :exc:`ExternalCommandFailed` when :attr:`check` is
                 :data:`True`, :attr:`async` is :data:`True` and the external
                 command exits with a nonzero status code.

        The :func:`wait()` function is only useful when :attr:`async` is
        :data:`True`, it performs the following steps:

        1. If :attr:`was_started` is :data:`False` the :func:`start()` method
           is called.

        2. If :attr:`is_running` is :data:`True` the
           :func:`~executor.process.ControllableProcess.wait_for_process()`
           method is called to wait for the child process to end.

        3. If :attr:`subprocess` isn't :data:`None` the :func:`cleanup()`
           method is called to wait for the external command to end, load its
           output into memory and release the resources associated with the
           :attr:`subprocess` object.

        4. Finally :func:`check_errors()` is called (in case the caller
           didn't disable :attr:`check`).
        """
        if not self.was_started:
            self.start()
        if self.is_running:
            self.wait_for_process()
        self.cleanup()
        self.check_errors(check=check)

    def terminate_helper(self):
        """
        Gracefully terminate the process.

        :raises: Any exceptions raised by the :mod:`subprocess` module.

        This method sets :attr:`check` to :data:`False`, the idea being that if
        you consciously terminate a command you don't need to be bothered with
        an exception telling you that you succeeded :-).
        """
        if self.subprocess is not None:
            self.logger.debug("Terminating process using subprocess.Popen.terminate() ..")
            self.subprocess.terminate()
            self.check = False

    def kill_helper(self):
        """
        Forcefully kill the process.

        :raises: Any exceptions raised by the :mod:`subprocess` module.

        This method sets :attr:`check` to :data:`False`, the idea being that if
        you consciously kill a command you don't need to be bothered with an
        exception telling you that you succeeded :-).
        """
        if self.subprocess is not None:
            self.logger.debug("Killing process using subprocess.Popen.kill() ..")
            self.subprocess.kill()
            self.check = False

    def load_output(self):
        """
        Load output captured from the standard output/error streams.

        Reads the contents of the temporary file(s) created by :func:`start()`
        (when :attr:`async` and :attr:`capture` are both set) into memory so
        that the output doesn't get lost when the temporary file is cleaned up
        by :func:`cleanup()`.
        """
        self.stdout_stream.load()
        self.stderr_stream.load()

    def cleanup(self):
        """
        Clean up after the external command has ended.

        This internal method is called by methods like :func:`start()` and
        :func:`wait()` to clean up the following temporary resources:

        - The temporary file(s) used to to buffer the external command's
          :attr:`input`, :attr:`stdout` and :attr:`stderr` (only when
          :attr:`async` is :data:`True`).

        - File handles to the previously mentioned temporary files and
          :data:`os.devnull` (used to implement the :attr:`silent` option).

        - The reference to the :class:`subprocess.Popen` object stored in
          :attr:`subprocess`. By destroying this reference as soon as possible
          we enable the object to be garbage collected and its related
          resources to be released.
        """
        # Cleanup the stdin/stdout/stderr streams.
        self.stdin_stream.cleanup()
        self.stdout_stream.finalize()
        self.stderr_stream.finalize()
        # Prepare to garbage collect the subprocess.Popen object?
        if self.subprocess is not None:
            if self.async:
                self.logger.debug("Joining asynchronous process using subprocess.Popen.wait() ..")
                # Perform a wait to allow the system to release the resources
                # associated with the child process; if a wait is not performed,
                # the terminated child remains in a `zombie' state (paraphrased
                # from http://linux.die.net/man/2/waitpid). We copy the return code
                # so we don't lose track of it once we allow the subprocess.Popen
                # object to be garbage collected.
                self.returncode = self.subprocess.wait()
                # Invoke the finish event callback?
                self.invoke_event_callback('finish_event')
            else:
                # Override the computed value of the `returncode' property
                # because computing it again after we destroy our reference
                # to the subprocess.Popen object will be impossible.
                self.returncode = self.subprocess.returncode
            # Destroy our reference to the subprocess.Popen object
            # to allow it to be garbage collected.
            delattr(self, 'subprocess')

    def reset(self):
        """Reset internal state created by :func:`start()`."""
        self.cleanup()
        delattr(self, 'error_message')
        delattr(self, 'error_type')
        delattr(self, 'pid')
        delattr(self, 'returncode')
        self.stdin_stream.reset()
        self.stdout_stream.reset()
        self.stderr_stream.reset()
        self.was_started = False

    def check_errors(self, check=None):
        """
        Raise an exception if the external command failed.

        This raises :attr:`error_type` when :attr:`check` is set and the
        external command failed.

        :param check: Override the value of :attr:`check` for the duration of
                      this call. Defaults to :data:`None` which means
                      :attr:`check` is not overridden.
        :raises: :attr:`error_type` when :attr:`check` is set and
                 :attr:`error_type` is not :data:`None`.

        This internal method is used by :func:`start()` and :func:`wait()` to
        make sure that failing external commands don't go unnoticed.
        """
        if (check if check is not None else self.check) and self.error_type is not None:
            raise self.error_type(self)

    def invoke_event_callback(self, name):
        """
        Invoke one of the event callbacks.

        :param name: The name of the callback (a string).
        """
        callback = getattr(self, name)
        if callback is not None:
            logger.debug("Invoking %s callback ..", name)
            callback(self)

    def __enter__(self):
        """
        Start the external command if it hasn't already been started.

        :returns: The :class:`ExternalCommand` object.

        When you use an :class:`ExternalCommand` as a context manager in the
        :keyword:`with` statement, the command is automatically started when
        entering the context and terminated when leaving the context.

        If the proces hasn't already been started yet :attr:`async` is
        automatically set to :data:`True` (if it's not already :data:`True`),
        otherwise the command will have finished execution by the time the body
        of the :keyword:`with` statement is executed (which isn't really all
        that useful :-).
        """
        if not self.was_started:
            if not self.async:
                self.async = True
            self.start()
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """
        Automatically terminate and clean up after the external command.

        Terminates the external command if it is still running (using
        :func:`~executor.process.ControllableProcess.terminate()`), cleans up
        (using :func:`cleanup()`) and checks for errors (using
        :func:`check_errors()`, only if an exception is not already being
        handled).
        """
        if self.was_started:
            if self.is_running:
                self.terminate()
            self.cleanup()
            if exc_type is None:
                # Check for external command errors only when not already
                # handling an exception.
                self.check_errors()


class CachedStream(object):

    """Manages a temporary file with input for / output from an external command."""

    def __init__(self, command, kind):
        """
        Initialize a :class:`CachedStream` object.

        :param command: The :class:`ExternalCommand` object that's using the
                        :class:`CachedStream` object.
        :param kind: A simple (alphanumeric) string with the name of the stream.
        """
        # Store the arguments.
        self.command = command
        self.kind = kind
        # Initialize instance variables.
        self.cached_output = None
        self.fd = None
        self.filename = None
        self.is_temporary_file = False
        self.kind = kind
        self.null_device = None

    def prepare_temporary_file(self):
        """Prepare the stream's temporary file."""
        if not (self.fd and self.filename):
            self.is_temporary_file = True
            self.fd, self.filename = tempfile.mkstemp(prefix='executor-', suffix='-%s.txt' % self.kind)
            logger.debug("Connected %s stream to temporary file %s ..", self.kind, self.filename)

    def prepare_input(self):
        """
        Initialize the input stream.

        :returns: A value that can be passed to the constructor of
                  :class:`subprocess.Popen` as the ``stdin`` argument.
        """
        if self.command.input is not None:
            if self.command.async:
                # Store the input provided by the caller in a temporary file
                # and connect the file to the command's standard input stream.
                self.prepare_temporary_file()
                with open(self.filename, 'wb') as handle:
                    handle.write(self.command.encoded_input)
                return self.fd
            else:
                # Prepare to pass the input provided by the caller to the
                # external command using subprocess.Popen.communicate().
                return subprocess.PIPE
        elif not self.command.tty:
            # Redirect the command's standard input to /dev/null to inform the
            # command that it can't expect to present an interactive prompt and
            # ask the operator to respond (because the operator likely won't
            # be able to see the interactive prompt).
            if self.null_device is None:
                self.null_device = open(os.devnull, 'rb')
            return self.null_device

    def prepare_output(self, file, capture):
        """
        Initialize an (asynchronous) output stream.

        :param file: A file handle or :data:`None`.
        :param capture: :data:`True` if capturing is enabled, :data:`False` otherwise.
        :returns: A value that can be passed to the constructor of
                  :class:`subprocess.Popen` as the ``stdout`` and/or
                  ``stderr`` argument.
        """
        if file is not None:
            # Capture the stream to a user defined file.
            self.redirect(file)
            return self.fd
        elif capture:
            if self.command.async:
                # Capture the stream to a temporary file.
                self.prepare_temporary_file()
                return self.fd
            else:
                # Capture the stream in memory.
                return subprocess.PIPE
        elif self.command.silent:
            # Silence the stream by redirecting it to /dev/null.
            if self.null_device is None:
                self.null_device = open(os.devnull, 'wb')
            return self.null_device

    def redirect(self, obj):
        """
        Capture the stream in a file provided by the caller.

        :param obj: A file-like object that has an associated file descriptor.
        """
        # Try to get the file descriptor.
        try:
            self.fd = obj.fileno()
        except Exception:
            msg = "Can't capture %s stream to file object without file descriptor!"
            raise ValueError(msg % self.kind)
        # Try to get the filename.
        self.filename = getattr(obj, 'name', None)
        if not self.filename:
            msg = "Can't capture %s stream to file object without filename! ('name' attribute)"
            raise ValueError(msg % self.kind)
        logger.debug("Connected %s stream to file %s ..", self.kind, self.filename)

    def load(self):
        """
        Load the stream's contents from the temporary file.

        :returns: The output of the stream (a string) or :data:`None` when the
                  stream was never initialized.
        """
        if self.filename and os.path.isfile(self.filename):
            with open(self.filename, 'rb') as handle:
                self.cached_output = handle.read()
        return self.cached_output

    def finalize(self, output=None):
        """
        Load or override the stream's contents and cleanup the temporary file.

        :param output: Override the stream's contents (defaults to :data:`None`
                       which means the contents are loaded from the temporary
                       file instead).
        """
        if output is not None:
            self.cached_output = output
        else:
            self.load()
        self.cleanup()

    def cleanup(self):
        """Cleanup temporary resources."""
        if self.is_temporary_file:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            if self.filename:
                if os.path.isfile(self.filename):
                    os.unlink(self.filename)
                self.filename = None
            self.is_temporary_file = False
        if self.null_device is not None:
            self.null_device.close()
            self.null_device = None

    def reset(self):
        """Reset internal state."""
        self.cached_output = None
        self.cleanup()


def quote(*args):
    """
    Quote a string or a sequence of strings to be used as command line argument(s).

    This function is a simple wrapper around :func:`pipes.quote()` which
    adds support for quoting sequences of strings (lists and tuples). For
    example the following calls are all equivalent::

      >>> from executor import quote
      >>> quote('echo', 'argument with spaces')
      "echo 'argument with spaces'"
      >>> quote(['echo', 'argument with spaces'])
      "echo 'argument with spaces'"
      >>> quote(('echo', 'argument with spaces'))
      "echo 'argument with spaces'"

    :param args: One or more strings, tuples and/or lists of strings to be quoted.
    :returns: A string containing quoted command line arguments.
    """
    if len(args) > 1:
        value = args
    else:
        value = args[0]
        if not isinstance(value, (list, tuple)):
            return pipes.quote(value)
    return ' '.join(map(quote, value))


def which(program, mode=os.F_OK | os.X_OK, path=None):
    """
    Find the pathname(s) of a program on the executable search path (``$PATH``).

    :param program: The name of the program (a string).
    :returns: A list of pathnames (strings) with found programs.

    Some examples:

    >>> from executor import which
    >>> which('python')
    ['/home/peter/.virtualenvs/executor/bin/python', '/usr/bin/python']
    >>> which('vim')
    ['/usr/bin/vim']
    >>> which('non-existing-program')
    []

    """
    matches = []
    if os.path.dirname(program):
        # Compatibility with shutil.which(): Don't traverse the executable
        # search path when we're given a path with a directory part (instead
        # look up the file directly).
        if is_executable(program, mode):
            matches.append(program)
    else:
        extensions = get_path_extensions()
        for directory in get_search_path(path):
            pathname = os.path.join(directory, program)
            for ext in extensions:
                extended_pathname = os.path.abspath(pathname + ext)
                if extended_pathname not in matches and is_executable(extended_pathname, mode):
                    matches.append(extended_pathname)
    return matches


def get_search_path(path=None):
    """
    Get the executable search path (``$PATH``).

    :param path: Override the value of ``$PATH`` (a string or :data:`None`).
    :returns: A list of strings with pathnames of directories.

    The executable search path is constructed as follows:

    1. The search path is taken from the environment variable ``$PATH``.
    2. If ``$PATH`` isn't defined the value of :data:`os.defpath` is used.
    3. The search path is split on :data:`os.pathsep` to get a list.
    4. On Windows the current directory is prepended to the list.
    5. Duplicate directories are removed from the list.
    """
    if path is None:
        # Fall back to the current or default path.
        path = os.environ.get('PATH', os.defpath)
    directories = path.split(os.pathsep) if path else []
    if IS_WINDOWS:
        # Prepend the current working directory to the path.
        directories.insert(0, os.getcwd())
    # Filter out duplicate directory pathnames.
    unique_directories = []
    for directory in directories:
        directory = os.path.abspath(directory)
        if directory not in unique_directories:
            unique_directories.append(directory)
    return unique_directories


def get_path_extensions(extensions=None):
    """
    Get the executable search path extensions (``$PATHEXT``).

    :returns: A list of strings with unique path extensions (on Windows)
              or a list containing an empty string (on other platforms).
    """
    if extensions is None:
        # Get the path extensions defined by the environment (on Windows).
        extensions = os.environ.get('PATHEXT', '') if IS_WINDOWS else ''
    # Filter out duplicate path extensions.
    unique_extensions = []
    for ext in extensions.split(os.pathsep):
        normalized_extension = ext.lower()
        if normalized_extension not in unique_extensions:
            unique_extensions.append(normalized_extension)
    return unique_extensions


def is_executable(filename, mode=os.F_OK | os.X_OK):
    """
    Check whether the given file is executable.

    :param filename: A relative or absolute pathname (a string).
    :returns: :data:`True` if the file is executable,
              :data:`False` otherwise.
    """
    return os.path.exists(filename) and os.access(filename, mode) and not os.path.isdir(filename)


class ExternalCommandFailed(PropertyManager, Exception):

    """
    Raised when an external command exits with a nonzero status code.

    This exception is raised by :func:`execute()`,
    :func:`~ExternalCommand.start()` and :func:`~ExternalCommand.wait()` when
    an external command exits with a nonzero status code.
    """

    def __init__(self, command, **options):
        """
        Initialize an :class:`ExternalCommandFailed` object.

        :param command: The :class:`ExternalCommand` object that triggered the
                        exception.
        :param kw: Keyword arguments are passed on to
                   :func:`property_manager.PropertyManager.__init__()`.
        :param error_message: An error message to override the default message
                              taken from :attr:`~ExternalCommand.error_message`.
        """
        PropertyManager.__init__(self, command=command, **options)
        Exception.__init__(self, self.error_message)

    @required_property(usage_notes=False)
    def command(self):
        """The :class:`ExternalCommand` object that triggered the exception."""

    @writable_property(usage_notes=False)
    def pool(self):
        """
        The :class:`.CommandPool` object that triggered the exception.

        This property will be :data:`None` when the exception wasn't raised
        from a command pool.
        """

    @property
    def returncode(self):
        """Shortcut for the external command's :attr:`~ExternalCommand.returncode`."""
        return self.command.returncode

    @writable_property(usage_notes=False)
    def error_message(self):
        """
        An error message explaining what went wrong (a string).

        Defaults to :attr:`~ExternalCommand.error_message` but can be
        overridden using the keyword argument of the same name to
        :func:`__init__()`.
        """
        return self.command.error_message


class CommandNotFound(ExternalCommandFailed, OSError):

    """
    Raised when an external command is not available on the system.

    This exception is raised by :func:`execute()`,
    :func:`~ExternalCommand.start()` and :func:`~ExternalCommand.wait()` when
    an external command can't be started because the command isn't available.

    It inherits from :exc:`ExternalCommandFailed` to enable uniform error
    handling but it also inherits from :exc:`~exceptions.OSError` for
    backwards compatibility (see :attr:`errno` and :attr:`strerror`).
    """

    @property
    def errno(self):
        """The numeric error code :data:`~errno.ENOENT` from :mod:`errno` (an integer)."""
        return errno.ENOENT

    @property
    def strerror(self):
        """The text corresponding to :attr:`errno` (a string)."""
        return os.strerror(self.errno)
