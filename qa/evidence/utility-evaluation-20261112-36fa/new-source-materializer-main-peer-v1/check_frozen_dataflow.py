#!/usr/bin/env python3
"""Root-authorized offline schema/dataflow audit; never loads the driver module.

Only named pure function ASTs are compiled. The driver's recording function is
replaced by an in-memory capture. No preflight/main/Git/H/source path is invoked.
"""
import ast
import base64
import collections
import hashlib
import json
import os
import pathlib
import time

HERE = pathlib.Path(__file__).parent
AUTHOR = pathlib.Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
FIXED = HERE / 'frozen'
DRIVER_OID = '6d1537fcd58540da64c18916369f4f04d2a0dce1'
PACKET_OID = '728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def check_pin(raw, expected):
    actual = identity(raw)
    assert all(actual[key] == expected[key] for key in ('bytes', 'sha256', 'git_blob')), (actual, expected)
    return actual


def read_json(path):
    return json.loads(path.read_bytes())


def main():
    output = HERE / 'FROZEN_DATAFLOW_REVIEW.json'
    assert not output.exists(), 'create-only review'
    sources = {}
    for path in sorted(FIXED.glob('*.GET.original.json')):
        name = path.name.removesuffix('.GET.original.json')
        original = read_json(path)['structuredContent']['content'].encode()
        actual = (FIXED / name).read_bytes()
        assert original == actual, name
        sources[name] = identity(actual)
    assert len(sources) == 11
    source = (FIXED / 'driver.HOLD.py').read_text()
    assert identity(source.encode())['git_blob'] == DRIVER_OID
    packet_raw = (FIXED / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes()
    assert identity(packet_raw)['git_blob'] == PACKET_OID
    packet = json.loads(packet_raw)
    syntax = ast.parse(source)
    definition_names = {
        'check', 'sha256', 'oid', 'nodup', 'parse', 'encoded', 'pin',
        'remaining', 'tree_objects', 'raw_commit_fields', 'identity_projection',
        'native_projection', 'derive_candidate_inventory', 'expected_graphs',
        'parse_supervisor',
    }
    selected = [node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name in definition_names]
    assert {node.name for node in selected} == definition_names
    assert all(node.decorator_list == [] for node in selected)
    # A no-I/O record adapter is deliberately external to the frozen function ASTs.
    captures = {}
    def capture(name, raw):
        assert name in {'EXPECTED_CANDIDATE.complete.inventory.json', 'EXPECTED_OBJECTS.json'}
        assert name not in captures
        captures[name] = raw
        return {'name': name, **identity(raw), 'offline_memory_capture_only': True}
    scope = {'__builtins__': __builtins__, 'base64': base64, 'hashlib': hashlib,
             'json': json, 'os': os, 'pathlib': pathlib, 'time': time,
             'deadline': time.monotonic() + 60, 'gzrecord': capture,
             'packet': packet, 'result': {}}
    constants = {'HEAD', 'TREE', 'PARENT', 'LEAVES', 'DONOR_HEAD', 'DONOR_TREE', 'DONOR_LEAVES'}
    for node in syntax.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in constants:
            scope[node.targets[0].id] = ast.literal_eval(node.value)
    assert constants <= set(scope)
    # Defining functions does not evaluate any of the original module's top level.
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<frozen-pure-functions-only>', 'exec'), scope)
    donor_path = pathlib.Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json')
    base_path = pathlib.Path('/tmp/hepta-36fa-c0f-format-base-independent-peer-v1/inputs/BASE_OBJECT_INPUT.json')
    candidate_path = AUTHOR / 'CANDIDATE_OBJECT_INPUT.json'
    donor_raw, base_raw, candidate_raw = [path.read_bytes() for path in (donor_path, base_path, candidate_path)]
    check_pin(donor_raw, packet['donor']['inventory'])
    check_pin(base_raw, packet['provided_inputs']['base']['raw'])
    check_pin(candidate_raw, packet['provided_inputs']['candidate']['raw'])
    scope.update(donor_complete=scope['parse'](donor_raw), base_input=scope['parse'](base_raw), candidate_input=scope['parse'](candidate_raw))
    assert scope['donor_complete']['source'] == {'head': scope['DONOR_HEAD'], 'tree': scope['DONOR_TREE'], 'status': ''}
    assert len(scope['donor_complete']['files']) == 15188
    scope['derive_candidate_inventory']()
    scope['expected_graphs']()
    complete_raw = captures['EXPECTED_CANDIDATE.complete.inventory.json']
    native_raw = scope['native_projection'](complete_raw)
    complete_pin = check_pin(complete_raw, packet['current']['inventory'])
    native_pin = check_pin(native_raw, packet['current']['native_inventory'])
    assert complete_raw == (AUTHOR / 'EXPECTED_CANDIDATE.complete.inventory.json').read_bytes()
    assert native_raw == (AUTHOR / 'EXPECTED_CANDIDATE.native-five-field.inventory.json').read_bytes()
    object_rows = scope['parse'](captures['EXPECTED_OBJECTS.json'])
    expected_rows = read_json(AUTHOR / 'EXPECTED_OBJECT_IDENTITIES.json')
    assert object_rows == expected_rows
    assert len({row['sha'] for row in object_rows}) == len(object_rows) == 16652
    donor_expected = read_json(AUTHOR / 'EXPECTED_DONOR_OBJECT_IDENTITIES.json')
    assert {row['sha']: {k: row[k] for k in ('type', 'bytes', 'sha256')} for row in donor_expected} == {key: scope['object_index'][key] for key in scope['donor_object_keys']}
    assert len(scope['donor_object_keys']) == 16449 and len(scope['provided_raw']) == 203
    counts = dict(collections.Counter(row['type'] for row in object_rows))
    assert counts == {'blob': 14796, 'tree': 1852, 'commit': 4}
    actual_candidate_raw = (HERE / 'inputs/CANONICAL_0c59.raw').read_bytes()
    assert scope['raw_commits'][scope['HEAD']] == actual_candidate_raw
    # Validate the original proof parser and the exact four proof-only predicates.
    # No preflight function is loaded or called.
    observed_raw = (AUTHOR / 'DONOR_RESULT.original.json').read_bytes()
    supervisor_raw = (AUTHOR / 'DONOR_NORMAL_SUPERVISOR.original.json').read_bytes()
    check_pin(observed_raw, packet['donor_proof']['result'])
    check_pin(supervisor_raw, packet['donor_proof']['supervisor'])
    normal = scope['parse_supervisor'](supervisor_raw, packet['donor_proof']['job_id'])
    observed = scope['parse'](observed_raw)
    scope.update(observed=observed, actual_inventory=observed['current_source_after']['inventory'], SOURCE=pathlib.Path(packet['source_repo']))
    proof_messages = {
        'actual independent donor materialization proof, not a new qualification',
        'completed preparation-only donor proof',
        'all original donor source/Git/input audit facts',
        'actual full donor source and distinct native inventory',
    }
    preflight = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == 'preflight')
    checks = [node for node in preflight.body if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'check' and len(node.value.args) == 2 and isinstance(node.value.args[1], ast.Constant) and node.value.args[1].value in proof_messages]
    assert len(checks) == len(proof_messages) == 4
    for statement in checks:
        exec(compile(ast.Module(body=[statement], type_ignores=[]), '<exact-donor-proof-expression-only>', 'exec'), scope)
    donor_metadata_raw = (AUTHOR / 'DONOR_GIT_METADATA.recovered.json').read_bytes()
    check_pin(donor_metadata_raw, packet['donor_proof']['current_git_metadata'])
    assert scope['parse'](donor_metadata_raw) == packet['donor_git']['files']
    assert len(packet['donor_git']['files']) == 6
    # Byte and AST preservation is computed independently of the author report.
    old_source = (HERE / 'inputs/MATERIALIZER_972ec.original.py').read_text()
    old_defs = {node.name: node for node in ast.parse(old_source).body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    new_defs = {node.name: node for node in syntax.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    unchanged, changed, added = [], [], []
    for name, node in new_defs.items():
        if name not in old_defs:
            added.append(name)
        elif ast.get_source_segment(old_source, old_defs[name]) == ast.get_source_segment(source, node):
            assert ast.dump(old_defs[name], include_attributes=False) == ast.dump(node, include_attributes=False)
            unchanged.append(name)
        else:
            changed.append(name)
    assert not (old_defs.keys() - new_defs.keys())
    assert len(unchanged) == 45 and len(changed) == 9 and len(added) == 2
    report = {
        'schema': 'hepta-successor-materializer-frozen-offline-dataflow-review-v1',
        'status': 'FROZEN_INPUT_AND_PURE_FUNCTION_DATAFLOW_MATCH',
        'driver': sources['driver.HOLD.py'], 'packet': sources['MATERIALIZATION_PACKET.HOLD.json'],
        'complete_control_GETs': sources,
        'source_and_destination': {'donor_commit': scope['DONOR_HEAD'], 'donor_tree': scope['DONOR_TREE'], 'donor_leaves': 15188, 'candidate_commit': scope['HEAD'], 'candidate_tree': scope['TREE'], 'candidate_parents': [scope['PARENT']], 'candidate_leaves': 15237},
        'dataflow': {'donor_input': identity(donor_raw), 'base_input': identity(base_raw), 'candidate_input': identity(candidate_raw),
                     'exact_complete_inventory': complete_pin, 'exact_native_projection': native_pin,
                     'all_expected_object_rows_equal': True, 'exact_object_count': len(object_rows), 'object_types': counts,
                     'donor_object_count': len(scope['donor_object_keys']), 'provided_object_count': len(scope['provided_raw']),
                     'candidate_commit_body_matches_actual_root_raw': True, 'candidate_is_actual_filesystem_observation': False},
        'proof_parser': {'original_parse_supervisor_returned_matching_normal_job': normal['job_id'], 'four_original_proof_predicates_passed': sorted(proof_messages), 'all_six_fixed_donor_git_metadata_rows_equal': True, 'metadata_source_is_exact_original_recovery_not_new_native_observation': True},
        'definition_delta': {'old': len(old_defs), 'new': len(new_defs), 'unchanged_byte_and_AST': sorted(unchanged), 'changed': sorted(changed), 'added': sorted(added), 'removed': []},
        'extracted_functions': [{'name': node.name, 'source_identity': identity(ast.get_source_segment(source, node).encode())} for node in selected],
        'isolation': {'whole_driver_module_imported': False, 'top_level_driver_executed': False, 'preflight_called': False, 'main_called': False, 'Git_or_H_called': False, 'SOURCE_or_TARGET_paths_accessed': False, 'record_adapter': 'Memory-only capture for two expected-record names; no native output path is used.', 'analysis_time_guard_seconds': 60, 'time_guard_is_not_a_materializer_or_test_budget_change': True, 'remaining_function_itself_is_original': True},
        'execution_scope': 'Only named pure AST functions and four exact proof-only predicates were evaluated against frozen local JSON. No source/Rust/QA/gate/materialization execution occurred.'
    }
    with output.open('xb') as stream:
        stream.write((json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps({'status': report['status'], 'output': identity(output.read_bytes()), 'objects': len(object_rows), 'types': counts, 'complete': complete_pin, 'native': native_pin}, sort_keys=True))


if __name__ == '__main__':
    main()
