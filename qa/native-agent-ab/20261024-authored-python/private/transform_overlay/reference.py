from copy import deepcopy

DELETE = object()


def merge(base, override):
    result = deepcopy(base)
    for key, value in override.items():
        if value is DELETE:
            result.pop(key, None)
        elif isinstance(value, dict):
            old = result.get(key)
            result[key] = merge(old if isinstance(old, dict) else {}, value)
        else:
            result[key] = deepcopy(value)
    return result
