#!/usr/bin/env python3
"""Offline verification of original fixed staging SDKs; no native I/O."""
import base64
import hashlib
import json
import pathlib
import sys

OUT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-materializer-staging-v1')
CONTROL = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')

def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key '+key)
        result[key] = value
    return result

def decode_json(data):
    return json.loads(data, object_pairs_hook=unique)

def original(name):
    data = (OUT/name).read_bytes()
    sdk = decode_json(data)
    assert sdk.get('isError') is False, name
    texts = [x['text'] for x in sdk['content'] if x.get('type') == 'text']
    assert len(texts) == 1, name
    return decode_json(texts[0]), {'name': name, **pin(data)}

def create(name, data):
    path = OUT/name
    if path.exists():
        assert path.read_bytes() == data, 'existing local artifact differs: '+name
    else:
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()

def main():
    number = int(sys.argv[1])
    assert 1 <= number <= 5
    approval_raw = (OUT/'ROOT_EXACT_APPROVAL.original.json').read_bytes()
    assert pin(approval_raw) == {'bytes': 7698, 'sha256': '624156a7a015cdde153c39450cfc6838033d7e139d5405d238395803e95cfe7a', 'git_blob': 'a395a49b15c861be88d4e4e49f1e03557470ca55'}
    row = decode_json(approval_raw)['allowed_staging_requests'][number-1]
    prefix = f'STAGE_{number:02d}'
    raw = (OUT/(prefix+'.REQUEST.original.json')).read_bytes()
    assert raw == (CONTROL/row['name']).read_bytes()
    assert pin(raw) == row['request']
    request = decode_json(raw)
    assert set(request) == {'data_base64', 'expected_version', 'host', 'path'}
    assert all(request[k] == row[k] for k in ('host', 'path', 'expected_version'))
    expected_bytes = base64.b64decode(request['data_base64'], validate=True)
    assert base64.b64encode(expected_bytes).decode() == request['data_base64']
    assert pin(expected_bytes) == row['decoded']
    write, write_sdk = original(prefix+'.WRITE.original.json')
    assert write['written'] == write['size'] == row['decoded']['bytes']
    assert write['sha256'] == row['decoded']['sha256'] and write['mode'] == row['expected_mode']
    assert isinstance(write['version'], str)
    info, info_sdk = original(prefix+'.FILE_INFO.original.json')
    assert info['path'] == row['path'] and info['version'] == write['version']
    assert info['size'] == row['decoded']['bytes'] and info['sha256'] == row['decoded']['sha256']
    assert info['mode'] == row['expected_mode'] == 384
    metadata = info['metadata']
    assert metadata['mode'] == 384 and metadata['uid'] == metadata['gid'] == 1000 and metadata['link_count'] == 1
    pieces = []
    receipts = []
    for offset in range(0, len(expected_bytes), 65536):
        chunk, receipt = original(prefix+f'.READ_OFFSET_{offset:06d}.original.json')
        body = base64.b64decode(chunk['data_base64'], validate=True)
        assert base64.b64encode(body).decode() == chunk['data_base64']
        assert chunk['path'] == row['path'] and chunk['version'] == write['version']
        assert chunk['size'] == len(expected_bytes) and chunk['offset'] == offset
        assert len(body) == min(65536, len(expected_bytes)-offset)
        assert chunk['next_offset'] == offset+len(body)
        assert chunk['eof'] is (offset+len(body) == len(expected_bytes))
        assert hashlib.sha256(body).hexdigest() == chunk['chunk_sha256']
        pieces.append(body)
        receipts.append({**receipt, 'offset': offset, 'decoded_bytes': len(body), 'chunk_sha256': chunk['chunk_sha256'], 'next_offset': chunk['next_offset'], 'eof': chunk['eof']})
    actual = b''.join(pieces)
    assert actual == expected_bytes and pin(actual) == row['decoded']
    report = {'format': 'hepta-fixed-staging-full-readback-v1', 'status': 'VERIFIED_COMPLETE',
              'sequence': number, 'approval': pin(approval_raw), 'request': row['request'],
              'native_path': row['path'], 'version': write['version'], 'decoded': pin(actual),
              'mode': info['mode'], 'metadata': metadata, 'original_write_sdk': write_sdk,
              'original_file_info_sdk': info_sdk, 'chunks': receipts, 'full_bytes_equal': True,
              'chunk_coverage': [0, len(actual)], 'all_chunks_same_actual_version': True,
              'native_process_dispatched_by_this_verifier': False,
              'observation_scope': 'Original h_binary_write, h_file_info and complete fixed-version h_binary_read payloads; verification is offline.'}
    output = (json.dumps(report, indent=2, ensure_ascii=False)+'\n').encode()
    name = prefix+'.FULL_READBACK_REVIEW.json'
    create(name, output)
    print(json.dumps({'status': report['status'], 'name': name, **pin(output), 'native_version': write['version'], 'decoded': pin(actual), 'chunks': len(receipts)}))

if __name__ == '__main__':
    main()
