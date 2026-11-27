from pathlib import Path
import os,subprocess,json,time,hashlib,sys
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5');repo=root/'candidate';out=root/'complete-owner-ba4b'
env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',CARGO_NET_GIT_FETCH_WITH_CLI='true',CARGO_INCREMENTAL='0',CARGO_BUILD_JOBS='1',CARGO_PROFILE_DEV_DEBUG='0',CARGO_PROFILE_TEST_DEBUG='0',CARGO_TARGET_DIR=str(root/'target'),RUSTUP_TOOLCHAIN='1.96.1',RUSTC='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin/rustc',CODEX_HIA_NATIVE_LIB_DIR=str(out/'hia-native'),GIT_TERMINAL_PROMPT='0')
env['PATH']='/home/qian-qi/.rustup/toolchains/1.96.1-x86_64-unknown-linux-gnu/bin:/home/qian-qi/.cargo/bin:'+env.get('PATH','')
for line in (out/'github-env').read_text().splitlines():key,value=line.split('=',1);env[key]=value
argv=[sys.executable,'-B',str(repo/'hia/tests/test_native_template_parse_caller.py'),'--producer',str(repo),'--original-repo',str(root/'file-update-original'),'--library-dir',str(out/'hia-native'),'--rustc',env['RUSTC'],'--work-dir',str(out/'hia-template-caller-small-mmap'),'--report',str(out/'hia-template-caller-small-mmap.json')]
started=time.time();print(json.dumps({'state':'running','argv':argv}),flush=True)
log=out/'template-small-mmap.log'
with log.open('xb') as f:p=subprocess.run(argv,cwd=repo,env=env,stdout=f,stderr=subprocess.STDOUT)
raw=log.read_bytes();record={'argv':argv,'returncode':p.returncode,'started':started,'finished':time.time(),'log':str(log),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'resource_bound_unchanged':True,'git_only_config':{'core.packedGitWindowSize':'16m','core.packedGitLimit':'64m'}}
(out/'template-small-mmap-command.json').open('x').write(json.dumps(record,indent=2)+'\n')
print(raw[-12000:].decode('utf8','replace'),flush=True);print(json.dumps(record),flush=True);raise SystemExit(p.returncode)

