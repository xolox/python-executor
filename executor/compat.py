# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 24, 2015
# URL: https://executor.readthedocs.org

"""
The :mod:`executor.compat` module
=================================

Simple tools to make it easier to write Python code that is compatible with
Python 2 as well as Python 3.

.. class:: basestring

   A reference to :func:`python2:basestring` in Python 2 and
   :class:`python3:str` in Python 3.

.. class:: bytes

   A reference to :class:`python2:str` in Python 2 and :class:`python3:bytes`
   in Python 3.

.. class:: unicode

   A reference to :func:`python2:unicode` in Python 2 and :class:`python3:str`
   in Python 3.
"""

# Standard library modules.
import sys

# Make Python 2 look like Python 3.
if sys.version_info[0] == 2:
    basestring = basestring
    bytes = str
    str = unicode

# Make Python 3 look like Python 2.
if sys.version_info[0] == 3:
    basestring = str
