"""Build review-only JSON/text from frozen files; never execute a gate or wrapper."""
from pathlib import Path
import ast
import hashlib
import json

OUT = Path('/tmp/hepta-36fa-final-qualification-hold-v1')
PLAN = Path('/tmp/hepta-36fa-exact-source-qualification-plan-v2/PLAN.json')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def code(name):
    raw = (OUT / name).read_bytes()
    parsed = ast.parse(raw, filename=name)
    compile(parsed, name, 'exec')
    return raw.decode(), parsed


plan = json.loads(PLAN.read_bytes())
controls = plan['unchanged_original_controls']
originals = {
    'native-driver.original.py': 'b92ddded4fce78aeb076d022471c62bf81ce2e4f',
    'source-gates-driver.original.py': '51181866cbbb6e0176aab04117efffa8b6792b31',
    'canonical-wrapper.previous.py': '5be7e21dff083c19c2b56c75964d6fa1a765a412',
    'hepta_ci_exec.original.py': 'c9434b3a4afb31f80e323d543936386a2fa738de',
    'hepta_ci_junit.original.py': '683626df091bdfe160a8965fdc92bf40f5783cf8',
}
for name, expected in originals.items():
    assert identity((OUT / name).read_bytes())['git_blob'] == expected, name
    code(name)
native, native_ast = code('native-wrapper.HOLD.py')
source, source_ast = code('source-gates-wrapper.HOLD.py')
admission, admission_ast = code('qualification-admission.HOLD.py')
old, old_ast = code('canonical-wrapper.previous.py')

eval_calls = [n for n in ast.walk(native_ast) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Name) and n.func.id == 'run'
              and len(n.args) >= 2 and isinstance(n.args[1], ast.List)]
assert len(eval_calls) == 1
eval_call = eval_calls[0]
assert ast.literal_eval(eval_call.args[1]) == plan['phases'][0]['command']
assert {k.arg: ast.literal_eval(k.value) for k in eval_call.keywords} == {
    'minimum_tests': 1, 'timeout_seconds': 3600}
assert '[("focused",12000),("all",21000)]' in native
assert 'len(actual)!=163' not in native and 'exactly163' not in native
assert 'command("fix"' not in native and 'command("fmt"' not in native
assert 'guard.inventory.main()' in source
assert "'budgets_seconds'] == {'source-closure': 600, 'self-test': 300, 'verify': 4800}" in source
assert "if result['driver_returncode'] == 0:" in source
assert "result['inconsistent_original_terminal']" in source

