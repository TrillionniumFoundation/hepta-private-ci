import os
os.sched_setaffinity(0,{0,1})
from pathlib import Path
import subprocess,json,hashlib,os,time,sys,traceback
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5')
repo=root/'candidate'
bundle=root/'historical-5c63003.bundle'
assert hashlib.sha256(bundle.read_bytes()).hexdigest()=='ce2bc05a3438dc410ac2e0ea291b2c50634fcfb5486bab93fa86eb200fc1e035'
output=root/'complete-owner-5c63003-fresh-receipts'
output.mkdir()
env=os.environ.copy()
env.update(PYTHONDONTWRITEBYTECODE='1',HEPTA_SOURCE=str(root/'hepta-0de'),CARGO_NET_GIT_FETCH_WITH_CLI='true',CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='2',CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',CARGO_TARGET_DIR=str(root/'target'),RUSTUP_TOOLCHAIN='1.96.1',RUSTC='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/rustc',CODEX_HIA_NATIVE_LIB_DIR=str(output/'hia-native'),GIT_TERMINAL_PROMPT='0')
env['PATH']='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin:/home/qian-qi/.cargo/bin:'+env.get('PATH','')
commands=[]
def run(label,argv,cwd=repo):
 log=output/(label+'.log');started=time.time()
 print(json.dumps({'label':label,'state':'running','argv':[str(x) for x in argv],'cwd':str(cwd),'started':started}),flush=True)
 with log.open('xb') as stream:p=subprocess.run([str(x) for x in argv],cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT)
 raw=log.read_bytes();row={'label':label,'argv':[str(x) for x in argv],'cwd':str(cwd),'started':started,'finished':time.time(),'returncode':p.returncode,'log':str(log),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 commands.append(row);(output/'preparation-commands.json').write_text(json.dumps(commands,indent=2)+'\n');print(json.dumps(row),flush=True)
 if p.returncode:
  print(raw[-16000:].decode('utf-8','replace'),flush=True)
  raise SystemExit(p.returncode)
 return raw
assert subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=repo)==b''
run('bundle-verify',['/usr/bin/git','bundle','verify',bundle])
run('bundle-import',['/usr/bin/git','fetch',bundle,'HEAD'])
run('candidate-checkout',['/usr/bin/git','checkout','--detach','5c630034a0b638673e9dd410abf2e223cf6d4307'])
assert subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=repo).decode().strip()=='5c630034a0b638673e9dd410abf2e223cf6d4307'
run('just-fmt',['/home/qian-qi/.cargo/bin/just','fmt'],repo/'codex-rs')
run('formatted-tracked-unchanged',['/usr/bin/git','diff','--exit-code','HEAD'])
assert subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=repo)==b''
run('formatter-scope',[sys.executable,'-B',repo/'scripts/test_hepta_format_scope.py'])
run('native-build',[sys.executable,'-B',repo/'hia/build.py','--hepta-root',root/'hepta-0de','--output',output/'hia-native'])
run('unified-policy-prepare',[sys.executable,'-B',repo/'hia/prepare_unified_diff_policy.py','--repo',repo,'--rustc',env['RUSTC'],'--config',output/'unified-policy/config.json','--receipt-root',output/'unified-policy/receipts','--bind-input',output/'hia-native/build.json','--report',output/'unified-policy/configuration-report.json','--github-env',output/'github-env'])
run('rebuild-current-policy-producers',['/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/cargo','clean','--package','similar@2.7.0','--package','codex-apply-patch','--target-dir',root/'target'],repo/'codex-rs')
print(json.dumps({'status':'passed','phase':'exact source, formatting, compiler generations, native build and policy setup','candidate':'5c630034a0b638673e9dd410abf2e223cf6d4307','output':str(output)}),flush=True)

from pathlib import Path
import subprocess,json,hashlib,os,time,sys
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5');repo=root/'candidate';output=root/'complete-owner-5c63003-fresh-receipts'
assert subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=repo).decode().strip()=='5c630034a0b638673e9dd410abf2e223cf6d4307'
assert not subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=repo).strip()
preparation=json.loads((output/'preparation-commands.json').read_text());assert len(preparation)==9 and all(type(row['returncode']) is int and row['returncode']==0 for row in preparation)
env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',HEPTA_SOURCE=str(root/'hepta-0de'),CARGO_NET_GIT_FETCH_WITH_CLI='true',CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='2',CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',CARGO_TARGET_DIR=str(root/'target'),RUSTUP_TOOLCHAIN='1.96.1',RUSTC='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/rustc',CODEX_HIA_NATIVE_LIB_DIR=str(output/'hia-native'),GIT_TERMINAL_PROMPT='0')
env['PATH']='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin:/home/qian-qi/.cargo/bin:'+env.get('PATH','')
for line in (output/'github-env').read_text().splitlines():
 key,value=line.split('=',1);assert key in {'RUSTC_WRAPPER','CODEX_HIA_SIMILAR_POLICY_CONFIG'};(env.__setitem__(key,value))
