"""Registered supervised warmstart for the actual-episode natural generator.

These optimization losses are explicitly proxies. The resulting checkpoint is
only a common initialization and fixed control for subsequent actual-NDU runs.
"""
import argparse
import json
import shutil
from pathlib import Path
import time

import numpy as np
import torch

from .data_sources import digest,save
from .natural_media import SCORE_SPEC
from .natural_model import LAW,NaturalGenerator,parameter_hash,proxy_loss
from .natural_port import public_tensors
from .profile_contract import cpu_seconds
from .semantic_backbones import PINS,SemanticBackbones
from .semantic_tsm import TSM_FILE,TSM_SHA,TsmObserver

WARMSTART={'schema':'hepta.closure.natural-warmstart.v2','seed':6821,'steps':2048,'batch_size':4,
           'adamw_lr':.0003,'weight_decay':.0001,'gradient_clip':2.,
           'checkpoints':[0,256,1024,2048],'dataset_role':'generator_train',
           'selection':'Later compare all registered snapshots using original development complete episodes only; no calibration or qualification selection.',
           'loss_status':'Supervised proxy; not claimed to be the actual NDU objective',
           'actual_learning_plan':{'seeds':[811,823,839],'risk_gamma':2.,'mean_control_gamma':0.,
              'updates_per_arm':64,'complete_episodes_per_update':2,'optimizer_lr':.000003,
              'gradient_clip':.1,'paired_initialization':True,
              'policy_rule':'Use the shared true episode executor under the bound current actor; never replace actual generation with a cached trace.'}}


def generator_rows(root,role):
    plan=json.loads((root/'SOURCE_PROTOCOL.json').read_text())
    frozen={row['source_id']:row for row in plan['selected'] if row['role']==role}
    directories={p.name:p for p in (root/'prepared'/role).iterdir() if p.is_dir()}
    if set(directories)!=set(frozen):raise ValueError('Incomplete exact frozen generator source cohort')
    rows=[]
    for source_id,directory in sorted(directories.items()):
        receipt=json.loads((directory/'RECEIPT.json').read_text())
        event=frozen[source_id]['events'][0]
        if receipt['source_protocol_sha256']!=plan['protocol_sha256'] or receipt['source_id']!=source_id or receipt['role']!=role:
            raise ValueError('Generator source identity mismatch')
        if any(receipt['events'][0][key]!=value for key,value in event.items()):
            raise ValueError('Generator event window/annotation changed')
        if digest((directory/'EVENT.npz').read_bytes())!=receipt['retained_files']['EVENT.npz']:
            raise ValueError('Generator tensor bytes changed')
        rows.append((directory,receipt['events'][0]))
    if len({row['source_sha256'] for _,row in rows})!=len(rows):
        raise ValueError('Repeated original video bytes cannot inflate source count')
    return plan,rows


def load_proxy_data(root,rows,output):
    cache_path=output/'PUBLIC_CONTEXT_CACHE.npz'
    cache_receipt=output/'PUBLIC_CONTEXT_CACHE.json'
    ids=[row['event_id'] for _,row in rows]
    if cache_path.exists():
        receipt=json.loads(cache_receipt.read_text())
        if receipt['event_ids']!=ids or digest(cache_path.read_bytes())!=receipt['sha256']:
            raise ValueError('Proxy context cache identity changed')
        context=np.load(cache_path)
    else:
        pann=SemanticBackbones(root/'pretrained');tsm=TsmObserver(root/'pretrained')
        contexts={};started=time.monotonic();cpu=cpu_seconds()
        for index,(directory,_) in enumerate(rows):
            with np.load(directory/'EVENT.npz') as arrays:
                # Only frozen pretrained features are cached, not trainable
                # encoders or emission results. Real episodes never use this cache.
                public=public_tensors(arrays,tsm,pann)
            for key in ('video_features','audio_features'):
                contexts.setdefault(key,[]).append(public[key].numpy()[0])
            if (index+1)%16==0:print(json.dumps({'warmstart_contexts':index+1,'total':len(rows)}),flush=True)
        np.savez_compressed(cache_path,**{key:np.stack(value) for key,value in contexts.items()})
        save(cache_receipt,{'schema':'hepta.closure.proxy-cache.v1','event_ids':ids,
              'sha256':digest(cache_path.read_bytes()),'weights':{**PINS,TSM_FILE:TSM_SHA},
              'cpu_seconds':cpu_seconds()-cpu,'wall_seconds':time.monotonic()-started,
              'use':'supervised training proxy only; complete episodes recompute and bill these features'})
        context=np.load(cache_path)
        del pann,tsm
    public={};targets={};action_ids=sorted(map(int,json.loads((root/'SOURCE_PROTOCOL.json').read_text())['ontology']['action']))
    sound_ids=sorted(map(int,json.loads((root/'SOURCE_PROTOCOL.json').read_text())['ontology']['sound']))
    for directory,row in rows:
        with np.load(directory/'EVENT.npz') as a:
            tensors={'video':a['context_video'].transpose(0,3,1,2).copy(),
                     'audio':a['context_audio'],'video_mask':a['context_video_mask'].astype(np.float32) if 'context_video_mask' in a else np.ones(16,np.float32),
                     'audio_mask':a['context_audio_mask'].astype(np.float32) if 'context_audio_mask' in a else np.ones(32000,np.float32)}
            target={'video':a['target_video'].transpose(0,3,1,2).copy(),
                    'image':a['target_image'].transpose(2,0,1).copy(),'audio':a['target_audio'],
                    'action':np.int64(action_ids.index(row['action_id'])),
                    'sound':np.int64(sound_ids.index(row['sound_id']))}
        for key,value in tensors.items():public.setdefault(key,[]).append(value)
        for key,value in target.items():targets.setdefault(key,[]).append(value)
    public={key:torch.from_numpy(np.stack(value)) for key,value in public.items()}
    public.update({key:torch.from_numpy(context[key].copy()) for key in ('video_features','audio_features')})
    return public,{key:torch.from_numpy(np.stack(value)) for key,value in targets.items()}


