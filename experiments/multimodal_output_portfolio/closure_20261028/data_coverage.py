"""Training-only metadata proposal for disjoint class-coverage expansion.

This reads official training annotation ZIPs and the official video ZIP central
directory only. It neither downloads a new video nor reads any held-out score.
"""
import argparse
import copy
import json
from pathlib import Path
import time
import zipfile

from .data_sources import BASE,SIZE_LIMIT,digest,events,load_annotations,save
from ..unified_20261028.natural_data import RemoteZip

SEED="hepta-natural-training-coverage-v3-20261028"
ROLES=("generator_train","observer_train")
ADDITIONS=128


def labels(sources,role):
    return {kind:{event[kind+"_id"] for source in sources if source['role']==role
                  for event in source['events'][:source['retained_event_count']]}
            for kind in ('action','sound')}


def corrected_events(action,sound):
    clips=events(action,sound)
    a,s=action['metadata'],sound['metadata']
    duration=min(a['num_frames']/a['frame_rate'],s['audio_samples']/s['audio_sample_rate'])
    kept=[]
    for raw in clips:
        event=dict(raw)
        begin=max(event['action_interval_seconds'][0],event['sound_interval_seconds'][0])
        end=min(event['action_interval_seconds'][1],event['sound_interval_seconds'][1])
        target=int(max(0,min((begin+end)/2-1,duration-2.125))*8)/8
        event['previous_v1_window_start_seconds']=event['window_start_seconds']
        event.update(window_start_seconds=target-1,target_start_seconds=target,target_end_seconds=target+2,
                     target_label_overlap_seconds=max(0,min(end,target+2)-max(begin,target)))
        if event['target_label_overlap_seconds']>=.15-1e-9:kept.append(event)
    return duration,kept,len(clips)-len(kept)


