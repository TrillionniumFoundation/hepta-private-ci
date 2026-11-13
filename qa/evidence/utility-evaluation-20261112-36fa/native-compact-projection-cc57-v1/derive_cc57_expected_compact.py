#!/usr/bin/env python3
"""Invoke the byte-identical 9d9d projection function with explicit new source pins."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import types

ROOT = Path('/tmp/hepta-36fa-native-compact-projection-cc57-v1')
ORIGINAL = Path('/tmp/hepta-36fa-native-compact-projection-v1/project_native_inventory.py')
FULL = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
ORIGINAL_PIN = {
    'bytes': 9314,
    'sha256': '44f424f6a27d265afcde1896b2e67c959dcb73277f02feb48a023591ac6c4065',
    'git_blob': '9d9d81fd59ddd9876321f8abf9ed389e76d5445c',
}
EXPECTED_FULL_PIN = {
    'bytes': 5611184,
    'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
    'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537',
}
EXPECTED_SOURCE = {
    'head': 'cc57c7198db6293ccca562253c42fffbe2a04633',
    'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e', 'status': '',
}


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return {'name': name, **pin(raw)}


def jbytes(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def main():
    ROOT.mkdir(exist_ok=True)
    original_raw = ORIGINAL.read_bytes()
    assert pin(original_raw) == ORIGINAL_PIN
    save('original_project_native_inventory.py', original_raw)
    full_raw = FULL.read_bytes()
    assert pin(full_raw) == EXPECTED_FULL_PIN
    full = json.loads(full_raw)
    assert full['source'] == EXPECTED_SOURCE

    # This is the pure projection artifact, not b92/gate/native code. Its main
    # guard is not entered. The original file and every function byte remain
    # unchanged; only the two source-specific input globals are explicitly bound.
    module = types.ModuleType('hepta_original_pure_compact_projection')
    module.__file__ = str(ROOT / 'original_project_native_inventory.py')
    exec(compile(original_raw, module.__file__, 'exec'), module.__dict__)
    original_full_pin = copy.deepcopy(module.FULL_PIN)
    original_source = copy.deepcopy(module.SOURCE)
    assert original_full_pin['sha256'] == 'df891018254756c61007f91dd7cd9f794a550dc6ad33f389849eb44eaffc9b3e'
    assert original_source['head'] == '246d8cb614770252ee42029a5c014f2a4904176a'
    assert module.COUNT == 15188
    original_functions = {name: module.__dict__[name].__code__ for name in ('pin', 'require', 'project')}
    module.FULL_PIN = copy.deepcopy(EXPECTED_FULL_PIN)
    module.SOURCE = copy.deepcopy(EXPECTED_SOURCE)
    compact, summary, original_report = module.project(full_raw)
    assert all(module.__dict__[name].__code__ is code for name, code in original_functions.items())
    compact_record = save('NATIVE_COMPACT_INVENTORY.projected.json', compact)
    snapshot_record = save('NATIVE_SNAPSHOT.projected.json', jbytes(summary))
    original_report_record = save('ORIGINAL_PROJECT_RETURN_REPORT.json', jbytes(original_report))

    rows = json.loads(compact)
    original_by_path = {row['path']: row for row in full['files']}
    assert len(rows) == len(original_by_path) == 15188
    assert all(set(row) == {'path', 'mode', 'bytes', 'sha256', 'blob'} for row in rows)
    assert [row['path'] for row in rows] == sorted(original_by_path, key=lambda value: value.encode('ascii'))
    for row in rows:
        source = original_by_path[row['path']]
        assert row['mode'] == source['index_mode']
        assert row['bytes'] == source['bytes'] and row['sha256'] == source['sha256']
        assert row['blob'] == source['working_blob'] == source['index_blob']
    assert not compact.endswith(b'\n')
    assert compact == json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    assert summary == {'commit': EXPECTED_SOURCE['head'], 'tree': EXPECTED_SOURCE['tree'],
                       'status': '', 'files': 15188, 'inventory_sha256': pin(compact)['sha256']}

    # The historical compact is read only as a comparison artifact. It is not
    # imported as an actual snapshot or used in place of the current full input.
    old_compact_raw = Path('/tmp/hepta-36fa-native-compact-projection-v1/output/NATIVE_COMPACT_INVENTORY.projected.json').read_bytes()
    assert pin(old_compact_raw)['sha256'] == '2fa7277b524b57b91c4517655ea086ad0314a4a33df0d47ed230d8afb931a62a'
    old_rows = json.loads(old_compact_raw)
    assert [row['path'] for row in old_rows] == [row['path'] for row in rows]
    differences = [{'path': new['path'], 'before': old, 'after': new}
                   for old, new in zip(old_rows, rows) if old != new]
    changes = json.loads(Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/NONRUST_APPLY_PACKET.json').read_bytes())['changes']
    assert [row['path'] for row in differences] == [change['path'] for change in changes]
    for row, change in zip(differences, changes):
        assert {key: row['before'][key] for key in ('bytes', 'sha256')} == {key: change['before'][key] for key in ('bytes', 'sha256')}
        assert {key: row['after'][key] for key in ('bytes', 'sha256')} == {key: change['after'][key] for key in ('bytes', 'sha256')}
        assert row['before']['blob'] == change['before']['git_blob'] and row['after']['blob'] == change['after']['git_blob']
        assert row['before']['mode'] == row['after']['mode'] == change['mode']

    compressed = gzip.compress(compact, compresslevel=9, mtime=0)
    gzip_record = save('NATIVE_COMPACT_INVENTORY.projected.json.gz', compressed)
    parts = []
    for number, offset in enumerate(range(0, len(compressed), 262144), 1):
        piece = compressed[offset:offset + 262144]
        body = base64.b64encode(piece) + b'\n'
        parts.append({**save(f'NATIVE_COMPACT_INVENTORY.projected.json.gz.part-{number:03d}.b64', body),
                      'decoded_offset': offset, 'decoded_bytes': len(piece),
                      'decoded_sha256': hashlib.sha256(piece).hexdigest()})
    assert gzip.decompress(b''.join(base64.b64decode((ROOT / row['name']).read_bytes()) for row in parts)) == compact
    report = {
        'format': 'hepta-cc57-original-native-compact-projection-report-v1',
        'status': 'EXPECTED_PROJECTION_ONLY_NOT_ACTUAL_ALIGNMENT_OR_NATIVE_SNAPSHOT',
        'original_projection_script_byte_pin': ORIGINAL_PIN,
        'original_script_copy_unchanged': True, 'original_function_code_objects_unchanged': True,
        'original_main_executed': False,
        'only_external_input_global_rebindings': {
            'FULL_PIN': {'before': original_full_pin, 'after': EXPECTED_FULL_PIN},
            'SOURCE': {'before': original_source, 'after': EXPECTED_SOURCE},
        },
        'full_expected_input': EXPECTED_FULL_PIN, 'source_expected': EXPECTED_SOURCE,
        'compact_expected': compact_record, 'snapshot_expected': snapshot_record,
        'snapshot_expected_value': summary,
        'complete_mapping': {
            'rows': 15188, 'all_paths_preserved': True,
            'all_five_fields_exactly_mapped': True,
            'row_fields': ['path', 'mode', 'bytes', 'sha256', 'blob'],
            'sort': 'Unique raw Git path bytes; all 15188 paths are ASCII.',
            'mode': 'Original symlink/physical execute-bit rule, checked equal to the full inventory index mode.',
            'content': 'Original full row bytes, SHA256 and working Git blob; every working/index blob matches and every full row is stable.',
            'serializer': "json.dumps(rows, sort_keys=True, separators=(',', ':')).encode(); default ensure_ascii=True; no terminal LF.",
            'source_files_read_or_written': 0,
        },
        'historical_compact_comparison': {
            'before': pin(old_compact_raw), 'unchanged_rows': 15183,
            'changed_rows': differences, 'same_order_modes_and_membership': True,
            'only_five_approved_source_rows_change': True,
        },
        'original_function_return_report_preserved': original_report_record,
        'historical_literal_note': 'The byte-identical original function return includes the explanatory literal df891018... from its prior input. It is preserved in ORIGINAL_PROJECT_RETURN_REPORT.json. The current full_expected_input and source_expected fields in both reports are the new 13d3... and cc57 pins; no interchangeability of full/compact/clone formats is claimed.',
        'derived_transport': {
            'gzip': gzip_record, 'parts': parts,
            'original_b92_native_gzip_identity_not_predicted': True,
            'reconstruction': 'Decode each base64 text part separately, concatenate in listed order, verify the derived gzip, gunzip, verify the complete compact JSON identity. Native gates bind the uncompressed inventory hash; these transport gzip bytes are not a native snapshot.',
        },
        'requirements': [
            'Actual normal canonical alignment and all complete audits must be observed.',
            'Its actual full source inventory must match the exact current 13d3... input identity.',
            'The original native snapshot must then run from the actual checkout and independently match commit/tree/status/count and this compact uncompressed SHA256.',
            'Original b92 before/after snapshots, full source observations, gates, budgets and ignored-output reporting remain required.',
        ],
        'H_or_native_or_Git_commands': 0, 'gate_or_Cargo_tests_executed': 0,
        'commit_or_ref_changes': False, 'qualification': False,
    }
    report_record = save('PROJECTION_REPORT.json', jbytes(report))
    print(json.dumps({'compact': compact_record, 'snapshot': summary, 'report': report_record,
                      'parts': len(parts), 'original_function_unchanged': True}, sort_keys=True))


if __name__ == '__main__':
    main()
