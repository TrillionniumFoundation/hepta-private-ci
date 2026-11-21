#!/usr/bin/env python3
"""Independent NumPy-only finite timing and archived-array audit; no models."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import time

START_CPU,START_WALL=time.process_time(),time.perf_counter()
ROOT=Path(__file__).resolve().parent; OUT=ROOT/'attempt001'
P=json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
resource.setrlimit(resource.RLIMIT_CPU,(P['budget']['reader_cpu_soft_seconds'],P['budget']['reader_cpu_soft_seconds']+1))
os.sched_setaffinity(0,set(P['cpu_affinity']))
import numpy as np


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(test,why):
    if not test: raise ValueError(why)
def close(a,b): return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
def write(path,v):
    with path.open('x') as f:
        json.dump(v,f,indent=2,allow_nan=False); f.write('\n')


def main():
    work=read(ROOT/'WORKLOAD_FROZEN.json'); raw=(OUT/'TIMINGS.jsonl').read_bytes()
    raw_lines=raw.splitlines(keepends=True); rows=[json.loads(b) for b in raw_lines]
    result=read(OUT/'RESULT.json'); seal=read(OUT/'CALIBRATION_SEAL.json'); choice=read(OUT/'RESEARCH_CHOICE_SEALED.json')
    costs=read(ROOT/'SUPERVISOR_COST.json'); prep=read(OUT/'PREPARATION.json')
    require(result['status']=='COMPLETE' and costs['completed'],'Scientific child incomplete')
    require(result['timings_sha256']==sha(OUT/'TIMINGS.jsonl'),'Timing digest changed')
    require(P['worklist_sha256']==sha(ROOT/'WORKLOAD_FROZEN.json'),'Worklist changed')
    for pin in P['pins']+P['runtime_pins']:
        path=Path(pin['path']); require(path.stat().st_size==pin['bytes'] and sha(path)==pin['sha256'],'Pinned bytes changed')
    require(len(rows)==len(work['rows'])==216,'Missing grouped timing rows')
    ncal=seal['calibration_rows']; require(ncal==72,'Calibration row count')
    require(hashlib.sha256(b''.join(raw_lines[:ncal])).hexdigest()==seal['timings_sha256'],'Calibration was not sealed prefix')
    require(choice['calibration_seal_sha256']==sha(OUT/'CALIBRATION_SEAL.json'),'Choice seal mismatch')
    require(choice['confirmation_calls_before_choice']==0,'Late choice')
    choice_sha=sha(OUT/'RESEARCH_CHOICE_SEALED.json')
    stage_zeros={}; group_zeros={'calibration':{},'confirmation':{}}
    groups={}; taskcounts={}; fullcoords=0; coldcoords=0; max_abs=0.; bitdiff=0
    for expected,r in zip(work['rows'],rows):
        require(all(r[k]==v for k,v in expected.items()),'Worklist order changed')
        require(len(r['call_records'])==r['calls']==4,'Group call count')
        if r['phase']=='confirmation':
            require(r['choice_sha256']==choice_sha and r['started_utc']>choice['sealed_utc'],'Confirmation preceded selection')
        key=(r['phase'],r['fit'],r['case'],r['implementation']); groups.setdefault(key,[]).append(r)
        key2=r['phase']+'/'+r['implementation']; taskcounts[key2]=taskcounts.get(key2,0)+r['calls']
        gz=group_zeros[r['phase']]; gz[r['implementation']]=gz.get(r['implementation'],0)+int(r['cpu_ns']==0)
        require(r['cpu_ns']>=0 and r['wall_ns']>0,'Invalid timing')
        for c in r['call_records']:
            for k,v in c['stages'].items():
                if k!='evidence_archive': stage_zeros[k]=stage_zeros.get(k,0)+int(v['cpu_ns']==0)
                require(v['cpu_ns']>=0 and v['wall_ns']>=0,'Invalid stage timing')
            require(c['full']['same_argmax'],'Class change')
            fullcoords+=c['full']['coordinates']; coldcoords+=c['cold']['coordinates']
            max_abs=max(max_abs,c['full']['max_abs'],c['cold']['max_abs'])
            bitdiff+=c['full']['bitwise_mismatches']+c['cold']['bitwise_mismatches']
    require(taskcounts=={'calibration/reference':144,'calibration/specialized':144,
                        'confirmation/reference':288,'confirmation/specialized':288},'Actual call count changed')
    require(result['counters']=={'reference_forward':432,'specialized_forward':432,
        'continuation_steps':864,'optimizer_steps':0,'checkpoint_writes':0,'full_tasks':864},'Unexpected scientific operation')
    env={}
    for item in seal['envelopes']:
        key=(item['fit'],item['case'],item['implementation']); env[key]=item
        r=groups[('calibration',)+key]; values=[x['cpu_ns']/1e9 for x in r]
        require(values==item['calibration_block_cpu_seconds'],'Calibration samples changed')
        require(close(.5*min(values),item['cpu_seconds_lower']) and close(2*max(values),item['cpu_seconds_upper']),'Envelope arithmetic')
    original_lower=sum(e['cpu_seconds_lower']*4 for e in env.values() if e['implementation']=='reference')
    candidate_calls_upper=sum(e['cpu_seconds_upper']*4 for e in env.values() if e['implementation']=='specialized')
    investment=(choice['preconfirmation_process_cpu_seconds']+choice['timeout_probe_cpu_seconds']+
                choice['supervisor_cpu_seconds_at_launch']+choice['post_analysis_cpu_reserve_seconds'])
    require(close(choice['complete_qualification_investment_cpu_seconds'],investment),'Hidden preparation cost')
    require(close(choice['original_confirmation_cpu_lower_prediction'],original_lower),'Original prediction arithmetic')
    require(close(choice['candidate_complete_cpu_upper_prediction'],investment+candidate_calls_upper),'Candidate prediction arithmetic')
    require(choice['decision']==('COMPILED' if investment+candidate_calls_upper<original_lower else 'KEEP_ORIGINAL'),'Choice rule changed')
    coverage=[]
    for key,e in env.items():
        rr=groups[('confirmation',)+key]; values=[x['cpu_ns']/1e9 for x in rr]
        coverage.append(dict(fit=key[0],case=key[1],implementation=key[2],
            predicted_block_lower_cpu_seconds=e['cpu_seconds_lower'],predicted_block_upper_cpu_seconds=e['cpu_seconds_upper'],
            actual_confirmation_block_cpu_seconds=values,actual_total_cpu_seconds=sum(values),
            blocks_below=sum(x<e['cpu_seconds_lower'] for x in values),
            blocks_above=sum(x>e['cpu_seconds_upper'] for x in values),
            aggregate_within_prediction=(4*e['cpu_seconds_lower']<=sum(values)<=4*e['cpu_seconds_upper'])))
    # Read new archived complete states without importing the model or Torch.
    old=Path(P['old_root']); archives=[]; archivecoords=0; archivebitdiff=0; archivemax=0.
    for fit in P['fits']:
        for case in P['cases']:
            for implementation in ('reference','specialized'):
                name=fit+'__'+case+'__'+implementation
                metadata=read(OUT/'arrays'/(name+'.json'))
                with np.load(OUT/'arrays'/(name+'.npz'),allow_pickle=False) as fresh:
                    for kind in ('full','cold'):
                        source=old/'attempt001'/fit/(case+'-'+kind)
                        goldenmeta=read(Path(str(source)+'.json'))['metadata']
                        require(metadata[kind+'_metadata']==goldenmeta,'Archived metadata changed')
                        with np.load(str(source)+'.npz',allow_pickle=False) as z:
                            keys=[k for k in z.files if k.startswith('reference::')]
                            require({k.removeprefix('reference::') for k in keys}==
                                {k.removeprefix(kind+'::') for k in fresh.files if k.startswith(kind+'::')},'Archived tensor key mismatch')
                            c,bd,mx=0,0,0.
                            for k in keys:
                                b=z[k]; a=fresh[kind+'::'+k.removeprefix('reference::')]
                                require(a.shape==b.shape and a.dtype==b.dtype and np.isfinite(a).all(),'Archived array contract')
                                d=np.abs(a-b)
                                require(np.all(d<=P['abs_tolerance']+P['rel_tolerance']*np.abs(b)),'Archived numerical failure')
                                c+=a.size; bd+=int(np.count_nonzero(a.view(np.uint64)!=b.view(np.uint64))); mx=max(mx,float(d.max(initial=0)))
                            archivecoords+=c; archivebitdiff+=bd; archivemax=max(archivemax,mx)
                            archives.append(dict(fit=fit,case=case,implementation=implementation,kind=kind,coordinates=c,max_abs=mx,bitwise_mismatches=bd))
    summaries=[]
    for phase in ('calibration','confirmation'):
        for case in P['cases']:
            r=[x for x in rows if x['phase']==phase and x['case']==case]
            a=sum(x['cpu_ns'] for x in r if x['implementation']=='reference')/1e9
            b=sum(x['cpu_ns'] for x in r if x['implementation']=='specialized')/1e9
            aw=sum(x['wall_ns'] for x in r if x['implementation']=='reference')/1e9
            bw=sum(x['wall_ns'] for x in r if x['implementation']=='specialized')/1e9
            summaries.append(dict(phase=phase,case=case,calls_per_implementation=sum(x['calls'] for x in r)//2,
                reference_cpu_seconds=a,specialized_cpu_seconds=b,reference_wall_seconds=aw,specialized_wall_seconds=bw,
                observed_complete_task_cpu_ratio=a/b if b>0 else None,observed_complete_task_wall_ratio=aw/bw if bw>0 else None))
    refconf=sum(r['cpu_ns'] for r in rows if r['phase']=='confirmation' and r['implementation']=='reference')/1e9
    optconf=sum(r['cpu_ns'] for r in rows if r['phase']=='confirmation' and r['implementation']=='specialized')/1e9
    rawsum=sum(r['cpu_ns'] for r in rows)/1e9
    observed_task_saving=refconf-optconf
    bound_gap=original_lower-candidate_calls_upper
    memory=[]
    for fit in P['fits']:
        for case in P['cases']:
            r=groups[('confirmation',fit,case,'specialized')][0]['call_records'][0]
            p=next(x for x in prep['records'] if x['fit']==fit)
            kernel=next(x for x in p['compiles'] if x['steps']==P['cases_contract'][case][0])
            memory.append(dict(fit=fit,case=case,full_state_tensor_bytes=r['full_state_tensor_bytes'],
                serialized_state_bytes=r['serialized_state_bytes'],additional_cache_tensor_bytes=kernel['cache_tensor_bytes']))
    cpu_sofar=time.process_time(); wall_sofar=time.perf_counter()-START_WALL
    audit=dict(schema='hepta.specialization-cost-independent-audit.v1',status='PASS',
        scope='finite past observed complete tasks; no future coverage guarantee',protocol_sha256=sha(ROOT/'PROTOCOL_FROZEN.json'),
        workload_sha256=P['worklist_sha256'],actual_call_counts=taskcounts,grouped_timing_zeros=group_zeros,
        individual_stage_cpu_zeros_preserved=stage_zeros,zero_measurements_removed=0,
        choice_sealed_before_confirmation=True,choice=choice,confirmation_prediction_checks=coverage,
        confirmation_blocks_below_envelope=sum(c['blocks_below'] for c in coverage),
        confirmation_blocks_above_envelope=sum(c['blocks_above'] for c in coverage),
        aggregate_cells_outside_envelope=sum(not c['aggregate_within_prediction'] for c in coverage),
        cost_summaries=summaries,logical_memory=memory,
        total_task_validation_coordinates=fullcoords+coldcoords,total_task_bitwise_mismatches=bitdiff,max_abs=max_abs,
        independent_archived_coordinates=archivecoords,independent_archived_bitwise_mismatches=archivebitdiff,
        independent_archived_max_abs=archivemax,archive_checks=archives,
        reference_confirmation_cpu_seconds=refconf,specialized_confirmation_cpu_seconds=optconf,
        observed_confirmation_complete_task_cpu_saving_seconds=observed_task_saving,
        full_qualification_recovery_observed_saved_cpu_seconds=refconf-(investment+optconf),
        actual_supervised_science_plus_probe_cpu_seconds=costs['all_children_cpu_seconds'],
        actual_supervisor_cpu_seconds=costs['supervisor_cpu_seconds'],
        observed_group_task_cpu_seconds=rawsum,
        supervised_child_cpu_minus_group_tasks_seconds=costs['science']['child_cpu_seconds']-rawsum,
        compile_costs_sum_cpu_seconds=sum(c['cpu_ns'] for p in prep['records'] for c in p['compiles'])/1e9,
        reader_cpu_seconds_at_report=cpu_sofar,reader_body_cpu_seconds=cpu_sofar-START_CPU,
        reader_wall_seconds_at_report=wall_sofar,reader_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        model_imports=0,model_calls=0,optimizer_calls=0,production_eligible=False,
        statistical_intervals_claimed=False,bitwise_equivalence_claimed=False)
    write(OUT/'INDEPENDENT_REVIEW.json',audit)
    ndu=dict(schema='hepta.specialization-cost-ndu-trace.v1',decision='KEEP_ORIGINAL_AND_STOP',
        selected_candidate=None,production_eligible=False,finite_research_choice=choice['decision'],
        workload_sha256=P['worklist_sha256'],protocol_sha256=sha(ROOT/'PROTOCOL_FROZEN.json'),
        finite_queued_confirmation_calls_per_implementation=288,actual_total_calls=864,
        empirical_envelope_kind=P['prediction']['bound_kind'],owner_pinned_future_bounds=False,
        production_horizon=None,resource_utility_exchange_rates=None,net_value_lower=None,
        pareto={'reference_confirmation_cpu_seconds':refconf,'specialized_confirmation_cpu_seconds':optconf,
            'compiled_has_positive_additional_cache_bytes':True,'strict_resource_pareto_dominance':False,
            'reason':'CPU is measured lower for specialized only if supported above; additional cache means memory tradeoff'},
        break_even={'fixed_finite_mixture':P['cases_contract'],
            'prediction_per_call_saving_cpu_seconds':bound_gap/288,
            'qualification_investment_cpu_seconds':investment,
            'conditional_calls':investment/(bound_gap/288) if bound_gap>0 else None,
            'observed_confirmation_per_call_saving_cpu_seconds':observed_task_saving/288,
            'observed_arithmetic_calls':investment/(observed_task_saving/288) if observed_task_saving>0 else None,
            'not_production_volume_estimate':True,'not_success_completion_cost_guarantee':True},
        blockers=['research call count is not a production demand or deployment horizon',
            'empirical calibration envelopes are not enforceable future original lower / candidate upper bounds',
            'resource utility conversion is unspecified','old inputs test numerical retention, not new task quality',
            'full serialized same-process state restore does not measure process restart or durable recovery'],
        failure_costs={'probe':costs['probe'],'science':costs['science']},
        evidence_sha256={'review':sha(OUT/'INDEPENDENT_REVIEW.json'),'choice':choice_sha,'supervisor':sha(ROOT/'SUPERVISOR_COST.json')})
    write(OUT/'NDU_TRACE.json',ndu)
    print(json.dumps({'status':'PASS','actual_total_calls':864,'research_choice':choice['decision'],
        'general_ndu':'KEEP_ORIGINAL_AND_STOP','confirmation_cpu':{'reference':refconf,'specialized':optconf},
        'max_abs':max_abs,'envelope_violations':audit['confirmation_blocks_below_envelope']+audit['confirmation_blocks_above_envelope'],
        'reader_cpu_seconds':time.process_time(),'review_sha256':sha(OUT/'INDEPENDENT_REVIEW.json')}),flush=True)


if __name__=='__main__': main()
