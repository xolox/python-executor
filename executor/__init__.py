# vim: fileencoding=utf-8

# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 2, 2015
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
import logging
import os
import pipes
import signal
import subprocess
import tempfile

# Modules included in our package.
from executor.compat import str
from executor.property_manager import (
    mutable_property,
    PropertyManager,
    required_property,
)

# Semi-standard module versioning.
__version__ = '4.5'

# Initialize a logger.
logger = logging.getLogger(__name__)

DEFAULT_ENCODING = 'UTF-8'
"""The default encoding of the standard input, output and error streams (a string)."""

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

DEFAULT_WORKING_DIRECTORY = os.curdir
"""
The default working directory for external commands (a string). Defaults to the
working directory of the current process using :data:`os.curdir`.
"""


def execute(*command, **options):
    """
    Execute an external command and make sure it succeeded.

    :param command: All positional arguments are passed on to the constructor
                    of :class:`ExternalCommand`.
    :param options: All keyword arguments are passed on to the constructor of
                    :class:`ExternalCommand`.
    :returns: The return value of this function depends on two options:

              ==============================  ================================  =================================
              :attr:`~ExternalCommand.async`  :attr:`~ExternalCommand.capture`  Return value
              ==============================  ================================  =================================
              :data:`False`                   :data:`False`                     :attr:`ExternalCommand.succeeded`
              :data:`False`                   :data:`True`                      :attr:`ExternalCommand.output`
              :data:`True`                    :data:`True`                      :class:`ExternalCommand` object
              :data:`True`                    :data:`False`                     :class:`ExternalCommand` object
              ==============================  ================================  =================================
    :raises: :exc:`ExternalCommandFailed` when the command exits with a
             nonzero exit code (unless :attr:`~ExternalCommand.capture` is
             :data:`False`).

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

    If an external command exits with a nonzero status code an exception is raised,
    this makes it easy to do the right thing (never forget to check the status code
    of an external command without having to write a lot of repetitive code):

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

    The exceptions raised by :func:`execute()` expose
    :attr:`~ExternalCommandFailed.command` and
    :attr:`~ExternalCommandFailed.returncode` attributes. If you know a command
    is likely to exit with a nonzero status code and you want
    :func:`execute()` to simply return a boolean you can do this instead:

    >>> execute('false', check=False)
    False
    """
    cmd = ExternalCommand(*command, **options)
    if cmd.async:
        cmd.start()
        return cmd
    else:
        cmd.start()
        cmd.wait()
        return cmd.output if cmd.capture else cmd.succeeded


