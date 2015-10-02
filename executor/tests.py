# Automated tests for the `executor' module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 2, 2015
# URL: https://executor.readthedocs.org

"""Automated tests for the `executor` package."""

# Standard library modules.
import logging
import os
import random
import shlex
import shutil
import socket
import tempfile
import time
import unittest
import uuid

# External dependencies.
from humanfriendly import Timer

# Modules included in our package.
from executor import (
    execute,
    ExternalCommand,
    ExternalCommandFailed,
    quote,
    which,
)
from executor.concurrent import CommandPool
from executor.contexts import LocalContext, RemoteContext
from executor.property_manager import (
    assignable_property,
    cached_property,
    custom_property,
    mutable_property,
    PropertyManager,
    required_property,
)
from executor.ssh.client import (
    DEFAULT_CONNECT_TIMEOUT,
    foreach,
    RemoteCommand,
    RemoteCommandFailed,
    RemoteConnectFailed,
)
from executor.ssh.server import SSHServer


class ExecutorTestCase(unittest.TestCase):

    """Container for `executor` tests (methods)."""

    def setUp(self):
        """Set up (colored) logging to the terminal."""
        try:
            # Optional external dependency.
            import coloredlogs
            coloredlogs.install()
            coloredlogs.set_level(logging.DEBUG)
        except ImportError:
            logging.basicConfig(level=logging.DEBUG)

    def test_argument_validation(self):
        """Make sure the external command constructor requires a command argument."""
        self.assertRaises(TypeError, ExternalCommand)

    def test_program_searching(self):
        """Make sure which() works as expected."""
        self.assertTrue(which('python'))
        self.assertFalse(which('a-program-name-that-no-one-would-ever-use'))

    def test_status_code_checking(self):
        """Make sure that status code handling is sane."""
        self.assertTrue(execute('true'))
        self.assertFalse(execute('false', check=False))
        self.assertRaises(ExternalCommandFailed, execute, 'false')
        try:
            execute('exit 42')
            # Make sure the previous line raised an exception.
            self.assertTrue(False)
        except Exception as e:
            # Make sure the expected type of exception was raised.
            self.assertTrue(isinstance(e, ExternalCommandFailed))
            # Make sure the exception has the expected properties.
            self.assertEqual(e.command.command_line, ['bash', '-c', 'exit 42'])
            self.assertEqual(e.returncode, 42)

    def test_stdin(self):
        """Make sure standard input can be provided to external commands."""
        self.assertEqual(execute('tr', 'a-z', 'A-Z', input='test', capture=True), 'TEST')

    def test_stdout(self):
        """Make sure standard output of external commands can be captured."""
        self.assertEqual(execute('echo', 'this is a test', capture=True), 'this is a test')
        self.assertEqual(execute('echo', '-e', r'line 1\nline 2', capture=True), 'line 1\nline 2\n')
        # I don't know how to test for the effect of silent=True in a practical
        # way without creating the largest test in this test suite :-). The
        # least I can do is make sure the keyword argument is accepted and the
        # code runs without exceptions in supported environments.
        self.assertTrue(execute('echo', 'this is a test', silent=True))

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

    def test_working_directory(self):
        """Make sure the working directory of external commands can be set."""
        directory = tempfile.mkdtemp()
        try:
            self.assertEqual(execute('echo $PWD', capture=True, directory=directory), directory)
        finally:
            os.rmdir(directory)

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

    def test_sudo_option(self):
        """Make sure ``fakeroot`` can be used."""
        filename = os.path.join(tempfile.gettempdir(), 'executor-%s-sudo-test' % os.getpid())
        self.assertTrue(execute('touch', filename))
        try:
            self.assertTrue(execute('chown', 'root:root', filename, sudo=True))
            self.assertEqual(execute('stat', '--format=%U', filename, sudo=True, capture=True), 'root')
            self.assertEqual(execute('stat', '--format=%G', filename, sudo=True, capture=True), 'root')
            self.assertTrue(execute('chmod', '600', filename, sudo=True))
            self.assertEqual(execute('stat', '--format=%a', filename, sudo=True, capture=True), '600')
        finally:
            self.assertTrue(execute('rm', filename, sudo=True))

    def test_environment_variable_handling(self):
        """Make sure environment variables can be overridden."""
        # Check that environment variables of the current process are passed on to subprocesses.
        self.assertEqual(execute('echo $PATH', capture=True), os.environ['PATH'])
        # Test that environment variable overrides can be given to external commands.
        override_value = str(random.random())
        self.assertEqual(execute('echo $override',
                                 capture=True,
                                 environment=dict(override=override_value)),
                         override_value)

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

    def test_command_pool_logs_directory(self):
        """Make sure command pools can log output of commands in a directory."""
        directory = tempfile.mkdtemp()
        identifiers = [1, 2, 3, 4, 5]
        try:
            pool = CommandPool(concurrency=5, logs_directory=directory)
            for i in identifiers:
                pool.add(identifier=i, command=ExternalCommand('echo %i' % i))
            pool.run()
            files = os.listdir(directory)
            assert sorted(files) == sorted(['%s.log' % i for i in identifiers])
            for filename in files:
                with open(os.path.join(directory, filename)) as handle:
                    contents = handle.read()
                assert filename == ('%s.log' % contents.strip())
        finally:
            shutil.rmtree(directory)

    def test_ssh_command_lines(self):
        """Make sure SSH client command lines are correctly generated."""
        # Construct a remote command using as much defaults as possible and
        # validate the resulting SSH client program command line.
        cmd = RemoteCommand('localhost', 'true', ssh_user='some-random-user')
        cmd.logger.debug("Command line: %s", cmd.command_line)
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
            lambda: RemoteCommand('this.domain.surely.wont.exist.right', 'date', silent=True).start(),
        )

    def test_remote_working_directory(self):
        """Make sure remote working directories can be set."""
        with SSHServer(async=True) as server:
            some_random_directory = tempfile.mkdtemp()
            try:
                cmd = RemoteCommand('127.0.0.1',
                                    'pwd',
                                    capture=True,
                                    directory=some_random_directory,
                                    **server.client_options)
                cmd.start()
                assert cmd.output == some_random_directory
            finally:
                shutil.rmtree(some_random_directory)

    def test_remote_error_handling(self):
        """Make sure remote commands preserve exit codes."""
        with SSHServer(async=True) as server:
            cmd = RemoteCommand('127.0.0.1', 'exit 42', **server.client_options)
            self.assertRaises(RemoteCommandFailed, cmd.start)

    def test_foreach(self):
        """Make sure remote command pools work."""
        with SSHServer(async=True) as server:
            ssh_aliases = ['127.0.0.%i' % i for i in (1, 2, 3, 4, 5, 6, 7, 8)]
            results = foreach(ssh_aliases, 'echo $SSH_CONNECTION',
                              concurrency=3, capture=True,
                              **server.client_options)
            assert sorted(ssh_aliases) == sorted(cmd.ssh_alias for cmd in results)
            assert len(ssh_aliases) == len(set(cmd.output for cmd in results))

    def test_local_context(self):
        """Test a local command context."""
        self.check_context(LocalContext())

    def test_remote_context(self):
        """Test a remote command context."""
        with SSHServer(async=True) as server:
            self.check_context(RemoteContext('127.0.0.1', **server.client_options))

    def check_context(self, context):
        """Test a command execution context (whether local or remote)."""
        # Make sure __str__() does something useful.
        assert 'system' in str(context)
        # Test context.execute() and cleanup().
        random_file = os.path.join(tempfile.gettempdir(), uuid.uuid4().hex)
        assert not os.path.exists(random_file)
        with context:
            # Create the random file.
            context.execute('touch', random_file)
            # Make sure the file was created.
            assert os.path.isfile(random_file)
            # Schedule to clean up the file.
            context.cleanup('rm', random_file)
            # Make sure the file hasn't actually been removed yet.
            assert os.path.isfile(random_file)
        # Make sure the file has been removed (__exit__).
        assert not os.path.isfile(random_file)
        # Test context.capture().
        assert context.capture('hostname') == socket.gethostname()


