# vim: fileencoding=utf-8

# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: April 7, 2016
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
from humanfriendly import Spinner, Timer, format
from property_manager import PropertyManager, mutable_property, required_property, writable_property

# Define an alias for Unicode strings that's unambiguous
# whether we are running under Python 2 or Python 3.
try:
    # This will raise a NameError exception in Python 3.
    unicode
except NameError:
    # In Python 3 all strings are Unicode strings.
    unicode = str

# Semi-standard module versioning.
__version__ = '9.6.1'

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

DEFAULT_TIMEOUT = 10
"""The default timeout used to wait for process termination (number of seconds)."""

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


class ControllableProcess(PropertyManager):

    """
    Simple process control based on the :mod:`subprocess` module and/or process IDs.

    By creating a :class:`ControllableProcess` object with a :attr:`pid` or
    :attr:`subprocess` keyword argument you get a process control object that
    supports the :attr:`is_running` property and the :func:`terminate()`,
    :func:`kill()`, :func:`stop()` and :func:`cont()` methods.

    This class was created to decouple the primitives for process control from
    the :class:`ExternalCommand` class to make it easier to re-use these
    primitives in other contexts (like my Linux-specific proc_ package).

    .. _proc: http://proc.readthedocs.org/en/latest/
    """

    @mutable_property
    def pid(self):
        """
        The process ID of the child process (a number).

        If the :attr:`subprocess` property is set the value of :attr:`pid`
        defaults to the value of :attr:`subprocess.Popen.pid`, otherwise the
        default value is :data:`None`.
        """
        return self.subprocess.pid if self.subprocess else None

    @mutable_property
    def subprocess(self):
        """A :class:`subprocess.Popen` object or :data:`None`."""

    @mutable_property
    def command_line(self):
        """
        The command line used to start the process (a list of strings).

        The only reason why :class:`ControllableProcess` needs to know about
        command lines is to enable (optional) human friendly logging in methods
        like :func:`terminate()` and :func:`kill()` (see :func:`__str__()`).
        """
        return []

    @mutable_property
    def logger(self):
        """
        The :class:`logging.Logger` object to use.

        If you are using Python's :mod:`logging` module and you find it
        confusing that command/process management information is logged under
        the :mod:`executor` name space instead of the name space of the
        application or library you can set this attribute to inject a custom
        (and more appropriate) logger.
        """
        return logger

    @property
    def is_running(self):
        """
        Whether the process is currently running.

        The value if this property is :data:`True` when the process is running
        or :data:`False` otherwise (whether the process hasn't been started yet
        or has already finished). This property has two implementations (listed
        by order of preference):

        1. If :attr:`subprocess` is available :func:`~subprocess.Popen.poll()`
           is used to determine whether the process is currently running. The
           advantage of this approach is that it works on UNIX and Windows
           systems alike. A disadvantage of this approach is that the current
           process by definition needs to be a parent of the process in
           question.

        2. If :attr:`pid` is available the signal number zero is sent to the
           process with that process ID and the result is used to infer whether
           the process is alive or not (this technique is documented in `man
           kill`_):

           - If the sending of the signal doesn't raise an exception the
             process received the signal just fine and so must it exist.

           - If an :exc:`~exceptions.OSError` exception with error number
             :data:`~errno.EPERM` is raised we don't have permission to signal
             the process, which implies that the process is alive.

           - If an :exc:`~exceptions.OSError` exception with error number
             :data:`~errno.ESRCH` is raised we know that no process with the
             given id exists.

           An advantage of this approach (on UNIX systems) is that you don't
           need to be a parent of the process in question. A disadvantage of
           this approach is that it is never going to work on Windows (if
           you're serious about portability consider using a package like
           psutil_).

           .. warning:: After a process has been terminated but before the
                        parent process has reclaimed its child process this
                        property returns :data:`True`. Usually this is a small
                        time window, but when it isn't it can be really
                        confusing.

        .. _man kill: http://linux.die.net/man/2/kill
        .. _psutil: https://pypi.python.org/pypi/psutil
        """
        if self.subprocess:
            # If we have a subprocess.Popen object we can poll it
            # to check whether the child process is still alive.
            logger.debug("Polling process status using subprocess module ..")
            return self.subprocess.poll() is None
        elif self.pid:
            # Querying in-use process IDs is a platform specific operation that
            # Python doesn't provide, however sending the signal number zero is
            # a platform specific trick that works on most UNIX systems.
            logger.debug("Polling process status using signal 0 ..")
            try:
                os.kill(self.pid, 0)
                # If no exception is raised we successfully sent a NOOP signal
                # to the process so we know the process is (still) alive.
                logger.debug("Successfully sent signal 0, process must be alive.")
                return True
            except OSError as e:
                if e.errno == errno.EPERM:
                    # If we don't have permission this confirms that the
                    # process ID is in use.
                    logger.debug("Got EPERM, process must be alive.")
                    return True
                elif e.errno == errno.ESRCH:
                    # If we get this error we know the process doesn't exist.
                    logger.debug("Got ESRCH, process can't be alive.")
                    return False
                else:
                    # Don't swallow exceptions we can't handle.
                    raise
        else:
            # If there's no process information it can't be running ;-).
            logger.debug("Can't check if process is running! (no process information available)")
            return False

    def terminate(self, wait=True, timeout=DEFAULT_TIMEOUT):
        """
        Gracefully terminate the process.

        :param wait: Whether to wait for the process to end (a boolean,
                     defaults to :data:`True`).
        :param timeout: The number of seconds to wait for the process to
                        terminate after we've signaled it (defaults to
                        :data:`DEFAULT_TIMEOUT`). Zero means to wait
                        indefinitely.
        :returns: :data:`True` if the process was terminated, :data:`False`
                  otherwise (a warning will be logged if the process isn't
                  running). Please note that if `wait` is :data:`False` the
                  return value may be unreliable due to race conditions.
        :raises: :exc:`~exceptions.TypeError` when :attr:`pid` isn't available,
                 :exc:`~exceptions.OSError` when a signal can't be delivered
                 and any exceptions raised by the :mod:`subprocess` module.

        This method works as follows:

        1. If :attr:`subprocess` is available :func:`subprocess.Popen.terminate()`
           is called (this works on Windows and UNIX alike), otherwise :attr:`pid`
           is used to send SIGTERM_ to the process (this only works on UNIX).

           Processes can choose to intercept termination signals to allow for
           graceful termination (many daemon processes work like this) however
           the default action is to simply exit immediately.

        2. If `wait` is :data:`True` and we've signaled the process we wait for
           it to terminate gracefully or `timeout` seconds have passed
           (whichever comes first).

        3. If `wait` is :data:`True` and the process is still running at this
           point it will be forcefully terminated using :func:`kill()`.

        .. _SIGTERM: http://en.wikipedia.org/wiki/Unix_signal#SIGTERM
        """
        if self.is_running:
            self.logger.info("Gracefully terminating process %s ..", self)
            # Signal the process to terminate gracefully.
            if self.subprocess:
                logger.debug("Terminating process using subprocess module ..")
                self.subprocess.terminate()
            else:
                logger.debug("Terminating process by sending SIGTERM ..")
                os.kill(self.pid, signal.SIGTERM)
            # Block until the process ends or the timeout expires?
            if wait:
                timer = self.wait_for_process(timeout)
                if self.is_running:
                    self.logger.warning("Failed to gracefully terminate process! (it's still running)")
                    # Fall back to forcefully terminating the process.
                    return self.kill(wait=True, timeout=timeout)
                else:
                    self.logger.info("Took %s to gracefully terminate process.", timer)
                    return True
            return not self.is_running
        else:
            self.logger.warning("Ignoring graceful termination request (process isn't running).")
            return False

    def kill(self, wait=True, timeout=DEFAULT_TIMEOUT):
        """
        Forcefully terminate the process.

        :param wait: Whether to wait for the process to end (a boolean,
                     defaults to :data:`True`).
        :param timeout: The number of seconds to wait for the process to
                        terminate after we've signaled it (defaults to
                        :data:`DEFAULT_TIMEOUT`). Zero means to wait
                        indefinitely.
        :returns: :data:`True` if the process was terminated, :data:`False`
                  otherwise (a warning will be logged if the process isn't
                  running). Please note that if `wait` is :data:`False` the
                  return value may be unreliable due to race conditions.
        :raises: :exc:`~exceptions.TypeError` when :attr:`pid` isn't available,
                 :exc:`~exceptions.OSError` when a signal can't be delivered
                 and any exceptions raised by the :mod:`subprocess` module.

        If :attr:`subprocess` is available :func:`subprocess.Popen.kill()` is
        called (this works on Windows and UNIX alike), otherwise :attr:`pid` is
        used to send SIGKILL_ to the process (this only works on UNIX).

        The SIGKILL_ signal cannot be intercepted or ignored and causes the
        immediate termination of the process (under regular circumstances).
        Non-regular circumstances are things like blocking I/O calls on an NFS
        share while your file server is down (fun times!).

        .. _SIGKILL: http://en.wikipedia.org/wiki/Unix_signal#SIGKILL
        """
        if self.is_running:
            self.logger.info("Forcefully terminating process %s ..", self)
            # Signal the process to terminate forcefully.
            if self.subprocess:
                logger.debug("Terminating process using subprocess module ..")
                self.subprocess.kill()
            else:
                logger.debug("Terminating process by sending SIGKILL ..")
                os.kill(self.pid, signal.SIGKILL)
            # Block until the process ends or the timeout expires?
            if wait:
                timer = self.wait_for_process(timeout)
                if self.is_running:
                    self.logger.warning("Failed to forcefully terminate process!")
                    return False
                else:
                    self.logger.info("Took %s to forcefully terminate process.", timer)
                    return True
            return not self.is_running
        else:
            self.logger.warning("Ignoring forceful termination request (process isn't running).")
            return False

    def wait_for_process(self, timeout=0):
        """
        Wait until the current process ends or the timeout expires.

        :param timeout: The number of seconds to wait for the process to
                        terminate after we've signaled it (defaults to zero
                        which means we wait indefinitely).
        :returns: A :class:`~humanfriendly.Timer` object telling you how long
                  it took to wait for the process.

        This method renders an interactive spinner on the terminal using
        :class:`~humanfriendly.Spinner` to explain to the user what they are
        waiting for.
        """
        timer = Timer()
        with Spinner(timer=timer) as spinner:
            while self.is_running:
                if timeout and timer.elapsed_time >= timeout:
                    break
                spinner.step(label="Waiting for process %i to terminate" % self.pid)
                spinner.sleep()
        return timer

    def suspend(self):
        """
        Suspend a process so that its execution can be resumed later.

        :returns: :data:`True` if the process was stopped, :data:`False`
                  otherwise (a warning will be logged if the process isn't
                  running).
        :raises: :exc:`~exceptions.TypeError` when :attr:`pid` isn't available
                 or :exc:`~exceptions.OSError` when the signal can't be
                 delivered.

        The :func:`suspend()` method sends a SIGSTOP_ signal to the process.
        This signal cannot be intercepted or ignored and has the effect of
        completely pausing the process until you call :func:`resume()`.
        This functionality is only available on UNIX systems.

        .. _SIGSTOP: http://en.wikipedia.org/wiki/Unix_signal#SIGSTOP
        """
        if self.is_running:
            self.logger.info("Suspending process %s using SIGSTOP ..", self)
            os.kill(self.pid, signal.SIGSTOP)
            return True
        else:
            self.logger.warning("Process isn't running! (ignoring SIGSTOP request)")
            return False

    def resume(self):
        """
        Resume a process that was previously paused using :func:`suspend()`.

        :returns: :data:`True` if the process was continued, :data:`False`
                  otherwise (a warning will be logged if the process isn't
                  running).
        :raises: :exc:`~exceptions.TypeError` when :attr:`pid` isn't available
                 or :exc:`~exceptions.OSError` when the signal can't be
                 delivered.

        The :func:`resume()` method sends a SIGCONT_ signal to the process.
        This signal resumes a process that was previously paused using SIGSTOP_
        (e.g. using :func:`suspend()`). This functionality is only available on
        UNIX systems.

        .. _SIGCONT: http://en.wikipedia.org/wiki/Unix_signal#SIGCONT
        """
        if self.is_running:
            self.logger.info("Resuming process %s using SIGCONT ..", self)
            os.kill(self.pid, signal.SIGCONT)
            return True
        else:
            self.logger.warning("Process isn't running! (ignoring SIGCONT request)")
            return False

    def __str__(self):
        """
        Render a human friendly representation of a :class:`ControllableProcess` object.

        :returns: A string describing the process. Includes the process id and
                  command line (when available).
        """
        text = [str(self.pid)]
        if self.command_line:
            text.append("(%s)" % quote(self.command_line))
        return " ".join(text)


