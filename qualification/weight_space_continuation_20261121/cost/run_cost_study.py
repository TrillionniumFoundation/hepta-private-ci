#!/usr/bin/env python3
"""One sealed, finite and completely costed fixed-law CPU experiment."""
import io
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
from datetime import datetime, timezone

START_CPU_NS, START_WALL_NS = time.process_time_ns(), time.perf_counter_ns()
ROOT = Path(__file__).resolve().parent
P = json.loads((ROOT/'PROTOCOL_FROZEN.json').read_text())
resource.setrlimit(resource.RLIMIT_CPU, (P['budget']['main_child_soft_cpu_seconds'],
                                        P['budget']['main_child_hard_cpu_seconds']))
os.sched_setaffinity(0, set(P['cpu_affinity']))
OUT = ROOT/'attempt001'
OUT.mkdir(exist_ok=False)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def save(name, value):
    with (OUT/name).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')


for entry in P['pins'] + P['runtime_pins']:
    path = Path(entry['path'])
    if path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
        raise ValueError('Frozen bytes changed: '+str(path))

import numpy as np
import torch
from qualification.hcsn_currentstate.differentiable import Work
from qualification.hcsn_network.benchmark_models import make_model
from qualification.hcsn_network.checkpoint import state_from_record, state_to_record
from specialize import apply_flow, compile_flow, graph_descriptor, physics_digest, readout_features

torch.set_num_threads(1)
torch.set_num_interop_threads(1)
if torch.__version__ != P['torch_version']:
    raise ValueError('Runtime version mismatch')


def timed(fn):
    cpu, wall = time.process_time_ns(), time.perf_counter_ns()
    result = fn()
    return result, {'cpu_ns':time.process_time_ns()-cpu, 'wall_ns':time.perf_counter_ns()-wall}


def model_digest(model):
    h = hashlib.sha256()
    for name, value in model.state_dict().items():
        h.update(name.encode()); h.update(str((tuple(value.shape),str(value.dtype))).encode())
        h.update(value.detach().contiguous().numpy().tobytes())
    return h.hexdigest()


def flatten(value, prefix='root'):
    arrays, metadata = {}, {}
    def walk(obj, key):
        if isinstance(obj, torch.Tensor): arrays[key] = obj.detach().numpy()
        elif isinstance(obj, dict):
            for name in sorted(obj): walk(obj[name], key+'.'+name)
        elif isinstance(obj, (list,tuple)):
            metadata[key+'.length'] = len(obj)
            for i,item in enumerate(obj): walk(item,key+'.'+str(i))
        else: metadata[key] = obj
    walk(value,prefix)
    return arrays,metadata


def compare(value, golden):
    arrays,metadata = flatten(value)
    if metadata != golden['metadata'] or set(arrays) != set(golden['arrays']):
        raise ValueError('Complete state structure or metadata changed')
    max_abs, coordinates, bitdiff = 0.0,0,0
    for key,a in arrays.items():
        b = golden['arrays'][key]
        if a.dtype != b.dtype or a.shape != b.shape or not np.isfinite(a).all():
            raise ValueError('Array shape, type or finiteness changed: '+key)
        d = np.abs(a-b)
        if not np.all(d <= P['abs_tolerance'] + P['rel_tolerance']*np.abs(b)):
            raise ValueError('Numerical tolerance exceeded: '+key)
        max_abs=max(max_abs,float(d.max(initial=0)))
        coordinates+=a.size
        bitdiff+=int(np.count_nonzero(a.view(np.uint64) != b.view(np.uint64)))
    same_argmax=True
    if 'root.logits' in arrays:
        same_argmax=bool(np.array_equal(arrays['root.logits'].argmax(1),golden['arrays']['root.logits'].argmax(1)))
        if not same_argmax: raise ValueError('Classifier argmax changed')
    return dict(max_abs=max_abs, coordinates=coordinates, bitwise_mismatches=bitdiff,
                same_argmax=same_argmax),arrays,metadata


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def check_memory():
    if rss()>P['budget']['rss_cap_bytes']: raise MemoryError('RSS research cap exceeded')


