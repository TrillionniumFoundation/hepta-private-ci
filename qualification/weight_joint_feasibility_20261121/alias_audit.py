"""Post-result exact-input alias scan; zero forwards, no optimization."""
from pathlib import Path
import gzip
import hashlib
import json
import resource
import time
import numpy as np

ROOT=Path(__file__).resolve().parent


def read(path):
    path=Path(path);b=path.read_bytes();return json.loads(gzip.decompress(b) if path.suffix=='.gz' else b)


def main():
    start=time.process_time();out=ROOT/'posthoc_alias';out.mkdir(exist_ok=False)
    p=read(ROOT/'PROTOCOL_FROZEN.json');summaries=[];complete=True
    for fit in p['fits']:
        if time.process_time()>1.65:complete=False;break
        spec=p['inputs'][str(fit)];rec=read(spec['reconstruction'])
        for key in ('data','teacher','discovery_arrays','reconstruction'):
            raw=Path(spec[key]).read_bytes();pin=p['files'][spec[key]]
            assert len(raw)==pin['bytes'] and hashlib.sha256(raw).hexdigest()==pin['sha256']
        with np.load(spec['data'],allow_pickle=False) as z:X=z['X'];masks=z['legal_masks'];uniform=z['belief_weights']
        with np.load(spec['teacher'],allow_pickle=False) as z:Q=z['own_optimal_targets'][:,:3];post=z['own_posterior']
        with np.load(spec['discovery_arrays'],allow_pickle=False) as z:occupancy=z['incumbent_eligible_occupancy'];gap=z['own_action_gap'];target=z['own_actions']
        own=np.column_stack([np.zeros(len(X)),Q,1-2*post,2*post-1]);assert np.array_equal(np.where(masks,own,-np.inf).argmax(1),target)
        assert X.dtype==np.float64 and np.isfinite(X).all()
        boundaries=np.cumsum([0]+[w['rows'] for w in rec['reconstructed_worlds']]);assert boundaries[-1]==len(X)
        worlds=np.repeat(np.arange(64),np.diff(boundaries));groups={}
        for row in range(len(X)):
            key=X[row].tobytes()+masks[row].tobytes()
            groups.setdefault(key,[]).append(row)
        conflicts=[];aggregate={name:dict(total=float(w.sum()),involved_mass=0.,minimum_unavoidable_exact_target_disagreement=0.,minimum_unavoidable_own_Q_regret=0.) for name,w in [('uniform',uniform),('C_eligible_occupancy',occupancy),('C_eligible_occupancy_times_own_gap',occupancy*gap)]}
        weightsets={'uniform':uniform,'C_eligible_occupancy':occupancy,'C_eligible_occupancy_times_own_gap':occupancy*gap}
        duplicate_groups=0;alias_states=0;crossworld=0;positive_occ_states=0;robust_regret_groups=0
        for key,items in groups.items():
            if len(items)<2:continue
            duplicate_groups+=1;ix=np.asarray(items,dtype=np.int64);targets=target[ix]
            if len(np.unique(targets))<2:continue
            alias_states+=len(ix);positive_occ_states+=int(np.count_nonzero(occupancy[ix]>0))
            cross=bool(len(np.unique(worlds[ix]))>1);crossworld+=int(cross)
            legal=np.flatnonzero(masks[ix[0]])
            regrets=np.maximum(0.,own[ix,targets,None]-own[ix][:,legal])
            unweighted_min=float(regrets.sum(0).min());robust=bool(unweighted_min>1e-10);robust_regret_groups+=int(robust)
            metrics={}
            for name,w in weightsets.items():
                ww=w[ix];mass=float(ww.sum());counts=np.bincount(targets,weights=ww,minlength=6)
                missed=max(0.,mass-float(counts.max()))
                regret=float((ww[:,None]*regrets).sum(0).min())
                metrics[name]=dict(involved_mass=mass,minimum_unavoidable_exact_target_disagreement=missed,minimum_unavoidable_own_Q_regret=regret)
                for field in metrics[name]:aggregate[name][field]+=metrics[name][field]
            details=[]
            for row in ix:
                wi=int(worlds[row]);wr=rec['reconstructed_worlds'][wi]
                details.append(dict(row=int(row),world_id=wr['world_id'],local_row=int(row-boundaries[wi]),
                    state_order_sha256=wr['state_order_sha256'],target=int(target[row]),own_scores=own[row].tolist(),
                    normalized_C_eligible_occupancy=float(occupancy[row]),own_action_gap=float(gap[row])))
            conflicts.append(dict(input_bytes_sha256=hashlib.sha256(key[:-6]).hexdigest(),full_key_sha256=hashlib.sha256(key).hexdigest(),
                same_mask=masks[ix[0]].tolist(),cross_world=cross,rows=details,metrics=metrics,
                common_exact_optimal_actions=legal[np.all(regrets==0.,axis=0)].tolist(),
                minimum_unweighted_own_Q_regret=unweighted_min,positive_regret_exact=bool(unweighted_min>0.),
                regret_exceeds_1e_minus10=robust))
        for name,v in aggregate.items():
            for field in ('involved_mass','minimum_unavoidable_exact_target_disagreement','minimum_unavoidable_own_Q_regret'):
                v[field+'_fraction_of_weight']=v[field]/v['total'] if v['total'] else None
        result=dict(fit=fit,rows=len(X),groups=len(groups),duplicate_groups=duplicate_groups,
            conflicting_groups=len(conflicts),cross_world_conflicting_groups=crossworld,
            conflicting_states=alias_states,conflicting_positive_occupancy_states=positive_occ_states,
            conflicting_groups_with_min_regret_above_1e_minus10=robust_regret_groups,
            weighted=aggregate,conflicts=conflicts,
            conclusion_scope='Exact X85 bytes plus identical legal mask. Different targets contradict exact deterministic target matching; only positive own-Q regret indicates unavoidable local value loss. No end-to-end gain/loss inferred.',
            different_mask_groups_not_analyzed=True,source_inputs={k:{'path':spec[k],**p['files'][spec[k]]} for k in ('data','teacher','discovery_arrays','reconstruction')})
        with (out/f'fit_{fit}.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
        summaries.append({k:v for k,v in result.items() if k!='conflicts'})
        del X,masks,groups,conflicts,own,Q,post
    result=dict(schema='hepta-input-alias-posthoc-v1',status='COMPLETED' if complete and len(summaries)==5 else 'PARTIAL_FROZEN_CPU_BUDGET',
        posthoc=True,model_forwards=0,optimizer_calls=0,strict_byte_grouping=True,fits=summaries,
        CPU_seconds=time.process_time(),body_CPU_seconds=time.process_time()-start,
        peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        same_fit_only=True,cross_fit_conflicts_not_used=True,
        no_exact_target_mismatch_as_value_loss_claim=True,
        no_universal_impossibility_claim_without_actual_conflicting_groups=True)
    with (out/'SUMMARY.json').open('x') as f:json.dump(result,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
    print(json.dumps({'status':result['status'],'CPU_seconds':result['CPU_seconds'],'completed_fits':len(summaries),'conflicting_groups':[x['conflicting_groups'] for x in summaries]}))


if __name__=='__main__':main()
