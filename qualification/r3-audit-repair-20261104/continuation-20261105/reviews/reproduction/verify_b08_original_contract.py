from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import hashlib,json,xml.etree.ElementTree as ET,difflib

ROOT=Path('/workspace/scratch/07dd58cc9630')
D=ROOT/'ci-audit/published-eed4d6-ci-20261105/b08-source-review-v1/review-v1'
def read(p):return json.loads(Path(p).read_text())
def pin(p):
 b=Path(p).read_bytes()
 return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
         'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def verify(p):
 actual=pin(p['path'])
 for k in ['bytes','sha256','git_blob']:assert actual[k]==p[k],(p['path'],k)
 return actual
def tree_hash(leaves):
 root={}
 for path,r in leaves.items():
  parts=path.split('/');d=root
  for s in parts[:-1]:d=d.setdefault(s,{})
  assert parts[-1] not in d
  d[parts[-1]]=(r['mode'],r['sha'])
 def digest(d):
  rows=[]
  for n,v in d.items():
   isdir=isinstance(v,dict);mode,sha=('40000',digest(v)) if isdir else v
   rows.append((n.encode()+ (b'/' if isdir else b''),mode.encode()+b' '+n.encode()+b'\0'+bytes.fromhex(sha)))
  b=b''.join(x[1] for x in sorted(rows))
  return hashlib.sha1(b'tree '+str(len(b)).encode()+b'\0'+b).hexdigest()
 return digest(root)

review=read(D/'independent-review.json');ev=read(D/'four-case-evidence.json');bridge=read(D/'source-leaf-bridge.json')
assert review['recommendation']=='CLOSED_SCOPED_ELIGIBLE_FOR_ROOT_DECISION'
ledger=read(ROOT/'hepta-audit-fifth/v7-deliverables/continuation-blocker-progress-v5.json')
original=next(r for r in ledger['items'] if r['id']=='B08')['original_exit_condition_zh']
assert original==review['original_exit']['frozen_ledger_exit_condition_zh']
assert set(review['exact_four_names'])=={r['test'] for r in ev['cases']}
for r in ev['original_inputs']:verify(r)
base=read(ROOT/'hepta-audit-fifth/inputs/product-5b-full-leaf-manifest.json')
assert not base['truncated']
maps={'5b':{x['path']:x for x in base['leaves']}}
maps['e78']={k:dict(v) for k,v in maps['5b'].items()}
for r in read(ROOT/'hepta-audit-fifth/core-musl-initial-source-binding.json')['exact_changes']:
 assert maps['e78'][r['path']]['sha']==r['pre']
 maps['e78'][r['path']].update(sha=r['post'],mode=r['mode'])
maps['eed']={k:dict(v) for k,v in maps['5b'].items()}
for r in read(ROOT/'hepta-audit-fifth/inputs/integrated-14-path-candidate-v2.json')['changes']:
 assert maps['eed'].get(r['path'],{}).get('sha')==r['before_sha']
 maps['eed'][r['path']]={'path':r['path'],'mode':r['mode'],'type':r['type'],'sha':r['sha']}
tree_results={}
for label,m in maps.items():
 actual=tree_hash(m);expected=bridge['whole_trees_independently_recomputed'][label]
 assert actual==expected['tree'] and len(m)==expected['leaves']
 tree_results[label]={'tree':actual,'leaves':len(m),'root_recomputed':True}

sources=[];changed=[]
for r in bridge['source_files']:
 current=verify(r['current_full_source']);before=verify(r['cabc_full_source']);path=r['logical_source_path']
 for m in maps.values():assert m[path]['sha']==current['git_blob'] and m[path]['mode']==r['mode']
 a=Path(before['path']).read_bytes();b=Path(current['path']).read_bytes()
 assert (a==b)==r['cabc_equals_5b']
 if a!=b:
  changed.append(path)
  diff=list(difflib.unified_diff(a.decode().splitlines(),b.decode().splitlines(),lineterm=''))
  assert sum(x.startswith('+') and not x.startswith('+++') for x in diff)==5
  assert not any(x.startswith('-') and not x.startswith('---') for x in diff)
  assert [x[1:] for x in diff if x.startswith('+') and not x.startswith('+++')]==[
   '', '#[path = "responses_websocket_concurrent.rs"]', 'mod websocket_concurrent;', '',
   'pub use websocket_concurrent::start_concurrent_websocket_server;']
 sources.append({'path':path,'current':current,'cabc':before,'same_across_5b_e78_eed':True,'cabc_equal':a==b})
assert len(sources)==15 and changed==['codex-rs/core/tests/common/responses.rs']

