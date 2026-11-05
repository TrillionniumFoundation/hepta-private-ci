"""Verify every extracted member and reconstruct both exact original RPCs."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import hashlib
import json


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_member(root, name):
    relative = PurePosixPath(name)
    assert not relative.is_absolute() and '..' not in relative.parts
    path = root.joinpath(*relative.parts)
    assert path.is_file() and not path.is_symlink()
    assert path.resolve().is_relative_to(root.resolve())
    return path.read_bytes()


def verify(root, reconstruct_dir):
    manifest = json.loads(load_member(root, 'MANIFEST.json'))
    expected = {m['path']: m for m in manifest['members']}
    assert len(expected) == len(manifest['members'])
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}
    assert actual == set(expected) | {'MANIFEST.json'}
    checked = []
    for name, record in sorted(expected.items()):
        raw = load_member(root, name)
        assert len(raw) == record['bytes'] and digest(raw) == record['sha256']
        checked.append(record)
    recipe = json.loads(load_member(root, 'rpc-reconstruction.json'))
    reconstruct_dir.mkdir(parents=True, exist_ok=False)
    rebuilt = []
    for case in recipe['cases']:
        original = load_member(root, case['input_member'])
        assert len(original) == case['input_bytes']
        assert digest(original) == case['input_sha256']
        if case['transform'] == 'base64-wrapped':
            encoded = base64.b64encode(original).decode('ascii')
            width = case['wrap_columns']
            payload = case['newline'].join(encoded[i:i + width] for i in range(0, len(encoded), width))
            if case['trailing_newline']:
                payload += case['newline']
        else:
            assert case['transform'] == 'utf-8'
            payload = original.decode('utf-8')
        assert len(payload) == case['returned_content_characters']
        token = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        rpc = load_member(root, case['prefix_member']) + token + load_member(root, case['suffix_member'])
        assert len(rpc) == case['original_rpc_bytes']
        assert digest(rpc) == case['original_rpc_sha256']
        parsed = json.loads(rpc)
        assert not parsed['isError'] and parsed['structuredContent']['content'] == payload
        output = reconstruct_dir / case['original_rpc_name']
        with output.open('xb') as stream:
            stream.write(rpc)
        rebuilt.append({'case': case['case'], 'input_bytes': len(original),
                        'input_sha256': digest(original), 'rpc_bytes': len(rpc),
                        'rpc_sha256': digest(rpc), 'reconstructed_file': str(output)})
    return {'status': 'PASS', 'checked_members': checked, 'reconstructed_rpcs': rebuilt,
            'tested_binary_bytes': 1044516, 'tested_utf8_bytes': 2812928,
            'untested_5_6_mib_text': True,
            'scope': 'Exact two historical read-only responses, not an interface maximum or any new upload/read permission.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reconstruct-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.root.resolve(), args.reconstruct_dir.resolve()), indent=2))
