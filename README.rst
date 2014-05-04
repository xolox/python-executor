executor: Programmer friendly subprocess wrapper
================================================

The ``execute()`` function in the ``executor`` package/module is a simple
wrapper for Python's subprocess_ module that makes it very easy to handle
subprocesses on UNIX systems with proper escaping of arguments and error
checking. For usage instructions please refer to the documentation_.

Contact
-------

The latest version of ``executor`` is available on PyPi_ and GitHub_ (although
I don't suppose much will change, since it's so simple). For bug reports please
create an issue on GitHub_. If you have questions, suggestions, etc. feel free
to send me an e-mail at `peter@peterodding.com`_.

License
-------

This software is licensed under the `MIT license`_.

© 2014 Peter Odding.

.. External references:
.. _documentation: https://executor.readthedocs.org
.. _GitHub: https://github.com/xolox/python-executor
.. _MIT license: http://en.wikipedia.org/wiki/MIT_License
.. _peter@peterodding.com: peter@peterodding.com
.. _PyPi: https://pypi.python.org/pypi/executor
.. _subprocess: https://docs.python.org/2/library/subprocess.html
