#!/usr/bin/env python3
"""Freeze an unexecuted source-registration layer using complete actual bytes.

This performs byte, AST, schema and lexical-position inspection only. It does
not call a QA method, the verifier, the source collector, Rust or a native tool.
"""
import ast
import base64
import copy
import difflib
import gzip
import hashlib
import importlib.util
import json
import re
import sys
import textwrap
import tomllib
from pathlib import Path

sys.dont_write_bytecode = True
R = Path(__file__).resolve().parent
F = Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1')
REC = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1')
COORD = Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1')
NAMES = Path('/tmp/hepta-36fa-coordinator-original-metadata-getters-v1')
QA = 'qa/b4-no-bypass/'
AGENT = 'codex-rs/hepta-agentd/src/'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(path, raw):
    if not isinstance(raw, bytes):
        raw = raw.encode() if isinstance(raw, str) else (json.dumps(raw, indent=2, sort_keys=True) + '\n').encode()
    target = F / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw, str(target)
    else:
        with target.open('xb') as stream:
            stream.write(raw)
    return {'path': str(target), **pin(raw)}


def assignment(source, name):
    found = [n for n in ast.parse(source).body if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    assert len(found) == 1, name
    return ast.literal_eval(found[0].value)


def method_map(source):
    return {(c.name, f.name): ast.get_source_segment(source, f)
            for c in ast.parse(source).body if isinstance(c, ast.ClassDef)
            for f in c.body if isinstance(f, ast.FunctionDef) and f.name.startswith('test_')}


def top_functions(source):
    return {n.name: ast.get_source_segment(source, n)
            for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}


inv_raw = (REC / 'final.inventory.exact_recovered.json').read_bytes()
assert pin(inv_raw)['git_blob'] == 'e1e48f35bb6cf5a3dd86c59472da77df87154b6a'
inventory = json.loads(inv_raw)
base_rows = {row['path']: row for row in inventory['files']}
base_pin = lambda row: {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
spec = importlib.util.spec_from_file_location('archived_pure_merkle', REC / 'recover_inventory.py')
merkle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merkle)
assert merkle.merkle(inventory['files']) == 'f905b18e6b05de1582024548179725a05d932536'

prepared = copy.deepcopy(base_rows)
prepared_blobs = {}
layers = []
for source in (COORD / 'SOURCE_PACKET.json', NAMES / 'SOURCE_PACKET.json'):
    raw = source.read_bytes()
    layer = json.loads(raw)
    layers.append({'path': str(source), **pin(raw)})
    for change in layer['source_changes']:
        path = change['path']
        after = base64.b64decode(change['after_base64'], validate=True)
        assert pin(after) == change['after']
        if path in prepared_blobs:
            assert pin(prepared_blobs[path]) == change['before']
        elif change['before'] is None:
            assert path not in prepared
        else:
            assert base_pin(prepared[path]) == change['before']
        before = base64.b64decode(change['before_base64'], validate=True) if change['before'] else None
        assert before is None or pin(before) == change['before']
        row = copy.deepcopy(prepared.get(path, {'path': path, 'index_mode': '100644', 'index_blob': None,
                                               'kind': 'file', 'permissions': 420, 'stable': True}))
        row.update(bytes=len(after), sha256=pin(after)['sha256'], working_blob=pin(after)['git_blob'], matches_index=False)
        prepared[path] = row
        prepared_blobs[path] = after
    if source.parent == COORD:
        assert merkle.merkle(list(prepared.values())) == 'a0bd2241a3a005b68a4682a339d2be016fa3fa72'
assert len(prepared) == 15243 and len(prepared_blobs) == 9
for path, after in prepared_blobs.items():
    assert (R / 'view' / path).read_bytes() == after
prepared_tree = merkle.merkle(list(prepared.values()))

old_raw = (R / 'before/CALLERS.toml').read_bytes()
new_raw = (R / 'after/CALLERS.toml').read_bytes()
old, new = tomllib.loads(old_raw.decode()), tomllib.loads(new_raw.decode())
assert len(old['boundary']) == 621 and len(new['boundary']) == 633
assert new['boundary'][:621] == old['boundary']
assert len(old['protected_file']) == 437 and len(new['protected_file']) == 442
assert all(a['forbidden'] == b['forbidden'] for a, b in zip(old['protected_file'], new['protected_file']))
assert old['protected_file'][411] == new['protected_file'][411]
for key in ('authority', 'source_roots', 'ignored_path_fragments'):
    assert old[key] == new[key]
assert new['privileged_inventory']['required_boundary_ids'][:621] == old['privileged_inventory']['required_boundary_ids']
assert new['privileged_inventory']['required_boundary_ids'][621:] == [r['id'] for r in new['boundary'][621:]]
assert all(not row['product_callers'] for row in new['boundary'][621:])

refresh = json.loads((R / 'FORMATTED_GUARD_REFRESH.draft.json').read_bytes())
assert refresh['errors'] == [] and len(refresh['changes']) == 23
changed_old = [i for i in range(437) if old['protected_file'][i] != new['protected_file'][i]]
assert changed_old == [row['index'] for row in refresh['changes']]
marker_summary = []
for row in refresh['changes']:
    i = row['index']
    assert row['before'] == old['protected_file'][i]
    assert row['after'] == new['protected_file'][i]
    assert (R / 'pre-format' / row['path']).exists()
    assert pin((R / 'pre-format' / row['path']).read_bytes()) == row['before_source']
    assert pin((R / 'before' / row['path']).read_bytes()) == row['after_source']
    for item in row['replacements']:
        assert item['field'].startswith(('required_order[', 'required_function_order['))
        assert '.top_level[' not in item['field'] and '.literal_calls[' not in item['field']
        marker_summary.append({'row': i, 'path': row['path'], 'field': item['field'],
                               'before': pin(item['before'].encode()), 'after': pin(item['after'].encode())})
assert len(marker_summary) == 80

contract_path = QA + 'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'
before_contract = json.loads((R / 'before' / contract_path).read_bytes())
contract_raw = (R / 'after' / contract_path).read_bytes()
contract = json.loads(contract_raw)
assert sum(map(len, before_contract['attacks'].values())) == 83
assert all(contract['attacks'][key] == value for key, value in before_contract['attacks'].items())
assert sum(map(len, contract['attacks'].values())) == 107
assert contract['new_boundaries'] == new['boundary'][569:]
assert contract['boundary_count'] == 633
checked = {key: new[key] for key in ('boundary', 'privileged_inventory', 'authority', 'source_roots', 'ignored_path_fragments')}
digest = hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
assert contract['complete_boundary_sha256'] == digest
scope_review = json.loads((R / 'PROVIDER_SCOPE_REFRESH.draft.json').read_bytes())
assert len(scope_review['old_scope_digest_updates']) == 39
assert len(scope_review['actual_attack_locations']) == 107
assert all(row['actual_occurrences'] > 0 for row in scope_review['actual_attack_locations'])
assert set(contract['scopes']) - set(before_contract['scopes']) == {AGENT + x for x in (
    'neuron_generation_initial.rs', 'neuron_generation_initial_root_custody.rs',
    'neuron_generation_initial_root_task.rs', 'neuron_generation_initial_root_cold.rs')}
for path in before_contract['scopes']:
    assert [x['selector'] for x in before_contract['scopes'][path]] == [x['selector'] for x in contract['scopes'][path]]
for key in ('root_source_map', 'protocol_items', 'decoy_functions'):
    assert before_contract[key] == contract[key]

old_qa = (R / 'before' / QA)
qa_files = sorted(old_qa.glob('*.py'))
assert len(qa_files) == 64
old_count = new_count = same = 0
changed_methods = []
added_methods = []
qa_identity = []
for path in qa_files:
    rel = path.relative_to(R / 'before').as_posix()
    before = path.read_text()
    after = (R / 'after' / rel).read_text() if (R / 'after' / rel).exists() else before
    bm, am = method_map(before), method_map(after)
    assert bm.keys() <= am.keys(), rel
    assert top_functions(before) == top_functions(after), rel
    old_count += len(bm)
    new_count += len(am)
    same += sum(bm[k] == am[k] for k in bm)
    changed_methods.extend({'path': rel, 'class': k[0], 'method': k[1], 'before': pin(bm[k].encode()),
                            'after': pin(am[k].encode())} for k in bm if bm[k] != am[k])
    added_methods.extend({'path': rel, 'class': k[0], 'method': k[1]} for k in am if k not in bm)
    assert pin(before.encode()) == base_pin(base_rows[rel])
    qa_identity.append({'path': rel, 'before': pin(before.encode()), 'after': pin(after.encode()),
                        'old_methods': len(bm), 'retained_byte_equal': sum(bm[k] == am[k] for k in bm),
                        'removed_methods': 0})
assert (old_count, new_count, same, len(changed_methods), len(added_methods)) == (604, 607, 602, 2, 3)

ordinary_path = QA + 'test_evaluated_published_read_source_closure.py'
ob = (R / 'before' / ordinary_path).read_text()
oa = (R / 'after' / ordinary_path).read_text()
for key in ('ORDINARY_NEW_BOUNDARIES', 'ORDINARY_SCOPE_GUARDS', 'ORDINARY_LITERAL_SPECS', 'ORDINARY_MODULE_MOUNTS'):
    assert assignment(ob, key) == assignment(oa, key), key
assert assignment(oa, 'ORDINARY_NEW_BOUNDARIES') == new['boundary'][541:569]
assert assignment(oa, 'ORDINARY_COMPLETE_BOUNDARY_SHA256') == digest
om = [(k, method_map(ob)[k], method_map(oa)[k]) for k in method_map(ob) if method_map(ob)[k] != method_map(oa)[k]]
assert len(om) == 1 and om[0][2].replace('self.assertEqual(len(boundaries), 633)', 'self.assertEqual(len(boundaries), 621)') == om[0][1]

provider_path = QA + 'test_resident_provider_local_read_source_closure.py'
pb = (R / 'before' / provider_path).read_text()
pa = (R / 'after' / provider_path).read_text()
assert all(method_map(pa)[k] == v for k, v in method_map(pb).items())
assert pa.count(hashlib.sha256(contract_raw).hexdigest()) == 1
provider_new = {k: v for k, v in method_map(pa).items() if k not in method_map(pb)}
new_groups = set(contract['attacks']) - set(before_contract['attacks'])
assert new_groups == {'root_custody_consumption', 'root_cold_original_recovery', 'root_task_same_cell'}
for group in new_groups:
    assert sum(('self.attack_group("' + group + '")') in body for body in provider_new.values()) == 1

root_path = QA + 'test_resident_root_source_closure.py'
rb = (R / 'before' / root_path).read_text()
ra = (R / 'after' / root_path).read_text()
assert assignment(rb, 'ROOT_CASES') == assignment(ra, 'ROOT_CASES')
assert assignment(rb, 'ROOT_ISSUER_CASES') == assignment(ra, 'ROOT_ISSUER_CASES')
root_cases = assignment(ra, 'ROOT_CUSTODY_CASES')
assert len(root_cases) == len(set(root_cases)) == 9
rm = [(k, method_map(rb)[k], method_map(ra)[k]) for k in method_map(rb) if method_map(rb)[k] != method_map(ra)[k]]
assert len(rm) == 1
root_after = rm[0][2]
start = root_after.index('        task_support = ')
end = root_after.index('        for marker in (', start)
reversed_root = root_after[:start] + root_after[end:]
reversed_root = reversed_root.replace('        self.assertTrue(set(ROOT_CUSTODY_CASES).issubset(parents))\n', '')
reversed_root = reversed_root.replace('7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES) + len(ROOT_CUSTODY_CASES)',
                                      '7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES)')
assert reversed_root == rm[0][1]
assert '#[path = "neuron_generation_initial_root_custody_support_tests.rs"]\nmod root_initial_custody;' in prepared_blobs[AGENT + 'circuit_q24_task_test_support.rs'].decode()
support = prepared_blobs[AGENT + 'neuron_generation_initial_root_custody_support_tests.rs'].decode()
assert '#[path = "neuron_generation_initial_root_custody_tests.rs"]\nmod tests;' in support
assert '#[path = "neuron_generation_initial_root_cold_tests.rs"]\nmod cold_tests;' in support
root_count = 0
for module, filename in (('tests', 'neuron_generation_initial_root_custody_tests.rs'),
                         ('cold_tests', 'neuron_generation_initial_root_cold_tests.rs')):
    source = prepared_blobs[AGENT + filename].decode()
    names = re.findall(r'(?m)^async fn (root_initial_\w+)\(', source)
    root_count += len(names)
    assert len(names) == source.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]')
    for name in names:
        assert 'runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::' + module + '::' + name in root_cases
