python3 - <<'PY'
import hashlib,json,os,pathlib,shutil,subprocess,sys,time
T=pathlib.Path('/home/alex/work/hepta-cell-unified-20261106-a');S=T/'source';E=T/'evidence'
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
expected='ffa0a37f4616c5563169c7f0a9305bf6c982d58b';source_name='native-candidate-r17-source.json';stem='native-workspace-r18'
tree=subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip();assert tree==expected,tree
assert not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip()
assert not subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=S,text=True).strip()
assert sha((S/'codex-rs/Cargo.lock').read_bytes())=='4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
source_raw=(E/source_name).read_bytes();source=json.loads(source_raw);assert source['source_tree']==tree
assert source['source_commit']=='2d7ad1d60019f35fc13d84138ceb2755d914f434' and len(source['changed_files'])==180
for f in source['changed_files']:assert sha((S/f['path']).read_bytes())==f['sha256'],f['path']
prerequisites=[]
for name in ['native-core-mcp-r17-strict-receipt.json','native-core-mcp-r17-tests-receipt.json']:
 path=E/name;raw=path.read_bytes();r=json.loads(raw);assert r['exit_code']==0 and r['source_tree']==tree
 assert r['packages']==['codex-core','codex-mcp','core_test_support']
 logname=name.replace('-receipt.json','.log');assert sha((E/logname).read_bytes())==r['log_sha256']
 prerequisites.append({'path':name,'sha256':sha(raw),'source_tree':r['source_tree'],'exit_code':r['exit_code'],'log_sha256':r['log_sha256']})
env=os.environ.copy();env.update({'PATH':str(T/'bin')+':/home/alex/.cargo/bin:'+env.get('PATH',''),'RUSTUP_TOOLCHAIN':'1.96.0','CARGO_BUILD_JOBS':'2','CARGO_TARGET_DIR':str(T/'target'),'CARGO_NET_GIT_FETCH_WITH_CLI':'true','NEXTEST_TEST_THREADS':'2','PYTHONDONTWRITEBYTECODE':'1','CARGO_PROFILE_TEST_DEBUG':'0','CARGO_PROFILE_DEV_DEBUG':'0'})
for k,v in json.loads((E/'agentd-prerequisite-env.json').read_text()).items():
 if k in ['RUSTY_V8_ARCHIVE','RUSTY_V8_SRC_BINDING_PATH','PROTOC','PROTOC_INCLUDE','DOTSLASH_CACHE']:env[k]=v
selection={k:env.get(k) for k in ['RUSTUP_TOOLCHAIN','CARGO_BUILD_JOBS','CARGO_TARGET_DIR','CARGO_NET_GIT_FETCH_WITH_CLI','NEXTEST_TEST_THREADS','NEXTEST_PROFILE','HEPTA_NEXTTEST_FULL_METADATA','CARGO_PROFILE_TEST_DEBUG','CARGO_PROFILE_DEV_DEBUG','CARGO_INCREMENTAL','CARGO_BUILD_TARGET','RUSTFLAGS','DOTSLASH_CACHE','RUST_MIN_STACK']}
metadata_cmd=['cargo','metadata','--locked','--no-deps','--format-version','1']
metadata_raw=subprocess.check_output(metadata_cmd,cwd=S/'codex-rs',env=env);metadata=json.loads(metadata_raw);(E/(stem+'-metadata.json')).write_bytes(metadata_raw)
package_names={p['id']:p['name'] for p in metadata['packages']}
workspace_scope={'metadata_command':metadata_cmd,'metadata_sha256':sha(metadata_raw),'workspace_members':[{'id':p,'name':package_names[p]} for p in metadata['workspace_members']],'workspace_default_members':[{'id':p,'name':package_names[p]} for p in metadata['workspace_default_members']]}
assert len(workspace_scope['workspace_members'])==193 and len(workspace_scope['workspace_default_members'])==193
assert 'core_test_support' in [p['name'] for p in workspace_scope['workspace_members']]
write(E/(stem+'-scope.json'),workspace_scope)
write(E/(stem+'-environment.json'),{'source_tree':tree,'source_manifest':source_name,'source_manifest_sha256':sha(source_raw),'selection':selection,'free_bytes_before':shutil.disk_usage(T).free,'project_gate_prerequisites':prerequisites,'original_default_workspace_selection':True,'workspace_member_count':len(workspace_scope['workspace_members']),'workspace_default_member_count':len(workspace_scope['workspace_default_members']),'test_deadlines_features_filters_retries_unchanged':True})
cmd=['just','test','--locked','--retries','0'];log=E/(stem+'-tests.log');res=E/(stem+'-tests-resources.txt');start=time.time()
print(json.dumps({'phase':'original-default-workspace-start','command':cmd,'source_tree':tree,'selection':selection,'workspace_member_count':len(workspace_scope['workspace_members']),'workspace_default_member_count':len(workspace_scope['workspace_default_members']),'prerequisites':prerequisites}),flush=True)
with log.open('wb') as output:rc=subprocess.run(['/usr/bin/time','-v','-o',str(res),*cmd],cwd=S/'codex-rs',env=env,stdout=output,stderr=subprocess.STDOUT).returncode
end=time.time();after=subprocess.check_output(['git','write-tree'],cwd=S,text=True).strip();assert after==tree
assert not subprocess.check_output(['git','diff','--name-only'],cwd=S,text=True).strip()
for f in source['changed_files']:assert sha((S/f['path']).read_bytes())==f['sha256'],f['path']
receipt={'schema':'hepta.native-workspace-gate-receipt.v1','source_tree':tree,'source_manifest':source_name,'source_commit':source['source_commit'],'command':cmd,'cwd':str(S/'codex-rs'),'start_unix':start,'end_unix':end,'elapsed_seconds':end-start,'exit_code':rc,'log_sha256':sha(log.read_bytes()),'resources_sha256':sha(res.read_bytes()),'environment_manifest':stem+'-environment.json','test_scope':'original_default_workspace','retries':0,'features':'unchanged_defaults','filters':'no_additions','free_bytes_after':shutil.disk_usage(T).free}
write(E/(stem+'-tests-receipt.json'),receipt);print(json.dumps(receipt),flush=True);print(log.read_text(errors='replace')[-18000:],flush=True);sys.exit(rc)
PY