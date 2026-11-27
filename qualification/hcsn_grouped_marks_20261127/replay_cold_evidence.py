"""Independently reconstruct all 5,000-draw paired seed/image comparisons from a portable pack."""
import argparse,hashlib,json,math,tarfile
from pathlib import Path
import numpy as np


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def replay(folder,output):
    pack=folder/'heldout_losses.npz';meta=json.loads((folder/'heldout_index.json').read_text());receipts=folder/'training_receipts.tar.gz'
    assert sha(pack)==meta['packed_losses_sha256'] and sha(receipts)==meta['training_receipts_sha256']
    with tarfile.open(receipts,'r:gz') as tar:
        final_bytes=tar.extractfile('final.json').read();assert hashlib.sha256(final_bytes).hexdigest()==meta['final_sha256'];official=json.loads(final_bytes)
        seal=tar.extractfile('evaluation_seal.json').read();assert hashlib.sha256(seal).hexdigest()==meta['evaluation_seal'];assignments=json.loads(seal)['assignments']
        inputs=json.loads(tar.extractfile('tuning_seal.json').read());assert inputs['control']==meta['primary_control']
    fits={(v['arm'],v['seed']):v for v in meta['fits']};assert len(fits)==72 and len(assignments)==72
    arms=sorted({k[0] for k in fits});seeds=sorted({k[1] for k in fits});assert len(arms)==6 and len(seeds)==12
    raw=np.load(pack,allow_pickle=False);arrays={k:raw[k] for k in raw.files};raw.close();m=meta['states'];assert len(arrays['states'])==m
    states=arrays['states'];bound_arms=arrays['state_arms'];counts=arrays['test_counts'];loss=arrays['test_sum'];gain=arrays['test_swapped']-loss
    assert loss.shape==gain.shape==(m,800) and arrays['development_sum'].shape==(m,320)
    assert len(set(arrays['test_ids'])&set(arrays['development_ids']))==0 and int(counts.sum())==meta['counts']['test']
    for (arm,seed),rec in fits.items():
        name=f"{arm}-{seed}-{inputs['rates'][arm]:.4g}";assert rec['assignments']==assignments[name]['assignment'] and rec['complete_sha256']==assignments[name]['complete']
        for state,data in rec['original_arrays'].items():
            i=rec['model_indices'][state];assert states[i].decode()==state and bound_arms[i].decode()==arm
            for field,digest in data['array_sha256'].items():
                field_array=arrays[field][i] if field.endswith(('_sum','_swapped')) else arrays[field]
                assert hashlib.sha256(field_array.tobytes(order='C')).hexdigest()==digest
    def row(arm,seed,axis):
        f=fits[arm,seed];a=f['assignments'].get(axis)
        return None if a is None else (f['model_indices'][a['state']],a['seconds'])
    worst=0.;comparisons=0;split_stats={};axes=['best','0','1','2']
    for arm in arms:
        split_stats[arm]={}
        for axis in axes:
            members=[row(arm,s,axis) for s in seeds];present=[s for s,r in zip(seeds,members) if r is not None];idx=[r[0] for r in members if r is not None]
            old=official['arms'][arm][axis];assert old['attained']==len(idx)
            stats={}
            if idx:
                for split in ('development','test'):
                    n=arrays[split+'_counts'];s=arrays[split+'_sum'][idx].mean(0);shift=arrays[split+'_swapped'][idx].mean(0);nll=float(s.sum()/n.sum())
                    stats[split]={'nll':nll,'perplexity':math.exp(nll),'conditioning_gain':float((shift-s).sum()/n.sum()),'tokens_per_fit':int(n.sum())}
                worst=max(worst,abs(stats['test']['nll']-old['test_nll']),abs(stats['test']['conditioning_gain']-old['conditioning_gain']))
                for s,i in zip(present,idx):worst=max(worst,abs(loss[i].sum()/counts.sum()-old['per_seed'][str(s)]['nll']))
            stats['attained']=len(idx);split_stats[arm][axis]=stats
    contrasted={}
    for baseline in [a for a in arms if a!='grouped_hcsn']:
        contrasted[baseline]={}
        for axis in axes:
            pairs=[(s,row('grouped_hcsn',s,axis),row(baseline,s,axis)) for s in seeds];pairs=[p for p in pairs if p[1] is not None and p[2] is not None]
            old=official['contrasts'][baseline][axis];assert old['paired_n']==len(pairs);record={'paired_seeds':[p[0] for p in pairs]};contrasted[baseline][axis]=record
            if not pairs:continue
            ia=[r[1][0] for r in pairs];ib=[r[2][0] for r in pairs];k=len(pairs);d=loss[ia]-loss[ib];gain_a=gain[ia];logr=np.log([r[2][1]/r[1][1] for r in pairs]);values=[]
            # Consume the registered PRNG order, but implement resampling using multinomial counts
            # and two matrix products, separately from the official gather-by-index implementation.
            gen=np.random.default_rng(2026112719)
            for _ in range(50):
                si=gen.integers(k,size=(100,k));ii=gen.integers(800,size=(100,800))
                seed_counts=np.asarray([np.bincount(a,minlength=k) for a in si],dtype=np.float64)/k
                image_counts=np.asarray([np.bincount(a,minlength=800) for a in ii],dtype=np.float64)
                denom=image_counts@counts;gaps=np.sum((seed_counts@d)*image_counts,axis=1)/denom
                gains=np.sum((seed_counts@gain_a)*image_counts,axis=1)/denom
                ratios=np.exp(seed_counts@logr);values.append(np.column_stack([gaps,gains,ratios]))
            quant=np.quantile(np.vstack(values),[.025,.975],axis=0)
            candidate={'nll_difference':float(d.mean(0).sum()/counts.sum()),'conditioning_gain':float(gain_a.mean(0).sum()/counts.sum()),'comparator_over_grouped_first_observed':float(np.exp(logr.mean())),
                       'paired_nll_95':quant[:,0].tolist(),'conditioning_95':quant[:,1].tolist(),'time_ratio_seed_95':quant[:,2].tolist()}
            for n,v in candidate.items():worst=max(worst,float(np.max(np.abs(np.asarray(v)-np.asarray(old[n])))))
            record.update(candidate);comparisons+=1
    primary=contrasted[meta['primary_control']]['0'];n=len(primary['paired_seeds'])
    criteria={'attained_in_both_at_least_10':n>=10,'heldout_noninferiority':bool(n and primary['paired_nll_95'][1]<=.02),'speed_lower_above_one':bool(n and primary['time_ratio_seed_95'][0]>1.),'speed_point_at_least_one_tenth_faster':bool(n and primary['comparator_over_grouped_first_observed']>=1.10),'positive_conditioning':bool(n and primary['conditioning_gain']>0.)}
    assert criteria==official['criteria'] and all(criteria.values())==official['passes'] and worst<1e-9
    answer={'source_sha256':sha(Path(__file__)),'official_final_sha256':meta['final_sha256'],'unique_model_states':m,'direct_pairs_with_data':comparisons,'largest_replay_disagreement':worst,'cohorts':meta['counts'],'arms':split_stats,'paired':contrasted,'primary':primary,'criteria':criteria,'passes':all(criteria.values())}
    output.write_text(json.dumps(answer,sort_keys=True,allow_nan=False,indent=2)+'\n');print('verified',m,comparisons,worst,criteria)


if __name__=='__main__':
    c=argparse.ArgumentParser();c.add_argument('folder',type=Path);c.add_argument('output',type=Path);args=c.parse_args();replay(args.folder,args.output)
