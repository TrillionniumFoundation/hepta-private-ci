"""Verify and restore every original pilot artifact without overwriting files."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parent / 'evidence' / 'execution'


def restore(destination):
    index = json.loads((ROOT / 'archive-index.json').read_text())
    verified = []
    for name, archive in index['archives'].items():
        data = (ROOT / name).read_bytes()
        assert len(data) == archive['bytes']
        assert hashlib.sha256(data).hexdigest() == archive['sha256']
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(data)), mode='r:') as stream:
            members = stream.getmembers()
            assert len(members) == len(archive['members'])
            assert {m.name for m in members} == set(archive['members'])
            for member in members:
                path = PurePosixPath(member.name)
                assert member.isfile() and not path.is_absolute() and '..' not in path.parts
                payload = stream.extractfile(member).read()
                expected = archive['members'][member.name]
                assert len(payload) == expected['bytes']
                assert hashlib.sha256(payload).hexdigest() == expected['sha256']
                verified.append((name.removesuffix('.tar.gz'), member.name, payload))
    destination.mkdir(parents=True, exist_ok=False)
    for group, relative, payload in verified:
        target = destination / group / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(payload)
    return {'status': 'PASS_BYTE_IDENTICAL_RESTORATION', 'artifacts': len(verified),
            'model_calls_executed': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore(args.destination)))
