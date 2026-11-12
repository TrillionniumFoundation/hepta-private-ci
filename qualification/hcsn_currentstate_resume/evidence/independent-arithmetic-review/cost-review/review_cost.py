"""Read-only receipt arithmetic; no candidate/reference imports or execution."""
from pathlib import Path
import ast
import hashlib
import json

ROOT = Path('/workspace/scratch/c06d659c1e72/currentstate-resume-raw')
RAW = ROOT/'evidence/saved-fullraw-attempt001'
OUT = Path(__file__).resolve().parent


def filemeta(p):
    b = p.read_bytes()
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest()}


def main():
    freeze = json.loads((ROOT/'FREEZE.json').read_text())
    source_actual = {k: filemeta(ROOT/k)['sha256'] for k in freeze['source_sha256']}
    input_actual = {k: filemeta(ROOT/k)['sha256'] for k in freeze['input_sha256']}
    assert len(source_actual) == 10 and len(input_actual) == 5
    assert source_actual == freeze['source_sha256']
    assert input_actual == freeze['input_sha256']
    expected_guard = {'source_sha256':source_actual, 'input_sha256':input_actual}
    receipt_paths = [ROOT/'FREEZE.json', RAW/'SUMMARY.json']
    receipt_paths += [RAW/name/mode/'TRAJECTORY.json'
                     for name in ('mixed','rare') for mode in ('warm','coarse','cold')]
    receipt_paths += [RAW/name/'cold/GUARD.json' for name in ('mixed','rare')]
    source_paths = [ROOT/k for k in source_actual]
    input_paths = [ROOT/k for k in input_actual]
    paths = list(dict.fromkeys(receipt_paths+source_paths+input_paths))
    before = {str(p.relative_to(ROOT)):filemeta(p) for p in paths}
    s = json.loads((RAW/'SUMMARY.json').read_text())
    plan = json.loads((ROOT/'qualification/hcsn_currentstate_resume/PLAN.json').read_text())
    assert s['before'] == s['after'] == expected_guard and s['unchanged'] is True
    assert s['source_freeze_commit'] == freeze['source_commit'] == '9e9dc3fb698ce53046790e09497420eaaee8df5f'
    assert s['identity'] == freeze['identity'] == plan['identity']
    trajectory_counts = []; expm = segments = advances = observations = 0; max_matrix = 0
    for name in ('mixed','rare'):
        for mode in ('warm','coarse','cold'):
            t = json.loads((RAW/name/mode/'TRAJECTORY.json').read_text())
            times = [r['time'] for r in t['rows']]
            expected_times = ['9/25'] if mode == 'coarse' else ['7/25','9/25']
            assert times == expected_times and t['fixture'] == name
            assert t['ledger'] == s['cost'][name][mode]
            assert t['input_sha256'] == input_actual[f'qualification/hcsn_currentstate/evidence/currentstate-attempt001/{name}.resume.json']
            assert t['input_direct_bytes_equal'] is True
            assert t['initial_trajectory_advances'] == t['reference_evaluations'] == 0
            ledger = t['ledger']
            assert ledger['maximum'] == 100
            assert 0 <= ledger['expm_calls'] <= 100 and 0 <= ledger['segments'] <= 20
            assert 0 <= ledger['max_matrix'] <= 128
            expm += ledger['expm_calls']; segments += ledger['segments']
            max_matrix = max(max_matrix,ledger['max_matrix'])
            advances += len(times); observations += len(times)
            trajectory_counts.append({'fixture':name,'mode':mode,'times':times,'ledger':ledger})
        cg = json.loads((RAW/name/'cold/GUARD.json').read_text())
        assert cg['before'] == cg['after'] == expected_guard and cg['unchanged'] is True
    assert len(trajectory_counts) == plan['max_ledgers'] == 6
    assert expm == 284 <= plan['max_expm_global_fixed_roster'] == 600
    assert segments == 28 <= plan['max_segments_global_fixed_roster'] == 120
    assert advances == plan['candidate_advance_API_calls'] == 10
    assert observations == plan['candidate_observe_API_calls'] == 10
    assert s['rows'] == 10
    assert plan['parent_CPU_soft_hard_seconds'] == [20,21]
    assert plan['each_child_CPU_soft_hard_seconds'] == [5,6]
    assert plan['children'] == 2
    assert 21+2*6 == plan['fixed_roster_CPU_hard_upper_bound'] == 33
    assert plan['wall_hard_limit_seconds'] == 45
    assert plan['per_process_RLIMIT_AS_bytes'] == 536870912
    assert s['wall_seconds'] < 45
    assert s['parent_setup_before_timer_excluded'] is True
    assert s['combined_peak_RSS_not_measured'] is True
    for k in ('reference_evaluations','initial_trajectory_advances','old72_kernel_replays','torch','training'):
        assert s[k] == 0
    assert s['admission'] == plan['admission'] == 'HOLD_NO_GO'
    assert s['all_closed'] == plan['all_closed'] is False
    driver_path = ROOT/'qualification/hcsn_currentstate_resume/run_saved.py'
    driver = driver_path.read_text()
    imports = [ast.unparse(n) for n in ast.parse(driver).body if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert not any('reference' in i or 'mpmath' in i for i in imports)
    assert 'cmd = ["/usr/bin/prlimit", "--cpu=5:6", "--as=536870912:536870912", "--",' in driver
    spec = (ROOT/'qualification/hcsn_currentstate_resume/SPEC.md').read_text()
    assert 'timeout -s KILL 45s' in spec
    assert '/usr/bin/prlimit --cpu=20:21 --as=536870912:536870912 -- python' in spec
    assert '/usr/bin/prlimit --cpu=5:6 --as=536870912:536870912 -- python' in spec
    after = {str(p.relative_to(ROOT)):filemeta(p) for p in paths}
    assert before == after
    result = {
      'identity':'saved-fullraw-readonly-cost-review-001',
      'artifact_commit_prefix':'2d43f01f','source_freeze_commit':freeze['source_commit'],
      'reviewer_execution':{'candidate_imports':0,'reference_imports':0,'expm':0,
        'quadrature':0,'model_runs':0,'stdlib_receipt_arithmetic_only':True},
      'input_roster_before':before,'input_roster_after':after,'unchanged':True,
      'guard_checks':{'source_files':10,'input_files':5,
        'parent_and_two_cold_before_after_rosters':6,'all_match_freeze_and_current_bytes':True},
      'cost':{'trajectories':trajectory_counts,'ledger_count':6,
        'candidate_expm_calls':expm,'candidate_segments':segments,
        'candidate_advance_calls_from_saved_rows_and_fixed_driver':advances,
        'candidate_observe_calls_from_saved_rows_and_fixed_driver':observations,
        'fixed_roster_expm_upper_bound':600,'fixed_roster_segments_upper_bound':120,
        'max_recorded_augmented_matrix_dimension':max_matrix,
        'reference_evaluations':0,'initial_trajectory_advances':0},
      'resource_review':{
        'prior_import_before_limits_issue':'Resolved in frozen launcher contract: parent and each child are started under external prlimit before Python execution; child prlimit command is frozen in driver.',
        'parent_CPU_soft_hard_seconds':[20,21],'each_child_CPU_soft_hard_seconds':[5,6],
        'fixed_roster_configured_CPU_hard_sum_seconds':33,
        'external_GNU_timeout_KILL_wall_seconds':45,
        'per_process_RLIMIT_AS_bytes':536870912,
        'runtime_getrlimit_values_retained':False,
        'saved_wall_seconds':s['wall_seconds'],
        'saved_parent_instrumented_CPU_seconds':s['parent_CPU_seconds'],
        'saved_children_CPU_seconds':s['children_CPU_seconds'],
        'sum_instrumented_parent_plus_saved_children_CPU_seconds':s['parent_CPU_seconds']+s['children_CPU_seconds'],
        'parent_import_setup_before_instrumentation_excluded':True,
        'parent_ru_maxrss_KiB':s['parent_ru_maxrss_KiB'],
        'parent_ru_maxrss_MiB':s['parent_ru_maxrss_KiB']/1024,
        'children_ru_maxrss_platform_field_KiB':s['children_ru_maxrss_platform_field_KiB'],
        'children_ru_maxrss_platform_field_MiB':s['children_ru_maxrss_platform_field_KiB']/1024,
        'interpretation':'33 seconds is the sum of configured hard CPU limits for the fixed three-process roster, not the measured timer sum; 45 seconds is the external wall limit. The parent timer excludes setup/import, though external prlimit covers Python lifetime. ru_maxrss fields are separate platform statistics, not combined simultaneous peak RSS. AS is per-process address space, not RSS.'},
      'candidate_reference_isolation':{'driver_imports':imports,
        'reference64_read_from_hashed_old_ROWS_only':True,
        'old_reference_module_hashed_but_not_imported_by_driver':True},
      'verdict':'No saved-cost, fixed-roster guard or resource-definition arithmetic discrepancy found. This is a read-only review, not a new execution or independent enforcement trace.'}
    (OUT/'REVIEW.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'candidate_expm':expm,'candidate_segments':segments,'ledgers':6,
      'source_files':10,'input_files':5,'advance_calls':advances,'observe_calls':observations,
      'unchanged':True,'review_path':str(OUT/'REVIEW.json')},sort_keys=True))


if __name__ == '__main__':
    main()