assert root_count == 9

workflow_path = '.github/workflows/hepta-daemon-learning-native.yml'
wb = (R / 'before' / workflow_path).read_text()
wa = (R / 'after' / workflow_path).read_text()
pat = r'parents = (\[[\s\S]*?\n          \])'
mb, ma = re.search(pat, wb), re.search(pat, wa)
parents_b, parents_a = ast.literal_eval(mb.group(1)), ast.literal_eval(ma.group(1))
assert len(parents_b) == 39 and parents_a == parents_b + root_cases and len(set(parents_a)) == 48
assert wa[:ma.start(1)] + mb.group(1) + wa[ma.end(1):] == wb
prefix = mb.group(1)[:-len('          ]')]
assert ma.group(1).startswith(prefix)
native = (COORD / 'inputs/native-driver.original.py').read_bytes()
assert pin(native)['git_blob'] == 'b92ddded4fce78aeb076d022471c62bf81ce2e4f'
workflow_driver_marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
for workflow in (wb, wa):
    ast.parse(textwrap.dedent(workflow.split(workflow_driver_marker, 1)[1].split('          PY\n', 1)[0]))
allow_path = '.github/blob-size-allowlist.txt'
ab, aa = (R / 'before' / allow_path).read_bytes(), (R / 'after' / allow_path).read_bytes()
suffix = b'# Exact actual-format and original Root custody source guards; no wildcard.\nsha256:' + hashlib.sha256(new_raw).hexdigest().encode() + b' CALLERS.toml\n'
assert aa == ab + suffix

