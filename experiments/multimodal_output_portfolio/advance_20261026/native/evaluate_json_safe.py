"""Mechanical JSON-only wrapper around the unchanged frozen evaluator.

The original evaluator and analysis remain byte-identical. Only that module's
writer and JSON facade normalize NumPy scalar values for JSON serialization.
Model/host IPC, calibration, policy, original owner and source readers are not
patched. The original qualification serialization failure remains in custody.
"""

import argparse
import json as standard_json
from pathlib import Path

from . import evaluate as frozen
from .common import write as original_write


def native_scalars(value):
    if isinstance(value, dict):
        return {key: native_scalars(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [native_scalars(item) for item in value]
    if type(value).__module__.startswith('numpy') and hasattr(value, 'item'):
        return value.item()
    return value


def safe_write(path, value):
    return original_write(path, native_scalars(value))


class ScalarJson:
    loads = staticmethod(standard_json.loads)

    @staticmethod
    def dumps(value, *args, **kwargs):
        return standard_json.dumps(native_scalars(value), *args, **kwargs)


def run(args):
    # These two module-local bindings have no effect on the distinct json
    # globals in the source reader, native client, model host or common writer.
    frozen.write = safe_write
    frozen.json = ScalarJson
    frozen.run(args)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--phase', choices=('qualification', 'confirmation'), required=True)
    for name in ('binary', 'templates', 'protocol', 'settings', 'cache', 'allocation', 'audio-root', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    run(p.parse_args())
