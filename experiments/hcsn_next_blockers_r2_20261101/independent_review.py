"""Independent evidence reconstruction; scientific gates remain separate.

Run only after lane owners finish their confirmation outputs. No lane campaign,
scorer, network or policy implementation is imported by this reviewer.
"""
from datetime import datetime, timezone
import hashlib
import itertools
import math
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_addressed_flow_20261101 import data
from experiments.hcsn_four_stage_flow_20261031.extended_eval import stress_data

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def load(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_check(mapping):
    for path,digest in mapping.items(): assert sha(ROOT/path)==digest, path


def close(actual,expected):
    if actual is None or expected is None: assert actual is expected
    else: assert np.allclose(actual,expected,rtol=1e-10,atol=1e-12), (actual,expected)


def missing_arrays(task,stage,condition):
    if condition=='missing_tokens_128':
        base=data.batch(task,stage['episodes'],stage['seed'],stage['split'],'missing')
        arrays=stress_data(task,base,'long_tokens_128')
        available=np.zeros_like(arrays['y'],bool);available[:,-4:]=base['target_available'][:,-4:]
        arrays['target_available']=available
        return arrays
    return data.batch(task,stage['episodes'],stage['seed'],stage['split'],condition)


def expected_probabilities(task,arrays):
    """Count visible-consistent completions, independent of candidate code."""
    expected=np.zeros((len(arrays['x']),4,8));cardinalities=[]
    offset=4 if task=='binding' else 0;end=offset+8
    for row in range(len(arrays['x'])):
        initial={};updates={};aliases={};erased=[]
        for t in range(end+(2 if task=='selective' else 0)):
            if not arrays['observed'][row,t]: erased.append(t);continue
            event=arrays['x'][row,t];kind=event[12:16].argmax()
            if kind==0: (initial if t<end else updates)[int(event[:4].argmax())]=int(event[4:12].argmax())
            elif kind==3: aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
        worlds=[]
        if not erased:
            final=initial.copy();final.update(updates);worlds.append(final)
        elif erased[0]<end:
            key=next(iter(set(range(4))-set(initial)))
            for value in sorted(set(range(8))-set(initial.values())-set(updates.values())):
                final=initial.copy();final[key]=value;final.update(updates);worlds.append(final)
        else:
            for key in sorted(set(range(4))-set(updates)):
                for value in sorted(set(range(8))-set(initial.values())-set(updates.values())):
                    final=initial.copy();final.update(updates);final[key]=value;worlds.append(final)
        assert worlds;cardinalities.append(len(worlds))
        for slot,t in enumerate(range(arrays['x'].shape[1]-4,arrays['x'].shape[1])):
            event=arrays['x'][row,t]
            key=aliases[int(event[19:23].argmax())] if task=='binding' else int(event[:4].argmax())
            for world in worlds:expected[row,slot,world[key]]+=1/len(worlds)
    return expected,cardinalities


def visible_acceptance(task,arrays,group):
    """Independent implementation of the declared fixed visible-state hash."""
    output=np.zeros_like(group,bool);offset=4 if task=='binding' else 0;end=offset+8
    for row in range(len(arrays['x'])):
        initial=np.full(4,255,np.uint8);updates=np.full(4,255,np.uint8);aliases=np.full(4,255,np.uint8)
        missing_initial=missing_final=0
        for t in range(end+(2 if task=='selective' else 0)):
            if not arrays['observed'][row,t]:
                if t<end: missing_initial+=1
                else: missing_final+=1
                continue
            event=arrays['x'][row,t];kind=event[12:16].argmax()
            if kind==0:
                key=event[:4].argmax();value=event[4:12].argmax()
                (initial if t<end else updates)[key]=value
            elif kind==3: aliases[event[19:23].argmax()]=event[:4].argmax()
        for slot,t in enumerate(range(arrays['x'].shape[1]-4,arrays['x'].shape[1])):
            event=arrays['x'][row,t]
            key=int(aliases[event[19:23].argmax()]) if task=='binding' else int(event[:4].argmax())
            state=initial.tobytes()+updates.tobytes()+aliases.tobytes()+bytes([key,missing_initial,missing_final])
            coin=int.from_bytes(hashlib.blake2b(b'hcsn-r2-fixed-quarter-20261101'+task.encode()+state,digest_size=8).digest(),'big')
            output[row,slot]=group[row,slot]==0 or (group[row,slot]==2 and coin<2**62)
    return output


def probability_metrics(p,y,available,accepted,group):
    correct=p.argmax(-1)==y;confidence=p.max(-1)
    nll=-np.log(p[np.arange(len(y)),y].clip(1e-15));brier=((p-np.eye(8)[y])**2).sum(-1)
    result=dict(accuracy=float(correct.mean()),all4=float(correct.reshape(-1,4).all(-1).mean()),
                nll=float(nll.mean()),brier=float(brier.mean()),coverage=float(accepted.mean()),
                accepted_correctness=float(correct[accepted].mean()) if accepted.any() else None,
                accepted_known_coverage=float(accepted[available].mean()),
                accepted_unavailable_rate=float(accepted[~available].mean()) if (~available).any() else None,
                known_accuracy=float(correct[available].mean()),branches={})
    for name,mask in [('unavailable',~available),('certain',group==0),('initial_unknown',group==1),('final_ambiguous',group==2)]:
        result['branches'][name]=dict(count=int(mask.sum()),accuracy=float(correct[mask].mean()),
            nll=float(nll[mask].mean()),brier=float(brier[mask].mean()),confidence=float(confidence[mask].mean()),
            accepted_count=int((accepted&mask).sum()),accepted_correct=int((accepted&mask&correct).sum())) if mask.any() else None
    return result


def nested_close(actual,expected):
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,dict): nested_close(actual[key],value)
        else: close(actual[key],value)


