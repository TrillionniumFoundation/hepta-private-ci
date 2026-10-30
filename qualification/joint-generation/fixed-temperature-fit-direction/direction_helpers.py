"""Model-free fixed FIT group split and explicit equal-displacement controls."""
import numpy as np

def sample_direction_rows(group_ids,seed):
    ids=tuple(group_ids)
    if type(seed) is not int or seed not in (29103,29107,129103,129107) or len(ids)!=780 or any(type(x) is not str for x in ids):raise ValueError('fixed seed and130x6FITgroups')
    names=ids[::6]
    if len(set(names))!=130 or any(ids[6*i:6*i+6]!=(name,)*6 for i,name in enumerate(names)):raise ValueError('contiguous unique contentgroups')
    partial=[]
    for i,name in enumerate(names):
        parts=name.split(':')
        if len(parts)!=4 or any(not word.isdecimal() or str(int(word))!=word for word in parts):raise ValueError('canonical contentgroup')
        scene,c,s,p=map(int,parts)
        if not(0<=scene<12 and 0<=c<4 and 0<=s<3 and 0<=p<3):raise ValueError('fixed vocabulary')
        if 1<=sum(v!=0 for v in (c,s,p))<=2:partial.append(i)
    if len(partial)<16:raise ValueError('sixteen eligible distinct groups')
    rng=np.random.default_rng(seed);chosen=rng.choice(partial,16,replace=False);grad=[];sentinel=[]
    for group in chosen[:8]:
        for variant in rng.choice(6,4,replace=False):grad.extend((int(group)*6+int(variant),)*2)
    for group in chosen[8:]:
        for variant in range(6):sentinel.extend((int(group)*6+variant,)*2)
    return tuple(grad),(True,False)*32,tuple(sentinel),(True,False)*48

def displacement(base,updated):
    if not base or set(base)!=set(updated):raise ValueError('same nonempty parameter inventory')
    delta={}
    for key in sorted(base):
        a,b=np.asarray(base[key],dtype=np.float64),np.asarray(updated[key],dtype=np.float64)
        if a.shape!=b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():raise ValueError('finite matching parameters')
        delta[key]=b-a
    norm=float(np.sqrt(sum(float(np.sum(x*x)) for x in delta.values())))
    if not np.isfinite(norm) or norm<=0:raise ValueError('nonzero finite displacement; no fallback')
    return delta,norm

def norm_matched_parameters(base,delta,target_norm):
    if not base or set(base)!=set(delta):raise ValueError('same parameter inventory')
    if type(target_norm) not in (int,float) or not np.isfinite(target_norm) or target_norm<=0:raise ValueError('positive finite common norm')
    clean={}
    for key in sorted(base):
        a,d=np.asarray(base[key],dtype=np.float64),np.asarray(delta[key],dtype=np.float64)
        if a.shape!=d.shape or not np.isfinite(a).all() or not np.isfinite(d).all():raise ValueError('finite matching displacement')
        clean[key]=d
    norm=float(np.sqrt(sum(float(np.sum(d*d)) for d in clean.values())))
    if not np.isfinite(norm) or norm<=0 or target_norm>norm:raise ValueError('nonzero norm and never enlarged displacement')
    scale=target_norm/norm
    result={key:np.asarray(base[key],dtype=np.float64)+scale*clean[key] for key in clean}
    if not all(np.isfinite(x).all() for x in result.values()):raise ValueError('finite explicit perturbation')
    return result,scale
