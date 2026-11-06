import json,pathlib,hashlib,tarfile,stat,re,collections,io
root=pathlib.Path('/workspace/scratch/08f5efd48967')
p=root/'native-validation-results/checkpoint-r14'
sha=lambda b:hashlib.sha256(b).hexdigest()
blob=lambda b:hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def ident(path):
 b=path.read_bytes()
 return {'path':str(path.relative_to(root)),'bytes':len(b),'sha256':sha(b)}
archive=p/'checkpoint-r14-closed.tar.gz'
ab=archive.read_bytes()
assert len(ab)==984873 and sha(ab)=='e5449ef5dd31e08e4daa4a0ae85c3c6e818859a90c5f94235452e4e26a13229a'
index=json.loads((p/'INDEX.json').read_bytes())
pins={x['path']:x for x in index['files']}
assert len(pins)==len(index['files'])==178
with tarfile.open(fileobj=io.BytesIO(ab),mode='r:gz') as t:
 members=t.getmembers()
 assert len(members)==len({m.name for m in members})==179
 assert {m.name for m in members}==set(pins)|{'INDEX.json'}
 for m in members:
  assert m.isfile() and not m.issym() and not m.islnk()
  n=pathlib.PurePosixPath(m.name)
  assert not n.is_absolute() and '..' not in n.parts
  b=t.extractfile(m).read()
  assert b==(p/m.name).read_bytes()
  if m.name=='INDEX.json':continue
  pin=pins[m.name]
  assert len(b)==pin['bytes'] and sha(b)==pin['sha256']
  if 'git_blob' in pin: assert blob(b)==pin['git_blob']
  assert m.mode==int(pin['mode'],8)
  assert stat.S_IMODE((p/m.name).stat().st_mode)==int(pin['mode'],8)
assert sum(x.startswith('source/')for x in pins)==163
assert sum(x.startswith('evidence/')for x in pins)==15
source=json.loads((p/'evidence/native-candidate-r14-source.json').read_bytes())
tree=source['source_tree'];commit=source['source_commit']
assert tree=='d3d2313b838422818bf9448ce5a1b86d89abdf69'
assert commit=='b44d4ca4aa0ef9f894eff29e9975938e066a82f5'
changed={x['path']:x for x in source['changed_files']}
assert len(changed)==163
for path,x in changed.items():
 y=pins['source/'+path]
 assert all(x[k]==y[k]for k in ['bytes','sha256','git_blob'])
 assert int(x['mode'],8)&0o7777==int(y['mode'],8)
# Independently rebuild Git trees from pinned base immediate children and deltas.
git_input=json.loads((p/'INDEPENDENT-SOURCE-TREE-INPUT.json').read_bytes())
assert not git_input['base_listing_truncated'] and git_input['base_recursive_entry_count']==12259
base={e['path']:e for e in git_input['base_entries']}
children=collections.defaultdict(dict)
for e in base.values():
 parent,_,name=e['path'].rpartition('/')
 children[parent][name]={k:e[k]for k in ['mode','type','sha']}
