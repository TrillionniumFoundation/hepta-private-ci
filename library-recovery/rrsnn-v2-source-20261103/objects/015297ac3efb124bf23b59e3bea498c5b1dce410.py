"""Resource sidecars around the frozen benchmark's isolated row processes.

`snapshot` is read-only except for its JSON output and runs no benchmark.
`run` is for the coordinated post-training/evaluation measurement stage only.
It invokes benchmark.py unchanged with the frozen 25-sequence/200-tick protocol,
and brackets every child process with cgroup and filesystem observations.

Cgroup event deltas identify pressure during a shared observation window, not
proof that the benchmark process caused that pressure. Raw latency samples are
never removed or trimmed, including when a row is flagged as pressure-affected.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
CGROUP=Path('/sys/fs/cgroup')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def counters(text):
    result={}
    for line in text.splitlines():
        fields=line.split()
        if len(fields)==2:
            try:result[fields[0]]=int(fields[1])
            except ValueError:result[fields[0]]=fields[1]
    return result


def snapshot():
    errors={}
    memory={}
    for name in ['memory.current','memory.max','memory.high','memory.peak',
                 'memory.swap.current','memory.swap.max','memory.events',
                 'memory.events.local','memory.stat','memory.pressure']:
        path=CGROUP/name
        try:
            raw=path.read_text().strip()
            if name in ['memory.events','memory.events.local','memory.stat']:
                memory[name]=counters(raw)
            elif name=='memory.pressure':
                memory[name]=raw
            else:
                memory[name]=int(raw) if raw!='max' else 'max'
        except (OSError,ValueError) as error:
            memory[name]=None;errors[name]=str(error)
    filesystems={}
    for path in [ROOT,Path('/tmp')]:
        stat=os.statvfs(path)
        unit=stat.f_frsize
        filesystems[str(path)]={
            'device_id':os.stat(path).st_dev,
            'total_bytes':stat.f_blocks*unit,
            'free_bytes':stat.f_bfree*unit,
            'available_to_unprivileged_bytes':stat.f_bavail*unit,
            'used_bytes':(stat.f_blocks-stat.f_bfree)*unit,
            'inodes_total':stat.f_files,'inodes_available':stat.f_favail}
    return {'utc':datetime.now(timezone.utc).isoformat(),
            'monotonic_seconds':time.monotonic(),'cgroup_path':str(CGROUP),
            'memory':memory,'filesystems':filesystems,'read_errors':errors,
            'load_average':list(os.getloadavg())}


def summarize_window(before,after,returncode):
    a=before['memory'];b=after['memory']
    deltas={};counter_regressed=False
    for name in ['memory.events','memory.events.local']:
        left=a.get(name);right=b.get(name)
        if not isinstance(left,dict) or not isinstance(right,dict):
            deltas[name]=None;continue
        deltas[name]={key:right[key]-left[key] for key in left.keys()&right.keys()
                      if isinstance(left[key],int) and isinstance(right[key],int)}
        counter_regressed=counter_regressed or any(value<0 for value in deltas[name].values())
    events=deltas.get('memory.events')
    complete=isinstance(events,dict) and all(key in events for key in ['max','oom','oom_kill'])
    touched_limit=bool(complete and events['max']>0)
    throttled_high=bool(isinstance(events,dict) and events.get('high',0)>0)
    oom=bool(complete and (events['oom']>0 or events['oom_kill']>0))
    occupancy={}
    for key,values in [('before',a),('after',b)]:
        current=values.get('memory.current');limit=values.get('memory.max')
        occupancy[key]=(current/limit if isinstance(current,int) and isinstance(limit,int) and limit>0 else None)
    disk={}
    disk_exhausted=False
    for path in before['filesystems'].keys()&after['filesystems'].keys():
        old=before['filesystems'][path];new=after['filesystems'][path]
        old_free=old['available_to_unprivileged_bytes'];new_free=new['available_to_unprivileged_bytes']
        disk[path]={'available_before_bytes':old_free,'available_after_bytes':new_free,
                    'available_delta_bytes':new_free-old_free,
                    'same_device':old['device_id']==new['device_id']}
        disk_exhausted=disk_exhausted or old_free==0 or new_free==0
    if not complete or counter_regressed:
        condition='resource_counter_status_unknown'
    elif touched_limit or throttled_high or oom:
        condition='memory_pressure_observed_during_window'
    elif disk_exhausted:
        condition='disk_exhaustion_observed'
    else:
        condition='no_limit_events_observed_in_window'
    eligible=(returncode==0 and condition=='no_limit_events_observed_in_window')
    return {'condition':condition,'primary_resource_table_eligible':eligible,
            'child_returncode':returncode,'memory_event_deltas':deltas,
            'memory_hard_limit_events_increased':touched_limit,
            'memory_high_events_increased':throttled_high,
            'oom_events_increased':oom,'counter_regressed':counter_regressed,
            'memory_limit_fraction':occupancy,'disk_availability':disk,
            'qualification':'Shared-cgroup deltas cover child startup, warmup, timed ticks and shutdown; they do not isolate the benchmark as the cause or locate an event to an exact tick. No latency samples are trimmed.'}


def write_json(path,payload):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(payload,indent=2)+'\n')
    temporary.replace(path)


def retain_preexisting(path,archive):
    if not path.exists():return None
    identifier=digest(path)
    destination=archive/(path.stem+'_'+identifier[:16]+path.suffix)
    destination.parent.mkdir(parents=True,exist_ok=True)
    if not destination.exists():shutil.copy2(path,destination)
    return str(destination)


def run_rows(args):
    protocol=json.loads((ROOT/'benchmark_protocol.json').read_text())
    assert protocol['timed_sequences']==25 and protocol['primary_timed_tick_samples']==200
    assert protocol['warmup_sequences']==5 and protocol['cpu_affinity']==[7]
    destination=ROOT/'benchmark_results'
    observed=destination/'resource_observations'
    missing=[];records=[]
    for specification in args.runs:
        run_name,mode=specification.split(':',1)
        checkpoint=ROOT/args.group/run_name/f'seed_{args.seed}'/'model.pt'
        if not (checkpoint.exists() and checkpoint.with_name('training.json').exists()):
            missing.append(specification);continue
        for rows in args.sizes:
            key=f'{run_name}_{mode}_seed{args.seed}_b{rows}'
            output=destination/'runs'/f'{key}.json'
            sidecar=observed/f'{key}.json'
            expected={'checkpoint_sha256':digest(checkpoint),
                      'benchmark_sha256':digest(ROOT/'benchmark.py'),
                      'protocol_sha256':digest(ROOT/'benchmark_protocol.json')}
            if output.exists() and sidecar.exists() and not args.rerun:
                saved=json.loads(sidecar.read_text())
                if (saved.get('expected_sources')==expected and saved.get('row_sha256')==digest(output)
                    and saved.get('resource_window',{}).get('primary_resource_table_eligible')):
                    records.append(saved);continue
            old_row=retain_preexisting(output,observed/'retained_prior_attempts')
            old_sidecar=retain_preexisting(sidecar,observed/'retained_prior_attempts')
            command=[sys.executable,str(ROOT/'benchmark.py'),'--child','--run',run_name,
                     '--mode',mode,'--batch',str(rows),'--seed',str(args.seed),'--group',args.group,
                     '--repetitions','25','--warmups','5','--microbatch','-1',
                     '--cpu','7','--child-output',str(output)]
            log=observed/'logs'/f'{key}.log';log.parent.mkdir(parents=True,exist_ok=True)
            before=snapshot()
            start_record={'schema':'rrsnn.v2.benchmark-resource-window.v1','status':'child_starting',
                          'run_name':run_name,'mode':mode,'rows':rows,'seed':args.seed,
                          'expected_sources':expected,'before':before,
                          'prior_row_preserved_as':old_row,'prior_sidecar_preserved_as':old_sidecar,
                          'command':command,'child_log':str(log)}
            write_json(sidecar,start_record)
            print(json.dumps({'starting_observed_row':key,
                              'memory_current':before['memory'].get('memory.current'),
                              'disk_available':before['filesystems'][str(ROOT)]['available_to_unprivileged_bytes']}),flush=True)
            error=None;code=-1
            try:
                with log.open('w') as handle:
                    completed=subprocess.run(command,stdout=handle,stderr=subprocess.STDOUT,check=False)
                    code=completed.returncode
            except Exception as exception:
                error=repr(exception)
            after=snapshot()
            record={**start_record,'status':'child_finished','after':after,'execution_error':error,
                    'resource_window':summarize_window(before,after,code),
                    'row_sha256':digest(output) if output.exists() and code==0 else None,
                    'observer_sha256':digest(Path(__file__).resolve())}
            write_json(sidecar,record);records.append(record)
            print(json.dumps({'completed_observed_row':key,'returncode':code,
                              'resource_condition':record['resource_window']['condition'],
                              'memory_events_delta':record['resource_window']['memory_event_deltas']['memory.events']}),flush=True)
            build_summary(destination,records,missing,args)
            if code!=0:
                raise RuntimeError(f'Benchmark child failed; resource window and log retained at {sidecar}')
    build_summary(destination,records,missing,args)


def build_summary(destination,records,missing,args):
    results=[];observations=[]
    observation_dir=destination/'resource_observations'
    for sidecar in sorted(observation_dir.glob('*.json')):
        record=json.loads(sidecar.read_text())
        if record.get('status')!='child_finished':continue
        name=sidecar.name
        path=destination/'runs'/name
        if not path.exists() or record.get('row_sha256')!=digest(path):continue
        row=json.loads(path.read_text())
        row['resource_observation']={'path':str(sidecar),'sha256':digest(sidecar),
                                    **record['resource_window']}
        results.append(row);observations.append(record)
    write_json(destination/'scaling_results.json',{
        'schema':'rrsnn.v2.resource-observed-cost-matrix.v1','formal':True,
        'results':results,'primary_resource_results':[row for row in results
            if row['resource_observation']['primary_resource_table_eligible']],
        'pressure_or_unknown_rows':sum(not row['resource_observation']['primary_resource_table_eligible'] for row in results),
        'latest_requested_runs':args.runs,'latest_requested_sizes':args.sizes,
        'latest_missing_runs':missing,'observer_sha256':digest(Path(__file__).resolve()),
        'protocol_sha256':digest(ROOT/'benchmark_protocol.json'),
        'qualification':'All completed observed rows remain in results. Eligibility flags entire measurement windows; no individual latency outliers are removed.'})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    check=commands.add_parser('snapshot',help='Read resource state and write JSON; never runs a benchmark')
    check.add_argument('--output',type=Path,default=ROOT/'resource_observer_snapshot.json')
    run=commands.add_parser('run',help='Run only after the coordinated end of all training/evaluation')
    run.add_argument('--runs',nargs='+',default=['rr_density_sampled:ctmc','lif:standard',
                       'ctrnn:standard','ctrnn_matched:standard','ctrnn_matched_cpu:standard'])
    run.add_argument('--sizes',nargs='+',type=int,default=[64,256,1024,4096])
    run.add_argument('--seed',type=int,default=101);run.add_argument('--group',default='results')
    run.add_argument('--rerun',action='store_true')
    args=parser.parse_args()
    if args.command=='snapshot':
        payload=snapshot();write_json(args.output,payload)
        print(json.dumps({'snapshot':str(args.output),'memory_current':payload['memory']['memory.current'],
                          'memory_max':payload['memory']['memory.max'],
                          'disk_available':payload['filesystems'][str(ROOT)]['available_to_unprivileged_bytes']}))
    else:
        run_rows(args)


if __name__=='__main__':
    main()
