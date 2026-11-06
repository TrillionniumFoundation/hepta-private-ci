#!/usr/bin/env python3
"""Offline, read-only bound runner and closed input verification; never imports runners."""
import ast, collections, hashlib, json, re
from pathlib import Path
ROOT=Path('/workspace/scratch/08f5efd48967')
OUT=ROOT/'source52-r29-binding-independent-review'
T=ROOT/'source52-workspace-gates-preparation/native-run-r29-template.py'
B=ROOT/'native-validation-results/r29-bound-input/native-run-r29-bound.py'
F=ROOT/'native-validation-results/r29-bound-input/native-run-r29.py'
A=ROOT/'native-validation-results/r29-bound-input/ACTUAL-BINDINGS.json'
E=ROOT/'native-validation-results/r28-closed-input/evidence'
P='native-source52-project-r28'
def pin(data):
 return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}
def read(p): return json.loads(p.read_bytes())
def values(data):
 tree=ast.parse(data)
 return {n.targets[0].id:(ast.literal_eval(n.value),n) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and isinstance(n.value,(ast.Constant,ast.List,ast.Dict,ast.Tuple))}
def assert_pin(p,pn):
 d=p.read_bytes();got=pin(d)
 for k in ('bytes','sha256','git_blob'):
  if k in pn: assert got[k]==pn[k],(str(p),k,got[k],pn[k])
 return got
def inverse_bind(data,keys):
 text=data.decode();lines=text.splitlines(keepends=True);v=values(data)
 changes=[]
 for k in keys:
  n=v[k][1].value
  start=sum(len(s) for s in lines[:n.lineno-1])+n.col_offset
  end=sum(len(s) for s in lines[:n.end_lineno-1])+n.end_col_offset
  changes.append((start,end,'None'))
 for start,end,replacement in sorted(changes,reverse=True): text=text[:start]+replacement+text[end:]
 return text.encode()
t,b,f=T.read_bytes(),B.read_bytes(),F.read_bytes(); bindings=read(A)
assert pin(t)['sha256']=='4b2d2f5a4f3eb33dfa7f3d744f0d2d322e2e1c1697dfbed45d0047f49dd455b9'
assert pin(b)=={'bytes':82986,'sha256':'ef05d4d3cadadeacc02e3f5d3c3b6e476a683840de60d0a5b5dfff7a4f5ce6ac','git_blob':pin(b)['git_blob']}
assert len(f)==82985 and pin(f)['sha256']=='26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2'
tv,bv,fv=values(t),values(b),values(f)
assert len(bindings)==21
assert set(bindings)=={k for k,(v,n) in tv.items() if v is None}
assert all(tv[k][0] is None and bv[k][0]==v for k,v in bindings.items())
assert inverse_bind(b,bindings)==t
assert b.count(b'FROZEN = False\n')==1
assert f==b.replace(b'FROZEN = False\n',b'FROZEN = True\n',1)
assert fv['COMMAND'][0]==['just','test','--locked','--retries','0']
assert fv['METADATA_COMMAND'][0]==['cargo','metadata','--locked','--no-deps','--format-version','1']
assert fv['EXPECTED_WORKSPACE_MEMBER_COUNT'][0]==193
assert all(fv[k][0] is not None for k in bindings)
pins=bindings['R28_INPUT_PINS'];assert len(pins)==26
checked={name:assert_pin(E/name,pn) for name,pn in pins.items()}
terminal_path=E/bindings['R28_TERMINAL_NAME']
terminal_pin=assert_pin(terminal_path,{'bytes':bindings['R28_TERMINAL_BYTES'],'sha256':bindings['R28_TERMINAL_SHA256']})
terminal=read(terminal_path)
assert terminal['job_id']==bindings['R28_JOB_ID']
assert terminal['state']=='succeeded' and terminal['exit_code']==0
assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
assert terminal['cancelled'] is False and terminal['timed_out'] is False and terminal['automatic_retry'] is False
S=bindings['EXPECTED_TREE'];C=bindings['EXPECTED_COMMIT'];M=bindings['SOURCE_MANIFEST_SHA256']
for name in [P+'-environment.json',P+'-complete.json']:
 o=read(E/name);assert (o['source_tree'],o['source_commit'],o['source_manifest_sha256'])==(S,C,M)
