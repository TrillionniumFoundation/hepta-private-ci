"""Independent metadata/cost inventory. Never opens held feature/result/media files."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PRIMARY=HERE.parents[1]
REPO=PRIMARY.parents[1]
SECONDARY=PRIMARY.parent/'hcsn_grid_temporal_r2_20261101'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def stage(receipt):
    command=receipt.get('command',[])
    if '-m' not in command:return 'other'
    pos=command.index('-m');module=command[pos+1];tail=command[pos+2:]
    role=tail[tail.index('--role')+1] if '--role' in tail else 'train'
    if module.endswith('.collect_metadata'):return 'shared/metadata'
    if module.endswith(('.data','.data_v2')):return 'shared/acquire/'+tail[0]
    if module.endswith('.study'):
        owner='primary' if module.startswith('experiments.hcsn_grid_frontend') else 'secondary'
        return owner+'/'+tail[0]+'/'+role
    return 'other/'+module


def forbidden_held_content(path):
    text=str(path)
    return any(s in text for s in ['/features/development/','/features/confirmation/']) or (
        '/results/' in text and any(s in path.name.lower() for s in ['development','confirmation']))


def inventory():
    checks=[];bindings=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    def bind(path,expected,tag):
        path=Path(path)
        if forbidden_held_content(path):raise ValueError('Inventory refuses held feature/result bytes')
        actual=sha(path);check(tag,actual==expected);bindings.append(dict(path=str(path.relative_to(REPO)),sha256=actual))
    cohort_path=PRIMARY/'COHORT_SELECTION.json';cohort=read(cohort_path);protocol=read(PRIMARY/'PROTOCOL.json')
    check('exact original384-member cohort SHA',sha(cohort_path)=='63413cefa90021700f3738d475b262c5b2552332632c90cde6ea35700e3103aa')
    check('protocol unchanged',sha(PRIMARY/'PROTOCOL.json')=='6df1bf7fcbff2e2612a01d5c9e1ac99ae60ea2bc329c8892d367866e4704e7e1')
    check('role namespaces match registered protocol',cohort['roles']==protocol['speaker_roles']=={'train':[1,3,4,5,6,7],'development':[8,9],'confirmation':[10,11,12,13]})
    entries=cohort['entries'];expected={(r['speaker'],r['name']):r for r in entries}
    check('384 unique selected identities',len(entries)==len(expected)==384)
    role_inventory={}
    for role,group in cohort['roles'].items():
        rows=[r for r in entries if r['role']==role];targets=Counter(str(r['sentence_target']) for r in rows)
        check('exact selected clip counts: '+role,len(rows)==32*len(group))
        check('balanced selected classes: '+role,targets=={'0':16*len(group),'1':16*len(group)})
        role_inventory[role]=dict(speaker_ids=group,clips=len(rows),targets=dict(targets),raw_bytes=sum(r['bytes'] for r in rows),compressed_payload_bytes=sum(r['compressed_bytes'] for r in rows))
    check('161257472selected raw bytes under170MB',sum(r['bytes'] for r in entries)==cohort['raw_uncompressed_bytes']==161257472<=170000000)
    for name in ['SOURCE_FREEZE.json','SOURCE_FREEZE_V2.json','MODEL_SOURCE_FREEZE_FEATURES_V1.json','MODEL_SOURCE_FREEZE.json']:
        frozen=read(PRIMARY/name)
        for relative,digest in frozen['files'].items():
            path=PRIMARY/relative
            if name=='MODEL_SOURCE_FREEZE_FEATURES_V1.json' and relative=='study.py':path=PRIMARY/'study_features_v1.py'
            bind(path,digest,name+': '+relative)
        for relative,digest in frozen.get('dependencies',{}).items():
            if relative=='prior_training_pilot_sha256':path=PRIMARY.parent/'hcsn_video_raw_r2_20261101/external_grid/PILOT_ACQUISITION.json'
            elif relative.startswith('experiments/'):path=REPO/relative
            else:raise ValueError('Unknown frozen dependency binding: '+relative)
            bind(path,digest,name+' dependency: '+relative)
    secondary_source=read(SECONDARY/'SOURCE_FREEZE.json')
    for relative,digest in secondary_source['files'].items():bind(SECONDARY/relative,digest,'secondary source: '+relative)
    for relative,digest in secondary_source['dependencies'].items():bind(REPO/relative,digest,'secondary dependency: '+relative)
    primary_candidate_path=PRIMARY/'results/run001/CANDIDATE_FREEZE.json';secondary_candidate_path=SECONDARY/'results/run001/CANDIDATE_FREEZE.json'
    pc,sc=read(primary_candidate_path),read(secondary_candidate_path)
    ph,sh=sha(primary_candidate_path),sha(secondary_candidate_path)
    check('exact primary candidate identity',ph=='408843812ca057e5500b8006eafbba8fc1a66e69e512633246f3a19f5528dd5c')
    check('exact secondary candidate identity',sh=='01c515bc4214de328c2097de144d5a44ce744e2e4bd008ea2df301752778c84b')
    check('secondary pins primary candidate',sc['primary_candidate_sha256']==ph)
    for owner,root,candidate in [('primary',PRIMARY,pc),('secondary',SECONDARY,sc)]:
        for relative,digest in candidate['files'].items():bind(root/'results/run001'/relative,digest,owner+' trained artifact: '+relative)
    check('primary candidate source/cohort bindings',pc['protocol_sha256']==sha(PRIMARY/'PROTOCOL.json') and pc['cohort_sha256']==sha(cohort_path) and pc['model_source_freeze_sha256']==sha(PRIMARY/'MODEL_SOURCE_FREEZE.json'))
    check('secondary candidate source binding',sc['source_freeze_sha256']==sha(SECONDARY/'SOURCE_FREEZE.json'))
    check('fourteenprimary optimizerreceipts retained',sum(name.startswith('optimizer_') for name in pc['files'])==14)
    check('fivesecondary optimizerreceipts retained',sum(name.startswith('optimizer_') for name in sc['files'])==5)
    shared=['AT_head.npz','A_classifier.npz','T_classifier.npz']+[f'{mod}_fold{i}.npz' for mod in ['A','T'] for i in range(3)]
    check('nine shared A/T classifiers andAT head byte-identical',all(pc['files'][name]==sc['files'][name] for name in shared))
    pubs={name:read(PRIMARY/name) for name in ['PUBLICATION_SOURCE.json','PUBLICATION_SOURCE_V2.json','PUBLICATION_MODEL_SOURCE_FEATURES_V1.json','PUBLICATION_MODEL_SOURCE.json','PRIMARY_CANDIDATE_PUBLICATION.json','PUBLICATION_CANDIDATE.json']}
    secondary_pubs={name:read(SECONDARY/name) for name in ['PUBLICATION_SOURCE.json','PUBLICATION_CANDIDATE.json']}
    check('V2 publication binds exact V2freeze',pubs['PUBLICATION_SOURCE_V2.json']['source_freeze_sha256']==sha(PRIMARY/'SOURCE_FREEZE_V2.json'))
    check('initial feature-source publication matches preservedsnapshot',pubs['PUBLICATION_MODEL_SOURCE_FEATURES_V1.json']['model_source_freeze_sha256']==sha(PRIMARY/'MODEL_SOURCE_FREEZE_FEATURES_V1.json'))
    check('retention amendment publication matches currentmodel source',pubs['PUBLICATION_MODEL_SOURCE.json']['model_source_freeze_sha256']==sha(PRIMARY/'MODEL_SOURCE_FREEZE.json'))
    check('secondary publication binds secondarysource',secondary_pubs['PUBLICATION_SOURCE.json']['source_freeze_sha256']==sha(SECONDARY/'SOURCE_FREEZE.json'))
    check('primary initially remained heldpaused',pubs['PRIMARY_CANDIDATE_PUBLICATION.json']['candidate_sha256']==ph and pubs['PRIMARY_CANDIDATE_PUBLICATION.json']['held_access_permitted']==False)
    check('global go cross-binds both published candidates',pubs['PUBLICATION_CANDIDATE.json']['candidate_sha256']==ph and pubs['PUBLICATION_CANDIDATE.json']['secondary_candidate_sha256']==sh and pubs['PUBLICATION_CANDIDATE.json']['global_held_go']==True)
    check('secondary go cross-binds primary publication',secondary_pubs['PUBLICATION_CANDIDATE.json']['candidate_sha256']==sh and secondary_pubs['PUBLICATION_CANDIDATE.json']['primary_candidate_commit']==pubs['PRIMARY_CANDIDATE_PUBLICATION.json']['candidate_commit'])
    addendum=read(PRIMARY/'PROVENANCE_ADDENDUM.json')
    check('V2 stalezero counter correction remains explicitunknown',read(PRIMARY/'SOURCE_FREEZE_V2.json')['new_mpeg_payloads_acquired']==0 and addendum['new_payload_count_at_v2_freeze'] is None and addendum['qualification_changed']==False)
    check('historical model-freeze binding resolves preservedv1 snapshot',addendum['bindings']['MODEL_SOURCE_FREEZE.json']==sha(PRIMARY/'MODEL_SOURCE_FREEZE_FEATURES_V1.json'))
    for relative,digest in addendum['bindings'].items():
        path=PRIMARY/('MODEL_SOURCE_FREEZE_FEATURES_V1.json' if relative=='MODEL_SOURCE_FREEZE.json' else relative)
        bind(path,digest,'provenance addendum historical binding: '+relative)
    retention=read(PRIMARY/'RETENTION_AMENDMENT.json')
    bind(PRIMARY/'features_train.receipt.json',retention['original_feature_extraction_receipt_sha256'],'retainedoriginalfeature-extraction envelope')
    acquisitions={}
    for role in role_inventory:
        path=PRIMARY/'inputs'/f'{role.upper()}_ACQUISITION.json'
        if not path.is_file():
            acquisitions[role]=dict(status='not_complete_or_not_recorded',expected=role_inventory[role]);continue
        ledger=read(path);actual={(r['speaker'],r['member']):r for r in ledger['records']};chosen={k:r for k,r in expected.items() if r['role']==role}
        check('acquisition exact registeredcoverage: '+role,len(actual)==len(ledger['records']) and set(actual)==set(chosen))
        check('acquisition source/cohort/rolebinding: '+role,ledger['role']==role and ledger['cohort_sha256']==sha(cohort_path) and ledger['protocol_sha256']==sha(PRIMARY/'PROTOCOL.json'))
        check('acquisition exactbytes/roles: '+role,all(r['bytes']==chosen[k]['bytes'] and r['role']==role and len(r['sha256'])==64 for k,r in actual.items()))
        acquisitions[role]=dict(status='complete_metadata_verified',ledger_sha256=sha(path),clips=len(actual),raw_bytes=sum(r['bytes'] for r in actual.values()),new_raw_bytes=sum(r['bytes'] for r in actual.values() if not r['reused']),reused_raw_bytes=sum(r['bytes'] for r in actual.values() if r['reused']),new_compressed_member_payload_bytes=sum(chosen[k]['compressed_bytes'] for k,r in actual.items() if not r['reused']),reused_clips=sum(r['reused'] for r in actual.values()),new_clips=sum(not r['reused'] for r in actual.values()),source_sha256=ledger['source_sha256'],raw_media_read_by_inventory=False)
    receipts=[];cpu=Decimal(0);wrapper=Decimal(0);pending=[]
    for owner,root in [('primary',PRIMARY),('secondary',SECONDARY)]:
        for path in sorted(root.glob('*.receipt.json')):
            r=read(path);completed=r.get('status')=='completed' and r.get('total_cpu_seconds') is not None
            phase=stage(r)
            if path.name.startswith('source_qa_'):phase='shared/source_qa/'+path.name.removeprefix('source_qa_').removesuffix('.receipt.json')
            row=dict(owner=owner,path=str(path.relative_to(REPO)),sha256=sha(path),stage=phase,status=r.get('status'),returncode=r.get('returncode'),cpu_seconds=r.get('total_cpu_seconds'),wall_seconds=r.get('wall_seconds'),started_utc=r.get('started_utc'),finished_utc=r.get('finished_utc'),command=r.get('command'),artifacts=r.get('artifacts',[]),complete_child_accounting=completed)
            if completed:
                cpu+=Decimal(str(r['total_cpu_seconds']));wrapper+=Decimal(str(r.get('wrapper_cpu_seconds') or 0))
            else:pending.append(row['path'])
            # Held artifacts are deliberately neither opened nor rehashed here.
            row['held_artifact_contents_not_read']=True
            receipts.append(row)
    bystage={r['stage']:r for r in receipts}
    if 'shared/acquire/development' in bystage:
        for stage_name in ['primary/train/train','secondary/train/train']:
            check(stage_name+' finished before developmentrawacquisition',datetime.fromisoformat(bystage[stage_name]['finished_utc'])<datetime.fromisoformat(bystage['shared/acquire/development']['started_utc']))
    required_confirmation_evaluations=['primary/evaluate/confirmation','secondary/evaluate/confirmation']
    final_ready=not pending and all(name in bystage and bystage[name]['complete_child_accounting'] for name in required_confirmation_evaluations)
    source_qa={}
    for role in ['development','confirmation']:
        path=PRIMARY/f'{role.upper()}_SOURCE_QA.json'
        if path.is_file():
            q=read(path)
            source_qa[role]={k:q.get(k) for k in ['status','registered_clips','registered_actors','qualified_source_clips','failed_source_clips','models_loaded','scores_generated','method_changed','valid_subset_adoption']}
            source_qa[role]['sha256']=sha(path)
    holds={}
    for role in ['development','confirmation']:
        path=PRIMARY/f'{role.upper()}_HOLD.json'
        if path.is_file():
            h=read(path);holds[role]={k:h.get(k) for k in ['status','registered_clips','registered_actors','qualified_source_clips','failed_source_clips','aggregate_model_scores','valid_subset_scores','retained_feature_bank','padding_or_short_prefix_exception','registered_sample_replaced','source_or_candidate_changed']}
    return dict(schema='hcsn.grid.independent-provenance-cost-inventory.v1',inventory_source_sha256=sha(__file__),fit_inventory=dict(primary_new_fits=14,secondary_new_fits=5,shared_existing_models_copied_without_refit=9,total_new_fits=19),snapshot_utc=datetime.now(timezone.utc).isoformat(),checks_passed=True,check_count=len(checks),checks=checks,source_and_train_artifact_bindings=bindings,
        selected_role_inventory=role_inventory,selected_raw_bytes=161257472,selected_compressed_payload_bytes=cohort['compressed_payload_bytes'],acquisition_metadata=acquisitions,
        publication_chain=dict(primary_source=pubs,secondary_source=secondary_pubs,ordering_evidence_scope='Exactcross-fileSHA/commitbindings and recordedstagepermissions plus meterUTC training-before-heldraw ordering. This inventory makes no new GitHubrequests to independently reauthenticate remotecommit timestamps.',v2_payload_count_correction=dict(original_published_counter=0,corrected_observation=None,reason=addendum['correction'],actual_order=addendum['actual_order'])),
        outer_receipt_count=len(receipts),failed_outer_receipt_count=sum(r['returncode'] not in [None,0] for r in receipts),complete_known_child_cpu_by_owner={owner:float(sum((Decimal(str(r['cpu_seconds'])) for r in receipts if r['owner']==owner and r['complete_child_accounting']),Decimal(0))) for owner in ['primary','secondary']},shared_phase_receipts=[r['path'] for r in receipts if r['stage'].startswith('shared/')],
        complete_known_child_cpu_seconds=float(cpu),cpu_quantity_kind='Lowerbound from all currently completed primary/secondary outer wait4 receipts, including nonzero-exit failures; shared acquisition/metadata each counted once and nestedbody/fit times never added',reported_wrapper_cpu_seconds_partial=float(wrapper),wrapper_scope='Separateknown parent-process partialtimers; initial/finalreceipt and interpreter startup gaps remain, not part of childsubtotal',receipts=receipts,pending_receipts=pending,
        final_cost_inventory_ready=final_ready,required_confirmation_evaluation_stages=required_confirmation_evaluations,source_quality_metadata=source_qa,
        parallel_wall_total_seconds=None,wall_scope='Per-envelope wall times retained only; parallel wall durations are never summed',source_holds=holds,
        omitted_or_external_costs=[dict(item='First failed-prefix probe QA',cpu_seconds=None,scope='Unmetered diagnostic before the separately metered full registered role sourceQA'),dict(item='Original32speaker1 training-source pilot and initial geometry/source discovery',cpu_seconds=None,scope='Earlierowner activities outside this GRID primary/secondary subtotal; must be attributed once if aggregating cross-componentcampaign cost'),dict(item='Third-party checkpoint acquisition and originalLRW/LibriSpeechpretraining',cpu_seconds=None,scope='External/upstreamdependency costs, not zero and not duplicated as GRIDfit cost'),dict(item='Audit, sourceauthoring, publication, packaging and transfers',cpu_seconds=None,scope='Outside core outerreceipts unless separately metered; this inventory doesnot complete that history')],
        isolated_AT_vs_AVT_deployment_latency_measured=False,cost_interpretation='PrimaryjointA/Vextraction mixesdecoder+encoder work. ThecampaignCPUsubtotal cannot establish isolatedAT-versusAVTdeployment speed, latency, energy or netadoptionbenefit.',
        held_media_features_or_results_read=False,numerical_quality_outcome_audited=False,energy_joules=None,all_blockers_closed=False,production_activation=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    if not args.out.resolve().is_relative_to(HERE.resolve()):raise ValueError('Inventory output must remain in additiveownedintegrationdirectory')
    result=inventory()
    if not result['final_cost_inventory_ready']:raise ValueError('Wait for all outer receipts and both confirmation evaluation envelopes before finalinventory')
    with args.out.open('x') as stream:json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps(dict(checks=result['check_count'],cpu_lower_bound=result['complete_known_child_cpu_seconds'],pending_receipts=result['pending_receipts'],source_holds=result['source_holds']),sort_keys=True))
