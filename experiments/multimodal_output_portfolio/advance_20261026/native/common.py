"""New-stage identities; all earlier study paths are read-only dependencies."""

import hashlib
import json
import os
from pathlib import Path

AREA = Path(__file__).resolve().parent
REPO = AREA.parents[3]
WORK = REPO.parent
ASSETS = WORK / 'ndu-next-assets'
NATIVE = ASSETS / 'native'
RAW = Path('/tmp/hepta-ndu-advance-native')
OWNER_SHA = '4d56cc99d0edb1018734aebf70dc715de8df7846a2a9c4f2edb4230a0fc87faf'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path = Path(path)
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
