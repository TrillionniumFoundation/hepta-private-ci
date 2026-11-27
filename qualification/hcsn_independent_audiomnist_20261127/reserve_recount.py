"""Recompute 40-speaker transfer and uncertainty from raw, unopened reserve vectors."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('reserve',type=Path);p.add_argument('primary',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    scope=json.loads((a.reserve/'SUMMARY.json').read_bytes());pri=json.loads(a.primary.read_bytes())
    assert digest(a.reserve/'source.tsv')==scope['scope']['source_manifest']
    names=[r.split('\t')[0] for r in (a.reserve/'source.tsv').read_text().splitlines()]
    recorded={}
    with np.load(a.reserve/'reference.npz') as ref:
        y=ref['y'];sp=ref['speaker'];ids=ref['record'];assert names==list(ids) and len(set(ids))==len(y)
        speakers=sorted(set(sp));assert len(speakers)==40 and len(y)+len(scope['scope']['duplicate_pcm'])==4800
        for model,df in scope['prediction_hashes'].items():
            f=a.reserve/(model+'.npz');assert digest(f)==df
            with np.load(f) as zz:z=zz['scores']
            assert z.shape==(len(y),10);ok=z.argmax(1)==y
            group=[float(ok[sp==s].mean()) for s in speakers]
            assert all(abs(j-k)<1e-13 for j,k in zip(group,scope['per_model'][model]['new']['by_speaker'].values()))
            recorded[model]=group
    rng=np.random.default_rng(12089);rng.integers(6,size=(20000,6));draw=rng.integers(40,size=(20000,40))
    both=np.random.default_rng(73319);sel_s=both.integers(3,size=(20000,3));sel_p=both.integers(40,size=(20000,40))
    checked={};seeds=(271,577,911)
    for arm,ref in [(a,'keep') for a in ('direct','bp','lora','wrong')]+[('direct',v) for v in ('bp','lora','wrong')]:
        effects=np.array([np.array(recorded[f'{arm}_{s}_45'])-np.array(recorded[f'{ref}_{s}_{0 if ref=="keep" else 45}']) for s in seeds])
        delta=100*effects.mean();ci=100*np.quantile(effects.mean(0)[draw].mean(1),[.025,.975])
        target=scope['vs_keep'][arm]['new'] if ref=='keep' else scope['direct_minus'][ref]['new']
        assert abs(target['delta_pp']-delta)<1e-10 and np.allclose(target['cluster_bootstrap95_pp'],ci,atol=1e-10)
        two_way=np.array([effects[si[:,None],pi[None,:]].mean() for si,pi in zip(sel_s,sel_p)])
        old=scope['vs_keep'][arm]['old'] if ref=='keep' else scope['direct_minus'][ref]['old']
        old_primary=pri['vs_keep'][arm+'_45']['old'] if ref=='keep' else pri['paired_arms']['direct_minus_'+ref+'_45']['old']
        assert abs(old['delta_pp']-old_primary['delta_pp'])<1e-10
        checked[arm+'_minus_'+ref]={'speaker_paired_ci95_pp':ci.tolist(),'paired_seed_and_speaker_ci95_pp':(100*np.quantile(two_way,[.025,.975])).tolist(),'delta_pp':float(delta),'per_seed_delta_pp':(100*effects.mean(1)).tolist()}
    out={'speakers':40,'recordings':len(y),'score_entries':len(recorded)*len(y)*10,'summary_sha256':digest(a.reserve/'SUMMARY.json'),'checked':checked}
    a.output.write_text(json.dumps(out,sort_keys=True,indent=1)+'\n')
    print('verified',out['score_entries'],'class scores',len(checked),'effects')


if __name__=='__main__':main()
