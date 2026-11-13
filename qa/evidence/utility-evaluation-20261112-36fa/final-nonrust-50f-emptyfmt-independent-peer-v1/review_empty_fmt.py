#!/usr/bin/env python3
"""Only compares immutable captured bytes; no producer or native code execution."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PINS={
 'RESULT.json':'800869ed57256984964dd3c8b9f29e09c496438a',
 'NORMAL.original.json':'0f7aee8fb7c354f234732b5791e78d63671cd894',
 'FMT_TERMINAL.original.json':'1d12f8870768081a3f35c32aaa9daab61e68a788',
 'ARTIFACTS.json':'0119bbc670ec82b93b5235d9e512f61f58baf409',
 'fmt.after.postimages.json':'f5c7643422eecfcde833cffc4cb61004f4f682ea',
 'fmt.after.postimages.json.gz.part-001.b64':'522981a1c63c0d98514e0b396692bf5d01853624'}
def ident(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
raw={};pins=[]
for n,sha in PINS.items():
 b=(ROOT/n).read_bytes();assert ident(b)['git_blob']==sha
 assert json.loads((ROOT/'github'/(n+'.GET.original.json')).read_bytes())['structuredContent']['content'].encode()==b
 raw[n]=b;pins.append({'name':n,**ident(b),'independent_full_get_equal':True})
r=json.loads(raw['RESULT.json']);stage=json.loads(raw['FMT_TERMINAL.original.json'])
sdk=json.loads(raw['NORMAL.original.json']);assert sdk['isError'] is False and len(sdk['content'])==1
n=json.loads(sdk['content'][0]['text'])
assert n['job_id']=='1a1d4a979d9-392-50f' and n['state']=='succeeded' and n['exit_code']==0
for k in ('timed_out','cancelled','automatic_retry'):assert n[k] is False
for k in ('output_complete','output_durable','terminal_publication_confirmed'):assert n[k] is True
assert all(v is False for v in n['log_truncated'].values())
assert r['format']=='hepta-reviewed-nonrust-final-format-result-v1' and r['status']=='APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
assert r['stages']==[stage] and stage['argv']==['just','fmt','--base','c0f78493f815780f68b9bf5e390a21314d79311f']
assert stage['timeout_seconds']==900 and stage['status']=='completed_review_required'
assert stage['execution']['returncode']==0 and stage['execution']['timed_out'] is False and stage['execution']['output_limit_exceeded'] is False
assert r['attempted_commands']==['fmt'] and r['not_run_commands']==[]
assert r['fix_dispatched'] is False and r['test_commands_dispatched']==0 and r['qualification'] is False
assert r['source_commit']=='d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
assert r['source_tree']=='a489b394666b8141840275128a780605b024cde0'
assert r['parents']==['cc57c7198db6293ccca562253c42fffbe2a04633']
assert r['formatter_changed_paths']==[] and r['format_source_stable'] is True
assert stage['retention']['postimages']['change_count']==0 and stage['retention']['postimages']['paths']==[]
assert r['application']==r['actual_final_source']
assert stage['retention']['inventory']==r['actual_final_source']['inventory']
assert r['actual_final_source']['complete'] is True
assert r['actual_final_source']['postimages']['all_actual_physical_leaf_count']==15243
assert r['actual_final_source']['postimages']['all_actual_physical_tree']=='8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
paths=['.github/blob-size-allowlist.txt','CALLERS.toml','qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json','qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py']
assert r['applied_paths']==paths==r['actual_final_source']['postimages']['paths']
assert r['actual_final_source']['postimages']['change_count']==4
assert {x['check']:x['status'] for x in r['final_audits']}=={'actual_complete_source_and_git':'verified','original_inputs':'verified','same_source_coordination_lock':'verified'}
assert len(r['final_audits'])==3
assert next(x for x in r['final_audits'] if x['check']=='original_inputs')['input_count']==28
a=json.loads(raw['ARTIFACTS.json'])['files']
item=next(x for x in a if x['name']=='fmt.after.postimages.json.gz')
part=item['parts'];assert len(part)==1 and part[0]['decoded_offset']==0
part_raw=raw['fmt.after.postimages.json.gz.part-001.b64']
assert ident(part_raw)=={k:part[0][k] for k in ('bytes','sha256','git_blob')}
compressed=base64.b64decode(part_raw.strip(),validate=True)
assert ident(compressed)=={k:item[k] for k in ('bytes','sha256','git_blob')}
assert len(compressed)==part[0]['decoded_bytes']==275
assert hashlib.sha256(compressed).hexdigest()==part[0]['decoded_sha256']
uncompressed=gzip.decompress(compressed)
assert uncompressed==raw['fmt.after.postimages.json']
assert ident(uncompressed)=={k:item['raw_'+k] for k in ('bytes','sha256','git_blob')}
t=json.loads(uncompressed)
assert t['format']=='hepta-maintenance-actual-source-transition-v1' and t['stage']=='fmt.after'
assert t['source_commit_unchanged']==r['source_commit'] and t['changes']==[] and t['qualification'] is False
assert t['all_physical_changes_including_untracked_or_ignored_are_recorded'] is True
assert t['base_inventory_sha256']==t['after_inventory_sha256']==r['actual_final_source']['inventory']['sha256']
mraw=Path('/tmp/hepta-36fa-final-qualification-admission-successor-hold-v1/inputs/MAINTENANCE_41E_RESULT.json').read_bytes()
assert ident(mraw)['git_blob']=='b87aed7647ac34e3db0e381110bf685438aee0ee'
m=json.loads(mraw)
assert r['actual_maintenance_result']==ident(mraw)
assert r['actual_maintenance_job']=='1a1d47cebc8-392-41e'
assert r['baseline_inventory']==m['actual_final_source']['inventory']
assert r['baseline_physical_tree']==m['actual_final_source']['postimages']['all_actual_physical_tree']
review={
 'format':'hepta-actual-50f-empty-formatter-independent-review-v1',
 'status':'ACTUAL_EMPTY_FMT_BYTES_AND_CORE_RECORDS_CONSISTENT_NOT_QUALIFICATION',
 'scope':'One independent check of actual original empty formatter transition and its artifact/terminal/result chain. Does not repeat four-file semantic review or reconstruct their actual postimages.',
 'actual_job':n['job_id'],'inputs':pins,
 'actual_maintenance_to_finalfmt_baseline_equal':True,
 'actual_format_command':stage['argv'],'actual_format_timeout_seconds':900,'original_format_returncode':0,
 'empty_transition':{'raw':ident(uncompressed),'gzip':ident(compressed),'part':ident(part_raw),'changes':[],
   'before_inventory_sha256':t['base_inventory_sha256'],'after_inventory_sha256':t['after_inventory_sha256'],
   'all_supported_physical_changes_scope':True},
 'manual_application_path_count':4,'actual_formatter_path_count':0,
 'actual_full_physical_inventory':r['actual_final_source']['inventory'],
 'actual_physical_tree':r['actual_final_source']['postimages']['all_actual_physical_tree'],
 'physical_leaf_count':15243,
 'HEAD_still_precanonical':{'commit':r['source_commit'],'tree':r['source_tree'],'parents':r['parents']},
 'limits':[
  'The zero-formatter-change conclusion comes from complete actual438-byte transition recovered from the original275-byte gzip and exact artifact pins, not from normal0 alone.',
  'RESULT reports three verified audits and28 unchanged inputs; complete original Git/metadata/read-only-command records are being separately retained by the native owner.',
  'Full actual four-path apply/final image recovery and complete inventory graph equivalence remain ordinary/Root work; this review does not claim a second native physical read.',
  'Canonical alignment, source closure and native qualification are not observed here. Original maintenance/fix history and all old failures remain preserved.',
  'This is a new observation window; the preceding schema/migration-spec null cutoff is unchanged.'
 ],'execution':{'new_H_calls':0,'source_or_ref_writes':0,'project_tests_run':0,'qualification':False}}
with (ROOT/'REVIEW.json').open('x') as f:json.dump(review,f,indent=2);f.write('\n')
print(json.dumps(ident((ROOT/'REVIEW.json').read_bytes())))
