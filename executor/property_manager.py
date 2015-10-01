# Programmer friendly subprocess wrapper.
#
# Author: Peter Odding <peter@peterodding.com>
# Last Change: October 1, 2015
# URL: https://executor.readthedocs.org

"""
Custom computed properties implemented using descriptors.

This module is used by the :mod:`executor` module to implement several types of
computed properties:

- The :class:`required_property` decorator converts a function into a required
  property whose value must be set when an object is created (by providing a
  keyword argument to the constructor). Classes defining required properties
  need to inherit from :class:`PropertyManager`.

- The :class:`cached_property` decorator converts a function into a lazy read
  only property. The value of the property is cached when it is computed the
  first time.

- The :class:`mutable_property` decorator converts a function into a lazy
  property whose value can be changed using normal attribute assignment syntax.

In addition to enabling read only properties the :class:`PropertyManager` class
provides several other enhancements:

- Keyword arguments to the constructor can be used to set properties created
  using :class:`required_property` as well as :class:`mutable_property`.

- The :func:`repr()` of an object shows the names and values of all instance
  properties including required properties, cached properties and mutable
  properties but also properties created using :class:`property`.
"""

# Standard library modules.
import inspect
import numbers
import textwrap

# External dependencies.
from humanfriendly import concatenate, pluralize

# Modules included in our package.
from executor.compat import basestring, bytes, str

# A tuple of types that are known to have useful repr() results.
repr_types = (bool, numbers.Number, bytearray, bytes, str, tuple, list, set, dict)

# Unique object instance.
nothing = object()


class PropertyManager(object):

    """
    Superclass for classes that use the computed properties from this module.

    Provides support for required properties, setting of properties in the
    constructor and generating a useful textual representation of objects with
    properties.
    """

    def __init__(self, **kw):
        """
        Initialize a :class:`PropertyManager` object.

        :param kw: Any keyword arguments are passed on to :func:`set_properties()`.
        """
        self.set_properties(**kw)
        missing = self.missing_properties
        if missing:
            raise TypeError("%s (%s)" % ("missing %s" % pluralize(len(missing), "required argument"),
                                         concatenate(map(repr, sorted(missing)))))

    def set_properties(self, **kw):
        """
        Set instance properties from keyword arguments.

        :param kw: Every keyword argument is used to assign a value to the
                   instance property whose name matches the keyword argument.
        :raises: :exc:`~exceptions.TypeError` when a keyword argument doesn't
                 match a :class:`property` on the given object.
        """
        for name, value in kw.items():
            if self.have_property(name):
                setattr(self, name, value)
            else:
                msg = "got an unexpected keyword argument %r"
                raise TypeError(msg % name)

    @property
    def missing_properties(self):
        """
        The names of required properties that are missing.

        This is a list of strings with the names of required properties that
        either haven't been set or are set to :data:`None`.
        """
        return sorted(n for n in self.required_properties if getattr(self, n, None) is None)

    @property
    def required_properties(self):
        """A list of strings with the names of any required properties."""
        return sorted(n for n in dir(self) if self.have_property(n, required_property))

    def have_property(self, name, *types):
        """
        Check if a (certain type of) property is present.

        :param name: The name of the property (a string).
        :param types: A :class:`tuple` of :class:`type` objects (defaults to
                      matching objects that inherit from :class:`property`).
        """
        value = getattr(self.__class__, name, nothing)
        return value is not nothing and isinstance(value, types or property)

    def __repr__(self):
        """
        Render a human friendly string representation of computed properties.

        Generates a user friendly textual representation for objects that use
        computed properties (:class:`property`, :class:`mutable_property`
        and/or :class:`default_property`).
        """
        fields = []
        for name in dir(self):
            class_value = getattr(self.__class__, name, None)
            # Check if the field is a property defined by a subclass.
            if isinstance(class_value, property) and not hasattr(PropertyManager, name):
                instance_value = getattr(self, name, nothing)
                if instance_value is not nothing and isinstance(instance_value, repr_types):
                    fields.append("%s=%r" % (name, instance_value))
        return "%s(%s)" % (self.__class__.__name__, ", ".join(sorted(fields)))


