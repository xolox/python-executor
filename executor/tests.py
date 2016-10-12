# Automated tests for the `executor' module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 12, 2016
# URL: https://executor.readthedocs.org

"""
Automated tests for the `executor` package.

This test suite uses ``sudo`` in several tests. If you don't have passwordless
sudo configured you'll notice because you'll get interactive prompts when
running the test suite ...

Of course the idea behind a test suite is to run non-interactively, so in my
personal development environment I have added a custom sudo configuration file
``/etc/sudoers.d/executor-test-suite`` with the following contents::

    # /etc/sudoers.d/executor-test-suite:
    #
    # Configuration for sudo to run the executor test suite
    # without getting interactive sudo prompts.

    # To enable test_sudo_option.
    peter ALL=NOPASSWD:/bin/chmod 600 /tmp/executor-test-suite/*
    peter ALL=NOPASSWD:/bin/chown root\:root /tmp/executor-test-suite/*
    peter ALL=NOPASSWD:/bin/rm -R /tmp/executor-test-suite
    peter ALL=NOPASSWD:/usr/bin/stat --format=%a /tmp/executor-test-suite/*
    peter ALL=NOPASSWD:/usr/bin/stat --format=%G /tmp/executor-test-suite/*
    peter ALL=NOPASSWD:/usr/bin/stat --format=%U /tmp/executor-test-suite/*

    # To enable test_uid_option and test_user_option. The ALL=(ALL) tokens allow
    # running the command as any user (because the test suite picks user names
    # and user IDs more or less at random).
    peter ALL=(ALL) NOPASSWD:/usr/bin/id *

If you want to use this, make sure you change the username and sanity check the
locations of the executables whose pathnames have been expanded in the sudo
configuration. Happy testing!

By the way none of this is relevant on e.g. Travis CI because in that
environment passwordless sudo access has been configured.
"""

# Standard library modules.
import datetime
import logging
import os
import pwd
import random
import shlex
import shutil
import socket
import sys
import tempfile
import time
import unittest
import uuid

# External dependencies.
import coloredlogs
from humanfriendly import Timer, compact, dedent
from humanfriendly.compat import StringIO

# Modules included in our package.
from executor import (
    DEFAULT_SHELL,
    CommandNotFound,
    ExternalCommand,
    ExternalCommandFailed,
    execute,
    quote,
    which,
)
from executor.cli import main
from executor.concurrent import CommandPool, CommandPoolFailed
from executor.contexts import LocalContext, RemoteContext, create_context
from executor.process import ProcessTerminationFailed
from executor.ssh.client import (
    DEFAULT_CONNECT_TIMEOUT,
    RemoteCommand,
    RemoteCommandFailed,
    RemoteCommandNotFound,
    RemoteConnectFailed,
    foreach,
    remote,
)
from executor.ssh.server import SSHServer

MISSING_COMMAND = 'a-program-name-that-no-one-would-ever-use'

# Initialize a logger for this module.
logger = logging.getLogger(__name__)


