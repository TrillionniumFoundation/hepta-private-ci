"""Archive the same frozen 755 originals without nested base64 expansion.

Pure cloud archival only. Every original byte is retained verbatim in a bounded
binary container, whose header is the original complete frozen file index.
"""
import base64
import hashlib
import json
import lzma
import struct
from pathlib import Path

SOURCE = Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
PREVIOUS = Path('/tmp/hepta-36fa-b608-history-transport-runtime-compact-archive-v2')
OUT = Path('/tmp/hepta-36fa-b608-history-transport-runtime-raw-archive-v3')
MAGIC = b'HEPTA-RAW-FILE-SET-V3\0'
LIMIT = 294912


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def put(name, raw):
    path = OUT / name
    with path.open('xb') as stream:
        stream.write(raw)
    return {'name': name, 'local_path': str(path), **pin(raw)}


index_raw = (PREVIOUS / 'CLOSED_FILE_INDEX.json').read_bytes()
assert pin(index_raw) == {'bytes': 264526, 'sha256': '46e2a41be1a7df03003b0ec6ac0e68e86aa449b8177524e9bec2919fa40ec96c', 'git_blob': 'c83d5ac314bbbb9191277779f013ab9adee95fca'}
index = json.loads(index_raw)
assert index['file_count'] == 755 and len(index['files']) == 755
assert index['total_original_bytes'] == 38963673
parts = [MAGIC, struct.pack('>Q', len(index_raw)), index_raw]
names = set()
for row in index['files']:
    assert row['name'] not in names and Path(row['name']).name == row['name']
    names.add(row['name'])
    path = SOURCE / row['name']
    assert row['source_path'] == str(path)
    raw = path.read_bytes()
    assert pin(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    parts.append(raw)
packet = b''.join(parts)
assert len(packet) == len(MAGIC) + 8 + 264526 + 38963673
compressed = lzma.compress(packet, format=lzma.FORMAT_XZ, check=lzma.CHECK_SHA256,
                           filters=[{'id': lzma.FILTER_LZMA2, 'dict_size': 64 * 1024 * 1024, 'preset': 6}])
decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=128 * 1024 * 1024)
decoded = decoder.decompress(compressed, max_length=len(packet) + 1)
assert decoder.eof and decoder.unused_data == b'' and decoded == packet
assert decoded.startswith(MAGIC)
header_size = struct.unpack('>Q', decoded[len(MAGIC):len(MAGIC) + 8])[0]
assert header_size == len(index_raw)
offset = len(MAGIC) + 8
assert decoded[offset:offset + header_size] == index_raw
offset += header_size
for row in index['files']:
    raw = decoded[offset:offset + row['bytes']]
    assert pin(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert raw == (SOURCE / row['name']).read_bytes()
    offset += row['bytes']
assert offset == len(decoded)
OUT.mkdir(exist_ok=False)
index_pin = put('CLOSED_FILE_INDEX.json', index_raw)
packet_pin = put('RAW_FILE_SET.bin', packet)
compressed_pin = put('RAW_FILE_SET.bin.xz', compressed)
rows = []
for number, offset in enumerate(range(0, len(compressed), LIMIT), 1):
    chunk = compressed[offset:offset + LIMIT]
    encoded = base64.b64encode(chunk) + b'\n'
    assert len(encoded) <= 393217
    rows.append({**put(f'PART_{number:03d}.b64', encoded), 'offset': offset, 'decoded': pin(chunk)})
prior_raw = (PREVIOUS / 'MANIFEST.json').read_bytes()
prior_pin = put('PREVIOUS_V2_MANIFEST.original.json', prior_raw)
manifest = {
    'format': 'hepta-bounded-verbatim-raw-file-set-v3',
    'file_count': 755, 'original_bytes': 38963673, 'file_index': index_pin,
    'framing': {'magic_ascii': 'HEPTA-RAW-FILE-SET-V3', 'magic_terminal_nul': True,
                'header_length': 'unsigned 64-bit big-endian; exactly 264526',
                'header': 'Exact original CLOSED_FILE_INDEX.json bytes',
                'bodies': 'Original raw file bytes in header files order, with lengths and three pins from each row',
                'no_trailing_bytes': True},
    'packet': packet_pin, 'compressed': compressed_pin,
    'compression': {'format': 'xz', 'check': 'SHA256', 'dictionary_bytes': 67108864,
                    'decompression_memory_limit': 134217728, 'decompressed_limit': len(packet) + 1},
    'parts': rows, 'ascii_leaf_limit': 400000,
    'previous_archive_manifest': prior_pin,
    'same_original_closed_index_and_all_755_original_bytes': True,
    'old_gzip_xz_packets_and_originals_preserved': True,
    'all_755_originals_replayed_after_bounded_roundtrip': True,
    'reason': 'Avoid encoding already encoded SDK contents again; this changes only archival framing and compression.',
    'git_identity_semantics': 'Computed identity until separately created and full-GET verified; prior direct observations remain in the original index.',
    'H_calls': 0, 'source_changes': False, 'qualification': False,
}
raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
final = put('MANIFEST.json', raw)
print(json.dumps({'manifest': final, 'packet': packet_pin, 'compressed': compressed_pin, 'parts': len(rows), 'original_files': 755, 'original_bytes': 38963673, 'H_calls': 0}))
