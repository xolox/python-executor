# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 4, 2015
# URL: https://executor.readthedocs.org

"""
Support for concurrent external command execution.

The :mod:`executor.concurrent` module defines the :class:`CommandPool` class
which makes it easy to prepare a large number of external commands, group them
together in a pool, start executing a configurable number of external commands
simultaneously and wait for all external commands to finish.
"""

# Standard library modules.
import logging
import multiprocessing
import os

# External dependencies.
from humanfriendly import pluralize, Spinner, Timer
from property_manager import mutable_property

# Initialize a logger.
logger = logging.getLogger(__name__)


class CommandPool(object):

    """
    Execute multiple external commands concurrently.

    After constructing a :class:`CommandPool` instance you add commands to it
    using :func:`add()` and when you're ready to run the commands you call
    :func:`run()`.
    """

    def __init__(self, concurrency=None, logs_directory=None):
        """
        Construct a :class:`CommandPool` object.

        :param concurrency: Override the value of :attr:`concurrency`.
        :param logs_directory: Override the value of :attr:`logs_directory`.
        """
        self.collected = set()
        self.commands = []
        if concurrency:
            self.concurrency = concurrency
        self.logs_directory = logs_directory

    @mutable_property
    def concurrency(self):
        """
        The number of external commands that the pool is allowed to run simultaneously.

        This is a positive integer number. It defaults to the return value of
        :func:`multiprocessing.cpu_count()` (which may not make much sense if
        your commands are I/O bound instead of CPU bound).
        """
        return multiprocessing.cpu_count()

    @mutable_property
    def logs_directory(self):
        """
        The pathname of a directory where captured output is stored (a string).

        If this property is set to the pathname of a directory (before any
        external commands have been started) the merged output of each external
        command is captured and stored in a log file in this directory. The
        directory will be created if it doesn't exist yet.

        Output will start appearing in the log files before the external
        commands are finished, this enables `tail -f`_ to inspect the progress
        of commands that are still running and emitting output.

        .. _tail -f: https://en.wikipedia.org/wiki/Tail_(Unix)#File_monitoring
        """

    @property
    def is_finished(self):
        """:data:`True` if all commands in the pool have finished, :data:`False` otherwise."""
        return all(cmd.is_finished for id, cmd in self.commands)

    @property
    def num_commands(self):
        """The number of commands in the pool (an integer)."""
        return len(self.commands)

    @property
    def num_finished(self):
        """The number of commands in the pool that have already finished (an integer)."""
        return sum(cmd.is_finished for id, cmd in self.commands)

    @property
    def num_running(self):
        """The number of currently running commands in the pool (an integer)."""
        return sum(cmd.is_running for id, cmd in self.commands)

    @property
    def results(self):
        """
        A mapping of identifiers to external command objects.

        This is a dictionary with external command identifiers as keys (refer
        to :func:`add()`) and :class:`~executor.ExternalCommand` objects as
        values. The :class:`~executor.ExternalCommand` objects provide access
        to the return codes and/or output of the finished commands.
        """
        return dict(self.commands)

    def add(self, command, identifier=None, log_file=None):
        """
        Add an external command to the pool of commands.

        :param command: The external command to add to the pool (an
                        :class:`~executor.ExternalCommand` object).
        :param identifier: A unique identifier for the external command (any
                           value). When this parameter is not provided the
                           identifier is set to the number of commands in the
                           pool plus one (i.e. the first command gets id 1).
        :param log_file: Override the default log file name for the command
                         (the identifier with ``.log`` appended) in case
                         :attr:`logs_directory` is set.

        The :attr:`~executor.ExternalCommand.async` property of command objects
        is automatically set to :data:`True` when they're added to a
        :class:`CommandPool`. If you really want the commands to execute with a
        concurrency of one (1) then you can set :attr:`concurrency` to one
        (I'm not sure why you'd want to do that though :-).
        """
        command.async = True
        if identifier is None:
            identifier = len(self.commands) + 1
        if self.logs_directory:
            if not log_file:
                log_file = '%s.log' % identifier
            pathname = os.path.join(self.logs_directory, log_file)
            directory = os.path.dirname(pathname)
            if not os.path.isdir(directory):
                os.makedirs(directory)
            handle = open(pathname, 'ab')
            command.stdout_file = handle
            command.stderr_file = handle
        self.commands.append((identifier, command))

    def run(self):
        """
        Keep spawning commands and collecting results until all commands have run.

        :return: The value of :attr:`results`.

        This method calls :func:`spawn()` and :func:`collect()` in a loop until
        all commands registered using :func:`add()` have run and finished. If
        you're writing code where you want to own the main loop then consider
        calling :func:`spawn()` and :func:`collect()` directly instead of using
        :func:`run()`.
        """
        # Start spawning processes to execute the commands.
        timer = Timer()
        logger.debug("Preparing to run %s with a concurrency of %i ..",
                     pluralize(self.num_commands, "command"),
                     self.concurrency)
        with Spinner(timer=timer) as spinner:
            while not self.is_finished:
                self.spawn()
                self.collect()
                label_format = "Waiting for %i/%i %s"
                waiting_for = self.num_commands - self.num_finished
                commands_pluralized = "command" if self.num_commands == 1 else "commands"
                spinner.step(label=label_format % (waiting_for, self.num_commands, commands_pluralized))
                spinner.sleep()
        # Collect the output and return code of any commands not yet collected.
        self.collect()
        logger.debug("Finished running %s in %s.",
                     pluralize(self.num_commands, "command"),
                     timer)
        # Report the results to the caller.
        return dict(self.commands)

    def spawn(self):
        """
        Spawn additional external commands up to the :attr:`concurrency` level.

        :returns: The number of external commands that were spawned by this
                  invocation of :func:`spawn()` (an integer).
        """
        num_started = 0
        todo = [cmd for id, cmd in self.commands if not cmd.was_started]
        while todo and self.num_running < self.concurrency:
            cmd = todo.pop(0)
            cmd.start()
            num_started += 1
        if num_started > 0:
            logger.debug("Spawned %i external commands ..", num_started)
        return num_started

    def collect(self):
        """
        Collect the exit codes and output of finished commands.

        :returns: The number of external commands that was collected by this
                  invocation of :func:`collect()` (an integer).
        """
        num_finished = 0
        for identifier, command in self.commands:
            if identifier not in self.collected and command.is_finished:
                command.wait()
                num_finished += 1
                self.collected.add(identifier)
        if num_finished > 0:
            logger.debug("Collected %i external commands ..", num_finished)
        return num_finished
