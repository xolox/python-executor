# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 17, 2014
# URL: https://executor.readthedocs.org

# Standard library modules.
import logging
import os
import pipes
import subprocess

# Semi-standard module versioning.
__version__ = '1.4'

# Initialize a logger.
logger = logging.getLogger(__name__)


def execute(*command, **options):
    """
    Execute an external command and make sure it succeeded.

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
    :param fakeroot: If ``True`` (the default is ``False``) and we're not
                     running with ``root`` privileges the command is prefixed
                     with ``fakeroot``. If ``fakeroot`` is not installed we
                     fall back to ``sudo``.
    :param encoding: In Python 3 the :py:func:`subprocess.Popen()` function
                     expects its ``input`` argument to be an instance of
                     :py:class:`bytes`. If :py:func:`execute()` is given a
                     string as input it automatically encodes it. The default
                     encoding is UTF-8. You can change it using this argument
                     by passing a string containing the name of an encoding.
    :returns: - If ``capture=False`` (the default) then a boolean is returned:

                - ``True`` if the subprocess exited with a zero status code,
                - ``False`` if the subprocess exited with a nonzero status code.

              - If ``capture=True`` the standard output of the external command
                is returned as a string:

                - If the standard output contains a single line then all
                  leading and trailing whitespace is stripped,

                - if the output contains multiple lines then no whitespace will
                  be stripped.
    :raises: :py:class:`ExternalCommandFailed` when the command exits with a
             nonzero exit code.
    """
    encoding = options.get('encoding', 'utf-8')
    custom_logger = options.get('logger', logger)
    if len(command) == 1:
        command = command[0]
    else:
        command = ' '.join(pipes.quote(a) for a in command)
    use_fakeroot = options.get('fakeroot', False)
    use_sudo = options.get('sudo', False)
    if (use_fakeroot or use_sudo) and os.getuid() != 0:
        prefix = 'fakeroot' if use_fakeroot and which('fakeroot') else 'sudo'
        command = '%s sh -c %s' % (prefix, pipes.quote(command))
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
    input = options.get('input', None)
    if input is not None:
        input = input.encode(encoding)
    stdout, stderr = shell.communicate(input=input)
    if options.get('check', True) and shell.returncode != 0:
        raise ExternalCommandFailed(command, shell.returncode)
    if options.get('capture', False):
        stdout = stdout.decode(encoding)
        stripped = stdout.strip()
        return stdout if '\n' in stripped else stripped
    else:
        return shell.returncode == 0


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
    Raised by :py:func:`execute()` when an external command exits with a
    nonzero status code.

    :ivar command: The command line that was executed (a string).
    :ivar returncode: The return code of the external command (an integer).
    """

    def __init__(self, command, returncode):
        self.command = command
        self.returncode = returncode
        error_message = "External command failed with exit code %s! (command: %s)"
        super(ExternalCommandFailed, self).__init__(error_message % (returncode, command))