class ExecutorTestCase(unittest.TestCase):

    """Container for the `executor` test suite."""

    def setUp(self):
        """Set up logging to the terminal and initialize test directories."""
        # Enable very verbose logging to the terminal, for the current process
        # as well as child processes.
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)
        os.environ['COLOREDLOGS_LOG_LEVEL'] = 'DEBUG'
        # Create the directory where superuser privileges are tested.
        self.sudo_enabled_directory = os.path.join(tempfile.gettempdir(), 'executor-test-suite')
        if not os.path.isdir(self.sudo_enabled_directory):
            os.makedirs(self.sudo_enabled_directory)
        # Separate the name of the test method (printed by the superclass
        # and/or py.test without a newline at the end) from the first line of
        # logging output that the test method is likely going to generate.
        sys.stderr.write("\n")

    def assertRaises(self, type, callable, *args, **kw):
        """Replacement for :func:`unittest.TestCase.assertRaises()` that returns the exception."""
        try:
            callable(*args, **kw)
        except Exception as e:
            if isinstance(e, type):
                # Return the expected exception as a regular return value.
                return e
            else:
                # Don't swallow exceptions we can't handle.
                raise
        else:
            assert False, "Expected an exception to be raised!"

    def test_graceful_termination(self):
        """Test graceful termination of processes."""
        self.check_termination(method='terminate')

    def test_forceful_termination(self):
        """Test forceful termination of processes."""
        self.check_termination(method='kill')

    def test_graceful_to_forceful_fallback(self):
        """Test that graceful termination falls back to forceful termination."""
        timer = Timer()
        expected_lifetime = 60
        with NonGracefulCommand('sleep', str(expected_lifetime), check=False) as cmd:
            # Request graceful termination even though we know it will fail.
            cmd.terminate(timeout=1)
            # Verify that the process terminated even though our graceful
            # termination request was ignored.
            assert not cmd.is_running
            # Verify that the process actually terminated due to the fall back
            # and not because its expected life time simply ran out.
            assert timer.elapsed_time < expected_lifetime

    def test_process_termination_failure(self):
        """Test handling of forceful termination failures."""
        with NonForcefulCommand('sleep', '60', check=False) as cmd:
            # Request forceful termination even though we know it will fail.
            self.assertRaises(ProcessTerminationFailed, cmd.kill, timeout=1)
            # Verify that the process is indeed still running :-).
            assert cmd.is_running
            # Bypass the overrides to get rid of the process.
            ExternalCommand.terminate_helper(cmd)

    def check_termination(self, method):
        """Helper method for process termination tests."""
        with ExternalCommand('sleep', '60', check=False) as cmd:
            timer = Timer()
            # We use a positive but very low timeout so that all of the code
            # involved gets a chance to run, but without slowing us down.
            getattr(cmd, method)(timeout=0.1)
            # Gotcha: Call wait() so that the process (our own subprocess) is
            # reclaimed because until we do so proc.is_running will be True!
            cmd.wait()
            # Now we can verify our assertions.
            assert not cmd.is_running, "Child still running despite graceful termination request!"
            assert timer.elapsed_time < 10, "It look too long to terminate the child!"

    def test_program_searching(self):
        """Make sure which() works as expected."""
        assert which('python')
        assert not which(MISSING_COMMAND)

    def test_status_code_checking(self):
        """Make sure that status code handling is sane."""
        assert execute('true') is True
        assert execute('false', check=False) is False
        # Make sure execute('false') raises an exception.
        self.assertRaises(ExternalCommandFailed, execute, 'false')
        # Make sure execute('exit 42') raises an exception.
        e = self.assertRaises(ExternalCommandFailed, execute, 'exit 42')
        # Make sure the exception has the expected properties.
        self.assertEqual(e.command.command_line, ['bash', '-c', 'exit 42'])
        self.assertEqual(e.returncode, 42)
        # Make sure the CommandNotFound exception is raised consistently
        # regardless of the values of the `shell' and `async' options.
        for async in True, False:
            for shell in True, False:
                cmd = ExternalCommand(MISSING_COMMAND, async=async, shell=shell)
                self.assertRaises(CommandNotFound, cmd.wait)

    def test_shell_opt_out(self):
        """Test that callers can always opt out of shell evaluation."""
        # A command consisting of a single string implies shell evaluation but
        # you can change that default.
        assert DEFAULT_SHELL in ExternalCommand('echo 42').command_line
        assert DEFAULT_SHELL not in ExternalCommand('echo 42', shell=False).command_line
        # A command consisting of more than one string implies no shell
        # evaluation but you can change that default.
        assert DEFAULT_SHELL not in ExternalCommand('echo', '42').command_line
        assert DEFAULT_SHELL in ExternalCommand('echo', '42', shell=True).command_line
        # Confirm that opting out of shell evaluation really bypasses all shells.
        cmd = ExternalCommand(
            'echo this will never match an executable name',
            shell=False, check=False,
        )
        cmd.start()
        cmd.wait()
        assert cmd.error_type is CommandNotFound

    def test_commands_on_stdin(self):
        """Test that callers can opt in to shell evaluation for local commands given on standard input."""
        random_string = uuid.uuid4().hex
        output = execute(capture=True, shell=True, input='echo %s' % quote(random_string))
        assert output == random_string

    def test_remote_commands_on_stdin(self):
        """Test that callers can opt in to shell evaluation for remote commands given on standard input."""
        random_string = uuid.uuid4().hex
        with SSHServer() as server:
            output = remote('127.0.0.1',
                            capture=True, shell=True,
                            input='echo %s' % quote(random_string),
                            **server.client_options)
            assert output == random_string

    def test_stdin(self):
        """Make sure standard input can be provided to external commands."""
        assert execute('tr', 'a-z', 'A-Z', input='test', capture=True) == 'TEST'

    def test_stdout(self):
        """Make sure standard output of external commands can be captured."""
        assert execute('echo', 'this is a test', capture=True) == 'this is a test'
        assert execute('echo', '-e', r'line 1\nline 2', capture=True) == 'line 1\nline 2\n'
        # I don't know how to test for the effect of silent=True in a practical
        # way without creating the largest test in this test suite :-). The
        # least I can do is make sure the keyword argument is accepted and the
        # code runs without exceptions in supported environments.
        assert execute('echo', 'this is a test', silent=True) is True

    def test_stderr(self):
        """Make sure standard error of external commands can be captured."""
        stdout_value = 'this goes to standard output'
        stderr_value = 'and this goes to the standard error stream'
        shell_command = 'echo %s; echo %s >&2' % (stdout_value, stderr_value)
        cmd = ExternalCommand(shell_command, capture=True, capture_stderr=True)
        cmd.start()
        assert stdout_value in cmd.decoded_stdout
        assert stderr_value in cmd.decoded_stderr

    def test_merged_streams(self):
        """Make sure standard output/error of external commands can be captured together."""
        stdout_value = 'this goes to standard output'
        stderr_value = 'and this goes to the standard error stream'
        shell_command = 'echo %s; echo %s >&2' % (stdout_value, stderr_value)
        cmd = ExternalCommand(shell_command, capture=True, merge_streams=True)
        cmd.start()
        assert stdout_value in cmd.decoded_stdout
        assert stderr_value in cmd.decoded_stdout
        assert stdout_value not in (cmd.decoded_stderr or '')
        assert stderr_value not in (cmd.decoded_stderr or '')

    def test_stdout_to_file(self):
        """Make sure the standard output stream of external commands can be redirected and appended to a file."""
        fd, filename = tempfile.mkstemp(prefix='executor-', suffix='-stdout.txt')
        with open(filename, 'w') as handle:
            handle.write('existing contents\n')
        with open(filename, 'a') as handle:
            execute('echo appended output', stdout_file=handle)
        # Make sure the file was _not_ removed.
        assert os.path.isfile(filename)
        # Make sure the output was appended.
        with open(filename) as handle:
            lines = [line.strip() for line in handle]
        assert lines == ['existing contents', 'appended output']

    def test_stderr_to_file(self):
        """Make sure the standard error stream of external commands can be redirected and appended to a file."""
        fd, filename = tempfile.mkstemp(prefix='executor-', suffix='-stderr.txt')
        with open(filename, 'w') as handle:
            handle.write('existing contents\n')
        with open(filename, 'a') as handle:
            execute('echo appended output 1>&2', stderr_file=handle)
        # Make sure the file was _not_ removed.
        assert os.path.isfile(filename)
        # Make sure the output was appended.
        with open(filename) as handle:
            lines = [line.strip() for line in handle]
        assert lines == ['existing contents', 'appended output']

    def test_merged_streams_to_file(self):
        """Make sure the standard streams of external commands can be merged, redirected and appended to a file."""
        fd, filename = tempfile.mkstemp(prefix='executor-', suffix='-merged.txt')
        with open(filename, 'w') as handle:
            handle.write('existing contents\n')
        with open(filename, 'a') as handle:
            execute('echo standard output; echo standard error 1>&2', stdout_file=handle, stderr_file=handle)
        # Make sure the file was _not_ removed.
        assert os.path.isfile(filename)
        # Make sure the output was appended.
        with open(filename) as handle:
            lines = [line.strip() for line in handle]
        assert lines == ['existing contents', 'standard output', 'standard error']

    def test_asynchronous_stream_to_file(self):
        """Make sure the standard streams can be redirected to a file and asynchronously stream output to that file."""
        fd, filename = tempfile.mkstemp(prefix='executor-', suffix='-streaming.txt')
        with open(filename, 'w') as handle:
            cmd = ExternalCommand('for ((i=0; i<25; i++)); do command echo $i; sleep 0.1; done',
                                  async=True, stdout_file=handle)
            cmd.start()

        def expect_some_output():
            """Expect some but not all output to be readable at some point."""
            with open(filename) as handle:
                lines = list(handle)
                assert len(lines) > 0
                assert len(lines) < 25

        def expect_most_output():
            """Expect most but not all output to be readable at some point."""
            with open(filename) as handle:
                lines = list(handle)
                assert len(lines) > 15
                assert len(lines) < 25

        def expect_all_output():
            """Expect all output to be readable at some point."""
            with open(filename) as handle:
                lines = list(handle)
                assert len(lines) == 25

        retry(expect_some_output, 10)
        retry(expect_most_output, 20)
        retry(expect_all_output, 30)

    def test_tty_option(self):
        """Make sure the ``tty`` option works as expected."""
        # By default we expect the external command to inherit our standard
        # input stream (of course this test suite is expected to work
        # regardless of whether it's connected to a terminal).
        test_stdin_isatty = python_golf('import sys; sys.exit(0 if sys.stdin.isatty() else 1)')
        assert sys.stdin.isatty() == execute(*test_stdin_isatty, check=False)
        # If the command's output is being captured then its standard
        # input stream should be redirected to /dev/null.
        self.assertRaises(ExternalCommandFailed, execute, *test_stdin_isatty, capture=True)
        # If the caller explicitly disabled interactive terminal support then
        # the command's standard input stream should also be redirected to
        # /dev/null.
        self.assertRaises(ExternalCommandFailed, execute, *test_stdin_isatty, tty=False)

    def test_working_directory(self):
        """Make sure the working directory of external commands can be set."""
        with TemporaryDirectory() as directory:
            self.assertEqual(execute('echo $PWD', capture=True, directory=directory), directory)

    def test_virtual_environment_option(self):
        """Make sure Python virtual environments can be used."""
        with TemporaryDirectory() as directory:
            virtual_environment = os.path.join(directory, 'environment')
            # Create a virtual environment to run the command in.
            execute('virtualenv', virtual_environment)
            # This is the expected value of `sys.executable'.
            expected_executable = os.path.join(virtual_environment, 'bin', 'python')
            # Get the actual value of `sys.executable' by running a Python
            # interpreter inside the virtual environment.
            actual_executable = execute('python', '-c', 'import sys; print(sys.executable)',
                                        capture=True, virtual_environment=virtual_environment)
            # Make sure the values match.
            assert os.path.samefile(expected_executable, actual_executable)
            # Make sure that shell commands are also supported (command line
            # munging inside executor is a bit tricky and I specifically got
            # this wrong on the first attempt :-).
            output = execute('echo $VIRTUAL_ENV', capture=True, virtual_environment=virtual_environment)
            assert os.path.samefile(virtual_environment, output)

    def test_fakeroot_option(self):
        """Make sure ``fakeroot`` can be used."""
        filename = os.path.join(tempfile.gettempdir(), 'executor-%s-fakeroot-test' % os.getpid())
        self.assertTrue(execute('touch', filename, fakeroot=True))
        try:
            self.assertTrue(execute('chown', 'root:root', filename, fakeroot=True))
            self.assertEqual(execute('stat', '--format=%U', filename, fakeroot=True, capture=True), 'root')
            self.assertEqual(execute('stat', '--format=%G', filename, fakeroot=True, capture=True), 'root')
            self.assertTrue(execute('chmod', '600', filename, fakeroot=True))
            self.assertEqual(execute('stat', '--format=%a', filename, fakeroot=True, capture=True), '600')
        finally:
            os.unlink(filename)

    def test_uid_option(self):
        """
        Make sure ``sudo`` can be used to switch users based on a user ID.

        The purpose of this test is to switch to any user that is not root or
        the current user and verify that switching worked correctly. It's
        written this way because I wanted to make the least possible
        assumptions about the systems that will run this test suite.
        """
        uids_to_ignore = (0, os.getuid())
        entry = next(e for e in pwd.getpwall() if e.pw_uid not in uids_to_ignore)
        output = execute('id', '-u', capture=True, uid=entry.pw_uid)
        assert output == str(entry.pw_uid)

    def test_user_option(self):
        """
        Make sure ``sudo`` can be used to switch users based on a username.

        The purpose of this test is to switch to any user that is not root or
        the current user and verify that switching worked correctly. It's
        written this way because I wanted to make the least possible
        assumptions about the systems that will run this test suite.
        """
        uids_to_ignore = (0, os.getuid())
        entry = next(e for e in pwd.getpwall() if e.pw_uid not in uids_to_ignore)
        output = execute('id', '-u', capture=True, user=entry.pw_name)
        assert output == str(entry.pw_uid)

    def test_sudo_option(self):
        """Make sure ``sudo`` can be used to elevate privileges."""
        filename = os.path.join(self.sudo_enabled_directory, 'executor-%s-sudo-test' % os.getpid())
        self.assertTrue(execute('touch', filename))
        try:
            self.assertTrue(execute('chown', 'root:root', filename, sudo=True))
            self.assertEqual(execute('stat', '--format=%U', filename, sudo=True, capture=True), 'root')
            self.assertEqual(execute('stat', '--format=%G', filename, sudo=True, capture=True), 'root')
            self.assertTrue(execute('chmod', '600', filename, sudo=True))
            self.assertEqual(execute('stat', '--format=%a', filename, sudo=True, capture=True), '600')
        finally:
            self.assertTrue(execute('rm', '-R', self.sudo_enabled_directory, sudo=True))

    def test_environment_variable_handling(self):
        """Make sure environment variables can be overridden."""
        # Check that environment variables of the current process are passed on to subprocesses.
        output = execute('echo $PATH', capture=True)
        assert output == os.environ['PATH']
        # Test that environment variable overrides can be given to external commands.
        output = execute(
            'echo $HELLO $WORLD',
            capture=True,
            environment=dict(
                HELLO='Hello',
                WORLD='world!',
            ),
        )
        assert output == 'Hello world!'
        # Test that the environment variables of a command can be modified
        # after the command has been initialized.
        cmd = ExternalCommand('echo $DELAYED', capture=True)
        cmd.environment['DELAYED'] = 'Also works fine'
        cmd.wait()
        assert cmd.output == 'Also works fine'

    def test_simple_async_cmd(self):
        """Make sure commands can be executed asynchronously."""
        cmd = ExternalCommand('sleep 4', async=True)
        # Make sure we're starting from a sane state.
        assert not cmd.was_started
        assert not cmd.is_running
        assert not cmd.is_finished
        # Start the external command.
        cmd.start()

        def assert_running():
            """
            Make sure command switches to running state within a reasonable time.

            This is sensitive to timing issues on slow or overloaded systems,
            the retry logic is there to make the test pass as quickly as
            possible while still allowing for some delay.
            """
            assert cmd.was_started
            assert cmd.is_running
            assert not cmd.is_finished

        retry(assert_running, timeout=4)
        # Wait for the external command to finish.
        cmd.wait()
        # Make sure we finished in a sane state.
        assert cmd.was_started
        assert not cmd.is_running
        assert cmd.is_finished
        assert cmd.returncode == 0

    def test_async_with_input(self):
        """Make sure asynchronous commands can be provided standard input."""
        random_file = os.path.join(tempfile.gettempdir(), 'executor-%s-async-input-test' % os.getpid())
        random_value = str(random.random())
        cmd = ExternalCommand('cat > %s' % quote(random_file), async=True, input=random_value)
        try:
            cmd.start()
            cmd.wait()
            assert os.path.isfile(random_file)
            with open(random_file) as handle:
                contents = handle.read()
                assert random_value == contents.strip()
        finally:
            if os.path.isfile(random_file):
                os.unlink(random_file)

    def test_async_with_output(self):
        """Make sure asynchronous command output can be captured."""
        random_value = str(random.random())
        cmd = ExternalCommand('echo %s' % quote(random_value), async=True, capture=True)
        cmd.start()
        cmd.wait()
        assert cmd.output == random_value

    def test_callback_evaluation(self):
        """Make sure result processing callbacks work as expected."""
        result = execute('echo', str(time.time()), callback=self.coerce_timestamp)
        assert isinstance(result, datetime.datetime)

    def coerce_timestamp(self, cmd):
        """Callback for :func:`test_callback_evaluation()`."""
        return datetime.datetime.fromtimestamp(float(cmd.output))

    def test_event_callbacks(self):
        """Make sure the ``start_event`` and ``finish_event`` callbacks are actually invoked."""
        for async in True, False:
            results = []
            cmd = ExternalCommand(
                'sleep', '0.1',
                async=async,
                start_event=lambda cmd: results.append(('started', time.time())),
                finish_event=lambda cmd: results.append(('finished', time.time())),
            )
            cmd.start()
            mapping = dict(results)
            assert 'started' in mapping
            cmd.wait()
            mapping = dict(results)
            assert 'finished' in mapping
            assert mapping['finished'] > mapping['started']

    def test_repr(self):
        """Make sure that repr() on external commands gives sane output."""
        cmd = ExternalCommand('echo 42',
                              async=True,
                              capture=True,
                              directory='/',
                              environment={'my_environment_variable': '42'})
        assert repr(cmd).startswith('ExternalCommand(')
        assert repr(cmd).endswith(')')
        assert 'echo 42' in repr(cmd)
        assert 'async=True' in repr(cmd)
        assert ('directory=%r' % '/') in repr(cmd)
        assert 'my_environment_variable' in repr(cmd)
        assert 'was_started=False' in repr(cmd)
        assert 'is_running=False' in repr(cmd)
        assert 'is_finished=False' in repr(cmd)
        cmd.start()

        def assert_finished():
            """Allow for some delay before the external command finishes."""
            assert 'was_started=True' in repr(cmd)
            assert 'is_running=False' in repr(cmd)
            assert 'is_finished=True' in repr(cmd)

        retry(assert_finished, 10)

    def test_command_pool(self):
        """Make sure command pools actually run multiple commands in parallel."""
        num_commands = 10
        sleep_time = 4
        pool = CommandPool(5)
        for i in range(num_commands):
            pool.add(ExternalCommand('sleep %i' % sleep_time))
        timer = Timer()
        results = pool.run()
        assert all(cmd.returncode == 0 for cmd in results.values())
        assert timer.elapsed_time < (num_commands * sleep_time)

    def test_command_pool_resumable(self):
        """Make sure command pools can be resumed after raising exceptions."""
        pool = CommandPool()
        # Prepare two commands that will both raise an exception.
        c1 = ExternalCommand('exit 1', check=True)
        c2 = ExternalCommand('exit 42', check=True)
        # Add the commands to the pool and start them.
        pool.add(c1)
        pool.add(c2)
        pool.spawn()
        # Wait for both commands to finish.
        while not pool.is_finished:
            time.sleep(0.1)
        # The first call to collect() should raise an exception about `exit 1'.
        e1 = intercept(ExternalCommandFailed, pool.collect)
        assert e1.command is c1
        # The second call to collect() should raise an exception about `exit 42'.
        e2 = intercept(ExternalCommandFailed, pool.collect)
        assert e2.command is c2

    def test_command_pool_termination(self):
        """Make sure command pools can be terminated on failure."""
        pool = CommandPool()
        # Include a command that just sleeps for a minute.
        sleep_cmd = ExternalCommand('sleep 60')
        pool.add(sleep_cmd)
        # Include a command that immediately exits with a nonzero return code.
        pool.add(ExternalCommand('exit 1', check=True))
        # Start the command pool and terminate it as soon as the control flow
        # returns to us (because `exit 1' causes an exception to be raised).
        try:
            pool.run()
            assert False, "Assumed CommandPool.run() to raise ExternalCommandFailed!"
        except ExternalCommandFailed as e:
            # Make sure the exception was properly tagged.
            assert e.pool == pool
        # Make sure the sleep command was terminated.
        assert sleep_cmd.is_terminated

    def test_command_pool_delay_checks(self):
        """Make sure command pools can delay error checking until all commands have finished."""
        pool = CommandPool(delay_checks=True)
        # Include a command that fails immediately.
        pool.add(ExternalCommand('exit 1', check=True))
        # Include some commands that just sleep for a while.
        pool.add(ExternalCommand('sleep 1', check=True))
        pool.add(ExternalCommand('sleep 2', check=True))
        pool.add(ExternalCommand('sleep 3', check=True))
        # Make sure the expected exception is raised.
        self.assertRaises(CommandPoolFailed, pool.run)
        # Make sure all commands were started.
        assert all(cmd.was_started for id, cmd in pool.commands)
        # Make sure all commands finished.
        assert all(cmd.is_finished for id, cmd in pool.commands)

    def test_command_pool_delay_checks_noop(self):
        """Make sure command pools with delayed error checking don't raise when ``check=False``."""
        pool = CommandPool(delay_checks=True)
        # Include a command that fails immediately.
        pool.add(ExternalCommand('exit 1', check=False))
        # Run the command pool without catching exceptions; we don't except any.
        pool.run()
        # Make sure the command failed even though the exception wasn't raised.
        assert all(cmd.failed for id, cmd in pool.commands)

    def test_command_pool_logs_directory(self):
        """Make sure command pools can log output of commands in a directory."""
        with TemporaryDirectory() as root_directory:
            identifiers = [1, 2, 3, 4, 5]
            sub_directory = os.path.join(root_directory, 'does-not-exist-yet')
            pool = CommandPool(concurrency=5, logs_directory=sub_directory)
            for i in identifiers:
                pool.add(identifier=i, command=ExternalCommand('echo %i' % i))
            pool.run()
            files = os.listdir(sub_directory)
            assert sorted(files) == sorted(['%s.log' % i for i in identifiers])
            for filename in files:
                with open(os.path.join(sub_directory, filename)) as handle:
                    contents = handle.read()
                assert filename == ('%s.log' % contents.strip())

    def test_concurrency_control_with_groups(self):
        """Make sure command pools support ``group_by`` for high level concurrency control."""
        pool = CommandPool(concurrency=10)
        for i in range(10):
            pool.add(ExternalCommand('sleep 0.1', group_by='group-a'))
        for i in range(10):
            pool.add(ExternalCommand('sleep 0.1', group_by='group-b'))
        while not pool.is_finished:
            pool.spawn()
            # Make sure we never see more than two commands running at the same
            # time (because the commands are spread over two command groups).
            assert pool.num_running <= 2
            pool.collect()

    def test_concurrency_control_with_dependencies(self):
        """Make sure command pools support ``dependencies`` for low level concurrency control."""
        pool = CommandPool(concurrency=10)
        group_one = [ExternalCommand('sleep 0.1') for i in range(5)]
        group_two = [ExternalCommand('sleep 0.1', dependencies=group_one) for i in range(5)]
        group_three = [ExternalCommand('sleep 0.1', dependencies=group_two) for i in range(5)]
        for group in group_one, group_two, group_three:
            for cmd in group:
                pool.add(cmd)
        while not pool.is_finished:
            pool.spawn()
            # Make sure we never see more than one group of commands running at
            # the same time (because we've set up the dependencies like this).
            assert pool.num_running <= 5
            pool.collect()

    def test_ssh_user_at_host(self):
        """Make sure a username can be injected via an SSH alias."""
        cmd = RemoteCommand('root@host', 'true')
        assert cmd.ssh_user == 'root'
        assert cmd.ssh_alias == 'host'
        assert cmd.have_superuser_privileges

    def test_ssh_command_lines(self):
        """Make sure SSH client command lines are correctly generated."""
        # Construct a remote command using as much defaults as possible and
        # validate the resulting SSH client program command line.
        cmd = RemoteCommand('localhost', 'true', ssh_user='some-random-user')
        for token in (
                'ssh', '-o', 'BatchMode=yes',
                       '-o', 'ConnectTimeout=%i' % DEFAULT_CONNECT_TIMEOUT,
                       '-o', 'StrictHostKeyChecking=no',
                       '-l', 'some-random-user',
                       'localhost', 'true',
        ):
            assert token in tokenize_command_line(cmd)
        # Make sure batch mode can be disabled.
        assert 'BatchMode=no' in \
            RemoteCommand('localhost', 'date', batch_mode=False).command_line
        # Make sure the connection timeout can be configured.
        assert 'ConnectTimeout=42' in \
            RemoteCommand('localhost', 'date', connect_timeout=42).command_line
        # Make sure the SSH client program command can be configured.
        assert 'Compression=yes' in \
            RemoteCommand('localhost', 'date', ssh_command=['ssh', '-o', 'Compression=yes']).command_line
        # Make sure the known hosts file can be ignored.
        cmd = RemoteCommand('localhost', 'date', ignore_known_hosts=True)
        assert cmd.ignore_known_hosts
        cmd.ignore_known_hosts = False
        assert not cmd.ignore_known_hosts
        # Make sure strict host key checking can be enabled.
        assert 'StrictHostKeyChecking=yes' in \
            RemoteCommand('localhost', 'date', strict_host_key_checking=True).command_line
        assert 'StrictHostKeyChecking=yes' in \
            RemoteCommand('localhost', 'date', strict_host_key_checking='yes').command_line
        # Make sure host key checking can be set to prompt the operator.
        assert 'StrictHostKeyChecking=ask' in \
            RemoteCommand('localhost', 'date', strict_host_key_checking='ask').command_line
        # Make sure strict host key checking can be disabled.
        assert 'StrictHostKeyChecking=no' in \
            RemoteCommand('localhost', 'date', strict_host_key_checking=False).command_line
        assert 'StrictHostKeyChecking=no' in \
            RemoteCommand('localhost', 'date', strict_host_key_checking='no').command_line
        # Make sure fakeroot and sudo requests are honored.
        assert 'fakeroot' in \
            tokenize_command_line(RemoteCommand('localhost', 'date', fakeroot=True))
        assert 'sudo' in \
            tokenize_command_line(RemoteCommand('localhost', 'date', sudo=True))
        assert 'sudo' not in \
            tokenize_command_line(RemoteCommand('localhost', 'date', ssh_user='root', sudo=True))

    def test_ssh_unreachable(self):
        """Make sure a specific exception is raised when ``ssh`` fails to connect."""
        # Make sure invalid SSH aliases raise the expected type of exception.
        self.assertRaises(
            RemoteConnectFailed,
            remote, 'this.domain.surely.wont.exist.right', 'date', silent=True,
        )

    def test_remote_command_missing(self):
        """Make sure a specific exception is raised when a remote command is missing."""
        with SSHServer() as server:
            self.assertRaises(
                RemoteCommandNotFound,
                remote, '127.0.0.1', MISSING_COMMAND,
                **server.client_options
            )

    def test_remote_working_directory(self):
        """Make sure remote working directories can be set."""
        with SSHServer() as server:
            with TemporaryDirectory() as some_random_directory:
                output = remote('127.0.0.1', 'pwd',
                                capture=True,
                                directory=some_random_directory,
                                **server.client_options)
                assert output == some_random_directory

    def test_remote_error_handling(self):
        """Make sure remote commands preserve exit codes."""
        with SSHServer() as server:
            cmd = RemoteCommand('127.0.0.1', 'exit 42', **server.client_options)
            self.assertRaises(RemoteCommandFailed, cmd.start)

    def test_foreach(self):
        """Make sure remote command pools work."""
        with SSHServer() as server:
            ssh_aliases = ['127.0.0.%i' % i for i in (1, 2, 3, 4, 5, 6, 7, 8)]
            results = foreach(ssh_aliases, 'echo $SSH_CONNECTION',
                              concurrency=3, capture=True,
                              **server.client_options)
            assert sorted(ssh_aliases) == sorted(cmd.ssh_alias for cmd in results)
            assert len(ssh_aliases) == len(set(cmd.output for cmd in results))

    def test_foreach_with_logging(self):
        """Make sure remote command pools can log output."""
        with TemporaryDirectory() as directory:
            ssh_aliases = ['127.0.0.%i' % i for i in (1, 2, 3, 4, 5, 6, 7, 8)]
            with SSHServer() as server:
                foreach(ssh_aliases, 'echo $SSH_CONNECTION',
                        concurrency=3, logs_directory=directory,
                        capture=True, **server.client_options)
            log_files = os.listdir(directory)
            assert len(log_files) == len(ssh_aliases)
            assert all(os.path.getsize(os.path.join(directory, fn)) > 0 for fn in log_files)

    def test_create_context(self):
        """Test context creation."""
        assert isinstance(create_context(), LocalContext)
        assert isinstance(create_context(ssh_alias=None), LocalContext)
        assert isinstance(create_context(ssh_alias='whatever'), RemoteContext)
        assert create_context(ssh_alias='whatever').ssh_alias == 'whatever'
        assert create_context(sudo=True).options['sudo'] is True
        assert create_context(sudo=False).options['sudo'] is False

    def test_local_context(self):
        """Test a local command context."""
        self.check_context(LocalContext())

    def test_remote_context(self):
        """Test a remote command context."""
        with SSHServer() as server:
            self.check_context(RemoteContext('127.0.0.1', **server.client_options))

    def check_context(self, context):
        """Test a command execution context (whether local or remote)."""
        # Make sure __str__() does `something useful'.
        assert 'system' in str(context)
        # Make sure context.cpu_count is supported.
        assert context.cpu_count >= 1
        # Test context.execute() and cleanup().
        random_file = os.path.join(self.sudo_enabled_directory, uuid.uuid4().hex)
        with context:
            # Make sure the test directory exists.
            assert context.exists(self.sudo_enabled_directory)
            assert context.is_directory(self.sudo_enabled_directory)
            assert not context.is_file(self.sudo_enabled_directory)
            # Make sure the random file doesn't exist yet.
            assert not context.exists(random_file)
            # Create the random file.
            context.execute('touch', random_file)
            # Make sure the file was created.
            assert context.exists(random_file)
            assert context.is_file(random_file)
            assert not context.is_directory(random_file)
            # Make sure the file is readable and writable.
            assert context.is_readable(random_file)
            assert context.is_writable(random_file)
            # Schedule to clean up the file.
            context.cleanup('rm', '-f', random_file)
            # Make sure the file hasn't actually been removed yet.
            assert context.exists(random_file)
            # The following tests only make sense when we're not already
            # running with superuser privileges.
            if os.getuid() != 0:
                # Revoke our privileges to the file.
                context.execute('chown', 'root:root', random_file, sudo=True)
                context.execute('chmod', '600', random_file, sudo=True)
                # Make sure the file is no longer readable or writable.
                assert not context.is_readable(random_file)
                assert not context.is_writable(random_file)
        # Make sure the file has been removed (__exit__).
        assert not context.exists(random_file)
        # Test context.capture().
        assert context.capture('hostname') == socket.gethostname()
        # Test context.read_file() and context.write_file() and make sure they
        # are binary safe (i.e. they should be usable for non-text files).
        random_file = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        assert not os.path.exists(random_file)
        expected_contents = bytes(random.randint(0, 255) for i in range(25))
        context.write_file(random_file, expected_contents)
        # Make sure the file was indeed created.
        assert os.path.exists(random_file)
        # Make sure the contents are correct.
        actual_contents = context.read_file(random_file)
        assert actual_contents == expected_contents
        # Test the happy path in context.atomic_write().
        random_file = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        expected_contents = bytes(random.randint(0, 255) for i in range(25))
        assert not context.exists(random_file)
        with context.atomic_write(random_file) as temporary_file:
            context.write_file(temporary_file, expected_contents)
            assert not context.exists(random_file)
        assert not context.exists(temporary_file)
        assert context.exists(random_file)
        assert context.read_file(random_file) == expected_contents
        # Test the failure handling in context.atomic_write().
        random_file = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        try:
            assert not context.exists(random_file)
            with context.atomic_write(random_file) as temporary_file:
                context.write_file(temporary_file, '')
                assert context.exists(temporary_file)
                # Interrupt the `with' block by raising an exception.
                raise Exception
        except Exception:
            pass
        finally:
            # Make sure the temporary file was cleaned up.
            assert not context.exists(temporary_file)
            # Make sure the target file wasn't created.
            assert not context.exists(random_file)
        # Test context.list_entries() and make sure it doesn't
        # mangle filenames containing whitespace.
        nasty_filenames = [
            'something-innocent',
            'now with spaces',
            'and\twith\ttabs',
            'and\nfinally\nnewlines',
        ]
        with TemporaryDirectory() as directory:
            # Create files with nasty names :-).
            for filename in nasty_filenames:
                with open(os.path.join(directory, filename), 'w') as handle:
                    handle.write('\n')
            # List the directory entries.
            parsed_filenames = context.list_entries(directory)
            # Make sure all filenames were parsed correctly.
            assert sorted(nasty_filenames) == sorted(parsed_filenames)

    def test_cli_usage(self):
        """Make sure the command line interface properly presents its usage message."""
        for arguments in [], ['-h'], ['--help']:
            with CaptureOutput() as stream:
                assert run_cli(*arguments) == 0
                assert "Usage: executor" in str(stream)

    def test_cli_return_codes(self):
        """Make sure the command line interface doesn't swallow exit codes."""
        assert run_cli(*python_golf('import sys; sys.exit(0)')) == 0
        assert run_cli(*python_golf('import sys; sys.exit(1)')) == 1
        assert run_cli(*python_golf('import sys; sys.exit(42)')) == 42

    def test_cli_fudge_factor(self, fudge_factor=5):
        """Try to ensure that the fudge factor applies (a bit tricky to get right) ..."""
        def fudge_factor_hammer():
            timer = Timer()
            assert run_cli('--fudge-factor=%i' % fudge_factor, *python_golf('import sys; sys.exit(0)')) == 0
            assert timer.elapsed_time > (fudge_factor / 2.0)
        retry(fudge_factor_hammer, 60)

    def test_cli_exclusive_locking(self):
        """Ensure that exclusive locking works as expected."""
        run_cli('--exclusive', *python_golf('import sys; sys.exit(0)')) == 0

    def test_cli_timeout(self):
        """Ensure that external commands can be timed out."""
        def timeout_hammer():
            timer = Timer()
            assert run_cli('--timeout=5', *python_golf('import time; time.sleep(10)')) != 0
            assert timer.elapsed_time < 10
        retry(timeout_hammer, 60)