class ExternalCommand(ControllableProcess):

    """
    Programmer friendly :class:`subprocess.Popen` wrapper.

    The :class:`ExternalCommand` class wraps :class:`subprocess.Popen` to make
    it easier to do the right thing (the simplicity of :func:`os.system()` with
    the robustness of :class:`subprocess.Popen`) and to provide additional
    features (e.g. asynchronous command execution that preserves the ability to
    provide input and capture output).

    :class:`ExternalCommand` inherits from :class:`ControllableProcess` so all
    of the process manipulation supported by :class:`ControllableProcess` is
    also supported by :class:`ExternalCommand` objects.

    Because the :class:`ExternalCommand` class has a lot of properties and
    methods here is a summary:

    **Writable properties**
     The :attr:`async`, :attr:`callback`, :attr:`capture`,
     :attr:`capture_stderr`, :attr:`check`, :attr:`directory`,
     :attr:`encoding`, :attr:`environment`, :attr:`fakeroot`, :attr:`input`,
     :attr:`logger`, :attr:`merge_streams`, :attr:`shell`, :attr:`silent`,
     :attr:`stdout_file`, :attr:`stderr_file`, :attr:`uid`, :attr:`user`,
     :attr:`sudo` and :attr:`virtual_environment` properties allow you to
     configure how the external command will be run (before it is started).

    **Computed properties**
     The :attr:`command`, :attr:`command_line`, :attr:`decoded_stderr`,
     :attr:`decoded_stdout`, :attr:`encoded_input`, :attr:`error_message`,
     :attr:`error_type`, :attr:`failed`, :attr:`have_superuser_privileges`,
     :attr:`is_finished`, :attr:`is_running`, :attr:`is_terminated`,
     :attr:`output`, :attr:`result`, :attr:`returncode`, :attr:`stderr`,
     :attr:`stdout`, :attr:`succeeded` and :attr:`was_started` properties allow
     you to inspect if and how the external command was started, what its
     current status is and what its output is.

    **Public methods**
     The public methods :func:`start()`, :func:`wait()`, :func:`terminate()`
     and :func:`kill()` enable you to start external commands, wait for them to
     finish and terminate them if they take too long.

    **Internal methods**
     The internal methods :func:`check_errors()`, :func:`load_output()` and
     :func:`cleanup()` are used by :func:`start()`, :func:`wait()` and
     :func:`terminate()` so unless you're reimplementing one of those methods
     you probably don't need these internal methods.

    **Context manager**
      :class:`ExternalCommand` objects can be used as context managers by using
      the :keyword:`with` statement:

      - When the scope of the :keyword:`with` statement starts the
        :func:`start()` method is called (if the external command
        isn't already running).
      - When the scope of the :keyword:`with` statement ends
        :func:`terminate()` is called if the command is still running. The
        :func:`load_output()` and :func:`cleanup()` functions are used to
        cleanup after the external command. If an exception isn't already being
        raised :func:`check_errors()` is called to make sure the external
        command succeeded.
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
                        :attr:`logger`, :attr:`merge_streams`, :attr:`shell`,
                        :attr:`silent`, :attr:`stdout_file`,
                        :attr:`stderr_file`, :attr:`uid`, :attr:`user`,
                        :attr:`sudo` and :attr:`virtual_environment`.Any other
                        keyword argument will raise :exc:`TypeError` as
                        usual.

        The external command is not started until you call :func:`start()` or
        :func:`wait()`.
        """
        # Store the command and its arguments but make it possible for
        # subclasses to redefine whether `command' is a required property.
        if command:
            self.command = list(command)
        # Set properties based on keyword arguments.
        super(ExternalCommand, self).__init__(**options)
        # Initialize instance variables.
        self.null_device = None
        self.stdin_stream = CachedStream('stdin')
        self.stdout_stream = CachedStream('stdout')
        self.stderr_stream = CachedStream('stderr')

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

    @required_property
    def command(self):
        """A list of strings with the command to execute."""
        # We specifically return None so that __init__() will raise a
        # TypeError exception because no command has been specified.
        return None

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
        # Apply the `shell' and/or `virtual_environment' options.
        if self.virtual_environment:
            # Prepare to execute the command inside a Python virtual environment.
            activate_script = os.path.join(self.virtual_environment, 'bin', 'activate')
            if self.shell:
                shell_command = 'source %s && %s' % (quote(activate_script), command_line[0])
                command_line = [DEFAULT_SHELL, '-c', shell_command] + command_line[1:]
            else:
                shell_command = 'source %s && %s' % (quote(activate_script), quote(command_line))
                command_line = [DEFAULT_SHELL, '-c', shell_command]
        elif self.shell:
            # Prepare to execute a shell command.
            command_line = [DEFAULT_SHELL, '-c'] + command_line
        # Run the command under `fakeroot' to fake super user privileges?
        if self.fakeroot:
            command_line = ['fakeroot'] + command_line
        # Run the command under `sudo' to enable super user privileges? (only if necessary)
        if self.sudo and not self.have_superuser_privileges:
            command_line = ['sudo'] + command_line
        # Apply the `uid' or `user' options.
        if self.uid is not None:
            # Run the command under a different user ID.
            command_line = ['sudo', '-u', '#%i' % self.uid] + command_line
        elif self.user is not None:
            # Run the command under a different username.
            command_line = ['sudo', '-u', self.user] + command_line
        return command_line

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

    @mutable_property
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
        run with ``fakeroot``. If the ``fakeroot`` program is not installed a
        fall back to ``sudo`` is performed.

        .. _superuser privileges: http://en.wikipedia.org/wiki/Superuser#Unix_and_Unix-like
        """
        return False

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
        return self.error_type is not None or self.returncode is not None

    @property
    def is_terminated(self):
        """
        Whether the external command has been terminated.

        :data:`True` if the external command was terminated using
        :data:`signal.SIGTERM` (e.g. by :func:`terminate()`),
        :data:`False` otherwise.
        """
        return abs(self.returncode) == signal.SIGTERM if self.returncode and self.returncode < 0 else False

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

    @property
    def returncode(self):
        """
        The return code of the external command (an integer).

        When the external command hasn't finished yet :data:`None` is
        returned.
        """
        return self.subprocess.poll() if self.subprocess else None

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
        if self.is_finished:
            return self.returncode == 0
        else:
            return None

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
        return None

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
        return None

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
        return self.error_type is not None or self.subprocess is not None

    def start(self):
        """
        Start execution of the external command.

        :raises: :exc:`ExternalCommandFailed` when :attr:`~ExternalCommand.check` is
                 :data:`True`, :attr:`async` is :data:`False` and the external
                 command exits with a nonzero status code.

        This method instantiates a :class:`subprocess.Popen` object based on
        the defaults defined by :class:`ExternalCommand` and the overrides
        configured by the caller. What happens then depends on :attr:`async`:

        - If :attr:`async` is set :func:`start()` starts the external command
          but doesn't wait for it to end (use :func:`wait()` for that).

        - If :attr:`async` isn't set :func:`subprocess.Popen.communicate()` is
          used to synchronously execute the external command.
        """
        # Prepare the keyword arguments to subprocess.Popen().
        kw = dict(args=self.command_line,
                  cwd=self.directory,
                  env=os.environ.copy())
        kw['env'].update(self.environment)
        # Prepare the input.
        if self.input is not None:
            if self.async:
                self.stdin_stream.prepare_input(self.encoded_input)
                kw['stdin'] = self.stdin_stream.fd
            else:
                kw['stdin'] = subprocess.PIPE
        # Prepare to capture the standard output and/or error stream(s).
        kw['stdout'] = self.stdout_stream.prepare_output(self.stdout_file, self.capture, self.async)
        # Make it possible to merge stderr into stdout.
        kw['stderr'] = (subprocess.STDOUT if self.merge_streams else
                        self.stderr_stream.prepare_output(self.stderr_file, self.capture_stderr, self.async))
        # Silence the standard output and/or error stream(s)?
        if self.silent and any(kw.get(n) is None for n in ('stdout', 'stderr')):
            if self.null_device is None:
                self.null_device = open(os.devnull, 'wb')
            kw['stdout'] = self.null_device if kw['stdout'] is None else kw['stdout']
            kw['stderr'] = self.null_device if kw['stderr'] is None else kw['stderr']
        # Create the subprocess object.
        self.logger.debug("Executing external command: %s", quote(kw['args']))
        # Clear previous values (if any).
        delattr(self, 'error_type')
        self.subprocess = None
        try:
            self.subprocess = subprocess.Popen(**kw)
        except OSError as e:
            if e.errno in COMMAND_NOT_FOUND_CODES:
                # Enable uniform error handling.
                self.error_type = CommandNotFound
            else:
                # Don't swallow exceptions we can't handle.
                raise
        # Synchronously wait for the external command to end?
        if not self.async:
            # Feed the external command its input, capture the external
            # command's output, cleanup resources and check for errors.
            if self.subprocess:
                stdout, stderr = self.subprocess.communicate(input=self.encoded_input)
                self.stdout_stream.override(stdout)
                self.stderr_stream.override(stderr)
            self.wait()

    def wait(self, check=None):
        """
        Wait for the external command to finish.

        :param check: Override the value of :attr:`check` for the duration of
                      this call to :func:`wait()`. Defaults to :data:`None`
                      which means :attr:`check` is not overridden.
        :raises: :exc:`ExternalCommandFailed` when :attr:`check` is
                 :data:`True`, :attr:`async` is :data:`True` and the external
                 command exits with a nonzero status code.

        The :func:`wait()` function is only useful when :attr:`async` is
        :data:`True`, it performs the following steps:

        1. If :attr:`was_started` is :data:`False` :func:`start()` is called.
        2. If :attr:`is_finished` is :data:`False` :func:`subprocess.Popen.wait()`
           is called to wait for the external command to end.
        3. :func:`load_output()` is called (in case the caller enabled output
           capturing).
        4. :func:`cleanup()` is called to clean up temporary resources after
           the external command has ended.
        5. Finally :func:`check_errors()` is called (in case the caller
           didn't disable :attr:`check`).
        """
        if not self.was_started:
            self.start()
        if self.was_started and not self.is_finished:
            self.subprocess.wait()
        self.load_output()
        self.cleanup()
        self.check_errors(check=check)

    def terminate(self, *args, **kw):
        """
        Gracefully terminate the external command.

        Please refer to :func:`ControllableProcess.terminate()` for
        documentation about this method's parameters and return value. After
        :func:`ControllableProcess.terminate()` successfully terminates the
        external command this method does two more things:

        - It sets :attr:`check` to :data:`False`. The idea here is that if you
          consciously terminate a command you don't need to be bothered with an
          exception telling you that you succeeded :-).

        - It calls :func:`wait()` so that the command's output is loaded and
          temporary resources are cleaned up.
        """
        if super(ExternalCommand, self).terminate(*args, **kw):
            self.wait(check=False)
            self.check = False
            return True
        else:
            return False

    def kill(self, *args, **kw):
        """
        Forcefully terminate the external command.

        Please refer to :func:`ControllableProcess.kill()` for documentation
        about this method's parameters and return value.

        After :func:`ControllableProcess.kill()` successfully terminates the
        external command this method does two more things:

        - It sets :attr:`check` to :data:`False`. The idea here is that if you
          consciously terminate a command you don't need to be bothered with an
          exception telling you that you succeeded :-).

        - It calls :func:`wait()` so that the command's output is loaded and
          temporary resources are cleaned up.
        """
        if super(ExternalCommand, self).kill(*args, **kw):
            self.wait(check=False)
            self.check = False
            return True
        else:
            return False

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
        Clean up temporary resources after the external command has ended.

        This internal method is used by :func:`start()` and :func:`wait()` to
        clean up the temporary files that store the external command's input
        and output and to close the file handle to :data:`os.devnull`.
        """
        self.stdin_stream.cleanup()
        self.stdout_stream.cleanup()
        self.stderr_stream.cleanup()
        if self.null_device:
            self.null_device.close()
            self.null_device = None

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
        :func:`terminate()`), cleans up (using :func:`cleanup()`) and checks
        for errors (using :func:`check_errors()`, only if an exception is not
        already being handled).
        """
        if self.was_started:
            if self.is_running:
                self.terminate()
            self.load_output()
            self.cleanup()
            if exc_type is None:
                # Check for external command errors only when not already
                # handling an exception.
                self.check_errors()


class CachedStream(object):

    """Manages a temporary file with input for / output from an external command."""

    def __init__(self, kind):
        """
        Initialize a :class:`CachedStream` object.

        :param kind: A simple (alphanumeric) string with the name of the stream.
        """
        self.cached_output = None
        self.fd = None
        self.filename = None
        self.is_temporary_file = False
        self.kind = kind

    def prepare_temporary_file(self):
        """Prepare the stream's temporary file."""
        if not (self.fd and self.filename):
            self.is_temporary_file = True
            self.fd, self.filename = tempfile.mkstemp(prefix='executor-', suffix='-%s.txt' % self.kind)
            logger.debug("Connected %s stream to temporary file %s ..", self.kind, self.filename)

    def prepare_input(self, contents=None):
        """
        Initialize an asynchronous input stream (using a temporary file).

        :param contents: If you pass this argument the given string will be
                         written to the temporary file.
        """
        if contents is not None:
            self.prepare_temporary_file()
            with open(self.filename, 'wb') as handle:
                handle.write(contents)

    def prepare_output(self, file, capture, async):
        """
        Initialize an (asynchronous) output stream.

        :param file: A file handle or :data:`None`.
        :param capture: :data:`True` if capturing is enabled, :data:`False` otherwise.
        :param async: :data:`True` for asynchronous execution, :data:`False` otherwise.
        :returns: A file descriptor, :data:`subprocess.PIPE` or :data:`None`.
        """
        if file is not None:
            # Capture the stream to a user defined file.
            self.redirect(file)
            return self.fd
        elif capture:
            if async:
                # Capture the stream to a temporary file.
                self.prepare_temporary_file()
                return self.fd
            else:
                # Capture the stream in memory.
                return subprocess.PIPE

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

        :returns: The output of the stream (a string) or :data:`None` when
                  :func:`prepare()` was never called.
        """
        if self.filename and os.path.isfile(self.filename):
            with open(self.filename, 'rb') as handle:
                self.cached_output = handle.read()
        return self.cached_output

    def override(self, output):
        """
        Override the value returned by :func:`load()`.

        :param output: The value to return as the stream's content.
        """
        self.cleanup()
        self.cached_output = output

    def cleanup(self):
        """Cleanup the temporary file."""
        if self.filename and self.is_temporary_file:
            if os.path.isfile(self.filename):
                os.unlink(self.filename)
            self.is_temporary_file = False
            self.filename = None


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


class ExternalCommandFailed(Exception, PropertyManager):

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
        :param kw: Keyword arguments are passed on to :func:`.PropertyManager.__init__()`.
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
