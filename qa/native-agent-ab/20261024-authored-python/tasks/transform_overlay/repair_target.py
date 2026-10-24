DELETE = object()


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if value is DELETE:
            result.pop(key, None)
        elif not value:
            continue
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result
