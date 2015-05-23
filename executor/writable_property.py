# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 23, 2015
# URL: https://executor.readthedocs.org

"""
The :mod:`executor.writable_property` module
============================================

This module is used by the :mod:`executor` module to implement the many
writable properties on the :class:`~executor.ExternalCommand` class and their
handling in :class:`~executor.ExternalCommand.__init__()` .

The :class:`writable_property` class is a simple variant of the
:class:`property` method decorator (a descriptor) that provides the computed
return value of the decorated method by default but supports assignment to
override the value. Overrides can be cleared (resetting the property to its
'default value') using :keyword:`del` or :func:`delattr()`.

The :func:`override_properties()` function can be used to easily and safely
store a set of keyword arguments as writable properties on an object that has
properties decorated with :class:`writable_property`.
"""

# Standard library modules.
import textwrap

class writable_property(object):

    """Variant of :class:`property` that allows assignment and can be reset to its default value."""

    def __init__(self, func):
        self.func = func
        self.__doc__ = getattr(self.func, '__doc__')
        if self.__doc__:
            self.__doc__ = textwrap.dedent(self.__doc__) + "\n\n.. note:: You can change the value of this property using regular attribute assignment syntax. To restore its default value use :keyword:`del` or :func:`delattr`."

    def __get__(self, instance, owner):
        if instance is None:
            return self
        elif self.func.__name__ in instance.__dict__:
            return instance.__dict__[self.func.__name__]
        else:
            default_value = self.func(instance)
            instance.__dict__[self.func.__name__] = default_value
            return default_value

    def __set__(self, instance, value):
        instance.__dict__[self.func.__name__] = value

    def __delete__(self, instance):
        if self.func.__name__ in instance.__dict__:
            del instance.__dict__[self.func.__name__]


def override_properties(obj, **kw):
    """
    Override writable instance properties with a dictionary of name, value pairs.

    :param obj: The object whose properties should be overridden.
    :param kw: Every keyword argument is used to set the property of the same
               name on the given object.
    :raises: :exc:`~exceptions.TypeError` when a keyword argument doesn't match
             a :class:`writable_property` on the given object.
    """
    cls = type(obj)
    for name, value in kw.items():
        if isinstance(getattr(cls, name, None), writable_property):
            setattr(obj, name, value)
        else:
            # Make sure keyword arguments for unsupported options still
            # raise the same type of exception (it feels kind of ugly that
            # I have to re-implement this logic).
            msg = "got an unexpected keyword argument %r"
            raise TypeError(msg % name)
