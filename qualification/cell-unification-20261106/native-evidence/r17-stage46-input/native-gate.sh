python3 - <<'PY'
import hashlib,io,json,os,pathlib,shutil,subprocess,sys,tarfile,time
T=pathlib.Path('/home/alex/work/hepta-cell-unified-20261106-a');S=T/'source';E=T/'evidence';D=T/'stage46-r17-input'
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
data=(T/'stage46-r17-input.tar.gz').read_bytes()
assert len(data)==3064 and sha(data)=='c9554c2c42c3202f693427ca2c4f137acb240172c0708f44b8c204aa48a4f24b'
D.mkdir(exist_ok=True)
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tf:
 for member in tf.getmembers():
  assert member.isfile() and not pathlib.PurePosixPath(member.name).is_absolute() and '..' not in pathlib.PurePosixPath(member.name).parts
  p=D/member.name;p.parent.mkdir(parents=True,exist_ok=True);raw=tf.extractfile(member).read()
  if p.exists():assert p.read_bytes()==raw
  else:p.write_bytes(raw)
m=json.loads((D/'manifest.json').read_text())
assert m['source_commit']=='2d7ad1d60019f35fc13d84138ceb2755d914f434' and m['expected_after_tree']=='ffa0a37f4616c5563169c7f0a9305bf6c982d58b'
assert m['expected_changed_file_count']==180
assert sha((D/'root-published-source.json').read_bytes())==m['root_published_source_sha256']
before=subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip()
assert before==m['before_tree'],before
assert not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip(),'unstaged source'
assert not subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=S,text=True).strip(),'untracked source'
assert sha((S/'codex-rs/Cargo.lock').read_bytes())=='4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
for f in m['files']:assert sha((S/f['path']).read_bytes())==f['before']['sha256'],f['path']
assert sha((D/m['combined_patch']['path']).read_bytes())==m['combined_patch']['sha256']
assert sha((D/'root-publish-manifest.json').read_bytes())==m['root_publish_manifest_sha256']
subprocess.run(['git','apply','--check',str(D/m['combined_patch']['path'])],cwd=S,check=True)
subprocess.run(['git','apply',str(D/m['combined_patch']['path'])],cwd=S,check=True)
for f in m['files']:assert sha((S/f['path']).read_bytes())==f['after']['sha256'],f['path']
subprocess.run(['git','add','--',*[f['path'] for f in m['files']]],cwd=S,check=True)
tree=subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip()
assert tree==m['expected_after_tree'],tree
assert not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip()
assert not subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=S,text=True).strip()
base='bef6fa7645df9df12b69fda499e97eed25de6c75'
paths=subprocess.check_output(['git','diff','--name-only',base,tree],cwd=S,text=True).splitlines();assert len(paths)==m['expected_changed_file_count'],len(paths)
files=[]
for path in paths:
 raw=(S/path).read_bytes();mode,kind,blob=subprocess.check_output(['git','ls-tree',tree,'--',path],cwd=S,text=True).strip().split('\t')[0].split()
 assert kind=='blob' and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==blob
 files.append({'path':path,'bytes':len(raw),'sha256':sha(raw),'git_blob':blob,'mode':mode})
source={'schema':'hepta.native-candidate-r17.v1','source_tree':tree,'source_commit':m['source_commit'],'parent_identities':[base,'caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b'],'before_tree':before,'applied_stage':46,'input_archive_sha256':sha(data),'input_combined_patch_sha256':m['combined_patch']['sha256'],'changed_files':files,'lock_sha256':sha((S/'codex-rs/Cargo.lock').read_bytes()),'workflow_sha256':sha((S/'.github/workflows/hepta-cell-framework-native.yml').read_bytes())}
assert source['lock_sha256']=='4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
write(E/'native-candidate-r17-source.json',source)
env=os.environ.copy();env.update({'PATH':str(T/'bin')+':/home/alex/.cargo/bin:'+env.get('PATH',''),'RUSTUP_TOOLCHAIN':'1.96.0','CARGO_BUILD_JOBS':'2','CARGO_TARGET_DIR':str(T/'target'),'CARGO_NET_GIT_FETCH_WITH_CLI':'true','NEXTEST_TEST_THREADS':'2','PYTHONDONTWRITEBYTECODE':'1','CARGO_PROFILE_TEST_DEBUG':'0','CARGO_PROFILE_DEV_DEBUG':'0'})
for k,v in json.loads((E/'agentd-prerequisite-env.json').read_text()).items():
 if k in ['RUSTY_V8_ARCHIVE','RUSTY_V8_SRC_BINDING_PATH','PROTOC','PROTOC_INCLUDE','DOTSLASH_CACHE']:env[k]=v
