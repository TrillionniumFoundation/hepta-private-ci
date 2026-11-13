#!/usr/bin/env python3
"""Exact offline recovery from pre-held bytes and actual producer identities.

No second native full read is performed. Only the original pure compression
and projection function definitions are extracted; no driver main/import runs.
"""
import ast
import base64
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import zlib

HERE = Path(__file__).resolve().parent
RUNTIME = Path('/tmp/hepta-36fa-coordinator-a489-materializer-runtime-v1')
PREHELD = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/expected-inventory-v1')
DRIVER = Path('/tmp/hepta-36fa-coordinator-a489-static-control-archive-v1/originals/driver.HOLD.py')
PREFIX = 'coordinator-a489-actual-inventory-recovery-v1/'
EXPECTED = {
    'complete': {'bytes': 5631947, 'sha256': '0463522b45970d8ae9dbf5f4560e1b15e61768ec7c9ec164848019009c4643f0', 'git_blob': 'f1e2d72f99093581403a2dcc91b55da22a33f905'},
    'native': {'bytes': 3543409, 'sha256': '69cab8dc5e68f6c9ebd8e8bd98ee54565fbbf112f1a1c61113c3413b77e3173b', 'git_blob': '7647480c5ed06525e1661ac451d0ac0ff2b23ea7'}
}


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def identity(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': oid('blob', raw)}


def dump(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def put(name, raw, bounded=True):
    path = HERE / name
    with path.open('xb') as stream:
        stream.write(raw)
    check(path.read_bytes() == raw, 'exact local archival write')
    if not bounded:
        return {'local_path': str(path), **identity(raw)}
    check(len(raw) <= 512000, 'evidence leaf bounded')
    return {'name': name, 'path': PREFIX + name, 'local_path': str(path), 'chars': len(raw.decode()), **identity(raw)}


def raw_pin(record):
    return {'bytes': record['raw_bytes'], 'sha256': record['raw_sha256'], 'git_blob': record['raw_git_blob']}


def gzip_pin(record):
    return {key: record[key] for key in ('bytes', 'sha256', 'git_blob')}


def exact_gunzip(packed):
    reader = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = reader.decompress(packed) + reader.flush()
    check(reader.eof and not reader.unused_data and not reader.unconsumed_tail, 'single complete gzip member')
    return raw


def main():
    inputs = {}
    def read(path, expected_blob):
        raw = path.read_bytes()
        check(oid('blob', raw) == expected_blob, 'fixed full input blob: ' + str(path))
        inputs[str(path)] = identity(raw)
        return raw
    artifacts_raw = read(RUNTIME / 'ARTIFACTS.json', '5d2eb472d5651500e02957013e5cdacb3f7b05af')
    result_raw = read(RUNTIME / 'RESULT.json', '30ab4aad6ff10942063da972e02db49629e3809c')
    driver_raw = read(DRIVER, '2044db8282eb8db8d5627519a425a49f636377da')
    raw = {
        'complete': read(PREHELD / 'EXPECTED_CLEAN_INVENTORY.json', EXPECTED['complete']['git_blob']),
        'native': read(PREHELD / 'EXPECTED_NATIVE_FIVE_FIELD.json', EXPECTED['native']['git_blob'])
    }
    for label in raw:
        check(identity(raw[label]) == EXPECTED[label], 'pre-held full raw three-pin equality')
    artifacts, result = json.loads(artifacts_raw), json.loads(result_raw)
    check(isinstance(artifacts, list), 'original ARTIFACTS is a list of records')
    by_name = {r['name']: r for r in artifacts}
    check(len(by_name) == len(artifacts) == 267, 'unique original artifact names')
    check(result['artifact_records'] == {'name': 'ARTIFACTS.json', **identity(artifacts_raw)}, 'RESULT binds actual full ARTIFACTS')
    check(result['status'] == 'MATERIALIZED_EXACT_CANDIDATE_FOR_MAINTENANCE_REVIEW_ONLY' and
          result['action_completed'] is True and result['qualification'] is False, 'actual original result status remains narrow')
    current = result['current_source_before']
    check(current == result['current_source_after'], 'actual before/after complete source identity equal')
    check(current['head'] == result['source_commit'] == 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f' and
          current['tree'] == result['source_tree'] == 'a489b394666b8141840275128a780605b024cde0' and
          current['parents'] == result['parents'] == ['cc57c7198db6293ccca562253c42fffbe2a04633'] and
          current['status'] == '', 'actual source identity is expected clean d256/a489')
    check({k: current['inventory'][k] for k in EXPECTED['complete']} == EXPECTED['complete'] and
          current['native_inventory'] == EXPECTED['native'], 'pre-held full bytes match actual RESULT inventory pins')
    inventory, native = json.loads(raw['complete']), json.loads(raw['native'])
    check(inventory['source'] == {'head': current['head'], 'tree': current['tree'], 'status': ''} and
          len(inventory['files']) == inventory['filesystem_entries'] == inventory['tracked_entries'] ==
          current['inventory']['filesystem_entries'] == current['inventory']['tracked_entries'] == len(native) == 15243,
          'complete source row count and source status')
    source = driver_raw.decode()
    module = ast.parse(source)
    functions = {n.name: n for n in module.body if isinstance(n, ast.FunctionDef)}
    saved = {}
    payloads = [put('ARTIFACTS.original.json', artifacts_raw), put('RESULT.original.json', result_raw)]
    for name in ('gzrecord', 'native_projection'):
        text = (ast.get_source_segment(source, functions[name]) + '\n').encode()
        saved[name] = put('ORIGINAL_' + name + '.py.txt', text)
        payloads.append(saved[name])
    captures = {}
    def memory_write(name, value):
        check(name not in captures, 'one original serializer output name')
        captures[name] = value
        return {'name': name, **identity(value)}
    def original_pin(value, wanted, label):
        check(identity(value) == wanted, label)
        return value
    namespace = {'gzip': gzip, 'base64': base64, 'check': check, 'write': memory_write,
                 'sha256': sha256, 'oid': oid, 'json': json, 'os': os, 'parse': json.loads,
                 'pin': original_pin, 'packet': {'current': {'native_inventory': EXPECTED['native']}}}
    # Only these two exact function AST nodes are compiled in a memory-only namespace.
    exec(compile(ast.Module(body=[functions['gzrecord'], functions['native_projection']], type_ignores=[]),
                 'isolated-original-pure-inventory-serializers', 'exec'), namespace)
    check(namespace['native_projection'](raw['complete']) == raw['native'], 'exact original five-field projection full bytes')
    aliases = {
        'EXPECTED_CANDIDATE.complete.inventory.json.gz': 'complete',
        'initial.complete.inventory.json.gz': 'complete',
        'initial.native-five-field.inventory.json.gz': 'native',
        'final.complete.inventory.json.gz': 'complete',
        'final.native-five-field.inventory.json.gz': 'native'
    }
    matching = {r['name'] for r in artifacts if r.get('raw_git_blob') in {x['git_blob'] for x in EXPECTED.values()}}
    check(matching == set(aliases), 'exact five original raw/gzip artifact aliases')
    alias_proof = []
    for name, label in aliases.items():
        actual = by_name[name]
        check(raw_pin(actual) == EXPECTED[label], 'every actual alias raw three-pin equality')
        reproduced = namespace['gzrecord'](name[:-3], raw[label])
        check(reproduced == actual, 'entire original gzip record with all five parts equals actual ARTIFACTS')
        check(len(actual['parts']) == 5 and identity(captures[name]) == gzip_pin(actual), 'complete original gzip identity and five parts')
        decoded, offset = [], 0
        for part in actual['parts']:
            encoded = captures[part['name']]
            check(part == by_name[part['name']] and identity(encoded) == gzip_pin(part), 'nested/top-level actual part records and complete encoded identity')
            check(encoded.endswith(b'\n') and len(encoded) <= 512000, 'one final LF and original evidence leaf bound')
            body = base64.b64decode(encoded[:-1], validate=True)
            check(base64.b64encode(body) + b'\n' == encoded and part['decoded_offset'] == offset and
                  part['decoded_bytes'] == len(body) and part['decoded_sha256'] == sha256(body), 'strict base64/offset/decoded identity')
            offset += len(body)
            decoded.append(body)
        packed = b''.join(decoded)
        check(packed == captures[name] and identity(packed) == gzip_pin(actual) and
              exact_gunzip(packed) == raw[label] and identity(exact_gunzip(packed)) == raw_pin(actual),
              'all five actual parts restore entire gzip and exact original raw')
        canonical = 'final.complete.inventory.json.gz' if label == 'complete' else 'final.native-five-field.inventory.json.gz'
        alias_proof.append({'actual_artifact_name': name, 'kind': label, 'raw': raw_pin(actual), 'gzip': gzip_pin(actual),
                            'parts': actual['parts'], 'saved_canonical_gzip_name': canonical,
                            'complete_record_and_all_part_identities_equal': True})
    for label, canonical in [('complete', 'final.complete.inventory.json.gz'), ('native', 'final.native-five-field.inventory.json.gz')]:
        put(canonical[:-3] + '.exact_recovered', raw[label], bounded=False)
        put(canonical, captures[canonical], bounded=False)
        for part in by_name[canonical]['parts']:
            payloads.append(put(part['name'], captures[part['name']]))
    modes = dict(sorted(collections.Counter(row['index_mode'] for row in inventory['files']).items()))
    check(modes == {'100644': 15152, '100755': 90, '120000': 1}, 'complete retained mode-aware source count')
    for path, expected in inputs.items():
        check(identity(Path(path).read_bytes()) == expected, 'all read fixed inputs unchanged at recovery end')
    alias_map = {'format': 'hepta-actual-inventory-artifact-alias-recovery-v1', 'actual_artifacts': identity(artifacts_raw),
                 'actual_result': identity(result_raw), 'aliases': alias_proof, 'distinct_raw_bytes': 2,
                 'distinct_gzip_streams': 2, 'distinct_saved_base64_leaves': 10,
                 'all_25_original_named_part_records_match': True, 'second_native_read': False}
    payloads.append(put('ACTUAL_ARTIFACT_ALIAS_MAP.json', dump(alias_map)))
    proof = {
        'format': 'hepta-d256-materialized-inventory-exact-offline-recovery-v1',
        'status': 'EXACT_RECOVERY_MATCHED_ALL_ACTUAL_RAW_GZIP_AND_PART_IDENTITIES',
        'provenance': 'Pre-held full expected bytes from placement88ad were compared with actual producer RESULT/ARTIFACTS. The exact original pure gzip/part serializer was rerun only in a memory-only namespace. All actual raw, gzip and named-part pins match. No second native full inventory read occurred.',
        'actual_result': identity(result_raw), 'actual_artifacts': identity(artifacts_raw),
        'source': inventory['source'], 'parents': current['parents'], 'files': 15243, 'modes': modes,
        'recovered_complete': EXPECTED['complete'], 'recovered_native_five_field': EXPECTED['native'],
        'original_expected_archive': '88ad362796481f768cde7953c9c9485719c04591',
        'original_driver': identity(driver_raw), 'original_function_sources': saved,
        'actual_alias_records_checked': 5, 'actual_named_part_records_checked': 25,
        'distinct_base64_leaves_archived': 10, 'actual_compressed_part_size': 262144,
        'actual_encoding': 'base64 plus one LF; gzip.compress(raw, mtime=0), original default level9',
        'actual_before_after_inventory_identities_equal': True,
        'inputs': [{'path': p, **meta} for p, meta in sorted(inputs.items())],
        'new_native_reads': 0, 'H_calls': 0, 'driver_main_import_or_execution': False, 'project_gates': 0,
        'source_or_ref_changes': False, 'qualification': False,
        'limits': [
            'Exact recovery is from pre-held full bytes constrained by actual three-pin identities; it is not a new external/native download or fresh physical scan.',
            'The current raw index and its stat fields are not reconstructed here. Existing native original metadata/index evidence has separate provenance.',
            'This packet supplies no maintenance success, compiled result, test pass, source qualification, or real task-chain completion.',
            'Large raw and gzip files remain local exact recovered companions; bounded actual-format base64 parts preserve their complete bytes in Git.'
        ]
    }
    payloads.append(put('EXACT_RECOVERY_REVIEW.json', dump(proof)))
    raw_script = Path(__file__).read_bytes()
    payloads.append({'name': Path(__file__).name, 'path': PREFIX + Path(__file__).name, 'local_path': str(Path(__file__)),
                     'chars': len(raw_script.decode()), **identity(raw_script)})
    check(len(payloads) == 17 and len({r['path'] for r in payloads}) == 17 and all(r['bytes'] <= 512000 for r in payloads),
          'unique bounded exact recovery payloads')
    out = dump({'format': 'hepta-exact-inventory-recovery-payload-index-v1', 'entries': payloads, 'count': 17,
                'leaf_limit': 512000, 'not_a_second_native_read': True})
    with (HERE / 'ARCHIVE_PAYLOAD_INDEX.json').open('xb') as handle:
        handle.write(out)
    print(json.dumps({'status': proof['status'], 'payloads': len(payloads), 'maximum_leaf': max(r['bytes'] for r in payloads),
                      'complete_raw': EXPECTED['complete'], 'native_raw': EXPECTED['native'],
                      'payload_index': identity(out), 'payload_index_chars': len(out.decode())}, sort_keys=True))


if __name__ == '__main__':
    main()