def missing():
    lane=ROOT/'experiments/hcsn_missing_reliability_r2_20261101';out=lane/'results/run001'
    if not (out/'PROTOCOL.json').exists(): return dict(status='pending_source')
    p=load(out/'PROTOCOL.json'); source_check(p['source_hashes'])
    law=load(lane/'AUDIT_LAW.json');source_check(law['source_sha256']);assert law['passed']
    if not (out/'confirmation/SUMMARY.json').exists(): return dict(status='pending_confirmation',law_query_checks=law['query_checks'])
    candidate=load(out/'CANDIDATE.json');s=load(out/'confirmation/SUMMARY.json')
    assert s['candidate_sha256']==sha(out/'CANDIDATE.json') and s['source_unchanged']
    assert candidate['protocol_sha256']==sha(out/'PROTOCOL.json')
    cache={};unique_rows=[];branches=[]
    for r in s['records']:
        key=(r['task'],r['condition'])
        if key not in cache:
            arrays=missing_arrays(r['task'],p['confirmation'],r['condition']);mask=arrays['y']>=0
            raw_path=out/'confirmation'/r['raw_file'];assert sha(raw_path)==r['raw_sha256']
            with np.load(raw_path,allow_pickle=False) as z: raw={k:z[k] for k in z.files}
            for name,value in arrays.items(): assert hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()==r['data_sha256'][name]
            assert np.array_equal(raw['labels'],arrays['y'][mask]);assert np.array_equal(raw['available'],arrays.get('target_available',mask)[mask])
            expected,_=expected_probabilities(r['task'],arrays)
            expected=expected.reshape(-1,8);close(raw['exact_probabilities'],expected)
            group=np.where((expected>0).sum(-1)==1,0,np.where(expected.max(-1)>.5,2,1))
            assert np.array_equal(group,raw['group'])
            fitted=expected.copy();ambiguous=group==2
            for i in np.flatnonzero(ambiguous):
                support=expected[i]>0;old=expected[i].argmax();fitted[i,support]=(1-candidate['q'])/3;fitted[i,old]=candidate['q']
            close(raw['probabilities'],fitted)
            accepted=visible_acceptance(r['task'],arrays,group.reshape(-1,4)).reshape(-1)
            assert np.array_equal(accepted,raw['accepted'])
            cache[key]=(raw,expected,fitted,accepted,group)
        raw,expected,fitted,accepted,group=cache[key]
        if r['version']=='ordinary_exact_law': probability=expected
        elif r['version']=='shared_posterior_readout': probability=fitted
        elif r['version']=='r1_neural':
            path=out/'confirmation'/r['neural_raw_file'];assert sha(path)==r['neural_raw_sha256']
            with np.load(path,allow_pickle=False) as z: logits=z['logits'].astype(np.float64)/r['calibration']['temperature']
            e=np.exp(logits-logits.max(-1,keepdims=True));probability=e/e.sum(-1,keepdims=True)
            accepted=probability.max(-1)>=r['calibration']['threshold']
        else: raise AssertionError('Unexpected version')
        calculated=probability_metrics(probability,raw['labels'],raw['available'],accepted,group)
        nested_close(r['metrics'],calculated)
        if r['version']=='shared_posterior_readout' and r['core']=='flow' and r['seed']==17:
            unique_rows.append(dict(task=r['task'],condition=r['condition'],metrics=calculated))
            branch=calculated['branches']['final_ambiguous']
            if branch: branches.append(dict(task=r['task'],condition=r['condition'],**branch))
    assert len(s['records'])==156 and len(cache)==12 and len(unique_rows)==12
    gates=p['gates'];checks=[]
    for row in unique_rows:
        m=row['metrics'];passed=(m['known_accuracy']>=gates['known_accuracy_min']
            and m['accepted_correctness'] is not None and m['accepted_correctness']>=gates['accepted_correctness_min']
            and m['accepted_known_coverage']>=gates['accepted_known_coverage_min']
            and ('missing' in row['condition'] or m['all4']>=gates['nonmissing_all4_min']))
        checks.append(dict(task=row['task'],condition=row['condition'],passed=passed))
    return dict(status='verified',record_checks=len(s['records']),distinct_posterior_records=len(cache),
                gate_checks=checks,restricted_interface_point_gates_pass=all(r['passed'] for r in checks),
                final_ambiguous_branch=branches,summary_sha256=sha(out/'confirmation/SUMMARY.json'),
                law_audit_sha256=sha(lane/'AUDIT_LAW.json'),law_query_checks=law['query_checks'],
                limits=['Same posterior repeated across six core/seed pairs; not independent evidence',
                        'Class-law parser bypasses neural state; analytic-core increment is zero by construction',
                        'Overall selective correctness is not per-answer 95 percent confidence; accepted ambiguous queries retain about two-thirds correctness',
                        'No resample, multiple-erasure, unknown-generator or open-language qualification'])


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