def run():
    old=Path(P['old_root']); preparations=[]; models={}; goldens={}
    with np.load(old/'attempt001/inputs.npz',allow_pickle=False) as z:
        inputs={'training64':torch.from_numpy(z['train'].copy()),
                'synthetic1':torch.from_numpy(z['synthetic'][:10,:1].copy()),
                'synthetic20':torch.from_numpy(z['synthetic'].copy())}
    for case,x in inputs.items():
        if list(x.shape)!=P['cases_contract'][case]: raise ValueError('Input contract changed')
    with torch.no_grad():
        for fit in P['fits']:
            checkpoint=old/'originals/campaign/fits'/fit/'selected.pt'
            def load_model():
                selected=torch.load(checkpoint,map_location='cpu',weights_only=True)
                model=make_model(fit.split('-s')[0]); model.load_state_dict(selected['model'],strict=True)
                model.eval(); return model
            model,load_cost=timed(load_model)
            episode,law_cost=timed(model.episode); physics=(episode.physics,episode.physics)
            compilers={}; compiles=[]
            for steps in (10,20):
                compiled,cost=timed(lambda:compile_flow(model.flow,physics,steps))
                compilers[steps]=compiled
                compiles.append(dict(steps=steps,cache_tensor_bytes=compiled.tensor_bytes(),
                    kernel_sha256=compiled.kernel_sha256,exponentials=compiled.exponentials,**cost))
            models[fit]=dict(model=model,checkpoint=checkpoint,checkpoint_sha256=sha(checkpoint),
                model_sha256=model_digest(model),physics=physics,physics_sha256=physics_digest(physics),
                compilers=compilers)
            preparations.append(dict(fit=fit,checkpoint_sha256=sha(checkpoint),model_sha256=model_digest(model),
                physics_sha256=physics_digest(physics),load_cost=load_cost,law_cost=law_cost,compiles=compiles))
            for case in P['cases']:
                for kind in ('full','cold'):
                    base=old/'attempt001'/fit/(case+'-'+kind)
                    with np.load(str(base)+'.npz',allow_pickle=False) as z:
                        arrays={key.removeprefix('reference::'):z[key].copy() for key in z.files if key.startswith('reference::')}
                    meta=json.loads(Path(str(base)+'.json').read_text())['metadata']
                    goldens[(fit,case,kind)]={'arrays':arrays,'metadata':meta}
    check_memory()
    save('PREPARATION.json',dict(records=preparations,complete_cpu_ns=time.process_time_ns()-START_CPU_NS,
        complete_wall_ns=time.perf_counter_ns()-START_WALL_NS,peak_rss_bytes=rss(),
        imports_and_source_verification_included=True))
    rows=[]; worklist=json.loads((ROOT/'WORKLOAD_FROZEN.json').read_text())['rows']
    choice=None; counters={'reference_forward':0,'specialized_forward':0,'continuation_steps':0,
                           'optimizer_steps':0,'checkpoint_writes':0,'full_tasks':0}
    archives=OUT/'arrays'; archives.mkdir()
    raw=OUT/'TIMINGS.jsonl'

    def task(q, archive):
        m=models[q['fit']]; model=m['model']; physics=m['physics']; x=inputs[q['case']]
        stages={}
        def identity():
            if sha(m['checkpoint'])!=m['checkpoint_sha256'] or model_digest(model)!=m['model_sha256']:
                raise ValueError('Checkpoint or live parameter identity changed')
            if physics_digest(physics)!=m['physics_sha256']:
                raise ValueError('Own law identity changed')
            if graph_descriptor(model.flow,len(x))!=m['compilers'][len(x)].graph:
                raise ValueError('Graph contract changed')
        _,stages['identity']=timed(identity)
        def forward():
            if q['implementation']=='reference':
                em,state=model.flow(x,physics,work=Work()); counters['reference_forward']+=1
            else:
                em,state=apply_flow(m['compilers'][len(x)],model.flow,x,physics); counters['specialized_forward']+=1
            logits=model.readout(readout_features(state,x.shape[1],8))
            return em,state,logits
        (em,state,logits),stages['fullstate_forward']=timed(forward)
        record,stages['fullstate_snapshot']=timed(lambda:state_to_record(state))
        def cold_restore():
            buffer=io.BytesIO(); torch.save(record,buffer)
            size=buffer.tell(); buffer.seek(0)
            loaded=torch.load(buffer,map_location='cpu',weights_only=True)
            return state_from_record(loaded),size
        (restored,serialized_bytes),stages['serialized_cold_restore']=timed(cold_restore)
        def continuation():
            ce,cs=model.flow.step(x[-1].clone()*0.25,restored,physics,Work())
            counters['continuation_steps']+=1
            return {'emission':ce,'state':state_to_record(cs)}
        cold,stages['continuation_fullstate']=timed(continuation)
        def validate():
            fm,fa,fmd=compare({'emissions':em,'state':record,'logits':logits},goldens[(q['fit'],q['case'],'full')])
            cm,ca,cmd=compare(cold,goldens[(q['fit'],q['case'],'cold')])
            return fm,cm,fa,ca,fmd,cmd
        (fm,cm,fa,ca,fmd,cmd),stages['validation']=timed(validate)
        if archive:
            def archive_call():
                name=q['fit']+'__'+q['case']+'__'+q['implementation']
                np.savez_compressed(archives/(name+'.npz'),**{'full::'+k:v for k,v in fa.items()},
                                    **{'cold::'+k:v for k,v in ca.items()})
                with (archives/(name+'.json')).open('x') as f:
                    json.dump({'full_metadata':fmd,'cold_metadata':cmd,'full':fm,'cold':cm},f,allow_nan=False)
            _,stages['evidence_archive']=timed(archive_call)
        else: stages['evidence_archive']={'cpu_ns':0,'wall_ns':0}
        counters['full_tasks']+=1
        check_memory()
        return dict(stages=stages,full=fm,cold=cm,full_state_tensor_bytes=state.tensor_bytes(),
                    serialized_state_bytes=serialized_bytes)

    def choose():
        # No confirmation call has been made at this point.
        if any(r['phase']!='calibration' for r in rows): raise ValueError('Late choice')
        groups={}; envelopes=[]
        for r in rows: groups.setdefault((r['fit'],r['case'],r['implementation']),[]).append(r['cpu_ns']/1e9)
        for key,values in sorted(groups.items()):
            if len(values)!=2: raise ValueError('Incomplete calibration')
            envelopes.append(dict(fit=key[0],case=key[1],implementation=key[2],
                cpu_seconds_lower=.5*min(values),cpu_seconds_upper=2*max(values),
                calibration_block_cpu_seconds=values,confirmation_blocks=4))
        probe=json.loads((ROOT/'TIMEOUT_PROBE.json').read_text())
        before_cpu=time.process_time_ns()/1e9
        # This charges imports too; the difference from START is recorded separately.
        investment=before_cpu+probe['child_cpu_seconds']+probe['supervisor_cpu_seconds_at_launch']+P['budget']['post_analysis_cpu_reserve_seconds']
        original_lower=sum(e['cpu_seconds_lower']*4 for e in envelopes if e['implementation']=='reference')
        candidate_calls_upper=sum(e['cpu_seconds_upper']*4 for e in envelopes if e['implementation']=='specialized')
        candidate_upper=investment+candidate_calls_upper
        decision='COMPILED' if candidate_upper<original_lower else 'KEEP_ORIGINAL'
        gap_per_mixture=(original_lower-candidate_calls_upper)/288
        calibration_seal=dict(sealed_utc=utc(),timings_sha256=sha(raw),calibration_rows=len(rows),
            calibration_calls=sum(r['calls'] for r in rows),confirmation_calls_so_far=0,
            envelopes=envelopes,bound_kind=P['prediction']['bound_kind'],
            statistical_coverage_claim=False,enforceable_future_bound=False)
        save('CALIBRATION_SEAL.json',calibration_seal)
        result=dict(schema='hepta.finite-cpu-research-choice.v1',decision=decision,selected_candidate=None if decision!='COMPILED' else 'fixed_law_compiled',
            sealed_utc=utc(),protocol_sha256=sha(ROOT/'PROTOCOL_FROZEN.json'),workload_sha256=P['worklist_sha256'],
            calibration_seal_sha256=sha(OUT/'CALIBRATION_SEAL.json'),confirmation_calls_before_choice=0,
            confirmation_horizon_calls_per_implementation=288,preconfirmation_process_cpu_seconds=before_cpu,
            preconfirmation_body_cpu_seconds=(time.process_time_ns()-START_CPU_NS)/1e9,
            timeout_probe_cpu_seconds=probe['child_cpu_seconds'],post_analysis_cpu_reserve_seconds=P['budget']['post_analysis_cpu_reserve_seconds'],
            supervisor_cpu_seconds_at_launch=probe['supervisor_cpu_seconds_at_launch'],
            complete_qualification_investment_cpu_seconds=investment,
            original_confirmation_cpu_lower_prediction=original_lower,
            candidate_confirmation_tasks_cpu_upper_prediction=candidate_calls_upper,
            candidate_complete_cpu_upper_prediction=candidate_upper,
            conservative_predicted_saved_cpu_seconds=original_lower-candidate_upper,
            fixed_mixture_break_even_calls=(investment/gap_per_mixture if gap_per_mixture>0 else None),
            break_even_scope='conditional on unchanged finite mixture and empirical calibration envelope; no production demand or enforceable bound inferred',
            reason=('candidate prediction covers full investment and finite queue' if decision=='COMPILED' else 'complete qualification investment is not recovered under frozen conservative prediction'),
            production_eligible=False,general_ndu_decision='KEEP_ORIGINAL_AND_STOP',resource_utility_exchange_rates=None)
        save('RESEARCH_CHOICE_SEALED.json',result)
        print(json.dumps({'phase':'choice','decision':decision,'original_lower_prediction':original_lower,
            'candidate_complete_upper_prediction':candidate_upper}),flush=True)
        return result

    with torch.no_grad(),raw.open('x') as handle:
        for q in worklist:
            if q['phase']=='confirmation' and choice is None:
                handle.flush(); choice=choose()
            started=utc(); c,w=time.process_time_ns(),time.perf_counter_ns()
            calls=[]
            for i in range(q['calls']): calls.append(task(q,q['archive_first_call'] and i==0))
            row={**q,'started_utc':started,'ended_utc':utc(),
                 'cpu_ns':time.process_time_ns()-c,'wall_ns':time.perf_counter_ns()-w,
                 'call_records':calls,'peak_rss_bytes':rss(),
                 'choice_sha256':sha(OUT/'RESEARCH_CHOICE_SEALED.json') if choice else None}
            rows.append(row); handle.write(json.dumps(row,allow_nan=False)+'\n'); handle.flush()
            if q['fit']==P['fits'][-1] and q['case']==P['cases'][-1]:
                print(json.dumps({'phase':q['phase'],'block':q['block'],'implementation':q['implementation'],
                    'full_tasks':counters['full_tasks'],'process_cpu_seconds':time.process_time()}),flush=True)
    unchanged=[]
    for fit,m in models.items():
        passed=sha(m['checkpoint'])==m['checkpoint_sha256'] and model_digest(m['model'])==m['model_sha256']
        if not passed: raise ValueError('Original checkpoint changed')
        unchanged.append(dict(fit=fit,checkpoint_sha256=m['checkpoint_sha256'],model_sha256=m['model_sha256'],unchanged=True))
    save('RESULT.json',dict(status='COMPLETE',production_eligible=False,new_quality_holdout=False,
        protocol_sha256=sha(ROOT/'PROTOCOL_FROZEN.json'),workload_sha256=P['worklist_sha256'],
        timing_rows=len(rows),timings_sha256=sha(raw),choice_sha256=sha(OUT/'RESEARCH_CHOICE_SEALED.json'),
        counters=counters,unchanged=unchanged,all_numeric_comparisons_passed=True,
        body_cpu_seconds=(time.process_time_ns()-START_CPU_NS)/1e9,
        body_wall_seconds=(time.perf_counter_ns()-START_WALL_NS)/1e9,
        process_cpu_seconds=time.process_time(),peak_rss_bytes=rss(),
        library_imports_in_body=True,optimizer_calls=0,weight_edits=0))


if __name__=='__main__':
    try: run()
    except BaseException as exc:
        save('FAILURE.json',dict(type=type(exc).__name__,reason=str(exc),utc=utc(),
            process_cpu_seconds=time.process_time(),peak_rss_bytes=rss(),retry_authorized=False))
        raise
