"""Recover original audit bytes from the fully downloaded actual raw index.

This does not access the native source or repeat lstat.  The original producer's
stat-comparison result is retained only when the complete audit identity matches.
"""
import ast
import base64
import gzip
import hashlib
import json
import os
import pathlib
import struct

ROOT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
OUT = ROOT / 'recovered-index-audit'
OUT.mkdir(exist_ok=True)
DRIVER = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1/driver.HOLD.py')

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def create(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **identity(raw)}

driver_raw = DRIVER.read_bytes()
assert identity(driver_raw) == {'bytes': 46159, 'sha256': 'f82c0550492a6f6230e29a5047777ec999a563669ec124425a3149b4f115b4e5', 'git_blob': 'e8d606b801b54ab949c5f215c49cdf47ed0ea89a'}
source = driver_raw.decode()
nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'parse_index']
assert len(nodes) == 1
function_text = ''.join(source.splitlines(keepends=True)[nodes[0].lineno - 1:nodes[0].end_lineno])
namespace = {'check': check, 'struct': struct, 'hashlib': hashlib, 'LEAVES': 15243}
exec(compile(function_text, str(DRIVER) + ':pure-parse_index-only', 'exec'), namespace)
parse_index = namespace['parse_index']
catalogue = {row['name']: row for row in json.loads((ROOT / 'ARTIFACTS.json').read_bytes())}
parsed = {}
actual_indices = {}
for stage in ('before', 'final'):
    raw = (ROOT / 'artifacts' / ('INDEX.' + stage + '.raw')).read_bytes()
    native = catalogue['INDEX.' + stage + '.raw.gz']
    assert identity(raw) == {key: native['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}
    parsed[stage] = parse_index(raw)
    actual_indices[stage] = identity(raw)
before, before_extensions = parsed['before']
entries, extensions = parsed['final']
assert set(before) == set(entries) and len(entries) == 15243
assert [row['name'] for row in extensions] == ['TREE']
expected_path = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1/EXPECTED_AFTER_INVENTORY.json')
expected_raw = expected_path.read_bytes()
assert identity(expected_raw) == {'bytes': 5631947, 'sha256': 'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e', 'git_blob': '457adb9bf9ba3a844e9dfa149be49460bb306998'}
expected = {row['path']: row for row in json.loads(expected_raw)['files']}
assert set(expected) == set(entries)
rows = []
for path in sorted(entries, key=os.fsencode):
    entry = entries[path]
    leaf = expected[path]
    mode = '120000' if leaf['kind'] == 'symlink' else ('100755' if leaf['permissions'] & 0o111 else '100644')
    assert entry['mode'] == mode and entry['sha'] == leaf['working_blob']
    assert not entry['flags'] & 0xf000 and entry['flags'] == min(len(os.fsencode(path)), 0xfff)
    rows.append({'path': path, 'mode': entry['mode'], 'sha': entry['sha'], 'flags': entry['flags'], 'stat': list(entry['stat']), 'raw_entry_sha256': hashlib.sha256(entry['raw']).hexdigest()})
candidate = {'entry_count': len(rows), 'all_entries_equal_canonical_tree': True, 'all_stat_fields_match_actual_files': True, 'entries': rows, 'extensions': [{'name': row['name'], 'bytes': row['bytes'], 'sha256': hashlib.sha256(row['raw']).hexdigest()} for row in extensions]}
raw = (json.dumps(candidate, sort_keys=True, separators=(',', ':')) + '\n').encode()
compressed = gzip.compress(raw, mtime=0)
aliases = []
for name in ('INDEX.pre-head-cas.audit.json.gz', 'INDEX.final.audit.json.gz'):
    expected_row = catalogue[name]
    assert identity(raw) == {key: expected_row['raw_' + key] for key in ('bytes', 'sha256', 'git_blob')}, name
    assert identity(compressed) == {key: expected_row[key] for key in ('bytes', 'sha256', 'git_blob')}, name
    parts = []
    for part in expected_row['parts']:
        block = compressed[part['decoded_offset']:part['decoded_offset'] + part['decoded_bytes']]
        assert len(block) == part['decoded_bytes'] and hashlib.sha256(block).hexdigest() == part['decoded_sha256']
        encoded = base64.b64encode(block) + b'\n'
        assert identity(encoded) == {key: part[key] for key in ('bytes', 'sha256', 'git_blob')}
        parts.append({'name': part['name'], **identity(encoded)})
        if name == 'INDEX.final.audit.json.gz':
            create(OUT / part['name'], encoded)
    aliases.append({'name': name, 'raw': identity(raw), 'gzip': identity(compressed), 'parts': parts})
create(OUT / 'INDEX.final.audit.json', raw)
create(OUT / 'INDEX.final.audit.json.gz', compressed)
assert {key: catalogue['INDEX.pre-head-cas.raw.gz'][key] for key in ('bytes', 'sha256', 'git_blob', 'raw_bytes', 'raw_sha256', 'raw_git_blob')} == {key: catalogue['INDEX.final.raw.gz'][key] for key in ('bytes', 'sha256', 'git_blob', 'raw_bytes', 'raw_sha256', 'raw_git_blob')}
report = {'format': 'hepta-original-index-audit-exact-recovery-from-actual-raw-index-v1', 'status': 'EXACT_ALL_RAW_GZIP_AND_PART_IDENTITIES_MATCH', 'job_id': '1a1d4cbd33e-392-5a9', 'actual_raw_indices': actual_indices, 'original_driver': identity(driver_raw), 'original_parse_index': identity(function_text.encode()), 'logical_entries': len(entries), 'canonical_blob_mode_and_normal_flags_match': True, 'changed_raw_entry_paths': [path for path in sorted(entries, key=os.fsencode) if entries[path]['raw'] != before[path]['raw']], 'aliases': aliases, 'new_native_lstat_performed': False, 'new_native_audit_file_download_performed': False, 'stat_comparison_scope': 'all_stat_fields_match_actual_files is the original producer assertion, proven to be retained by complete raw/gzip/part identity equality. This recovery only decodes actual raw index stat fields; it does not independently repeat filesystem lstat.', 'qualification': False}
report_raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
print(json.dumps({'review': create(OUT / 'EXACT_RECOVERY_REVIEW.json', report_raw), 'raw': identity(raw), 'gzip': identity(compressed), 'alias_count': len(aliases), 'parts_per_alias': len(aliases[0]['parts']), 'changed_entry_count': len(report['changed_raw_entry_paths'])}))
