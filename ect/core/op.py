"""
Module Description
==================

This modules provides classes and functions allowing to maintain *operations*.

Design targets:

* Simplicity - exploit Python language to let users express an operation in an intuitive form.
* Stay with Python base types instead og introducing a number of new data structures.
* Derive meta information such as names, types and documentation for the operation, its inputs, and its outputs from
  Python code
* An operation should be able to explain itself when used in a REPL in terms of its algorithms, its inputs, and its
  outputs.
* Three simple class annotations shall be used to decorate operations classes: an optional ``operation`` decorator,
  one or more ``input``, ``output`` decorators.
* Operation registration is done by operation class annotations.
* It shall be possible to register any Python-callable of the from ``op(*args, **kwargs)`` as an operation.
* Initial operation meta information will be derived from Python code introspection
* Operations should take an optional *monitor* which will be passed by the framework to observe the progress and
  to cancel an operation


Module Reference
================
"""

from collections import OrderedDict
from inspect import isclass
from typing import Dict

from .monitor import Monitor
from .util import object_to_qualified_name, Namespace


class OpMetaInfo:
    """
    Meta-information about an operation.

    :param op_qualified_name: The operation's qualified name.
    """

    def __init__(self, op_qualified_name: str, header: dict = None, input: dict = None, output: dict = None):
        self._qualified_name = op_qualified_name
        self._header = header if header else OrderedDict()
        self._input_namespace = Namespace()
        if input:
            for name, value in input.items():
                self._input_namespace[name] = value
        self._output_namespace = Namespace()
        if output:
            for name, value in output.items():
                self._output_namespace[name] = value

    #: The constant ``'monitor'``, which is the name of an operation input that will
    #: receive a :py:class:`Monitor` object as value.
    MONITOR_INPUT_NAME = 'monitor'

    #: The constant ``'return'``, which is the name of a single, unnamed operation output.
    RETURN_OUTPUT_NAME = 'return'

    @property
    def qualified_name(self) -> str:
        """
        :return: Fully qualified name of the actual operation.
        """
        return self._qualified_name

    @property
    def header(self) -> dict():
        """
        :return: Operation header attributes.
        """
        return self._header

    @property
    def input(self) -> Namespace:
        """
        Mapping from an input name to a dictionary of properties describing the input.

        :return: Named input slots.
        """
        return self._input_namespace

    @property
    def output(self) -> Namespace:
        """
        Mapping from an output name to a dictionary of properties describing the output.

        :return: Named input slots.
        """
        return self._output_namespace

    @property
    def has_monitor(self) -> bool:
        """
        :return: ``True`` if the output value of the operation is expected be a dictionary-like mapping of output names
                 to output values.
        """
        return self.MONITOR_INPUT_NAME in self._input_namespace

    @property
    def has_named_outputs(self) -> bool:
        """
        :return: ``True`` if the output value of the operation is expected be a dictionary-like mapping of output names
                 to output values.
        """
        return not (len(self._output_namespace) == 1 and self.RETURN_OUTPUT_NAME in self._output_namespace)

    def to_json_dict(self):
        """
        Return a JSON-serializable dictionary representation of this object. E.g. values of the `data_type``
        property are converted from Python types to their string representation.

        :return: A JSON-serializable dictionary
        """

        def io_namespace_to_dict(io_def_namespace: Namespace):
            io_dict = OrderedDict(io_def_namespace)
            for name, properties in io_dict.items():
                properties_copy = dict(properties)
                if 'data_type' in properties_copy:
                    properties_copy['data_type'] = object_to_qualified_name(properties_copy['data_type'])
                io_dict[name] = properties_copy
            return io_dict

        json_dict = OrderedDict()
        json_dict['qualified_name'] = self.qualified_name
        json_dict['header'] = OrderedDict(self.header)
        json_dict['input'] = io_namespace_to_dict(self.input)
        json_dict['output'] = io_namespace_to_dict(self.output)
        return json_dict

    # todo (nf) - add missing test
    @classmethod
    def from_json_dict(cls, json_dict):
        op_meta_info = OpMetaInfo(json_dict.get('qualified_name', None),
                                  header=json_dict.get('header', None))
        input = json_dict.get('input', OrderedDict())
        for name, value in input.items():
            op_meta_info.input[name] = value
        output = json_dict.get('output', OrderedDict())
        for name, value in output.items():
            op_meta_info.output[name] = value
        return op_meta_info

    def __str__(self):
        return "OpMetaInfo('%s')" % self.qualified_name

    def __repr__(self):
        return "OpMetaInfo('%s')" % self.qualified_name

    @classmethod
    def introspect_operation(cls, operation) -> 'OpMetaInfo':
        if not operation:
            raise ValueError('operation object must be given')
        op_qualified_name = object_to_qualified_name(operation, fail=True)
        op_meta_info = OpMetaInfo(op_qualified_name)
        # Introspect the operation instance (see https://docs.python.org/3.5/library/inspect.html)
        if hasattr(operation, '__doc__'):
            # documentation string
            op_meta_info.header['description'] = operation.__doc__
        if hasattr(operation, '__code__'):
            cls._introspect_function(op_meta_info, operation, False)
        if isclass(operation):
            if hasattr(operation, '__call__'):
                call_method = getattr(operation, '__call__')
                cls._introspect_function(op_meta_info, call_method, True)
            else:
                raise ValueError('operations of type class must define a __call__(self, ...) method')
        if hasattr(operation, '__annotations__'):
            # mapping of parameters names to annotations; 'return' key is reserved for return annotations.
            annotations = operation.__annotations__
            for annotated_name, annotated_type in annotations.items():
                if annotated_name == 'return':
                    # meta_info.output can't be present so far -> assign new dict
                    op_meta_info.output[OpMetaInfo.RETURN_OUTPUT_NAME] = dict(data_type=annotated_type)
                else:
                    # meta_info.input may be present already, through _introspect_function() call
                    op_meta_info.input[annotated_name]['data_type'] = annotated_type
        if len(op_meta_info.output) == 0:
            op_meta_info.output[OpMetaInfo.RETURN_OUTPUT_NAME] = dict()
        return op_meta_info

    @classmethod
    def _introspect_function(cls, op_meta_info, operation, is_method):
        # code object containing compiled function bytecode
        if not hasattr(operation, '__code__'):
            # Check: throw exception here?
            return
        code = operation.__code__
        # number of arguments (not including * or ** args)
        arg_count = code.co_argcount
        # tuple of names of arguments and local variables
        arg_names = code.co_varnames[0:arg_count]
        if len(arg_names) > 0 and is_method and arg_names[0] == 'self':
            arg_names = arg_names[1:]
            arg_count -= 1
        # Reserve input slots for all arguments
        for arg_name in arg_names:
            op_meta_info.input[arg_name] = dict()
        # Set 'default_value' for input
        if operation.__defaults__:
            # tuple of any default values for positional or keyword parameters
            default_values = operation.__defaults__
            num_default_values = len(default_values)
            for i in range(num_default_values):
                arg_name = arg_names[i - num_default_values]
                op_meta_info.input[arg_name]['default_value'] = default_values[i]


