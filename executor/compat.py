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

if sys.version_info[0] == 2:
    # Enable importing of basestring from this module.
    basestring = basestring
    # Alias bytes to str.
    bytes = str
    # Alias str to unicode.
    str = unicode
elif sys.version_info[0] == 3:
    # Alias basestring to str.
    basestring = str
    # Enable importing of bytes and str from this module.
    bytes = bytes
    str = str
