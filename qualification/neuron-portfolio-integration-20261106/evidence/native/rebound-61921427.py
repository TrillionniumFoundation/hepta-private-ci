import datetime,hashlib,json,os,pathlib,shutil,subprocess,sys,time
root=pathlib.Path('/home/qq/work/hepta-portfolio-816d-20261106');source=root/'source';records=root/'records';expected='61921427dc19223fd8c9d0ded1a4723b255c5df5';tree='31d99be67393619aca47436d82f9dca909cba359'
env=os.environ.copy();env.update(json.loads((root/'env.json').read_text()));env.update(CARGO_TERM_COLOR='never',CARGO_NET_OFFLINE='true',GIT_TERMINAL_PROMPT='0',GIT_LFS_SKIP_SMUDGE='1',CODEX_REPO_ROOT=str(source),BINDGEN_EXTRA_CLANG_ARGS='-isystem /usr/lib/gcc/x86_64-linux-gnu/15/include',LIBCLANG_PATH='/usr/lib/x86_64-linux-gnu',RUST_MIN_STACK='8388608',NEXTEST_PROFILE='local');env.update(json.loads((records/'current-helper-env.json').read_text()))
def git(*args):return subprocess.check_output(['git',*args],cwd=source,env=env,text=True).strip()
def identity():return {'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'status':git('status','--porcelain=v1','--untracked-files=all')}
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
assert identity()=={'head':expected,'tree':tree,'status':''}
for kind in ['manifest','env']:
 origin=records/('current-helper-'+kind+'.json');dest=records/'formal-61921427-tests'/('pre-test-helper-'+kind+'.json')
 if dest.exists():assert dest.read_bytes()==origin.read_bytes()
 else:shutil.copy2(origin,dest)
manifest=json.loads((records/'current-helper-manifest.json').read_text())
def helpers():
 return {n:{'path':a['executable'],'sha256':digest(pathlib.Path(a['executable'])),'mtime_ns':pathlib.Path(a['executable']).stat().st_mtime_ns,'bytes':pathlib.Path(a['executable']).stat().st_size} for n,a in manifest['artifacts'].items()}
v8=json.loads((records/'formal-61921427-tests/receipt.json').read_text())['v8_build_assets']
for key,item in v8.items():
 p=pathlib.Path(item['path']);assert digest(p)==item['sha256'];env[key]=str(p)
dest=records/'formal-61921427-test-profile-artifacts';dest.mkdir(exist_ok=False)
cmd=['cargo','nextest','list','--locked','--offline','-p','codex-hepta-neuron','-p','codex-hepta-intelligence','-p','codex-hepta-agentd','-p','codex-hepta-infer-worker-host','--cargo-metadata',str(records/'formal-61921427-test-inventory/cargo-metadata.json'),'--profile','local','--cargo-message-format','json','--message-format','json']
receipt={'source_before':identity(),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'command':cmd,'helper_before':helpers(),'action':'List only; capture Cargo compiler artifacts for current test-profile binaries; no test bodies executed.'}
start=time.monotonic()
with (dest/'stdout.jsonl').open('wb') as out,(dest/'stderr.log').open('wb') as err:rc=subprocess.call(cmd,cwd=source/'codex-rs',env=env,stdout=out,stderr=err)
receipt.update(exit_code=rc,elapsed_seconds=time.monotonic()-start,source_after=identity(),helper_after=helpers())
(dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
assert rc==0 and receipt['source_before']==receipt['source_after']
artifacts=[];finished=False
for line in (dest/'stdout.jsonl').read_text().splitlines():
 try:item=json.loads(line)
 except ValueError:continue
 if item.get('reason')=='compiler-artifact':artifacts.append(item)
 if item.get('reason')=='build-finished':finished=item.get('success') is True
assert finished
agent=manifest['artifacts']['codex-hepta-agentd']
matches=[a for a in artifacts if a.get('executable')==agent['executable'] and a.get('target',{}).get('name')=='codex-hepta-agentd' and not a.get('profile',{}).get('test')]
assert len(matches)==1,len(matches)
actual=matches[0];p=pathlib.Path(actual['executable'])
manifest['artifacts']['codex-hepta-agentd']={'package':'codex-hepta-agentd','package_id':actual['package_id'],'executable':str(p),'profile':actual['profile'],'sha256':digest(p),'bytes':p.stat().st_size}
joint=manifest['artifacts']['hepta-joint-propose'];assert digest(pathlib.Path(joint['executable']))==joint['sha256']
manifest['artifact_provenance']={'hepta-joint-propose':{'cargo_artifact_file':str(records/'formal-61921427-joint-helper/helpers/codex-hepta-infer-worker-host.jsonl'),'sha256_unchanged_after_first_tests':True},'codex-hepta-agentd':{'cargo_artifact_file':str(dest/'stdout.jsonl'),'compiler_artifact':actual,'listing_receipt':str(dest/'receipt.json')}}
manifest['previous_pretest_manifest']=str(records/'formal-61921427-tests/pre-test-helper-manifest.json')
manifest['test_profile_rebinding_note']='First just test rebuilt normal agentd executable during test compilation; this manifest uses the actual current test-profile Cargo compiler-artifact and bytes. Joint helper is unchanged. Original build manifest, first test results and comparison are retained.'
(records/'rebound-helper-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');shutil.copy2(records/'current-helper-env.json',records/'rebound-helper-env.json')
runner=(root/'native-command-v2.py').read_text()
runner=runner.replace("current-helper-env.json","rebound-helper-env.json").replace("current-helper-manifest.json","rebound-helper-manifest.json")
needle="        for artifact in manifest['artifacts'].values():"
assert runner.count(needle)==1
runner=runner.replace(needle,"        receipt['helper_manifest_path'] = str(root / 'records/rebound-helper-manifest.json')\n        receipt['helper_manifest_sha256'] = hashlib.sha256((root / 'records/rebound-helper-manifest.json').read_bytes()).hexdigest()\n        receipt['helper_before'] = []\n        shutil.copy2(root / 'records/rebound-helper-manifest.json', records / 'pre-test-helper-manifest.json')\n        shutil.copy2(helper_env, records / 'pre-test-helper-env.json')\n"+needle)
needle="            assert hashlib.sha256(executable.read_bytes()).hexdigest() == artifact['sha256']"
assert runner.count(needle)==1
runner=runner.replace(needle,needle+"\n            receipt['helper_before'].append({'executable': str(executable), 'sha256': artifact['sha256'], 'mtime_ns': executable.stat().st_mtime_ns, 'bytes': executable.stat().st_size})")
runner=runner.replace("root / 'target/nextest/local/junit.xml'","source / 'codex-rs/target/nextest/local/junit.xml'")
needle="after = identity()"
assert runner.count(needle)==1
afterblock="""if command[:2] == ['just', 'test']:
    receipt['helper_after'] = []
    for artifact in manifest['artifacts'].values():
        executable = pathlib.Path(artifact['executable'])
        actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        receipt['helper_after'].append({'executable': str(executable), 'sha256': actual_hash, 'mtime_ns': executable.stat().st_mtime_ns, 'bytes': executable.stat().st_size})
    receipt['helper_unchanged'] = receipt['helper_before'] == receipt['helper_after']
    if not receipt['helper_unchanged'] and rc == 0:
        receipt['command_exit_code'] = 0
        rc = 78
"""
runner=runner.replace(needle,afterblock+needle)
needle="receipt['junit'] = {'path': str(saved),"
assert runner.count(needle)==1
runner=runner.replace(needle,"receipt['junit'] = {'origin': str(junit), 'origin_mtime_ns': junit.stat().st_mtime_ns, 'started_ns': receipt['started_ns'], 'path': str(saved),")
(root/'native-command-v3.py').write_text(runner)
command=['just','test','--locked','--offline','-p','codex-hepta-neuron','-p','codex-hepta-intelligence','-p','codex-hepta-agentd','-p','codex-hepta-infer-worker-host']
state={'source':identity(),'state':'running','label':'formal-61921427-tests-rebound','reason':'Necessary warm revalidation binds actual test-profile agentd binary with both pre/post helper hash guard; first successful run retained.'}
(records/'rebound-61921427.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state),flush=True)
rc=subprocess.call(['/usr/bin/python3',str(root/'native-command-v3.py'),expected,tree,'formal-61921427-tests-rebound',json.dumps(command)],env=env)
state.update(exit_code=rc,state='succeeded' if rc==0 else 'failed',source_after=identity())
(records/'rebound-61921427.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps(state),flush=True)
raise SystemExit(rc)
