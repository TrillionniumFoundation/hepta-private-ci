"""Fresh synthetic FIT corruptions only; renderer injected, never model-adaptive."""
import hashlib,json
import numpy as np
SEEDS=(19103,19107,119103,119107)

def _records(group_ids):
    ids=tuple(group_ids)
    if len(ids)!=780 or any(type(x) is not str for x in ids):raise ValueError('130FITgroups x6positions')
    names=ids[::6]
    if len(set(names))!=130 or any(ids[6*i:6*i+6]!=(name,)*6 for i,name in enumerate(names)):raise ValueError('contiguous distinct FIT groups')
    records=[]
    for name in names:
        parts=name.split(':')
        if len(parts)!=4 or any(not word.isdecimal() or str(int(word))!=word for word in parts):raise ValueError('canonical scene/command group')
        scene,color,shape,position=map(int,parts)
        if not(0<=scene<12 and 0<=color<4 and 0<=shape<3 and 0<=position<3):raise ValueError('group vocabulary')
        records.append((scene,color,shape,position))
    return ids,tuple(records)

def stream_digest(stream):
    header=json.dumps({'seed':stream['seed'],'shape':list(stream['inputs'].shape)},sort_keys=True,separators=(',',':')).encode()
    digest=hashlib.sha256(header);digest.update(memoryview(stream['inputs']));digest.update(memoryview(stream['labels']))
    return digest.hexdigest()

def build_fresh_stream(group_ids,schedule,seed,renderer):
    if type(seed) is not int or seed not in SEEDS or not callable(renderer):raise ValueError('fixed noise seed and explicit renderer')
    ids,records=_records(group_ids)
    if type(schedule) is not tuple or not 1<=len(schedule)<=300:raise ValueError('bounded immutable schedule')
    # Validate every schedule before any rendering/noise draw.
    for rows,full,groups in schedule:
        if (type(rows) is not tuple or len(rows)!=64 or any(type(r) is not int or not 0<=r<780 for r in rows)
                or type(full) is not tuple or full!=(True,False)*32 or any(type(v) is not bool for v in full) or type(groups) is not tuple or any(type(g) is not int for g in groups) or groups!=tuple(i for i in range(8) for _ in range(8))):raise ValueError('64pairedfull/low canonicalgroup rows')
        chosen=[]
        for j in range(8):
            block=rows[j*8:j*8+8];chosen.append(block[0]//6)
            if len({r//6 for r in block})!=1 or len(set(block[::2]))!=4 or any(block[i]!=block[i+1] for i in (0,2,4,6)):raise ValueError('four distinct variant positions pergroup')
        if len(set(chosen))!=8:raise ValueError('eight distinct content groups')
    rng=np.random.default_rng(seed);x=np.empty((len(schedule),64,202),dtype='<f8');y=np.empty((len(schedule),64),dtype='<i8')
    for step,(rows,full,groups) in enumerate(schedule):
        for pair in range(32):
            scene,color_cmd,shape_cmd,position_cmd=records[rows[2*pair]//6]
            color,shape,position=scene//4,(scene//2)%2,scene%2
            target=((color if color_cmd==0 else color_cmd-1)*2+(shape if shape_cmd==0 else shape_cmd-1))*2
            target+=position if position_cmd==0 else position_cmd-1
            instruction=np.concatenate((np.eye(4)[color_cmd],np.eye(3)[shape_cmd],np.eye(3)[position_cmd]))
            clean=np.asarray(renderer(scene),dtype=np.float64)
            if clean.shape!=(8,8,3) or not np.isfinite(clean).all() or np.any(clean<0) or np.any(clean>1):raise ValueError('finite normalized8x8x3renderer output')
            noise=rng.uniform(.03,.25)
            observed=np.clip(clean+rng.normal(0,noise,(8,8,3)),0,1)
            thumbnail=observed.reshape(4,2,4,2,3).mean(axis=(1,3));thumbnail=thumbnail.repeat(2,axis=0).repeat(2,axis=1)
            x[step,2*pair]=np.concatenate((observed.reshape(-1),instruction));x[step,2*pair+1]=np.concatenate((thumbnail.reshape(-1),instruction));y[step,2*pair:2*pair+2]=target
    # bytes-backed arrays cannot have WRITEABLE reenabled; modelinputs are views.
    inputs=np.frombuffer(x.tobytes(),dtype='<f8').reshape(x.shape);labels=np.frombuffer(y.tobytes(),dtype='<i8').reshape(y.shape)
    result={'seed':seed,'inputs':inputs,'labels':labels,'fresh_observations':32*len(schedule),'paired_view_rows':64*len(schedule),'uniform_scalars':32*len(schedule),'normal_scalars':192*32*len(schedule),'cache_payload_bytes':inputs.nbytes+labels.nbytes}
    header=json.dumps({'seed':seed,'shape':list(inputs.shape)},sort_keys=True,separators=(',',':')).encode();result['hash_bytes_per_pass']=result['cache_payload_bytes']+len(header);result['sha256']=stream_digest(result)
    return result
