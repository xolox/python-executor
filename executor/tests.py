# Automated tests for the `executor' module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 23, 2015
# URL: https://executor.readthedocs.org

# Standard library modules.
import logging
import os
import random
import tempfile
import time
import unittest

# The module we're testing.
from executor import (
    execute,
    ExternalCommand,
    ExternalCommandFailed,
    quote,
    which,
)

class ExecutorTestCase(unittest.TestCase):

    def setUp(self):
        try:
            # Optional external dependency.
            import coloredlogs
            coloredlogs.install()
            coloredlogs.set_level(logging.DEBUG)
        except ImportError:
            logging.basicConfig(level=logging.DEBUG)

    def test_program_searching(self):
        self.assertTrue(which('python'))
        self.assertFalse(which('a-program-name-that-no-one-would-ever-use'))

    def test_status_code_checking(self):
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

    def test_subprocess_output(self):
        self.assertEqual(execute('echo', 'this is a test', capture=True), 'this is a test')
        self.assertEqual(execute('echo', '-e', r'line 1\nline 2', capture=True), 'line 1\nline 2\n')
        # I don't know how to test for the effect of silent=True in a practical
        # way without creating the largest test in this test suite :-). The
        # least I can do is make sure the keyword argument is accepted and the
        # code runs without exceptions in supported environments.
        self.assertTrue(execute('echo', 'this is a test', silent=True))

    def test_subprocess_input(self):
        self.assertEqual(execute('tr', 'a-z', 'A-Z', input='test', capture=True), 'TEST')

    def test_working_directory(self):
        directory = tempfile.mkdtemp()
        try:
            self.assertEqual(execute('echo $PWD', capture=True, directory=directory), directory)
        finally:
            os.rmdir(directory)

    def test_fakeroot_option(self):
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
        # Check that environment variables of the current process are passed on to subprocesses.
        self.assertEqual(execute('echo $PATH', capture=True), os.environ['PATH'])
        # Test that environment variable overrides can be given to external commands.
        override_value = str(random.random())
        self.assertEqual(execute('echo $override', capture=True, environment=dict(override=override_value)), override_value)

    def test_simple_async_cmd(self):
        cmd = ExternalCommand('sleep 4', async=True)
        # Make sure we're starting from a sane state.
        assert not cmd.was_started
        assert not cmd.is_running
        assert not cmd.is_finished
        # Start the external command.
        cmd.start()
        # Make sure the external command switches to the running state within a
        # reasonable time (this is sensitive to timing issues on slow or
        # overloaded systems, the retry logic is there to make the test pass as
        # quickly as possible while still allowing for some delay).
        def assert_running():
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
        random_value = str(random.random())
        cmd = ExternalCommand('echo %s' % quote(random_value), async=True, capture=True)
        cmd.start()
        cmd.wait()
        assert cmd.output == random_value

    def test_repr(self):
        cmd = ExternalCommand('echo 42', async=True, directory='/', environment={'my-environment-variable': '42'})
        assert repr(cmd).startswith('ExternalCommand(')
        assert repr(cmd).endswith(')')
        assert 'echo 42' in repr(cmd)
        assert 'async=True' in repr(cmd)
        assert ('directory=%r' % '/') in repr(cmd)
        assert 'my-environment-variable' in repr(cmd)
        assert 'was_started=False' in repr(cmd)
        assert 'is_running=False' in repr(cmd)
        assert 'is_finished=False' in repr(cmd)
        cmd.start()
        def assert_finished():
            assert 'was_started=True' in repr(cmd)
            assert 'is_running=False' in repr(cmd)
            assert 'is_finished=True' in repr(cmd)
        retry(assert_finished, 10)

def retry(func, timeout):
    time_started = time.time()
    while (time.time() - time_started) < timeout:
        try:
            return func()
        except AssertionError:
            pass
    assert False, "Timeout expired but function never passed all assertions!"
