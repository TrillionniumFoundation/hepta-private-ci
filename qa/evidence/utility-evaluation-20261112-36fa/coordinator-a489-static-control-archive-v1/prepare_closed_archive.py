#!/usr/bin/env python3
"""Pure archival preparation of the fixed 89-member static closure.

Reads no future runtime outputs and never recursively collects SDK records.
Writes exclusively inside this independent archive directory. No H, source
edits, Git subprocess, project module import or project gate execution.
"""
from __future__ import annotations
import base64
import collections
import gzip
import hashlib
import json
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
SOURCE = Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')
INDEX = SOURCE / 'CLOSED_STATIC_CONTROL_INPUTS.json'
INDEX_BLOB = '8817a6d9ec4a96b01da373e86c348d78f9941670'
INDEX_SHA256 = '3099504b1279a1fb44984235b754bd6819ac9044baf95b6b017d1abf1480fffe'
PREFIX = 'coordinator-a489-static-control-archive-v1/'
LEAF_LIMIT = 512000
DECODED_PART = 307200


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check(value, label):
    if not value:
        raise AssertionError(label)


def dump(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def put(relative, raw):
    path = HERE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    check(path.read_bytes() == raw, 'exclusive local write roundtrip: ' + relative)
    return {'name': relative, 'path': PREFIX + relative, 'local_path': str(path), 'chars': len(raw.decode('utf-8')), **pin(raw)}


def gzip_decode(packed):
    reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = reader.decompress(packed) + reader.flush()
    check(reader.eof and not reader.unused_data and not reader.unconsumed_tail, 'one complete gzip member')
    return raw


def main():
    source_index = INDEX.read_bytes()
    check(pin(source_index) == {'bytes': 46153, 'sha256': INDEX_SHA256, 'git_blob': INDEX_BLOB}, 'fixed complete original index identity')
    index = json.loads(source_index)
    rows = index['entries']
    check(index['count'] == len(rows) == 89 and index['primary_count'] == 45 and index['completed_original_sdk_count'] == 44,
          'fixed 45+44 membership')
    check(collections.Counter(row['category'] for row in rows) == {'fixed_primary_control': 45, 'completed_original_git_sdk': 44},
          'exact categories')
    check(index['future_git_sdk_capture'] is False and index['future_native_records_included'] is False and
          index['maximum_evidence_leaf_bytes'] == LEAF_LIMIT and index['oversized_member_count'] == 6,
          'frozen closure and original leaf contract')
    check(len({r['name'] for r in rows}) == len({r['path'] for r in rows}) == 89, 'unique original names and paths')
    payloads = [put('CLOSED_STATIC_CONTROL_INPUTS.original.json', source_index)]
    members, encodings = [], []
    actual_bodies = {}
    for row in rows:
        name = row['name']
        check(Path(name).name == name and name not in ('', '.', '..') and '\0' not in name, 'simple exact member basename')
        check(Path(row['path']) == SOURCE / name, 'only explicit fixed source member path')
        raw = (SOURCE / name).read_bytes()
        expected = {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
        check(pin(raw) == expected, 'full original raw identity: ' + name)
        raw.decode('utf-8')
        copy = put('originals/' + name, raw)
        actual_bodies[name] = raw
        member = {'name': name, 'category': row['category'], 'original_source_path': row['path'], 'raw': pin(raw)}
        oversized = len(raw) > LEAF_LIMIT
        check(row['requires_lossless_bounded_representation'] is oversized, 'fixed oversized classification')
        if not oversized:
            payloads.append(copy)
            member.update(representation='exact_original_raw_leaf', evidence_paths=[copy['path']])
        else:
            packed = gzip.compress(raw, compresslevel=9, mtime=0)
            check(gzip_decode(packed) == raw, 'complete original raw/gzip equality')
            packed_path = HERE / 'encoded' / (name + '.gz')
            packed_path.parent.mkdir(parents=True, exist_ok=True)
            with packed_path.open('xb') as stream:
                stream.write(packed)
            parts, offset = [], 0
            for number, start in enumerate(range(0, len(packed), DECODED_PART), 1):
                body = packed[start:start + DECODED_PART]
                encoded = base64.b64encode(body) + b'\n'
                check(len(encoded) <= LEAF_LIMIT and offset == start, 'bounded base64 leaf and exact contiguous offset')
                payload = put('encoded/' + name + f'.gz.part-{number:03d}.b64', encoded)
                payloads.append(payload)
                check(base64.b64decode(encoded[:-1], validate=True) == body and base64.b64encode(body) + b'\n' == encoded,
                      'strict canonical complete part base64')
                parts.append({'number': number, 'offset': start, 'decoded': pin(body), 'encoded': pin(encoded),
                              'path': payload['path'], 'local_path': payload['local_path']})
                offset += len(body)
            reconstructed = b''.join(base64.b64decode(Path(part['local_path']).read_bytes()[:-1], validate=True) for part in parts)
            check(offset == len(packed) and reconstructed == packed and pin(reconstructed) == pin(packed) and
                  gzip_decode(reconstructed) == raw and pin(gzip_decode(reconstructed)) == expected,
                  'entire stored-part reconstruction preserves raw/gzip/full pins')
            encoding = {'name': name, 'raw': expected, 'gzip': pin(packed), 'algorithm': 'gzip compresslevel9 mtime0',
                        'decoded_part_bytes': DECODED_PART, 'encoded_leaf_limit': LEAF_LIMIT, 'parts': parts,
                        'complete_raw_roundtrip_equal': True, 'oversized_raw_or_gzip_is_evidence_leaf': False}
            encodings.append(encoding)
            member.update(representation='lossless_gzip_bounded_base64_parts', evidence_paths=[part['path'] for part in parts],
                          gzip=encoding['gzip'], part_count=len(parts))
        members.append(member)
    check(len(encodings) == 6 and sum(m['representation'] == 'exact_original_raw_leaf' for m in members) == 83,
          '83 direct and six losslessly represented original members')
    check(len({row['path'] for row in payloads}) == len(payloads) and all(row['bytes'] <= LEAF_LIMIT for row in payloads),
          'unique bounded evidence leaf paths')
    for row in rows:
        check((SOURCE / row['name']).read_bytes() == actual_bodies[row['name']], 'original closed member unchanged at preparation end')
    check(INDEX.read_bytes() == source_index, 'index unchanged at preparation end')
    encoding_manifest = {'format': 'hepta-exact-static-originals-lossless-encoding-v1', 'original_index': pin(source_index),
                         'source_member_count': 89, 'oversized_members': encodings, 'oversized_member_count': 6,
                         'leaf_limit': LEAF_LIMIT, 'roundtrip_all_complete': True,
                         'binary_gzip_and_oversized_raw_not_direct_evidence_leaves': True}
    payloads.append(put('ENCODING_MANIFEST.json', dump(encoding_manifest)))
    member_index = {'format': 'hepta-closed-static-original-member-map-v1', 'source_index': pin(source_index),
                    'members': members, 'count': 89, 'primary': 45, 'completed_original_sdk': 44,
                    'future_native_or_Git_SDK_members_added': 0}
    payloads.append(put('CLOSED_MEMBER_MAP.json', dump(member_index)))
    recovery = {}
    packet = json.loads(actual_bodies['MATERIALIZATION_PACKET.HOLD.json'])
    for label in ('base', 'candidate'):
        parts = []
        for number, expected_part in enumerate(packet['provided_inputs'][label]['parts'], 1):
            name = f'STAGE_{label.upper()}_{number:03d}.REQUEST.HOLD.json'
            request = json.loads(actual_bodies[name])
            check(set(request) == {'host', 'path', 'expected_version', 'data_base64'} and
                  request['host'] == 'desktop' and request['expected_version'] == 'absent' and
                  request['path'] == expected_part['path'], 'archived exact write requests retain create-only fields')
            part = base64.b64decode(request['data_base64'], validate=True)
            check(base64.b64encode(part).decode() == request['data_base64'] and
                  pin(part) == {k: expected_part[k] for k in ('bytes', 'sha256', 'git_blob')} and
                  expected_part['offset'] == sum(len(p) for p in parts), 'archived request full binary part and offset')
            parts.append(part)
        packed = b''.join(parts)
        raw = gzip_decode(packed)
        check(pin(packed) == packet['provided_inputs'][label]['gzip'] and pin(raw) == packet['provided_inputs'][label]['raw'],
              'all provided raw objects recover exactly from preserved requests')
        recovery[label] = {'gzip': pin(packed), 'raw': pin(raw), 'parts': len(parts), 'complete_equal_packet': True}
    preparation = {
        'format': 'hepta-closed-static-archive-preparation-review-v1',
        'status': 'ALL_89_ORIGINAL_BYTES_VERIFIED_AND_LOSSLESSLY_REPRESENTED_PENDING_GIT_ARCHIVAL',
        'original_index': pin(source_index), 'original_member_count': 89,
        'original_raw_total_bytes': sum(r['bytes'] for r in rows), 'primary_controls': 45, 'completed_original_git_sdk': 44,
        'direct_original_raw_leaves': 83, 'oversized_originals': 6, 'derived_base64_leaves': sum(len(x['parts']) for x in encodings),
        'maximum_leaf_bytes_so_far': max(row['bytes'] for row in payloads), 'leaf_limit': LEAF_LIMIT,
        'original_member_roundtrips': True, 'original_paths_rehashed_unchanged': True,
        'provided_packages_recoverable_from_exact_requests': recovery,
        'already_archived_expected_inventories_placement': '88ad362796481f768cde7953c9c9485719c04591',
        'large_derived_inputs_not_reuploaded': index['not_included_derived_large_local_files'],
        'closed_members_changed_or_added': 0, 'future_native_outputs_included': False, 'future_git_sdk_recursion': False,
        'H_calls': 0, 'source_control_tree_commit_ref_writes': 0,
        'limits': ['Static controls retain their original HOLD/candidate wording and original invocation metadata; this archive adds no execution result.',
                   'Six oversized originals are represented by complete gzip/base64 parts; their computed raw blob IDs are content identities, not claims that those oversized originals are newly inserted as evidence leaves.',
                   'New archival GET receipts are maintained separately and are not members of the original89 closed set.']
    }
    payloads.append(put('PREPARATION_REVIEW.json', dump(preparation)))
    script = HERE / 'prepare_closed_archive.py'
    script_raw = script.read_bytes()
    payloads.append({'name': script.name, 'path': PREFIX + script.name, 'local_path': str(script),
                     'chars': len(script_raw.decode()), **pin(script_raw)})
    check(all(row['bytes'] <= LEAF_LIMIT for row in payloads), 'all initial archive payloads bounded')
    payload_index = {'format': 'hepta-static-archive-derived-payload-index-v1', 'original_member_count': 89,
                     'payload_count': len(payloads), 'entries': payloads, 'leaf_limit': LEAF_LIMIT}
    index_raw = dump(payload_index)
    with (HERE / 'ARCHIVE_PAYLOAD_INDEX.json').open('xb') as stream:
        stream.write(index_raw)
    print(json.dumps({'originals': 89, 'direct_originals': 83, 'oversized_originals': 6,
                      'base64_parts': sum(len(x['parts']) for x in encodings), 'initial_payloads': len(payloads),
                      'index': pin(index_raw), 'maximum_leaf_bytes': max(row['bytes'] for row in payloads)}, sort_keys=True))


if __name__ == '__main__':
    main()
