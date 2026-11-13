"""Offline AST/byte audit only. Never import or execute any reviewed control."""
import ast
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).parent
HOLD = Path('/tmp/hepta-36fa-native-after-cc57-source-hold-v1')
OLD = Path('/tmp/hepta-36fa-final-native-qualification-launch-hold-v1')
SOURCE = Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v2')
INPUTS = SOURCE / 'inputs'
CC57 = 'cc57c7198db6293ccca562253c42fffbe2a04633'
B7 = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
PARENT = '246d8cb614770252ee42029a5c014f2a4904176a'
BASE = '/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2'
JOB = '1a1d23c92f3-2564-1cb4'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(path):
    raw = path.read_bytes()
    return raw, {'path': str(path), **pin(raw)}


def assignments(text):
    return {node.targets[0].id: node for node in ast.parse(text).body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)}


def section(text, node):
    return ''.join(text.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


old_raw, old_pin = read(OLD / 'BOOTSTRAP_TEMPLATE.HOLD.py')
raw, template_pin = read(HOLD / 'BOOTSTRAP_TEMPLATE.HOLD.py')
assert old_pin['git_blob'] == 'e857c626029f201df16f758b165aa95a00d7d965'
assert template_pin['git_blob'] == 'fcd164e362993c49affd4893e4108e06100b4726'
old, new = old_raw.decode(), raw.decode()
oa, na = assignments(old), assignments(new)
names = ('BASE', 'PINS', 'SOURCE_SUCCESS')
rebuilt = new.splitlines(keepends=True)
for name in sorted(names, key=lambda key: na[key].lineno, reverse=True):
    rebuilt[na[name].lineno - 1:na[name].end_lineno] = [section(old, oa[name])]
assert ''.join(rebuilt).encode() == old_raw
old_ast, new_ast = ast.parse(old), ast.parse(new)
for tree in (old_ast, new_ast):
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], 'id', None) in names:
            node.value = ast.Constant(value='PIN_ONLY_REVIEW_PLACEHOLDER')
assert ast.dump(old_ast, include_attributes=False) == ast.dump(new_ast, include_attributes=False)
functions = {}
for node in ast.parse(new).body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        previous = next(x for x in ast.parse(old).body if isinstance(x, ast.FunctionDef) and x.name == node.name)
        assert section(new, node) == section(old, previous)
        functions[node.name] = {'exact_bytes_unchanged': True, 'AST_unchanged': ast.dump(node) == ast.dump(previous)}
assert len(functions) == 5
source_raw, source_bootstrap_pin = read(SOURCE / 'SOURCE_BOOTSTRAP.candidate.py')
pins = ast.literal_eval(na['PINS'].value)
assert pins == ast.literal_eval(assignments(source_raw.decode())['PINS'].value)
assert ast.literal_eval(na['BASE'].value.args[0]) == BASE
success = {ast.literal_eval(k): v for k, v in zip(na['SOURCE_SUCCESS'].value.keys, na['SOURCE_SUCCESS'].value.values)}
assert ast.literal_eval(success['job_id']) == JOB
assert all(ast.literal_eval(success[key]) is None for key in ('result', 'original_run_result', 'supervisor'))
input_rows = []
for name, expected in pins.items():
    input_raw, actual = read(INPUTS / name)
    assert pin(input_raw) == expected
    input_rows.append(actual)
assert len(input_rows) == 8
request_raw, request_pin = read(HOLD / 'REQUEST.HOLD.json')
request = json.loads(request_raw)
assert set(request) == {'host', 'executable', 'args', 'cwd', 'stdin', 'idempotency_key', 'timeout_seconds'}
assert request['host'] == 'desktop' and request['executable'] == '/usr/bin/python3'
assert request['args'] == ['-B', '-c', new] and request['cwd'] == '/home/qian-qi'
assert request['timeout_seconds'] == 45000
assert request['idempotency_key'] == 'hepta-utility-36fa-final-native-gates-cc57-v1'
assert json.loads(request['stdin']) == {'format': 'hepta-final-native-after-source-bootstrap-v1', 'source_supervisor_base64': None}
assert json.loads((OLD / 'PLAN.HOLD.json').read_bytes())['expected_outer_seconds'] == request['timeout_seconds']

cfg = json.loads((INPUTS / 'APPROVED_QUALIFICATION_INPUT.json').read_bytes())
scfg = json.loads((INPUTS / 'APPROVED_SOURCE_GATES_CONFIG.json').read_bytes())
assert (cfg['source'], cfg['tree'], cfg['parents']) == (CC57, B7, [PARENT])
assert (scfg['source_sha'], scfg['source_tree']) == (CC57, B7)
for key, filename in [('admission_path', 'qualification-admission.py'), ('native_driver_path', 'native-driver.original.py'), ('plan_path', 'PLAN.original.json'), ('source_gates_config_path', 'APPROVED_SOURCE_GATES_CONFIG.json')]:
    assert cfg[key] == BASE + '/' + filename
