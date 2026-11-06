"""Bounded one-blob receiver for an already returned GitHub tool response.

Transport via local stdin only; no network/Git/desktop action. An exact raw RPC
is retained losslessly as canonical payload plus original prefix/suffix. The
decoded original part, both hashes and the Git object identity are verified.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tty


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def receive(metadata, length, output):
    assert 0 < length <= 8 * 1024 * 1024
    if os.isatty(0):
        tty.setraw(0)
    print('READY', flush=True)
    blocks, remaining = [], length
    while remaining:
        block = os.read(0, min(1024 * 1024, remaining))
        if not block:
            raise ValueError('truncated RPC input')
        blocks.append(block)
        remaining -= len(block)
    raw = b''.join(blocks)
    result = json.loads(raw)
    assert result.get('isError', False) is False
    content = result['structuredContent']['content']
    encoded = content.encode('ascii')
    assert len(encoded) == metadata['transport_bytes'] and sha(encoded) == metadata['transport_sha256']
    assert hashlib.sha1(b'blob ' + str(len(encoded)).encode() + b'\0' + encoded).hexdigest() == metadata['transport_git_blob_sha']
    original = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(original) == encoded
    assert len(original) == metadata['original_bytes'] and sha(original) == metadata['original_sha256']
    assert raw.count(encoded) == 1
    offset = raw.index(encoded)
    prefix, suffix = raw[:offset], raw[offset + len(encoded):]
    assert prefix + base64.b64encode(original) + suffix == raw
    output.mkdir(parents=True, exist_ok=False)
    part = output / 'actual-part.bin'
    with part.open('xb') as stream:
        assert stream.write(original) == len(original)
    (output / 'rpc-prefix.bin').write_bytes(prefix)
    (output / 'rpc-suffix.bin').write_bytes(suffix)
    receipt = {
        'schema': 'lossless-github-base64-part-receipt-v1',
        'original_bytes': len(original), 'original_sha256': sha(original),
        'transport_bytes': len(encoded), 'transport_sha256': sha(encoded),
        'transport_git_blob_sha': metadata['transport_git_blob_sha'],
        'rpc_bytes': len(raw), 'rpc_sha256': sha(raw),
        'prefix_bytes': len(prefix), 'prefix_sha256': sha(prefix),
        'suffix_bytes': len(suffix), 'suffix_sha256': sha(suffix),
        'reconstruction': 'rpc-prefix.bin + canonical base64(actual-part.bin), without newline + rpc-suffix.bin',
        'original_rpc_byte_equality_verified': True,
        'scope': 'Readback of an existing Git blob; no native/archive/source execution credit.',
    }
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    # Independently reopen every newly persisted byte used for reconstruction.
    persisted = part.read_bytes()
    reconstructed = (output / 'rpc-prefix.bin').read_bytes() + base64.b64encode(persisted) + (output / 'rpc-suffix.bin').read_bytes()
    assert reconstructed == raw and sha(persisted) == metadata['original_sha256']
    print(json.dumps({'result': 'PASS_ACTUAL_BYTES', 'output': str(output), 'bytes': len(persisted), 'sha256': sha(persisted), 'rpc_sha256': sha(reconstructed)}), flush=True)


if __name__ == '__main__':
    metadata_path, length, output_path = sys.argv[1:]
    receive(json.loads(Path(metadata_path).read_bytes()), int(length), Path(output_path))
