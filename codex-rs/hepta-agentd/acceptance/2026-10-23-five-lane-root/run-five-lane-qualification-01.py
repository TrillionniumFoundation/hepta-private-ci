import hashlib,json,os,pathlib,subprocess,time
base=pathlib.Path('/home/qian-qi/Documents/Codex/2026-10-23/https-github-com-trillionniumfoundation-trillionnium-os-3')
repo=base/'work/hepta-local-authority-closure';cwd=repo/'codex-rs';out=base/'work/local-authority-validation'
cache=json.loads((out/'root-service-196-cache-copy-01.json').read_text());target=pathlib.Path(cache['target'])
tool=pathlib.Path('/home/qian-qi/.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu/bin')
env=os.environ.copy();env.update(PATH=f'{tool}:/home/qian-qi/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin',RUSTUP_TOOLCHAIN='1.96.0',RUSTC=str(tool/'rustc'),CARGO_HOME='/home/qian-qi/.cargo',CARGO_TARGET_DIR=str(target),TMPDIR=cache['tmpdir'],CARGO_BUILD_JOBS='2',CARGO_NET_OFFLINE='true',RUSTY_V8_ARCHIVE='/data/hepta-dependency-v8-pair/rusty-v8-150.4.0-x86_64-unknown-linux-gnu/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz',RUSTY_V8_SRC_BINDING_PATH='/data/hepta-dependency-v8-pair/rusty-v8-150.4.0-x86_64-unknown-linux-gnu/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs')
for key in ['CARGO_PROFILE_DEV_DEBUG','CARGO_INCREMENTAL']:
 env.pop(key,None)
def sha(path):
 h=hashlib.sha256()
 with pathlib.Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=repo).decode().strip()
def snapshot():
 paths=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=repo).split(b'\0'); records=[]
 for raw in sorted(set(paths)):
  if not raw:continue
  p=repo/os.fsdecode(raw)
  if p.is_symlink():records.append([os.fsdecode(raw),'symlink',os.readlink(p)])
  elif p.is_file():records.append([os.fsdecode(raw),p.stat().st_size,sha(p)])
  else:records.append([os.fsdecode(raw),'absent'])
 return {'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'status':git('status','--porcelain=v1','--untracked-files=all'),'index_flags':sorted({line[0] for line in git('ls-files','-v').splitlines()}),'files':len(records),'live_source_sha256':hashlib.sha256(json.dumps(records,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()}
source=snapshot();(out/'five-lane-source-before-01.json').write_text(json.dumps(source,indent=2)+'\n')
def run(name,command,renv=env):
 start=time.monotonic()
 with (out/f'{name}.log').open('w') as f:r=subprocess.run(command,cwd=cwd,env=renv,stdout=f,stderr=subprocess.STDOUT)
 (out/f'{name}.json').write_text(json.dumps({'command':command,'exit':r.returncode,'seconds':time.monotonic()-start,'cache_reused':True,'source_before':source,'toolchain':'1.96.0'},indent=2)+'\n');print(name,r.returncode,flush=True)
 if r.returncode:raise SystemExit(r.returncode)
run('five-lane-private-contracts-cache-invalidation-01',[str(tool/'cargo'),'clean','-p','codex-hepta-contracts'])
run('five-lane-scope-tests-01',['/home/qian-qi/.cargo/bin/just','test','-p','codex-hepta-agentd','--lib','--locked','-E','test(deployment_) | test(authority_host_service) | test(authority_host_consumer_frontier) | test(authority_host_wire) | test(root_writer_proof) | test(production_composition::objective_sender_tests)','--test-threads','2'])
run('five-lane-cli-thin-build-01',[str(tool/'cargo'),'build','-p','codex-hepta-agentd','--bin','hepta-authority-host','--example','authority_host_peer_qualification','--locked'])
after=snapshot();(out/'five-lane-source-after-build-01.json').write_text(json.dumps(after,indent=2)+'\n');assert source==after,'source changed during qualification'
print('five-lane scope+build complete; actual Root SSD qualification is separate',flush=True)
