#!/usr/bin/env python3
"""Offline verification only: exact fixed APIs, complete ZIPs, source, test attempts and compact projection."""
from pathlib import Path, PurePosixPath
import collections, hashlib, json, re, stat, sys, xml.etree.ElementTree as ET, zipfile
ROOT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
HEAD='67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
TREE='3982ba56dc5a3f1da0c1de7ea57992f88125c359'
MERGE='b7a57dbb61b00e51c05da9cf5c4bc95b365d85ae'
IDS=[13475811429,13475001412,13475231392,13474964431,13474454125]
JOB_IDS=[127679861660,127679861699,127679861775,127679861740,127679861749]
def ident(b):
 return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def load(p):return json.loads((ROOT/p).read_bytes())
def api(p):return json.loads(load(p)['structuredContent']['content'])
def states(xs):return dict(sorted(collections.Counter(x['conclusion'] or x['status'] for x in xs).items()))
runs=api('original/main_runs.tool-return.original.json')
assert runs['total_count']==len(runs['workflow_runs'])==19
jobs=[];run_counts=[]
for run in runs['workflow_runs']:
 assert run['head_sha']==HEAD
 path='original/main_blocking_jobs.tool-return.original.json' if run['id']==42123581385 else f"original/run-{run['id']}-jobs.tool-return.original.json"
 d=api(path);assert len(d['jobs'])==d['total_count']
 assert all(j['run_id']==run['id'] and j['head_sha']==HEAD for j in d['jobs'])
 jobs.extend(d['jobs']);run_counts.append({'run_id':run['id'],'jobs':len(d['jobs'])})
assert len(jobs)==len({x['id'] for x in jobs})==92
assert states(jobs)=={'success':67,'failure':8,'cancelled':10,'skipped':6,'queued':1}
assert states(runs['workflow_runs'])=={'success':11,'failure':5,'skipped':2,'queued':1}
assert {j['id'] for j in jobs if j['conclusion']=='failure'}==set(JOB_IDS+[127679861307,127679861687,127691446306])
api_summary={'run_count':19,'run_states':states(runs['workflow_runs']),'job_count':92,'job_states':states(jobs),'per_run_job_count':run_counts,
 'job_failures':[{'id':j['id'],'name':j['name'],'steps':[s['name'] for s in j['steps'] if s['conclusion']=='failure']} for j in jobs if j['conclusion']=='failure'],
 'window':{'root_list_and_blocking_jobs':load('original/API-CUT.json'),'other18_jobs':load('OTHER-JOBS-READ-WINDOW.json')},
 'non_atomic':True,'summary_failure_job_id':127691446306,'distinct_failed_execution_jobs':7}
logs=[]
for job in JOB_IDS:
 p=f'original/job-{job}.decoded.original.log'
 b=(ROOT/p).read_bytes();original=load(f'original/job-{job}.tool-return.original.json')
 assert not original.get('isError')
 assert b==original['structuredContent']['content'].encode('utf-8')
 t=b.decode('utf-8')
 exits=re.findall(r'##\[error\]Process completed with exit code (\d+)\.',t)
 assert exits==(['1'] if job==127679861740 else ['3'])
 assert MERGE in t
 logs.append({'job_id':job,'path':p,**ident(b),'terminal_exit_codes':exits,'newline_preserved':True,'scope':'Complete decoded UTF-8 bytes delivered by GitHub log tool; no HTTP wire-byte claim.'})
tree=load('borrowed/authority/main67-full-tree.json')
assert tree['sha']==TREE and tree['truncated'] is False
children=collections.defaultdict(list);expected={x['path']:x for x in tree['tree']}
for item in tree['tree']:
 parent,_,name=item['path'].rpartition('/')
 children[parent].append((name,item['mode'],item['type'],item['sha']))
count=0
def merkle(path):
 global count
 entries=[]
 for name,mode,kind,sha in sorted(children[path],key=lambda x:(x[0]+('/' if x[2]=='tree' else '')).encode()):
  if kind=='tree':
   got=merkle((path+'/' if path else '')+name);assert got==sha;mode='40000'
  entries.append(mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha))
 body=b''.join(entries);count+=1
 return hashlib.sha1(b'tree '+str(len(body)).encode()+b'\0'+body).hexdigest()
assert merkle('')==TREE
leaves=sum(x['type']!='tree' for x in tree['tree'])
assert leaves==10582 and count==1571
merge=load('borrowed/original/actual-executed-merge-commit.original.json')
assert merge['sha']==MERGE and merge['tree']['sha']==TREE
assert [p['sha'] for p in merge['parents']]==['63652be658ebed8d3052eb789b951793384fd5e4',HEAD]
for row in load('SOURCE-IDENTITIES.json'):
 b=(ROOT/'source'/row['path']).read_bytes()
 assert all(ident(b)[k]==row[k] for k in ['bytes','git_blob','sha256'])
 assert expected[row['path']]['sha']==row['git_blob']
 if 'full_GET_original' in row:assert load(row['full_GET_original'])['structuredContent']['content'].encode('utf-8')==b
