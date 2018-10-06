Changelog
=========

The purpose of this document is to list all of the notable changes to this
project. The format was inspired by `Keep a Changelog`_. This project adheres
to `semantic versioning`_.

.. contents::
   :local:

.. _Keep a Changelog: http://keepachangelog.com/
.. _semantic versioning: http://semver.org/

`Release 20.0.1`_ (2018-10-07)
------------------------------

- Bug fix: Merged pull request `#14`_ to make ``ionice_command`` compatible with older ``ionice`` versions not supporting the ``--class`` option.
- Lots of commit noise to debug Python 2.6 support on Travis CI. I'm not sure why I still bother...

.. _Release 20.0.1: https://github.com/xolox/python-executor/compare/20.0...20.0.1
.. _#14: https://github.com/xolox/python-executor/pull/14

`Release 20.0`_ (2018-05-21)
----------------------------

*While intended to be fully backwards compatible (because the new behavior is
opt-in) I decided to bump the major version number in this release because
adding retry support touched on some of the most critical pieces of code in
this project.*

- Experimental support for retrying of commands that fail. Retrying of
  asynchronous commands is only supported in the context of command pools.
- Bug fix: Pass keyword arguments of ``wait()`` to ``wait_for_process()``.
- Fix Sphinx warnings (mostly broken references).

Notes about retry support
~~~~~~~~~~~~~~~~~~~~~~~~~

I've been wanting to add retry support to `executor` for quite a while now. One
thing that I struggled with until recently was how to support retrying of
synchronous and asynchronous commands in a way that made sense for both types
of commands, without compromising too much on the simplicity of the Python API
or the actual implementation code.

In a pragmatic *"just implement something and see how it works"* moment I
decided to add support for retrying of synchronous commands to the
``ExternalCommand`` class while requiring the use of a command pool to retry
asynchronous commands. Although this implementation doesn't cover every
possible use case I do believe it covers the most important use cases. Some
high-level implementation notes:

- Synchronous commands are retried inside of the ``start()`` method. The second
  part of this method was extracted into a new ``start_once()`` method and then
  a loop was added to ``start()`` that calls ``start_once()`` until the command
  succeeds.

- Asynchronous commands allow for retry behavior to be configured but won't
  actually run a command more than once unless used in the context of command
  pools.  I did experiment with retrying of asynchronous commands inside the
  ``wait()`` method but this ended up creating an API whose behavior was very
  unintuitive (changing its behavior from non blocking to blocking in order to
  retry on failure).

.. _Release 20.0: https://github.com/xolox/python-executor/compare/19.3...20.0

`Release 19.3`_ (2018-05-04)
----------------------------

- Added ``SecureTunnel`` class for easy to use SSH tunnels (``ssh -NL ...``).
- Added ``RemoteCommand.compression`` property to enable ``ssh -C``.
- Extracted generic TCP functionality from the ``executor.ssh.server`` module
  into a new ``executor.tcp`` module (so that the functionality could be reused
  by the new SSH tunnel support).

.. _Release 19.3: https://github.com/xolox/python-executor/compare/19.2...19.3

`Release 19.2`_ (2018-04-27)
----------------------------

- Added a ``glob()`` method to contexts (this was triggered
  by the  feature request in `rotate-backups issue #10
  <https://github.com/xolox/python-rotate-backups/issues/10>`_).
- Improved documentation using ``property_manager.sphinx``.
- Added this changelog, restructured the online documentation.
- Include documentation in source distributions.
- Added ``license`` key to ``setup.py`` script.

.. _Release 19.2: https://github.com/xolox/python-executor/compare/19.1...19.2

`Release 19.1`_ (2018-03-25)
----------------------------

Added ``context.is_executable()`` shortcut.

.. _Release 19.1: https://github.com/xolox/python-executor/compare/19.0...19.1

`Release 19.0`_ (2018-02-25)
----------------------------

Backwards incompatible: Report command output on failure.

Refer to the new ``really_silent`` property for details about how this is
backwards incompatible. I suspect this to bite less than 1% of use cases
and I want `executor` to have sane defaults, so there :-).