def intercept(exc_type, func, *args, **kw):
    """Intercept and return a raised exception."""
    try:
        func(*args, **kw)
    except exc_type as e:
        return e
    else:
        assert False, "Expected exception to be raised, but nothing happened! :-s"


def tokenize_command_line(cmd):
    """Tokenize a command line string into a list of strings."""
    return sum(map(shlex.split, cmd.command_line), [])


def retry(func, timeout):
    """Retry a function until it no longer raises assertion errors or time runs out before then."""
    time_started = time.time()
    while True:
        timeout_expired = (time.time() - time_started) >= timeout
        try:
            return func()
        except AssertionError:
            if timeout_expired:
                raise


def python_golf(statements):
    """Generate a Python command line."""
    return sys.executable, '-c', dedent(statements)


def run_cli(*arguments):
    """Run the command line interface (in the same process)."""
    saved_argv = sys.argv
    try:
        sys.argv = ['executor'] + list(arguments)
        main()
    except SystemExit as e:
        return e.code
    else:
        return 0
    finally:
        sys.argv = saved_argv


class NonGracefulCommand(ExternalCommand):

    """Wrapper for :class:`~executor.process.ControllableProcess` that disables graceful termination."""

    def terminate_helper(self, *args, **kw):
        """Swallow graceful termination signals."""
        self.logger.debug(compact("""
            Process termination using subprocess.Popen.terminate()
            intentionally disabled to simulate processes that refuse to
            terminate gracefully ..
        """))


