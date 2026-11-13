"""Independent bounded decode of the exact already full-GET-verified archive."""
import base64
import hashlib
import json
import lzma
import re
import struct
from pathlib import Path

A = Path('/tmp/hepta-36fa-b608-history-transport-runtime-raw-archive-v3')
R = Path('/tmp/hepta-36fa-root-history-stage-complete-review-v1')
S = Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
K = ('bytes', 'sha256', 'git_blob')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def require(raw, expected):
    assert pin(raw) == {key: expected[key] for key in K}
    return raw


get_raw = (R / 'ROOT_GIT_PARTS_FULL_GET_INDEX.json').read_bytes()
assert pin(get_raw)['git_blob'] == '81f8b7942d91d45801b45d163ce708ecfd80d879'
get = json.loads(get_raw)
assert get['part_count'] == 73 and get['metadata_count'] == 3
actual_gets = {row['name']: row for row in get['entries']}
assert len(actual_gets) == 76 and all(row['actual_Git_full_GET_verified'] is True for row in actual_gets.values())
manifest_raw = require((A / 'MANIFEST.json').read_bytes(), actual_gets['MANIFEST.json'])
assert pin(manifest_raw)['git_blob'] == '081b148d08c5fb104eb0bb2a15cf5687b343915f'
manifest = json.loads(manifest_raw)
assert manifest['file_count'] == 755 and manifest['original_bytes'] == 38963673
index_raw = require((A / 'CLOSED_FILE_INDEX.json').read_bytes(), actual_gets['CLOSED_FILE_INDEX.json'])
assert pin(index_raw)['git_blob'] == 'c83d5ac314bbbb9191277779f013ab9adee95fca'
require((A / 'PREVIOUS_V2_MANIFEST.original.json').read_bytes(), actual_gets['PREVIOUS_V2_MANIFEST.original.json'])
parts = []
offset = 0
for number, row in enumerate(manifest['parts'], 1):
    assert row['name'] == f'PART_{number:03d}.b64' and row['offset'] == offset
    raw = require((A / row['name']).read_bytes(), actual_gets[row['name']])
    require(raw, row)
    assert len(raw) <= 400000 and raw.endswith(b'\n') and raw.count(b'\n') == 1
    decoded = base64.b64decode(raw[:-1], validate=True)
    assert base64.b64encode(decoded) + b'\n' == raw
    require(decoded, row['decoded'])
    parts.append(decoded)
    offset += len(decoded)
assert len(parts) == 73
compressed = require(b''.join(parts), manifest['compressed'])
assert offset == len(compressed) == 21418548
decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=134217728)
packet = decoder.decompress(compressed, max_length=39228230)
assert decoder.eof and decoder.unused_data == b''
require(packet, manifest['packet'])
assert len(packet) == 39228229 and packet.startswith(b'HEPTA-RAW-FILE-SET-V3\0')
offset = len(b'HEPTA-RAW-FILE-SET-V3\0')
index_len = struct.unpack('>Q', packet[offset:offset + 8])[0]
assert index_len == 264526
offset += 8
assert packet[offset:offset + index_len] == index_raw
offset += index_len
index = json.loads(index_raw)
assert index['file_count'] == len(index['files']) == 755
bodies = {}
for row in index['files']:
    name = row['name']
    assert name not in bodies and Path(name).name == name
    body = require(packet[offset:offset + row['bytes']], row)
    assert body == (S / name).read_bytes()
    bodies[name] = body
    offset += row['bytes']
assert offset == len(packet) and sum(map(len, bodies.values())) == 38963673
root_review_raw = (R / 'ROOT_COMPLETE_READBACK_REVIEW.json').read_bytes()
assert pin(root_review_raw)['git_blob'] == 'b0434543015a01fac8d60267981f08af8160be50'
root_review = json.loads(root_review_raw)
assert len(root_review['inputs']) == 457
for row in root_review['inputs']:
    require(bodies[row['name']], row)
part_reads = [name for name in bodies if re.fullmatch(r'PART_\d{3}\.READ_\d+\.(?:RECONCILE_01\.)?original\.json', name)]
file_reads = [name for name in bodies if re.fullmatch(r'FILE_\d{3}\.READ_\d+\.original\.json', name)]
part_writes = [name for name in bodies if re.fullmatch(r'PART_\d{3}\.WRITE\.original\.json', name)]
assert len(part_reads) == 83 and len(file_reads) == 176 and len(part_writes) == 17
assert sum(json.loads(bodies[name]).get('isError', False) for name in part_reads) == 1
assert not any(json.loads(bodies[name]).get('isError', False) for name in file_reads + part_writes + ['STAGING_READBACK_01.original.json'])
failed = 'PART_008.READ_262144.original.json'
assert pin(bodies[failed])['git_blob'] == 'ee720552601b4fd39acb31c5a6b5128f3dce17cd'
review = {
    'format': 'hepta-root-complete-history-archive-and-replay-closure-v1',
    'archive_manifest': pin(manifest_raw), 'original_closed_index': pin(index_raw),
    'actual_Git_full_GET_index': pin(get_raw), 'actual_Git_full_GET_items': 76,
    'all_73_parts_full_GET_bytes_equal_exact_locally_decoded_inputs': True,
    'bounded_decoded_packet': pin(packet), 'bounded_compressed_packet': pin(compressed),
    'all_original_raw_files': 755, 'all_original_raw_bytes': 38963673,
    'all_755_reconstructed_originals_equal_frozen_index_and_current_originals': True,
    'Root_independent_complete_native_replay': pin(root_review_raw),
    'all_457_replay_input_bytes_present_unchanged_in_actual_Git_archive': True,
    'native_records': {'part_write_responses': 17, 'part_read_responses': 83,
                       'retained_failed_read_responses': 1, 'same_version_recovery_responses': 1,
                       'fixed_file_read_responses_including_receipt': 177,
                       'fixed_files': 61, 'fixed_file_bytes': 8301563},
    'typed_request_and_actual_dispatch_and_normal_streams_preserved': True,
    'raw_native_integer_bytes_preserved': True,
    'original_computed_git_identity_is_not_individual_blob_publication': True,
    'availability_claim': 'All archive parts were fetched completely now. No perpetual availability or legitimate model authority is inferred.',
    'historical_old_source_failure_preserved': True,
    'live_source_and_environment_validation': 'Still required by the separate exact source request.',
    'H_calls': 0, 'source_or_native_qualification': False, 'real_qualified_task_chains': 0,
}
raw = (json.dumps(review, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
with (R / 'ROOT_ARCHIVE_AND_REPLAY_CLOSURE.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'closure': pin(raw), 'originals': 755, 'bytes': 38963673, 'complete_native_readback_files': 61, 'qualification': False}))