old_defs = {n.name: ast.get_source_segment(old, n) for n in old_ast.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
new_defs = {n.name: ast.get_source_segment(native, n) for n in native_ast.body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
definitions = [{'name': k, 'same_source': old_defs[k] == new_defs.get(k)} for k in old_defs]

repo = '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
base = '/home/qian-qi/hepta-utility-36fa-evidence'
known_controls = base + '/fresh-maintenance-86dd-v1'
four = [
 'closure::tests::incomplete_evidence::known_failure_does_not_replace_longitudinal_retention_or_unlearning',
 'closure::tests::incomplete_evidence::known_failure_keeps_missing_evidence_unknown_under_both_claim_scopes',
 'closure::tests::incomplete_evidence::legacy_negative_evaluation_also_requires_complete_evidence',
 'tests::incomplete_evidence::known_regression_with_unknown_metric_support_is_not_complete_ineligible',
]
cfg = {
    'schema': 'hepta.utility.final-source-qualification-handoff.v1',
    'state': 'HOLD_WAITING_FOR_ACTUAL_FINAL_FORMAT_AND_CANONICAL_ALIGNMENT',
    'root_execution_approved': False,
    'source': None, 'tree': None, 'parents': None,
    'expected_file_count': 15188, 'full_physical_inventory': None,
    'expected_inventory_sha256': None,
    'repo': repo, 'target': '/data/hepta-utility-36fa-final-native-target-v1',
    'records_parent': base, 'records': None, 'root_parent': None,
    'run_identity': None,
    'native_driver_path': None,
    'native_driver_pin': controls['native_driver'],
    'admission_path': None,
    'admission_pin': identity((OUT / 'qualification-admission.HOLD.py').read_bytes()),
    'maintenance_guard_path': known_controls + '/driver-v5.py',
    'inventory_driver_path': known_controls + '/inventory-driver-v2.py',
    'plan_path': None, 'plan_pin': identity(PLAN.read_bytes()),
    'runtime_guard': None,
    'final_format': None, 'canonical_alignment': None,
    'actual_final_format_postimages_reviewed': False,
    'reviewed_formatter_changed_paths': None,
    'coordination_lock': {
        'path': known_controls + '/SOURCE_COORDINATION.lock',
        'device': 2050, 'inode': 50139448, 'uid': 1000, 'mode': 384, 'nlink': 1,
    },
    'positive_eval_cases': four,
    'source_gates_handoff_records': None,
    'source_gates_config_path': None, 'source_gates_config_pin': None,
}
save('QUALIFICATION_INPUT.HOLD.json', cfg)
save('SOURCE_GATES_CONFIG.HOLD.json', {
    'schema': 'hepta.utility.desktop-source-gates.v1',
    'state': 'HOLD_WAITING_FOR_ACTUAL_FINAL_SOURCE',
    'source_sha': None, 'source_tree': None,
    'driver_sha256': controls['source_gates_driver']['sha256'],
    'hepta_ci_exec_sha256': identity((OUT / 'hepta_ci_exec.original.py').read_bytes())['sha256'],
    'source_checkout': None, 'object_repository': repo,
    'records': None, 'run_identity': None,
    'budgets_seconds': {'source-closure': 600, 'self-test': 300, 'verify': 4800},
})

phase_map = []
for row in plan['phases']:
    item = {'id': row['id']}
    for k in ('timeout_seconds', 'outer_driver_budget_seconds'):
        if k in row:
            item[k] = row[k]
    item['implementation'] = ('unchanged original 5118 main' if row['id'] in
        ('source-closure', 'caller-self-test', 'caller-verify') else
        'unchanged original b92 main' if row['id'] != 'eval-lib' else
        'original run/collect command; fresh four-case coverage, dynamic complete library count')
    phase_map.append(item)
assert len(phase_map) == 14
save('PHASES.original-plan.json', phase_map)
save('STATIC_REVIEW.json', {
    'format': 'hepta-final-qualification-hold-static-review-v1',
    'state': 'PREPARED_HOLD_NOT_EXECUTED',
    'checks': {
        'original_native_source_recorders_exact': originals,
        'syntax_compiled_to_code_objects_only': True,
        'any_module_or_control_main_executed': False,
        'eval_command_and_budget_equal_plan': True,
        'focused_all_budgets_12000_21000_preserved': True,
        'source_main_and_budgets_600_300_4800_preserved': True,
        'historical_163_test_count_not_a_gate': True,
        'no_repeat_fix_or_fmt_in_qualification': True,
        'actual_future_source_environment_proofs_not_filled': True,
        'original_outer_native_definition_comparison': definitions,
        'source_wrapper_inconsistent_success_does_not_pass': True,
    },
    'remaining_actual_inputs': [
        'Root-approved actual final-format normal supervisor/result/postimage review',
        'Actual final canonical SHA/tree/parents and clean alignment normal supervisor/result',
        'Actual canonical complete physical inventory and original native compact snapshot hash',
        'Current approved restored runtime 17-field input and original seed-bound proofs',
        'Fresh external records/clone/Root parent/idempotency key and staged control identities',
        'Root-reviewed actual host request and outer source-gate execution budget',
    ],
    'dispatches': {'H': 0, 'Cargo': 0, 'source_gates': 0, 'formatter': 0},
})

readme = '''# Final exact-source qualification controls: HOLD

This is a local, unexecuted control proposal. It does not contain a final source
commit, current environment admission, actual final-format success, or canonical
alignment success. Root must bind those actual facts before dispatch. No H call,
Cargo invocation, source gate, formatter, or source/ref modification was made.

## Preserved entrypoints

`native-wrapper.HOLD.py` is the small successor to the actual 5be7 wrapper:
complete unfiltered eval library through the original recorder/collector, then
the exact b92 focused driver, then its exact all driver (ordinary followed by
Root). Its four named eval regressions remain mandatory. Counts come from the
fresh complete library, not the old 163 observation. b92, 5118, both recorders,
all original 14 phase budgets, 8 MiB stack, nextest overrides, zero retries, and
the dynamic final-source workflow Root inventory are unchanged. The original
native toolchain/helper phases still execute in each original b92 invocation.

`source-gates-wrapper.HOLD.py` calls the exact original 5118 `main()` with its
normal config/argv. Original clone, freeze, complete input enumeration, closure
600, self-test 300, full caller 4800, retention, failure and not-run behavior
are owned by that unchanged driver. A nonzero/unknown main return cannot be
success merely because a JSON status says passed; the original bytes remain.

## Actual admission only

`qualification-admission.HOLD.py` reuses the exact V5 environment preflight,
including its original historical 86dd seed-bound restoration proof, all six
normal UV commands, explicit 17-field environment, tool/material hashes,
32 GiB resource floor, and unchanged current build/formatter process guard.
Only current Git HEAD/tree expectations are set to the future approved source;
the original restoration SEED constants are not relabeled. It does not invoke
V5 maintenance main, fix, fmt, download, installation, or target creation.

Actual normal final-format and clean-alignment results must link to each other
and the final commit/tree/parents/full source. Every actual formatter postimage
must already be reviewed. Final format is the separately recorded original
`just fmt --base c0f78493f815780f68b9bf5e390a21314d79311f`, 900 seconds,
after the final code change. This qualification does not repeat it or fix.

Admission holds a real SH lock on the already observed coordination inode;
cooperating source writers use EX. It keeps actual full physical observations,
raw Git equality, source control pins, and original native snapshots. Generated
ignored JUnit/output entries are retained explicitly; their existence is not
called full physical byte equality. Original source rows cannot change.

## Scheduling and values still pending

Both wrappers require the actual initial canonical full physical inventory.
Run source-gate admission before native-generated source-local JUnit files
exist, or review a separate actual current full source handoff; do not silently
substitute a different inventory. A simple source-gates-first schedule avoids
both that issue and Cargo overlap. Scheduling is left to Root/native and no
parallel launch is requested here. The native outer request historically used
45000 seconds; the final source wrapper outer request has no invented budget.
Each original phase retains its own approved limit.

The HOLD JSON files deliberately leave final commit/tree/parents, original
compact snapshot, clean full inventory, runtime guard, actual result/normal
pins, unique execution paths, and keys empty. Changing the state/approval flag
alone cannot satisfy those checks. Final create-only staging/typed launch must
be reviewed after real final-format and canonical-alignment observations.

## Evidence semantics

Only original raw records/JUnit and their actual normal terminal establish a
phase outcome. Earlier c0f/86dd diagnostics and local QA results are not reused
as final-source PASS. Missing evidence stays unknown; known nonzero/timeout and
source changes stay failed. The unchanged source driver retains all original
per-gate files, including post-packaging `gate-final.json` and original
`run-result.json`; its earlier `gate-summary.json` can be a pending snapshot.
Even successful mechanism gates do not prove a real authorized A/T/independent
B/new C/daemon/Root learning iteration, complete costs, or adoption.
'''
(OUT / 'README.md').write_text(readme)
print(json.dumps({'prepared': str(OUT), 'phase_count': len(phase_map),
                  'actual_execution': False, 'files': {
    name: identity((OUT / name).read_bytes()) for name in (
        'qualification-admission.HOLD.py', 'native-wrapper.HOLD.py',
        'source-gates-wrapper.HOLD.py', 'QUALIFICATION_INPUT.HOLD.json',
        'SOURCE_GATES_CONFIG.HOLD.json', 'STATIC_REVIEW.json')}}, indent=2))
