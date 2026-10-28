"""Prepare the corrected, immutable natural cohorts; preserve temporal labels."""
import argparse
import json
from pathlib import Path
import time
import zipfile

import numpy as np
import torch

from ..unified_20261028.natural_data import RemoteZip
from .data_prepare import decode
from .data_sources import digest, save
from .semantic_backbones import PINS, SemanticBackbones
from .semantic_tsm import TSM_FILE, TSM_SHA, TsmObserver

TRAIN_ROLES=("generator_train","observer_train","development")


def validate_freeze(plan, roles, path):
    if all(role in TRAIN_ROLES for role in roles):return None
    if path is None:raise ValueError('An immutable prior holdout freeze is required')
    freeze=json.loads(path.read_text())
    if freeze.get('source_protocol_sha256')!=plan['protocol_sha256']:
        raise ValueError('Holdout freeze/source identity mismatch')
    if roles==['observer_calibration']:
        if freeze.get('schema')!='hepta.closure.semantic-observer-freeze.v1':
            raise ValueError('Expected observer-only freeze before observer calibration')
        protocol=json.loads((path.parent/'PROTOCOL.json').read_text())
        if digest(protocol)!=freeze['protocol_sha256']:
            raise ValueError('Frozen observer protocol changed')
        for selected in freeze['selected'].values():
            if digest((path.parent/selected['checkpoint_file']).read_bytes())!=selected['checkpoint_sha256']:
                raise ValueError('Frozen observer weights changed')
    else:
        if freeze.get('schema')!='hepta.closure.natural-policy-freeze.v1':
            raise ValueError('Expected complete natural policy freeze')
        if not freeze.get('independent_observer_adequate',False):
            raise ValueError('Inadequate independent observer blocks semantic qualification')
        for record in freeze['frozen_files']:
            if digest(Path(record['path']).read_bytes())!=record['sha256']:
                raise ValueError('A frozen model/actor/observer file changed')
    return digest(path.read_bytes())


def window(frames, audio, event):
    first=round(event['window_start_seconds']*8)
    indices=np.arange(first,first+32)
    valid=(indices>=0)&(indices<len(frames))
    video=np.zeros((32,112,112,3),np.uint8)
    video[valid]=frames[indices[valid]]
    audio_indices=np.arange(first*2000,first*2000+64000)
    audio_valid=(audio_indices>=0)&(audio_indices<len(audio))
    waveform=np.zeros(64000,np.float32)
    waveform[audio_valid]=audio[audio_indices[audio_valid]]
    if not valid[8:24].all() or not audio_valid[16000:48000].all():
        raise ValueError('A target contains padding instead of real source media')
    return video,waveform,valid,audio_valid


