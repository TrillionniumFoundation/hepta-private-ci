"""Cold full-score independent direct-law replay. Verify two boundary values and source IDs."""
import argparse,hashlib,json,time,sys
from core import HERE,T,H,KAPPA,DATA,sha,splits,table
from confirm import canonical
from scipy.linalg import svdvals
import numpy as np
sys.path.insert(0,str(HERE.parent/'uji'));from verify import law
anchor=law(0.)
def A(x):return law(x)-anchor
def fb(a):return .4*np.tanh(a[...,0])+.4*np.tanh(a[...,1])
def B(x):return np.log1p(KAPPA*np.tanh(x))/KAPPA
def lower(x,p):
    x=x.astype('f8');z=x@p['w1']+p['b1'];hidden=[];old=0.
    for n in range(T):
        driven=z[:,n]+old;old=fb(A(driven));hidden.append(np.concatenate([B(driven),B(z[:,n]+old)],axis=-1))
    return np.stack(hidden,axis=1)
def upper(h,p,w):
    us=h@w+p['b2'];old=0.;out=[]
    for t in range(T):
        a=A(us[:,t]+old);old=fb(a);out.append(a)
    return np.stack(out,axis=1).reshape(len(h),-1)@p['head']+p['bias']
def geom(h):
    h=h.reshape(-1,2*H);h-=h.mean(0);v=svdvals(h);e=v*v/(v@v)
    first=h[:,:H];later=h[:,H:];prior=first@np.linalg.lstsq(first,later,rcond=None)[0]
    return {'effective_entropy_rank':float(np.exp(-np.sum(e*np.log(np.maximum(e,1e-300))))),'stable_rank':float(1/e[0]),
            'rank_1e-5':int(np.sum(v>1e-5*v[0])),'rank_99pct_energy':int(np.searchsorted(np.cumsum(e),.99)+1),
            'relative_post_residual_from_all_first_linear':float(np.linalg.norm(later-prior)/np.linalg.norm(later))}
def main():
    start=time.perf_counter();r=json.loads((HERE/'results.json').read_text());te=canonical('test',splits('test'));checks={};geoms={};seen=0
    for seed in (409,571,647):
        p=dict(np.load(HERE/'fits'/str(seed)/'parent.npz'));dh={k:lower(o[0],p) for k,o in te.items()}
        geoms[seed]={k:geom(h.copy()) for k,h in dh.items()};cache={}
        for name,oldsha in r['cold_files'].items():
            if not name.startswith(str(seed)+'-'):continue
            loc=HERE/'cold'/name;assert sha(loc)==oldsha
            _,arm,route=loc.stem.split('-');w=np.load(HERE/'fits'/str(seed)/arm/(route+'.npz'))['w2'];key=hashlib.sha256(w.tobytes()).hexdigest()
            if key not in cache:cache[key]={k:upper(h,p,w) for k,h in dh.items()}
            with np.load(loc) as pred:
                for k,rows in te.items():
                    _,y,sp,ids=rows;z=pred[k+'_scores'];other=cache[key][k]
                    assert np.array_equal(y,pred[k+'_y']) and np.array_equal(ids,pred[k+'_id']) and np.array_equal(sp,pred[k+'_speaker'])
                    seen+=z.size;correct=z.argmax(1)==y;record=r['cold'][loc.stem][k];assert abs(record['acc']-correct.mean())<1e-12
                    assert abs(record['macro']-np.mean([correct[sp==s].mean() for s in sorted(set(sp))]))<1e-12
                    checks[loc.stem+'/'+k]={'max_abs':float(abs(z-other).max()),'class_changes':int((z.argmax(1)!=other.argmax(1)).sum()),'rows':len(z)}
    out={'model_selections':42,'class_scores':seen,'verified_source_metrics':len(checks),'max_abs':max(s['max_abs'] for s in checks.values()),
         'argmax_changes':sum(s['class_changes'] for s in checks.values()),'geometry':geoms,'per_selection':checks,'seconds':time.perf_counter()-start}
    (HERE/'independent.json').write_text(json.dumps(out,indent=2)+'\n');print({k:v for k,v in out.items() if k not in ('geometry','per_selection')},flush=True)
if __name__=='__main__':main()
