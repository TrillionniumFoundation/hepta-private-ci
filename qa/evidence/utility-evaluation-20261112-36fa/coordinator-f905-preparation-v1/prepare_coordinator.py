#!/usr/bin/env python3
"""Rebase immutable coordinator bytes onto observed f905, without executing Rust."""
import ast
import base64
import copy
import difflib
import hashlib
import importlib.util
import json
import re
import textwrap
from pathlib import Path

R = Path(__file__).resolve().parent
RECOVERY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1')
COMPOSED = Path('/tmp/hepta-36fa-root-generation-custody-composed-v2')
OLDPROD = Path('/tmp/hepta-36fa-root-generation-custody-coordinator-v1/PRODUCTION_PACKET.json')
TESTS = Path('/tmp/hepta-36fa-root-generation-custody-tests-v1/SOURCE_PACKET.json')
COLD = Path('/tmp/hepta-36fa-root-generation-custody-cold-v2/SOURCE_PACKET.json')
BASE_OVERLAY = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1/overlay')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def write(path, raw):
    p = R / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        assert p.read_bytes() == raw, str(p)
    else:
        with p.open('xb') as f: f.write(raw)
    return {'path': str(p), **pin(raw)}

def save(path, value):
    return write(path, (json.dumps(value, indent=2, sort_keys=True) + '\n').encode())

def packet_rows(path):
    value = json.loads(path.read_bytes())
    return value.get('source_changes', value.get('changes'))

def full_contents(row, side):
    if row[side] is None: return None
    if side + '_base64' in row: raw = base64.b64decode(row[side + '_base64'], validate=True)
    elif side + '_text' in row: raw = row[side + '_text'].encode()
    else: raise AssertionError((row['path'],side))
    assert pin(raw) == row[side]
    return raw

inventory_raw = (RECOVERY / 'final.inventory.exact_recovered.json').read_bytes()
assert pin(inventory_raw) == {'bytes': 5634549, 'sha256': 'bc6b9d59143004236665bb9446e2c45d1ac77cd7aaba14ba7cee8f4ea76d003f', 'git_blob': 'e1e48f35bb6cf5a3dd86c59472da77df87154b6a'}
inventory = json.loads(inventory_raw)
base_rows = {row['path']: row for row in inventory['files']}
baseline = {}
layer_after = {}
layer_pins = []
for path in (OLDPROD, TESTS, COLD):
    layer_pins.append({'path': str(path), **pin(path.read_bytes())})
    for row in packet_rows(path):
        before, after = full_contents(row, 'before'), full_contents(row, 'after')
        if row['path'] in layer_after:
            assert layer_after[row['path']] == before
        else:
            baseline[row['path']] = before
        layer_after[row['path']] = after
assert len(layer_after) == 9 and sum(x is None for x in baseline.values()) == 6
oldmap = json.loads((COMPOSED / 'FINAL_SOURCE_MAP.json').read_text())
for path, after in layer_after.items():
    assert pin(after)['git_blob'] == oldmap[path]
    assert after == (COMPOSED / 'after' / path).read_bytes()

