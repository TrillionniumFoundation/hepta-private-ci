"""Restore the original downloaded CI ZIP without changing its bytes."""

import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = json.loads((root / 'REMOTE_ARTIFACT_ARCHIVE.json').read_text())
    pieces = []
    for expected_index, item in enumerate(manifest['parts']):
        if item['index'] != expected_index:
            raise ValueError('Archive part order differs from its manifest')
        path = (root / item['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Archive part must be inside the evidence directory')
        data = path.read_bytes()
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Archive part identity mismatch: ' + item['path'])
        pieces.append(data)
    archive = b''.join(pieces)
    digest = hashlib.sha256(archive).hexdigest()
    if len(archive) != manifest['bytes'] or digest != manifest['sha256']:
        raise ValueError('Complete archive identity mismatch')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as destination:
        destination.write(archive)
    print(json.dumps({'bytes': len(archive), 'sha256': digest,
                      'artifact_id': manifest['artifact_id']}))


if __name__ == '__main__':
    main()
