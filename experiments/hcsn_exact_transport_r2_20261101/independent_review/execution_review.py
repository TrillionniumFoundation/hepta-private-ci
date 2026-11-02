"""Independent registered-output, timing, cold-use, cost and projection review.

No candidate model, scoring, campaign or analysis module is imported.
"""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def load(path): return json.loads(Path(path).read_text())

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def source_check(mapping):
    for path,digest in mapping.items(): assert sha(ROOT/path)==digest, path

def close(actual,expected):
    if actual is None or expected is None: assert actual is expected
    else: assert np.allclose(actual,expected,rtol=1e-10,atol=1e-12), (actual,expected)

def speed():
    lane=ROOT/'experiments/hcsn_exact_transport_r2_20261101'
    paths=sorted(lane.glob('results/confirmation*/SUMMARY.json'))
    if not paths:return dict(status='pending_confirmation')
    path=paths[-1];s=load(path);p=load(lane/'PROTOCOL.json');f=load(lane/'CANDIDATE_FREEZE.json')
    source_check(s['source']);assert s['source']==f['source'] and s['source_unchanged']
    assert s['phase']=='confirmation' and len(s['rows'])==20
    started=load(path.parent/'START_IDENTITY.json');remote=load(lane/'REMOTE_FREEZE_BEFORE_CONFIRMATION.json')
    assert started['source']==s['source'] and started['candidate_freeze_sha256']==sha(lane/'CANDIDATE_FREEZE.json')==remote['candidate_freeze_sha256']
    assert remote['recorded_unix_ns']<started['started_unix_ns'] and not remote['confirmation_opened']
    blob=(lane/'CANDIDATE_FREEZE.json').read_bytes()
    assert hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest()==remote['candidate_freeze_remote_blob']
    selected=f['selected_backend']
    for task,digest in f['checkpoints'].items():
        assert sha(ROOT/'experiments/hcsn_propagation_perf_20261101/checkpoints'/f'{task}_flow.pt')==digest
        tests=[r for r in s['checks'] if r['task']==task and r['backend']==selected]
        assert len(tests)==p['engineering_checks_per_task_backend']+p['numerical_workloads_per_task_backend']
        assert len({r['name'] for r in tests})==len(tests)
        completion=[r for r in s['construction'] if r['task']==task and r['backend']==selected and r.get('stage')=='engineering_complete']
        assert len(completion)==1 and completion[0]['checks']==p['engineering_checks_per_task_backend'] and completion[0]['passed']
    assert all(r['passed'] for r in s['checks']) and all(r['passed'] for r in s['construction'])
    for row in s['rows']:
        med={name:float(np.median(values)) for name,values in row['raw_seconds'].items()}
        assert all(len(v)==p['confirmation_repeats'] for v in row['raw_seconds'].values())
        for name,value in med.items():close(row['median_seconds'][name],value)
        for backend,value in row['dense_over_adapter'].items():close(value,med['dense']/med[backend])
    minimum=min(row['dense_over_adapter'][selected] for row in s['rows'])
    c=next(r for r in s['candidates'] if r['backend']==selected)
    assert c['numerical_eligible'];close(c['minimum_ratio'],minimum);assert c['stable_speed_gate']==(minimum>=1.05)
    cold=dict(status='pending')
    if (lane/'results/cold001/SUMMARY.json').exists():
        cold_out=lane/'results/cold001';cs=load(cold_out/'SUMMARY.json');source_check(cs['source_sha256'])
        assert cs['source_freeze_sha256']==sha(lane/'CANDIDATE_FREEZE.json') and cs['process_count']==40 and len(cs['rows'])==20
        processes=load(cold_out/'PROCESS_RECORDS.json');assert len(processes)==40 and all(r['returncode']==0 for r in processes)
        for row in cs['rows']:
            assert row['passed'] and row['input_identical'] and row['argmax_identical']
            dense,candidate=row['dense'],row['candidate'];assert dense['kind']=='dense' and candidate['kind']=='integrated'
            cold_raw={}
            for kind,record in [('dense',dense),('integrated',candidate)]:
                source_check(record['source_sha256']);assert record['checkpoint_sha256']==f['checkpoints'][row['task']]
                assert len(record['calls'])==4 and [r['index'] for r in record['calls']]==list(range(4))
                name=f"{row['task']}_B{row['batch']}_{row['condition']}_{int(row['backward'])}_{kind}.npz"
                assert sha(cold_out/name)==record['raw_sha256']
                with np.load(cold_out/name,allow_pickle=False) as z:cold_raw[kind]={k:z[k] for k in z.files}
            assert dense['input_sha256']==candidate['input_sha256']
            assert np.array_equal(cold_raw['dense']['labels'],cold_raw['integrated']['labels'])
            cold_error=float(np.max(np.abs(cold_raw['dense']['logits']-cold_raw['integrated']['logits'])))
            close(row['max_cold_output_error'],cold_error);assert cold_error<=p['max_output_absolute_error']
            scored=cold_raw['dense']['labels']>=0
            assert np.array_equal(cold_raw['dense']['logits'].argmax(-1)[:,scored],cold_raw['integrated']['logits'].argmax(-1)[:,scored])
            assert candidate['construction']['scripted_cache_empty_before_construction'] and candidate['construction']['compiled_here']
        assert cs['passed']
        cold=dict(status='verified',fresh_processes=40,paired_workloads=20,summary_sha256=sha(cold_out/'SUMMARY.json'),
                  scope='Four first-use calls per fresh process; compilation/import/setup retained; no steady-speed gate substitution')
    cost_review=dict(status='pending')
    if (lane/'COST_LEDGER.json').exists() and (lane/'COLD_AMORTIZATION.json').exists():
        ledger=load(lane/'COST_LEDGER.json');projection=load(lane/'COLD_AMORTIZATION.json');total=0.;intervals=[]
        for item in ledger['outer_receipts']:
            assert sha(ROOT/item['path'])==item['sha256'];receipt=load(ROOT/item['path'])
            close(item['cpu_seconds'],receipt['total_cpu_seconds']);total+=receipt['total_cpu_seconds']
            assert item['returncode']==receipt['returncode']
            intervals.append((datetime.fromisoformat(receipt['started_utc']),datetime.fromisoformat(receipt['finished_utc'])))
        ordered=sorted(intervals);assert all(a[1]<=b[0] for a,b in zip(ordered,ordered[1:]))
        close(ledger['total_measured_non_nested_child_cpu_seconds'],total)
        assert ledger['nested_worker_cpu_not_added_again'] and ledger['complete_lifecycle_cpu_seconds'] is None
        workers=list((lane/'results/cold001').glob('*.worker.receipt.json'))
        assert len(workers)==40
        worker_cpu=sum(load(path)['total_cpu_seconds'] for path in workers)
        close(ledger['nested_cold_worker_cpu_seconds'],worker_cpu)
        assert len(projection['rows'])==20 and not projection['complete_training_or_adoption_cost_proved']
        for row,cold_row in zip(projection['rows'],cs['rows'],strict=True):
            dense,candidate=cold_row['dense'],cold_row['candidate']
            dense_prefix=dense['construction']['wall_seconds']+sum(call['wall_seconds'] for call in dense['calls'])
            candidate_prefix=candidate['construction']['wall_seconds']+sum(call['wall_seconds'] for call in candidate['calls'])
            saved=row['steady_dense_wall_median_seconds']-row['steady_candidate_wall_median_seconds']
            expected_break=None if saved<=0 else 4+max(0,math.ceil((candidate_prefix-dense_prefix)/saved))
            assert row['projected_sustained_break_even_after_four_calls']==expected_break
            assert row['steady_cpu_per_call_seconds'] is None and row['isolated_lazy_profiling_cpu_seconds'] is None
            for point in row['conditional_projections']:
                calls=point['calls']
                if calls<=4:
                    a=dense['construction']['wall_seconds']+sum(call['wall_seconds'] for call in dense['calls'][:calls])
                    b=candidate['construction']['wall_seconds']+sum(call['wall_seconds'] for call in candidate['calls'][:calls])
                else:
                    a=dense_prefix+(calls-4)*row['steady_dense_wall_median_seconds']
                    b=candidate_prefix+(calls-4)*row['steady_candidate_wall_median_seconds']
                close(point['dense_wall_seconds'],a);close(point['candidate_wall_seconds'],b)
                close(point['candidate_minus_dense_wall_seconds'],b-a)
                assert point['observed_invocation_prefix_only']==(calls<=4)
        cost_review=dict(status='verified',outer_receipts=len(ledger['outer_receipts']),measured_non_nested_cpu_seconds=total,
                         nested_cold_worker_cpu_seconds=worker_cpu,projection_rows=20,
                         lifecycle_complete=False,ledger_sha256=sha(lane/'COST_LEDGER.json'),projection_sha256=sha(lane/'COLD_AMORTIZATION.json'))
    return dict(status='verified',record_checks=20,numerical_engineering_records=len(s['checks']),
                selected_backend=selected,minimum_speed_ratio=minimum,local_same_core_speed_gate=c['stable_speed_gate'],
                timing_rows_above_five_percent=sum(row['dense_over_adapter'][selected]>=1.05 for row in s['rows']),
                max_output_error=max(r.get('max_output_error',0) for r in s['checks']),
                max_parameter_gradient_error=max(r.get('max_parameter_gradient_error',0) for r in s['checks']),
                remote_freeze_before_confirmation=True,source_commit=remote['source_commit'],
                cold_first_use=cold,
                cost_and_projection=cost_review,
                summary_sha256=sha(path),limits=['Same trained Flow weights only; no strong ordinary-core speed claim',
                    'Final integrated script retains original separate moment transport and per-time decoder order/shapes',
                    'Compile/warmup/startup costs remain additional to steady timing',
                    'No GPU, joules, production tail latency or full-training economic qualification'])

def main():
    result=speed()
    if result['status']!='verified' or result['cold_first_use']['status']!='verified' or result['cost_and_projection']['status']!='verified':
        raise RuntimeError('Complete final evidence required: '+str(result))
    result.update(schema='hcsn.exact-transport-r2.independent-execution-review.v1',audit_source_sha256=sha(__file__),review_cpu_seconds=None)
    with (HERE/'EXECUTION_REVIEW.json').open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(status=result['status'],main_timing_records=result['record_checks'],engineering_records=result['numerical_engineering_records'],cold_processes=result['cold_first_use']['fresh_processes'],local_same_core_speed_gate=result['local_same_core_speed_gate']),sort_keys=True))

if __name__=='__main__':main()