def prepare(root, roles, freeze_path):
    plan=json.loads((root/'SOURCE_PROTOCOL.json').read_text())
    check=dict(plan);expected=check.pop('protocol_sha256')
    if digest(check)!=expected or plan['schema']!='hepta.closure.natural-sources.v2':
        raise ValueError('Corrected frozen source allocation changed')
    if not set(roles).issubset(plan['roles']):raise ValueError('Unknown source role')
    freeze_sha=validate_freeze(plan,roles,freeze_path)
    torch.set_num_threads(2)
    models=SemanticBackbones(root/'pretrained');tsm=TsmObserver(root/'pretrained')
    sources={name:digest((Path(__file__).parent/name).read_bytes()) for name in
             ('data_prepare_v2.py','data_prepare.py','semantic_backbones.py','semantic_tsm.py')}
    feature_spec={'schema':'hepta.closure.semantic-feature-protocol.v1','source_protocol_sha256':expected,
        'source_hashes':sources,'weights':{**PINS,TSM_FILE:TSM_SHA},
        'action_candidates':['S3D Kinetics-400','TSM Something-Something V2'],
        'tsm_frames':'uniform segment centers [1,3,5,7,9,11,13,15] of the actual sixteen-frame target',
        'selection_before_any_development_or_calibration_metrics':True,
        'reason_for_tsm':'Public action-template domain matches fine-grained object interactions better than coarse Kinetics pretraining; this is a hypothesis, not an observed gain.'}
    spec_path=root/'FEATURE_PROTOCOL.json'
    if spec_path.exists():
        if json.loads(spec_path.read_text())!=feature_spec:raise ValueError('Frozen feature implementation changed')
    else:save(spec_path,feature_spec)
    remotes={};archives={};started=time.monotonic();done=0
    selected=[row for row in plan['selected'] if row['role'] in roles]
    for source in selected:
        role,sid=source['role'],source['source_id'];destination=root/'prepared'/role/sid
        receipt_path=destination/'RECEIPT.json'
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text())
            if receipt['source_protocol_sha256']!=expected:raise ValueError('Prepared source belongs to another allocation')
            for name,pin in receipt['retained_files'].items():
                if digest((destination/name).read_bytes())!=pin:raise ValueError('Prepared bytes changed')
            done+=1;continue
        destination.mkdir(parents=True,exist_ok=True)
        split=source['official_split']
        if split not in archives:
            remote=RemoteZip(plan['archive'][split]['url'])
            if remote.generation!=plan['archive'][split]['generation'] or remote.etag!=plan['archive'][split]['etag']:
                raise ValueError('Original archive identity changed')
            remotes[split]=remote;archives[split]=zipfile.ZipFile(remote)
        payload=archives[split].read(source['member'])
        if len(payload)!=source['source_bytes']:raise ValueError('Original member length changed')
        source_sha=digest(payload);raw=root/('pending-'+sid+'.mp4');raw.write_bytes(payload);del payload
        try:
            frames,audio=decode(raw)
            clips=[(*window(frames,audio,event),event) for event in source['events'][:source['retained_event_count']]]
            features={key:[] for key in ('video','video_tsm','audio')};cpu=0.
            if role!='generator_train':
                for offset in range(0,len(clips),2):
                    group=clips[offset:offset+2]
                    videos=np.stack([x[0][8:24] for x in group]);waves=np.stack([x[1][16000:48000] for x in group])
                    start=time.process_time();v,a,_=models.features(videos,waves);tv=tsm.features(videos)
                    cpu+=time.process_time()-start
                    features['video'].append(v);features['video_tsm'].append(tv);features['audio'].append(a)
                np.savez_compressed(destination/'FEATURES.npz',**{k:np.concatenate(v) for k,v in features.items()})
            if role!='observer_train':
                v,a,vm,am,_=clips[0];indices=np.r_[0:8,24:32];ai=np.r_[0:16000,48000:64000]
                np.savez_compressed(destination/'EVENT.npz',context_video=v[indices],context_audio=a[ai],
                    context_video_mask=vm[indices],context_audio_mask=am[ai],
                    target_video=v[8:24],target_audio=a[16000:48000],target_image=v[16])
            rows=[{'event_id':f'{sid}-closure-{i}','source_id':sid,'source_sha256':source_sha,'role':role,**clip[-1]}
                  for i,clip in enumerate(clips)]
            retained={p.name:digest(p.read_bytes()) for p in destination.iterdir() if p.is_file()}
            save(receipt_path,{'schema':'hepta.closure.prepared-source.v2','source_protocol_sha256':expected,
                'source_id':sid,'role':role,'original_source_sha256':source_sha,'original_source_bytes':source['source_bytes'],
                'original_url':plan['archive'][split]['url'],'original_member':source['member'],
                'events':rows,'retained_files':retained,'feature_cpu_seconds':cpu,
                'source_hashes':sources,'feature_protocol_sha256':digest(feature_spec),'heldout_freeze_sha256':freeze_sha})
        finally:raw.unlink(missing_ok=True)
        done+=1
        if done%8==0 or done==len(selected):
            print(json.dumps({'prepared':done,'total':len(selected),'last_source':sid,'last_role':role,
                              'elapsed_wall_seconds':time.monotonic()-started}),flush=True)
    save(root/('PREPARATION_'+str(time.time_ns())+'.json'),{'schema':'hepta.closure.preparation-pass.v2',
        'source_protocol_sha256':expected,'roles':roles,'sources_completed':done,
        'source_hashes':sources,'wall_seconds':time.monotonic()-started,
        'range_receipts':{k:v.receipts for k,v in remotes.items()},'new_qualification_metrics':0,'observer_metrics':0})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--roles',nargs='+',default=list(TRAIN_ROLES));p.add_argument('--holdout-freeze',type=Path)
    a=p.parse_args();prepare(a.assets,a.roles,a.holdout_freeze)
