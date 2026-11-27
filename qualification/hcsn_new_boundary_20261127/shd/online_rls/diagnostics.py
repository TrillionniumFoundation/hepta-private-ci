"""Post-hoc magnitude and task-space accounting for already frozen online writes."""
from online import *
def main():
    out={};L=table();tr=splits('train')
    for seed in (409,571,647):
        s=dict(np.load(CROSS/'fits'/str(seed)/'parent.npz'));order,ends=stream(tr['gsc'],seed);hs=lower(tr['gsc'][0],s,L)
        take=order[::16];basew=s['w2'];before=logits(hs[take],s,L)
        raw=[]
        for ix in take:
            target=latent(hs[ix],basew,s,L,int(tr['gsc'][1][ix]));drive=hs[ix]@basew+s['b2']
            a=upper(drive[None],L).reshape(1,-1)@s['head']+s['bias'];z=upper((drive+target)[None],L).reshape(1,-1)@s['head']+s['bias'];y=tr['gsc'][1][ix]
            raw.append({'norm':float(np.linalg.norm(target)),'true_probability_difference':float(softmax(z[0])[y]-softmax(a[0])[y])})
        rows={}
        for arm in ('full','orth','noanchor','shuffled','feedback','Adam','LoRA'):
            p=HERE/'fits'/str(seed)/arm;w=np.load(p/'W2.npy');fit=json.loads((p/'fit.json').read_text());chosen=next((q for q in fit['front'] if q['cfg']==fit['selected']),None)
            rows[arm]={'weights_changed':int(np.sum(w!=basew)),'relative_matrix_change':float(np.linalg.norm(w-basew)/np.linalg.norm(basew)),
                       'latent_pre_drive_rms':float(np.sqrt(np.mean((hs[take]@(w-basew))**2))),
                       'terminal_logit_rms':float(np.sqrt(np.mean((logits(hs[take],s,L,w)-before)**2))),
                       'selection_stats':chosen['audited'] if chosen else None}
        out[seed]={'unconstrained_per_record_target_mean_norm':float(np.mean([q['norm'] for q in raw])),'unconstrained_mean_true_probability_gain':float(np.mean([q['true_probability_difference'] for q in raw])),'sampled_new_train':len(raw),'terminal':rows}
    dump(HERE/'diagnostics.json',out)
if __name__=='__main__':main()