.. _Release 19.0: https://github.com/xolox/python-executor/compare/18.1...19.0

`Release 18.1`_ (2018-01-21)
----------------------------

- Enable runtime processing of stdin/stdout/stderr (`#7`_).
- Enable iteration over lines of text in output (related to `#7`_).
- Changed the Sphinx documentation theme.
- Fixed a broken reStructuredText reference.

.. _Release 18.1: https://github.com/xolox/python-executor/compare/18.0...18.1
.. _#7: https://github.com/xolox/python-executor/issues/7

`Release 18.0`_ (2017-06-28)
----------------------------

Several backwards incompatible changes were made in an attempt to improve the
consistency of error handling:

- Bug fix: Set returncode on OSError exception
- Bug fix: Don't leave std{out,err} unset on OSError
- Don't raise exceptions from lsb_release shortcuts.
- Update usage in readme.
- Move test helpers to ``humanfriendly.testing``.

.. _Release 18.0: https://github.com/xolox/python-executor/compare/17.1...18.0

`Release 17.1`_ (2017-06-21)
----------------------------

Added support for Python callbacks in ``context.cleanup()``.

.. _Release 17.1: https://github.com/xolox/python-executor/compare/17.0...17.1

`Release 17.0`_ (2017-06-10)
----------------------------

- Rename ``ChangeRoot*`` to ``SecureChangeRoot*`` to avoid an upcoming name collision (backwards incompatible!).
- Added support for command execution in chroots using the ``chroot`` command.
- Reduced code duplication of ``&&`` logic.

.. _Release 17.0: https://github.com/xolox/python-executor/compare/16.1...17.0

`Release 16.1`_ (2017-06-08)
----------------------------

- Give contexts some ``lsb_release`` shortcuts.
- Add Python 3.6 to tested versions.

.. _Release 16.1: https://github.com/xolox/python-executor/compare/16.0.1...16.1

`Release 16.0.1`_ (2017-04-13)
------------------------------

Bug fix: Allow explicitly setting ``ionice=None``.

.. _Release 16.0.1: https://github.com/xolox/python-executor/compare/16.0...16.0.1

`Release 16.0`_ (2017-04-13)
----------------------------

- Make it very easy to use ``ionice``.
- Add simple wrapper for ``which`` (``context.find_program()``).
- Avoid nested shell in ``context.prepare_interactive_shell()``.
- Don't add trailing ``--`` in ``ChangeRootCommand.command_line``.
- Change default working directory in chroots (backwards incompatible, although
  I wouldn't be surprised if there are zero uses of the ``executor.schroot``
  module outside of the code bases I maintain :-).

.. _Release 16.0: https://github.com/xolox/python-executor/compare/15.1...16.0

`Release 15.1`_ (2017-01-10)
----------------------------

- Merged pull request `#3`_: Allow disabling of spinners.
- Bug fix: Stop timer used by ``wait_for_process()`` after waiting.
- Bumped humanfriendly_ requirement for upstream bug fix.

.. _Release 15.1: https://github.com/xolox/python-executor/compare/15.0...15.1
.. _#3: https://github.com/xolox/python-executor/pull/3

`Release 15.0`_ (2016-12-20)
----------------------------

- Added support for command execution in chroots using ``schroot``.
- Added experimental support for nested contexts.

.. _Release 15.0: https://github.com/xolox/python-executor/compare/14.1...15.0

`Release 14.1`_ (2016-10-12)
----------------------------

Added support for atomic file writes using execution contexts.

.. _Release 14.1: https://github.com/xolox/python-executor/compare/14.0...14.1

`Release 14.0`_ (2016-08-10)
----------------------------

Enable passing shell commands via stdin without specifying a command.
Strictly speaking this change is not backwards compatible but my
impression is that this won't break any valid, existing use cases.

.. _Release 14.0: https://github.com/xolox/python-executor/compare/13.0...14.0

`Release 13.0`_ (2016-07-09)
----------------------------

Improve concurrency control for command pools

