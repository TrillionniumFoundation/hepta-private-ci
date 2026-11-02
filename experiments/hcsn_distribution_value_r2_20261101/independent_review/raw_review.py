"""Independent training/raw-fee/contrast audit, including cancellation correction.

No campaign, controller, model, world, scorer or analysis module is imported.
The audit reconstructs saved records without opening new simulated worlds.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]

def load(path): return json.loads(Path(path).read_text())

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def close(actual,expected):
    if actual is None or expected is None: assert actual is expected
    else: assert np.allclose(actual,expected,rtol=1e-10,atol=1e-12), (actual,expected)

def nested_close(actual,expected):
    assert actual.keys()==expected.keys()
    for key,value in expected.items():
        if isinstance(value,dict): nested_close(actual[key],value)
        else: close(actual[key],value)

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

def main():
    result=distribution()
    if result['status']!='verified':raise RuntimeError('Complete corrected evidence required: '+str(result))
    result.update(schema='hcsn.distribution-value-r2.independent-raw-review.v1',review_cpu_seconds=None,
        audit_source_sha256=sha(__file__),scope='Independent saved-source/training/trajectory fee and arithmetic reconstruction, not policy rerun or new confirmation')
    with (HERE/'RAW_REVIEW.json').open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(status=result['status'],raw_files=result['raw_files'],record_checks=result['record_checks'],rollout_records=result['rollout_records'],interaction_correction_verified=result['interaction_reporting_correction']['verified']),sort_keys=True))

if __name__=='__main__':main()
