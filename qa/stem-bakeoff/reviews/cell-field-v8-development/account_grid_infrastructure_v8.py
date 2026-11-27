"""Account for the original partial grid, full retry and same-process suspension.

No model/optimizer/control execution. Every shared original case is compared to
the full retry, with timings kept separately and never selected for favorability.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def sha(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):result.update(block)
    return result.hexdigest()


def read(path):
    path=Path(path)
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes())


def account(workspace,grid,audit,output):
    workspace,grid,audit,output=map(Path,(workspace,grid,audit,output))
    directory=workspace/'pft-development-v8'
    assert not output.exists() and grid not in output.parents
    previous=directory/'grid'
    inventory_path=directory/'grid-attempt1-interruption-approved-exec.json'
    inventory=read(inventory_path)
    files={p.relative_to(previous).as_posix():p for p in previous.rglob('*') if p.is_file()}
    assert set(files)==set(inventory['retained_files'])
    for name,path in files.items():
        pin=inventory['retained_files'][name]
        assert path.stat().st_size==pin['bytes'] and sha(path)==pin['sha256'],name
    declaration=read(directory/'grid-retry-declaration.json')
    runtime=read(directory/'grid-r2-runtime-execution.json')
    pause=read(directory/'grid-r2-pause.json')
    resume=read(directory/'grid-r2-resume.json')
    probe=read(directory/'grid-r2-capacity-probe.json')
    verified,run=read(audit),read(grid/'run.json')
    assert verified['status']=='PASS' and verified['primary_records']==1152
    assert verified['development_seal_sha256']==sha(grid/'development_seal.json')
    assert declaration['original_inventory_sha256']==sha(inventory_path)
    assert declaration['original_log_sha256']==inventory['log_sha256']==sha(directory/'grid.log')
    assert declaration['runtime_receipt_sha256']==sha(directory/'grid-r2-runtime-execution.json')
    assert declaration['all_registered_cases_repeated'] and not declaration['case_subset_selection']
    assert declaration['protocol_sha256']==run['protocol_sha256']==verified['protocol_sha256']
    assert declaration['executed_source_sha256']==run['executed_source_sha256']==verified['executed_source_sha256']
    assert runtime['runtime_execution']=='approved_escalated_local_research'
    assert pause['matched_pids']==[resume['pid']] and pause['signal']=='SIGSTOP' and resume['signal']=='SIGCONT'
    assert resume['pause_receipt_sha256']==sha(directory/'grid-r2-pause.json')
    assert resume['capacity_probe_sha256']==sha(directory/'grid-r2-capacity-probe.json')
    assert probe['status']=='PASS' and probe['fsync_passed'] and probe['write_bytes']==1<<20
    assert resume['monotonic_ns']-pause['monotonic_ns']==resume['pause_interval_ns']
    pairs=[]
    for original in inventory['complete_rows']:
        slot=original['slot'];old_dir=previous/slot;new_dir=grid/slot
        old,new=read(old_dir/'result.json'),read(new_dir/'result.json')
        with np.load(old_dir/'compact.npz',allow_pickle=False) as a,np.load(new_dir/'compact.npz',allow_pickle=False) as b:
            assert set(a.files)==set(b.files)=={'actions','terminal_vector','future_losses','old_differences'}
            differences={name:{'same_shape':a[name].shape==b[name].shape,
                'bit_equal':a[name].shape==b[name].shape and np.array_equal(a[name],b[name]),
                'maximum_absolute_difference':float(np.max(np.abs(a[name]-b[name]),initial=0.))
                    if a[name].shape==b[name].shape else None} for name in a.files}
        ta,tb=read(old_dir/'trace.json.gz'),read(new_dir/'trace.json.gz')
        pairs.append({'slot':slot,'original_status':old['status'],'retry_status':new['status'],
            'original_completed_steps':old['completed_steps'],'retry_completed_steps':new['completed_steps'],
            'arrays':differences,'receipts_equal':ta['receipts']==tb['receipts'],
            'complete_state_hashes_equal':ta['state_sha256']==tb['state_sha256'],
            'original_cpu_ns':old['cpu_ns'],'retry_cpu_ns':new['cpu_ns'],
            'original_wall_ns':old['wall_ns'],'retry_wall_ns':new['wall_ns']})
    assert len(pairs)==46
    original_lower=sum(inventory['recoverable_disjoint_cpu_lower_bounds'].values())
    assert original_lower==inventory['recoverable_cpu_lower_bound_ns']==57251806899
    result={'schema':'hepta.v8-grid-infrastructure-and-paired-retry-accounting','status':'PASS',
        'scope':'All existing evidence identities and arithmetic verified. Pair changes, if any, are reported rather than omitted. No controller/solver/model execution.',
        'source_sha256':sha(__file__),'independent_full_retry_audit_sha256':sha(audit),
        'complete_retry_seal_sha256':sha(grid/'development_seal.json'),
        'bound_receipts':{name:sha(directory/name) for name in ('grid-attempt1-interruption-approved-exec.json',
            'grid-retry-declaration.json','grid-r2-runtime-execution.json','grid-r2-pause.json',
            'grid-r2-capacity-probe.json','grid-r2-resume.json')},
        'original_complete_outputs':46,'original_status_counts':inventory['status_counts'],
        'original_partial_output':inventory['invalid_result_records'],
        'original_retained_files':inventory['file_count'],'original_retained_bytes':inventory['retained_bytes'],
        'original_recoverable_disjoint_cpu_lower_bounds':inventory['recoverable_disjoint_cpu_lower_bounds'],
        'original_cost_exact_known':False,'original_unknown_costs':declaration['original_unknown_costs'],
        'retry_producer_recorded_cpu_interval_ns':run['cpu_ns'],
        'retry_producer_recorded_wall_interval_ns':run['wall_ns'],
        'producer_recorded_cpu_lower_bound_across_attempts_ns':run['cpu_ns']+original_lower,
        'aggregate_cost_exact_known':False,
        'recorded_interval_scope':'Retry producer interval ends before final run.json/seal writes; first partial attempt omits interrupted47th, shared preparation and unrecorded IO. Post-run audits are separately charged.',
        'independent_full_retry_audit_cpu_ns':verified['cpu_ns'],
        'same_process_suspension_ns':resume['pause_interval_ns'],
        'policy_cpu_adjustments_ns':0,'policy_or_run_wall_adjustments_ns':0,
        'pause_wall_scope':'Original wall measurements include suspension and remain unchanged; CPU clocks do not accrue while SIGSTOPped.',
        'shared_original_case_count':46,
        'shared_status_or_step_changes':sum((r['original_status'],r['original_completed_steps'])!=(r['retry_status'],r['retry_completed_steps']) for r in pairs),
        'shared_array_changes':sum(not all(v['bit_equal'] for v in r['arrays'].values()) for r in pairs),
        'shared_receipt_changes':sum(not r['receipts_equal'] for r in pairs),
        'shared_state_hash_changes':sum(not r['complete_state_hashes_equal'] for r in pairs),
        'all46_pairs':pairs,'new_confirmation_selected':False,'scientific_acceptance':False}
    output.write_bytes(canonical(result)+b'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('workspace','grid','audit','output'):parser.add_argument('--'+key,required=True)
    result=account(**vars(parser.parse_args()))
    print(json.dumps({k:result[k] for k in ('status','shared_status_or_step_changes','shared_array_changes','shared_receipt_changes','same_process_suspension_ns')}))