changes = []
patch = []
updated = copy.deepcopy(prepared)
for path in sorted((p for p in (R / 'after').rglob('*') if p.is_file()), key=lambda p: p.relative_to(R / 'after').as_posix().encode()):
    relative = path.relative_to(R / 'after').as_posix()
    before, after = (R / 'before' / relative).read_bytes(), path.read_bytes()
    assert before != after
    assert base_pin(base_rows[relative]) == pin(before)
    assert base_rows[relative]['index_mode'] == '100644'
    assert base_pin(prepared[relative]) == pin(before)
    save('before/' + relative, before)
    save('after/' + relative, after)
    changes.append({'path': relative, 'mode': '100644', 'before': pin(before), 'after': pin(after),
                    'before_base64': base64.b64encode(before).decode(), 'after_base64': base64.b64encode(after).decode()})
    patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                                    fromfile='a/' + relative, tofile='b/' + relative))
    updated[relative].update(bytes=len(after), sha256=pin(after)['sha256'], working_blob=pin(after)['git_blob'], matches_index=False)
assert len(changes) == 7
final_tree = merkle.merkle(list(updated.values()))
assert len(updated) == len(prepared) == 15243
source_changes = {row['path']: row['after'] for row in changes}
packet = {'format': 'hepta-source-registration-proposal-v1', 'status': 'PREPARATION_HOLD_NOT_QUALIFIED',
          'base_actual_complete_inventory': pin(inv_raw), 'base_actual_physical_tree': 'f905b18e6b05de1582024548179725a05d932536',
          'required_prepared_rust_layers': layers, 'expected_before_physical_tree': prepared_tree,
          'expected_after_physical_tree': final_tree, 'expected_after_leaf_count': len(updated),
          'source_changes': changes, 'canonical_source_deletions': [], 'qa_methods_executed': 0,
          'full_source_scans': 0, 'formatter_runs': 0, 'rust_compiles_or_tests': 0, 'H_calls': 0,
          'source_commit_or_ref_writes': 0,
          'qualification': False, 'real_authorized_task_chain_results': 0,
          'notes': 'Complete preimages match actual formatted f905. This layer registers immutable coordinator preparation, refreshed actual-format code spans and unchanged old attack intent. The original full collector, QA, source gates and Rust/Root cases have not run on this candidate.'}
