# Automated tests for the `executor' module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 18, 2014
# URL: https://executor.readthedocs.org

# Standard library modules.
import logging
import os
import tempfile
import unittest

# The module we're testing.
from executor import execute, which, ExternalCommandFailed

class ExecutorTestCase(unittest.TestCase):

    def setUp(self):
        try:
            # Optional external dependency.
            import coloredlogs
            coloredlogs.install()
            coloredlogs.set_level(logging.DEBUG)
        except ImportError:
            logging.basicConfig()

    def test_program_searching(self):
        self.assertTrue(which('python'))
        self.assertFalse(which('a-program-name-that-no-one-would-ever-use'))

    def test_status_code_checking(self):
        self.assertTrue(execute('true'))
        self.assertFalse(execute('false', check=False))
        self.assertRaises(ExternalCommandFailed, execute, 'false')
        try:
            execute('bash', '-c', 'exit 42')
            # Make sure the previous line raised an exception.
            self.assertTrue(False)
        except Exception as e:
            # Make sure the expected type of exception was raised.
            self.assertTrue(isinstance(e, ExternalCommandFailed))
            # Make sure the exception has the expected properties.
            self.assertEqual(e.command, "bash -c 'exit 42'")
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
            self.assertEqual(execute('bash', '-c', 'echo $PWD', capture=True, directory=directory), directory)
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