class OpRegistration:
    """
    A registered operation comprises the actual operation object, which may be a class or any callable, and
    meta-information about the operation.

    :param operation: the actual class or any callable object.
    """

    def __init__(self, operation):
        self._meta_info = OpMetaInfo.introspect_operation(operation)
        self._operation = operation

    @property
    def meta_info(self):
        """
        :return: Meta-information about the operation, see :py:class:`ect.core.op.OpMetaInfo`.
        """
        return self._meta_info

    @property
    def operation(self):
        """
        :return: The actual operation object which may be a class or any callable.
        """
        return self._operation

    def __str__(self):
        return '%s: %s' % (self.operation, self.meta_info)

    def __call__(self, monitor: Monitor = Monitor.NULL, **input_values):
        """
        Perform this operation.

        :param monitor: an optional progress monitor, which is passed to the wrapped callable, if it supports it.
        :param input_values: the input values
        :return: the output value(s).
        """

        # set default_value where input values are missing
        for name, properties in self.meta_info.input:
            if name not in input_values:
                input_values[name] = properties.get('default_value', None)

        # validate the input_values using this operation's meta-info
        self.validate_input_values(input_values)

        if self.meta_info.has_monitor:
            # set the monitor only if it is an argument
            input_values[self.meta_info.MONITOR_INPUT_NAME] = monitor

        operation = self.operation
        if isclass(operation):
            # create object instance
            operation_instance = operation()
            # call the instance
            return_value = operation_instance(**input_values)
        else:
            # call the function/method/callable/?
            return_value = operation(**input_values)

        if self.meta_info.has_named_outputs:
            # return_value is expected to be a dictionary-like object
            # set default_value where output values in return_value are missing
            for name, properties in self.meta_info.output:
                if name not in return_value or return_value[name] is None:
                    return_value[name] = properties.get('default_value', None)
            # validate the return_value using this operation's meta-info
            self.validate_output_values(return_value)
        else:
            # return_value is a single value, not a dict
            # set default_value if return_value is missing
            if return_value is None:
                properties = self.meta_info.output[OpMetaInfo.RETURN_OUTPUT_NAME]
                return_value = properties.get('default_value', None)
            # validate the return_value using this operation's meta-info
            self.validate_output_values({OpMetaInfo.RETURN_OUTPUT_NAME: return_value})
        return return_value

    def validate_input_values(self, input_values: Dict):
        inputs = self.meta_info.input
        for name, value in input_values.items():
            if name not in inputs:
                raise ValueError("'%s' is not an input of operation '%s'" % (name, self.meta_info.qualified_name))
            input_properties = inputs[name]
            if value is None:
                if input_properties.get('required', False):
                    raise ValueError(
                        "input '%s' for operation '%s' required" % (name, self.meta_info.qualified_name))
            else:
                data_type = input_properties.get('data_type', None)
                is_float_type = data_type is float and (isinstance(value, float) or isinstance(value, int))
                if data_type and not (isinstance(value, data_type) or is_float_type):
                    raise ValueError(
                        "input '%s' for operation '%s' must be of type %s" % (
                            name, self.meta_info.qualified_name, data_type))
                value_set = input_properties.get('value_set', None)
                if value_set and value not in value_set:
                    raise ValueError(
                        "input '%s' for operation '%s' must be one of %s" % (
                            name, self.meta_info.qualified_name, value_set))
                value_range = input_properties.get('value_range', None)
                if value_range and not (value_range[0] <= value <= value_range[1]):
                    raise ValueError(
                        "input '%s' for operation '%s' must be in range %s" % (
                            name, self.meta_info.qualified_name, value_range))

    def validate_output_values(self, output_values: Dict):
        outputs = self.meta_info.output
        for name, value in output_values.items():
            if name not in outputs:
                raise ValueError("'%s' is not an output of operation '%s'" % (name, self.meta_info.qualified_name))
            output_properties = outputs[name]
            if value is not None:
                data_type = output_properties.get('data_type', None)
                if data_type and not isinstance(value, data_type):
                    raise ValueError(
                        "output '%s' for operation '%s' must be of type %s" % (
                            name, self.meta_info.qualified_name, data_type))


