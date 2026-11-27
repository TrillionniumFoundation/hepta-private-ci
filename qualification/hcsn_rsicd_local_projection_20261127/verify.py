"""Recompute token-weighted quality, image grounding and frontiers using original score arrays."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

SEEDS=(109,271,463);ARMS=('forward','shuffle','feature_only','tied_only','frozen_probe')
SLOTS=('step0','step4','step16','wall_s60','wall_s180','wall_s300','cpu_s60','cpu_s180','cpu_s300')


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def save(p,v):Path(p).write_text(json.dumps(v,sort_keys=True,indent=1,allow_nan=False)+'\n')
def summary(z):
    a,b,n=z['matched'],z['shifted'],z['counts'];delta=b-a
    return {'target_nll':float(a.sum()/n.sum()),'shifted_nll':float(b.sum()/n.sum()),'shift_minus_match':float(delta.sum()/n.sum()),
            'matched_image_preferred_fraction':float((delta>0).mean()),'matched_equals_shifted_fraction':float((delta==0).mean()),'counts':int(n.sum())}


def main():
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('out',type=Path);a.add_argument('--bp',type=Path);p=a.parse_args()
    w=p.work;sealed=read(w/'SEAL.json');roster=read(w/'cold/roster.json');cf=read(w/'prepared.json')
    dist={};meta={};n=None;ids=None;narrays=0;uniques={};controls=list(ARMS)
    for arm in ARMS:
        for seed in SEEDS:
            dr=w/'fits'/f'{arm}-{seed}';done=read(dr/'done.json');hist=read(dr/'history.json')
            assert sha(dr/'done.json')==sealed['fits'][dr.name]['receipt'] and sha(dr/'history.json')==sealed['fits'][dr.name]['history']
            for slot,key in roster[dr.name].items():
                f=w/'cold'/(key+'.npz');receipt=read(f.with_suffix('.json'));assert sha(f)==receipt['npz_sha256'] and receipt['seal_sha256']==sha(w/'SEAL.json')
                with np.load(f) as q:z=dict(q)
                if n is None:n=z['counts'];ids=z['ids']
                assert np.array_equal(n,z['counts']) and np.array_equal(ids,z['ids']) and np.array_equal(z['shift'],np.roll(ids,1))
                d=done['selected'][slot];dist[arm,seed,slot]=z
                used=done['fit_development_save_total_wall']
                if slot.startswith(('wall_s','cpu_s')):
                    clk=next(k for k in ('wall_s','cpu_s') if slot.startswith(k));cut=int(slot[len(clk):]);later=[r['wall_s'] for r in hist if r[clk]>cut]
                    used=min(later+[used])
                elif slot.startswith('step'):used=d['wall_s']
                meta[arm,seed,slot]={**summary(z),'prefix':d['prefix'],'train_target_tokens':d['train_tokens'],
                    'all_paid_selection_upper_wall_s':used,'end_to_end_upper_s':cf['total_wall_s']+done['setup_process_wall']+used+receipt['cold_model_reconstruction_wall_s']+receipt['matched_inference_wall_s'],
                    'dev_nll':d['dev_token_nll']}
                uniques[key]=2*len(n);narrays+=2
    if p.bp:
        br=read(p.bp/'index.json')
        for (arm,typ) in [('literal_bp','literal'),('causal_sdpa_bp','sdpa')]:
            controls.append(arm)
            for seed in SEEDS:
                for slot,rec in br[typ+'-'+str(seed)].items():
                    if slot not in SLOTS:continue
                    f=p.bp/(rec['sha']+'.npz');assert sha(f)==rec['archive_sha256']
                    with np.load(f) as q:z=dict(q)
                    assert np.array_equal(z['counts'],n) and np.array_equal(z['rows'],ids)
                    dist[arm,seed,slot]=z
                    meta[arm,seed,slot]={**summary(z),'prefix':rec['step'],'train_target_tokens':rec['train_tokens'],'all_paid_selection_upper_wall_s':rec['selection_wall_upper'],'end_to_end_upper_s':rec['end_to_end_upper_s'],'dev_nll':rec['nll']}
    rng=np.random.default_rng(46503);b=8000
    draws=rng.multinomial(len(n),np.ones(len(n))/len(n),b)/len(n)
    sr=rng.multinomial(3,[1/3]*3,b)/3
    denom=draws@n
    def boot(x):
        by_seed=x.sum(1)/n.sum();g=x.mean(0);a0=(draws@g)/denom;a1=np.einsum('bi,ij,bj->b',sr,x,draws,optimize=True)/denom
        return {'delta_nats':float(by_seed.mean()),'by_seed_nats':by_seed.tolist(),'paired_image_ci95':np.quantile(a0,[.025,.975]).tolist(),'paired_image_and_seed_ci95':np.quantile(a1,[.025,.975]).tolist()}
    curves={};compare={};frontiers={}
    for k in controls:
        curves[k]={};frontiers[k]={}
        for slot in SLOTS:
            if not all((k,s,slot) in meta for s in SEEDS):continue
            rs=[meta[k,s,slot] for s in SEEDS]
            curves[k][slot]={f:float(np.mean([r[f] for r in rs])) for f in ('target_nll','shifted_nll','shift_minus_match','matched_image_preferred_fraction','matched_equals_shifted_fraction','all_paid_selection_upper_wall_s','end_to_end_upper_s')}
            curves[k][slot]['per_seed']=rs
            diff=np.stack([dist[k,s,slot]['shifted']-dist[k,s,slot]['matched'] for s in SEEDS])
            curves[k][slot]['shift_minus_match_paired']=boot(diff)
            if k!='forward' and all(('forward',s,slot) in dist for s in SEEDS):
                diff=np.stack([dist['forward',s,slot]['matched']-dist[k,s,slot]['matched'] for s in SEEDS])
                compare[k+'_'+slot]=boot(diff)
        for tag in ('wall_s','cpu_s'):
            frontiers[k][tag]={}
            for goal in (4.5,4.,3.5,3.):
                ok=[t for t in (60,180,300) if tag+str(t) in curves[k] and max(r['target_nll'] for r in curves[k][tag+str(t)]['per_seed'])<=goal]
                frontiers[k][tag][str(goal)]=None if not ok else {'first_prefix_s':min(ok),'mean_end_to_end_upper_s':curves[k][tag+str(min(ok))]['end_to_end_upper_s']}
    assert len(n)==964 and n.sum()==11756
    save(p.out,{'scope':{'source_images':len(n),'target_words':int(n.sum()),'seeds':SEEDS,'distinct_local_score_states':len(uniques),'original_local_image_loss_sums':sum(uniques.values()),'local_repeated_budget_score_vectors':narrays,'bootstrap_draws':b,'bp_imported':bool(p.bp),'seal_sha256':sha(w/'SEAL.json')},'curves':curves,'paired_forward_minus_control':compare,'all_seed_external_frontier':frontiers})


if __name__=='__main__':main()