rawmeta=ev['cases'][0]['full_original_raw'];xmlmeta=ev['cases'][0]['complete_original_junit']
verify(rawmeta);verify(xmlmeta)
raw=Path(rawmeta['path']).read_bytes();xml=ET.fromstring(Path(xmlmeta['path']).read_bytes())
actual_cases=[]
for r in ev['cases']:
 block=Path(r['raw_block']['path']).read_bytes();verify(r['raw_block'])
 assert raw[r['raw_byte_start']:r['raw_byte_end_exclusive']]==block
 text=block.decode();name=r['test'];binary=r['binary']
 assert text.count('running 1 test')==1
 assert text.count('test '+name+' ... ok')==1
 assert text.count('test result: ok. 1 passed; 0 failed; 0 ignored;')==1
 assert r['linux_rog_e78_actual_scope']['observed_early_returns']==[]
 assert not any(s in text.lower() for s in ['skipping test','network disabled','test result: failed'])
 selected=[c for c in xml.iter('testcase') if c.get('name')==name and c.get('classname')==binary]
 assert len(selected)==1 and selected[0].attrib==r['junit_attributes']
 assert not any(c.tag in {'failure','error','skipped','rerunFailure'} for c in selected[0])
 assert ET.tostring(selected[0],encoding='unicode')==r['junit_xml_fragment']
 actual_cases.append({'binary':binary,'name':name,'result':'PASS','seconds':selected[0].get('time'),
                      'raw_block':pin(r['raw_block']['path']),'raw_offsets':[r['raw_byte_start'],r['raw_byte_end_exclusive']],
                      'one_exact_raw_and_JUnit_result':True,'observed_early_return':False})
assert len(actual_cases)==4
guards=[read(x['path']) for x in ev['original_inputs'] if 'source-guard' in x['path']]
assert len(guards)==2
for key in ['source_tree','leaf_count','ordinary_head','ordinary_index','locks','untracked_relative_to_ordinary_index','unexpected_untracked','tool_pins_equal','external_build_inputs']:
 assert guards[0][key]==guards[1][key],key
assert guards[0]['source_tree']==tree_results['e78']['tree'] and guards[0]['tool_pins_equal']
assert ev['command']['retries']==0 and ev['overall_original_scope']=={'exit_code':100,'selected':3967,'passed':3962,'failed':5,'retries':0,'must_not_be_relabelled_suite_pass':True}
assert guards[0]['ordinary_head']=='cabcb40d36e116beaa65750e1f674c52035da785'

result={'schema':'hepta-b08-original-contract-root-closure-v1','verified_utc':datetime.now(timezone.utc).isoformat(),
 'decision':'CLOSED_SCOPED','blocker':'B08','original_exit_condition_zh':original,
 'scope':'Four original GNU e78 cases, unchanged relevant source through5b/eed; supplemental Windows three units retain their own exact source scopes. No eed GNU or full-workspace execution is inferred.',
 'independent_review':pin(D/'independent-review.json'),'source_bridge':pin(D/'source-leaf-bridge.json'),
 'four_case_review':pin(D/'four-case-evidence.json'),'previous_complete_ROG_root_review':pin(ROOT/'hepta-audit-fifth/inputs/rog-complete29-root-verification-v2.json'),
 'original_command':ev['command'],'overall_scope_still_failed':ev['overall_original_scope'],
 'full_raw':rawmeta,'full_junit':xmlmeta,'cases':actual_cases,'source_guards_before_after_equal':True,
 'ordinary_HEAD_cabc_not_native_source_tree':guards[0]['ordinary_head'],'trees':tree_results,'sources':sources,
 'semantic_review':{'root_read_complete_original_case_bodies':True,
 'actual_prompt':'Production session turn attaches pending calls before build_prompt and passes the real prompt into the sampling request.',
 'observer':'Read-only getter reads the production retained map; it neither consumes pending calls nor creates metadata.',
 'integration':'Original namespace, exact wire and durable output tuples, escaped-byte overflow marker, historical replay and direct exec calls remain exact; actual flush_rollout/load_history is used.',
 'existing_negative_semantics':'Original passing cases retain None-before-attach, overflow, exact replay, compaction clearing, 512-history byte bound and omission accounting. No new mutation-negative execution is claimed.',
 'wire':'All4 endpoint/name ×2 feature ×2 format combinations preserve the original exact resolved-endpoint policy. Nonofficial and ChatGPT Codex strip; first-party OpenAI keeps, including a custom friendly name.',
 'persistence':'Existing relevant production and rollout/protocol source are byte-identical to frozen cabc. Getter is read-only; captured nonofficial wire remains free of private fields. Only5 unrelated test helper module/export lines differ.'},
 'limits':['Q02 four-Unix artifact collection is not an extra original B08 exit condition.','The current complete product and all required-platform matrix remain B15 OPEN.','Original project exit100, five other failures,25 other early returns, resource refusal and unknown B16 driver remain.','No Windows namespace run is invented; original module excludes Windows.','Binary identities are original native evidence, not a claim to reread old binary bytes in this root verifier.'],
 'ledger_transition':{'before':{'CLOSED_SCOPED':10,'OPEN':12,'SCIENTIFIC_HOLD':1},'after':{'CLOSED_SCOPED':11,'OPEN':11,'SCIENTIFIC_HOLD':1}},
 'root_verifier_correction':'Initial generic module/export-only assertion also rejected the actual two blank lines and path attribute. It was replaced with an exact five-line diff comparison; no original evidence or test was changed.',
 'tests_rerun':False,'all_blockers_closed':False}
out=ROOT/'hepta-audit-fifth/inputs/b08-original-contract-root-closure-v1.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'result':pin(out),'decision':result['decision'],'counts':result['ledger_transition']['after']},ensure_ascii=False))