class OpRegistry:
    """
    An operation registry allows for addition, removal, and retrieval of operations.
    """

    def __init__(self):
        self._op_registrations = OrderedDict()

    @property
    def op_registrations(self) -> OrderedDict:
        """
        Get all operation registrations of type :py:class:`ect.core.op.OpRegistration`.

        :return: a mapping of fully qualified operation names to operation registrations
        """
        return OrderedDict(sorted(self._op_registrations.items(), key=lambda name: name[0]))

    def add_op(self, operation, fail_if_exists=True) -> OpRegistration:
        """
        Add a new operation registration.

        :param operation: A operation object such as a class or any callable.
        :param fail_if_exists: raise ``ValueError`` if the operation was already registered
        :return: a :py:class:`ect.core.op.OpRegistration` object
        """
        op_qualified_name = object_to_qualified_name(operation)
        if op_qualified_name in self._op_registrations:
            if fail_if_exists:
                raise ValueError("operation with name '%s' already registered" % op_qualified_name)
            else:
                return self._op_registrations[op_qualified_name]
        op_registration = OpRegistration(operation)
        self._op_registrations[op_qualified_name] = op_registration
        return op_registration

    def remove_op(self, operation, fail_if_not_exists=False) -> OpRegistration:
        """
        Remove an operation registration.

        :param operation: A fully qualified operation name or registered operation object such as a class or callable.
        :param fail_if_not_exists: raise ``ValueError`` if no such operation was found
        :return: the removed :py:class:`ect.core.op.OpRegistration` object or ``None``
                 if *fail_if_not_exists* is ``False``.
        """
        op_qualified_name = operation if isinstance(operation, str) else object_to_qualified_name(operation)
        if op_qualified_name not in self._op_registrations:
            if fail_if_not_exists:
                raise ValueError("operation with name '%s' not registered" % op_qualified_name)
            else:
                return None
        return self._op_registrations.pop(op_qualified_name)

    def get_op(self, operation, fail_if_not_exists=False) -> OpRegistration:
        """
        Get an operation registration.

        :param operation: A fully qualified operation name or registered operation object such as a class or callable.
        :param fail_if_not_exists: raise ``ValueError`` if no such operation was found
        :return: a :py:class:`ect.core.op.OpRegistration` object or ``None`` if *fail_if_not_exists* is ``False``.
        """
        op_qualified_name = operation if isinstance(operation, str) else object_to_qualified_name(operation)
        op_registration = self._op_registrations.get(op_qualified_name, None)
        if op_registration is None and fail_if_not_exists:
            raise ValueError("operation with name '%s' not registered" % op_qualified_name)
        return op_registration


