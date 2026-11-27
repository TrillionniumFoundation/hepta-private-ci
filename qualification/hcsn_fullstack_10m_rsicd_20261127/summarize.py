"""Rebuild token-weighted NLL, grounding and paired image uncertainty from cold arrays."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np

ARMS=('literal','smooth','no_wire','no_E','no_L','no_prices','lif','sdpa');SEEDS=(109,271,463)

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def interval(delta,counts):
    rng=np.random.default_rng(3142701);vals=[]
    for _ in range(40):
        idx=rng.integers(len(delta),size=(100,len(delta)));vals.extend(delta[idx].sum(1)/counts[idx].sum(1))
    return {'mean':float(delta.sum()/counts.sum()),'paired95':np.quantile(vals,[.025,.975]).tolist()}
def main(root):
    seal=json.loads((root/'seal.json').read_text());manifest=json.loads((root/'cold_manifest.json').read_text());per={};identities={};cx={}
    for arm in ARMS:
        for seed in SEEDS:
            ident=f'{arm}-{seed}';history=json.loads((root/'runs'/ident/'history.json').read_text());done=json.loads((root/'runs'/ident/'done.json').read_text());per[ident]={};identities[ident]={};cx[ident]={}
            for mode,state in seal[ident].items():
                if mode.startswith('steps'):
                    opts=[row for row in history if row['step']==int(mode[5:])]
                else:
                    clock='cpu' if mode.startswith('cpu') else 'wall';budget=int(mode[len(clock):]);opts=sorted((row for row in history if row[clock]<=budget),key=lambda r:(r['nll'],r[clock]))
                choice=opts[0] if opts else None;assert choice==state
                if state is None:continue
                key=state['sha'];path=root/'cold'/(key+'.npz');assert manifest[path.name]==sha(path)
                with np.load(path) as z:
                    labels=z['rows'];counts=z['counts'];assert counts.sum()==11756 and len(labels)==964
                    per[ident][mode]=(z['matched'],z['shifted'],counts);identities[ident][mode]={'state':key,'dev_nll':state['nll'],'step':state['step'],'train_tokens':state['train_tokens'],'cpu_s':state['cpu'],'wall_s':state['wall'],'heldout_nll':float(z['matched'].sum()/counts.sum())}
            for level in (4.5,4.,3.5,3.):
                for clock in ('cpu','wall'):
                    eligible=[row for row in history if row[clock]<=300];last=0.;hit=None
                    for row in eligible:
                        if row['nll']<=level:hit=[last,row[clock]];break
                        last=row[clock]
                    cx[ident][f'{clock}-{level}']={'interval':hit,'last_observation':last,'available':done['elapsed'][clock]}
    aggregates={}
    for mode in ('cpu60','cpu180','cpu300','wall60','wall180','wall300','steps4','steps16'):
        combined={};summ={}
        for arm in ARMS:
            ids=[f'{arm}-{seed}' for seed in SEEDS];parts=[per[k][mode] for k in ids if mode in per[k]]
            if len(parts)<3:summ[arm]={'completed':len(parts)};continue
            count=parts[0][2];assert all(np.array_equal(count,x[2]) for x in parts)
            matched=np.mean([x[0] for x in parts],axis=0);shifted=np.mean([x[1] for x in parts],axis=0);combined[arm]=matched
            summ[arm]={'matched_nll':float(matched.sum()/count.sum()),'shifted_nll':float(shifted.sum()/count.sum()),'grounding':interval(shifted-matched,count),'completed':3}
        differences={other:interval(combined['literal']-v,count) for other,v in combined.items() if other!='literal' and 'literal' in combined}
        aggregates[mode]={'arms':summ,'literal_minus_other':differences}
    for mode in ('steps4','steps16'):
        for seed in SEEDS:
            vals=[identities[f'{a}-{seed}'][mode]['train_tokens'] for a in ARMS if mode in identities[f'{a}-{seed}']];assert len(set(vals))<=1
    info={'full':aggregates,'by_cell':identities,'validation_crossings':cx,'gallery':964,'caption_tokens':11756,'seal_sha':sha(root/'seal.json'),'cold_manifest_sha':sha(root/'cold_manifest.json'),'states':len(manifest)}
    (root/'summary.json').write_text(json.dumps(info,indent=1,allow_nan=False));print('states',len(manifest),'300 CPU',aggregates['cpu300'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root)
