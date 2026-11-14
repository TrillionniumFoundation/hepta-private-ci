"""One prespecified paired corruption domain, not a sigma/seed search API."""
import hashlib
import numpy as np
MODE='fixed-paired-heldout-corruption-035-v1'
DOMAINS=('freshID','OOD')
def check_request(fold,noise_seed,mode):
    if mode!=MODE or type(fold) is not int or fold not in (0,1):raise ValueError('fixed paired mode/fold')
    if type(noise_seed) is not int or noise_seed not in (4701+10*fold,4702+10*fold):raise ValueError('fixed paired seed')
def paired_images(clean,sigma,z,*,mode):
    if mode!=MODE or type(sigma) is not float or not .03<=sigma<=.25:raise ValueError('fixed ID sigma/domain')
    clean=np.asarray(clean,dtype=np.float64);z=np.asarray(z,dtype=np.float64)
    if clean.shape!=(8,8,3) or z.shape!=clean.shape or not np.isfinite(clean).all() or not np.isfinite(z).all() or np.any(clean<0) or np.any(clean>1):raise ValueError('finite fixed image/Z')
    answer={}
    for domain,scale in (('freshID',sigma),('OOD',.35)):
        noisy=clean+scale*z
        if not np.isfinite(noisy).all():raise ValueError('nonfinite before clip')
        observed=np.clip(noisy,0,1);low=observed.reshape(4,2,4,2,3).mean(axis=(1,3)).repeat(2,axis=0).repeat(2,axis=1)
        answer[domain]=(observed,low)
    return answer

def paired_dataset(fold,noise_seed,*,mode):
    check_request(fold,noise_seed,mode)
    # Only the science worker after BOTH freeze barriers calls this endpoint.
    from data import attributes,render
    from group_data import partition_groups
    _,groups=partition_groups(fold);rng=np.random.default_rng(noise_seed)
    buffers={domain:{'full':[],'low':[],'labels':[],'groups':[],'input_hashes':[]} for domain in DOMAINS}
    sigma_hash=hashlib.sha256();z_hash=hashlib.sha256();clean_hash=hashlib.sha256()
    for scene,color_cmd,shape_cmd,position_cmd in groups:
        color,shape,position=attributes(scene)
        target=((color if color_cmd==0 else color_cmd-1)*2+(shape if shape_cmd==0 else shape_cmd-1))*2+(position if position_cmd==0 else position_cmd-1)
        instruction=np.concatenate((np.eye(4)[color_cmd],np.eye(3)[shape_cmd],np.eye(3)[position_cmd]));group=f'{scene}:{color_cmd}:{shape_cmd}:{position_cmd}'
        for _ in range(6):
            clean=render(scene);sigma=float(rng.uniform(.03,.25));z=rng.normal(0.,1.,(8,8,3))
            sigma_hash.update(np.asarray([sigma],dtype='<f8').tobytes());z_hash.update(z.astype('<f8').tobytes());clean_hash.update(clean.astype('<f8').tobytes())
            images=paired_images(clean,sigma,z,mode=mode)
            for domain,(observed,low) in images.items():
                row=np.concatenate((observed.reshape(-1),instruction));buf=buffers[domain]
                buf['full'].append(row);buf['low'].append(np.concatenate((low.reshape(-1),instruction)));buf['labels'].append(target);buf['groups'].append(group);buf['input_hashes'].append(hashlib.sha256(row.astype('<f8').tobytes()).hexdigest())
    for buf in buffers.values():
        for key in ('full','low','labels'):
            array=np.asarray(buf[key]);buf[key]=np.frombuffer(array.tobytes(),dtype=array.dtype).reshape(array.shape)
    return buffers,{'mode':MODE,'fold':fold,'noise_seed':noise_seed,'rows_per_domain':780,'variants':6,'groups':130,'OOD_sigma':.35,'ID_sigma_interval':[.03,.25],'sigma_SHA256':sigma_hash.hexdigest(),'standard_normal_SHA256':z_hash.hexdigest(),'clean_render_SHA256':clean_hash.hexdigest(),'render_calls':780,'standard_normal_scalars':149760,'uniform_sigma_draws':780,'clipped_images':1560,'thumbnail_images':1560,'full_low_view_rows':3120,'latent_hash_bytes':780*(8+192*8+192*8),'input_hash_bytes':1560*202*8}