complete=read(E/(P+'-complete.json'));assert complete['source_guards_pass'] is True
assert [complete[k] for k in ('python_exit','strict_exit','tests_exit')]==[0,0,0]
assert complete['workspace_not_started_by_this_runner'] and complete['fix_fmt_executed'] is False
assert complete['source52_bazel_lock_update_executed'] is False
phases={}
last_end=None
for phase in ('python-runner','strict','tests'):
 receipt=read(E/(P+'-'+phase+'-receipt.json'));raw=read(E/(P+'-'+phase+'-raw-process-result.json'))
 assert receipt['exit_code']==receipt['effective_exit_code']==raw['exit_code']==0
 assert receipt['phase_pass'] and receipt['source_guards_pass'] and receipt['issues']==[]
 assert (receipt['source_tree'],receipt['source_commit'],receipt['source_manifest_sha256'])==(S,C,M)
 assert (raw['source_tree'],raw['source_commit'])==(S,C)
 assert raw['command']==receipt['command']
 assert raw['start_unix']==receipt['start_unix'] and raw['end_unix']==receipt['end_unix']
 if last_end is not None: assert receipt['start_unix']>=last_end
 last_end=receipt['end_unix']
 assert_pin(E/receipt['raw_process_result']['path'],receipt['raw_process_result'])
 assert_pin(E/receipt['source_postguard']['path'],receipt['source_postguard'])
 assert pin((E/(P+'-'+phase+'.log')).read_bytes())['sha256']==receipt['log_sha256']
 resource=(E/(P+'-'+phase+'-resources.txt')).read_bytes()
 assert pin(resource)['sha256']==receipt['resources_sha256']
 assert re.search(rb'Exit status:\s*0(?:\r?\n|$)',resource)
 for suffix in ('source-pre-verification','source-post-verification'):
  g=read(E/(P+'-'+phase+'-'+suffix+'.json'))
  assert g['pass'] is True and g['expected_tree']==g['actual_tree']==S
  assert g['source_commit']==C and g['changed_file_count']==195
  assert g['native_head']=='bef6fa7645df9df12b69fda499e97eed25de6c75'
  assert g['unstaged_paths']==g['untracked_paths']==g['file_mismatches']==[]
  assert g['changed_path_set_matches'] is True
  assert g['cargo_lock_sha256']==fv['CARGO_LOCK_SHA256'][0] and g['bazel_lock_sha256']==fv['BAZEL_LOCK_SHA256'][0]
 phases[phase]={'command':receipt['command'],'exit_code':0,'effective_exit_code':0,'elapsed_seconds':receipt['elapsed_seconds'],'receipt':pin((E/(P+'-'+phase+'-receipt.json')).read_bytes()),'log_sha256':receipt['log_sha256']}
assert phases['tests']['command']==['just','test','--locked','-p','codex-cli','-p','codex-exec-server','-p','codex-network-proxy','-p','codex-external-agent-migration','--retries','0']
log=(E/(P+'-tests.log')).read_bytes();rows=[];summary=[];starting=[];offset=0
pattern=re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$')
for ln,line in enumerate(log.splitlines(keepends=True),1):
 txt=line.decode().rstrip('\r\n')
 if re.match(r'^\s*Starting ',txt): starting.append({'line':ln,'byte_offset':offset,'text':txt})
 if re.match(r'^\s*Summary ',txt): summary.append({'line':ln,'byte_offset':offset,'text':txt})
 m=pattern.match(txt)
 if m and not summary: rows.append({'status':m[1],'seconds':float(m[2]),'binary':m[3],'name':m[4],'line':ln,'byte_offset':offset})
 offset+=len(line)
