#!/usr/bin/env python3
"""Only immutable byte/map evaluation; no materializer import, I/O helpers, or main."""
from __future__ import annotations
import ast, base64, hashlib, json, os, pathlib
HERE = pathlib.Path(__file__).resolve().parent
OLD = pathlib.Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1')
def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
source = (HERE / 'driver.HOLD.py').read_text()
fixed_pin = identity(source.encode())
assert fixed_pin['git_blob'] == '6d1537fcd58540da64c18916369f4f04d2a0dce1'
module = ast.parse(source)
names = {'check', 'sha256', 'oid', 'nodup', 'parse', 'encoded', 'pin', 'identity', 'identity_projection',
         'raw_commit_fields', 'tree_objects', 'native_projection', 'derive_candidate_inventory', 'expected_graphs'}
selected = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert len(selected) == len(names)
ns = {'base64': base64, 'hashlib': hashlib, 'json': json, 'os': os, 'pathlib': pathlib,
      'HEAD': '0c59aaca0b4932507f068c723f73da2f96729b3d', 'TREE': '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09',
      'PARENT': 'cc57c7198db6293ccca562253c42fffbe2a04633', 'LEAVES': 15237,
      'DONOR_HEAD': 'cc57c7198db6293ccca562253c42fffbe2a04633', 'DONOR_TREE': 'b7b357c07b5539769a068c6b9b009629f5612d1e',
      'DONOR_LEAVES': 15188, 'result': {}}
recorded = []
ns['remaining'] = lambda: 1
ns['gzrecord'] = lambda name, raw: recorded.append({'name': name, **identity(raw)})
exec(compile(ast.Module(body=selected, type_ignores=[]), 'only-two-pure-packet-binding-functions', 'exec'), ns)
ns['packet'] = json.loads((HERE / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes())
ns['donor_complete'] = json.loads((OLD / 'CC57_INVENTORY.json').read_bytes())
ns['base_input'] = json.loads((OLD / 'BASE_OBJECT_INPUT.json').read_bytes())
ns['candidate_input'] = json.loads((HERE / 'CANDIDATE_OBJECT_INPUT.json').read_bytes())
ns['derive_candidate_inventory']()
ns['expected_graphs']()
expected_objects = json.loads((HERE / 'EXPECTED_OBJECT_IDENTITIES.json').read_bytes())
expected_donor = json.loads((HERE / 'EXPECTED_DONOR_OBJECT_IDENTITIES.json').read_bytes())
assert ns['object_index'] == {row['sha']: {k: row[k] for k in ('type', 'bytes', 'sha256')} for row in expected_objects}
assert ns['donor_object_keys'] == {row['sha'] for row in expected_donor}
assert ns['encoded'](ns['complete']) == (HERE / 'EXPECTED_CANDIDATE.complete.inventory.json').read_bytes()
# Evaluate only the exact frozen producer-data predicates in preflight.
# No cfg approval predicate, native read, constructor, process or mutation function runs.
observed = json.loads((HERE / 'DONOR_RESULT.original.json').read_bytes())
predicate_context = {**ns, 'observed': observed, 'SOURCE': pathlib.Path('/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'),
                     'actual_inventory': observed['current_source_after']['inventory']}
predicate_records = []
preflight = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'preflight')
for node in preflight.body:
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == 'check'):
        continue
    predicate = node.value.args[0]
    identifiers = {item.id for item in ast.walk(predicate) if isinstance(item, ast.Name)}
    if not ({'observed', 'actual_inventory'} & identifiers):
        continue
    actual = eval(compile(ast.Expression(body=predicate), 'actual-immutable-donor-predicate', 'eval'), predicate_context)
    assert actual is True
    predicate_records.append({'line': node.lineno, 'predicate': ast.get_source_segment(source, predicate), 'evaluates_true_on_actual_original_proof': True})
assert len(predicate_records) == 4
report = {'format': 'hepta-pure-prepared-input-binding-review-v1', 'status': 'STATIC_ONLY_NOT_EXECUTION_APPROVAL',
          'driver': fixed_pin, 'loaded_definitions': sorted(names), 'pure_mapping_functions_called': ['derive_candidate_inventory', 'expected_graphs'],
          'full_driver_imported': False, 'runtime_or_main_executed': False, 'H_calls': 0, 'source_mutations': 0, 'qualification': False,
          'runtime_remaining_and_recording_not_exercised': True,
          'immutable_donor_producer_predicates': predicate_records, 'expected_objects': len(ns['object_index']),
          'donor_object_count': len(ns['donor_object_keys']), 'provided_object_count': len(ns['provided_raw']),
          'four_commit_raw_identities_match_exact_refs': len(ns['raw_commits']) == 4,
          'candidate_complete_inventory_equal_independent_preparation': True, 'computed_record_identities': recorded,
          'future_live_donor_body_reads_and_all_runtime_guards_still_required': True,
          'original_budget_seconds_unchanged': [600, 180, 900]}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
with (HERE / 'STATIC_INPUT_BINDING_REVIEW.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'report': identity(raw), 'objects': len(ns['object_index']), 'predicate_count': len(predicate_records)}))