changes = []
rebase = []
patch = []
after_rows = copy.deepcopy(base_rows)
for path in sorted(layer_after):
    old_before, old_after = baseline[path], layer_after[path]
    if old_before is None:
        assert path not in base_rows
        before, after = None, old_after
        classification = 'new path, absent from complete actual f905 inventory'
    else:
        row = base_rows[path]
        native_after = RECOVERY / 'actual-after' / path
        before = native_after.read_bytes() if native_after.exists() else old_before
        assert pin(before) == {'bytes':row['bytes'], 'sha256':row['sha256'], 'git_blob':row['working_blob']}
        if before == old_before:
            after = old_after
            classification = 'existing actual bytes unchanged by formatter; frozen delta reused exactly'
        else:
            assert path == 'codex-rs/hepta-agentd/src/lib.rs'
            anchor = b'#[cfg(unix)]\npub use neuron_generation_initial::PreparedAgentdGenerationInitialV1;'
            assert old_before.count(anchor) == old_after.count(anchor) == before.count(anchor) == 1
            block = b''.join(b'#[cfg(target_os = "linux")]\npub use neuron_generation_initial::' + name.encode() + b';\n' for name in (
                'OriginalRootCircuitTaskCustodyV1','OriginalRootCircuitTaskInputsV1','OriginalRootCircuitTaskRuntimeV1',
                'OriginalRootInitialGenerationCustodyV1','OriginalRootInitialInstallationErrorV1'))
            assert old_before.replace(anchor,block+anchor,1) == old_after
            assert block not in before
            after = before.replace(anchor,block+anchor,1)
            assert after.replace(block,b'',1) == before
            classification = 'exact original five individually Linux-guarded exports inserted into actual formatted lib; every other byte preserved'
        write('before/' + path, before)
    write('after/' + path, after)
    changes.append({'path':path, 'mode':'100644', 'before':pin(before) if before is not None else None, 'after':pin(after),
                    'before_base64':base64.b64encode(before).decode() if before is not None else None,
                    'after_base64':base64.b64encode(after).decode()})
    rebase.append({'path':path, 'classification':classification, 'old_frozen_before':pin(old_before) if old_before is not None else None,
                   'actual_f905_before':pin(before) if before is not None else None, 'old_frozen_after':pin(old_after),
                   'candidate_after':pin(after), 'candidate_after_equal_frozen_after':after == old_after})
    patch.extend(difflib.unified_diff((before or b'').decode().splitlines(True),after.decode().splitlines(True),
                                    fromfile='a/'+path if before is not None else '/dev/null',tofile='b/'+path))
    existing = copy.deepcopy(base_rows.get(path, {'path':path,'index_mode':'100644','index_blob':None,'kind':'file','permissions':420,'stable':True}))
    existing.update(bytes=len(after),sha256=pin(after)['sha256'],working_blob=pin(after)['git_blob'],matches_index=False)
    after_rows[path] = existing

# Import only this pure, already archived hash implementation, never its main.
spec = importlib.util.spec_from_file_location('exact_merkle_only', RECOVERY/'recover_inventory.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
assert m.merkle(inventory['files']) == 'f905b18e6b05de1582024548179725a05d932536'
expected_tree = m.merkle(list(after_rows.values()))
packet = {'format':'hepta-reviewed-rust-source-proposal-v1', 'status':'HOLD_UNEXECUTED_COORDINATOR_ON_ACTUAL_FORMATTED_SOURCE',
          'qualification':False,'H_calls':0,'format_compile_test_calls':0,'source_or_ref_writes':False,
          'base_source_identity':inventory['source'], 'base_complete_inventory':pin(inventory_raw),
          'base_actual_physical_tree':'f905b18e6b05de1582024548179725a05d932536', 'base_leaf_count':15237,
          'expected_after_physical_tree':expected_tree,'expected_after_leaf_count':len(after_rows),
          'canonical_source_deletions':[], 'immutable_input_layers':layer_pins, 'source_changes':changes}
packet_pin = save('SOURCE_PACKET.json',packet)
patch_pin = write('SOURCE_DELTA.patch',''.join(patch).encode())
save('FINAL_SOURCE_MAP.json',{row['path']:row['after'] for row in changes})
save('REBASE_REVIEW.json',{'format':'hepta-coordinator-f905-exact-rebase-review-v1','actual_base':pin(inventory_raw),
     'actual_physical_tree':packet['base_actual_physical_tree'],'changed_existing_preimages':1,'unchanged_existing_preimages':2,
     'new_paths':6,'total_paths':9,'rows':rebase,'full_before_and_after_bytes_verified':True,
     'old_layers_unchanged':True,'no_fmt_compile_tests_or_H':True,'candidate_only':True,
     'expected_after_tree':expected_tree,'expected_after_leaves':len(after_rows)})

workflow_path='.github/workflows/hepta-daemon-learning-native.yml'
workflow=(BASE_OVERLAY/workflow_path).read_bytes()
row=base_rows[workflow_path]
assert pin(workflow)=={'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']}
marker='          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
original_driver=textwrap.dedent(workflow.decode().split(marker,1)[1].split('          PY\n',1)[0])
constants={}
for node in ast.parse(original_driver).body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and getattr(node.targets[0],'id',None) in ('parents','packages'):
        constants[node.targets[0].id]=ast.literal_eval(node.value)
