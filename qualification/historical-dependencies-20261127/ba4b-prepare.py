from pathlib import Path
import subprocess,json,hashlib,os,time,sys,traceback
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5')
repo=root/'candidate'
bundle=root/'codex-historical-candidate-ba4b.bundle'
assert hashlib.sha256(bundle.read_bytes()).hexdigest()=='a37f19ca3362e3136a5518ca971cd251691d40d710030abae310340011e0b731'
output=root/'complete-owner-ba4b'
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
run('candidate-checkout',['/usr/bin/git','checkout','--detach','ba4b4778d0b900c2259538b14b181e11dd39a3a7'])
assert subprocess.check_output(['/usr/bin/git','rev-parse','HEAD'],cwd=repo).decode().strip()=='ba4b4778d0b900c2259538b14b181e11dd39a3a7'
run('just-fmt',['/home/qian-qi/.cargo/bin/just','fmt'],repo/'codex-rs')
run('formatted-tracked-unchanged',['/usr/bin/git','diff','--exit-code','HEAD'])
assert subprocess.check_output(['/usr/bin/git','status','--porcelain=v1','--untracked-files=all'],cwd=repo)==b''
run('formatter-scope',[sys.executable,'-B',repo/'scripts/test_hepta_format_scope.py'])
run('native-build',[sys.executable,'-B',repo/'hia/build.py','--hepta-root',root/'hepta-0de','--output',output/'hia-native'])
run('unified-policy-prepare',[sys.executable,'-B',repo/'hia/prepare_unified_diff_policy.py','--repo',repo,'--rustc',env['RUSTC'],'--config',output/'unified-policy/config.json','--receipt-root',output/'unified-policy/receipts','--bind-input',output/'hia-native/build.json','--report',output/'unified-policy/configuration-report.json','--github-env',output/'github-env'])
print(json.dumps({'status':'passed','phase':'exact source, formatting, compiler generations, native build and policy setup','candidate':'ba4b4778d0b900c2259538b14b181e11dd39a3a7','output':str(output)}),flush=True)

