"""Fixed content-group sampler and aligned group-risk integration, anchor separate."""
import numpy as np
from grouped_risk import GroupRiskProfile,MODE,aggregate_rows

A_PROFILE=GroupRiskProfile(0.,8,MODE)
N_PROFILE=GroupRiskProfile(1.5,8,MODE)
GROUPS=tuple(i for i in range(8) for _ in range(8))

def group_schedule(group_ids,seed,steps=300):
    ids=tuple(group_ids)
    if type(seed) is not int or seed<0 or type(steps) is not int or not 1<=steps<=300:raise ValueError('fixed bounded integer schedule')
    if len(ids)!=780 or any(type(x) is not str for x in ids):raise ValueError('130groups x6variants required')
    names=ids[::6]
    if len(set(names))!=130 or any(ids[6*i:6*i+6]!=(name,)*6 for i,name in enumerate(names)):raise ValueError('contiguous unique contentgroups, not targetlabels')
    rng=np.random.default_rng(seed);schedule=[]
    for _ in range(steps):
        chosen=rng.choice(130,8,replace=False);rows=[];full=[]
        for group in chosen:
            variants=rng.choice(6,4,replace=False)
            for variant in variants:
                rows.extend((int(group)*6+int(variant),)*2);full.extend((True,False))
        schedule.append((tuple(rows),tuple(full),GROUPS))
    return tuple(schedule)

def grouped_terms(terms,groups):
    """Every arm computes BOTH groupA andgroupN from qualified aligned rowterms."""
    a=aggregate_rows(A_PROFILE,*terms['aligned_additive'],groups)
    n=aggregate_rows(N_PROFILE,*terms['aligned_ndu'],groups)
    return {'group_additive':a,'group_ndu':n}

def select_group_gradients(terms,grouped,objective):
    if objective=='additive':_,gp,gq=terms['aligned_additive']
    elif objective=='row_ndu':_,gp,gq=terms['aligned_ndu']
    elif objective=='group_ndu':_,gp,gq,_=grouped['group_ndu']
    else:raise ValueError('explicit additive/row_ndu/group_ndu objective')
    ap,aq=terms['aligned_anchor']
    return gp+.2*ap,gq+.2*aq
