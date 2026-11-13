#!/usr/bin/env python3
"""Preserve only the fixed completed41 staging originals; pure cloud bytes."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
SOURCE = Path('/tmp/hepta-36fa-coordinator-a489-materializer-staging-v1')
STATIC = Path('/tmp/hepta-36fa-coordinator-a489-static-control-archive-v1')
PREFIX = 'coordinator-a489-staging-archive-v1/'
LIMIT = 512000
INDEX_PIN = {'bytes': 14899, 'sha256': 'c1fa2ff5c84362042e699a65517fe25a121f3584d9d1eb86c7899ec4cd805187',
             'git_blob': '0e0ad43034df0c703da61a2c800b4a77d171e5a6'}
ALIASES = ['STAGE_BASE_001.REQUEST.HOLD.json', 'STAGE_BASE_002.REQUEST.HOLD.json',
           'STAGE_CANDIDATE_001.REQUEST.HOLD.json', 'STAGE_CANDIDATE_002.REQUEST.HOLD.json',
           'STAGE_CANDIDATE_003.REQUEST.HOLD.json']


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(value, label):
    if not value:
        raise AssertionError(label)


def dumped(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def put(relative, raw):
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    check(path.read_bytes() == raw, 'local exact copy')
    return {'name': relative, 'path': PREFIX + relative, 'local_path': str(path),
            'chars': len(raw.decode()), **pin(raw)}


def strict_decode(text):
    raw = base64.b64decode(text, validate=True)
    check(base64.b64encode(raw).decode() == text, 'canonical complete base64')
    return raw


def ungzip(packed):
    reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = reader.decompress(packed) + reader.flush()
    check(reader.eof and not reader.unused_data and not reader.unconsumed_tail, 'single complete gzip stream')
    return raw


def sdk(raw):
    wrapper = json.loads(raw)
    check(wrapper['isError'] is False and len(wrapper['content']) == 1 and wrapper['content'][0]['type'] == 'text',
          'exact completed SDK wrapper')
    return json.loads(wrapper['content'][0]['text'])


def main():
    index_raw = (SOURCE / 'CLOSED_STAGE_ARCHIVE_INPUTS.json').read_bytes()
    check(pin(index_raw) == INDEX_PIN, 'fixed stage index complete pin')
    index = json.loads(index_raw)
    check(index['file_count'] == len(index['items']) == 41 and index['main_runtime_excluded'] is True and
          index['qualification'] is False, 'fixed completed41 scope')
    check(len({x['name'] for x in index['items']}) == 41, 'unique original names')
    previous_raw = (STATIC / 'ENCODING_MANIFEST.json').read_bytes()
    check(pin(previous_raw)['git_blob'] == '5d25d85ca4d7f2c20655ca9aa241c8a28a99aec9', 'actual frozen static encoding manifest')
    previous = {r['name']: r for r in json.loads(previous_raw)['oversized_members']}
    payloads = [put('CLOSED_STAGE_ARCHIVE_INPUTS.original.json', index_raw)]
    originals, members, aliases = {}, [], []
    for row in index['items']:
        name = row['name']
        check(Path(name).name == name and Path(row['local_path']) == SOURCE / name, 'only explicitly indexed stage path')
        raw = (SOURCE / name).read_bytes()
        check(pin(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}, 'original member complete identity: ' + name)
        raw.decode()
        originals[name] = raw
        local = put('originals/' + name, raw)
        member = {'name': name, 'original_local_path': row['local_path'], 'raw': pin(raw)}
        is_request = name.startswith('STAGE_') and name.endswith('.REQUEST.original.json')
        alias = None
        if is_request:
            number = int(name.split('_', 1)[1].split('.', 1)[0])
            alias = ALIASES[number - 1]
            check(raw == (STATIC / 'originals' / alias).read_bytes(), 'executed request alias full bytes equal frozen static request')
        if len(raw) <= LIMIT:
            payloads.append(local)
            member.update(representation='exact_original_raw_leaf', evidence_paths=[local['path']])
            if alias:
                aliases.append({'stage_name': name, 'static_name': alias, 'raw': pin(raw),
                                'representation': 'same immutable raw blob', 'stage_evidence_paths': [local['path']]})
        else:
            check(alias is not None and alias in previous, 'only three known oversize request aliases')
            spec = previous[alias]
            check(spec['raw'] == pin(raw), 'reuse exact original request encoding identity')
            parts, decoded_parts, cursor = [], [], 0
            for item in spec['parts']:
                encoded = Path(item['local_path']).read_bytes()
                check(pin(encoded) == item['encoded'] and encoded.endswith(b'\n') and len(encoded) <= LIMIT, 'existing bounded encoded part pin')
                decoded = strict_decode(encoded[:-1].decode())
                check(pin(decoded) == item['decoded'] and item['offset'] == cursor, 'existing part decoded identity and offset')
                cursor += len(decoded)
                decoded_parts.append(decoded)
                copied = put('encoded/' + name + f'.gz.part-{item["number"]:03d}.b64', encoded)
                payloads.append(copied)
                parts.append({'number': item['number'], 'offset': item['offset'], 'encoded': item['encoded'],
                              'decoded': item['decoded'], 'path': copied['path'], 'local_path': copied['local_path'],
                              'reused_static_evidence_path': item['path']})
            packed = b''.join(decoded_parts)
            check(pin(packed) == spec['gzip'] and ungzip(packed) == raw and pin(ungzip(packed)) == spec['raw'],
                  'reused complete gzip/raw three-pin roundtrip')
            member.update(representation='reused_lossless_gzip_base64_parts', evidence_paths=[x['path'] for x in parts])
            aliases.append({'stage_name': name, 'static_name': alias, 'raw': pin(raw), 'gzip': spec['gzip'], 'parts': parts,
                            'representation': 'same immutable bounded leaf blobs under stage alias paths', 'complete_roundtrip': True})
        members.append(member)
    check(len(aliases) == 5 and sum('parts' in x for x in aliases) == 3, 'five exact aliases with three oversized originals')
    check(sum(len(x.get('parts', [])) for x in aliases) == 6, 'six reused part leaves')
    result = json.loads(originals['STAGING_RESULT.json'])
    clarification = json.loads(originals['ROOT_MATERIALIZATION_INPUT_VERIFICATION_CLARIFICATION.original.json'])
    check(result['status'] == 'FIVE_EXACT_WRITES_SUCCEEDED' and result['write_count'] == 5 and
          result['unknown_writes'] == result['rejected_writes'] == 0 and
          result['external_full_readback_files'] == 2 and result['external_read_chunk_count'] == 11,
          'original staging result accurately bounded')
    check(pin(originals['ROOT_MATERIALIZATION_INPUT_VERIFICATION_CLARIFICATION.original.json'])['git_blob'] ==
          '8473a68b5906c4b31285749259a87158e2e8f0bf' and
          result['original_driver_full_five_input_read_and_final_audit_required'] is True,
          'original clarification and mandatory driver checks retained')
    observations = []
    all_read_names = [n for n in originals if '.READ_OFFSET_' in n]
    check(len(all_read_names) == 11, 'exact external read SDK closure')
    for number in range(1, 6):
        prefix = f'STAGE_{number:02d}'
        request_raw = originals[prefix + '.REQUEST.original.json']
        request = json.loads(request_raw)
        intended = strict_decode(request['data_base64'])
        write = sdk(originals[prefix + '.WRITE.original.json'])
        check(request['host'] == 'desktop' and request['expected_version'] == 'absent' and
              write['mode'] == 0o600 and write['size'] == write['written'] == len(intended) and
              write['sha256'] == pin(intended)['sha256'] and isinstance(write['version'], str), 'original completed fixed write metadata')
        declared = result['writes'][number - 1]
        check(declared['sequence'] == number and declared['actual_write'] == write and
              declared['request'] == pin(request_raw) and declared['expected_decoded'] == pin(intended) and
              declared['native_path'] == request['path'], 'original write result exact fields')
        names = sorted(n for n in all_read_names if n.startswith(prefix + '.'))
        check(len(names) == {1: 8, 2: 3, 3: 0, 4: 0, 5: 0}[number], 'actual external chunk count by path')
        if names:
            info = sdk(originals[prefix + '.FILE_INFO.original.json'])
            check(info['path'] == request['path'] and info['size'] == len(intended) and
                  info['sha256'] == write['sha256'] and info['mode'] == 0o600 and info['version'] == write['version'],
                  'original file-info complete write identity')
            chunks, offset = [], 0
            for position, name in enumerate(names):
                chunk = sdk(originals[name])
                body = strict_decode(chunk['data_base64'])
                check(chunk['path'] == request['path'] and chunk['size'] == len(intended) and
                      chunk['version'] == write['version'] and chunk['offset'] == offset and
                      chunk['next_offset'] == offset + len(body) and
                      chunk['chunk_sha256'] == pin(body)['sha256'] and chunk['eof'] == (position == len(names) - 1),
                      'same fixed-version complete external read chunk')
                chunks.append(body)
                offset += len(body)
            full = b''.join(chunks)
            check(full == intended and offset == len(intended), 'actual external full readback equals fixed intended binary bytes')
            review = json.loads(originals[prefix + '.FULL_READBACK_REVIEW.json'])
            check(review['status'] == 'VERIFIED_COMPLETE' and review['full_bytes_equal'] is True and
                  review['decoded'] == pin(full) and review['version'] == write['version'], 'original full readback review exact result')
        else:
            check(declared['external_full_readback'] == 'not requested; original driver mandatory full read remains',
                  'unperformed external reads not invented')
        observations.append({'sequence': number, 'path': request['path'], 'request': pin(request_raw),
                             'write_sdk': pin(originals[prefix + '.WRITE.original.json']), 'actual_write': write,
                             'external_chunk_count': len(names), 'external_full_readback': bool(names),
                             'decoded': pin(intended)})
    for name, raw in originals.items():
        check((SOURCE / name).read_bytes() == raw, 'closed stage original unchanged at preparation end')
    check((SOURCE / 'CLOSED_STAGE_ARCHIVE_INPUTS.json').read_bytes() == index_raw, 'fixed index unchanged')
    alias_record = {'format': 'hepta-executed-stage-request-alias-reuse-v1', 'static_archive_placement': '287eb242c162d757a4f57ff16d18af94f5733055',
                    'static_encoding_manifest': '5d25d85ca4d7f2c20655ca9aa241c8a28a99aec9', 'aliases': aliases,
                    'request_bodies_are_inputs_not_tool_responses': True, 'all_exact_bytes_equal': True}
    payloads.append(put('REQUEST_ALIAS_REUSE.json', dumped(alias_record)))
    payloads.append(put('CLOSED_MEMBER_MAP.json', dumped({'format': 'hepta-completed-stage-member-map-v1',
        'original_index': INDEX_PIN, 'original_count': 41, 'members': members, 'future_runtime_members_added': 0})))
    review = {'format': 'hepta-completed-stage-archive-review-v1', 'status': 'FIXED_41_ORIGINALS_VERIFIED_PREPARED_FOR_BOUNDED_ARCHIVE',
              'source_index': INDEX_PIN, 'original_count': 41, 'source_raw_bytes': sum(len(x) for x in originals.values()),
              'direct_raw_leaves': 38, 'oversized_request_aliases': 3, 'reused_bounded_part_leaves': 6,
              'five_exact_request_aliases': True, 'write_receipts': 5, 'actual_external_readback_paths': 2,
              'actual_external_read_chunks': 11, 'stage_external_chunk_counts': [8, 3, 0, 0, 0],
              'observations_from_originals': observations, 'root_clarification': '8473a68b5906c4b31285749259a87158e2e8f0bf',
              'unchanged_mandatory_original_driver_full_five_input_reads_and_final_audit': True,
              'original_authorization_not_runtime_Root_authority': clarification['not_runtime_Root_authority'],
              'scope': 'Only original index41 plus derived archival metadata; no main runtime results inspected or included.',
              'new_H_calls': 0, 'source_or_control_changes': False, 'new_Git_tree_commit_ref_operations': 0,
              'qualification': False, 'maximum_leaf_bytes': max(x['bytes'] for x in payloads), 'leaf_limit': LIMIT,
              'limits': ['Original write SDKs and two actual external fixed-version reads are preserved; the other three were explicitly not requested.',
                         'The unchanged controller obligation to fully read and audit all five inputs is separate from these eleven external transport reads.',
                         'This archiver performs no new native read/write or process launch and supplies no main materialization or qualification conclusion.',
                         'The five request originals are aliases of exact staged inputs, not additional tool responses or additional native writes.']}
    payloads.append(put('REVIEW.json', dumped(review)))
    script = Path(__file__)
    raw = script.read_bytes()
    payloads.append({'name': script.name, 'path': PREFIX + script.name, 'local_path': str(script), 'chars': len(raw.decode()), **pin(raw)})
    check(len(payloads) == 49 and len({x['path'] for x in payloads}) == 49 and all(x['bytes'] <= LIMIT for x in payloads), '49 bounded initial payloads')
    index_out = {'format': 'hepta-stage-archive-payload-index-v1', 'original_members': 41, 'entries': payloads,
                 'count': 49, 'leaf_limit': LIMIT}
    raw = dumped(index_out)
    with (HERE / 'ARCHIVE_PAYLOAD_INDEX.json').open('xb') as handle:
        handle.write(raw)
    print(json.dumps({'originals': 41, 'initial_payloads': 49, 'largest_leaf': max(x['bytes'] for x in payloads),
                      'payload_index': pin(raw), 'payload_index_chars': len(raw.decode())}, sort_keys=True))


if __name__ == '__main__':
    main()