class CustomPropertyTestCase(unittest.TestCase):

    """Tests for the custom properties defined in the :mod:`~executor.property_manager` module."""

    def test_custom_property(self):
        """Test that :class:`.custom_property` works just like :class:`property`."""
        class test_class(object):
            @custom_property
            def test_property(self):
                return random.random()
        # Test that custom properties can be recognized as properties.
        assert isinstance(test_class.test_property, property)
        # Test that custom properties are recomputed every time.
        obj = test_class()
        assert obj.test_property != obj.test_property

    def test_assignable_property(self):
        """Test that :class:`.assignable_property` supports assignment."""
        class test_class(object):
            @assignable_property
            def test_property(self):
                return 'default'
        # Test that assignable properties can be recognized as properties.
        assert isinstance(test_class.test_property, property)
        # Test that assignable properties have a default value.
        obj = test_class()
        assert obj.test_property == 'default'
        # Test that assignable properties can be assigned a new value.
        obj = test_class()
        obj.test_property = 'changed'
        assert obj.test_property == 'changed'

    def test_required_property(self):
        """Test that :class:`.required_property` performs validation."""
        class test_class(PropertyManager):
            @required_property
            def test_property(self):
                """A very important property."""
        # Test that required properties must be set.
        self.assertRaises(TypeError, test_class)
        # Test that required properties can be set in the constructor.
        obj = test_class(test_property='default')
        assert obj.test_property == 'default'
        # Test that required properties support assignment.
        obj = test_class(test_property='default')
        obj.test_property = 'changed'
        assert obj.test_property == 'changed'
        # Test that required objects can't be deleted.
        obj = test_class(test_property='default')
        self.assertRaises(AttributeError, delattr, obj, 'test_property')

    def test_mutable_property(self):
        """Test that :class:`mutable_property` supports assignment and deletion."""
        class test_class(object):
            @mutable_property
            def test_property(self):
                return 'default'
        # Test that mutable properties can be recognized as properties.
        assert isinstance(test_class.test_property, property)
        # Test that mutable properties have a default value.
        obj = test_class()
        assert obj.test_property == 'default'
        # Test that mutable properties can be reset to their default value.
        obj = test_class()
        obj.test_property = 'changed'
        assert obj.test_property == 'changed'
        del obj.test_property
        assert obj.test_property == 'default'

    def test_cached_property(self):
        """Test that :class:`.cached_property` caches its result."""
        class test_class(object):
            @cached_property
            def test_property(self):
                return random.random()
        # Test that cached properties can be recognized as properties.
        assert isinstance(test_class.test_property, property)
        # Test that cached properties are not recomputed.
        obj = test_class()
        some_value = obj.test_property
        assert some_value == obj.test_property
        # Test that cached properties can be reset.
        del obj.test_property
        assert some_value != obj.test_property

    def test_property_injection(self):
        """Test that :class:`.PropertyManager` enables property injection but raises an error for unknown properties."""
        class test_class(PropertyManager):
            @mutable_property
            def test_property(self):
                return 'default'
        assert test_class().test_property == 'default'
        assert test_class(test_property='injected').test_property == 'injected'
        self.assertRaises(TypeError, test_class, random_keyword_argument=True)


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
