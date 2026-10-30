"""Independent fixed synthetic noise branch for FIT-only calibration, no gradients."""
import hashlib
import numpy as np
from fresh_views import _records

def calibration_view_dataset(group_ids,fold,noise_seed,renderer):
    if type(fold) is not int or fold not in (0,1) or type(noise_seed) is not int or noise_seed!=5701+fold or not callable(renderer):raise ValueError('fixed fold/newcal seed/renderer')
    ids,records=_records(group_ids);rng=np.random.default_rng(noise_seed);full=np.empty((780,202),dtype='<f8');low=np.empty_like(full);labels=np.empty(780,dtype='<i8');hashes=[]
    for group,(scene,color_cmd,shape_cmd,position_cmd) in enumerate(records):
        color,shape,position=scene//4,(scene//2)%2,scene%2
        target=((color if color_cmd==0 else color_cmd-1)*2+(shape if shape_cmd==0 else shape_cmd-1))*2+(position if position_cmd==0 else position_cmd-1)
        instruction=np.concatenate((np.eye(4)[color_cmd],np.eye(3)[shape_cmd],np.eye(3)[position_cmd]))
        for variant in range(6):
            row=6*group+variant;clean=np.asarray(renderer(scene),dtype=np.float64)
            if clean.shape!=(8,8,3) or not np.isfinite(clean).all() or np.any(clean<0) or np.any(clean>1):raise ValueError('finite8x8x3renderer')
            noise=rng.uniform(.03,.25);observed=np.clip(clean+rng.normal(0,noise,(8,8,3)),0,1)
            thumbnail=observed.reshape(4,2,4,2,3).mean(axis=(1,3)).repeat(2,axis=0).repeat(2,axis=1)
            full[row]=np.concatenate((observed.reshape(-1),instruction));low[row]=np.concatenate((thumbnail.reshape(-1),instruction));labels[row]=target;hashes.append(hashlib.sha256(full[row].tobytes()).hexdigest())
    return {'full':np.frombuffer(full.tobytes(),dtype='<f8').reshape(full.shape),'low':np.frombuffer(low.tobytes(),dtype='<f8').reshape(low.shape),'labels':np.frombuffer(labels.tobytes(),dtype='<i8'),'groups':ids,'input_hashes':tuple(hashes),'noise_seed':noise_seed,'observations':780,'view_rows':1560,'normal_scalars':149760,'cache_payload_bytes':full.nbytes+low.nbytes+labels.nbytes}