packet_info = save('SOURCE_PACKET.json', packet)
patch_info = save('SOURCE_DELTA.patch', ''.join(patch))
save('FINAL_SOURCE_MAP.json', source_changes)
save('QA_METHOD_PRESERVATION.json', {'format': 'hepta-static-qa-method-preservation-v1',
    'files': qa_identity, 'old_total': old_count, 'after_total': new_count, 'old_byte_equal': same,
    'old_method_changes': changed_methods, 'new_methods': added_methods, 'removed_methods': [],
    'all_top_level_helper_functions_byte_equal': True, 'qa_or_gate_executed': False})
save('FORMATTED_GUARD_REFRESH_SUMMARY.json', {'old_protected_count': 437, 'new_protected_count': 442,
    'changed_old_rows': changed_old, 'changes': marker_summary, 'all_old_forbidden_equal': True,
    'old_row411_byte_schema_equal': True, 'all_old_top_level_and_literal_call_requirements_equal': True,
    'full_author_span_record': pin((R / 'FORMATTED_GUARD_REFRESH.draft.json').read_bytes())})

scope_inputs = []
for path in sorted((R / 'view').rglob('*.rs')):
    relative = path.relative_to(R / 'view').as_posix()
    raw = path.read_bytes()
    assert pin(raw) == base_pin(prepared[relative])
    scope_inputs.append({'path': relative, **pin(raw),
                         'origin': 'prepared Rust layer' if relative in prepared_blobs else 'complete actual f905 inventory identity'})
