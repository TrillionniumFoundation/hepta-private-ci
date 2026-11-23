"""Explain the registered TEST policies by actual purchase decisions on paired recordings."""
import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .frontend import dump


def explain(s,action,time):
    action=np.asarray(action)
    chosen_time=np.asarray(time)
    free=s['scores'].argmax(-1)==s['target'][:,None]
    paid=s['read_scores'].argmax(-1)==s['target'][:,None]
    i=np.arange(len(action))
    f,p=free[i,chosen_time],paid[i,chosen_time]
    elapsed=s['dt'].cumsum(-1)-s['dt'][:,:1]
    disc=np.exp(-.20*elapsed)
    running=2.*np.expm1(-.2*elapsed)
    u0=free*disc+running
    u1=(paid.astype(float)-.30)*disc+running
    possible=np.maximum(u0.max(-1),u1.max(-1))-u0.max(-1)
    wmax=np.maximum(u0.max(-1),u1.max(-1))-np.maximum(u0[:,0],u1[:,0])
    price_effect=u1[i,chosen_time]-u0[i,chosen_time]
    def npair(j):
        return 'rescued' if p[j] and not f[j] else 'broke' if f[j] and not p[j] else 'already_correct' if f[j] else 'both_wrong'
    examples=[dict(query=str(s['query_id'][j]),creator=str(s['group'][j]),source=str(s['source'][j]),
                   label=int(s['target'][j]),prefix=int(chosen_time[j])+1,action='READ' if action[j]==1 else 'STOP',
                   free_guitar_probability=float(s['scores'][j,chosen_time[j],1]),
                   margin=float(abs(s['scores'][j,chosen_time[j],1]-s['scores'][j,chosen_time[j],0])),
                   paid_change=npair(j),net_paid_gain_at_exit=float(price_effect[j]),
                   future_knowledge_paid_opportunity=float(possible[j]),future_knowledge_wait_opportunity=float(wmax[j]))
              for j in i]
    reads=action==1
    bins=[]
    # Same fixed thresholds on the free class probability across all models and methods.
    margin=np.abs(s['scores'][:,:,1]-s['scores'][:,:,0])
    for lo,hi in [(0,.25),(.25,.50),(.50,.75),(.75,1.0000001)]:
        m=(margin[:,0]>=lo)&(margin[:,0]<hi)
        groups=s['group']
        def sm(v):
            return float(np.mean([v[m&(groups==g)].mean() for g in np.unique(groups[m])])) if m.any() else None
        bins.append(dict(first_margin_lo=lo,first_margin_hi=min(hi,1),n=int(m.sum()),groups=len(np.unique(groups[m])),
                         first_net_read_advantage=sm(u1[:,0]-u0[:,0]),ever_read_rate=sm(reads),
                         wait_rate=sm(chosen_time>0)))
    return dict(queries=len(s['target']),reads=int(reads.sum()),wait_queries=int((chosen_time>0).sum()),
                paid_increment_possible_queries=int((possible>1.e-12).sum()),
                bought_among_possible=int((reads&(possible>1.e-12)).sum()),
                chosen_reads_at_exit=dict(Counter(npair(j) for j in i[reads])),
                first_audio_margin_bins=bins,episodes=examples)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('data',type=Path)
    p.add_argument('evidence',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    from .run import check_seal
    check_seal(a.evidence)
    if not (a.evidence/'summary.json').is_file():
        raise ValueError('require complete heldout roster')
    with np.load(a.data/'test.npz',allow_pickle=False) as z: s=dict(z)
    independent=json.loads((a.data/'heldout_controls.json').read_text())
    regimes={'registered_tabular':independent['policy']['policies']['full']}
    for path in sorted((a.evidence/'confirm').glob('read-*.json')):
        r=json.loads(path.read_text())
        regimes[path.stem]=r['chosen']
    dump(a.output,{k:explain(s,r['terminal_action'],r['exit_prefix']) for k,r in regimes.items()})


if __name__=='__main__': main()
