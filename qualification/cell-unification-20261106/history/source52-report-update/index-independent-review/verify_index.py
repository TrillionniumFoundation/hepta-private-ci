#!/usr/bin/env python3
"""Independent local byte/static review of the exact source52 INDEX candidate.

Reads closed files only. Does not import or execute the builder, run native
tools, or write the formal INDEX, ledger, reports, source or existing groups.
"""
import ast
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

WORK = Path('/workspace/scratch/08f5efd48967')
REPORT = WORK/'hepta-cell/qualification/cell-unification-20261106'
FORMAL = REPORT/'native-evidence'
PREP = WORK/'source52-index-preparation'
OUT = WORK/'source52-index-independent-review'
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'


def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def read(path,sha=None,size=None):
    assert path.is_file() and not path.is_symlink(),str(path)
    raw=path.read_bytes()
    if sha is not None: assert pin(raw)['sha256']==sha,str(path)
    if size is not None: assert len(raw)==size,str(path)
    return raw


def encoded(value):
    return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()


def create(name,value):
    path=OUT/name
    raw=encoded(value)
    path.parent.mkdir(parents=True,exist_ok=True)
    assert not path.exists() or path.read_bytes()==raw,'create-only mismatch: '+str(path)
    if not path.exists():
        with path.open('xb') as f:f.write(raw)
    return {'path':name,**pin(raw)}


