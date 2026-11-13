#!/usr/bin/env python3
"""Close the completed 3bb runtime evidence; no native or network operations."""
import base64
import datetime
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')
PREFIX = 'coordinator-a489-materializer-runtime-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(name, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()
    with (ROOT / name).open('xb') as stream:
        stream.write(raw)
    assert (ROOT / name).read_bytes() == raw
    return {'name': name, **pin(raw)}


def read_sdk(name):
    raw = (ROOT / name).read_bytes()
    sdk = json.loads(raw)
    assert not sdk.get('isError')
    assert len(sdk['content']) == 1 and sdk['content'][0]['type'] == 'text'
    return json.loads(sdk['content'][0]['text'])


def archive_row(name):
    raw = (ROOT / name).read_bytes()
    assert len(raw) <= 512000
    raw.decode('utf-8')
    return {'path': PREFIX + '/' + name, 'local_path': str(ROOT / name), **pin(raw)}


def main():
    index_raw = (ROOT / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json').read_bytes()
    assert pin(index_raw)['git_blob'] == '46f6cb916120a41f19fa304ed9fa8cd8773d5e2c'
    frozen = json.loads(index_raw)
    assert frozen['input_set_count'] == len(frozen['files']) == 53
    all_readbacks = []
    for row in frozen['files']:
        raw = (ROOT / row['name']).read_bytes()
        assert pin(raw) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
        sdk_name = row['name'] + '.PUBLISH_GET.original.json'
        sdk_raw = (ROOT / sdk_name).read_bytes()
        sdk = json.loads(sdk_raw)
        assert not sdk.get('isError') and sdk['structuredContent']['content'].encode() == raw
        all_readbacks.append({'name': row['name'], **pin(raw), 'complete_git_content_equal': True,
                              'saved_original_full_get': {'name': sdk_name, **pin(sdk_raw)}})
    artifacts = json.loads((ROOT / 'ARTIFACTS.json').read_bytes())
    artifact_map = {row['name']: row for row in artifacts}
    assert len(artifacts) == len(artifact_map) == 267
    encoded = []
    for stem, raw_name in [('final.new-index.raw', 'final.new-index.raw'),
                           ('final.git-metadata.json', 'final.git-metadata.json')]:
        compressed = (ROOT / (stem + '.gz')).read_bytes()
        raw = (ROOT / raw_name).read_bytes()
        assert gzip.decompress(compressed) == raw
        artifact = artifact_map[stem + '.gz']
        assert pin(compressed) == {key: artifact[key] for key in ('bytes', 'sha256', 'git_blob')}
        assert pin(raw) == {key: artifact['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
        parts = []
        decoded = []
        for number, offset in enumerate(range(0, len(compressed), 262144), 1):
            name = stem + '.gz.part-%03d.b64' % number
            body = (ROOT / name).read_bytes()
            block = compressed[offset:offset + 262144]
            assert body == base64.b64encode(block) + b'\n'
            assert pin(body) == {key: artifact_map[name][key] for key in ('bytes', 'sha256', 'git_blob')}
            restored = base64.b64decode(body[:-1], validate=True)
            assert restored == block
            decoded.append(restored)
            parts.append({'name': name, **pin(body), 'offset': offset,
                          'next_offset': offset + len(block), 'decoded': pin(block)})
        assert b''.join(decoded) == compressed
        reads = []
        next_offset = 0
        first_version = None
        actual_chunks = []
        for name in sorted(row['name'] for row in frozen['files']
                           if row['name'].startswith(stem + '.gz.READ_OFFSET_')):
            observation = read_sdk(name)
            block = base64.b64decode(observation['data_base64'], validate=True)
            assert observation['offset'] == next_offset
            assert observation['next_offset'] == next_offset + len(block)
            assert observation['size'] == len(compressed)
            assert hashlib.sha256(block).hexdigest() == observation['chunk_sha256']
            if first_version is None:
                first_version = observation['version']
            assert observation['version'] == first_version
            assert observation['eof'] == (observation['next_offset'] == len(compressed))
            actual_chunks.append(block)
            reads.append({'name': name, 'offset': next_offset,
                          'next_offset': observation['next_offset'], 'version': first_version})
            next_offset = observation['next_offset']
        assert next_offset == len(compressed) and b''.join(actual_chunks) == compressed
        encoded.append({'format': 'gzip-base64-original-native-parts', 'raw_name': raw_name,
                        'raw': pin(raw), 'compressed_name': stem + '.gz',
                        'compressed': pin(compressed), 'parts': parts,
                        'actual_native_read_ranges': reads, 'actual_complete_read_equal': True,
                        'native_artifact_pins_equal': True,
                        'raw_and_gzip_standalone_Git_upload_claimed': False})
    normal = read_sdk('STATUS_04.original.json')
    assert normal['job_id'] == '1a1d468462a-392-3bb' and normal['state'] == 'succeeded'
    assert normal['exit_code'] == 0 and normal['output_complete'] and normal['output_durable']
    assert all(normal[key] is False for key in ('timed_out', 'cancelled', 'automatic_retry'))
    streams = {}
    for key in ('stdout', 'stderr'):
        offset = 0
        blocks = []
        for name in ['STREAM_READ_01.original.json', 'STREAM_READ_02.original.json', 'STREAM_READ_03.original.json']:
            row = read_sdk(name)[key]
            block = bytes.fromhex(row['bytes_hex'])
            assert block.decode() == row['text'] and row['offset'] == offset
            offset = row['next_offset']
            blocks.append(block)
        raw = b''.join(blocks)
        assert offset == len(raw) and raw == (ROOT / (key.upper() + '.complete.original.txt')).read_bytes()
        assert normal['log_bytes'][key] == {'seen': len(raw), 'stored': len(raw)}
        assert normal['log_synced'][key] and normal['log_truncated'][key] is False and normal['log_errors'][key] is None
        streams[key] = pin(raw)
    encoding = save('BINARY_COMPANIONS_ENCODING_MANIFEST.json', {
        'format': 'hepta-runtime-original-binary-companion-map-v1',
        'job_id': normal['job_id'], 'companions': encoded,
        'source': 'Actual retained native gzip bytes read through exact stable-version chunks; original native part bytes regenerated and required to equal original ARTIFACTS entries.',
        'complete_source_inventory_included': False})
    review = save('RUNTIME_FULL_READBACK_CLOSURE.json', {
        'format': 'hepta-completed-materialization-runtime-archive-review-v1',
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'job_id': normal['job_id'], 'status': 'COMPLETE_FIXED_RUNTIME_WINDOW_PRESERVED',
        'closed_original_members': 53, 'all_53_actual_full_git_get_equal': True,
        'actual_native_index_compressed_chunks': len(encoded[0]['actual_native_read_ranges']),
        'actual_native_metadata_compressed_chunks': len(encoded[1]['actual_native_read_ranges']),
        'binary_companions_complete': True, 'streams': streams,
        'readback_records': all_readbacks, 'H_read_errors_in_this_closed_window': [],
        'qualification': False, 'archive_invoked_H': False,
        'maintenance_or_future_result_included': False,
        'scope': 'This archive preserves the named 53 original responses/decoded artifacts/local review records and exact binary companions. ARTIFACTS lists 267 retained native files; this does not claim external download or standalone upload of all 267. Expected full source inventories are a separately owned exact reconstruction and are not in this archive.'})
    extra = [encoding['name'], review['name'], 'close_runtime_archive.py', 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json']
    rows = [archive_row(item['name']) for item in frozen['files']] + [archive_row(name) for name in extra]
    assert len({row['path'] for row in rows}) == len(rows)
    placement = save('PLACEMENT.json', {
        'format': 'hepta-evidence-placement-v1', 'prefix': PREFIX,
        'job_id': normal['job_id'], 'status': 'FIXED_COMPLETED_MATERIALIZATION_RUNTIME_ONLY',
        'entries': rows, 'entry_count': len(rows),
        'binary_companion_manifest': encoding, 'scope_review': review,
        'no_new_H_or_native_execution': True,
        'publication_rule': 'Every listed UTF-8 body must have actual complete Git readback before placement is handed off. Binary original raw/gzip identities use the explicitly mapped original base64 parts; no standalone Git storage is claimed for those binaries.'})
    print(json.dumps({'generated': [encoding, review, archive_row('close_runtime_archive.py'), placement]}, indent=2))


if __name__ == '__main__':
    main()