save('PARTIAL_SOURCE_INPUTS.json', {'format': 'hepta-static-partial-view-inputs-v1', 'full_source_scan': False,
    'rows': scope_inputs, 'view_rust_files': len(scope_inputs),
    'complete_actual_inventory': pin(inv_raw), 'prepared_layers': layers,
    'additional_original_source_readback': json.loads((R / 'ADDITIONAL_SCOPE_INPUTS.json').read_bytes())})
for name in ('COORDINATOR_BOUNDARIES.draft.json', 'REGISTRATION_CONSTRUCTION_REVIEW.draft.json',
             'PROVIDER_SCOPE_REFRESH.draft.json', 'QA_WORKFLOW_CONSTRUCTION_REVIEW.draft.json'):
    save(name.replace('.draft', ''), (R / name).read_bytes())
for name in ('build_registration.py', 'build_qa_workflow.py', 'refresh_formatted_guards.py',
             'inspect_coordinator_edges.py', 'freeze_registration.py'):
    save('authoring/' + name, (R / name).read_bytes())

summary = {'format': 'hepta-coordinator-actual-format-registration-author-review-v1',
    'status': 'FROZEN_PREPARATION_ONLY_INDEPENDENT_REVIEW_REQUIRED', 'source_packet': packet_info,
    'source_patch': patch_info, 'source_paths': [r['path'] for r in changes],
    'base_actual_physical_tree': packet['base_actual_physical_tree'], 'expected_prepared_before_tree': prepared_tree,
    'expected_after_tree': final_tree, 'expected_leaves': len(updated), 'canonical_source_deletions': [],
    'original_boundaries_preserved': 621, 'new_boundaries': 12, 'final_boundaries': 633,
    'new_methods_non_test_callers': [], 'main_or_root_startup_integration_completed': False,
    'original_protected_rows': 437, 'new_rows': 5, 'final_protected_rows': 442,
    'formatted_old_rows': 23, 'formatted_marker_values': 80, 'original_forbidden_preserved': True,
    'row411_preserved': True, 'source_roots_ignore_and_authority_preserved': True,
    'original_ordinary_boundary_slice': '[541:569]', 'provider_boundary_slice': '[569:]',
    'ordinary_scope_digest_changes': 0, 'provider_scope_digest_changes': 39,
    'original_attack_specs': 83, 'new_attack_specs': 24, 'original_ordinary_literal_specs': 17,
    'original_qa_files': 64, 'original_methods': 604, 'old_methods_byte_equal': 602,
    'old_methods_with_explicit_registration_changes': 2, 'new_methods': 3, 'removed_methods': 0,
    'root_workflow_old_parents': 39, 'root_workflow_appended': 9, 'root_workflow_expected_parents': 48,
    'original_root_budget_seconds': 7200, 'original_root_threads': 1, 'run_ignored': 'only', 'retries': 0,
    'native_phase_count_or_driver_or_filter_semantics_changed': False,
    'original_native_driver': pin(native), 'qa_or_full_collector_or_rust_or_native_executed': False,
    'prior_fix101_remains_failed': True, 'new_lint_or_qualification_success': False,
    'lifecycle_limits': ['RootSession timeout/outer cancellation leaves worker terminal state Unknown; no join guarantee is supplied.',
        'Cold mechanism cases reopen the same protected Current/journal in one process; no Root process cold restart was observed.',
        'Twelve new public methods still have no non-test caller. Root host/startup production wiring is a separate open implementation boundary.'],
    'independent_prior_evidence': {
        'fmt62_semantic_peer': '976863ddbbca0ee4558e7846eddcb458114590cb',
        'coordinator_rebase_peer': 'f7766b77fe1a7df5a0cc0b63b5a01d9b88e9d85a',
        'metadata_name_peer': '8846963f793638f9b00e629de9b42966ec20fef3',
        'old_qa_marker_peer': 'abade3fd99defe3139c34b334167c36d4b57a370'}}
