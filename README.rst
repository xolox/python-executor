executor: Programmer friendly subprocess wrapper
================================================

.. image:: https://travis-ci.org/xolox/python-executor.svg?branch=master
   :target: https://travis-ci.org/xolox/python-executor

.. image:: https://coveralls.io/repos/xolox/python-executor/badge.png?branch=master
   :target: https://coveralls.io/r/xolox/python-executor?branch=master

The ``executor`` package/module is a simple wrapper for Python's subprocess_
module that makes it very easy to handle subprocesses on UNIX systems with
proper escaping of arguments and error checking. It's currently tested on
Python 2.6, 2.7, 3.4 and PyPy. For usage instructions please refer to the
documentation_.

Examples of usage
-----------------

Below are some examples of how versatile the `execute()`_ function is.

Checking status codes
~~~~~~~~~~~~~~~~~~~~~

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
executor.ExternalCommandFailed: External command failed with exit code 1! (command: bash -c false)

The ExternalCommandFailed_ exception exposes ``command`` and ``returncode``
attributes. If you know a command is likely to exit with a nonzero status code
and you want `execute()`_ to simply return a boolean you can do this instead:

>>> execute('false', check=False)
False

Providing input
~~~~~~~~~~~~~~~

Here's how you can provide input to an external command:

>>> execute('tr a-z A-Z', input='Hello world from Python!\n')
HELLO WORLD FROM PYTHON!
True

Getting output
~~~~~~~~~~~~~~

Getting the output of external commands is really easy as well:

>>> execute('hostname', capture=True)
'peter-macbook'

Running commands as root
~~~~~~~~~~~~~~~~~~~~~~~~

It's also very easy to execute commands with super user privileges:

>>> execute('echo test > /etc/hostname', sudo=True)
[sudo] password for peter: **********
True
>>> execute('hostname', capture=True)
'test'

Enabling logging
~~~~~~~~~~~~~~~~

If you're wondering how prefixing the above command with ``sudo`` would
end up being helpful, here's how it works:

>>> import logging
>>> logging.basicConfig()
>>> logging.getLogger().setLevel(logging.DEBUG)
>>> execute('echo peter-macbook > /etc/hostname', sudo=True)
DEBUG:executor:Executing external command: sudo bash -c 'echo peter-macbook > /etc/hostname'

Running remote commands
~~~~~~~~~~~~~~~~~~~~~~~

To run a command on a remote system using SSH you can use the RemoteCommand_
class, it works as follows:

>>> from executor.ssh.client import RemoteCommand
>>> cmd = RemoteCommand('localhost', 'echo $SSH_CONNECTION', capture=True)
>>> cmd.start()
>>> cmd.output
'127.0.0.1 57255 127.0.0.1 22'

Running remote commands concurrently
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The `foreach()`_ function wraps the RemoteCommand_ and CommandPool_ classes to
make it very easy to run a remote command concurrently on a group of hosts:

>>> from executor.ssh.client import foreach
>>> from pprint import pprint
>>> hosts = ['127.0.0.1', '127.0.0.2', '127.0.0.3', '127.0.0.4']
>>> commands = foreach(hosts, 'echo $SSH_CONNECTION')
>>> pprint([cmd.output for cmd in commands])
['127.0.0.1 57278 127.0.0.1 22',
 '127.0.0.1 52385 127.0.0.2 22',
 '127.0.0.1 49228 127.0.0.3 22',
 '127.0.0.1 40628 127.0.0.4 22']

Contact
-------

The latest version of ``executor`` is available on PyPI_ and GitHub_. The
documentation is hosted on `Read the Docs`_. For bug reports please create an
issue on GitHub_. If you have questions, suggestions, etc. feel free to send me
an e-mail at `peter@peterodding.com`_.

License
-------

This software is licensed under the `MIT license`_.

© 2015 Peter Odding.

.. External references:
.. _CommandPool: https://executor.readthedocs.org/en/latest/#executor.concurrent.CommandPool
.. _documentation: https://executor.readthedocs.org
.. _execute(): http://executor.readthedocs.org/en/latest/#executor.execute
.. _ExternalCommandFailed: http://executor.readthedocs.org/en/latest/#executor.ExternalCommandFailed
.. _foreach(): https://executor.readthedocs.org/en/latest/#executor.ssh.client.foreach
.. _GitHub: https://github.com/xolox/python-executor
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPI: https://pypi.python.org/pypi/executor
.. _Read the Docs: https://executor.readthedocs.org
.. _RemoteCommand: https://executor.readthedocs.org/en/latest/#executor.ssh.client.RemoteCommand
.. _subprocess: https://docs.python.org/2/library/subprocess.html
