# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: May 24, 2015
# URL: https://executor.readthedocs.org

"""
The :mod:`executor.writable_property` module
============================================

This module is used by the :mod:`executor` module to implement the many
writable properties on the :class:`~executor.ExternalCommand` class and their
handling in :class:`~executor.ExternalCommand.__init__()`:

- The :class:`writable_property` class is a subclass of the :class:`property`
  method decorator which adds support for assignment to properties.

- The :class:`default_property` class is a subclass of
  :class:`writable_property` that adds support for deletion using
  :keyword:`del` or :func:`delattr()` to reset the property to
  its default (computed) value.

- The :func:`override_properties()` function can be used to easily and safely
  store a set of keyword arguments as writable properties on an object that has
  properties decorated with :class:`writable_property` and/or
  :class:`default_property`.

- The :func:`property_repr()` function can be used to create a user friendly
  textual representation of an object that uses computed properties.
"""

# Standard library modules.
import numbers
import textwrap

# Modules included in our package.
from executor.compat import basestring, bytes, str

# A tuple of types that are known to have useful repr() results.
repr_types = (bool, numbers.Number, bytearray, bytes, str, tuple, list, set, dict)


class writable_property(property):

    """
    Subclass of :class:`property` that allows assignment.
    """

    def __init__(self, func):
        self.func = func
        self.name = getattr(func, '__name__')
        documentation = getattr(func, '__doc__')
        if isinstance(documentation, basestring):
            self.__doc__ = textwrap.dedent(documentation) + u"\n\n" + (
                u".. note:: You can change the value of this property"
                u" using regular attribute assignment syntax.\n"
            )

    def __get__(self, instance, owner):
        if instance is None:
            return self
        elif self.name in instance.__dict__:
            return instance.__dict__[self.name]
        else:
            default_value = self.func(instance)
            instance.__dict__[self.name] = default_value
            return default_value

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value


class default_property(writable_property):

    """
    Subclass of :class:`writable_property` that can be reset to its "default" value.
    """

    def __init__(self, func):
        super(default_property, self).__init__(func)
        documentation = getattr(self, '__doc__')
        if isinstance(documentation, basestring):
            self.__doc__ = textwrap.dedent(documentation) + (
                u" To restore its default value use"
                u" :keyword:`del` or :func:`delattr`."
            )

    def __delete__(self, instance):
        if self.name in instance.__dict__:
            del instance.__dict__[self.name]


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


def property_repr(obj):
    """
    Generate a user friendly textual representation of an object that uses
    computed properties (:class:`property`, :class:`writable_property` and/or
    :class:`default_property`).
    """
    fields = []
    cls = obj.__class__
    for attribute_name in dir(obj):
        class_value = getattr(cls, attribute_name, None)
        if isinstance(class_value, property):
            instance_value = getattr(obj, attribute_name)
            if isinstance(instance_value, repr_types):
                fields.append("%s=%r" % (attribute_name, instance_value))
    return "%s(%s)" % (cls.__name__, ", ".join(sorted(fields)))