review_info = save('REVIEW.json', summary)

bundles = []
for name, raw in (('SOURCE_PACKET', (F / 'SOURCE_PACKET.json').read_bytes()),
                  ('FORMATTED_GUARD_REFRESH', (R / 'FORMATTED_GUARD_REFRESH.draft.json').read_bytes())):
    zipped = gzip.compress(raw, compresslevel=9, mtime=0)
    gz_info = save(name + '.json.gz', zipped)
    parts = []
    for number, offset in enumerate(range(0, len(zipped), 307200), 1):
        segment = zipped[offset:offset + 307200]
        encoded = base64.b64encode(segment)
        assert len(encoded) <= 512000
        part_info = save(name + f'.json.gz.part-{number:03d}.b64', encoded)
        parts.append({**part_info, 'offset': offset, 'decoded': pin(segment)})
    decoded = b''.join(base64.b64decode(Path(part['path']).read_bytes(), validate=True) for part in parts)
    assert decoded == zipped and gzip.decompress(decoded) == raw
    bundles.append({'name': name, 'raw': pin(raw), 'gzip': gz_info, 'parts': parts,
                    'encoding': 'base64 of contiguous gzip byte chunks; concatenate decoded chunks, then gzip-decompress; complete exact raw bytes'})

readme = '''# Coordinator registration on actual formatted source

This is an unexecuted source-registration proposal. Its seven complete preimages match the observed f905 source inventory. Apply the independently frozen coordinator rebase (773d6712) and metadata getter naming layer (5279a43b) before this registration layer. The old layers are immutable.

The proposal retains all 621 old boundary rows, every old forbidden array, row 411's unique-function requirements, the original source roots and ignore rules, and all authority=false fields. It appends 12 coordinator boundaries whose non-test caller sets are empty. That accurately records a deployment gap: these new APIs have not been wired into ordinary Root startup or recovery.

Actual formatter bytes require 80 exact code-span replacements across 23 existing protected rows. Original top-level/literal-call guards remain unchanged. Five additional protected rows cover the original initial factory plus the three coordinator modules and five individually Linux-guarded exports. The resulting inventory contains 633 boundaries and 442 protected rows.

The 64 original QA files contain 604 test methods. 602 method bodies are byte-identical; two retain every old assertion while extending the exact boundary or Root-parent inventory. Three new methods invoke 24 exact deletion attacks. All 83 old provider attack specs, 17 ordinary literal specs, and the original [541:569] boundary slice remain unchanged. Every provider scope is still traversed by the original default QA method; 39 existing scope digests change only with the actual formatter bytes.

The original 39 workflow parent strings remain in their original order and bytes. Nine ignored Root mechanism FQNs are appended, for a candidate list of 48. The original native driver reads that list through its existing AST extraction and exact Root JUnit comparison. The original 14 phases, filters, 7200-second Root budget, one test thread, ignored-only mode and zero retries are unchanged. The ordinary observer-coverage module has no Root parent registry and is unchanged. Ordinary --lib skipping ignored tests is not a pass for these cases.

No QA method, full source collector, Rust compilation, formatter, test or native job ran during this preparation. The earlier single scoped fix returned 101 and remains failed. A new source snapshot needs its own reviewed maintenance and original gates. Real authorized A/B/C task-chain results remain zero.

RootSession's five-second finish timeout or outer cancellation does not prove that its worker joined. The cold cases exercise same-process reopening of existing protected Current/journal state, not a Root-process cold restart. The registered helpers and mechanisms do not supply missing real owners, grants, independent B results or a successful C daemon.

SOURCE_PACKET.json includes all seven complete before/after images. The bounded base64 gzip parts reconstruct it byte-for-byte and are the evidence transport for the large CALLERS data; raw computed identities are not described as independent native reads. The frozen authoring scripts and preservation records document byte/AST/schema/lexical inspection only. No source commit or ref is created by this package.
'''
readme_info = save('README.md', readme)
manifest = {'format': 'hepta-bounded-registration-proposal-manifest-v1', 'status': 'HOLD_NOT_QUALIFIED',
    'packet': packet_info, 'patch': patch_info, 'review': review_info, 'readme': readme_info,
    'source_paths': [{k: row[k] for k in ('path', 'mode', 'before', 'after')} for row in changes],
    'required_rust_layers': layers, 'expected_before_tree': prepared_tree, 'expected_after_tree': final_tree,
    'expected_leaf_count': len(updated), 'canonical_source_deletions': [], 'bundles': bundles,
    'evidence_leaf_limit': 512000, 'source_or_ref_writes': False, 'native_or_test_calls': 0}