def save_checkpoint(path,model,protocol_sha,step):
    state={'schema':'hepta.closure.natural-checkpoint.v1','model':model.state_dict(),'ontology':model.ontology,
           'parameter_sha256':parameter_hash(model),'warmstart_protocol_sha256':protocol_sha,
           'step':step,'emission_law':LAW}
    torch.save(state,path)
    return {'file':path.name,'sha256':digest(path.read_bytes()),'parameter_sha256':state['parameter_sha256'],'step':step}


def load_checkpoint(path):
    state=torch.load(path,map_location='cpu',weights_only=True)
    if state['emission_law']!=LAW:raise ValueError('Checkpoint emission law changed')
    model=NaturalGenerator(state['ontology'])
    model.load_state_dict(state['model'],strict=True)
    if parameter_hash(model)!=state['parameter_sha256']:raise ValueError('Checkpoint parameter identity changed')
    return model,state


def warmstart(root,output,cache_from=None):
    torch.set_num_threads(2);torch.manual_seed(WARMSTART['seed'])
    plan,rows=generator_rows(root,'generator_train')
    if output.exists():raise FileExistsError('Use a fresh warmstart output directory')
    output.mkdir(parents=True)
    if cache_from is not None:
        for name in ('PUBLIC_CONTEXT_CACHE.npz','PUBLIC_CONTEXT_CACHE.json'):
            shutil.copyfile(cache_from/name,output/name)
    sources={name:digest((Path(__file__).parent/name).read_bytes()) for name in
             ('natural_train.py','natural_model.py','natural_media.py','natural_port.py','semantic_backbones.py','semantic_tsm.py')}
    protocol={**WARMSTART,'source_protocol_sha256':plan['protocol_sha256'],'emission_law':LAW,
              'terminal_score':SCORE_SPEC,'implementation_sha256':sources,
              'training_sources':[row['source_id'] for _,row in rows],
              'context_pretraining_weights':{**PINS,TSM_FILE:TSM_SHA},
              'dataset_storage':'uint8 pixels, float conversion only on the current batch; identical public inputs and targets',
              'model_initialization_seed_reset_immediately_before_constructor':True,
              'proxy_cache_reused_from':str(cache_from) if cache_from else None}
    save(output/'WARMSTART_PROTOCOL.json',protocol);protocol_sha=digest(protocol)
    started=time.monotonic();cpu=cpu_seconds()
    public,target=load_proxy_data(root,rows,output)
    torch.manual_seed(WARMSTART['seed'])
    model=NaturalGenerator(plan['ontology']);initial_hashes={k:parameter_hash(v) for k,v in model.components().items()}
    optimizer=torch.optim.AdamW(model.parameters(),lr=.0003,weight_decay=.0001)
    rng=torch.Generator().manual_seed(WARMSTART['seed']+1)
    checkpoints=[save_checkpoint(output/'warmstart-0000.pt',model,protocol_sha,0)]
    log=[]
    for step in range(1,WARMSTART['steps']+1):
        ids=torch.randint(len(rows),(WARMSTART['batch_size'],),generator=rng)
        batch={key:value[ids] for key,value in public.items()};truth={key:value[ids] for key,value in target.items()}
        batch['video']=batch['video'].float()/255
        for name in ('video','image'):truth[name]=truth[name].float()/255
        prediction=model(batch);loss=proxy_loss(prediction,truth).mean()
        optimizer.zero_grad();loss.backward()
        norm=torch.nn.utils.clip_grad_norm_(model.parameters(),WARMSTART['gradient_clip'])
        optimizer.step()
        if step%64==0:
            row={'step':step,'proxy_loss':float(loss.detach()),'raw_gradient_norm':float(norm),
                 'cpu_seconds':cpu_seconds()-cpu,'wall_seconds':time.monotonic()-started}
            log.append(row);print(json.dumps(row),flush=True)
        if step in WARMSTART['checkpoints']:
            checkpoints.append(save_checkpoint(output/f'warmstart-{step:04d}.pt',model,protocol_sha,step))
    if sources!={name:digest((Path(__file__).parent/name).read_bytes()) for name in sources}:
        raise ValueError('Executed warmstart source changed while training')
    result={'schema':'hepta.closure.natural-warmstart-result.v1','protocol_sha256':protocol_sha,
            'source_protocol_sha256':plan['protocol_sha256'],'checkpoints':checkpoints,'training_log':log,
            'optimizer_steps':WARMSTART['steps'],'training_source_count':len(rows),
            'proxy_training_examples':WARMSTART['steps']*WARMSTART['batch_size'],
            'trainable_parameters':sum(p.numel() for p in model.parameters()),
            'components_changed':{key:parameter_hash(module)!=initial_hashes[key] for key,module in model.components().items()},
            'cpu_seconds':cpu_seconds()-cpu,'wall_seconds':time.monotonic()-started,
            'new_development_metrics':0,'new_calibration_metrics':0,'new_qualification_metrics':0,
            'actual_ndu_updates':0,'scientific_scope':'proxy warmstart only; actual-output NDU/mean comparison remains separate'}
    save(output/'WARMSTART_RESULT.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cache-from',type=Path)
    args=p.parse_args();warmstart(args.assets,args.output,args.cache_from)
