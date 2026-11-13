from __future__ import annotations

import ast
import datetime
import hashlib
import json
import stat
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-complete-new-source-handoff-hold-v1')
ACTUAL = Path('/tmp/hepta-36fa-v8-single-archive-restore-v3-actual')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def read(name):
    return (ROOT / 'inputs' / (name + '.txt')).read_bytes()


def constants(raw):
    result = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def write(name, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    path = ROOT / name
    with path.open('xb') as stream:
        stream.write(raw)
    return {'name': name, **pin(raw)}


def main():
    v5 = read('V5_ORIGINAL')
    v5_values = constants(v5)
    admission = read('ISOLATED_ADMISSION_ORIGINAL')
    materializer = read('MATERIALIZER_ORIGINAL')
    materializer_packet = json.loads(read('MATERIALIZER_PACKET_ORIGINAL'))
    formatter = read('FORMAT_ORIGINAL')
    old_ready = json.loads(read('HISTORICAL_ENVIRONMENT_READY'))
    old_cfg = json.loads(read('PRIOR_QUALIFICATION_INPUT'))
    source_request = json.loads(read('PRIOR_SOURCE_REQUEST'))
    source_pins = constants(source_request['args'][2])['PINS']
    applyfmt = json.loads(read('PRIOR_APPLYFMT_APPROVAL'))
    alignment = json.loads(read('PRIOR_ALIGNMENT_APPROVAL'))
    result_raw = (ACTUAL / 'RESULT.json').read_bytes()
    result = json.loads(result_raw)
    normal_raw = (ACTUAL / 'STATUS_01.original.json').read_bytes()
    archive_raw = (ACTUAL / 'small/ARCHIVE_READBACK.json').read_bytes()
    archive = json.loads(archive_raw)
    assert result['archive_actual'] == archive == result['final_audits'][2]['archive']
    assert result['status'] == 'ARCHIVE_RESTORED_FOR_REVIEW_ONLY'
    assert all(x['status'] == 'verified' for x in result['final_audits'])
    assert result['qualification'] is False and result['native_main_started'] is False
    historical = old_ready['tool_and_material_files']['v8-sandbox-archive']
    fields = ['path', 'resolved', 'bytes', 'sha256', 'mode']
    projected = {'path': archive['path'], 'resolved': archive['path'],
                 'bytes': archive['identity']['bytes'], 'sha256': archive['identity']['sha256'],
                 'mode': stat.S_IMODE(archive['stat']['st_mode'])}
    assert projected == {x: historical[x] for x in fields} == old_cfg['runtime_guard']['v8_files']['RUSTY_V8_ARCHIVE']
    assert historical['inode'] != archive['stat']['st_ino']
    commits = [x['sha'] for x in materializer_packet['raw_commits']]
    assert commits == ['246d8cb614770252ee42029a5c014f2a4904176a',
                       'cc57c7198db6293ccca562253c42fffbe2a04633']
    base = v5_values['C0F']
    assert base not in commits
    original_fix = v5_values['FIX']
    successor_fix = original_fix + ['-p', 'codex-hepta-learning-ledger']
    outputs = []
    runtime = {
        'format': 'hepta-actual-archive-runtime-successor-binding-proposal-v1',
        'status': 'HOLD_NOT_AN_EXECUTABLE_CONTROL',
        'historical_runtime_environment': pin(read('HISTORICAL_ENVIRONMENT_READY')),
        'historical_runtime_environment_is_unchanged': True,
        'original_v5_guard': pin(v5),
        'original_functions': {
            'project_runtime_file': 'lines 495-499: exact path/resolved/bytes/sha256/mode projection',
            'installed_file_observation': 'lines 480-493: current full SHA read with current dev/inode/size/mtime/ctime equal before/after; returns five fields only',
            'environment_preflight': 'lines 616-620: current V8 pair == approved cfg pair == historical content/path/mode projection',
            'validate_runtime_restoration': 'lines 501-549: original 86dd restoration source identity and its six original commands remain historical'},
        'original_five_field_projection': projected,
        'new_archive_actual_stat': archive['stat'],
        'historical_archive_stat': {x: historical[x] for x in ['device', 'inode', 'uid', 'nlink', 'mode', 'mtime_ns', 'ctime_ns']},
        'new_inode_equals_historical_inode': False,
        'required_successor_evidence': {
            'job_id': '1a1d38b82e9-392-160',
            'result_path': '/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run/RESULT.json',
            'result': pin(result_raw),
            'supervisor': pin(normal_raw),
            'supervisor_staged_path': None,
            'archive_record_path': '/home/qian-qi/hepta-utility-36fa-evidence/v8-single-archive-restore-v3/run/ARCHIVE_READBACK.json',
            'archive_record': pin(archive_raw),
            'artifact_index': pin((ACTUAL / 'ARTIFACTS.json').read_bytes()),
            'source_of_this_repair_remains': {'repo': result['source_repo'], 'commit': result['source_commit'], 'tree': result['source_tree']}},
        'minimal_integration': [
            'Keep 6632 V5 original bytes and the original 8b62 runtime document unchanged.',
            'Add a separately reviewed actual archive-restoration proof validator to the successor admission, binding the normal job, full result, artifact and exact archive record.',
            'Require this proof to describe only the known original path and original content/mode identity, all three final audits verified, no source/env changes, no native/test qualification, and no retry.',
            'Retain the new full archive stat from the repair as the latest observed restoration identity. Never label the old historical inode as current.',
            'At a future approved run the unmodified original guard still performs its own full live read and before/after stat stability check. Historical five-field equality remains a content/path/mode check, not an inode-continuity assertion.',
            'If a successor records another full current stat, it must be an actual new observation under that reviewed action. No current inode/stat is filled from prediction.',
            'The original explicit environment, tool projections, formatter environment, target, 32 GiB check and global build guard stay unchanged. No target or dependency installation is implied.'],
        'no_current_execution_permission': True,
        'no_future_material_availability_guarantee': True,
    }
    outputs.append(write('RUNTIME_ARCHIVE_BINDING.HOLD.json', runtime))
    base_review = {
        'format': 'hepta-new-source-format-base-object-scope-review-v1',
        'status': 'STATIC_GAP_CONFIRMED_FUTURE_INPUT_REQUIRED',
        'materializer': pin(materializer),
        'materialization_packet': pin(read('MATERIALIZER_PACKET_ORIGINAL')),
        'declared_scope': materializer_packet['object_scope'],
        'declared_commit_objects': commits,
        'unmaterialized_parent_boundary': materializer_packet['parent_snapshot']['parents'],
        'formatter': pin(formatter),
        'required_base': {'commit': base, 'tree': v5_values['C0F_TREE']},
        'required_base_commit_in_original_pack': False,
        'actual_current_repository_presence_rechecked': False,
        'observed_static_calls': [
            ['git', 'rev-parse', '--verify', '--end-of-options', base + '^{commit}'],
            ['git', 'diff', '--name-only', '--diff-filter=ACDMRT', '--no-renames', '-z', '<resolved-base>', '--'],
            ['git', 'ls-files', '--others', '--exclude-standard', '-z'],
            ['git', 'show', base + ':<changed-pyproject-path>']],
        'conclusion': 'The old 16449-object closed pack does not supply c0f. A new maintenance source must explicitly include the authentic c0f commit and its full snapshot object closure before any original fmt --base invocation.',
        'required_frozen_input': 'FORMAT_BASE_OBJECTS_PACKET.json',
        'required_input_body': ['authentic raw c0f commit with exact original Git object hash', 'complete original c0f tree graph rooted at 313ee34febc8ccc54c611ab56286e289518c63cb', 'complete required original blob bodies, deduplicated against current and candidate snapshots', 'every object type/size/SHA256/Git SHA plus raw data or a pinned local source', 'bounded pack union and explicit ancestor boundary'],
        'source_strategy': 'Reuse the previously retained exact c0f snapshot evidence; verify complete raw identities before import. Do not fetch recursively in the execution, create shallow/graft/replace refs, or repair the old source repository.',
        'preflight': 'The new materializer must read back the complete declared object union and resolve the original c0f commit/tree. The maintenance control must reject a missing base rather than substitute HEAD, --all, a different base or a smaller file list.',
        'original_fmt_seconds': 900,
        'ancestry_or_merge_base_required_by_read_formatter_source': False,
        'all_future_tests_build_scripts_history_audited': False,
        'new_H_or_git_command_executed_for_this_review': False,
    }
    outputs.append(write('FORMAT_BASE_OBJECT_SCOPE.HOLD.json', base_review))
    interfaces = {
        'format': 'hepta-complete-new-source-existing-runner-interfaces-v1',
        'original_materializer_driver': pin(materializer),
        'original_materializer_packet': pin(read('MATERIALIZER_PACKET_ORIGINAL')),
        'original_maintenance_driver': pin(v5),
        'original_inventory_driver': v5_values['INVENTORY_PIN'],
        'original_execute_logged_entry': next(x for x in v5_values['SOURCE_PINS'] if x['path'] == 'scripts/hepta_ci_exec.py'),
        'original_formatter': pin(formatter),
        'original_final_nonrust_apply_fmt_driver': applyfmt['four_raw_inputs']['driver.py'],
        'original_final_nonrust_apply_fmt_bootstrap': applyfmt['actual_bootstrap'],
        'original_canonical_alignment_driver': alignment['four_inputs']['driver.py'],
        'original_canonical_alignment_bootstrap': alignment['bootstrap'],
        'isolated_native_admission_predecessor': pin(admission),
        'source_wrapper': source_pins['source-gates-wrapper.py'],
        'native_wrapper': source_pins['native-wrapper.py'],
        'native_driver': source_pins['native-driver.original.py'],
        'original_qualification_plan': source_pins['PLAN.original.json'],
        'source_request_predecessor': pin(read('PRIOR_SOURCE_REQUEST')),
        'scoped_ledger_maintenance_HOLD': '9549cfdac98061108d895441c8179981eb16b62f',
        'original_fix_argv': original_fix,
        'proposed_single_fix_argv': successor_fix,
        'fmt_argv': ['just', 'fmt', '--base', base],
        'budgets_seconds': {'materialize_action': 600, 'materialize_records': 180, 'materialize_outer': 900, 'maintenance_preflight': 600, 'single_fix': 7200, 'fmt': 900, 'maintenance_records': 300, 'maintenance_outer': 9300, 'final_nonrust_apply': 600, 'final_nonrust_fmt': 900, 'final_nonrust_records': 300, 'final_nonrust_outer': 2100, 'canonical_action': 600, 'canonical_records': 180, 'canonical_outer': 900, 'source_closure': 600, 'source_self_test': 300, 'source_verify': 4800, 'source_outer': 7200, 'native_outer': 45000},
        'unchanged_native_contract': 'All original 14 phases, argv, filters, per-phase budgets, original 8 MiB stack and existing nextest overrides; ordinary already includes ledger --lib, so no duplicate ledger phase.',
        'new_ledger_assertion_scope': 'Only a later actual final-source JUnit can establish the ten new codec methods ran and were not skipped; no historical pass is transferred.',
    }
    outputs.append(write('ORIGINAL_RUNNER_INTERFACES.json', interfaces))
    plan = {
        'format': 'hepta-complete-new-source-maintenance-qualification-handoff-v1',
        'status': 'HOLD_FINAL_SOURCE_AND_EXACT_CONTROLS_NOT_FROZEN',
        'root_execution_approved': False,
        'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope': 'Reviewable continuation plan only. No new native request, source mutation, runner implementation, material installation, source/ref publication or qualification is authorized or performed.',
        'historical_source': {'commit': 'cc57c7198db6293ccca562253c42fffbe2a04633', 'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e', 'actual_inventory_sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'},
        'future_subject': {'final_overlay_map': None, 'source_packet': None, 'source_commit': None, 'source_tree': None, 'complete_inventory': None, 'native_inventory': None, 'leaf_count': None, 'rust_count': None, 'source_repo': None, 'control_directories': None},
        'current_prepared_map_is_not_final': True,
        'new_source_requirement': 'Root must freeze the complete final overlay, registration and all source/QA paths and raw pre/post identities, including any final A/T/B and first-admission increments. Numbers from the 89-Rust/20-nonRust preparation are not observed source counts or frozen qualification arguments.',
        'stages': [
            {'name': 'isolated_materialization', 'input_files_to_freeze': ['driver-materialize.py', 'COMPLETE_SOURCE_PACKET.json', 'FORMAT_BASE_OBJECTS_PACKET.json', 'APPROVED_MATERIALIZATION_CONFIG.json', 'MATERIALIZATION_BOOTSTRAP.py', 'MATERIALIZATION_STDIN.json', 'MATERIALIZATION_PROCESS_INPUT.json'], 'required_behavior': 'Create only a new approved repository/control directory under the existing cooperative EX protocol and original live guard. Verify every preserved cc57 source leaf plus the exact complete candidate delta, retain deletions and original symlinks/modes, import only the full declared current/candidate/c0f object union, create normal index stat/flags, no refs/alternates/shallow/grafts, and record complete actual physical/raw Git/input audits plus normal terminal. Never alter the damaged old source or reuse its index/refs.', 'actual_proofs': None},
            {'name': 'single_original_scoped_fix_and_fmt', 'input_files_to_freeze': ['driver-maintenance.py', 'ACTUAL_MATERIALIZATION_RESULT.original.json', 'ACTUAL_MATERIALIZATION_NORMAL.original.json', 'ARCHIVE_RESTORATION_RESULT.original.json', 'ARCHIVE_RESTORATION_NORMAL.original.json', 'ARCHIVE_READBACK.original.json', 'APPROVED_MAINTENANCE_CONFIG.json', 'MAINTENANCE_BOOTSTRAP.py', 'MAINTENANCE_STDIN.json', 'MAINTENANCE_PROCESS_INPUT.json'], 'required_behavior': 'Reuse reviewed V5 recorders/environment/guards with separately reviewed new current-source identity bindings; never call its old main/initial_preflight with historical 9c4/c006 constants as if they described the new tree. One original7200 fix appends only ledger to the original two-package argv, then original900 fmt --base c0f. Nonzero/timeout/output-limit stops the next step and preserves every postimage and original log.', 'actual_proofs': None},
            {'name': 'bind_actual_formatter_bytes', 'input_files_to_freeze': ['POSTFORMAT_CAPTURE_CONFIG.json', 'POSTFORMAT_PROCESS_INPUT.json', 'ACTUAL_PROTECTED_SOURCE_PACKET.json', 'REVIEWED_NONRUST_PACKET.json'], 'required_behavior': 'Obtain actual final inventory and protected working bytes under the same SH coordination protocol. Review all formatter changes. Rebind CALLERS/allowlist/protected scopes and QA to the observed exact source, preserving all legacy guard/assertion semantics and the separate canonical and layer-local method counts.', 'actual_proofs': None},
            {'name': 'last_nonrust_apply_and_original_fmt', 'input_files_to_freeze': ['driver-final-fmt.py', 'NONRUST_PACKET.json', 'APPROVED_FINAL_FMT_CONFIG.json', 'FINAL_FMT_BOOTSTRAP.py', 'FINAL_FMT_STDIN.json', 'FINAL_FMT_PROCESS_INPUT.json'], 'required_behavior': 'Reuse the reviewed thin apply+fmt-only control with exact new before/after leaves and normal preceding proof, EX guard, full current audits and original900 fmt. No repeated fix/tests. Any further protected Rust changes require fresh actual rebind before canonical freeze; no automatic retry or unbounded loop.', 'actual_proofs': None},
            {'name': 'canonical_alignment', 'input_files_to_freeze': ['driver-canonical.py', 'CANONICAL_PACKET.json', 'FINAL_FORMAT_NORMAL.original.json', 'APPROVED_CANONICAL_CONFIG.json', 'CANONICAL_BOOTSTRAP.py', 'CANONICAL_STDIN.json', 'CANONICAL_PROCESS_INPUT.json'], 'required_behavior': 'Root constructs the exact approved canonical objects only after actual formatter output. Import the exact objects and align normal index/HEAD by existing read-tree-without-worktree-update, refresh, write-tree and detached CAS logic. No physical-source overwrite, reset or rollback. Freeze actual complete clean inventory/raw Git and normal terminal.', 'actual_proofs': None},
            {'name': 'new_exact_source_gates', 'input_files_to_freeze': ['qualification-admission.py', 'source-gates-wrapper.py', 'native-wrapper.py', 'native-driver.original.py', 'PLAN.original.json', 'APPROVED_QUALIFICATION_INPUT.json', 'APPROVED_SOURCE_GATES_CONFIG.json', 'CANONICAL_ALIGNMENT_NORMAL.original.json', 'SOURCE_BOOTSTRAP.py', 'SOURCE_STDIN.json', 'SOURCE_PROCESS_INPUT.json'], 'required_behavior': 'Use the existing original5118 shared/no-hardlinks exact clone/freeze then original600/300/4800 source stages and7200 outer. Bind new actual source/format/alignment/materialization evidence; retain historical cc57 source PASS as a different execution, never transfer it. Finish and recover original gate receipts/full logs/clone and origin audits before native.', 'actual_proofs': None},
            {'name': 'new_exact_native_gates', 'input_files_to_freeze': ['SOURCE_WRAPPER_RESULT.original.json', 'SOURCE_RUN_RESULT.original.json', 'SOURCE_NORMAL.original.json', 'APPROVED_QUALIFICATION_INPUT.json', 'NATIVE_BOOTSTRAP.py', 'NATIVE_STDIN.json', 'NATIVE_PROCESS_INPUT.json'], 'required_behavior': 'After Root independently verifies complete new source PASS, freeze one exact seven-field/no-env request reusing originalde3 wrapper/b92 driver/14 phases and45000 outer. Native JUnit/source-local artifacts must not contaminate the earlier source-clone baseline. Root authorization remains separate.', 'actual_proofs': None}],
        'approval_rules': ['Each executable successor requires exact immutable driver/config/input/typed request pins and concrete Root approval.', 'No placeholder or HOLD file is installed as an approved config.', 'An unknown admission reconciles only the same exact bytes/key, without a new key or automatic main retry.', 'Actual failures and partial state are retained; no source/reset/ref cleanup or budget/filter/stack relaxation.'],
        'original_global_conditions': {'cargo_target': old_cfg['target'], 'minimum_target_free_bytes': 32 * 1024**3, 'create_target_if_absent': False, 'same_uid_global_guard': True, 'cooperative_EX_for_mutations_SH_for_captures': True, 'full_source_and_raw_Git_audits': True},
        'archive_runtime_binding_document': 'RUNTIME_ARCHIVE_BINDING.HOLD.json',
        'format_base_scope_document': 'FORMAT_BASE_OBJECT_SCOPE.HOLD.json',
        'existing_runner_interfaces_document': 'ORIGINAL_RUNNER_INTERFACES.json',
        'no_old_cc57_native_rerun_planned_before_new_source': True,
        'H_actions_by_this_preparation': 0,
    }
    outputs.append(write('PLAN.HOLD.json', plan))
    outputs.append(write('STATIC_PREPARATION_RESULTS.json', {
        'format': 'hepta-new-source-handoff-pure-static-findings-v1',
        'executed': 'This local preparation script only decoded recorded JSON and AST literal constants; no imported reviewed module or entry point was executed.',
        'materializer_exact_two_commit_scope': commits, 'format_base_missing_from_declared_scope': base,
        'new_actual_archive_five_field_projection_equals_historical_and_cfg': True,
        'new_archive_inode_differs_from_historical': True,
        'future_source_and_execution_proofs_left_null': True,
        'original_fix_argv': original_fix, 'single_fix_HOLD_argv': successor_fix,
        'original_source_outer': source_request['timeout_seconds'],
        'H_requests': 0, 'Cargo_formatter_tests_or_gates_executed': 0,
    }))
    manifest = {'format': 'hepta-prepared-handoff-manifest-v1', 'status': 'HOLD', 'files': outputs,
                'script': pin(Path(__file__).read_bytes()),
                'source_input_pins': {p.name: pin(p.read_bytes()) for p in sorted((ROOT / 'inputs').iterdir())}}
    outputs.append(write('MANIFEST.json', manifest))
    print(json.dumps(outputs, sort_keys=True))


if __name__ == '__main__':
    main()
