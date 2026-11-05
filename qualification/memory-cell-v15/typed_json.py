"""Exact typed JSON output comparison for the worker and offline diagnostics.

Only plain JSON runtime values are accepted. Booleans, integers and floats are
distinct types: True != 1 and 1 != 1.0 deliberately. Finite floats compare by
numeric value, so -0.0 == 0.0. Object key order is irrelevant; array order is not.
Tuple/set/bytes, non-string object keys, subclasses and custom equality hooks are
rejected instead of being silently converted. Nonfinite floats are rejected.
"""

import math


def _value(value):
    kind = type(value)
    if value is None:
        return ("null",)
    if kind is bool or kind is int or kind is str:
        return (kind.__name__, value)
    if kind is float:
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON value")
        return ("float", value)
    if kind is list:
        return ("array", tuple(_value(item) for item in value))
    if kind is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("JSON object keys must be plain strings")
        return ("object", tuple((key, _value(value[key])) for key in sorted(value)))
    raise TypeError("unsupported JSON runtime value")


def equal_json(actual, expected):
    """Compare validated typed values without calling arbitrary object __eq__."""
    return _value(actual) == _value(expected)