Previously there was only ``CommandPool.concurrency`` to control *how many*
commands were allowed to run concurrently, now the caller can control *which*
commands are allowed to run concurrently (using the two new properties
``ExternalCommand.dependencies`` and ``group_by``).

.. _Release 13.0: https://github.com/xolox/python-executor/compare/12.0...13.0

`Release 12.0`_ (2016-07-09)
----------------------------

Connect stdin to ``/dev/null`` in command pools (backwards incompatible!)

Recently I ran into some spectacularly weird failures and it took me a
while to realize that it was happening because a command pool with SSH
client commands was running multiple SSH clients concurrently and each
of the SSH clients was allocating a pseudo-tty (``ssh -t``).

I'm currently under the impression that this new behavior is the only
sane choice, even if it is backwards incompatible. Here's hoping I
thought that through well enough before releasing this change :-).

.. _Release 12.0: https://github.com/xolox/python-executor/compare/11.0.1...12.0

`Release 11.0.1`_ (2016-07-09)
------------------------------

- Bug fix: Allow assignment of individual environment variables.
- Refactored makefile and ``setup.py`` script (checkers, docs, wheels, twine, etc).

.. _Release 11.0.1: https://github.com/xolox/python-executor/compare/11.0...11.0.1

`Release 11.0`_ (2016-06-03)
----------------------------

Connect stdin to ``/dev/null`` when ``tty=False`` (backwards incompatible!)

Recently I ran into several external commands whose output was being
captured and thus not visible, but which nevertheless rendered an
interactive prompt, waiting for a response on standard input (which
I wasn't providing because I never saw the interactive prompt :-).
The option to connect stdin and ``/dev/null`` was never available in
executor, however given the recent addition of the ``tty`` option it
seemed logical to combine the two.

Two changes in this commit backwards incompatible:

1. The standard input stream of external commands was never connected to
   ``/dev/null`` before and this is changing without an explicit opt-in or
   opt-out mechanism. I'm making this choice because I believe it to be the
   only sane approach.

2. The interface of the ``CachedStream`` class has changed even though this is
   a documented, externally available class. However I don't actually see
   anyone using ``CachedStream`` outside of the executor project, so in the
   grand scheme of things this is a minor thing (99% of users will never even
   notice, I'm guessing).

.. _Release 11.0: https://github.com/xolox/python-executor/compare/10.1...11.0

`Release 10.1`_ (2016-06-03)
----------------------------

Added support for ``start_event`` and ``finish_event`` callbacks.

.. _Release 10.1: https://github.com/xolox/python-executor/compare/10.0...10.1

`Release 10.0`_ (2016-06-01)
----------------------------

Large refactoring concerning ``executor`` / ``proc`` separation of concerns,
backwards incompatible!

In executor 7.7 the process management functionality was decoupled from
external command execution in order to re-use the process management
functionality in my proc package (this was integrated into proc 0.4). In
retrospect I implemented this refactoring (in November '15) too hastily because
the UNIX signal handling doesn't belong in the executor package (it's meant to
be portable). Last weekend I decided to finally do something about this! I'm
only committing this now because it took me days to clean up, stabilize,
document and test the refactoring :-). A high level summary:

- All process manipulation that uses UNIX signals is being moved to the 'proc'
  package, that includes things like SIGSTOP / SIGCONT. This means that the
  methods ``ControllableProcess.suspend()`` and ``ControllableProcess.resume()``
  are no longer available. This will break fresh installations of my 'proc'
  package until I release a new version, because I haven't pinned the max
  version of dependencies I control. The new release of 'proc' is waiting to be
  uploaded though :-).

- The 'executor' package no longer keeps references to ``subprocess.Popen``
  objects after the process has finished, to allow garbage collection. This
  should resolve an issue I was seeing recently when I was pushing the limits
  of executor command pools and ran into ``IOError: [Errno 24] Too many open
  files``.

  Someone on StackOverflow with the same problem:
  http://stackoverflow.com/questions/6669996/python-subprocess-running-out-of-file-descriptors

  Someone on StackOverflow who knows how to fix it:
  http://stackoverflow.com/a/23763193/788200

  While implementing this refactoring I had a lot of trouble making sure that
  ``ExternalCommand.pid`` and ``returncode`` would be preserved when the
  ``subprocess`` reference was destroyed (it seems so obvious, but nevertheless
  this tripped me up). The test suite agrees with me that I got things right
  eventually, so here's hoping for no external breakage :-).

