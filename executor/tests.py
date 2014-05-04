# Automated tests for the `executor' module.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 4, 2014
# URL: https://executor.readthedocs.org

# Standard library modules.
import logging
import os
import tempfile
import unittest

# External dependencies.
import coloredlogs

# The module we're testing.
from executor import execute, ExternalCommandFailed

class ExecutorTestCase(unittest.TestCase):

    def setUp(self):
        coloredlogs.install()
        coloredlogs.set_level(logging.DEBUG)

    def test_status_code_checking(self):
        self.assertEqual(execute('true'), True)
        self.assertEqual(execute('false', check=False), False)
        self.assertRaises(ExternalCommandFailed, execute, 'false')

    def test_subprocess_output(self):
        self.assertEqual(execute('echo this is a test', capture=True), 'this is a test')
        self.assertEqual(execute('echo', '-e', r'line 1\nline 2', capture=True), 'line 1\nline 2\n')

    def test_subprocess_input(self):
        self.assertEqual(execute('tr', 'a-z', 'A-Z', input='test', capture=True), 'TEST')

    def test_working_directory(self):
        directory = tempfile.mkdtemp()
        try:
            self.assertEqual(execute('bash', '-c', 'echo $PWD', capture=True, directory=directory), directory)
        finally:
            os.rmdir(directory)

# vim: ts=4 sw=4 et