class custom_property(property):

    """
    Base class for the custom properties defined in the :mod:`~executor.property_manager` module.

    .. note:: The :class:`custom_property` decorator calls the decorated
              function each time the property's value is needed.
    """

    def __init__(self, func, name=None, doc=None):
        """
        Initialize a :class:`custom_property` object.

        :param func: The method that computes the property's value.
        :param name: The name of the property.
        :param doc: The documentation of the property.
        """
        super(custom_property, self).__init__(self, func)
        self.__name__ = name or func.__name__
        self.__module__ = func.__module__
        self.__doc__ = doc or func.__doc__
        self.func = func
        self.patch_documentation()

    def get_note(self):
        """Get a description of the property for the documentation."""
        text = "The :attr:`%s` property is a :class:`.%s` object."
        return text % (self.__name__, self.__class__.__name__)

    def patch_documentation(self):
        """
        Patch the documentation of the property.

        Calls :func:`get_note()` for each superclass of the property to get a
        combined description of the property's usage/behavior.
        """
        if self.__doc__ and isinstance(self.__doc__, basestring):
            blocks = [textwrap.dedent(self.__doc__)]
            # Collect documentation notes from super/subclasses.
            notes = []
            for cls in reversed(inspect.getmro(self.__class__)):
                if hasattr(cls, 'get_note'):
                    text = cls.get_note(self)
                    if text not in notes:
                        notes.append(text)
            if notes:
                blocks.append(".. note:: %s" % " ".join(notes))
            self.__doc__ = "\n\n".join(blocks)

    def __get__(self, obj, type=None):
        """Get the computed value of the property."""
        if obj is None:
            return self
        else:
            return self.func(obj)


class assignable_property(custom_property):

    """
    A property that supports assignment.

    This property is based on :class:`custom_property`, it implements
    assignment by storing the assigned value in the :attr:`~object.__dict__` of
    the object having the property.

    .. note:: The :class:`assignable_property` decorator calls the decorated
              function each time the property's value is needed until a value
              is assigned, at which point the decorated function will no longer
              be called.
    """

    def get_note(self):
        """Get a description of the property for the documentation."""
        return "You can set it using normal attribute assignment syntax."

    def __get__(self, obj, type=None):
        """Get the assigned or computed value of the property."""
        if obj is None:
            return self
        elif self.__name__ in obj.__dict__:
            return obj.__dict__[self.__name__]
        else:
            return self.func(obj)

    def __set__(self, obj, value):
        """Override the computed value of the property."""
        obj.__dict__[self.__name__] = value


class resetable_property(custom_property):

    """
    A property that can be reset using :keyword:`del` and :func:`delattr()`.

    This property is based on :class:`custom_property`, it implements deletion
    by removing the value in the :attr:`~object.__dict__` of the object having
    the property.

    The :class:`resetable_property` decorator is not useful in isolation, it
    has to be combined with :class:`assignable_property` or a subclass of
    :class:`assignable_property`.

    .. note:: The :class:`resetable_property` decorator calls the decorated
              function each time the property's value is needed until a value
              is assigned, at which point the decorated function will no longer
              be called. When the property's value is deleted the decorator
              will resume the previous behavior of computing the property's
              value each it is needed.
    """

    def get_note(self):
        """Get a description of the property for the documentation."""
        return "You can reset it to its default value using :keyword:`del` or :func:`delattr()`."

    def __delete__(self, obj):
        """Reset the assigned value of a property, reverting back to the computed value."""
        obj.__dict__.pop(self.__name__)


class required_property(assignable_property):

    """
    A property that requires a value to be set.

    Required properties must be set by providing keyword arguments to the
    constructor of the relevant type. When :func:`PropertyManager.__init__()`
    notices that required properties haven't been set
    :exc:`~exceptions.TypeError` is raised.
    """

    def get_note(self):
        """Get a description of the property for the documentation."""
        text = ("You're required to provide a value for this property by"
                " calling the constructor of the class that defines the"
                " property with a keyword argument named `%s`.")
        return text % self.__name__


class cached_property(resetable_property):

    """
    A decorator that converts a function into a lazy read only property.

    The function wrapped is called the first time to retrieve the result and
    then that calculated result is used the next time you access the value.

    The class has to have a `__dict__` in order for :class:`cached_property` to
    work.

    This :class:`cached_property` implementation is based on the implementation
    included in Werkzeug_.

    .. _Werkzeug: https://github.com/mitsuhiko/werkzeug/blob/master/werkzeug/utils.py
    """

    def get_note(self):
        """Get a description of the property for the documentation."""
        return "Its value is computed once (the first time the property is accessed) and the result is cached."

    def __get__(self, obj, type=None):
        """Get the cached or computed value of the property."""
        if obj is None:
            return self
        value = obj.__dict__.get(self.__name__, nothing)
        if value is nothing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value


class mutable_property(resetable_property, assignable_property):

    """
    A decorator that converts a function into a property which supports assignment.

    Works the same as :class:`cached_property` but additionally supports
    assignment to override the default computed value of the property.
    """
