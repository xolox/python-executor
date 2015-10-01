# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 1, 2015
# URL: https://executor.readthedocs.org

"""
Some aliases to make it easier to support both Python 2 and 3.

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


try:
    # Enable importing of basestring from this module. This will raise
    # NameError on Python 3 because basestring is no longer available.
    basestring = basestring
    # Alias bytes to str.
    bytes = str
    # Alias str to unicode.
    str = unicode
except NameError:
    # Alias basestring to str.
    basestring = str
    # Enable importing of bytes and str from this module.
    bytes = bytes
    str = str