.. _Release 10.0: https://github.com/xolox/python-executor/compare/9.11...10.0

`Release 9.11`_ (2016-05-27)
----------------------------

Make it possible to disable command pool spinners.

.. _Release 9.11: https://github.com/xolox/python-executor/compare/9.10...9.11

`Release 9.10`_ (2016-05-27)
----------------------------

``ExternalCommand`` and ``RemoteCommand`` objects now have a ``tty`` option to
express whether they need to and/or will be connected to an interactie terminal.

.. _Release 9.10: https://github.com/xolox/python-executor/compare/9.9...9.10

`Release 9.9`_ (2016-04-21)
---------------------------

Bug fix: Preserve environment variables when using ``sudo``.

.. _Release 9.9: https://github.com/xolox/python-executor/compare/9.8...9.9

`Release 9.8`_ (2016-04-13)
---------------------------

Make it easy to test contexts for superuser privileges.

.. _Release 9.8: https://github.com/xolox/python-executor/compare/9.7...9.8

`Release 9.7`_ (2016-04-09)
---------------------------

Added a shortcut for context creation (``executor.contexts.create_context()``).

.. _Release 9.7: https://github.com/xolox/python-executor/compare/9.6.1...9.7

`Release 9.6.1`_ (2016-04-07)
-----------------------------

Bug fix for previous commit.

.. _Release 9.6.1: https://github.com/xolox/python-executor/compare/9.6...9.6.1

`Release 9.6`_ (2016-04-07)
---------------------------

Make remote commands optional (stdin only is a valid use case).

.. _Release 9.6: https://github.com/xolox/python-executor/compare/9.5...9.6

`Release 9.5`_ (2016-04-03)
---------------------------

Provide contexts shortcuts for various ``test`` program invocations.

.. _Release 9.5: https://github.com/xolox/python-executor/compare/9.4...9.5

`Release 9.4`_ (2016-04-03)
---------------------------

Automatically get the SSH username from the given SSH alias when available
(delimited by an ``@`` sign).

.. _Release 9.4: https://github.com/xolox/python-executor/compare/9.3...9.4

`Release 9.3`_ (2016-03-22)
---------------------------

- Added support for listing directory entries using execution contexts.
- Stop Travis CI from testing tagged releases (I create a lot of them :-).
- Introduce context manager for temporary directories in test suite.

.. _Release 9.3: https://github.com/xolox/python-executor/compare/9.2...9.3

`Release 9.2`_ (2016-03-22)
---------------------------

Improved ``RemoteContext.cpu_count`` (by adding a fallback for ``nproc``).

.. _Release 9.2: https://github.com/xolox/python-executor/compare/9.1...9.2

`Release 9.1`_ (2016-03-22)
---------------------------

Support for reading and writing of files using execution contexts.

.. _Release 9.1: https://github.com/xolox/python-executor/compare/9.0.1...9.1

`Release 9.0.1`_ (2016-03-21)
-----------------------------

Bug fix: Proper error messages for ``RemoteCommandNotFound``.

.. _Release 9.0.1: https://github.com/xolox/python-executor/compare/9.0...9.0.1

`Release 9.0`_ (2016-02-20)
---------------------------

- Backwards incompatible: Removed ``fakeroot`` → ``sudo`` fallback behavior.
- Added more documentation of the ``uid`` and ``user`` options.
- Documented tested interpreters with trove classifiers.

.. _Release 9.0: https://github.com/xolox/python-executor/compare/8.4...9.0

`Release 8.4`_ (2016-02-20)
---------------------------

