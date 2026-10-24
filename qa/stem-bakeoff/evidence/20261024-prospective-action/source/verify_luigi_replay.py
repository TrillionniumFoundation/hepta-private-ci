"""Post-completion integrity/infrastructure audit; no label or model scoring."""
import hashlib
import json
from pathlib import Path
import re
import sys
import time

SOURCE = Path('/workspace/scratch/f1f83ab8f2f0/hepta/qa/stem-bakeoff')
sys.path.insert(0, str(SOURCE))
from operational_region_evidence import verify_pins
from prospective_action_execution import validate_case
from prospective_action_run import verify_inventory
from prospective_outcome_selection import load_selection
from reconcile_prospective_outcomes import capture_condition

ROOT = Path('/tmp/hepta-prospective-action-20261024/luigi-dependencies-v1')
SELECTION = ROOT.parent/'outcome-selection-v1/plan.json'
SELECTION_SHA = '9a7b8e667aba20ba3e98545dd9598f14afbb6331fac28cc595fc6cc3fca1380f'
SUMMARY_SHA = '814a7ccbc8625bcc017ee9efa457c788fbcb51c6e22628af7084b88d68048505'
CONFIG_SHA = '7b88e5b223e38d12de2e3bee2de4c1bb718b048bbd0fdf4c63c8447f80e8d9b2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    plan, _, inputs, config, pins = load_selection(SELECTION, SELECTION_SHA)
    executions = ROOT/'executions'
    execution_plan_sha = sha(executions/'execution-plan.json')
    condition = capture_condition(executions, inputs['case_bindings'], plan['replacement']['projected_inputs_sha256'],
                                  execution_plan_sha, SUMMARY_SHA, pins)
    actual_plan, summary = condition['plan'], condition['summary']
    issues, expected_files, commands, import_errors, disk_errors, execution_errors = [], set(), [], [], [], []
    if (actual_plan['runtime_config'] != config or actual_plan['runtime_config_sha256'] != CONFIG_SHA
            or actual_plan['frozen_file_pins'].get(str(SELECTION)) != SELECTION_SHA
            or any(actual_plan[key] != value for key, value in plan['execution_policy'].items())
            or actual_plan['work_root'] != str(ROOT/'worktrees')):
        issues.append('execution differs from the independently pinned whole-project selection')
    for group, binding in inputs['case_bindings'].items():
        case = condition['cases'][group]
        directory = executions/(binding['project']+'-'+str(binding['bug_id']))
        execution_errors.extend({'group_id': group, 'error': error} for error in case['errors'])
        for action in binding['actions']:
            key = action['key']
            for role in ('base', 'candidate'):
                path = directory/key/role/'execution.json'
                expected_files.add(str(path))
                if not path.is_file() or role not in case['pairs'].get(key, {}):
                    issues.append('missing complete command observation: '+str(path))
                    continue
                record = json.loads(path.read_bytes())
                profile = config['profiles'][config['group_profiles'][group]]
                if (record != case['pairs'][key][role] or record['candidate_key'] != key
                        or record['original_args'] != action['args'] or record['runner'] != action['runner']
                        or record['command'][0] != profile['python']
                        or record['limits'] != plan['execution_policy']['limits']
                        or record['observer_sha256'] != actual_plan['code_sha256']['prospective_action_observer.py']):
                    issues.append('command/source/observer binding mismatch: '+str(path))
                evidence = {'group_id': group, 'action_key': key, 'revision_role': role,
                            'execution_sha256': sha(path)}
                commands.append(evidence)
                for name in ('stdout.log', 'stderr.log'):
                    log = path.with_name(name)
                    for line in log.read_text(errors='replace').splitlines():
                        if re.search(r'(?:ModuleNotFoundError|ImportError):', line):
                            import_errors.append({**evidence, 'log': name, 'line': line[:2000]})
                        if 'No space left on device' in line or '[Errno 28]' in line:
                            disk_errors.append({**evidence, 'log': name, 'line': line[:2000]})
                observed = record.get('observation') or {}
                for item in observed.get('observations', []):
                    if item.get('resource_failure_errno') == 28:
                        disk_errors.append({**evidence, 'structured_resource_errno': 28})
    actual_files = {str(p) for p in executions.rglob('execution.json')}
    if actual_files != expected_files or len(commands) != 268:
        issues.append('complete command receipt inventory is not exactly all268 frozen slots')
    if summary['physical_command_executions'] != 268 or summary['complete_command_observations'] != 268:
        issues.append('physical starts or complete observations differ from268')
    inventories = {name: verify_inventory(r['root'], r['manifest'], r['sha256'])
                   for name, r in config['inventories'].items()}
    ready = json.loads((ROOT/'plan.json').read_bytes())
    original = ready['repair']['original_runtime']
    original_check = verify_inventory(original['root'], original['manifest'], original['sha256'])
    verify_pins(pins)
    for group, binding in inputs['case_bindings'].items():
        directory = executions/(binding['project']+'-'+str(binding['bug_id']))
        if validate_case(directory, binding, execution_plan_sha) != condition['cases'][group]:
            raise ValueError('case evidence changed before post-replay audit publication')
    target_errors = [record for record in import_errors if re.search(r'\b(?:pyparsing|sqlalchemy)\b', record['line'], re.I)]
    report = {'schema': 'hepta.uniform-luigi-replay-integrity.v1', 'selection_plan_sha256': SELECTION_SHA,
        'execution_plan_sha256': execution_plan_sha, 'summary_sha256': SUMMARY_SHA,
        'runtime_config_sha256': CONFIG_SHA, 'projected_inputs_sha256': plan['replacement']['projected_inputs_sha256'],
        'source_groups': len(inputs['case_bindings']), 'actions': len(commands)//2,
        'physical_starts': summary['physical_command_executions'], 'complete_command_observations': len(commands),
        'exactly_all268_receipts_verified': len(commands) == 268 and not issues,
        'issues': issues, 'per_command_evidence': commands, 'orchestration_errors': execution_errors,
        'target_missing_dependency_signatures': target_errors, 'all_import_error_signatures': import_errors,
        'enospc_signatures': disk_errors, 'runtime_inventory_checks': inventories,
        'original_runtime_unchanged_check': original_check,
        'original_source_and_execution_code_pins_unchanged': True, 'selection_pin_in_actual_execution_plan': True,
        'all_observations_preserved_regardless_of_outcome': True, 'model_fit_or_score_performed': False,
        'verifier_sha256': sha(__file__), 'wall_ns': time.perf_counter_ns()-started,
        'cpu_ns': time.process_time_ns()-cpu,
        'cost_scope': 'Post-completion independent receipt, log and source/runtime inventory audit; excludes this report write. No benchmark commands rerun.'}
    with (ROOT/'verification/replay-integrity.json').open('xb') as stream:
        stream.write(json.dumps(report, sort_keys=True, indent=2).encode()+b'\n')
    print(json.dumps({'report_sha256': sha(ROOT/'verification/replay-integrity.json'),
        **{key: report[key] for key in ('execution_plan_sha256', 'summary_sha256', 'source_groups',
           'complete_command_observations', 'exactly_all268_receipts_verified', 'wall_ns', 'cpu_ns')},
        'issues': len(issues), 'orchestration_errors': len(execution_errors),
        'target_missing_dependency_signatures': len(target_errors), 'all_import_error_signatures': len(import_errors),
        'enospc_signatures': len(disk_errors)}))


if __name__ == '__main__':
    main()
