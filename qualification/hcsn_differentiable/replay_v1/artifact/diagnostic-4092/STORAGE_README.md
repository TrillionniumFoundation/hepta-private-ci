# Lossless storage for the original branch files

This directory retains historical evidence under its original source identity.
The merge changes storage containers only. It establishes no new native test,
training, model execution, independent replay or production acceptance.

`MERGE_STORAGE.json` maps every original branch file to its current storage,
including original Git blob, mode, byte count and SHA-256. Every reconstructed
file was compared byte for byte with the original Git blob. All stored files
remain below the unchanged 512000-byte repository limit; no exception is added.

For gzip evidence storage, original log and patch bytes are unchanged. Physical storage fields
in current log indices point to the gzip files. Exact prior index JSON is also
retained as gzip so that the complete original source package can be restored.
Historical receipt paths and hashes continue to identify the original bytes.

For an archive stored as ordered gzip chunks, decompress each numbered chunk
independently and concatenate the raw chunks in manifest order. The resulting
archive has the original byte count and SHA-256. These are storage fragments,
not separate experiments or new training results. The original archive manifest
and publication receipts remain unchanged.

## Restore to a new directory

Run this snippet from this directory. Choose a new output directory outside the
repository. It refuses an existing output directory, verifies every stored and
reconstructed digest, and restores the original relative paths and file modes.
The original indices will then resolve their original paths in that directory.

```python
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath

source = Path.cwd()
destination = Path('/tmp/hepta-original-evidence')
destination.mkdir(parents=True, exist_ok=False)
manifest = json.loads((source / 'MERGE_STORAGE.json').read_bytes())

def checked_file(record):
    relative = PurePosixPath(record['stored_path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe stored path')
    data = (source / relative).read_bytes()
    if len(data) != record['stored_bytes'] or hashlib.sha256(data).hexdigest() != record['stored_sha256']:
        raise ValueError('stored file identity mismatch')
    return data

for record in manifest['original_files']:
    if record['encoding'] == 'ordered-gzip-chunks':
        pieces = []
        offset = 0
        for number, part in enumerate(record['chunks'], 1):
            if part['ordinal'] != number or part['offset'] != offset:
                raise ValueError('chunk order mismatch')
            piece = gzip.decompress(checked_file(part))
            if len(piece) != part['original_bytes'] or hashlib.sha256(piece).hexdigest() != part['original_sha256']:
                raise ValueError('original chunk identity mismatch')
            pieces.append(piece)
            offset += len(piece)
        original = b''.join(pieces)
    elif record['encoding'] == 'gzip':
        original = gzip.decompress(checked_file(record))
    elif record['encoding'] == 'identity':
        original = checked_file(record)
    else:
        raise ValueError('unknown encoding')
    if len(original) != record['original_bytes'] or hashlib.sha256(original).hexdigest() != record['original_sha256']:
        raise ValueError('original file identity mismatch')
    relative = PurePosixPath(record['original_path'])
    if relative.is_absolute() or '..' in relative.parts or record['original_mode'] != '100644':
        raise ValueError('unsafe original path or mode')
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as output:
        output.write(original)
    target.chmod(0o644)
print('Verified original files:', len(manifest['original_files']))
```