- Make it possible to run commands as specific users (via ``sudo``).
- Add Python 3.5 to tested versions and document support.
- Refactored ``setup.py`` script, add trove classifiers.
- Moved Sphinx customizations to humanfriendly_ package.

.. _Release 8.4: https://github.com/xolox/python-executor/compare/8.3...8.4
.. _humanfriendly: https://humanfriendly.readthedocs.io/en/latest/

`Release 8.3`_ (2016-01-24)
---------------------------

- Make it possible to explicitly enable/disable shell evaluation.
- Expand documentation of callback/result properties.

.. _Release 8.3: https://github.com/xolox/python-executor/compare/8.2...8.3

`Release 8.2`_ (2016-01-14)
---------------------------

Experimental support for 'result processing' callbacks.

.. _Release 8.2: https://github.com/xolox/python-executor/compare/8.1.1...8.2

`Release 8.1.1`_ (2016-01-13)
-----------------------------

Enable custom loggers for remote commands.

.. _Release 8.1.1: https://github.com/xolox/python-executor/compare/8.1...8.1.1

`Release 8.1`_ (2016-01-13)
---------------------------

- Added ``remote()`` shortcut (``execute()`` for remote commands).
- Simplified ``RemoteCommand.command_line``.
- Improved documentation of ``execute()`` function.

.. _Release 8.1: https://github.com/xolox/python-executor/compare/8.0.1...8.1

`Release 8.0.1`_ (2015-11-14)
-----------------------------

Silence 'make check' (now failing on Travis CI).

.. _Release 8.0.1: https://github.com/xolox/python-executor/compare/8.0...8.0.1

`Release 8.0`_ (2015-11-13)
---------------------------

- Added a command line interface: The ``executor`` program.
- Improved documentation after previous refactoring.

.. _Release 8.0: https://github.com/xolox/python-executor/compare/7.7...8.0

`Release 7.7`_ (2015-11-10)
---------------------------

Better process management, decoupled from ``ExternalCommand``.

.. _Release 7.7: https://github.com/xolox/python-executor/compare/7.6...7.7

`Release 7.6`_ (2015-11-10)
---------------------------

- Automatically set ``async=True`` when used as context manager.
- Minor improvements to ``executor.ssh.server`` module.
- Improve how Sphinx generates the documentation:
  
  - Configure Sphinx not to skip magic methods by default.
  - Order autodoc entries by source, not alphabetically.

.. _Release 7.6: https://github.com/xolox/python-executor/compare/7.5...7.6

`Release 7.5`_ (2015-11-08)
---------------------------

- Change default logger of commands executed in pools.
- Extract ephemeral TCP server support from ``executor.ssh.server.SSHServer``.

.. _Release 7.5: https://github.com/xolox/python-executor/compare/7.4...7.5

`Release 7.4`_ (2015-11-08)
---------------------------

- Decompose ``ExternalCommand.start()``.
- Introduce ``CommandNotFound`` subclass of ``ExternalCommandFailed``.

.. _Release 7.4: https://github.com/xolox/python-executor/compare/7.2...7.4

`Release 7.2`_ (2015-11-08)
---------------------------

- Decompose ``executor.which()`` and add Windows support.
- Disable capturing in pytest.ini (because it breaks ``sudo`` tests).

.. _Release 7.2: https://github.com/xolox/python-executor/compare/7.1.1...7.2

`Release 7.1.1`_ (2015-10-18)
-----------------------------

- Bug fix for integration of ``ExternalCommandFailed`` / ``TimeoutError`` exceptions.
- Improve documentation of ``virtual_environment`` option.

.. _Release 7.1.1: https://github.com/xolox/python-executor/compare/7.1...7.1.1

`Release 7.1`_ (2015-10-18)
---------------------------

Make it easy to run commands in Python virtual environments.

.. _Release 7.1: https://github.com/xolox/python-executor/compare/7.0.1...7.1

`Release 7.0.1`_ (2015-10-06)
-----------------------------

Bug fix: Only raise ``CommandPoolFailed`` for commands with ``check=True``.

.. _Release 7.0.1: https://github.com/xolox/python-executor/compare/7.0...7.0.1

