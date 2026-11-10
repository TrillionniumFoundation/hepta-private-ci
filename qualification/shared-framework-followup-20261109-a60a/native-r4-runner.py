import json,os,pathlib,subprocess,time,hashlib,sys,tomllib,copy
base=pathlib.Path('/home/qq/hepta-shared-framework-f8e4-20261109')
task=pathlib.Path('/home/qq/hepta-framework-followup-a60a-20261110')
source=task/'source';record=task/'validation-r4';record.mkdir(exist_ok=True)
temp=pathlib.Path('/home/qq/t-a60a4');temp.mkdir(mode=0o700,exist_ok=True)
env=os.environ.copy();env.update(PATH=str(base/'tools/bin')+':/home/qq/.cargo/bin:'+env.get('PATH',''),RUSTUP_TOOLCHAIN='1.96.0',CARGO_TARGET_DIR=str(base/'target'),CARGO_BUILD_JOBS='2',CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',CARGO_INCREMENTAL='0',CARGO_HTTP_MULTIPLEXING='false',CARGO_NET_RETRY='5',NEXTEST_TEST_THREADS='2',TMPDIR=str(temp),PYTHONDONTWRITEBYTECODE='1',BINDGEN_EXTRA_CLANG_ARGS='-resource-dir='+str(base/'clang-resource/usr/lib/llvm-21/lib/clang/21'),SOURCE_SHA='fb1397873bef0eea81efe0c8aac48c56385ffe55',TESTED_SHA='fb1397873bef0eea81efe0c8aac48c56385ffe55',BASE_SHA='300ebaaedd9ec578ffcd2bc341c2394ead6a92c8',HEPTA_CI_LANE='source-head')
progress={'source':'fb1397873bef0eea81efe0c8aac48c56385ffe55','commands':[],'complete':False,'temporary_directory':str(temp),'nextest_test_threads':2}
def save():(record/'progress.json').write_text(json.dumps(progress,indent=2)+'\n')
def output(args,cwd=None):return subprocess.check_output(args,cwd=cwd,env=env,text=True).strip()
def run(name,args,cwd=None,timeout=1800):
 t=time.time()
 with (record/(name+'.log')).open('wb') as log:p=subprocess.run(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 r={'name':name,'argv':args,'exit_code':p.returncode,'wall_seconds':time.time()-t,'log':name+'.log'};progress['commands'].append(r);save();print(json.dumps(r),flush=True)
 if p.returncode:sys.exit(p.returncode)
save()
if output(['git','status','--porcelain'],source):raise RuntimeError('owned source is dirty; do not overwrite')
run('fetch',['git','fetch','--depth','2','https://github.com/TrillionniumFoundation/hepta-private-ci.git','codex/shared-cell-framework-followup-20261109-a60a'],source,300)
run('checkout',['git','checkout','--detach','fb1397873bef0eea81efe0c8aac48c56385ffe55'],source,60)
assert output(['git','rev-parse','HEAD'],source)=='fb1397873bef0eea81efe0c8aac48c56385ffe55'
progress['tree']=output(['git','rev-parse','HEAD^{tree}'],source)
progress['rustc']=output(['rustc','--version','--verbose'],source/'codex-rs')
progress['storage_bytes']=output(['df','-h',str(temp)])
progress['storage_inodes']=output(['df','-i',str(temp)])
original=(source/'codex-rs/.config/nextest.toml').read_text()
lines=original.splitlines(keepends=True);inside=False;changed=0
for i,line in enumerate(lines):
 if line.startswith('['):inside=line.strip()=='[profile.local.junit]'
 elif inside and line.startswith('path = '):
  lines[i]='path = '+json.dumps(str(record/'junit-original.xml'))+'\n';changed+=1
modified=''.join(lines);parsed=tomllib.loads(original);expected=copy.deepcopy(parsed);expected['profile']['local']['junit']['path']=str(record/'junit-original.xml')
assert changed==1 and tomllib.loads(modified)==expected
config=record/'nextest.toml';config.write_text(modified)
progress['nextest_config_sha256']=hashlib.sha256(modified.encode()).hexdigest()
progress['configuration_delta']='profile.local.junit.path only; package selection and all other settings preserved'
save()
helper=record/'helper-env'
run('helper',['python3','scripts/hepta_cell_test_helpers.py','--package','codex-hepta-infer-worker-host','--output-dir',str(record/'helpers'),'--github-env',str(helper)],source,1800)
for line in helper.read_text().splitlines():
 if line.strip():
  key,value=line.split('=',1);env[key]=value
run('tests',['python3','scripts/hepta_ci_exec.py','--timeout-seconds','3600','--minimum-tests','1','--output',str(record/'tests.json'),'--','just','test','--locked','-p','codex-hepta-automation','-p','codex-hepta-neuron','-p','codex-hepta-agentd','--lib','--config-file',str(config)],source,3700)
run('helper-after',['python3','scripts/hepta_cell_test_helpers.py','--verify-only','--package','codex-hepta-infer-worker-host','--output-dir',str(record/'helpers')],source,120)
run('junit',['python3','scripts/hepta_ci_junit.py','--execution',str(record/'tests.json'),'--junit',str(record/'junit-original.xml'),'--output',str(record/'junit.xml')],source,120)
run('fix',['just','fix','-p','codex-hepta-automation','-p','codex-hepta-agentd'],source/'codex-rs',1800)
run('fmt',['just','fmt','--base','71738345326b98d88b738250d2b84ecbcb466eb8'],source/'codex-rs',600)
run('diff-check',['git','diff','--check'],source,60)
(record/'maintenance.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=source,env=env))
progress['status_after']=output(['git','status','--porcelain'],source);progress['diff_stat']=output(['git','diff','--stat'],source)
progress['complete']=True;save();print(json.dumps(progress),flush=True)