def proposal(original,registry_paths,destination):
    original,destination=Path(original),Path(destination)
    plan=json.loads((original/'SOURCE_PROTOCOL.json').read_text());body=dict(plan)
    if body.pop('protocol_sha256')!=digest(body):raise ValueError('Source allocation changed')
    if destination.exists():raise FileExistsError('Preserve prior coverage proposals')
    excluded=set(plan['excluded_prior_video_ids'])|{row['source_id'] for row in plan['selected']}
    registries={}
    for path in registry_paths:
        path=Path(path);record=json.loads(path.read_text())
        ids=record['source_ids']
        excluded.update(ids);registries[str(path)]={'file_sha256':digest(path.read_bytes()),'source_ids':ids}
    annotations={kind:load_annotations(original,'train',kind)[0] for kind in ('action','sound')}
    remote=RemoteZip(BASE+'train_videos.zip')
    expected=plan['archive']['train']
    if (remote.generation!=expected['generation'] or remote.etag!=expected['etag']
            or remote.length!=expected['length']):raise ValueError('Official archive object changed')
    archive=zipfile.ZipFile(remote)
    candidates={};invalid_windows=0
    for member in archive.infolist():
        source=Path(member.filename).stem
        if (not member.filename.endswith('.mp4') or member.file_size>SIZE_LIMIT or source in excluded
                or source not in annotations['action'] or source not in annotations['sound']):continue
        duration,clips,invalid=corrected_events(annotations['action'][source],annotations['sound'][source])
        invalid_windows+=invalid
        if not clips:continue
        candidates[source]={'source_id':source,'official_split':'train','member':member.filename,
            'source_bytes':member.file_size,'compressed_bytes':member.compress_size,'zip_crc32':f'{member.CRC:08x}',
            'duration_seconds':duration,'priority':digest([SEED,source]),'events':clips}
    if len(candidates)<2*ADDITIONS:raise ValueError('Insufficient untouched training sources for both disjoint cohorts')
    coverage={role:labels(plan['selected'],role) for role in ROLES}
    before={role:{kind:sorted(ids) for kind,ids in value.items()} for role,value in coverage.items()}
    fresh={role:[] for role in ROLES};remaining=dict(candidates)
    for ordinal in range(ADDITIONS):
        for role in ROLES:
            choices=[]
            for source,row in remaining.items():
                clips=row['events']
                if role=='generator_train':
                    selected=max(clips,key=lambda event:(sum(event[k+'_id'] not in coverage[role][k] for k in ('action','sound')),
                        -int(digest([SEED,role,source,event['action_annotation_id'],event['sound_annotation_id']]),16)))
                    candidate_events=[selected]
                else:candidate_events=clips
                gain=sum(len({event[k+'_id'] for event in candidate_events}-coverage[role][k]) for k in ('action','sound'))
                choices.append((-gain,digest([SEED,role,source]),source,candidate_events))
            gain,tie,source,chosen=min(choices,key=lambda item:(item[0],item[1]))
            row=copy.deepcopy(remaining.pop(source))
            # Only new generator examples use the train-label coverage choice;
            # all original768 sources and their retained annotation IDs stay exact.
            if role=='generator_train':
                selected=chosen[0]
                if gain==0:selected=row['events'][0]  # Hash-fill event rule.
                row['events']=[selected]+[event for event in row['events'] if event!=selected]
            row.update(role=role,retained_event_count=(1 if role=='generator_train' else len(row['events'])),
                       coverage_gain_at_allocation=-gain,coverage_round=ordinal,
                       coverage_tie_sha256=tie,training_only_coverage_addition=True)
            fresh[role].append(row)
            for kind in ('action','sound'):
                coverage[role][kind].update(event[kind+'_id'] for event in row['events'][:row['retained_event_count']])
    additions=[row for role in ROLES for row in fresh[role]]
    if len({row['source_id'] for row in additions})!=256 or any(row['source_id'] in excluded for row in additions):
        raise ValueError('New training cohort independence violated')
    new=copy.deepcopy(plan);new.pop('protocol_sha256')
    new['schema']='hepta.closure.natural-sources.v3';new['created_at_unix']=time.time()
    new['selected']+=additions
    for role in ROLES:new['roles'][role]+=ADDITIONS
    new['coverage_amendment']={'schema':'hepta.closure.training-only-coverage-amendment.v1',
        'parent_source_protocol_sha256':plan['protocol_sha256'],'selection_seed':SEED,
        'implementation_sha256':digest(Path(__file__).read_bytes()),
        'reason':'Training metadata showed only31/63action and11/17sound labels for generator,50/63and14/17for observer; expand disjoint training sources before any new observer/generator development prediction.',
        'algorithm':'128rounds, generator then observer each round; maximize count of newly covered action IDs plus newly covered sound IDs using this role training labels only. Ties by SHA256([seed,role,source_id]). Generator retains the best single paired event, event ties by SHA256([seed,role,source,action_annotation_id,sound_annotation_id]); after gain0 fill by source SHA and original first event. Observer retains all up-to8 originally hashed windows. Remove each chosen source from both pools immediately.',
        'training_annotation_inputs':{kind:plan['annotation_archives']['train_'+kind] for kind in ('action','sound')},
        'new_video_pixels_downloaded':False,'new_development_predictions_seen':0,
        'new_calibration_predictions_seen':0,'new_qualification_pixels_or_predictions_seen':0,
        'all_original_768_ids_roles_and_retained_events_unchanged':True,
        'original_observer_adequacy_thresholds_unchanged':{'action':.6,'sound':.6,'must_beat_training_majority':True},
        'all_original_holdout_ids_and_sampling_unchanged':True,
        'all_published_ontology_classes_retained':True,'additional_source_exclusion_registries':registries,
        'excluded_source_count':len(excluded),'excluded_source_ids_sha256':digest(sorted(excluded)),
        'candidate_pool_count':len(candidates),'alignment_invalid_training_windows_rejected':invalid_windows,
        'coverage_before':before,'coverage_after':{role:{kind:sorted(ids) for kind,ids in cov.items()} for role,cov in coverage.items()},
        'new_source_ids':{role:[row['source_id'] for row in fresh[role]] for role in ROLES},
        'new_source_id_lists_sha256':digest({role:[row['source_id'] for row in fresh[role]] for role in ROLES}),
        'eligible_fresh_training_class_ids':{kind:sorted({event[kind+'_id'] for row in candidates.values() for event in row['events']}) for kind in ('action','sound')},
        'training_archive_index_range_receipts':remote.receipts,
        'additional_raw_source_bytes':{role:sum(row['source_bytes'] for row in fresh[role]) for role in ROLES},
        'additional_retained_events':{role:sum(row['retained_event_count'] for row in fresh[role]) for role in ROLES},
        'raw_storage_rule':'stream one source, verify source SHA, retain compact arrays/features then remove owned raw MP4; no large aggregate raw video download',
        'execution_plan':'finish original v2 prepare; metadata/hash migrate its immutable arrays into v3, decode new generator128 then new observer128 sequentially; fit observer and independent original64-source adequacy; only then complete same2048-update microbatch warmstart from originalseed with lazy NPZ reads; actual64updates/arm and3seeds unchanged; archive immutable phases to stay<=850MB'}
    new['protocol_sha256']=digest(new)
    destination.mkdir(parents=True)
    save(destination/'SOURCE_PROTOCOL_PROPOSAL.json',new)
    report={'source_protocol_sha256':new['protocol_sha256'],'parent_source_protocol_sha256':plan['protocol_sha256'],
            'roles':new['roles'],'amendment':new['coverage_amendment'],
            'full_new_ids_are_frozen_metadata_only':True,'new_decode_or_fit_started':False}
    save(destination/'COVERAGE_PROPOSAL.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--original',type=Path,required=True);p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--registry',type=Path,action='append',required=True);args=p.parse_args()
    result=proposal(args.original,args.registry,args.destination)
    print(json.dumps({key:value for key,value in result.items() if key!='amendment'}))
    print(json.dumps({key:result['amendment'][key] for key in ('coverage_before','coverage_after','candidate_pool_count','additional_raw_source_bytes','additional_retained_events','new_source_id_lists_sha256')}))