manifest_info = save('MANIFEST.json', manifest)

index = []
for path in sorted(F.rglob('*')):
    if not path.is_file() or path.name == 'ARCHIVE_INPUT_INDEX.json':
        continue
    relative = path.relative_to(F).as_posix()
    raw = path.read_bytes()
    # Large exact raw blobs are represented by complete bounded gzip parts in
    # evidence. Source after blobs are still eligible for object creation.
    place = len(raw) <= 512000 and not relative.startswith('before/') and not relative.endswith('.gz')
    upload = place or relative.startswith('after/')
    if relative.startswith('before/'):
        upload = False
    index.append({'name': relative, 'path': str(path), **pin(raw),
                  'chars': len(raw.decode()) if upload else None,
                  'upload_blob': upload, 'place_in_evidence': place,
                  'evidence_path': 'coordinator-f905-registration-v1/' + relative if place else None})
save('ARCHIVE_INPUT_INDEX.json', {'format': 'hepta-registration-archive-input-index-v1', 'entries': index})
print(json.dumps({'manifest': manifest_info, 'packet': packet_info, 'review': review_info,
                  'paths': len(changes), 'before_tree': prepared_tree, 'after_tree': final_tree,
                  'leaves': len(updated), 'bundles': [{k: v for k, v in x.items() if k != 'parts'} | {'part_count': len(x['parts'])} for x in bundles]}, indent=2))