class ExternalCommand(PropertyManager):

    """
    Programmer friendly :class:`subprocess.Popen` wrapper.

    The :class:`ExternalCommand` class wraps :class:`subprocess.Popen` to make
    it easier to do the right thing (the simplicity of :func:`os.system()` with
    the robustness of :class:`subprocess.Popen`) and to provide additional
    features (e.g. asynchronous command execution that preserves the ability to
    provide input and capture output).

    Because the :class:`ExternalCommand` class has a lot of properties and
    methods here is a summary:

    **Writable properties**
     The :attr:`async`, :attr:`capture`, :attr:`capture_stderr`, :attr:`check`,
     :attr:`directory`, :attr:`encoding`, :attr:`environment`,
     :attr:`fakeroot`, :attr:`input`, :attr:`logger`, :attr:`merge_streams`,
     :attr:`silent`, :attr:`stdout_file`, :attr:`stderr_file` and :attr:`sudo`
     properties allow you to configure how the external command will be run
     (before it is started).

    **Computed properties**
     The :attr:`command`, :attr:`command_line`, :attr:`decoded_stderr`,
     :attr:`decoded_stdout`, :attr:`encoded_input`, :attr:`error_message`,
     :attr:`error_type`, :attr:`failed`, :attr:`have_superuser_privileges`,
     :attr:`is_finished`, :attr:`is_running`, :attr:`is_terminated`,
     :attr:`output`, :attr:`returncode`, :attr:`stderr`, :attr:`stdout`,
     :attr:`succeeded` and :attr:`was_started` properties allow you to inspect
     if and how the external command was started, what its current status is
     and what its output is.

    **Public methods**
     The public methods :func:`start()`, :func:`wait()` and :func:`terminate()`
     enable you to start external commands, wait for them to finish and
     terminate them if they take too long.

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
        Construct an :class:`ExternalCommand` object.

        :param command: Any positional arguments are converted to a list and
                        used to set :attr:`command`.
        :param options: Keyword arguments can be used to conveniently override
                        the default values of :attr:`async`, :attr:`capture`,
                        :attr:`check`, :attr:`directory`, :attr:`encoding`,
                        :attr:`environment`, :attr:`fakeroot`, :attr:`input`,
                        :attr:`logger`, :attr:`silent` and :attr:`sudo`. Any
                        other keyword argument will raise :exc:`TypeError` as
                        usual.

        The external command is not started until you call :func:`start()` or
        :func:`wait()`.
        """
        # Store the command and its arguments.
        command = list(command)
        if not command:
            raise TypeError("Please provide a command to execute!")
        self.command = command
        # Set properties based on keyword arguments.
        super(ExternalCommand, self).__init__(**options)
        # Initialize instance variables.
        self.null_device = None
        self.stdin_stream = CachedStream('stdin')
        self.stdout_stream = CachedStream('stdout')
        self.stderr_stream = CachedStream('stderr')
        self.subprocess = None

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
        """
        return False

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

    @property
    def command_line(self):
        """
        The command line of the external command.

        The command line used to actually run the external command requested by
        the user (a list of strings). The command line is constructed based on
        :attr:`command` according to the following rules:

        - If :attr:`command` contains a single string it is assumed to be a
          shell command and run using ``bash -c '...'`` (assuming you haven't
          changed :data:`DEFAULT_SHELL`) which means constructs like
          semicolons, ampersands and pipes can be used (and all the usual
          caveats apply :-).

        - If :attr:`fakeroot` or :attr:`sudo` is set the respective command
          name may be prefixed to the command line generated here.
        """
        command_line = list(self.command)
        if len(command_line) == 1:
            command_line = [DEFAULT_SHELL, '-c'] + command_line
        if (self.fakeroot or self.sudo) and not self.have_superuser_privileges:
            if self.sudo:
                # Superuser privileges requested by caller.
                command_line = ['sudo'] + command_line
            elif self.fakeroot and which('fakeroot'):
                # fakeroot requested by caller and available.
                command_line = ['fakeroot'] + command_line
            else:
                # fakeroot requested by caller but not available.
                command_line = ['sudo'] + command_line
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
                if isinstance(self.input, str)
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

    @property
    def error_message(self):
        """A string describing how the external command failed or :data:`None`."""
        if self.error_type is ExternalCommandFailed:
            text = "External command failed with exit code %s! (command: %s)"
            return text % (self.returncode, quote(self.command_line))

    @property
    def error_type(self):
        """:exc:`ExternalCommandFailed` when :attr:`returncode` is a nonzero number, :data:`None` otherwise."""
        if self.is_finished and self.failed:
            return ExternalCommandFailed

    @property
    def failed(self):
        """
        Whether the external command has failed.

        :data:`True` if :attr:`returncode` is a nonzero number, :data:`False`
        if :attr:`returncode` is zero, :data:`None` when the external command
        hasn't been started or is still running.
        """
        return (not self.succeeded) if self.is_finished else None

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
        return self.subprocess.poll() is not None if self.subprocess else False

    @property
    def is_running(self):
        """
        Whether the external command is currently running.

        :data:`True` while the external command is running, :data:`False` when
        the external command hasn't been started yet or has already finished.
        """
        return self.subprocess.poll() is None if self.subprocess else False

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
    def logger(self):
        """
        The :class:`logging.Logger` object to use.

        If you are using Python's :mod:`logging` module and you find it
        confusing that external command execution is logged under the
        :mod:`executor` name space instead of the name space of the application
        or library using :mod:`executor` you can set this attribute to inject
        a custom (and more appropriate) logger.
        """
        return logger

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
    def returncode(self):
        """
        The return code of the external command (an integer).

        When the external command hasn't finished yet :data:`None` is
        returned.
        """
        return self.subprocess.poll() if self.subprocess else None

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

        :data:`True` if :attr:`returncode` is zero, :data:`False` if
        :attr:`returncode` is a nonzero number, :data:`None` when the external
        command hasn't been started or is still running.
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
        """
        return False

    @property
    def was_started(self):
        """
        Whether the external command has already been started.

        :data:`True` once :func:`start()` has been called to start executing
        the external command, :data:`False` when :func:`start()` hasn't been
        called yet.
        """
        return self.subprocess is not None

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
                self.stdin_stream.prepare(self.encoded_input)
                kw['stdin'] = self.stdin_stream.fd
            else:
                kw['stdin'] = subprocess.PIPE
        # Silence the standard output and error streams?
        if self.silent:
            if self.null_device is None:
                self.null_device = open(os.devnull, 'wb')
            kw['stdout'] = self.null_device
            kw['stderr'] = self.null_device
        # Prepare to capture the standard output stream.
        if self.stdout_file:
            self.stdout_stream.redirect(self.stdout_file)
            kw['stdout'] = self.stdout_stream.fd
        elif self.capture:
            if self.async:
                self.stdout_stream.prepare()
                kw['stdout'] = self.stdout_stream.fd
            else:
                kw['stdout'] = subprocess.PIPE
        # Make it possible to merge stderr into stdout.
        if self.merge_streams:
            kw['stderr'] = subprocess.STDOUT
        elif self.stderr_file:
            self.stderr_stream.redirect(self.stderr_file)
            kw['stderr'] = self.stderr_stream.fd
        elif self.capture_stderr:
            # Prepare to capture the standard error stream.
            if self.async:
                self.stderr_stream.prepare()
                kw['stderr'] = self.stderr_stream.fd
            else:
                kw['stderr'] = subprocess.PIPE
        # Construct the subprocess object.
        self.logger.debug("Executing external command: %s", quote(kw['args']))
        self.subprocess = subprocess.Popen(**kw)
        # Synchronously wait for the external command to end?
        if not self.async:
            # Feed the external command its input, capture the external
            # command's output, cleanup resources and check for errors.
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
        if not self.is_finished:
            self.subprocess.wait()
        self.load_output()
        self.cleanup()
        self.check_errors(check=check)

    def terminate(self):
        """
        Terminate a running process.

        Uses the :func:`subprocess.Popen.terminate()` function. Calls
        :func:`wait()` after terminating the process so that the external
        command's output is loaded and temporary resources are cleaned up. The
        value of :attr:`check` is overridden to :data:`False` during the call
        to :func:`terminate()` (if you're terminating an external command you
        know the return code isn't going to be zero so there's no point in
        raising an exception about it).
        """
        if self.is_running:
            self.logger.debug("Terminating external command: %s", quote(self.command_line))
            self.subprocess.terminate()
            self.wait(check=False)

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
        """Start the external command if it hasn't already been started."""
        if not self.was_started:
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

    def prepare(self, contents=None):
        """
        Initialize the temporary file (and write the given string to it).

        :param contents: If you pass this argument the given string will be
                         written to the temporary file.
        """
        if not (self.fd and self.filename):
            self.is_temporary_file = True
            self.fd, self.filename = tempfile.mkstemp(prefix='executor-', suffix='-%s.txt' % self.kind)
            logger.debug("Connected %s stream to temporary file %s ..", self.kind, self.filename)
        if contents is not None:
            with open(self.filename, 'wb') as handle:
                handle.write(contents)

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


def which(program):
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
    for directory in os.environ['PATH'].split(':'):
        pathname = os.path.join(directory, program)
        if os.access(pathname, os.X_OK):
            matches.append(pathname)
    return matches


class ExternalCommandFailed(Exception):

    """
    Raised when an external command exits with a nonzero status code.

    This exception is raised by :func:`execute()`,
    :func:`~ExternalCommand.start()` and :func:`~ExternalCommand.wait()` when
    an external command exits with a nonzero status code. Exposes the following
    attributes:

    .. attribute:: command

       The :class:`ExternalCommand` object.
    """

    def __init__(self, command):
        """
        Initialize an :class:`ExternalCommandFailed` object.

        :param command: The :class:`ExternalCommand` object.
        """
        self.command = command
        super(ExternalCommandFailed, self).__init__(command.error_message)

    @property
    def returncode(self):
        """Shortcut for :attr:`ExternalCommand.returncode`."""
        return self.command.returncode

    @property
    def error_message(self):
        """Shortcut for :attr:`ExternalCommand.error_message`."""
        return self.command.error_message
