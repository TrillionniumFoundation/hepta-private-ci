#!/usr/bin/env python3
"""Pure cloud generation of the reviewed candidate's exact HOLD controls."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
EXPECTED = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/expected-inventory-v1')
TARGET = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1'
STAGING = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-materialization-v1'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pretty(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def write(name, raw):
    with (HERE / name).open('xb') as stream:
        stream.write(raw)
    return {'name': name, **pin(raw)}


packet_raw = (HERE / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes()
packet = json.loads(packet_raw)
assert packet['current']['commit'] == 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
assert packet['current']['tree'] == 'a489b394666b8141840275128a780605b024cde0'
assert packet['current']['parents'] == ['cc57c7198db6293ccca562253c42fffbe2a04633']
assert packet['current']['leaves'] == 15243
assert packet['object_scope']['union_objects'] == 16661
assert packet['object_scope']['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}
assert packet['object_scope']['provided_candidate_objects'] == 129
assert packet['object_scope']['provided_base_candidate_overlap'] == []

comparison = []
for own, other, field in [
    ('EXPECTED_CANDIDATE.complete.inventory.json', 'EXPECTED_CLEAN_INVENTORY.json', 'inventory'),
    ('EXPECTED_CANDIDATE.native-five-field.inventory.json', 'EXPECTED_NATIVE_FIVE_FIELD.json', 'native_inventory'),
]:
    raw = (HERE / own).read_bytes()
    original = (EXPECTED / other).read_bytes()
    assert raw == original
    assert pin(raw) == packet['current'][field]
    comparison.append({'independent_preparer_output': str(HERE / own),
                       'ordinary_frozen_expected': str(EXPECTED / other),
                       'full_bytes_equal': True, **pin(raw)})
write('PURE_EXPECTED_INPUT_COMPARISON.json', pretty({
    'status': 'EXPECTED_BYTES_EQUAL_NOT_NATIVE_OBSERVATION',
    'native_calls': 0, 'qualification': False, 'comparisons': comparison,
}))

original_raw = (ORIGINAL / 'driver.HOLD.py').read_bytes()
assert pin(original_raw) == {
    'bytes': 70560,
    'sha256': '2c4c8582d1940605d1b2138587ee3a73ab4b4d6eb265bfcb03ffd7d291c8b1f6',
    'git_blob': '6d1537fcd58540da64c18916369f4f04d2a0dce1',
}
source = original_raw.decode()
replacements = [
    ("TARGET = pathlib.Path('/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1')",
     'TARGET = pathlib.Path(' + repr(TARGET) + ')'),
    ("CONTROL = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1')",
     'CONTROL = pathlib.Path(' + repr(CONTROL) + ')'),
    ("STAGING_PREFIX = '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-materialization-v1'",
     'STAGING_PREFIX = ' + repr(STAGING)),
    ("HEAD = '0c59aaca0b4932507f068c723f73da2f96729b3d'",
     "HEAD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'"),
    ("TREE = '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'",
     "TREE = 'a489b394666b8141840275128a780605b024cde0'"),
    ('LEAVES = 15237', 'LEAVES = 15243'),
    ("PACKET_PIN = {'bytes': 14331, 'sha256': 'b733baa29e1b70c6fa57582d61dfe47e360e9d3de4d0ef482193be30057914c6', 'git_blob': '728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'}",
     'PACKET_PIN = ' + repr(pin(packet_raw))),
    ("check(len(covered) == packet['overlay']['covered_paths'] == 110 and added == packet['overlay']['new_paths'] == 49 and changed == packet['overlay']['modified_paths'] == 60 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 110-path overlay')",
     "check(len(covered) == packet['overlay']['covered_paths'] == 119 and added == packet['overlay']['new_paths'] == 55 and changed == packet['overlay']['modified_paths'] == 63 and unchanged == packet['overlay']['unchanged_covered_paths'] == 1, 'exact complete reviewed 119-path overlay')"),
    ('candidate_provided = add_provided(candidate_input, 120)',
     'candidate_provided = add_provided(candidate_input, 129)'),
    ("check(len(object_index) == packet['object_scope']['union_objects'] == 16652 and counts == packet['object_scope']['counts'] == {'blob': 14796, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')",
     "check(len(object_index) == packet['object_scope']['union_objects'] == 16661 and counts == packet['object_scope']['counts'] == {'blob': 14805, 'tree': 1852, 'commit': 4}, 'complete exact four-snapshot union, not ancestry')"),
]
modified = source
for before, after in replacements:
    assert modified.count(before) == 1
    modified = modified.replace(before, after, 1)
inverse = modified
for before, after in reversed(replacements):
    assert inverse.count(after) == 1
    inverse = inverse.replace(after, before, 1)
assert inverse.encode() == original_raw
before_ast, after_ast = ast.parse(source), ast.parse(modified)
before_definitions = {node.name: ast.get_source_segment(source, node)
                      for node in before_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
after_definitions = {node.name: ast.get_source_segment(modified, node)
                     for node in after_ast.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
assert set(before_definitions) == set(after_definitions)
changed = [name for name in before_definitions if before_definitions[name] != after_definitions[name]]
assert changed == ['derive_candidate_inventory', 'expected_graphs']
driver = write('driver.HOLD.py', modified.encode())
write('FROM_6D1537.diff', ''.join(difflib.unified_diff(
    source.splitlines(keepends=True), modified.splitlines(keepends=True),
    fromfile='6d1537/driver.HOLD.py', tofile='d256-a489/driver.HOLD.py')).encode())
write('FUNCTION_DELTA.json', pretty({
    'original': pin(original_raw), 'successor': pin(modified.encode()),
    'replacement_count': len(replacements), 'inverse_full_bytes_equal': True,
    'top_level_definition_count': len(before_definitions), 'changed_definitions': changed,
    'unchanged_definition_count': len(before_definitions) - len(changed),
    'unchanged_definition_names': [name for name in before_definitions if name not in changed],
    'all_changes_are_fixed_paths_commit_tree_packet_identity_and_exact_counts': True,
    'new_or_removed_definitions': [], 'ast_parse_only': True,
    'control_functions_invoked': False, 'native_calls': 0,
    'budgets': {'action': 600, 'records': 180, 'outer': 900},
    'caps': {'decoded_part': 524288, 'typed_input': 1048576, 'base_parts': 2, 'candidate_parts': 3},
}))

cfg = json.loads((ORIGINAL / 'WAITING_CONFIG.json').read_bytes())
assert cfg['root_execution_approved'] is False and cfg['status'] == 'WAITING_ROOT_EXACT_APPROVAL'
cfg.update(destination_repo=TARGET, control=CONTROL, driver=pin(modified.encode()))
config = write('WAITING_CONFIG.json', pretty(cfg))

requests = []
for label in ['base', 'candidate']:
    part_spec = packet['provided_inputs'][label]
    assert part_spec['maximum_decoded_part'] == 524288
    assert len(part_spec['parts']) == (2 if label == 'base' else 3)
    packed_parts = []
    for number, part in enumerate(part_spec['parts'], 1):
        raw = (HERE / (label.upper() + '.json.gz.part-%03d' % number)).read_bytes()
        assert pin(raw) == {key: part[key] for key in ('bytes', 'sha256', 'git_blob')}
        assert part['offset'] == sum(len(value) for value in packed_parts)
        assert part['path'] == STAGING + '-' + label + '.json.gz.part-%03d' % number
        assert part['mode'] == 0o600 and 0 < len(raw) <= 524288
        packed_parts.append(raw)
        name = 'STAGE_' + label.upper() + '_%03d.REQUEST.HOLD.json' % number
        prior_raw = (ORIGINAL / name).read_bytes()
        prior = json.loads(prior_raw)
        assert set(prior) == {'host', 'path', 'data_base64', 'expected_version'}
        assert prior_raw == pretty(prior)
        request = dict(prior, path=part['path'], data_base64=base64.b64encode(raw).decode())
        assert request['host'] == 'desktop' and request['expected_version'] == 'absent'
        body = pretty(request)
        assert len(body) <= 1048576
        write(name, body)
        requests.append({'name': name, 'host': 'desktop', 'path': part['path'],
                         'expected_version': 'absent', 'expected_mode': 0o600,
                         'decoded': pin(raw), 'decoded_bytes': len(raw), 'request': pin(body)})
    packed = b''.join(packed_parts)
    assert pin(packed) == part_spec['gzip']
    assert pin(gzip.decompress(packed)) == part_spec['raw']
manifest = json.loads((ORIGINAL / 'STAGING_MANIFEST.HOLD.json').read_bytes())
manifest.update(files=requests, input_packet=pin(packet_raw),
                max_actual_decoded_bytes=max(row['decoded_bytes'] for row in requests),
                max_actual_typed_bytes=max(row['request']['bytes'] for row in requests))
assert manifest['file_count'] == len(requests) == 5
stage = write('STAGING_MANIFEST.HOLD.json', pretty(manifest))
print(json.dumps({'status': 'HOLD_NO_H_EXECUTION_APPROVAL', 'driver': driver,
                  'config': config, 'stage_manifest': stage,
                  'changed_definitions': changed,
                  'unchanged_definitions': len(before_definitions) - len(changed),
                  'max_staging_typed_bytes': manifest['max_actual_typed_bytes'],
                  'native_calls': 0}, sort_keys=True))