def main():
    old_path=REPORT/'history/source52-report-update/NATIVE-EVIDENCE-INDEX.json'
    old_raw=read(old_path,'eec856c07862186f583963794cfaa951882a5a38321dc042cdfa62d3837fae8e',1204766)
    leaves_raw=read(PREP/'CHECKPOINT5-NATIVE-GIT-LEAVES.json','4f30945a4ed6b96d61c15033722b4e7a9ddad96b6a892180d625b355a8fbb8a6',347697)
    facts_raw=read(PREP/'FACTS.json','4cc9ce8cb9f06aeca74793d4b60961a87e3222c3e2234fd6e3a839c59f37a01b',3735)
    candidate_raw=read(PREP/'candidate/INDEX.candidate.json','e747d83505480b71517f975509a8c7f97ae383f552ac435e6b752fe38ff3729f',1545575)
    construction_raw=read(PREP/'candidate/ROOT-CONSTRUCTION-READBACK.json','d9e36082a9663c52a546b581ee3db3110511a9c3c4f3f6570e8e390acc0c3161',724)
    builder_raw=read(PREP/'build_index.py')
    ast.parse(builder_raw)
    old,leaves,facts,candidate,construction=map(json.loads,[old_raw,leaves_raw,facts_raw,candidate_raw,construction_raw])
    assert len(old['artifacts'])==1673
    old_rows={r['path']:r for r in old['artifacts']}
    actual={r['path']:r for r in leaves['files']}
    assert len(old_rows)==1673 and len(actual)==len(leaves['files'])==1724
    assert leaves['checkpoint_commit']=='e904dc657d8f511380178d32f8563175ce7bfaa8'
    assert leaves['report_tree']=='01433bda50236b306199e9c0fa767583d7fd1d96'
    assert set(old_rows)<set(actual) and 'INDEX.json' not in old_rows
    assert actual['INDEX.json']['git_blob']==pin(old_raw)['git_blob'] and actual['INDEX.json']['bytes']==len(old_raw)
    assert candidate['artifacts'][:1673]==old['artifacts']
    assert encoded(candidate['artifacts'][:1673])==encoded(old['artifacts'])
    bindings=candidate['historical_artifact_git_bindings']
    assert len(bindings)==1673 and [r['path'] for r in bindings]==[r['path'] for r in old['artifacts']]
    for row,binding in zip(old['artifacts'],bindings):
        git=actual[row['path']]
        assert git['mode']=='100644' and git['bytes']==row['bytes']
        if 'git_blob' in row: assert git['git_blob']==row['git_blob']
        assert binding=={'path':row['path'],'historical_sha256':row['sha256'],
                         'published_git_blob':git['git_blob'],'published_size':git['bytes'],
                         'raw_bytes_re_read_this_inventory':False,'source_index_git_blob':pin(old_raw)['git_blob'],
                         'source_checkpoint':leaves['checkpoint_commit']}
    extra_names=set(actual)-set(old_rows)-{'INDEX.json'}
    assert len(extra_names)==50
    extras=candidate['additional_inherited_git_paths_not_in_prior_raw_inventory']
    assert extras==[{**actual[name],'raw_sha256_observed_this_inventory':None,'raw_bytes_re_read_this_inventory':False} for name in sorted(extra_names)]
    assert candidate['unmaterialized_binary_references']==old['unmaterialized_binary_references']
    assert encoded(candidate['unmaterialized_binary_references'])==encoded(old['unmaterialized_binary_references'])
    assert len(candidate['unmaterialized_binary_references'])==candidate['unmaterialized_reference_count']==139

    prefix='qualification/cell-unification-20261106/native-evidence/'
    expected_plans={
        'r26-formal-root-preparation/ROOT-UPLOAD-PLAN.json':('r26-project-checkpoint',113,'d8f96e73974d76e011c9ca65642225ad7b589fc651db8d6e7a3d37c76b199567'),
        'source52-formal-root-preparation/ROOT-UPLOAD-PLAN.json':('source52-repair-apply-checkpoint',149,'b840ffe6f6b182ae1fa8beb957fc87aee7304f61248301955327740129135199'),
        'r28-formal-root-preparation/ROOT-UPLOAD-PLAN.json':('r28-project-checkpoint',174,'a103432d676069456abe1eb924077da154db533c13efb7bd357bf0166477d84e')}
    assert {v['path'] for v in candidate['addition_plans']}==set(expected_plans)
    observed,group_reports,seals=[],[],[]
    for plan_pin in candidate['addition_plans']:
        group,count,sha=expected_plans[plan_pin['path']]
        raw=read(WORK/plan_pin['path'],sha)
        assert pin(raw)=={k:plan_pin[k] for k in ('bytes','sha256','git_blob')}
        plan=json.loads(raw)
        assert plan['file_count']==len(plan['files'])==count
        assert plan['artifact_bytes']==sum(r['bytes'] for r in plan['files'])
        group_rows=[]
        for row in plan['files']:
            assert row['repo_path'].startswith(prefix+group+'/')
            rel=row['repo_path'][len(prefix):]
            p=PurePosixPath(rel)
            assert not p.is_absolute() and '..' not in p.parts and '.' not in p.parts
            assert row['mode']=='100644'
            local=Path(row['local_path'])
            assert local.resolve()==(FORMAL/rel).resolve()
            data=read(local)
            assert pin(data)=={k:row[k] for k in ('bytes','sha256','git_blob')}
            assert rel not in old_rows and rel not in extra_names
            entry={'path':rel,**pin(data)}
            observed.append(entry);group_rows.append(entry)
            if len(p.parts)==2 and (rel.endswith('/ATTACHMENT-MANIFEST.json') or rel.endswith('/HANDOFF-MANIFEST.json')):
                seals.append(entry)
        assert len({r['path'] for r in group_rows})==count
        group_reports.append({'group':group,'files':count,'raw_bytes':sum(r['bytes'] for r in group_rows),
                              'plan':plan_pin,'all_raw_sha_git_blob_verified':True,
                              'recomputed_rows_digest':pin(encoded(sorted(group_rows,key=lambda r:r['path'])))})
    observed.sort(key=lambda r:r['path'])
    assert len(observed)==len({r['path'] for r in observed})==436
    assert candidate['observed_local_artifacts']==observed==candidate['artifacts'][1673:]
    assert candidate['artifacts']==old['artifacts']+observed
    assert len(candidate['artifacts'])==len({r['path'] for r in candidate['artifacts']})==2109
    assert candidate['verified_local_group_or_file_seals']==seals
    assert candidate['current_raw_hash_count']==436 and candidate['historical_artifact_count']==1673
    assert candidate['artifact_count']==2109 and candidate['inherited_additional_git_reference_count']==50
    assert candidate['unsealed_local_paths_not_indexed']==[] and candidate['self_excluded'] is True
    assert candidate['formal_INDEX_written'] is False and candidate['all_prior_Git_paths_retained_by_publication_plan_required'] is True
    assert candidate['qualification_not_inferred_from_integrity'] is True
    for key in ['source_identity','last_closed_workspace_gate','last_closed_complete_project_gate','prior_source51_r26_result',
                'candidate_state','current_workspace_snapshot','snapshot_basis','source_ledger_snapshot','science','authority']:
        assert candidate[key]==facts[key]
    assert candidate['facts_input']=={'path':'source52-index-preparation/FACTS.json',**pin(facts_raw)}
    assert candidate['prior_actual_git_leaves']=={'path':'source52-index-preparation/CHECKPOINT5-NATIVE-GIT-LEAVES.json',**pin(leaves_raw)}
    assert facts['source_identity']=={'commit':COMMIT,'tree':TREE,'stage':52,'changed_paths':195,'rust_paths':181,'other_paths':14,
                                      'gitdata_identity_not_native_checkout':True}
    assert facts['science']=='HOLD' and facts['authority']=='DENY_ALL'
    assert facts['last_closed_workspace_gate']==old['last_closed_workspace_gate']
    assert facts['last_closed_workspace_gate']['exit_code']==100

    closure_raw=read(FORMAL/'r28-project-checkpoint/CLOSURE.json','4b0deafe8f0b6b6d405716eae380de0e5253efbc4677b9eafdab1b768b5a3465',3106)
    closure=json.loads(closure_raw);project=facts['last_closed_complete_project_gate']
    assert project['source_commit']==closure['source_commit']==COMMIT and project['source_tree']==closure['source_tree']==TREE
    assert project['outcome']=='PASS' and project['exit_code']==project['strict_exit_code']==project['outer_exit_code']==0
    assert project['counts']=={'PASS':1564,'FAIL':0,'TIMEOUT':0} and project['unique_results']==1564 and project['reported_skipped']==3
    assert project['python_pass']==32 and project['python_reported_skip']==0
    assert closure['counts']=={'unique':1564,'PASS':1564,'FAIL':0,'TIMEOUT':0,'reported_skipped':3}
    assert closure['original_phase_exits']=={'python-runner':0,'strict':0,'tests':0}
    r26=json.loads(read(FORMAL/'r26-project-checkpoint/CLOSURE.json'))
    assert facts['prior_source51_r26_result']['counts']=={s:r26['counts'][s] for s in ('PASS','FAIL','TIMEOUT')}
    assert facts['prior_source51_r26_result']['exit_code']==100 and r26['original_outer_exit']==100

    snapshot=facts['current_workspace_snapshot']
    start=WORK/'native-validation-results/r29-start-closed'
    start_raw=read(start/'LOCAL-READBACK.json',snapshot['origin_readback']['sha256'],snapshot['origin_readback']['bytes'])
    start_review=json.loads(start_raw)
    for row in start_review['originals']:
        assert pin(read(start/'evidence'/row['path']))=={k:row[k] for k in ('bytes','sha256','git_blob')}
    for row in start_review['controller_originals']:
        assert pin(read(start/row['path']))=={k:row[k] for k in ('bytes','sha256','git_blob')}
    assert snapshot['job_id']==start_review['job_id']=='1a1b1f83e4b-fc05-7bcd'
    assert snapshot['command']==start_review['original_workspace_command']==['just','test','--locked','--retries','0']
    assert snapshot['started_actual'] is True and snapshot['as_of_fixed_start_evidence_snapshot_not_live_status'] is True
    assert snapshot['nextest_started'] is None and snapshot['terminal_counts'] is None and snapshot['terminal_exit_code'] is None
    fresh=WORK/'source52-final-scope-preparation/input'
    metadata_packed=read(fresh/'native-workspace-r29-metadata.json.gz')
    metadata_raw=gzip.decompress(metadata_packed)
    assert pin(metadata_raw)['sha256']==snapshot['metadata_sha256'] and len(metadata_raw)==snapshot['metadata_bytes']==937659
    metadata=json.loads(metadata_raw)
    assert len(metadata['workspace_members'])==len(set(metadata['workspace_members']))==snapshot['workspace_members']==193
    assert len(metadata['workspace_default_members'])==len(set(metadata['workspace_default_members']))==snapshot['workspace_default_members']==193
    scope_raw=read(fresh/'native-workspace-r29-scope.json',snapshot['scope_sha256'],snapshot['scope_bytes'])
    scope=json.loads(scope_raw)
    assert scope['source_commit']==COMMIT and scope['source_tree']==TREE
    packages={p['id']:p for p in metadata['packages']}
    for key in ('workspace_members','workspace_default_members'):
        ids=[row['id'] for row in scope[key]]
        assert len(ids)==len(set(ids))==193 and set(ids)==set(metadata[key])
        for row in scope[key]:
            assert row['name']==packages[row['id']]['name']
            if 'manifest_path' in row: assert row['manifest_path']==packages[row['id']]['manifest_path']
    assert scope['command']==snapshot['command'] and scope['metadata_generated_on_current_source'] is True
    assert scope['old_metadata_reused_as_current'] is False and scope['all_platforms_features_external_services_qualified'] is False
    receipt_raw=read(fresh/'native-workspace-r29-metadata-receipt.json')
    receipt=json.loads(receipt_raw)
    raw_result=read(fresh/'native-workspace-r29-metadata-raw-process-result.json')
    original_rc=json.loads(raw_result)
    assert receipt['exit_code']==original_rc['exit_code']==snapshot['fresh_metadata_exit_code']==0
    assert receipt['stdout']==pin(metadata_raw)
    assert receipt['raw_process_result']=={'path':'native-workspace-r29-metadata-raw-process-result.json',**pin(raw_result)}
    assert receipt['source_tree']==TREE and receipt['source_commit']==COMMIT and receipt['source_guards_pass'] is True
    launch=json.loads(read(start/'controller/launch.json'))
    initial=json.loads(read(start/'controller/initial-process-status.json'))
    assert launch['job']['id']==snapshot['job_id'] and launch['job']['launch_state']=='launched' and launch['launch']['ok'] is True
    assert initial['job_id']==snapshot['job_id'] and initial['state']=='running' and 'exit_code' not in initial
    assert initial['systemd']['ActiveState']=='active' and initial['systemd']['SubState']=='running'
    ledger_path=WORK/'source52-report-update-preparation/new-files/history/source52-ledger-snapshot/publication-ledger.json'
    ledger_raw=read(ledger_path,facts['source_ledger_snapshot']['sha256'],facts['source_ledger_snapshot']['bytes'])
    assert facts['source_ledger_snapshot']['not_a_permanent_current_attachment_count'] is True
    assert construction['prior1673_rows_preserved_exact'] is True and construction['new_raw_hashed_rows']==436
    assert construction['total_raw_hash_inventory_rows']==2109
    assert {k:construction['index'][k] for k in ('bytes','sha256','git_blob')}==pin(candidate_raw)

    # Static review: no import/exec of build_index.py; only this separate reader ran.
    report={
        'schema':'hepta.source52-index-independent-review.v1','result':'CLEAR','material_blockers':[],
        'candidate':{'path':'source52-index-preparation/candidate/INDEX.candidate.json',**pin(candidate_raw)},
        'builder':{'path':'source52-index-preparation/build_index.py',**pin(builder_raw),'ast_valid':True,'builder_executed_by_reviewer':False},
        'facts':{'path':'source52-index-preparation/FACTS.json',**pin(facts_raw)},
        'previous_index':{'path':str(old_path.relative_to(WORK)),**pin(old_raw)},
        'checkpoint5_actual_leaves':{'path':'source52-index-preparation/CHECKPOINT5-NATIVE-GIT-LEAVES.json',**pin(leaves_raw)},
        'construction_readback':{'path':'source52-index-preparation/candidate/ROOT-CONSTRUCTION-READBACK.json',**pin(construction_raw)},
        'preserved_historical_rows':1673,'all_old_row_fields_order_and_values_preserved':True,
        'checkpoint5_native_paths':1724,'checkpoint5_index_self_entry':1,
        'old1673_git_blob_size_mode_bindings_verified':True,'old_raw_bytes_re_read_here':False,
        'additional_inherited_git_only_paths':50,'git_only_paths_have_no_new_raw_hash_claim':True,
        'new_raw_hashed_files':436,'new_groups':group_reports,'all_new_raw_bytes_sha256_gitblob_and_paths_verified':True,
        'total_raw_hash_rows':2109,'new_vs_old_or_git_only_overlap':[],
        'unmaterialized_reference_count':139,'all139_original_reference_records_exactly_preserved':True,
        'references_not_promoted_to_materialized_or_rehashed_status':True,
        'r28_project_state':{'source_commit':COMMIT,'source_tree':TREE,'closure':pin(closure_raw),'counts':project['counts'],
                             'unique':1564,'reported_skipped':3,'python':32,'three_phase_exits':[0,0,0],
                             'only_same_source_project_gate_qualified':True},
        'r26_prior_failed_state_preserved':True,'r23_last_closed_workspace_fact_exactly_preserved':True,
        'r29_fixed_start_snapshot':{'job_id':snapshot['job_id'],'launch_observed':True,'fresh_metadata_original_exit':0,
                                  'metadata':pin(metadata_raw),'scope':pin(scope_raw),'metadata_receipt':pin(receipt_raw),
                                  'workspace_members':193,'workspace_default_members':193,
                                  'nextest_started':None,'terminal_counts':None,'terminal_exit_code':None,
                                  'original_running_status_exit_code_field_present':False,
                                  'interim_systemd_success_fields_not_used_as_terminal_result':True,
                                  'as_of_fixed_start_evidence_not_live_status':True,'active_log_read':False},
        'ledger_snapshot':{'path':str(ledger_path.relative_to(WORK)),**pin(ledger_raw),
                           'is_pending_report_overlay_input_not_rewritten_formal_ledger':True,
                           'snapshot_not_current_attachment_total':True},
        'static_builder_findings':[
            'Prior artifact rows are concatenated unchanged; no old raw hash is recomputed or rewritten.',
            'Actual checkpoint5 bindings retain Git-only provenance and explicitly mark no new raw read.',
            'New plan files are read and checked before construction; duplicate new/prior paths are rejected for these fixed inputs.',
            'Frozen facts preserve project PASS separately from the still-unqualified workspace snapshot.',
            'The builder output is an isolated candidate and does not perform native execution or Git publication.'
        ],
        'publication_boundary':'This review covers the exact candidate and three addition plans only. Retention of all1843 prior report Git paths remains the separate root overlay requirement; not claimed executed here.',
        'root_adoption_expected_later':'Only formal_INDEX_written=true plus an explicit root_adoption declaration; preserve this reviewed candidate and review as history.',
        'formal_INDEX_modified':False,'ledger_modified':False,'root_three_reports_modified':False,
        'reviewer_preparation_correction':'The first local checker expected an exit_code key in the original running process status. The original has no such terminal field; the final checker explicitly verifies its absence. No candidate or original bytes were changed.',
        'native_or_rust_or_formatter_executed':False,'science':'HOLD','authority':'DENY_ALL'}
    report_pin=create('INDEPENDENT-REVIEW.json',report)
    script_pin={'path':'verify_index.py',**pin(Path(__file__).read_bytes())}
    handoff=create('HANDOFF-MANIFEST.json',{'schema':'hepta.source52-index-review-handoff.v1','files':[script_pin,report_pin],
                                        'reviewed_candidate_sha256':pin(candidate_raw)['sha256'],'result':'CLEAR','formal_modified':False})
    print(json.dumps({'report':report_pin,'handoff':handoff,'result':'CLEAR','old_rows':1673,'new_raw_files':436,
                      'raw_rows':2109,'git_only_refs':50,'unmaterialized_refs':139},indent=2))


if __name__=='__main__':
    assert __debug__
    main()
