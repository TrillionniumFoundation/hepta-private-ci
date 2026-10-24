"""Classify a module snapshot, hashing only real files inside the source root.

Relative/virtual origins are never resolved against cwd. Missing or unreadable
source files fail collection; non-file records never imply byte attestation.
"""
import hashlib
import os
from pathlib import Path


def collect_module_origins(modules, source_root):
    root = Path(source_root).resolve(strict=True)
    records, source = {}, {}
    for name, module in tuple(modules.items()):
        try:
            raw = vars(module).get('__file__')
        except TypeError:
            records[name] = {'kind': 'no_module_dictionary'}
            continue
        if raw is None:
            records[name] = {'kind': 'no_file_attribute'}
            continue
        if not isinstance(raw, (str, bytes)):
            records[name] = {'kind': 'non_path_file_attribute', 'type': type(raw).__name__}
            continue
        path = Path(os.fsdecode(raw))
        if not path.is_absolute():
            records[name] = {'kind': 'relative_or_virtual', 'file': str(path)}
            continue
        # Do not hash external dependencies or invent their content identities.
        if not path.is_relative_to(root):
            records[name] = {'kind': 'external_absolute_unhashed', 'file': str(path)}
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise ValueError(f'source module escapes root: {name}')
        if not resolved.is_file():
            raise ValueError(f'source module is not a regular file: {name}')
        data = resolved.read_bytes()  # Real I/O failures remain fatal.
        item = {'path': str(resolved.relative_to(root)), 'bytes': len(data),
                'sha256': hashlib.sha256(data).hexdigest()}
        source[name] = item
        records[name] = {'kind': 'source_file_hashed', **item}
    return {'source_module_origins': source, 'module_origins': records,
            'complete_dynamic_import_attestation': False}