rows=[];started=time.time()
def run(label,args,condition=True):
 if not condition:
  row={'label':label,'status':'skipped','qualified':False};rows.append(row);save();print(json.dumps(row),flush=True);return False
 argv=[sys.executable,'-B',repo/'hia/tests'/args[0],*args[1:]]
 log=output/(label+'.log')
 print(json.dumps({'label':label,'state':'running','argv':[str(x) for x in argv],'started':time.time()}),flush=True)
 t=time.time()
 with log.open('xb') as f:
  child=subprocess.Popen([str(x) for x in argv],cwd=repo,env=env,stdout=f,stderr=subprocess.STDOUT)
  (output/'active-command.json').write_text(json.dumps({'label':label,'pid':child.pid,'started':t,'argv':[str(x) for x in argv]},indent=2)+'\n')
  code=child.wait()
 raw=log.read_bytes();row={'label':label,'status':'passed' if code==0 else 'failed','argv':[str(x) for x in argv],'cwd':str(repo),'started':t,'finished':time.time(),'returncode':code,'log':str(log),'log_bytes':len(raw),'log_sha256':hashlib.sha256(raw).hexdigest()}
 rows.append(row);save();print(json.dumps(row),flush=True)
 if code:print(raw[-16000:].decode('utf-8','replace'),flush=True)
 return code==0
def save():
 (output/'comparison-commands.json').write_text(json.dumps(rows,indent=2)+'\n')
library=output/'hia-native';rustc=env['RUSTC'];original=root/'file-update-original'
for path,commit in [(original,'a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095'),(root/'unified-original','aeb88f596b83186456caac577080bcb2f253ad32')]:
 assert subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=path).decode().strip()==commit
 assert not subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=path).strip()
run('source-admission',['test_file_update_dependency_admission.py','-v'])
run('darwin-source-admission',['test_file_update_darwin_admission.py','-v'])
run('uuid',['test_native_uuid_find_caller.py','--producer',repo,'--original-repo',original,'--library-dir',library,'--rustc',rustc,'--work-dir',output/'hia-uuid-caller','--report',output/'hia-uuid-caller.json'])
run('template',['test_native_template_parse_caller.py','--producer',repo,'--original-repo',original,'--library-dir',library,'--rustc',rustc,'--work-dir',output/'hia-template-caller','--report',output/'hia-template-caller.json'])
file_update=run('file-update',['test_native_file_update_caller.py','--original-root',original,'--library-dir',library,'--rustc',rustc,'--output-dir',output/'hia-file-update-caller','--report',output/'hia-file-update-caller.json'])
run('historical-controls',['test_historical_dependency_admission.py','--receipt',output/'hia-file-update-caller.json','--output-dir',output/'hia-historical-dependency-controls','--report',output/'hia-historical-dependency-controls.json'],file_update)
effects=run('effects',['test_native_patch_effects_caller.py','--producer',repo,'--original-root',original,'--library-dir',library,'--rustc',rustc,'--work-dir',output/'hia-patch-effects-caller','--report',output/'hia-patch-effects-caller.json'])
for label in ('standalone','application','summary'):
 run(label,['test_native_patch_'+label+'_caller.py','--producer',repo,'--library-dir',library,'--effects-report',output/'hia-patch-effects-caller.json','--rustc',rustc,'--work-dir',output/('hia-patch-'+label+'-caller'),'--report',output/('hia-patch-'+label+'-caller.json')],effects)
policy=run('unified-policy',['test_unified_diff_policy.py','--library-dir',library,'--rustc',rustc,'--target-dir',root/'target','--output-dir',output/'unified-policy-gate','--report',output/'unified-policy-report.json'])
run('unified-public',['test_native_unified_diff_caller.py','--library-dir',library,'--rustc',rustc,'--original-root',root/'unified-original','--policy-report',output/'unified-policy-report.json','--target-dir',root/'target','--output-dir',output/'unified-public-gate','--report',output/'unified-public-report.json'],policy)
unchanged=subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=repo)==b''
record={'schema':'codex.hia.complete-owner-actual-sequence.v1','candidate':'5c630034a0b638673e9dd410abf2e223cf6d4307','started':started,'finished':time.time(),'passed':all(row['status']=='passed' for row in rows) and unchanged,'source_unchanged':unchanged,'tests_skipped':sum(row['status']=='skipped' for row in rows),'commands':rows,'cpu_affinity':sorted(os.sched_getaffinity(0)),'cargo_build_jobs':2,'full_native_workflow_qualified':False,'whole_product_qualified':False}
(output/'sequence-result.json').open('x').write(json.dumps(record,indent=2)+'\n')
print(json.dumps({k:v for k,v in record.items() if k!='commands'}),flush=True)
raise SystemExit(0 if record['passed'] else 1)