`Release 7.0`_ (2015-10-06)
---------------------------

``foreach()`` now sets ``delay_checks=True`` by default.

This change is not backwards compatible but IMHO it fits in the scheme of
"making it easy to do the right thing". For further argumentation refer to the
updated documentation.

.. _Release 7.0: https://github.com/xolox/python-executor/compare/6.2...7.0

`Release 6.2`_ (2015-10-06)
---------------------------

Enable delayed error checking for command pools.

.. _Release 6.2: https://github.com/xolox/python-executor/compare/6.1...6.2

`Release 6.1`_ (2015-10-05)
---------------------------

Tag exceptions with the command pool from which they were raised.

.. _Release 6.1: https://github.com/xolox/python-executor/compare/6.0...6.1

`Release 6.0`_ (2015-10-05)
---------------------------

Make ``CommandPool.run()`` terminate commands before aborting.

This bumps the major version number because the change isn't backwards
compatible (although I believe it does make for more sane default behavior) and
version numbers are cheap :-).

.. _Release 6.0: https://github.com/xolox/python-executor/compare/5.1...6.0

`Release 5.1`_ (2015-10-05)
---------------------------

Make it possible to terminate command pools.

.. _Release 5.1: https://github.com/xolox/python-executor/compare/5.0.1...5.1

`Release 5.0.1`_ (2015-10-05)
-----------------------------

- Bug fix: Make ``CommandPool.collect()`` resumable after failing commands.
- Enable intersphinx mapping from ``executor`` to ``property-manager``.
- Removed minor (trivial) code duplication from ``CommandPool.run()``.
- Renamed 'construct' to 'initialize' where applicable: A constructor in Python
  is called ``__new__()`` and overriding it is the exception, not the norm.
  Overriding the ``__init__()`` method is the norm, but then ``__init__()`` is
  not a constructor, it's an "initializer".

.. _Release 5.0.1: https://github.com/xolox/python-executor/compare/5.0...5.0.1

`Release 5.0`_ (2015-10-04)
---------------------------

Promote ``executor.property_manager`` to a separate property-manager_ package
(I'd been wanting to reuse this functionality in several other packages for a
while now).

.. _Release 5.0: https://github.com/xolox/python-executor/compare/4.9...5.0
.. _property-manager: https://property-manager.readthedocs.org/en/latest/

`Release 4.9`_ (2015-10-02)
---------------------------

Change ``executor.ssh.client.foreach()`` to use SSH aliases as identifiers.

.. _Release 4.9: https://github.com/xolox/python-executor/compare/4.8...4.9

`Release 4.8`_ (2015-10-02)
---------------------------

Change command pool output logging to append instead of overwrite.

.. _Release 4.8: https://github.com/xolox/python-executor/compare/4.7...4.8

`Release 4.7`_ (2015-10-02)
---------------------------

Support capturing ``foreach()`` command pool output to logs directory.

.. _Release 4.7: https://github.com/xolox/python-executor/compare/4.6...4.7

`Release 4.6`_ (2015-10-02)
---------------------------

Support capturing command pool output to logs directory.

.. _Release 4.6: https://github.com/xolox/python-executor/compare/4.5...4.6

`Release 4.5`_ (2015-10-02)
---------------------------

- Bug fix: Python 3 doesn't support ur"strings" (Unicode raw strings)
- Support redirecting standard streams to files provided by caller.
- Implement and enforce PEP-8 and PEP-257 compliance.

.. _Release 4.5: https://github.com/xolox/python-executor/compare/4.4.1...4.5

`Release 4.4.1`_ (2015-08-30)
-----------------------------

- Bug fix for obscure ``UnicodeDecodeError`` in ``setup.py`` (on Python 3 only).
- Make Travis CI builds fail when coverage isn't >= 90%.
- Also run the tests under PyPy on Travis CI.

.. _Release 4.4.1: https://github.com/xolox/python-executor/compare/4.4...4.4.1

`Release 4.4`_ (2015-05-30)
---------------------------

