"""Inventory the untouched infrastructure-interrupted V8 grid, without retries."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path


def sha(path):
    result=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):result.update(block)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def record(workspace, output):
    workspace,output=map(Path,(workspace,output))
    root=workspace/"pft-development-v8/grid"
    log=workspace/"pft-development-v8/grid.log"
    assert not output.exists() and not (root/"development_seal.json").exists()
    pins=read(workspace/"pft-audit-v8-development/pins.json")
    plan=read(root/"protocol.json")
    source=read(root/"executed_source.json")
    canonical=lambda value:json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    assert sha(root/"protocol.json")==pins["protocol_sha256"]
    assert len(source)==117 and hashlib.sha256(canonical(source)).hexdigest()==pins["source_sha256"]
    for name,value in source.items():assert sha(workspace/"hepta-repo-v8/qa/stem-bakeoff"/name)==value
    files={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)}
        for p in sorted(root.rglob('*')) if p.is_file()}
    expected=[]
    for index in range(12):
        for ordinal,(v,t,h,s) in enumerate(product(plan['versions'],plan['tasks'],plan['head_modes'],plan['seeds'])):
            policies=plan['primary_policies'];shift=(index+ordinal)%4
            expected.extend(f'config{index:02d}/{v}-{t}-seed{s}-{h}/{policy}'
                for policy in policies[shift:]+policies[:shift])
    complete,invalid=[],[]
    for slot in expected:
        path=root/slot/'result.json'
        if not path.exists():continue
        try:row=read(path)
        except (ValueError,OSError) as error:
            invalid.append({'slot':slot,'bytes':path.stat().st_size,'error':str(error)})
            continue
        for filename,key in [('policy-record.json.gz','policy_record'),('trace.json.gz','trace_file'),('controller-checkpoints.json.gz','controller_file')]:
            assert sha(path.parent/filename)==row[key]['sha256']
        complete.append({'slot':slot,**{k:row[k] for k in ('policy','status','completed_steps','cpu_ns','wall_ns','error','audit_passed','future_mean_nll','old_mean_difference')},
            'original_result_sha256':sha(path),'independent_audit_cpu_ns':row['audit']['cpu_ns'],
            'scoring_cpu_ns':row['scoring']['cpu_ns']})
    assert [r['slot'] for r in complete]==expected[:len(complete)]
    assert len(complete)==46 and len(invalid)==1 and invalid[0]['slot']==expected[46]
    assert 'OSError: [Errno 28] No space left on device' in log.read_text()
    costs={'policy_call_cpu_ns':sum(r['cpu_ns'] for r in complete),
        'independent_audit_cpu_ns':sum(r['independent_audit_cpu_ns'] for r in complete),
        'scoring_cpu_ns':sum(r['scoring_cpu_ns'] for r in complete)}
    result={'schema':'hepta.cell-field-grid-infrastructure-interruption.v8','recorded_at':datetime.now(timezone.utc).isoformat(),
        'process_exit_code':1,'cause':'infrastructure_disk_full','original_directory':str(root),'completed':False,
        'registered_outputs':1152,'complete_result_records':len(complete),'invalid_result_records':invalid,
        'status_counts':dict(Counter(r['status'] for r in complete)),'complete_rows':complete,
        'retained_files':files,'file_count':len(files),'retained_bytes':sum(v['bytes'] for v in files.values()),
        'log_sha256':sha(log),'log_bytes':log.stat().st_size,'protocol_sha256':pins['protocol_sha256'],
        'executed_source_sha256':pins['source_sha256'],'execution_source_commit':pins['source_commit'],'source_files':117,
        'recoverable_disjoint_cpu_lower_bounds':costs,'recoverable_cpu_lower_bound_ns':sum(costs.values()),
        'whole_attempt_cpu_ns':None,'whole_attempt_cost_exact_known':False,
        'cost_scope':'46 complete execute calls plus their independent audit and scoring regions only. Interrupted47th execution, shared preparation, and unrecorded I/O cost unknown; never treat this lower bound as complete cost.',
        'partial_attempt_modified_or_replaced':False,'retry_started':False,'new_optimizer_or_solver_calls':0,
        'scientific_acceptance':False,'recorder_sha256':sha(__file__)}
    output.write_bytes(canonical(result)+b'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('workspace','output'):parser.add_argument('--'+key,required=True)
    r=record(**vars(parser.parse_args()))
    print(json.dumps({k:r[k] for k in ('complete_result_records','status_counts','file_count','retained_bytes','recoverable_disjoint_cpu_lower_bounds')}))