artlist=api('original/run-artifacts.tool-return.original.json')
assert len(artlist['artifacts'])==artlist['total_count']==14
artlookup={a['id']:a for a in artlist['artifacts']}
artifacts=[];attempts=[];mismatches=[]
for aid in IDS:
 info=artlookup[aid];zpath=ROOT/f'artifacts/artifact-{aid}.original.zip';zb=zpath.read_bytes()
 assert ident(zb)['bytes']==info['size_in_bytes']
 assert 'sha256:'+ident(zb)['sha256']==info['digest']
 assert info['workflow_run']['head_sha']==HEAD and info['workflow_run']['id']==42123581385
 unpack=ROOT/f'artifacts/artifact-{aid}'
 with zipfile.ZipFile(zpath) as z:
  assert z.testzip() is None
  assert len(z.namelist())==len(set(z.namelist()))
  names=[]
  for zi in z.infolist():
   p=PurePosixPath(zi.filename);assert not p.is_absolute() and '..' not in p.parts and not stat.S_ISLNK(zi.external_attr>>16)
   if zi.is_dir():continue
   assert (unpack/zi.filename).read_bytes()==z.read(zi);names.append(zi.filename)
 manifests=[];failed_manifest=None
 for path in sorted(unpack.rglob('manifest.json')):
  md=json.loads(path.read_bytes())
  assert md['source']=={'commit':MERGE,'tree':TREE,'tracked_worktree_dirty':False}
  assert md['complete_for_selected_targets'] is True and md['errors']==[]
  for f in md['files']:
   b=(path.parent/f['archive_relative_path']).read_bytes()
   assert len(b)==f['bytes'] and hashlib.sha256(b).hexdigest()==f['sha256']
  manifests.append({'path':str(path.relative_to(unpack)),'files':len(md['files']),'targets':md['selected_targets']})
  if 'failed-test-logs' in path.parts:failed_manifest=(path,md)
 spawns=load(f'derived/{aid}/all-test-runners.json')
 summary=load(f'derived/{aid}/compact-summary.json')
 assert summary['test_runner_count']==len(spawns)
 compact,=unpack.glob('*.zst')
 assert summary['compressed_sha256']==hashlib.sha256(compact.read_bytes()).hexdigest()
 if failed_manifest:
  mp,md=failed_manifest
  selected=[s for s in spawns if s['target_label'] in md['selected_targets']]
  groups=collections.defaultdict(lambda:{'actual':[],'xml':[]})
  for s in selected:
   env={e['name']:e['value'] for e in s['env_vars']};group=(s['target_label'],int(env.get('TEST_SHARD_INDEX','0')),int(env.get('TEST_TOTAL_SHARDS','0')))
   command=s['args'][0].replace('\\','/').rsplit('/',1)[-1]
   assert command in ['tw.exe','test-setup.sh','xml.exe','generate-xml.sh'],command
   kind='xml' if command in ['xml.exe','generate-xml.sh'] else 'actual'
   assert s['cache_hit'] is False and s['runner'] in ['local','darwin-sandbox']
   groups[group][kind].append(s)
  for (target,shard,shards),g in sorted(groups.items()):
   assert len(g['actual'])==len(g['xml'])
   for idx,(native,xml) in enumerate(zip(g['actual'],g['xml']),1):
    assert native['sequence']<xml['sequence'] and int(xml['args'][4])==native['exit_code']
    assert xml['exit_code']==0 and xml['timeout_millis']==0
    assert native['timeout_millis']==(900000 if target=='//codex-rs/core:core-unit-tests' else 300000)
    tail=f'shard_{shard+1}_of_{shards}/' if shards else ''
    tail+=f'test_attempts/attempt_{idx}.log' if idx<len(g['actual']) else 'test.log'
    candidates=[f for f in md['files'] if f['target']==target and f['testlogs_relative_path'].endswith('/'+tail)]
    assert len(candidates)==1,(target,tail,candidates)
    f=candidates[0];log=(mp.parent/f['archive_relative_path']).read_bytes()
    xpath=mp.parent/f['archive_relative_path'].replace('.log','.xml');xb=xpath.read_bytes();xr=ET.fromstring(xb)
    cases=xr.findall('.//testcase');assert len(cases)==1
    failed_wrapper=any(c.tag in ('failure','error') for c in cases[0])
    assert failed_wrapper==(native['exit_code']!=0)
    outs=[o for o in xml['outputs'] if o.get('path','').endswith('/test.xml')]
    assert len(outs)==1
    match=outs[0]['digest']['hash']==hashlib.sha256(xb).hexdigest() and outs[0]['digest']['size_bytes']==len(xb)
    item={'artifact_id':aid,'target':target,'shard_one_based':shard+1 if shards else None,'total_shards':shards,'attempt':idx,'attempts_for_shard':len(g['actual']),
     'native_sequence':native['sequence'],'native_runner':native['runner'],'native_cache_hit':native['cache_hit'],'native_exit_code':native['exit_code'],'native_timeout_millis':native['timeout_millis'],
     'xml_sequence':xml['sequence'],'xml_exit_code':xml['exit_code'],'xml_wrapper_testcase_count':len(cases),'xml_actual_digest_matches_compact':match,
     'log_path':str((mp.parent/f['archive_relative_path']).relative_to(ROOT)), 'log':ident(log),'xml_path':str(xpath.relative_to(ROOT)),'xml':ident(xb),
     'literal_libtest_summaries':re.findall(r'^test result:.*$',log.decode('utf-8'),re.M)}
    if not match:
     first=mp.parent/f['archive_relative_path'].rsplit('/',1)[0]/'test_attempts/attempt_1.xml'
     assert aid==13475811429 and target=='//codex-rs/core:core-unit-tests' and shard==0 and idx==2
     assert outs[0]['entry_id']==[o for o in g['xml'][0]['outputs'] if o.get('path','').endswith('/test.xml')][0]['entry_id']
     assert outs[0]['digest']['hash']==hashlib.sha256(first.read_bytes()).hexdigest()
     item['mismatch_scope']='Second XML output reuses first XML entry_id/digest; first digest matches original attempt_1.xml, not final test.xml. ZIP/collector still preserve final XML.'
     mismatches.append(item)
    attempts.append(item)
 artifacts.append({'artifact_id':aid,'zip':ident(zb),'members':len(names),'collector_manifests':manifests,'compact':summary})