Expose the CPU count of execution contexts.

.. _Release 4.4: https://github.com/xolox/python-executor/compare/4.3...4.4

`Release 4.3`_ (2015-05-30)
---------------------------

Give contexts a ``test()`` method.

.. _Release 4.3: https://github.com/xolox/python-executor/compare/4.2...4.3

`Release 4.2`_ (2015-05-30)
---------------------------

Enable context users to prepare commands without starting them.

.. _Release 4.2: https://github.com/xolox/python-executor/compare/4.1...4.2

`Release 4.1`_ (2015-05-29)
---------------------------

Make it possible to nest 'unwind contexts' (``executor.contexts``).

.. _Release 4.1: https://github.com/xolox/python-executor/compare/4.0.1...4.1

`Release 4.0.1`_ (2015-05-28)
-----------------------------

Bug fix for remote working directory logic.

.. _Release 4.0.1: https://github.com/xolox/python-executor/compare/4.0...4.0.1

`Release 4.0`_ (2015-05-27)
---------------------------

Added support for external command contexts (agnostic to local vs. remote execution).

.. _Release 4.0: https://github.com/xolox/python-executor/compare/3.6...4.0

`Release 3.6`_ (2015-05-27)
---------------------------

Support non-default remote working directories.

.. _Release 3.6: https://github.com/xolox/python-executor/compare/3.5...3.6

`Release 3.5`_ (2015-05-26)
---------------------------

Added a ``RemoteCommandPool`` class.

.. _Release 3.5: https://github.com/xolox/python-executor/compare/3.4.1...3.5

`Release 3.4.1`_ (2015-05-26)
-----------------------------

Default to ``StrictHostKeyChecking=no`` for SSH commands.

.. _Release 3.4.1: https://github.com/xolox/python-executor/compare/3.4...3.4.1

`Release 3.4`_ (2015-05-26)
---------------------------

Make the decoded values of stdout/stderr available.

.. _Release 3.4: https://github.com/xolox/python-executor/compare/3.3...3.4

`Release 3.3`_ (2015-05-26)
---------------------------

Made it possible to merge the standard output and error streams.

.. _Release 3.3: https://github.com/xolox/python-executor/compare/3.2...3.3

`Release 3.2`_ (2015-05-26)
---------------------------

Made it possible to capture the standard error stream.

.. _Release 3.2: https://github.com/xolox/python-executor/compare/3.1...3.2

`Release 3.1`_ (2015-05-25)
---------------------------

Added ``ExternalCommand.succeeded`` and ``failed`` properties.

.. _Release 3.1: https://github.com/xolox/python-executor/compare/3.0.2...3.1

`Release 3.0.2`_ (2015-05-25)
-----------------------------

Don't set the SSH port number to 22 by default (let the SSH client program figure it out instead).

.. _Release 3.0.2: https://github.com/xolox/python-executor/compare/3.0.1...3.0.2

`Release 3.0.1`_ (2015-05-25)
-----------------------------

Bug fix for ``setup.py`` (forgot to remove import).

.. _Release 3.0.1: https://github.com/xolox/python-executor/compare/3.0...3.0.1

`Release 3.0`_ (2015-05-25)
---------------------------

- Added support for remote command execution using SSH.
- Improved ``ExternalCommand`` documentation.

.. _Release 3.0: https://github.com/xolox/python-executor/compare/2.4...3.0

`Release 2.4`_ (2015-05-24)
---------------------------

Make ``ExternalCommand`` a context manager.

.. _Release 2.4: https://github.com/xolox/python-executor/compare/2.3...2.4

`Release 2.3`_ (2015-05-24)
---------------------------

Made it possible to terminate external commands.

.. _Release 2.3: https://github.com/xolox/python-executor/compare/2.2.2...2.3

`Release 2.2.2`_ (2015-05-24)
-----------------------------

Improved logging output of ``CommandPool.run()``.

.. _Release 2.2.2: https://github.com/xolox/python-executor/compare/2.2.1...2.2.2

`Release 2.2.1`_ (2015-05-24)
-----------------------------

