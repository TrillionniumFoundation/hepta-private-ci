"""Post-primary reanalysis of the normalized-PCA arm with actual whitening."""
import shutil
import numpy as np
import edit_speech as ed
from core import HERE,splits,table,lower,logits,summarize,sha,dump
from confirm import canonical,d_ci

def white(new,old,mode,seed):
    if mode!='white':return ed._initial_axes(new,old,mode,seed)
    h=ed.balanced_keys(new);S=h.T@h/len(h);v,U=np.linalg.eigh(S)
    order=np.argsort(v)[::-1][:16];ridge=.1*np.trace(S)/len(S)
    Q=(U[:,order]/np.sqrt(v[order]+ridge)).T
    return (Q/np.sqrt(np.mean(np.sum(Q*Q,axis=1)))).astype('f4')
def main():
    original=ed.axes;ed._initial_axes=original;ed.axes=white
    selected={};root=HERE/'whitening';root.mkdir(exist_ok=True)
    for seed in (409,571,647):
        d=root/str(seed);d.mkdir(exist_ok=True);shutil.copyfile(HERE/'fits'/str(seed)/'parent.npz',d/'parent.npz')
        ed.run(d,seed,'white')
        for route in ('point','confidence'):selected[f'{seed}-{route}']=sha(d/'white'/(route+'.npz'))
    dump(root/'selected.json',selected)
    te=canonical('test',splits('test'));L=table();rows={}
    for seed in (409,571,647):
        d=root/str(seed);s=dict(np.load(d/'parent.npz'))
        for route in ('point','confidence'):
            w=np.load(d/'white'/(route+'.npz'))['w2'];stats={};store={}
            for k,dd in te.items():
                h=lower(dd[0],s,L);z=logits(h,s,L,w);base=summarize(logits(h,s,L),dd);res=summarize(z,dd)
                stats[k]={'macro':res['macro'],'delta':d_ci(res['by_speaker'],base['by_speaker'])};store[k]=z
            np.savez_compressed(d/(route+'-scores.npz'),**store)
            rows[f'{seed}-{route}']=stats
    dump(root/'result.json',rows)
    for route in ('point','confidence'):print('corrected',route,[(k,round(100*np.mean([rows[f'{s}-{route}'][k]['delta']['d'] for s in (409,571,647)]),2)) for k in te],flush=True)
if __name__=='__main__':main()
