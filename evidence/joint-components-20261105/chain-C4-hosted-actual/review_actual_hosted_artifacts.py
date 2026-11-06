#!/usr/bin/env python3
"""Validate actual hosted artifacts and preserve selected original members losslessly."""
from pathlib import Path, PurePosixPath
import collections
import hashlib
import json
import tarfile
import zipfile

HERE=Path(__file__).resolve().parent
HEAD='8df4b21d893906570d48f5beafabb3b31e0aefbc'
TREE='6f5aaa2af0432e27e24b6bd2ad18013ab4423d14'
sha=lambda b:hashlib.sha256(b).hexdigest()
def dump(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def rpc(name):
    x=json.loads((HERE/name).read_bytes())
    assert not x.get('isError',False)
    v=x.get('structuredContent')
    if v is None:v=json.loads(x['content'][0]['text'])
    if isinstance(v,dict) and isinstance(v.get('content'),str):v=json.loads(v['content'])
    return v
def fields(v,names):return {k:v.get(k) for k in names}

specs=[
 ('W1-fresh-service-head','C4-W1-fresh-service-head-original.zip','C4-W1-artifacts.raw.json',13462092257,'C4-W1-head-zip-index.json'),
 ('priority-service-head','C4-priority-service-head-original.zip','C4-priority-artifacts.raw.json',13462094914,'C4-priority-service-head-zip-index.json'),
 ('history-head','C4-history-head-original.zip','C4-priority-artifacts.raw.json',13464309534,'C4-history-head-zip-index.json'),
 ('native-campaign-head','C4-native-campaign-head-original.zip','C4-native-artifacts.raw.json',13462216107,'C4-native-campaign-head-zip-index.json'),
]
out=HERE/'root-artifact-review'
selected=out/'selected-original-members'
assert not selected.exists(), 'fresh output required; preserve a prior failed review before retry'
selected.mkdir(parents=True)
inventories=[]
all_sums={}
for key,filename,api,aid,prior_index in specs:
    p=HERE/filename
    b=p.read_bytes();digest=sha(b)
    artifacts=rpc(api)['artifacts']
    matches=[a for a in artifacts if a['id']==aid]
    assert len(matches)==1
    a=matches[0]
    assert a['workflow_run']['head_sha']==HEAD
    assert len(b)==a['size_in_bytes'] and 'sha256:'+digest==a['digest']
    del b
    old=json.loads((HERE/prior_index).read_bytes())
    assert old['bytes']==p.stat().st_size and old['sha256']==digest
    members=[];sums={};seen=set()
    with zipfile.ZipFile(p) as z:
        assert len(z.infolist())==len(old['members'])
        for zi in z.infolist():
            name=zi.filename
            pure=PurePosixPath(name)
            assert not pure.is_absolute() and '..' not in pure.parts and name not in seen and not zi.is_dir()
            assert zi.flag_bits & 1 == 0
            seen.add(name)
            excluded=(pure.suffix in {'.sqlite','.lock','.sqlite-shm','.sqlite-wal','.dev-key'} or (key=='history-head' and name.startswith('history-native/long-history/packets/')))
            dest=selected/key/name
            if not excluded:dest.parent.mkdir(parents=True,exist_ok=True)
            h=hashlib.sha256();length=0
            sink=None if excluded else dest.open('xb')
            try:
                with z.open(zi) as src:
                    while True:
                        chunk=src.read(1024*1024)
                        if not chunk:break
                        h.update(chunk);length+=len(chunk)
                        if sink is not None:sink.write(chunk)
            finally:
                if sink is not None:sink.close()
            assert length==zi.file_size
            sums[name]=h.hexdigest()
            members.append({'path':name,'bytes':length,'sha256':h.hexdigest(),'zip_crc32':f'{zi.CRC:08x}','selected_for_lossless_republication':not excluded})
            if not excluded:
                assert sha(dest.read_bytes())==h.hexdigest()
        # The two original manifest hash maps cover original retained raw files.
        pref={'W1-fresh-service-head':'fresh-service/','priority-service-head':'from-zero-native/'}.get(key)
        if pref:
            m=json.loads(z.read(pref+'manifest.json'))
            for name,d in m['files'].items():
                assert sums[pref+name]==d, (key,name)
            assert m['source_before']==m['source_after']
            s=m['source_before']
            assert s['commit']==HEAD and s['tree']==TREE and s['tracked_source_identity']['tracked_worktree_verified']
            assert m['binary_sha256_before']==m['binary_sha256_after']==sums[pref+'public_v3_from_zero']
        if key=='history-head':
            m=json.loads(z.read('history-native/manifest.json'))
            assert m['source_before']==m['source_after']
            assert m['source_before']['commit']==HEAD and m['source_before']['tree']==TREE
            for mk,path in [('log','history-native/history.log'),('resources','history-native/history-resources.txt'),('summary_file','history-native/long-history/summary.json')]:
                assert sums[path]==m[mk]['sha256']
        if key=='native-campaign-head':
            m=json.loads(z.read('results.json'))
            assert m['expected_head']==HEAD and m['expected_tree']==TREE
            assert m['source_after']['tested_commit']==HEAD and m['source_after']['tested_tree']==TREE
            assert m['binary']['sha256_before']==m['binary']['sha256_after']==sums[m['binary']['retained']]
            for attempt in m['attempts']:
                assert sums[attempt['report_directory']+'/report.json']==attempt['report_sha256']
                for stream in ['stdout','stderr']:
                    step=attempt['step'];assert sums[step[stream]]==step[stream+'_sha256']
    inv={'schema':'actual-hosted-artifact-complete-member-sha256-inventory-v1','key':key,
         'artifact_id':aid,'artifact_name':a['name'],'workflow_run':a['workflow_run'],
         'original_zip':{'filename':filename,'bytes':p.stat().st_size,'sha256':digest},
         'actual_artifact_list_rpc':{'path':api,'sha256':sha((HERE/api).read_bytes())},
         'member_count':len(members),'member_bytes':sum(v['bytes'] for v in members),
         'selected_member_count':sum(v['selected_for_lossless_republication'] for v in members),
         'selected_member_bytes':sum(v['bytes'] for v in members if v['selected_for_lossless_republication']),
         'all_zip_members_read_to_eof_and_crc_checked':True,'members':members,
         'excluded_member_policy':'SQLite databases/WAL/SHM, empty lock files, dev key bodies, and the history packet directory are inventoried and retained in the original downloaded ZIPs; not included in the selected-member tar. No claim that the complete original ZIP is republished in this evidence commit.'}
    dump(out/(key+'-complete-inventory.json'),inv)
    inventories.append({k:v for k,v in inv.items() if k!='members'})
    all_sums[key]=sums

def original(key,path):return json.loads((selected/key/path).read_bytes())
w=original('W1-fresh-service-head','fresh-service/manifest.json')
p=original('priority-service-head','from-zero-native/manifest.json')
h=original('history-head','history-native/manifest.json')
n=original('native-campaign-head','results.json')
checks1=rpc('C4-checks.raw.json'); checks2=rpc('C4-checks-page2.raw.json')
checks={q['id']:q for q in checks1['check_runs']+checks2['check_runs']}
assert len(checks)==checks1['total_count']==checks2['total_count']==102
workflows=rpc('C4-workflow-runs.raw.json')
def phase_summary(q):
    return {'mode':q['mode'],'workers':q['workers'],'window_ns':q['window_ns'],
      'business':fields(q['business'],['required_signed_transactions','reported_independently_confirmed_in_window','unconfirmed','unknown','reported_finite_business_target_met','observed_success_latency_ns','unconfirmed_latency_lower_bound_ns']),
      'signed_submit_ack':fields(q['signed_submit_ack'],['attempts','successful_in_original_window','failed_or_late']),
      'history_response':fields(q['history_response'],['attempts','successful_in_original_window','failed_or_late']),
      'independent_page_replay':fields(q['independent_page_replay'],['attempts','accepted_in_original_window','failed_or_late'])}
campaign=[]
for a in n['attempts']:
    q=original('native-campaign-head',a['report_directory']+'/report.json')
    campaign.append({'number':a['number'],'native_exit':a['step']['returncode'],'elapsed_seconds':a['step']['elapsed_seconds'],
      'outer_timeout_seconds':a['step']['outer_stage_timeout_seconds'],
      'finite_experiment_criteria_met':q['finite_experiment_criteria_met'],
      'report_validation_failure':a['report_validation_failure'],'phase_startup_errors':a['phase_startup_errors'],
      'phases':[fields(v,['mode','duration_seconds','attacker_processes_requested','attacker_processes_ready','finite_phase_criteria_met','all_signed_rounds_confirmed_in_window','full_work_accepted','full_work_failed','receiver_client_state_equal','genuine_budget_depletion_observed']) for v in q['phases']]})
review={'schema':'root-actual-C4-hosted-failure-review-v1','source':{'commit':HEAD,'tree':TREE},
 'artifact_integrity':inventories,
 'workflow_snapshot':{'total_count':workflows['total_count'],'scope':'Actual finite API observations at different read times; not a synchronized or final all-jobs verdict.',
   'runs':[fields(q,['id','name','status','conclusion','head_sha','html_url']) for q in workflows['workflow_runs']]},
 'checks_snapshot':{'returned_pages':2,'unique_checks':len(checks),'total_reported':102,
   'status_counts':dict(collections.Counter(q['status'] for q in checks.values())),
   'conclusion_counts':dict(collections.Counter(str(q['conclusion']) for q in checks.values()))},
 'W1_fresh_service_manifest':{'manifest_sha256':all_sums['W1-fresh-service-head']['fresh-service/manifest.json'],
   'passed':w['passed'],'failures':w['failures'],'original_runs':w['runs'],
   'scope':'Independently reviewed separately; native original exit zero does not satisfy finite business confirmation.'},
 'priority_original_five':{'manifest_sha256':all_sums['priority-service-head']['from-zero-native/manifest.json'],
   'all_named_tests_passed':p['all_named_tests_passed'],'format_passed':p['format_passed'],'passed':p['passed'],
   'execution_finished':p['execution_finished'],'failures':p['failures'],
   'runs':[{'name':v['name'],**fields(v['process'],['exit_code','timed_out','wall_ns'])} for v in p['runs']],
   'original_gate_validated':p['confirmation_observation']['original_gate_validated'],
   'original_gate_validation_error':p['confirmation_observation']['original_gate_validation_error'],
   'phases':[phase_summary(q) for q in p['confirmation_observation']['phases']]},
 'history':{'manifest_sha256':all_sums['history-head']['history-native/manifest.json'],
   'process':h['process'],'passed':h['passed'],'failures':h['failures'],'summary':h['summary'],
   'observed_test_log_seconds':3085.27,'resource_log_elapsed':'51:25.26',
   'note':'4105 retained packet files do not establish successful full sync/reopen/corrupt-index refusal. Actual history binary is not in this artifact; its manifest records before/after identity.'},
 'original_three_campaigns':{'results_sha256':all_sums['native-campaign-head']['results.json'],'failure':n['failure'],
   'original_inputs':n['original_inputs'],'public_phase_placement':n['public_phase_placement'],'runs':campaign},
 'local_review_preparation_history':['Initial local review stopped before ZIP member processing because the first artifact index uses bytes/sha256 instead of the later actual_bytes/actual_sha256 aliases. Original stderr preserved; corrected to the common original schema. No CI or source execution repeated.'],
 'new_learning_trial_or_ledger_reset':False,'new_ci_rerun_cancel_or_gate_change':False,
 'whole_public_liveness_gate':'HOLD_ACTUAL_ORIGINAL_HOSTED_GATES_FAILED',
 'all_eight_whole_gates':'HOLD',
 'scope':['Genuine hosted jobs replace the earlier queued-only observation for C4; the older desktop missing-host-identity observation remains true only of that desktop execution.',
          'Frozen-source same-host/loopback observations are not independent WAN/operator qualification.',
          'A native test exit, artifact upload, invariant check, completed work packet or ACK is not by itself the finite confirmed business target.',
          'All original ZIP bytes are locally preserved with provider digests. Selected members are republished losslessly; excluded originals remain available in the original provider artifacts and local ZIPs.']}
dump(out/'root-review.json',review)
tarpath=out/'selected-original-members.tar.xz'
with tarfile.open(tarpath,'w:xz',preset=3) as tar:
    for f in sorted(selected.rglob('*')):
        if f.is_file():tar.add(f,arcname=str(f.relative_to(selected)),recursive=False)
count=0
with tarfile.open(tarpath,'r:xz') as tar:
    for member in tar:
        assert member.isfile()
        key,path=member.name.split('/',1)
        stream=tar.extractfile(member);hs=hashlib.sha256();length=0
        for chunk in iter(lambda:stream.read(1024*1024),b''):hs.update(chunk);length+=len(chunk)
        assert hs.hexdigest()==all_sums[key][path] and length==member.size
        count+=1
assert count==sum(v['selected_member_count'] for v in inventories)
manifest={'schema':'actual-hosted-selected-original-member-publication-v1','archive_bytes':tarpath.stat().st_size,
 'archive_sha256':sha(tarpath.read_bytes()),'members':count,
 'original_member_bytes':sum(v['selected_member_bytes'] for v in inventories),'verified_readback':True,
 'root_review_sha256':sha((out/'root-review.json').read_bytes()),
 'complete_original_zip_republished':False,'original_provider_zip_inventory':inventories}
dump(out/'selected-original-delivery.json',manifest)
print(json.dumps({k:v for k,v in manifest.items() if k!='original_provider_zip_inventory'}))