Bug fix for import error in ``executor.compat`` module.

.. _Release 2.2.1: https://github.com/xolox/python-executor/compare/2.2...2.2.1

`Release 2.2`_ (2015-05-24)
---------------------------

Properly distinguish writable properties from 'reset-able' properties.

.. _Release 2.2: https://github.com/xolox/python-executor/compare/2.1...2.2

`Release 2.1`_ (2015-05-23)
---------------------------

Added support for concurrent external command execution (command pools).

.. _Release 2.1: https://github.com/xolox/python-executor/compare/2.0...2.1

`Release 2.0`_ (2015-05-23)
---------------------------

- Added support for asynchronous command execution (and lots of small things).
- Improve formatting of ``ExternalCommandFailed`` attributes in documentation.

.. _Release 2.0: https://github.com/xolox/python-executor/compare/1.7.1...2.0

`Release 1.7.1`_ (2015-03-05)
-----------------------------

Fixed ``__version__`` variable corruption introduced in 1.7 :-S.

.. _Release 1.7.1: https://github.com/xolox/python-executor/compare/1.7...1.7.1

`Release 1.7`_ (2015-03-05)
---------------------------

Make it possible to provide overrides for environment variables (`#1`_).

.. _Release 1.7: https://github.com/xolox/python-executor/compare/1.6.2...1.7
.. _#1: https://github.com/xolox/python-executor/issues/1

`Release 1.6.2`_ (2015-03-04)
-----------------------------

- Stop mixing SH and Bash usage (consistently use Bash everywhere).
- Documented that the encoding option is used for input and output
- Added ``tox.ini`` for easy testing and execute ``tox`` using ``make test``.

.. _Release 1.6.2: https://github.com/xolox/python-executor/compare/1.6.1...1.6.2

`Release 1.6.1`_ (2015-03-04)
-----------------------------

Bug fix: Properly close open file handle to ``/dev/null``.

This fixes the following warning emitted by Python 3.4::

  ResourceWarning: unclosed file <_io.BufferedWriter name='/dev/null'>

.. _Release 1.6.1: https://github.com/xolox/python-executor/compare/1.6...1.6.1

`Release 1.6`_ (2014-10-18)
---------------------------

Expose ``pipes.quote()`` wrapping logic as ``executor.quote()``.

.. _Release 1.6: https://github.com/xolox/python-executor/compare/1.5...1.6

`Release 1.5`_ (2014-10-18)
---------------------------

Added support for ``execute(..., silent=True)`` which silences the standard
output and error streams.

.. _Release 1.5: https://github.com/xolox/python-executor/compare/1.4...1.5

`Release 1.4`_ (2014-10-18)
---------------------------

- Extend ``ExternalCommandFailed`` to expose ``command`` and ``returncode`` attributes.
- Get test coverage up to 100%.
- Fixed Sphinx documentation warning about missing static directory.
- Added a simple ``Makefile`` for common project maintenance tasks.

.. _Release 1.4: https://github.com/xolox/python-executor/compare/1.3...1.4

`Release 1.3`_ (2014-06-07)
---------------------------

- Added support for ``fakeroot``.
- Added a ``which()`` function.
- Submit test coverage from Travis CI to Coveralls.

.. _Release 1.3: https://github.com/xolox/python-executor/compare/1.2...1.3

`Release 1.2`_ (2014-05-10)
---------------------------

- Improved Python 3 compatibility:
  - Remove irregular raise syntax.
  - First experience with bytes vs strings.
- Documented supported Python versions (2.6, 2.7 and 3.4).
- Started using Travis CI to automatically run the test suite.

.. _Release 1.2: https://github.com/xolox/python-executor/compare/1.1...1.2

`Release 1.1`_ (2014-05-04)
---------------------------

Improved the documentation.

.. _Release 1.1: https://github.com/xolox/python-executor/compare/1.0...1.1

`Release 1.0`_ (2014-05-04)
---------------------------

Initial commit.

.. _Release 1.0: https://github.com/xolox/python-executor/tree/1.0