class NonForcefulCommand(NonGracefulCommand):

    """Wrapper for :class:`~executor.process.ControllableProcess` that disables graceful and forceful termination."""

    def kill_helper(self, *args, **kw):
        """Swallow forceful termination signals."""
        self.logger.debug(compact("""
            Process termination using subprocess.Popen.kill() intentionally
            disabled to simulate processes that refuse to terminate
            forcefully ..
        """))


class CaptureOutput(object):

    """Context manager that captures what's written to :data:`sys.stdout`."""

    def __init__(self):
        """Initialize a string IO object to be used as :data:`sys.stdout`."""
        self.stream = StringIO()

    def __enter__(self):
        """Start capturing what's written to :data:`sys.stdout`."""
        self.original_stdout = sys.stdout
        sys.stdout = self.stream
        return self

    def __exit__(self, exc_type=None, exc_value=None, traceback=None):
        """Stop capturing what's written to :data:`sys.stdout`."""
        sys.stdout = self.original_stdout

    def __str__(self):
        """Get the text written to :data:`sys.stdout`."""
        return self.stream.getvalue()


class TemporaryDirectory(object):

    """
    Easy temporary directory creation & cleanup using the :keyword:`with` statement.

    Here's an example of how to use this:

    .. code-block:: python

       with TemporaryDirectory() as directory:
           # Do something useful here.
           assert os.path.isdir(directory)
    """

    def __init__(self, **options):
        """
        Initialize a :class:`TemporaryDirectory` object.

        :param options: Any keyword arguments are passed on to :func:`tempfile.mkdtemp()`.
        """
        self.options = options
        self.temporary_directory = None

    def __enter__(self):
        """Create the temporary directory."""
        self.temporary_directory = tempfile.mkdtemp(**self.options)
        return self.temporary_directory

    def __exit__(self, exc_type, exc_value, traceback):
        """Destroy the temporary directory."""
        if self.temporary_directory is not None:
            shutil.rmtree(self.temporary_directory)
            self.temporary_directory = None
