"""Create-only artifacts and protocol/source seals for integration checks."""
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    encoded = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as f:
        f.write(gzip.compress(encoded, mtime=0) if str(path).endswith('.gz') else encoded)
    return {'path': str(path), 'bytes': Path(path).stat().st_size, 'sha256': sha(path)}


def verify(expected):
    path = ROOT/'ADAPTER_PROTOCOL.json'
    if sha(path) != expected:
        raise ValueError('Wrong frozen adapter protocol')
    protocol = json.loads(path.read_text())
    for name, digest in protocol['source_sha256'].items():
        if sha(ROOT/name) != digest:
            raise ValueError('Adapter source changed: '+name)
    if sha(ROOT/'ADAPTER_FIXTURES.json') != protocol['fixture_sha256']:
        raise ValueError('Adapter fixture manifest changed')
    return protocol