assert cfg['source_gates_handoff_records'] == BASE + '/source-handoff'
assert cfg['records'] == BASE + '/native-records' and scfg['records'] == BASE + '/source-gates-records'
assert scfg['source_checkout'] == '/home/qian-qi/hepta-utility-36fa-source-gates-cc57-v2'
assert cfg['repo'] == scfg['object_repository'] == '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
assert Path(cfg['root_parent']).parent == Path('/run')
assert cfg['root_parent'] == '/run/hepta-utility-36fa-final-cc57-v2'
assert cfg['runtime_guard']['inherited_source_environment'] == {'CODEX_REPO_ROOT': None, 'PYTHONPATH': None}
assert cfg['runtime_guard']['minimum_target_free_bytes'] == 32 * 1024 ** 3
assert cfg['runtime_guard']['create_target_if_absent'] is False
assert scfg['budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}
actual_admission_raw, actual_admission_pin = read(Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2/ACTUAL_ADMISSION_READBACK.json'))
actual_admission = json.loads(actual_admission_raw)
assert actual_admission['job_id'] == JOB and actual_admission['all_returned_original_request_fields_exact'] is True
assert actual_admission['actual_launch_state'] == 'launched' and actual_admission['reused'] is False
source_request_raw, source_request_pin = read(SOURCE / 'SOURCE_PROCESS_INPUT.candidate.json')
source_request = json.loads(source_request_raw)
assert source_request_pin['git_blob'] == actual_admission['request_git_blob']
assert source_request['args'] == ['-B', '-c', source_raw.decode()]
assert source_request['timeout_seconds'] == 7200
assert set(source_request) == set(request)

fmt_raw, fmt_pin = read(Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/RESULT.original.json'))
alignment_raw, alignment_pin = read(Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/RESULT.json'))
assert pin(fmt_raw) == cfg['final_format']['result']
assert pin(alignment_raw) == cfg['canonical_alignment']['result']
fmt, aligned = json.loads(fmt_raw), json.loads(alignment_raw)
assert (fmt['source_commit'], fmt['source_tree'], fmt['parents']) == (PARENT, 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087', ['9c4a11f61d30e9cc352bf44d56c98909d202a55d'])
assert (aligned['after']['commit'], aligned['after']['tree'], aligned['after']['parents']) == (CC57, B7, [PARENT])
assert all(aligned['after']['inventory'][k] == v for k, v in cfg['full_physical_inventory'].items())
assert aligned['final_format']['job_id'] == cfg['final_format']['job_id']
assert aligned['final_format']['result'] == cfg['final_format']['result']
assert aligned['final_format']['supervisor'] == cfg['final_format']['supervisor']
for key, actual_path in [('final_format', Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/STATUS_01.original.json')), ('canonical_alignment', INPUTS / 'CANONICAL_ALIGNMENT_NORMAL.original.json')]:
    normal = actual_path.read_bytes()
    assert pin(normal) == cfg[key]['supervisor']
    outer = json.loads(normal)
    terminal = json.loads(outer['content'][0]['text'])
    assert outer['isError'] is False and terminal['job_id'] == cfg[key]['job_id']
    assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0

inventory_raw, inventory_pin = read(Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json'))
assert all(cfg['full_physical_inventory'][k] == v for k, v in pin(inventory_raw).items())
inventory = json.loads(inventory_raw)
assert inventory['source'] == {'head': CC57, 'tree': B7, 'status': ''}
assert inventory['tracked_entries'] == inventory['filesystem_entries'] == cfg['expected_file_count'] == 15188
by_path = {r['path']: r for r in inventory['files']}
plan = json.loads((INPUTS / 'PLAN.original.json').read_bytes())
source_controls = []
for expected in plan['unchanged_original_controls']['reviewed_source_pins']['files']:
    actual = by_path[expected['path']]
    assert actual['bytes'] == expected['bytes'] and actual['sha256'] == expected['sha256']
    assert actual['working_blob'] == actual['index_blob'] == expected['git_blob']
    source_controls.append(expected)
compact = Path('/tmp/hepta-36fa-native-compact-projection-cc57-v1/NATIVE_COMPACT_INVENTORY.projected.json').read_bytes()
assert hashlib.sha256(compact).hexdigest() == cfg['expected_inventory_sha256']
assert len(json.loads(compact)) == 15188
assert len(plan['phases']) == 14
workflow = Path('/tmp/hepta-36fa-final-qualification-peer-review-v1/workflow.original.txt').read_bytes()
expected_workflow = next(r for r in source_controls if r['path'] == '.github/workflows/hepta-daemon-learning-native.yml')
assert pin(workflow) == {k: expected_workflow[k] for k in ('bytes', 'sha256', 'git_blob')}
import textwrap
marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
workflow_driver = textwrap.dedent(workflow.decode().split(marker, 1)[1].split('          PY\n', 1)[0])
constants = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(workflow_driver).body
             if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], 'id', None) in ('parents', 'packages')}
assert len(constants['parents']) == len(set(constants['parents'])) == 33
assert constants['parents'] == next(r for r in plan['phases'] if r['id'] == 'root')['prepared_parent_names']
assert constants['packages'] == ['-p', 'codex-hepta-agentd', '-p', 'codex-hepta-learning-ledger', '-p', 'codex-hepta-learning-artifacts', '-p', 'codex-hepta-intelligence-eval', '-p', 'codex-hepta-neuron']
for filename, repo_path in [('justfile.original.txt', 'justfile'), ('nextest_script.original.txt', 'scripts/run-nextest.py'), ('nextest_config.original.txt', 'codex-rs/.config/nextest.toml')]:
    actual_raw = (Path('/tmp/hepta-36fa-final-qualification-peer-review-v1') / filename).read_bytes()
    expected = next(r for r in source_controls if r['path'] == repo_path)
    assert pin(actual_raw) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}

forbidden_old = ('final-qualification-246d-v1', 'final-qualification-cc57-v1', '1a1d1e83bd4-2564-1c86', '5208cfa83a1f279c7fb76c4536adfa41c1df5f6f')
assert all(value not in new for value in forbidden_old)
top = ast.parse(new).body
assert isinstance(top[-1], ast.Expr) and isinstance(top[-1].value, ast.Call) and isinstance(top[-1].value.func, ast.Name) and top[-1].value.func.id == 'exec'
assert all(not isinstance(node, ast.Try) for node in top[top.index(next(x for x in top if isinstance(x, ast.Try))) + 1:])
assert section(new, top[-1]) == section(old, ast.parse(old).body[-1])

report = {
    'format': 'hepta-cc57-native-after-source-independent-static-review-v1',
    'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
    'conclusion': 'NO_CONCRETE_BLOCKER_TO_CONTINUE_HOLD_PREPARATION; NOT_READY_TO_EXECUTE',
    'qualification': False, 'H_calls': 0, 'reviewed_control_main_executions': 0,
    'tests_or_gate_runs': 0, 'source_writes': 0, 'ref_updates': 0,
    'template': template_pin, 'original_template': old_pin, 'request': request_pin,
    'actual_source_bootstrap': source_bootstrap_pin, 'actual_source_request': source_request_pin,
    'actual_source_admission_readback': actual_admission_pin,
    'comparison': {'inverse_three_assignment_spans_restore_entire_original_bytes': True,
        'normalized_AST_identical': True, 'top_level_functions': functions,
        'exact_unchanged_native_exec_outside_staging_try': True,
        'pins_equal_current_source_v2_bootstrap_and_all_eight_actual_input_bytes': True,
        'old_task_path_or_job_occurrences_in_new_template': [],
        'changed_pin_names': sorted(k for k in pins if pins[k] != ast.literal_eval(oa['PINS'].value)[k])},
    'current_subject': {'source': CC57, 'tree': B7, 'parents': [PARENT], 'source_job_id': JOB,
        'source_base': BASE, 'native_records': cfg['records'], 'root_parent': cfg['root_parent'],
        'source_run_identity': scfg['run_identity'], 'native_run_identity': cfg['run_identity'],
        'native_idempotency_key': request['idempotency_key'],
        'key_note': 'The first native request for cc57 is named v1 while it consumes the cc57 source/control v2. This opaque fresh key is not a records path or source identity; no native dispatch is claimed by this static review.'},
    'eight_exact_inputs': input_rows,
    'actual_historical_anchor_proofs': {'final_format': fmt_pin, 'canonical_alignment': alignment_pin,
        'final_format_subject': {'head': fmt['source_commit'], 'tree': fmt['source_tree'], 'parents': fmt['parents']},
        'canonical_subject': {'head': aligned['after']['commit'], 'tree': aligned['after']['tree'], 'parents': aligned['after']['parents']},
        'clean_inventory': inventory_pin,
        'compact_inventory': pin(compact), 'complete_source_control_pins_equal_current_inventory': source_controls,
        'runtime_seed_note': 'The runtime-restoration proof correctly remains tied to its original 86dd/383ab SEED. Admission changes m.HEAD/m.TREE to current cc57/B7 before actual Git checks; it does not rewrite that historical restoration proof.'},
    'source_success_guard_chain': [
        'Bootstrap checks all three success pins are dicts before any read or staging; they are currently null. Null supervisor payload also remains unfilled.',
        'The exact pinned original supervisor must be for job 1cb4 and normal succeeded/exit0, no timeout/cancellation/retry, complete and durable output, terminal publication confirmed and no truncation.',
        'The pinned source-handoff RESULT must be passed for cfg cc57/B7, driver_main_entered true, driver_returncode zero and original_run_status passed; the pinned original run-result must independently say passed.',
        'Pinned 8607 grants passed only when original 5118 status is passed and its return value is zero; contradictory or incomplete terminal evidence is not converted to passed.',
        'Pinned 5118 grants overall passed only for all three gate summaries passed. Each requires original normal result, full before/after inventory equality to the frozen clone baseline, no execution or after-inventory errors, an original record, and completed retention. Source mismatch is Failed; incomplete evidence is Unknown.',
        '8607 finally calls a8be.finish: exact raw Git state and every original full inventory row must be unchanged. Any failure downgrades passed. Additional physical files are explicitly reported instead of being silently equated to original full bytes.',
        'After source proof sealing, de3e9 again admits the actual clean canonical origin and exact full 13d3 inventory before native work. Thus unexpected additional origin files cannot be borrowed as an unchanged clean baseline.',
        'Bootstrap itself uses the pinned proof producers and Root exact pin review; it does not independently re-run all per-gate semantics. Root must verify run_identity, all three named gate finals/records, source_changed false, complete baseline/before/after evidence and origin observation when filling the three actual pins.'
    ],
    'budget_and_runtime_contract': {'native_outer_seconds': 45000, 'source_outer_seconds': 7200,
        'source_gate_seconds': scfg['budgets_seconds'], 'plan_phase_count': 14,
        'eval_lib_seconds': 3600, 'focused_outer_seconds': 12000, 'all_outer_seconds': 21000,
        'focused_ordinary_root_each_seconds': 7200, 'toolchain_seconds': 120, 'helper_build_seconds': 3600,
        'helper_verification_each_seconds': 120, 'root_setup_and_unmount_each_seconds': 60,
        'admission_seconds': 600, 'final_evidence_seconds': 300,
        'native_driver': pins['native-driver.original.py'], 'native_wrapper': pins['native-wrapper.py'],
        'source_wrapper': pins['source-gates-wrapper.py'], 'plan': pins['PLAN.original.json'],
        'root_case_count_from_exact_current_workflow_AST': 33, 'ordinary_packages_from_exact_workflow': constants['packages'],
        'root_cases_dynamic_not_hardcoded_by_b92': True,
        'runtime_notes': ['Original justfile enforces RUST_MIN_STACK=8388608 and local nextest profile.',
            'Every invoked test argv retains --retries 0; the unchanged nextest file has profile defaults and per-case overrides, not a newly rewritten global zero-retry config.',
            'Original --no-fail-fast, timeout overrides, full eval library plus four required names, seven focused filters, full five-package ordinary suite and exact dynamic Root ignored-only cases remain unchanged.',
            'Root suite is reached only after ordinary success. Fresh direct /run child and source/bind/checkpoints setup, UID0 check, sudo env whitelist, JUnit equality and cleanup remain original b92.',
            'No source success or native suite result is inherited from 246d or prior cc57 v1 admission failure.']},
    'HOLD_fields': {'SOURCE_SUCCESS.result': None, 'SOURCE_SUCCESS.original_run_result': None,
        'SOURCE_SUCCESS.supervisor': None, 'stdin.source_supervisor_base64': None},
    'remaining_before_execution': ['Observe complete current 1cb4 terminal and full source records; a running job is insufficient.',
        'Root must approve exact actual source wrapper RESULT, original run-result and authoritative normal supervisor pins, full output and complete unchanged-source evidence.',
        'Only then prepare a sealed successor of this immutable HOLD with those exact observed bytes and receive Root exact-launch approval; do not execute the HOLD request.'],
    'limitations': ['Read-only local AST/byte/data audit; no reviewed module was imported or executed, no native filesystem/process probe and no runtime or qualification assertion.',
        'The exact future normal/payload and source proof pins do not exist in this HOLD. Source state may progress elsewhere after the audit; this report intentionally does not fill or infer success.']
}
OUT.mkdir(exist_ok=True)
out_raw = (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
with (OUT / 'REVIEW.json').open('xb') as stream:
    stream.write(out_raw)
print(json.dumps({'report': str(OUT / 'REVIEW.json'), **pin(out_raw)}, sort_keys=True))