assert len(starting)==len(summary)==1
assert re.search(r'Starting 1564 tests across 49 binaries \(3 tests skipped\)',starting[0]['text'])
assert re.search(r'Summary \[\s*52.852s\] 1564 tests run: 1564 passed, 3 skipped',summary[0]['text'])
assert len(rows)==1564 and len({(r['binary'],r['name']) for r in rows})==1564
assert collections.Counter(r['status'] for r in rows)=={'PASS':1564}
assert rows==read(E/(P+'-tests-test-results.json'))
readback=read(E/(P+'-tests-result-review.json'))
assert readback['baseline_count']==1564 and readback['baseline_missing']==[] and readback['additional_test_ids']==[] and readback['baseline_not_pass']==[]
assert readback['baseline_used_as_filter'] is False and readback['reported_skipped']==3
python_log=(E/(P+'-python-runner.log')).read_bytes()
assert re.search(rb'Ran 32 tests in [0-9.]+s\s+OK(?:\s|$)',python_log)
python_review=read(E/(P+'-python-runner-result-review.json'))
# Exact fixture/source binding uses the same original apply files independently reviewed before.
AP=ROOT/'native-validation-results/source52-apply-closed/evidence'
source_pin=assert_pin(AP/bindings['SOURCE_MANIFEST_NAME'],{'bytes':bindings['SOURCE_MANIFEST_BYTES'],'sha256':M})
apply_pin=assert_pin(AP/bindings['APPLY_COMPLETE_NAME'],{'bytes':bindings['APPLY_COMPLETE_BYTES'],'sha256':bindings['APPLY_COMPLETE_SHA256']})
delta_pin=assert_pin(AP/bindings['DELTA_MANIFEST_NAME'],{'bytes':bindings['DELTA_MANIFEST_BYTES'],'sha256':bindings['DELTA_MANIFEST_SHA256']})
prior_report=ROOT/'source52-r29-independent-static-review/INDEPENDENT-REVIEW.json'
report={
 'schema':'hepta.source52-r29-bound-independent-review.v1','result':'CLEAR','scope':'Offline binding and original closed-input review; no runner, native process or Rust executed.',
 'source_commit':C,'source_tree':S,'expected_changed_count':195,
 'template':pin(t),'bound':pin(b),'final':pin(f),'bindings':pin(A.read_bytes()),
 'literal_binding_count':21,'whole_file_inverse_equals_reviewed_template':True,'final_only_frozen_false_to_true':True,
 'reviewed_inert_template_reference':pin(prior_report.read_bytes()),
 'closed_original_pins':checked,'r28_outer':{'pin':terminal_pin,'job_id':terminal['job_id'],'state':terminal['state'],'exit_code':0,'natural_durable_complete':True},
 'r28_phases':phases,'r28_unique_tests':1564,'r28_counts':{'PASS':1564,'FAIL':0,'TIMEOUT':0},'reported_skipped':3,
 'raw_log_rows_equal_all_original_derived_rows':True,'raw_starting':starting[0],'raw_summary':summary[0],
 'baseline_scope_note':'Original full log independently parsed and all 1564 rows compared. Prior baseline set equality is the pinned original acceptance readback; it is never a test filter.',
 'source_manifest':source_pin,'apply_complete':apply_pin,'delta_manifest':delta_pin,
 'execution_boundary':{'r29_executed_by_reviewer':False,'r29_outcome':None,'workspace_qualification':None,'fix_fmt_executed':False},
 'unchanged_original_workspace_command':fv['COMMAND'][0],'fresh_metadata_command':fv['METADATA_COMMAND'][0],'expected_workspace_members':193,
 'new_issues':[]}
OUT.mkdir(exist_ok=True)
(OUT/'INDEPENDENT-REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'result':'CLEAR','report':pin((OUT/'INDEPENDENT-REVIEW.json').read_bytes()),'final':pin(f),'r28_unique':len(rows)},ensure_ascii=False))