def tree_digest(entries):
 def key(item):return item[0].encode()+(b'/' if item[1]['type']=='tree' else b'')
 raw=b''
 for name,e in sorted(entries.items(),key=key):
  mode='40000' if e['type']=='tree' else e['mode'].lstrip('0')
  raw+=mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(e['sha'])
 return hashlib.sha1(b'tree '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
assert tree_digest(children[''])==git_input['base_tree']=='ce997fd958b8073d99b1e5bc302b7a0188fb4c3b'
for e in git_input['existing_directory_pins']:
 assert tree_digest(children[e['path']])==e['sha'],e['path']
for path,x in changed.items():
 parent,_,name=path.rpartition('/')
 children[parent][name]={'mode':x['mode'],'type':'blob','sha':x['git_blob']}
computed={}
for directory in sorted(git_input['ancestors'],key=lambda x:(x.count('/'),len(x)),reverse=True):
 computed[directory]=tree_digest(children[directory])
 if directory:
  parent,_,name=directory.rpartition('/')
  children[parent][name]={'mode':'040000','type':'tree','sha':computed[directory]}
assert computed['']==tree
rt=json.loads((p/'ROOT-SOURCE-ROUNDTRIP-INPUT.json').read_bytes())
assert rt['base_tree']==git_input['base_tree'] and rt['expected_tree']==tree
assert {x['path']:(x['mode'],x['sha'])for x in rt['tree_elements']}=={path:(x['mode'],x['git_blob'])for path,x in changed.items()}
receipts={};log_data={}
for phase,expected_exit in [('strict',0),('tests',100)]:
 receipt_path=p/'evidence'/f'native-core-r14-{phase}-receipt.json'
 receipt=json.loads(receipt_path.read_bytes())
 log_path=p/'evidence'/f'native-core-r14-{phase}.log'
 resource_path=p/'evidence'/f'native-core-r14-{phase}-resources.txt'
 log=log_path.read_bytes();resource=resource_path.read_bytes()
 assert receipt['exit_code']==expected_exit
 assert receipt['source_tree']==tree and receipt['source_commit']==commit
 assert sha(log)==receipt['log_sha256'] and sha(resource)==receipt['resources_sha256']
 assert f'Exit status: {expected_exit}'.encode()in resource
 assert abs(receipt['end_unix']-receipt['start_unix']-receipt['elapsed_seconds'])<1e-6
 assert ('Command being timed: "'+' '.join(receipt['command'])+'"').encode()in resource
 receipts[phase]=receipt;log_data[phase]=log
assert receipts['strict']['command']==['just','clippy','--locked','-p','codex-core','--','-D','warnings']
assert receipts['tests']['command']==['just','test','--locked','-p','codex-core','--retries','0']
assert receipts['tests']['retries']==0
assert receipts['strict']['end_unix']<=receipts['tests']['start_unix']
log=log_data['tests']
assert sha(log)=='443a58d70c34d76ba9b8141ad7ee32d997a4f16af79e8f5a873770966028952c' and len(log)==551526
summary=re.search(rb'^\s*Summary \[([^\]]+)\] ([^\r\n]+)',log,re.M)
assert summary
pattern=rb'^\s*(PASS|FAIL|TIMEOUT|SKIP)\s+\[([^\]]+)\]\s+(\S+)\s+([^\r\n]+)'
rows=[]
for m in re.finditer(pattern,log[:summary.start()],re.M):
 rows.append({'status':m.group(1).decode(),'elapsed':m.group(2).decode().strip(),'binary':m.group(3).decode(),'name':m.group(4).decode(),'header_byte_offset':m.start()})
keys=[(x['binary'],x['name'])for x in rows]
assert len(keys)==len(set(keys))==3830
counts=collections.Counter(x['status']for x in rows)
assert counts=={'PASS':3806,'FAIL':24}
assert b'3830 tests run: 3806 passed, 24 failed, 9 skipped'in summary.group()
assert b'Starting 3830 tests across 4 binaries (9 tests skipped)'in log
footer=[m for m in re.finditer(pattern,log[summary.start():],re.M)]
assert len(footer)==24 and all(m.group(1)==b'FAIL'for m in footer)
review=json.loads((p/'evidence/native-core-r14-result-review.json').read_bytes())
assert review['source_tree']==tree and review['source_commit']==commit
assert review['log_sha256']==sha(log) and review['log_bytes']==len(log)
assert review['counts_unique']==dict(counts)
failed=[x for x in rows if x['status']=='FAIL']
fail_map={(x['binary'],x['name']):x for x in failed}
assert len(review['blocks'])==24
assert {(x['binary'],x['name'])for x in review['blocks']}==set(fail_map)
for block in review['blocks']:
 start,end=block['log_byte_range']
 assert log[start:end].decode()==block['excerpt']
 assert block['elapsed']==fail_map[(block['binary'],block['name'])]['elapsed']
active=json.loads((p/'evidence/native-core-r14-active-failure-excerpts-1.json').read_bytes())
prefix=log[:active['prefix_bytes']]
assert sha(prefix)==active['prefix_sha256'] and len(active['blocks'])==7
for block in active['blocks']:
 excerpt=block['excerpt'].encode()
 assert prefix.count(excerpt)==1
 assert block['excerpt']==next(x for x in review['blocks']if x['name']==block['name'])['excerpt']
reg=[]
assert len(review['new_regression_ids'])==6
for expected in review['new_regression_ids']:
 row=next(x for x in rows if(x['binary'],x['name'])==(expected['binary'],expected['name']))
 assert row['status']=='PASS' and row['elapsed']==expected['elapsed']
 reg.append(row)
post=json.loads((p/'evidence/native-core-r14-source-post-test-verification.json').read_bytes())
env=json.loads((p/'evidence/native-core-r14-environment.json').read_bytes())
terminal=json.loads((p/'evidence/native-core-r14-process-terminal.json').read_bytes())
assert post['source_tree']==env['source_tree']==tree and post['changed_files_verified']==163
assert post['unstaged_tracked_files']==post['untracked_paths']==[]
assert source['lock_sha256']==post['lock_sha256']
assert terminal['exit_code']==100 and terminal['state']=='failed'
assert not terminal['timed_out'] and not terminal['cancelled'] and not terminal['automatic_retry']
assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
assert not any(terminal['log_truncated'].values())
inner=p/'evidence/native-core-r14-blocker-input.tar.gz'
ipins=json.loads((p/'evidence/native-core-r14-failure-source-input-manifest.json').read_bytes())
assert len(ipins['files'])==11
with tarfile.open(inner,'r:gz')as t:
 ims=t.getmembers()
 assert len(ims)==15 and len({m.name for m in ims})==15 and all(m.isfile()for m in ims)
 ibytes={m.name:t.extractfile(m).read()for m in ims}
 assert ibytes['source-manifest.json']==(p/'evidence/native-core-r14-failure-source-input-manifest.json').read_bytes()
 assert ibytes['result-review.json']==(p/'evidence/native-core-r14-result-review.json').read_bytes()
 assert ibytes['oauth-hook-caller-input.json']==(p/'evidence/native-core-r14-oauth-hook-caller-input.json').read_bytes()
 for pin in ipins['files']+ipins['instructions']:
  b=ibytes['source/'+pin['path']]
  assert len(b)==pin['bytes'] and sha(b)==pin['sha256'] and blob(b)==pin['git_blob']
  bound=changed.get(pin['path'])or base[pin['path']]
  assert (bound.get('git_blob')or bound['sha'])==pin['git_blob']
report={
 'schema':'hepta.independent-native-r14-readback.v1',
 'reviewer':'historical_assets','result':'VERIFIED_CLOSED_CORE_GATE_FAILED',
 'source_commit':commit,'source_tree':tree,
 'archive':{
  **ident(archive),'regular_members_verified':179,'unique_member_paths':179,
  'source_members':163,'evidence_members':15,'index_members':1,
  'all_member_raw_sha256_size_tar_mode_and_extracted_mode_match':True,
  'all_163_source_git_blob_hashes_match':True,
  'no_archive_links_or_unsafe_paths':True,'index':ident(p/'INDEX.json')
 },
 'source_identity':{
  'source_manifest':ident(p/'evidence/native-candidate-r14-source.json'),
  'changed_source_files_verified':163,'base_commit':git_input['source_base_commit'],
  'base_tree':git_input['base_tree'],
  'base_recursive_listing_entries':git_input['base_recursive_entry_count'],
  'base_recursive_listing_truncated':False,
  'independent_git_tree_input':ident(p/'INDEPENDENT-SOURCE-TREE-INPUT.json'),
  'base_entries_used':len(git_input['base_entries']),
  'changed_ancestor_directories_recomputed':len(computed),
  'reconstructed_tree':computed[''],
  'root_roundtrip_input_matches_all_163_elements':True,
  'after_gate_tree_report':post,
  'boundary':'All 163 changed source bytes and modes were independently verified. Existing immutable Git tree/blob IDs from the previously fetched complete bef6fa listing bind unchanged repository contents; those remaining blobs were not individually downloaded or byte-verified in this readback. A separate offline Git tree hash reconstruction produced the exact source43 tree. Clean checkout and lock stability after execution are native-reported facts, cross-bound to the archived manifests.'
 },
 'gates':{
  phase:{**receipts[phase],
   'receipt':ident(p/'evidence'/f'native-core-r14-{phase}-receipt.json'),
   'log':ident(p/'evidence'/f'native-core-r14-{phase}.log'),
   'resources':ident(p/'evidence'/f'native-core-r14-{phase}-resources.txt')
  }for phase in ['strict','tests']
 },
 'test_result':{
  'unique_executed':3830,'passed':3806,'failed':24,'timeouts':0,
  'skipped_reported':9,'binary_count_reported':4,
  'nextest_execution_elapsed_seconds':570.123,
  'whole_test_command_elapsed_seconds':receipts['tests']['elapsed_seconds'],
  'retries':0,'duplicate_failure_footer_rows_excluded':24,
  'unique_ids_verified':True,'failure_blocks_exact_raw_byte_offsets_verified':24,
  'failed_tests':[{'binary':x['binary'],'name':x['name'],'elapsed':x['elapsed'],'log_byte_range':x['log_byte_range']}for x in review['blocks']],
  'skip_boundary':'Nine skips are reported by both the start and terminal summary; the log does not enumerate nine SKIP result rows. They are not counted as executed or passed, and their individual reasons are not inferred here.'
 },
 'active_prefix':{
  'status_retained':active['status'],'prefix_bytes':active['prefix_bytes'],
  'sha256':active['prefix_sha256'],'prefix_matches_closed_log':True,
  'complete_failure_blocks_verified':7,'not_used_as_terminal_gate_receipt':True
 },
 'six_new_termination_regressions':reg,
 'nested_blocker_input':{
  **ident(inner),'regular_members_verified':15,
  'eleven_suite_source_pins_and_root_instructions_verified':True,
  'suite_blobs_bound_to_same_source_tree':True,
  'closed_result_and_caller_inputs_equal_outer_evidence':True
 },
 'environment':env,'native_process_terminal':terminal,
 'scope_and_limits':[
  'No test, build, Rust, Cargo, just, fix or formatting command was executed for this readback.',
  'The strict codex-core gate passed; its complete original test gate failed. Six new regression passes do not make the whole Core gate pass.',
  'The full workspace gate was not started according to the checkpoint; no workspace qualification is claimed.',
  'Historical earlier strict-only readback remains a point-in-time snapshot and is superseded by this closed result for overall status.',
  'Post-r14 isolated repair candidates are not part of source tree d3d2313 and have not been qualified by these r14 results.'
 ]
}
out=p/'INDEPENDENT-READBACK.json'
out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(ident(out)))
print(json.dumps({'raw_member_checks':179,'source_files':163,'recomputed_tree':computed[''],'counts':dict(counts),'new_regressions':len(reg)}))