assert len(attempts)==14 and len(mismatches)==1
clippy=load('derived/13474964431/failed-nontest-spawns.json')
assert len(clippy)==3 and all(s['mnemonic']=='Clippy' and s['runner']=='remote' and not s['cache_hit'] and s['exit_code']==1 for s in clippy)
assert {s['target_label'] for s in clippy}=={'//codex-rs/arg0:test_arg0_preflight','//codex-rs/arg0:test_arg0_preflight-bin-unit-tests-bin','//codex-rs/arg0:arg0-unit-tests-bin'}
pty=next(a for a in attempts if a['target']=='//codex-rs/utils/pty:pty-unit-tests')
ptytext=(ROOT/pty['log_path']).read_bytes().decode('utf-8')
for token in ['30 passed; 1 failed; 0 ignored','wait_elapsed=2.228741523s','read_calls=6549','read_bytes=3358720','discarded_bytes=3358720','last_read=errno(35)','queued_bytes=Ok(0)','child_phase=Ok("python_started")']:assert token in ptytext
w=next(a for a in attempts if a['artifact_id']==13475231392);wt=(ROOT/w['log_path']).read_bytes().decode('utf-8')
assert '89 passed; 3 failed; 0 ignored' in wt and '50 passed; 10 failed; 2 ignored' in wt
assert wt.count('legacy Windows sandbox process test lock poisoned: PoisonError { .. }')==6
result={'schema':'hepta-main67-current-cut-and-five-failures-offline-v1','scope':'Original fixed 67 source; no new CI/native execution. Full APIs and five original job logs, five original ZIPs; selected failed-target attempt custody only.',
 'source':{'head':HEAD,'actual_checkout':MERGE,'tree':TREE,'leaves':leaves,'directory_nodes_including_root':count,'source_files':len(load('SOURCE-IDENTITIES.json'))},
 'apis':api_summary,'logs':logs,'artifacts':artifacts,'actual_failed_target_test_launches_and_retry_launches':len(attempts),'auxiliary_xml_generators':len(attempts),
 'attempts':attempts,'compact_XML_mismatch_count':len(mismatches),'compact_XML_mismatches':mismatches,
 'clippy_failed_actions':[{'sequence':s['sequence'],'target':s['target_label'],'runner':s['runner'],'cache_hit':s['cache_hit'],'exit_code':s['exit_code']} for s in clippy],
 'limits':['92 jobs are one bounded non-atomic 19-run snapshot; API states are not case qualification.',
 'The Windows summary job is not an eighth independent failure cause. Seven execution jobs failed; five new original logs collected here, prior cargo-deny/Win4 evidence remains separate.',
 'An original first failing Core attempt and later successful retry both remain; do not describe retries as no failures.',
 'One Intel Core final XML compact digest mismatch is explicit; official ZIP and collector manifest bind its actual bytes independently.',
 'Win2 main67 original sandbox bat two libtest segments sum to139P13F2I, including6 lock-poison failures; this is not native13 diagnostic source/result.',
 'Stored XML has one wrapper testcase per launch, not one XML per Rust definition. Exact literal libtest summaries are retained separately.',
 'Selected target archive completeness is not completeness of every target in //..., and cached passed targets cannot become fresh native acceptance.',
 'No assertions, retry policy, time budgets, production source, ref, required gate, or CI dispatch were changed by this evidence work.']}
print(json.dumps(result,ensure_ascii=False,indent=2))