assert len(constants['parents'])==39 and len(set(constants['parents']))==39
native=(R/'inputs/native-driver.original.py').read_bytes()
assert pin(native)['git_blob']=='b92ddded4fce78aeb076d022471c62bf81ce2e4f'
focused=['cell_q24_dataset::tests::','circuit_experience_intake::tests::','original_execution_owner_',
         'neuron_cell_evaluation::tests::learning::','holdout_current_completed_execution_readback_requires_physical_original',
         'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::',
         'runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::']
root_prefix='runtime::tests::circuit_task_ingress::q24_tests::support::root_initial_custody::'
cases=[]
for module,filename,count in [('tests','neuron_generation_initial_root_custody_tests.rs',5),('cold_tests','neuron_generation_initial_root_cold_tests.rs',4)]:
    path='codex-rs/hepta-agentd/src/'+filename
    body=layer_after[path].decode()
    names=re.findall(r'(?m)^async fn (root_initial_\w+)\(',body)
    assert len(names)==count and body.count('#[ignore')==count and body.count('#[tokio::test')==count
    for name in names:
        fqn=root_prefix+module+'::'+name
        assert fqn not in constants['parents']
        cases.append({'fqn':fqn,'source_path':path,'source_blob':pin(layer_after[path])['git_blob'],
                      'ignored':True,'current_workflow_root_selected':False,
                      'focused_filter_matches':[value for value in focused if value in fqn],
                      'ordinary_lib':'compiled if included, ignored execution skipped; not a PASS observation',
                      'proposed_root_phase':'root', 'proposed_root_exact_filter':'test(='+fqn+')',
                      'proposed_root_timeout_seconds':7200,'proposed_root_test_threads':1,'executed':False})
assert len(cases)==9 and not any(row['focused_filter_matches'] for row in cases)
save('ROOT_PHASE_COVERAGE_PREPARATION.json',{'format':'hepta-static-original-native-phase-coverage-v1','status':'PREPARATION_ONLY_NOT_SELECTION_OR_EXECUTION',
     'native_driver':pin(native),'workflow_before':{'path':workflow_path,**pin(workflow)},'original_parents':constants['parents'],
     'original_parent_count':39,'proposed_append':[row['fqn'] for row in cases],'proposed_parent_count':48,
     'packages_preserved':constants['packages'],'focused_filters_preserved':focused,'cases':cases,
     'mechanism':'Original b92 AST reads final workflow parents and constructs --run-ignored only -E exact test(=FQN) disjunction; successful retained Root JUnit must equal exactly that final list.',
     'root_budget_seconds':7200,'root_test_threads':1,'retries':0,'driver_and_phase_count_changes':False,
     'ordinary_ignored_cases_are_not_counted_as_passed':True,
     'workflow_and_coverage_registration_pending_separate_source_layer':True,
     'limits':'No formatter, compiler, test, QA method, source gate or native main is executed. Tests are mechanism fixtures, not a real authorized A/B/C task chain. RootSession.finish reports timeout/outer cancellation as unknown; losing JoinHandle does not prove worker termination. Cold tests reopen existing Current/journal in one process and do not claim a process cold restart.'})
print(json.dumps({'packet':packet_pin,'patch':patch_pin,'paths':len(changes),'expected_tree':expected_tree,'expected_leaves':len(after_rows),'root_candidates':len(cases)},sort_keys=True))
