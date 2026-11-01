"""Verify and restore archived evidence and the exact tested Linux native binaries."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def destination(name):
    result = (ROOT/name).resolve()
    if not result.is_relative_to(ROOT):
        raise ValueError('Archive path escapes project')
    return result


def save(name, data, verify_only, mode=0o644):
    target = destination(name)
    if target.exists() and target.read_bytes() != data:
        raise FileExistsError(f'Refusing to overwrite different bytes: {target}')
    if not verify_only:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        target.chmod(mode)


def restore(verify_only=False):
    checked = 0
    manifests = ['TRAINING_ARCHIVES.json', 'EVIDENCE_ARCHIVES.json']
    for name in manifests:
        source = ROOT/name
        if not source.exists():
            continue
        for record in json.loads(source.read_text())['archives']:
            if 'parts' in record:
                blocks = []
                for part in record['parts']:
                    block = (ROOT/part['file']).read_bytes()
                    if len(block) != part['bytes'] or sha(block) != part['sha256']:
                        raise ValueError('Archive part identity mismatch')
                    blocks.append(block)
                payload = b''.join(blocks)
                save(record['file'], payload, verify_only)
            else:
                payload = (ROOT/record['file']).read_bytes()
            if sha(payload) != record['sha256']:
                raise ValueError('Archive digest mismatch')
            with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as handle:
                members = handle.getmembers()
                if {m.name for m in members} != set(record['members']):
                    raise ValueError('Archive member set mismatch')
                for member in members:
                    if not member.isfile():
                        raise ValueError('Only regular evidence files are allowed')
                    data = handle.extractfile(member).read()
                    if sha(data) != record['members'][member.name]:
                        raise ValueError('Member digest mismatch')
                    save(member.name, data, verify_only)
                    checked += 1
    for record in json.loads((ROOT/'native/BINARY_ARTIFACTS.json').read_text())['artifacts']:
        blocks = []
        for part in record['parts']:
            compressed = (ROOT/part['file']).read_bytes()
            if sha(compressed) != part['sha256']:
                raise ValueError('Native binary part digest mismatch')
            data = gzip.decompress(compressed)
            if len(data) != part['uncompressed_bytes'] or sum(map(len, blocks)) != part['offset']:
                raise ValueError('Native part ordering/size mismatch')
            blocks.append(data)
        data = b''.join(blocks)
        if len(data) != record['bytes'] or sha(data) != record['sha256']:
            raise ValueError('Reconstructed native binary identity mismatch')
        save(record['target'], data, verify_only, record['mode'])
        checked += 1
    return {'verified_files': checked, 'mode': 'verify-only' if verify_only else 'restore',
            'different_existing_bytes_never_overwritten': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(restore(args.verify_only)))
