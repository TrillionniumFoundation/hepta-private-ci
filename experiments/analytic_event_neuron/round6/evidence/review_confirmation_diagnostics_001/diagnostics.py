"""Post-audit descriptive coordinate and operational-ledger verification only."""
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import time

RUN = Path(sys.argv[1]).resolve()
OUTPUT = Path(sys.argv[2]).resolve()
EXPECTED = {
    'FREEZE.json': '1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1',
    'RESULTS.json': '303e98b4c6679f7dd827bb2c3a7083d96010984adbba43e1c6548b7930f53a69',
    'execution/CONFIRMATION_BATCH_COMPLETED.json': '5548532acbfdc14e43df432058a9dc67653786e3fb6d146a3f6c20f68a2e6c37',
    'execution/confirmation_batch_001_COMPLETED.json': 'cc86ccca9688ae7f86bdc584c823075e5099a9c9d6bd42203508cc18952d6932',
}
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):
    return json.loads(path.read_text())
started, cpu = time.perf_counter_ns(), time.process_time_ns()
for name, expected in EXPECTED.items():
    assert sha(RUN / name) == expected, name
review_path = RUN.parent / 'review_confirmation_registered_001/REVIEW.json'
assert sha(review_path) == 'ef2ef939432eaa457b97def830f8719030e5050afa79457e4c663d33e5f977f2'
assert read(review_path)['passed']
ledger = read(RUN / 'execution/CONFIRMATION_BATCH_COMPLETED.json')
outer = read(RUN / 'execution/confirmation_batch_001_COMPLETED.json')
results = read(RUN / 'RESULTS.json')
assert outer['returncode'] == 0 and outer['full_invocation_scope']
assert ledger['full_batch_wall_ns'] == outer['wall_ns']
assert ledger['full_invocation_children_user_seconds'] == outer['children_user_seconds']
assert ledger['full_invocation_children_system_seconds'] == outer['children_system_seconds']
assert ledger['full_invocation_children_cpu_seconds'] == outer['children_user_seconds'] + outer['children_system_seconds']
assert ledger['failed_scopes'] == ledger['scope_reruns'] == ledger['scope_replacements'] == 0
seen, totals, sums = set(), {}, []
pair_count = groups = mismatches = structural = action_mismatches = 0
maximum = Fraction(0)
by_coordinate = [Fraction(0), Fraction(0)]
location = None
output_difference = probability_difference = 0.0
for scope in ledger['scopes']:
    seed, domain = scope['seed'], scope['domain']
    assert (seed, domain) not in seen
    seen.add((seed, domain))
    directory = RUN / 'confirmation' / f'seed_{seed}' / domain
    wrapper_path = RUN / scope['full_invocation_receipt']
    assert sha(wrapper_path) == scope['full_invocation_receipt_sha256']
    wrapper = read(wrapper_path)
    assert wrapper['returncode'] == scope['returncode'] == 0
    assert wrapper['wall_ns'] == scope['full_wall_ns']
    assert math.isclose(wrapper['children_user_seconds'] + wrapper['children_system_seconds'], scope['full_child_cpu_seconds'], rel_tol=0, abs_tol=1e-10)
    for file, field in [('RUN_COMPLETED.json','run_completed_sha256'),('WORKER.json','worker_receipt_sha256'),('JOB.json','job_sha256')]:
        assert sha(directory / file) == scope[field]
    worker, summary = read(directory / 'WORKER.json'), read(directory / 'SUMMARY.json')
    assert scope['independent_queries'] == summary['independent_trajectories'] == 128
    assert scope['executions'] == worker['executions'] == 1152
    assert scope['broker_complete'] == worker['broker']['complete'] is True
    for key, actual in [('archive_bytes',worker['archive']['bytes']),('verified_archive_members',worker['archive']['verified_files']),('native_requests',worker['native']['requests']),('native_sparse_ticks',worker['native']['ticks']),('native_roundtrip_ns',worker['native']['roundtrip_ns'])]:
        assert scope[key] == actual
    for key in ('independent_queries','executions','archive_bytes','verified_archive_members','native_requests','native_sparse_ticks','native_roundtrip_ns','full_wall_ns'):
        totals[key] = totals.get(key,0) + scope[key]
    sums.append(scope['full_child_cpu_seconds'])
    with gzip.open(directory / 'ROWS.json.gz','rt') as stream:
        rows=json.load(stream)
    left={r['index']:r for r in rows if r['arm']=='gaussian'}
    right={r['index']:r for r in rows if r['arm']=='probit'}
    assert set(left)==set(right)==set(range(128))
    for index in range(128):
        a,b=left[index],right[index]
        pair_count+=1
        action_mismatches += a['actions'] != b['actions']
        assert len(a['stages'])==len(b['stages'])
        output_difference=max(output_difference,abs(a['delivered']-b['delivered']))
        for stage,(x,y) in enumerate(zip(a['stages'],b['stages']),1):
            dl,dr=x['runtime']['decoder'],y['runtime']['decoder']
            groups+=1
            structural += any(dl[k]!=dr[k] for k in ('components','sequence','time'))
            mismatches += any(dl[k]!=dr[k] for k in ('components','values','sequence','time'))
            assert dl['components']==dr['components']==1 and len(dl['values'])==len(dr['values'])==2
            for coordinate,(u,v) in enumerate(zip(dl['values'],dr['values'])):
                difference=abs(Fraction.from_float(u)-Fraction.from_float(v))
                by_coordinate[coordinate]=max(by_coordinate[coordinate],difference)
                if difference>maximum:
                    maximum=difference
                    location={'seed':seed,'domain':domain,'index':index,'stage':stage,'coordinate':('mean','log_variance')[coordinate],'gaussian_value':u,'probit_value':v,'gaussian_hex':u.hex(),'probit_hex':v.hex()}
            probability_difference=max(probability_difference,max(abs(p-q) for p,q in zip(x['runtime']['law']['probabilities'],y['runtime']['law']['probabilities'])))
