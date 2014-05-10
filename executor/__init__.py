# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 10, 2014
# URL: https://executor.readthedocs.org

# Standard library modules.
import logging
import os
import pipes
import subprocess

# Semi-standard module versioning.
__version__ = '1.1'

# Initialize a logger.
logger = logging.getLogger(__name__)

def execute(*command, **options):
    """
    Execute an external command and make sure it succeeded. Raises
    :py:class:`ExternalCommandFailed` when the command exits with
    a nonzero exit code.

    :param command: The command to execute. If this is a single string it is
                    assumed to be a shell command and executed directly.
                    Otherwise it should be a tuple of strings, in this case
                    each string will be quoted individually using
                    :py:func:`pipes.quote()`.
    :param directory: The working directory for the external command (a string,
                      defaults to the current working directory).
    :param check: If ``True`` (the default) and the external command exits with
                  a nonzero status code, an exception is raised.
    :param capture: If ``True`` (not the default) the standard output of the
                    external command is returned as a string.
    :param input: The text to feed to the external command on standard input.
    :param logger: Specifies the custom logger to use (optional).
    :param sudo: If ``True`` (the default is ``False``) and we're not running
                 with ``root`` privileges the command is prefixed with ``sudo``.
    :returns: - If ``capture=False`` (the default) then a boolean is returned:

                - ``True`` if the subprocess exited with a zero status code,
                - ``False`` if the subprocess exited with a nonzero status code.

              - If ``capture=True`` the standard output of the external command
                is returned as a string:

                - If the standard output contains a single line then all
                  leading and trailing whitespace is stripped,

                - if the output contains multiple lines then no whitespace will
                  be stripped.
    """
    custom_logger = options.get('logger', logger)
    if len(command) == 1:
        command = command[0]
    else:
        command = ' '.join(pipes.quote(a) for a in command)
    if options.get('sudo', False) and os.getuid() != 0:
        command = 'sudo sh -c %s' % pipes.quote(command)
    directory = options.get('directory', os.curdir)
    if directory != os.curdir:
        custom_logger.debug("Executing external command in %s: %s", directory, command)
    else:
        custom_logger.debug("Executing external command: %s", command)
    kw = dict(cwd=directory)
    if options.get('input', None) is not None:
        kw['stdin'] = subprocess.PIPE
    if options.get('capture', False):
        kw['stdout'] = subprocess.PIPE
    shell = subprocess.Popen(['bash', '-c', command], **kw)
    stdout, stderr = shell.communicate(input=options.get('input', None))
    if options.get('check', True) and shell.returncode != 0:
        msg = "External command failed with exit code %s! (command: %s)"
        raise ExternalCommandFailed(msg % (shell.returncode, command))
    if options.get('capture', False):
        stripped = stdout.strip()
        return stdout if '\n' in stripped else stripped
    else:
        return shell.returncode == 0

class ExternalCommandFailed(Exception):
    """
    Raised by :py:func:`execute()` when an external command exits with a
    nonzero status code.
    """

# vim: ts=4 sw=4