selection={k:env.get(k) for k in ['RUSTUP_TOOLCHAIN','CARGO_BUILD_JOBS','CARGO_TARGET_DIR','CARGO_NET_GIT_FETCH_WITH_CLI','NEXTEST_TEST_THREADS','NEXTEST_PROFILE','HEPTA_NEXTTEST_FULL_METADATA','CARGO_PROFILE_TEST_DEBUG','CARGO_PROFILE_DEV_DEBUG','CARGO_INCREMENTAL','CARGO_BUILD_TARGET','RUSTFLAGS','DOTSLASH_CACHE']}
write(E/'native-core-mcp-r17-environment.json',{'source_tree':tree,'selection':selection,'free_bytes_before':shutil.disk_usage(T).free,'source_environment_immutable_during_gates':True,'test_deadlines_features_filters_retries_unchanged':True})
print(json.dumps({'phase':'stage46-applied','source_tree':tree,'changed_file_count':len(files),'stage_source_commit':m['source_commit'],'environment':selection}),flush=True)
for phase,cmd in [('strict',['just','clippy','--locked','-p','codex-core','-p','codex-mcp','-p','core_test_support','--','-D','warnings']),('tests',['just','test','--locked','-p','codex-core','-p','codex-mcp','-p','core_test_support','--retries','0'])]:
 assert subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip()==tree
 assert not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip()
 for f in files:assert sha((S/f['path']).read_bytes())==f['sha256'],f['path']
 stem='native-core-mcp-r17-'+phase;log=E/(stem+'.log');res=E/(stem+'-resources.txt');start=time.time()
 print(json.dumps({'phase':phase+'-start','command':cmd,'source_tree':tree}),flush=True)
 with log.open('wb') as f:rc=subprocess.run(['/usr/bin/time','-v','-o',str(res),*cmd],cwd=S/'codex-rs',env=env,stdout=f,stderr=subprocess.STDOUT).returncode
 end=time.time();receipt={'schema':'hepta.native-gate-receipt.v1','phase':phase,'source_tree':tree,'source_manifest':'native-candidate-r17-source.json','source_commit':m['source_commit'],'command':cmd,'cwd':str(S/'codex-rs'),'start_unix':start,'end_unix':end,'elapsed_seconds':end-start,'exit_code':rc,'log_sha256':sha(log.read_bytes()),'resources_sha256':sha(res.read_bytes()),'environment_manifest':'native-core-mcp-r17-environment.json','packages':['codex-core','codex-mcp','core_test_support'],'retries':0 if phase=='tests' else None}
 write(E/(stem+'-receipt.json'),receipt);print(json.dumps(receipt),flush=True);print(log.read_text(errors='replace')[-16000:],flush=True)
 post_tree=subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip()
 post_clean=not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip()
 post_untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=S,text=True).splitlines()
 post_hashes=all(sha((S/f['path']).read_bytes())==f['sha256'] for f in files)
 post_lock=sha((S/'codex-rs/Cargo.lock').read_bytes())
 post={'source_tree':tree,'actual_tree_after_phase':post_tree,'phase':phase,'all_changed_source_hashes_match':post_hashes,'unstaged_empty':post_clean,'untracked_source':post_untracked,'lock_sha256':post_lock,'changed_file_count':len(files),'gate_exit_code':rc}
 write(E/(stem+'-source-post-verification.json'),post)
 assert post_tree==tree and post_clean and not post_untracked and post_hashes and post_lock==source['lock_sha256'],'source changed during gate'
 if rc:sys.exit(rc)
write(E/'native-core-mcp-r17-complete.json',{'source_tree':tree,'strict_exit':0,'tests_exit':0,'free_bytes_after':shutil.disk_usage(T).free})
PY