assert len(seen)==15
mapping={'independent_queries_across_seed_domain_scopes':'independent_queries','actual_arm_executions':'executions','execution_archive_bytes':'archive_bytes','verified_archive_members':'verified_archive_members','actual_native_requests':'native_requests','actual_native_sparse_ticks':'native_sparse_ticks','native_roundtrip_ns_nested_component':'native_roundtrip_ns'}
for name,key in mapping.items(): assert ledger['counts'][name]==totals[key]
assert ledger['counts']['completed_scopes']==15
assert ledger['sum_scope_wall_ns_not_elapsed_time']==totals['full_wall_ns']
assert math.isclose(ledger['sum_scope_children_cpu_seconds_nested_subset'],math.fsum(sums),rel_tol=0,abs_tol=1e-9)
expected=results['equivalence']['gaussian-probit']
assert expected['decoded_coordinate_mismatches']==mismatches
assert expected['action_mismatches']==action_mismatches==0
assert expected['maximum_output_error']==output_difference==0
assert expected['maximum_probability_error']==probability_difference==0
for name,value in EXPECTED.items(): assert sha(RUN/name)==value
report={'schema':'hepta.round6.post-audit-descriptive-diagnostics.v1','passed':True,'source_sha256':sha(Path(__file__)),'inputs_sha256':EXPECTED,'full_independent_review_sha256':sha(review_path),'scientific_results_or_gates_changed':False,'new_training_or_experiment_performed':False,'descriptive_only':True,'operational_ledger':{'all_15_scope_receipts_counts_and_costs_independently_bound':True,'full_batch_wall_ns':outer['wall_ns'],'full_batch_user_cpu_seconds':outer['children_user_seconds'],'full_batch_system_cpu_seconds':outer['children_system_seconds'],'nested_scope_wall_sum_not_elapsed_time':totals['full_wall_ns'],'nested_costs_must_not_be_added_to_outer_cost':True,'counts':ledger['counts']},'gaussian_probit':{'paired_trajectories':pair_count,'compared_acquired_coordinate_groups':groups,'nonidentical_coordinate_groups':mismatches,'component_sequence_time_mismatches':structural,'maximum_absolute_coordinate_difference':float(maximum),'maximum_absolute_coordinate_difference_exact_fraction':str(maximum),'maximum_by_coordinate':dict(zip(('mean','log_variance'),map(float,by_coordinate))),'maximum_location':location,'action_mismatches':action_mismatches,'maximum_delivered_output_difference':output_difference,'maximum_released_probability_difference':probability_difference,'interpretation':'Outputs and actions agree on all registered executions; FP64 decoder coordinates are not bitwise identical. The coordinate diagnostic is descriptive, not a new scientific gate.'},'wall_ns':time.perf_counter_ns()-started,'parent_cpu_ns':time.process_time_ns()-cpu,'native_energy':None,'financial_cost':None}
with (OUTPUT/'DIAGNOSTICS.json').open('x') as stream:
    json.dump(report,stream,indent=2,sort_keys=True);stream.write('\n')
print(json.dumps({'passed':True,'coordinate_groups':groups,'nonidentical_groups':mismatches,'maximum_absolute_coordinate_difference':float(maximum),'diagnostics_sha256':sha(OUTPUT/'DIAGNOSTICS.json')}))
