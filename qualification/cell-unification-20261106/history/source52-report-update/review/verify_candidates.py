#!/usr/bin/env python3
"""Read-only semantic, citation and artifact-pin check of source52 report candidates."""
import gzip,hashlib,json,re
from pathlib import Path,PurePosixPath
B=Path('/workspace/scratch/08f5efd48967');P=B/'source52-report-update-preparation';N=P/'new-files';R=B/'hepta-cell/qualification/cell-unification-20261106'
def pin(d):return {'bytes':len(d),'sha256':hashlib.sha256(d).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(d)).encode()+b'\0'+d).hexdigest()}
def load(p):return json.loads(p.read_bytes())
S=load(P/'STATUS.candidate.json');I=load(P/'SOURCE_IDENTITY.candidate.json');oldS=load(P/'references/STATUS.json');oldI=load(P/'references/SOURCE_IDENTITY.json')
M=(P/'README.candidate.md').read_text();oldM=(P/'references/README.md').read_text()
C='1e0910becc37383e6d17ecf861ea844fd07d8862';T='211f15baff19095e8c98bcea2b0ed99ca2270ade'
leaf_map=load(B/'publication-recovery-prep/checkpoint5-actual-leaf-map.json')['files']
assert len(leaf_map)==1843
prefix='qualification/cell-unification-20261106/'
assert S['current_source']['commit']==I['current_source_commit']==C and S['current_source']['tree']==I['current_source_tree']==T
assert S['current_source']['scope']['changed_source_paths']==195 and S['current_source']['scope']['rust_paths']==181
assert S['current_source']['scope']['owner_package_count']==26 and S['current_source']['scope']['ci_package_selector_count']==27
for k in ['overall','taxonomy','source_inputs','implementation','science','historical_assets','source_compatibility','upstream_ci_history']:assert S[k]==oldS[k],k
assert I['scientific_reference_source']==oldI['scientific_reference_source']
assert S['overall']['scientific_disposition']==I['scientific_disposition']=='HOLD'
assert S['overall']['authority']==I['authority']=='DENY_ALL'
for a,z in [(1,2),(4,5)]:
 assert M[M.index('## '+str(a)+'. '):M.index('## '+str(z)+'. ')]==oldM[oldM.index('## '+str(a)+'. '):oldM.index('## '+str(z)+'. ')]
g=S['validation']['gates']
assert g['r26']['source_stage']==51 and g['r26']['tests_raw_exit_code']==g['r26']['original_outer_exit_code']==100
assert g['r26']['counts']=={'unique_test_results':1564,'passed':1562,'failed':2,'timed_out':0,'reported_skipped':3}
assert g['r28']['source_stage']==52 and g['r28']['tests_raw_exit_code']==g['r28']['tests_effective_exit_code']==g['r28']['original_outer_exit_code']==0
assert g['r28']['counts']=={'unique_test_results':1564,'passed':1564,'failed':0,'timed_out':0,'reported_skipped':3}
assert all(x['status']=='PASS' for x in g['r28']['old_r26_two_failures_now_pass'])
assert len(g['r28']['old_r26_two_failures_now_pass'])==2
assert g['r29']['source_stage']==52 and g['r29']['workspace_command_started'] is True
assert g['r29']['test_execution_started'] is None and g['r29']['original_outer_exit_code'] is None
assert all(v is None for v in g['r29']['counts'].values())
assert g['r29']['metadata_original_exit_code']==0 and g['r29']['workspace_members']==g['r29']['workspace_default_members']==193
assert S['overall']['default_workspace_gate_pass'] is False
assert S['final_fix_fmt']['fix_executed'] is S['final_fix_fmt']['fmt_executed'] is False
assert I['final_fix_executed'] is I['final_fmt_executed'] is I['branch_created'] is I['pull_request_created'] is False
assert len(I['created_source_commits'])==I['created_source_commit_count']==52
observed=I['creation_records_exact_from_publication_ledger']
assert observed['created_blob_path_count_at_observation']==185 and observed['artifact_checkpoint_count_at_observation']==5
for n in ['README.md','STATUS.json','SOURCE_IDENTITY.json']:assert (R/n).read_bytes()==(P/'references'/n).read_bytes()
issues=[];checks=[];external=set()
def locate(path):
 pure=PurePosixPath(path)
 if pure.is_absolute() or '..' in pure.parts:raise ValueError(path)
 if path in ['README.md','STATUS.json','SOURCE_IDENTITY.json']:
  return P/({'README.md':'README.candidate.md','STATUS.json':'STATUS.candidate.json','SOURCE_IDENTITY.json':'SOURCE_IDENTITY.candidate.json'}[path]),None
 if (N/path).is_file():return N/path,None
 if (R/path).is_file():return R/path,None
 return None,leaf_map.get(prefix+path)