class _DefaultOpRegistry(OpRegistry):
    def __repr__(self):
        return 'REGISTRY'


# check (nf) - for more flexibility, REGISTRY may be configured by dependency injection
# see Python libs 'pinject' (Google), 'inject', and others

#: The default operation registry of type :py:class:`ect.core.op.OpRegistry`.
REGISTRY = _DefaultOpRegistry()


def op(registry=REGISTRY):
    """
    Classes or functions annotated by this decorator are added to the given *registry*.
    Classes annotated by this decorator must have callable instances. Callable instances
    and functions must have the following signature:

        operation(**input_values) -> dict

    :param registry: The operation registry.
    """

    def _op(operation):
        registry.add_op(operation, fail_if_exists=False)
        return operation

    return _op


def op_input(input_name: str,
             default_value=None,
             required=None,
             data_type=None,
             value_set=None,
             value_range=None,
             registry=REGISTRY,
             **kwargs):
    """
    Define an operation input.
    This is a decorator function used to annotate classes or functions which are added the given *registry*
    (if not already done) and are assigned a new input with the given *input_name*.

    :param input_name: The name of an input.
    :param required: If ``True``, a value must be provided, otherwise *default_value* is used.
    :param default_value: A default value.
    :param data_type: The data type of the input values.
    :param value_set: A sequence of the valid values. Note that all values in this sequence
                      must be compatible with *data_type*.
    :param value_range: A sequence specifying the possible range of valid values.
    :param registry: The operation registry.
    """

    def decorator(operation):
        op_registration = registry.add_op(operation, fail_if_exists=False)
        input_namespace = op_registration.meta_info.input
        if input_name not in input_namespace:
            input_namespace[input_name] = dict()
        input_properties = input_namespace[input_name]
        new_properties = dict(data_type=data_type,
                              default_value=default_value,
                              required=required,
                              value_set=value_set,
                              value_range=value_range, **kwargs)
        _update_properties(input_properties, new_properties)
        return operation

    return decorator


def op_output(output_name: str,
              data_type=None,
              registry=REGISTRY,
              **kwargs):
    """
    Define an operation output.
    This is a decorator function used to annotate classes or functions which are added the given *registry*
    (if not already done) and are assigned a new output with the given *output_name*.

    :param output_name: The name of the output.
    :param data_type: The data type of the output value.
    :param registry: The operation registry.
    """

    def _op_output(operation):
        op_registration = registry.add_op(operation, fail_if_exists=False)
        output_namespace = op_registration.meta_info.output
        if not op_registration.meta_info.has_named_outputs:
            # if there is only one entry and it is the 'return' entry, rename it to value of output_name
            output_properties = output_namespace[OpMetaInfo.RETURN_OUTPUT_NAME]
            del output_namespace[OpMetaInfo.RETURN_OUTPUT_NAME]
            output_namespace[output_name] = output_properties
        elif output_name not in output_namespace:
            output_namespace[output_name] = dict()
        output_properties = output_namespace[output_name]
        new_properties = dict(data_type=data_type, **kwargs)
        _update_properties(output_properties, new_properties)
        return operation

    return _op_output


def op_return(data_type=None,
              registry=REGISTRY,
              **kwargs):
    """
    Define an operation's single return value.
    This is a decorator function used to annotate classes or functions which are added the given *registry*
    (if not already done) and are assigned a new single output.

    :param data_type: The data type of the output value.
    :param registry: The operation registry.
    """
    return op_output(OpMetaInfo.RETURN_OUTPUT_NAME,
                     data_type=data_type,
                     registry=registry,
                     **kwargs)


def _update_properties(old_properties: dict, new_properties: dict):
    for name, value in new_properties.items():
        if value is not None and (name not in old_properties or old_properties[name] is None):
            old_properties[name] = value