def distribution():
    lane=ROOT/'experiments/hcsn_distribution_value_r2_20261101'
    paths=sorted(lane.glob('results/run*/SUMMARY.json'))
    if not paths:return dict(status='pending_confirmation')
    out=paths[-1].parent;p=load(out/'PROTOCOL.json');s=load(out/'SUMMARY.json');c=load(out/'ALL_CANDIDATES.json')
    for name,digest in p['source_hashes'].items():assert sha(lane/name)==digest
    assert c['source_hashes']==p['source_hashes'] and c['protocol_sha256']==sha(out/'PROTOCOL.json')
    assert load(out/'confirmation/FREEZE.json')['candidate_manifest_sha256']==sha(out/'ALL_CANDIDATES.json')
    nfit,nctx,ncue,nprice,narm,nepisode=len(c['fits']),p['test_contexts'],p['cue_count'],len(p['profiles']),8,p['episodes_per_cell']
    utility=np.zeros((nfit,nctx,ncue,nprice,narm,nepisode));accuracy=np.zeros_like(utility)
    counts=np.zeros((8,5),np.int64);files=0;action_differences=engine_differences=0;initial_world={}
    summary_rows=load(out/'confirmation/ROWS.json');lookup={(r['seed'],r['context'],r['cue'],r['profile'],r['arm']):r for r in summary_rows}
    names=['A_ordinary_light','B_ordinary_value','C_analytic_light','D_analytic_value','joint_train_factor_execute','factor_train_joint_execute','factor_train_factor_execute','joint_train_mean_execute']
    durations={2:.15,3:.9,4:.25};maximum_events=0
    for si,fit in enumerate(c['fits']):
        assert sha(out/fit['candidate'])==fit['sha256'] and sha(out/fit['training_raw'])==fit['training_raw_sha256']
        candidate=load(out/fit['candidate'])
        with np.load(out/fit['training_raw'],allow_pickle=False) as z:
            count=np.zeros_like(z['counts']);exposure=np.zeros_like(z['exposure'])
            for context,trajectory,state,target,duration,kind in z['segments']:
                state,kind,context=int(state),int(kind),int(context)
                exposure[context]+=duration*np.array([state in (0,1),state in (1,2),state==2,state==3])
                if kind>=0:count[context,kind]+=1
            close(count,z['counts']);close(exposure,z['exposure'])
            prior=np.zeros((8,8));np.add.at(prior,tuple(z['prior_samples'].T),1);prior/=prior.sum(1,keepdims=True)
            close(candidate['full_priors'],prior)
            factor=np.asarray([(q.reshape(4,2).sum(1)[:,None]*q.reshape(4,2).sum(0)).ravel() for q in prior])
            close(candidate['factorized_priors'],factor)
            read=[np.mean(z['read_target'][z['read_state']==i]==z['read_observed'][z['read_state']==i]) for i in range(4)]
            close(candidate['read_accuracy'],read)
        for ci in range(nctx):
            for cue in range(ncue):
                for price in range(nprice):
                    path=out/'confirmation'/f"fit{fit['seed']}_context{ci}_cue{cue}_price{price}.npz"
                    with np.load(path,allow_pickle=False) as z:raw={k:z[k] for k in z.files}
                    assert np.array_equal(raw['target'],np.repeat(raw['target'][:1],8,axis=0))
                    assert np.array_equal(raw['before'][:,:,0],np.repeat(raw['before'][:1,:,0],8,axis=0))
                    world_key=(ci,cue,price)
                    world_tuple=(raw['target'][0].tobytes(),raw['before'][0,:,0].tobytes())
                    if world_key in initial_world:assert initial_world[world_key]==world_tuple
                    initial_world[world_key]=world_tuple
                    assert raw['events'].dtype==np.int64 and (raw['events']>=0).all()
                    maximum_events=max(maximum_events,int(raw['events'].max()))
                    for arm in range(narm):
                        actions=raw['actions'][arm];events=raw['events'][arm];fees=raw['fees'][arm];duration=raw['durations'][arm]
                        active=(actions>=2)&(actions<=4);terminal=actions<2
                        assert np.all(terminal.sum(1)==1)
                        for ep in range(nepisode):
                            stop=int(np.flatnonzero(terminal[ep])[0]);assert np.all(actions[ep,stop+1:]==255)
                            assert np.all(active[ep,:stop]);assert np.all(fees[ep,stop:]==0) and np.all(duration[ep,stop:]==0)
                            assert raw['after'][arm,ep,stop]==raw['before'][arm,ep,stop]
                            assert raw['correct'][arm,ep]==(actions[ep,stop]==raw['target'][arm,ep])
                        expected_fee=np.zeros_like(fees)
                        for action,dt in durations.items():
                            selected=actions==action;assert np.all(duration[selected]==dt)
                            expected_fee[selected]=p['profiles'][price][2]*dt+p['outage_fee']*events[selected]
                            if action in (2,4):expected_fee[selected]+=p['profiles'][price][0 if action==2 else 1]
                        close(fees,expected_fee)
                        close(raw['utility'][arm],raw['correct'][arm]-fees.sum(1))
                        event_flag=(events>0).astype(int)
                        simple=(actions==3)|(actions==4);assert np.array_equal(raw['obs'][arm][simple],event_flag[simple])
                        readmask=actions==2;assert np.all(raw['obs'][arm][readmask]//2==event_flag[readmask])
                        count_actions=np.bincount(actions[actions!=255],minlength=5)
                        counts[arm]+=count_actions
                        row=lookup[fit['seed'],ci,cue,price,names[arm]]
                        close(row['utility'],raw['utility'][arm].mean());close(row['accuracy'],raw['correct'][arm].mean())
                        assert np.array_equal(row['action_counts'],count_actions)
                    utility[si,ci,cue,price]=raw['utility'];accuracy[si,ci,cue,price]=raw['correct']
                    engine_differences+=int(np.any(raw['actions'][1]!=raw['actions'][3],axis=1).sum())
                    if cue in (2,3):action_differences+=int(np.any(raw['actions'][3]!=raw['actions'][4],axis=1).sum())
                    files+=1
    def contrast(left,right,cues=None,interaction=False,legacy_interaction=False):
        if legacy_interaction:diff=utility[...,3,:]-utility[...,2,:]-utility[...,1,:]+utility[...,0,:]
        elif interaction:diff=(utility[...,3,:]-utility[...,2,:])-(utility[...,1,:]-utility[...,0,:])
        else:diff=utility[...,left,:]-utility[...,right,:]
        if cues is not None:diff=diff[:,:,cues]
        by_context=diff.mean(axis=(0,2,3,4));by_fit=diff.mean(axis=(1,2,3,4));rng=np.random.default_rng(p['bootstrap']['seed'])
        draws=[by_context[rng.integers(len(by_context),size=len(by_context))].mean() for _ in range(p['bootstrap']['draws'])]
        interval=np.quantile(draws,[.025,.975])
        return dict(mean=float(diff.mean()),per_fit=by_fit.tolist(),per_context=by_context.tolist(),conditional_context_interval=interval.tolist(),strictly_positive_gate=bool((by_fit>0).all() and interval[0]>0))
    for name,left,right in [('B-A',1,0),('D-C',3,2),('C-A',2,0),('D-B',3,1)]:nested_close(s['main_2x2'][name],contrast(left,right))
    legacy=contrast(0,0,legacy_interaction=True);grouped=contrast(0,0,interaction=True)
    nested_close(s['main_2x2']['(D-C)-(B-A)'],legacy)
    reporting_correction_needed=legacy['strictly_positive_gate']!=grouped['strictly_positive_gate']
    correction=dict(needed=reporting_correction_needed,legacy_mean=legacy['mean'],grouped_mean=grouped['mean'],
                    legacy_strict_positive=legacy['strictly_positive_gate'],valid_grouped_strict_positive=grouped['strictly_positive_gate'])
    if (out/'CORRECTED_SUMMARY.json').exists():
        corrected=load(out/'CORRECTED_SUMMARY.json')
        nested_close(corrected['main_2x2']['(D-C)-(B-A)'],grouped)
        correction.update(verified=True,corrected_summary_sha256=sha(out/'CORRECTED_SUMMARY.json'))
    else:correction['verified']=not reporting_correction_needed
    for name,left,right in [('joint_execute_effect_joint_train',3,4),('joint_execute_effect_factor_train',5,6),('joint_train_effect_joint_execute',3,5),('joint_train_effect_factor_execute',4,6),('mean_projection_effect',3,7)]:nested_close(s['secondary'][name],contrast(left,right))
    nested_close(s['association_primary'],contrast(3,4,cues=[2,3]))
    assert s['ordinary_vs_analytic_value_action_differences']==engine_differences and s['association_projection_episode_action_differences']==action_differences
    assert s['distribution_mechanism_gate']==bool(s['association_primary']['strictly_positive_gate'] and action_differences>0)
    assert s['analytic_increment_gate']==s['main_2x2']['D-B']['strictly_positive_gate']
    for i,name in enumerate(names):
        close(s['mean_utility'][name],utility[...,i,:].mean());close(s['mean_accuracy'][name],accuracy[...,i,:].mean())
        assert np.array_equal(s['action_counts'][name],counts[i])
    return dict(status='verified' if correction['verified'] else 'awaiting_reporting_correction',raw_files=files,record_checks=len(summary_rows),rollout_records=int(np.prod(utility.shape)),
                maximum_recorded_repeated_events=maximum_events,distribution_mechanism_gate=s['distribution_mechanism_gate'],analytic_increment_gate=s['analytic_increment_gate'],
                ordinary_vs_analytic_action_differences=engine_differences,summary_sha256=sha(out/'SUMMARY.json'),interaction_reporting_correction=correction,
                limits=['Redesigned finite fully supervised identification task, same fixed rate-function family',
                        'Six context-cluster intervals conditional on three fitted candidates; not neural training or population certainty',
                        'Actual symbolic fees and repeated events reconciled; CPU cost reported separately, not subtracted from utility',
                        'No original learned-network, AV or production adoption closure'])


def video():
    lane=ROOT/'experiments/hcsn_video_raw_r2_20261101';paths=sorted(lane.glob('results/*/RESULT.json'))
    if not paths:return dict(status='pending_confirmation')
    path=paths[-1];out=path.parent;s=load(path);f=load(out/'CANDIDATE_FREEZE.json');training=load(out/'TRAINING.json')
    assert f['source_sha256']==sha(lane/'study.py') and f['raw_source_sha256']==sha(lane/'raw_data.py') and f['protocol_sha256']==sha(lane/'PROTOCOL.json')
    source_check(f['dependencies']);assert all(sha(out/name)==digest for name,digest in f['files'].items())
    assert not f['validation_loaded'] and not training['validation_loaded']
    identity_count=0
    cohort={r['clip']:r for r in load(ROOT/'experiments/hcsn_four_stage_flow_20261031/data/COHORT.json')['records']}
    for split in ('train','validation'):
        identity=load(lane/'inputs'/f'{split}_IDENTITY.json')
        assert identity['source_sha256']==sha(lane/'raw_data.py') and identity['protocol_sha256']==sha(lane/'PROTOCOL.json')
        assert sha(lane/'inputs'/f'{split}_pixels.npz')==identity['pixels_sha256']
        with np.load(lane/'inputs'/f'{split}_pixels.npz',allow_pickle=False) as raw_input:
            labels=raw_input['label'];clips=raw_input['clip'];actors_input=raw_input['actor']
            expected_labels=np.asarray([('DFA','IOM').index(cohort[clip]['sentence']) for clip in clips])
            assert np.array_equal(labels,expected_labels) and np.array_equal(np.unique(labels),[0,1])
            assert len(np.unique(actors_input))==(24 if split=='train' else 6)
            assert all(cohort[clip]['split']==split and cohort[clip]['actor']==actor for clip,actor in zip(clips,actors_input))
        for clip in identity['records']:
            assert len(clip['selected_timestamps'])==16 and all(t<=clip['accepted_end']+1e-12 for t in clip['selected_timestamps'])
            assert np.all(np.diff(clip['selected_timestamps'])>=0)
        identity_count+=len(identity['records'])
    held=[]
    for fit in training['visual_fits']:
        assert fit['updates']==300
        if fit['fold']!='full':
            assert not set(fit['fit_actors'])&set(fit['held_actors']);held.extend(fit['held_actors'])
    assert len(held)==len(set(held))==24 and all(r['success'] for r in training['relation_fits'])
    with np.load(out/'VALIDATION_OUTPUTS.npz',allow_pickle=False) as z:a={k:z[k] for k in z.files}
    probabilities=a['probabilities'];scores={}
    for name in ('AT','AT_unique','AVT'):
        inputs=probabilities.copy()
        if name!='AVT':inputs[:,1]=.5
        features=np.column_stack((inputs[:,0],inputs[:,2],inputs[:,0]*inputs[:,2])) if name=='AT_unique' else np.column_stack([np.prod(inputs[:,group],axis=1) for n in range(1,4) for group in itertools.combinations(range(3),n)])
        with np.load(out/f'{name}_head.npz',allow_pickle=False) as head:
            margins=((features-head['mean'])/head['scale'])@head['beta'][:-1]+head['beta'][-1]
        scores[name]=1/(1+np.exp(-margins))
        if name in a:close(a[name],scores[name])
        close(s['relation'][name]['accuracy'],np.average((scores[name]>=.5)==a['y'],weights=a['sample_weight']))
        close(s['relation'][name]['brier'],np.average((scores[name]-a['y'])**2,weights=a['sample_weight']))
    actors=np.unique(a['actor']);diffs=[]
    for actor in actors:
        ix=a['actor']==actor;y=a['y'][ix];w=a['sample_weight'][ix]
        diffs.append([np.average(((scores['AVT'][ix]>=.5)==y).astype(float)-((scores['AT_unique'][ix]>=.5)==y),weights=w),
                      np.average((scores['AVT'][ix]-y)**2-(scores['AT_unique'][ix]-y)**2,weights=w)])
    diffs=np.asarray(diffs);close(s['actor_differences'],diffs);rng=np.random.default_rng(20261103)
    boot=diffs[rng.integers(len(actors),size=(10000,len(actors)))].mean(1);interval=np.quantile(boot,[.025,.975],axis=0).T
    close(s['AVT_minus_AT_unique']['accuracy'],diffs[:,0].mean());close(s['AVT_minus_AT_unique']['accuracy_actor_bootstrap_95'],interval[0])
    close(s['AVT_minus_AT_unique']['brier'],diffs[:,1].mean());close(s['AVT_minus_AT_unique']['brier_actor_bootstrap_95'],interval[1])
    visual_accuracy=np.mean((a['video']>=.5)==a['video_label']);close(s['sentence_video_accuracy'],visual_accuracy)
    assert s['video_gate']==bool(visual_accuracy>=.9 and interval[0,0]>0)
    assert not s['external_independent_confirmation'] and not s['analytic_core_contribution']
    return dict(status='verified',record_checks=len(actors),raw_prefix_clip_identities=identity_count,
                video_sentence_accuracy=float(visual_accuracy),historical_development_video_gate=s['video_gate'],result_sha256=sha(path),
                limits=['Historical train/development actors only; raw extraction does not create a new independent population',
                        'No CNN rerun by this saved-output reviewer', 'Primary ordinary comparator is unique three-feature AT basis; duplicated seven-feature AT remains secondary'])


def cpu_envelope():
    lane=ROOT/'experiments/hcsn_cpu_envelope_r2_20261101';paths=sorted(lane.glob('results/run*/SUMMARY.json'))
    if not paths:return dict(status='pending_qualification')
    path=paths[-1];out=path.parent;p=load(out/'PROTOCOL.json');s=load(path)
    for name,digest in p['source'].items():assert sha(lane/name)==digest
    source_check(p['dependency_hashes']);source_check(p['checkpoint_hashes'])
    assert len(s['rows'])==2*len(p['cases'])==24
    r1=load(ROOT/'experiments/hcsn_missing_answers_20261101/results/run001/ALL_CHECKPOINTS.json')
    checkpoint={(r['task'],r['core'],r['seed']):r['checkpoint_sha256'] for r in r1['fits']}
    checks=[]
    for i in range(len(p['cases'])):
        ordinary,sealed=s['rows'][2*i:2*i+2];passed=ordinary['exit_code']==sealed['exit_code']==0
        assert ordinary['case']==sealed['case']==p['cases'][i] and ordinary['mode']=='no' and sealed['mode']=='yes'
        if passed:
            a,b=ordinary['result'],sealed['result'];case=sealed['case']
            assert a['checkpoint_sha256']==b['checkpoint_sha256']==checkpoint[case['task'],case['core'],17]
            guard=b['sealed'];assert guard['fork_denied'] and guard['seccomp']==2 and guard['no_new_privs']==1
            assert {r['name'] for r in guard['rules']}=={'fork','vfork','clone','clone3','execve','execveat'}
            assert b['final_tasks']==1 and not b['live_children'] and b['post_seal_waited_child_cpu_delta_seconds']==0
            assert sealed['wait4_peak_rss_bytes']>=b['peak_rss_before_result_write_bytes']
            passed=(a['output_sha256']==b['output_sha256'] and a['accuracy']==b['accuracy']
                and sealed['wait4_peak_rss_bytes']<=p['memory_worker_limit_bytes']
                and sealed['supervisor_plus_worker_rss_upper_bound_bytes']<=p['supervisor_plus_worker_upper_limit_bytes'])
        assert s['checks'][i]['passed']==passed;checks.append(passed)
    assert s['passed']==all(checks)
    assert s['attributable_full_family_peak_rss_bytes'] is None and not s['full_family_memory_gate']
    return dict(status='verified',record_checks=len(s['rows']),case_pairs=len(checks),guarded_worker_compatibility_rss_gate=s['passed'],
                full_family_memory_gate=False,attributable_full_family_peak_rss_bytes=None,summary_sha256=sha(path),
                limits=['Kernel prevents new process/thread creation after seal; initial descendants cannot be independently enumerated',
                        'Nonzero pre-numerical waited-child CPU is retained; only post-seal delta is checked zero',
                        'wait4 lifetime worker RSS; supervisor-plus-worker sum bounds those two measured processes only',
                        'No full-family, filesystem page cache, GPU, energy or production qualification'])


def main():
    result=dict(schema='hcsn.next-blockers.r2.independent-review.v1',created_utc=datetime.now(timezone.utc).isoformat(),
        review_source_sha256=sha(__file__),scope='Independent source reading, hidden-completion reference and saved-output arithmetic; not independent model retraining',
        blocker_map_sha256=sha(HERE/'BLOCKER_MAP.json'),lanes={},all_blockers_closed=False,production_activation=False,
        unresolved_critical_source_findings=[],interpretation_limits=[
            'New finite law/service tasks do not inherit old task acceptance',
            'Shared ordinary parsers and uniformization controls can match analytic methods; such equality is not hidden',
            'Historical raw-video development is not new population confirmation',
            'Hardware adoption requires actual target measurements'],resolved_findings=[
                dict(id='DYN_COUNT',resolution='Widened raw event counts to int64 and fail on overflow before adopted confirmation'),
                dict(id='DYN_INTERACTION',resolution='Legacy sequential cancellation flag invalid; independent grouped correction is exactly zero, both summaries retained'),
                dict(id='VIDEO_TARGET',resolution='Inherited emotion label was wrong target; failed training retained, corrected DFA/IOM labels and range/clip guards independently checked before eligible development'),
                dict(id='READ_RECEIPT',resolution='NaN timestamp and fractional-payload guards fixed before source freeze; independent receipt/clock/cache negatives pass'),
                dict(id='CPU_FAMILY',resolution='Unobservable initial descendants and nonzero pre-seal child counter retained; full-family peak stays null/HOLD'),
                dict(id='PERF_QUALIFICATION',resolution='Engineering completion/cardinality and exception cleanup required; final fresh timing gate remains separate')])
    for name,fn in [('missing_reliability',missing),('exact_transport',speed),('distribution_value',distribution),('raw_video',video),('cpu_envelope',cpu_envelope)]:
        try:result['lanes'][name]=fn()
        except Exception as exc:result['lanes'][name]=dict(status='failed_review',error=f'{type(exc).__name__}: {exc}')
    result['all_lane_evidence_checks_passed']=all(r['status']=='verified' for r in result['lanes'].values())
    (HERE/'INDEPENDENT_REVIEW.json').write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({k:v['status'] for k,v in result['lanes'].items()},sort_keys=True))


if __name__=='__main__':main()