def check(path,obj=None,where=''):
 if path.startswith(('https://','http://')):
  external.add(path);return
 if '#' in path:path=path.split('#',1)[0]
 if not path:return
 local,blob=locate(path)
 if local:
  actual=pin(local.read_bytes())
  if obj:
   for k in ['bytes','sha256','git_blob']:
    if k in obj and actual[k]!=obj[k]:issues.append({'where':where,'path':path,'field':k,'wanted':obj[k],'actual':actual[k]})
   if obj.get('compression')=='gzip' and 'original_uncompressed' in obj:
    up=pin(gzip.decompress(local.read_bytes()))
    assert up==obj['original_uncompressed'],(path,up,obj['original_uncompressed'])
  checks.append({'where':where,'path':path,'check':'LOCAL_BYTES','pin':actual})
 elif blob:
  if obj and 'git_blob' in obj and obj['git_blob']!=blob:issues.append({'where':where,'path':path,'wanted_blob':obj['git_blob'],'actual_blob':blob})
  checks.append({'where':where,'path':path,'check':'IMMUTABLE_CHECKPOINT5_BLOB_EXISTENCE_ONLY','git_blob':blob,'raw_sha256_not_recomputed':True})
 else:issues.append({'where':where,'path':path,'error':'missing from candidate/local/immutable checkpoint5 map'})
relative_prefix=('native-evidence/','history/','study-evidence/')
def walk(o,where):
 if isinstance(o,dict):
  if isinstance(o.get('path'),str) and (o['path'].startswith(relative_prefix) or o['path'] in ['STATUS.json','SOURCE_IDENTITY.json','README.md','MATURITY.zh-CN.md','HISTORICAL_ASSETS.json']):check(o['path'],o,where)
  for k,v in o.items():
   if k!='path' and isinstance(v,str) and (v.startswith(relative_prefix) or v in ['MATURITY.zh-CN.md','HISTORICAL_ASSETS.json']):check(v,None,where+'.'+k)
   elif isinstance(v,(dict,list)):walk(v,where+'.'+k)
 elif isinstance(o,list):
  for j,v in enumerate(o):walk(v,where+'['+str(j)+']')
walk(S,'STATUS');walk(I,'SOURCE_IDENTITY')
definitions=dict(re.findall(r'^\[([^\]]+)\]:\s*(\S+)\s*$',M,re.M))
refs=re.findall(r'\[[^\]]+\]\[([^\]]+)\]',M)
for ref in set(refs):
 if ref not in definitions:issues.append({'where':'README','undefined_reference':ref})
 else:check(definitions[ref],where='README:'+ref)
report={'schema':'hepta.source52-three-report-candidate-audit.v1','state':'CANDIDATE_NOT_ADOPTED',
 'source_commit':C,'source_tree':T,'current_main_reports_unchanged':True,'maturity_and_science_sections_byte_identical':True,
 'scientific_contract_json_blocks_identical':True,'r28_original_complete_gate_pass_preserves_r26_failure_history':True,
 'r29_start_only_no_nextest_or_terminal_count_claim':True,'no_fix_fmt_or_ref_publication_claim':True,
 'relative_reference_checks':len(checks),'checks':checks,'external_urls':sorted(external),'issues':issues,
 'old_remote_evidence_boundary':'Historical paths in the exact checkpoint5 map are checked by stored Git blob identity only when local raw bytes are absent; this audit does not claim to re-read those raw files.',
 'candidate_outputs':{n:pin((P/n).read_bytes()) for n in ['README.candidate.md','STATUS.candidate.json','SOURCE_IDENTITY.candidate.json']}}
(P/'CANDIDATE-AUDIT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'issues':issues,'checks':len(checks),'audit':pin((P/'CANDIDATE-AUDIT.json').read_bytes())},ensure_ascii=False))
assert not issues

