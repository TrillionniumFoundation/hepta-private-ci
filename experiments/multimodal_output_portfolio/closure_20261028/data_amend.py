"""Correct boundary target alignment without changing any allocated source role."""
import argparse
import copy
import json
import os
from pathlib import Path
import time

from .data_sources import digest, load_annotations, save


def amend(original, destination):
    old=json.loads((original/'SOURCE_PROTOCOL.json').read_text())
    destination.mkdir(parents=True,exist_ok=True)
    annotation={}
    for split in ('train','valid'):
        annotation[split]={kind:load_annotations(original,split,kind)[0] for kind in ('action','sound')}
    plan=copy.deepcopy(old);plan.pop('protocol_sha256')
    plan['schema']='hepta.closure.natural-sources.v2'
    plan['created_at_unix']=time.time()
    changed=0
    for source in plan['selected']:
        split=source['official_split'];sid=source['source_id']
        a=annotation[split]['action'][sid]['metadata'];s=annotation[split]['sound'][sid]['metadata']
        duration=min(a['num_frames']/a['frame_rate'],s['audio_samples']/s['audio_sample_rate'])
        source['duration_seconds']=duration
        for event in source['events']:
            begin=max(event['action_interval_seconds'][0],event['sound_interval_seconds'][0])
            end=min(event['action_interval_seconds'][1],event['sound_interval_seconds'][1])
            center=(begin+end)/2
            target=int(max(0,min(center-1,duration-2.125))*8)/8
            event['previous_v1_window_start_seconds']=event['window_start_seconds']
            if target!=event['target_start_seconds']:changed+=1
            event['target_start_seconds']=target;event['target_end_seconds']=target+2
            event['window_start_seconds']=target-1
            event['target_label_overlap_seconds']=max(0,min(end,target+2)-max(begin,target))
            if event['target_label_overlap_seconds']<.15-1e-9:
                raise ValueError('Frozen annotated event is not observable in its target')
    plan['decode']['boundary_context']='zero-pad only unavailable public context; explicit per-frame/sample availability mask; target media always real source samples'
    plan['amendment']={'parent_source_protocol_sha256':old['protocol_sha256'],
        'reason':'Metadata-only independent audit found clamped 4-second windows could exclude the labelled action/sound from their target. Center the real 2-second target first and pad unavailable surrounding public context.',
        'all_source_ids_and_roles_unchanged':True,'all_event_annotation_ids_unchanged':True,
        'events_with_adjusted_time_window':changed,'new_development_metrics_seen':0,
        'new_calibration_metrics_seen':0,'new_qualification_metrics_seen':0,
        'implementation_sha256':digest(Path(__file__).read_bytes())}
    plan['protocol_sha256']=digest(plan)
    save(destination/'SOURCE_PROTOCOL.json',plan)
    for path in original.glob('*annotations.zip'):
        os.link(path,destination/path.name)
    (destination/'pretrained').mkdir(exist_ok=True)
    for path in (original/'pretrained').iterdir():
        if path.is_file():os.link(path,destination/'pretrained'/path.name)
    migrated=[]
    for source in plan['selected']:
        olddir=original/'prepared'/source['role']/source['source_id']
        if not (olddir/'RECEIPT.json').exists() or source['role']!='generator_train':continue
        oldreceipt=json.loads((olddir/'RECEIPT.json').read_text())
        event=source['events'][0]
        if event['window_start_seconds']!=oldreceipt['events'][0]['window_start_seconds']:continue
        newdir=destination/'prepared'/source['role']/source['source_id'];newdir.mkdir(parents=True,exist_ok=True)
        oldarray=olddir/'EVENT.npz'
        if digest(oldarray.read_bytes())!=oldreceipt['retained_files']['EVENT.npz']:
            raise ValueError('Previously prepared source changed')
        os.link(oldarray,newdir/'EVENT.npz')
        receipt={**oldreceipt,'source_protocol_sha256':plan['protocol_sha256'],
            'events':[{**oldreceipt['events'][0],**event}],
            'migration':{'previous_receipt_sha256':digest((olddir/'RECEIPT.json').read_bytes()),
                         'pixel_audio_bytes_changed':False,'time_window_identical':True,
                         'implicit_all_context_samples_valid':True}}
        save(newdir/'RECEIPT.json',receipt);migrated.append(source['source_id'])
    save(destination/'SOURCE_AMENDMENT_RECEIPT.json',{'parent_source_protocol_sha256':old['protocol_sha256'],
        'source_protocol_sha256':plan['protocol_sha256'],'migrated_generator_sources':migrated,
        'all_source_ids_and_roles_unchanged':True,'events_with_adjusted_time_window':changed})
    return plan,migrated


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    plan,migrated=amend(a.original,a.destination)
    print(json.dumps({'protocol_sha256':plan['protocol_sha256'],'migrated_training_sources':len(migrated),
                      'amendment':plan['amendment']}))
