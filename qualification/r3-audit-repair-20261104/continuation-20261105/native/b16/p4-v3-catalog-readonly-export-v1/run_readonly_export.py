import base64
import collections
import gzip
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from datetime import datetime, timezone

ROOT = Path('/home/qq/work/hepta-audit-b16-20261105')
PRIOR = ROOT / 'evidence/bootstrap-P4-libcap-continuation-v3'
OUT = ROOT / 'evidence/bootstrap-P4-v3-catalog-readonly-export-v1'
TREE = '4a3374e22e16ce5c764288ad018cd9affadf94ea'
TERMINAL_SHA = '6eec39a2f566f2949b790db088bda2fd8aac30e32f7d0fc8fb1ac9875d3d1829'
REQUEST_SHA = 'd86ae86014c4f930e3c02f49529cac198fedc9f8a12158fedc6eb1403d9959ba'

def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def read_exact(path, expected=None):
    path = Path(path)
    assert path.parent == PRIOR and path.resolve() == path
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
    data = path.read_bytes()
    after = path.lstat()
    assert (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    actual = identity(data)
    if expected:
        for key in ('bytes', 'sha256', 'git_blob'):
            if key in expected:
                assert actual[key] == expected[key], (str(path), key)
    return data

def canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()

def save(name, data):
    path = OUT / name
    assert path.parent == OUT
    with path.open('xb') as stream:
        stream.write(data)
    reopened = path.read_bytes()
    assert reopened == data
    return {'path': str(path), **identity(reopened)}

def save_json(name, value):
    return save(name, (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode())

assert ROOT.resolve() == ROOT and PRIOR.resolve() == PRIOR and not os.path.lexists(OUT)
originals = []
terminal_data = read_exact(PRIOR / 'terminal.json', {'bytes': 33448, 'sha256': TERMINAL_SHA})
terminal = json.loads(terminal_data)
assert terminal['source_tree'] == TREE and not terminal['success'] and not terminal['tests_executed']
assert [c['exit_code'] for c in terminal['commands']] == [0, 0, 0]
assert len(terminal['source_guards']) == 6
seen = set()
data_by_path = {}
for pin in terminal['records']:
    assert pin['path'] not in seen
    seen.add(pin['path'])
    data = read_exact(pin['path'], pin)
    data_by_path[pin['path']] = data
    originals.append((Path(pin['path']).name, pin['path'], data, 'original-v3-record'))
originals.append(('terminal.json', str(PRIOR / 'terminal.json'), terminal_data, 'original-failed-v3-terminal'))
request_data = data_by_path[str(PRIOR / 'request.original.json')]
assert identity(request_data)['sha256'] == REQUEST_SHA
request = json.loads(request_data)
catalog_pin = terminal['commands'][2]['stdout']
catalog = json.loads(data_by_path[catalog_pin['path']])
assert catalog['rust-build-meta']['target-directory'] == str(ROOT / 'target-dev-small')
roles = []
cases = []
distribution = collections.Counter()
ignored_cases = []
unexpected = []
nonignored_mismatch = []
for sid, suite in sorted(catalog['rust-suites'].items()):
    roles.append([sid, suite['binary-name'], suite['package-name'], suite['kind'], suite['build-platform']])
    for name, case in sorted(suite['testcases'].items()):
        row = [sid, name, case['ignored']]
        cases.append(row)
        filt = case['filter-match']
        distribution[(case['ignored'], json.dumps(filt, sort_keys=True, separators=(',', ':')))] += 1
        entry = {'binary_id': sid, 'name': name, 'ignored': case['ignored'], 'filter_match': filt}
        if case['ignored'] is True:
            ignored_cases.append(entry)
        if case['ignored'] is False and filt != {'status': 'matches'}:
            nonignored_mismatch.append(entry)
        valid = ((case['ignored'] is False and filt == {'status': 'matches'})
                 or (case['ignored'] is True and filt == {'status': 'mismatch', 'reason': 'ignored'}))
        if not valid:
            unexpected.append(entry)
counter = collections.Counter(tuple(row) for row in cases)
case_digest = hashlib.sha256(canon(sorted(cases))).hexdigest()
roles_equal = collections.Counter(tuple(row) for row in roles) == collections.Counter(tuple(row) for row in request['expected_program_roles'])
counts = {'eligible': sum(row[2] is False for row in cases), 'ignored': sum(row[2] is True for row in cases)}
report = {
    'schema': 'hepta-P4-v3-readonly-catalog-analysis-v1',
    'source_tree': TREE, 'host_alias': 'ai395', 'prior_terminal': {'path': str(PRIOR / 'terminal.json'), **identity(terminal_data)},
    'catalog': catalog_pin, 'request': {'path': str(PRIOR / 'request.original.json'), **identity(request_data)},
    'original_controller_exit_code': 1, 'original_three_command_exits': [0, 0, 0],
    'tests_executed': False, 'test_qualification': False, 'build_or_list_repeated': False,
    'counts': counts, 'program_roles': len(roles), 'program_roles_counter_equal': roles_equal,
    'full_case_tuple_schema': ['binary_id', 'name', 'ignored'],
    'full_sorted_case_list_sha256': case_digest,
    'frozen_expected_case_list_sha256': request['complete_A_case_roster_sha256'],
    'full_case_counter_identity_equal': case_digest == request['complete_A_case_roster_sha256'],
    'duplicate_case_tuple_counts': [{'case': list(row), 'count': count} for row, count in sorted(counter.items()) if count != 1],
    'filter_distribution': [{'ignored': ignored, 'filter_match': json.loads(filt), 'count': count}
                            for (ignored, filt), count in sorted(distribution.items())],
    'nonignored_mismatches': nonignored_mismatch, 'unexpected_filter_forms': unexpected,
    'ignored_cases': ignored_cases,
    'exact_catalog_contract_holds': roles_equal and len(roles) == 363 and counts == {'eligible': 19506, 'ignored': 57}
         and case_digest == request['complete_A_case_roster_sha256'] and not unexpected,
    'scope': 'Read and export already completed original records only; this analysis does not supply missing current physical artifact guards or qualify tests.',
}
OUT.mkdir(mode=0o700)
report_pin = save_json('catalog-analysis.json', report)
case_pin = save_json('complete-case-tuples.json', sorted(cases))
for pin, role in ((report_pin, 'derived-readonly-analysis'), (case_pin, 'derived-complete-case-tuples')):
    originals.append((Path(pin['path']).name, pin['path'], Path(pin['path']).read_bytes(), role))
assets = []
for number, (name, path, data, role) in enumerate(originals):
    compressed = gzip.compress(data, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == data
    encoded = base64.b64encode(compressed)
    chunks = []
    for offset in range(0, len(encoded), 60000):
        chunks.append(save(f'asset-{number:03d}-part-{offset // 60000:03d}.b64', encoded[offset:offset + 60000]))
    assets.append({'name': name, 'role': role, 'original': {'path': path, **identity(data)},
                   'compressed': identity(compressed), 'encoding': 'gzip-mtime0-base64',
                   'encoded_bytes': len(encoded), 'chunks': chunks})
manifest = {'schema': 'hepta-immutable-evidence-export-v1', 'host_alias': 'ai395', 'at': datetime.now(timezone.utc).isoformat(),
            'owned_directory': str(OUT), 'original_directory': str(PRIOR), 'assets': assets,
            'original_record_count': len(terminal['records']) + 1, 'derived_record_count': 2,
            'original_bytes': sum(len(x[2]) for x in originals if x[3].startswith('original')),
            'source_modified': False, 'commands_repeated': False, 'original_files_unchanged': True,
            'analysis': report_pin, 'complete_case_tuples': case_pin}
manifest_pin = save_json('export-manifest.json', manifest)
print(json.dumps({'success': True, 'analysis': report_pin, 'manifest': manifest_pin,
                  'counts': counts, 'distribution': report['filter_distribution'],
                  'case_counter_sha256': case_digest, 'exact_contract': report['exact_catalog_contract_holds'],
                  'assets': len(assets), 'chunks': sum(len(a['chunks']) for a in assets)}, sort_keys=True), flush=True)

